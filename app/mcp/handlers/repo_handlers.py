import json
import logging
from typing import List, Dict, Any, Optional, Annotated
from pydantic import Field

from app.services.database import get_db_connection, extract_host_from_url, get_adr, list_adrs, create_adr, update_adr, supersede_adr, upsert_adr
from app.services.search import execute_hybrid_search, trace_symbol_path
from app.services.indexing import get_dynamic_catalog_description, sync_single_git_repo, run_full_indexing
from app.services.vector_store import get_vector_store_config
from app.services.git_manager import format_git_permalink
from app.services.chunking import match_route_and_call, normalize_path_pattern
from app.models.schemas import SearchRequest, FindSymbolRequest, GetFileOutlineRequest, SyncRequest

logger = logging.getLogger("contextcortex")
import sys

def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


async def handle_list_repositories() -> str:
    """Lists all indexed local paths and remote Git repositories, including active branches, commit SHAs, and file counts."""
    try:
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            git_repos = conn.execute("SELECT id, name, url, branch, commit_sha, provider, auth_user, status, last_synced FROM git_repositories").fetchall()
            local_paths = conn.execute("SELECT path, repo, category FROM indexed_paths WHERE enabled = 1").fetchall()
            counts = conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()
            file_count_map = {c["repo"]: c["cnt"] for c in counts}

        out = "# Registered Sources & Repositories\n\n"
        if git_repos:
            out += "### Git Repositories\n"
            for gr in git_repos:
                fc = file_count_map.get(gr["name"], 0)
                sha = gr["commit_sha"][:8] if gr["commit_sha"] else "None"
                prov = (gr["provider"] or "git").upper()
                out += f"- **{gr['name']}** [{prov}] ({gr['url']} @ `{gr['branch']}` | SHA: `{sha}`) - Status: `{gr['status']}` | Files: {fc} | Last Synced: {gr['last_synced'] or 'Never'}\n"
            out += "\n"

        if local_paths:
            out += "### Local Monitored Paths\n"
            for lp in local_paths:
                fc = file_count_map.get(lp["repo"], 0)
                out += f"- **{lp['repo']}** (`{lp['path']}`) - Category: `{lp['category']}` | Files: {fc}\n"

        return out
    except Exception as e:
        return f"Error listing repositories: {str(e)}"


async def handle_sync_repository(
    repo: Annotated[Optional[str], Field(description="Repository name to sync (or omit to sync all).")] = None
) -> str:
    """Trigger an immediate re-fetch and re-indexing of a registered Git repo or local path."""
    target_repo = repo
    try:
        from app.services.indexing import sync_single_git_repo, run_full_indexing
        import threading
        if target_repo:
            with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
                row = conn.execute("SELECT id FROM git_repositories WHERE name = ?", (target_repo,)).fetchone()
            if row:
                threading.Thread(target=sync_single_git_repo, args=(row["id"],), daemon=True).start()
                return f"Triggered background sync for repo: '{target_repo}'"

        threading.Thread(target=run_full_indexing, daemon=True).start()
        return "Triggered full background re-indexing."
    except Exception as e:
        return f"Failed to trigger sync: {str(e)}"


async def handle_index_status() -> str:
    """Get global index health, vector counts, Git provider auth sources, and active embedding models."""
    try:
        from app.services.git_manager import check_github_rate_limit, mask_token
        from app.services.database import get_effective_git_token, list_git_host_credentials
        from app.services.embeddings import EMBEDDING_PROVIDER, DENSE_MODEL_NAME, SPARSE_MODEL_NAME

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            files_count = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]
            git_count = conn.execute("SELECT count(*) FROM git_repositories").fetchone()[0]

        vs_cfg = _get_tools_attr("get_vector_store_config", get_vector_store_config)()
        provider = vs_cfg.get("provider", "qdrant").upper()
        mode_val = vs_cfg.get("mode", "embedded")
        mode_str = "Remote" if mode_val == "remote" else "Embedded Disk"
        storage_loc = vs_cfg.get("url") if mode_val == "remote" else vs_cfg.get("storage_path")
        collection_name = vs_cfg.get("collection", "knowledge_rag_v1")
        stats = vs_cfg.get("stats", {})
        points_count = stats.get("points_count", 0)

        gh_tok, _, gh_src = get_effective_git_token("https://github.com", provider="github")
        gl_tok, _, gl_src = get_effective_git_token("https://gitlab.com", provider="gitlab")
        gt_tok, _, gt_src = get_effective_git_token("https://gitea.com", provider="gitea")
        vault_creds = list_git_host_credentials()
        rate_info = check_github_rate_limit(gh_tok)

        lines = [
            f"Vector Store Provider: {provider}",
            f"Storage Mode: {mode_str} ({mode_val})",
            f"Storage Location: {storage_loc}",
            f"Collection: {collection_name}",
            f"Total Vectors: {points_count}",
            f"Embedding Provider: {EMBEDDING_PROVIDER.upper()} ({DENSE_MODEL_NAME} + {SPARSE_MODEL_NAME})",
            f"Total Indexed Files: {files_count}",
            f"Total AST Symbols: {symbols_count}",
            f"Registered Git Repos: {git_count}",
            f"Git Auth Sources: GitHub ({gh_src}: {mask_token(gh_tok)}), GitLab ({gl_src}), Gitea ({gt_src}), Host Vaults ({len(vault_creds)})",
        ]
        if gh_tok:
            lines.append(f"GitHub API Rate Limit: {rate_info.get('remaining', 0)} / {rate_info.get('limit', 60)}")

        return "\n".join(lines)
    except Exception as e:
        return f"Failed to get status: {str(e)}"




async def handle_catalog_summary() -> str:
    """Catalog of indexed repositories, documentation files, and AST symbol distributions."""
    try:
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            git_repos = conn.execute("SELECT name, url, branch, commit_sha, status, last_synced FROM git_repositories").fetchall()
            files = conn.execute("SELECT filepath, repo, doc_type, language FROM indexed_files").fetchall()
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]

        md = "# Repository & Documentation Catalog\n\n"
        md += f"**Total Files Indexed:** {len(files)} | **Total AST Code Symbols:** {symbols_count}\n\n"

        if git_repos:
            md += "## Registered Git Repositories\n\n"
            md += "| Name | URL | Branch | Commit SHA | Status | Last Synced |\n"
            md += "| --- | --- | --- | --- | --- | --- |\n"
            for gr in git_repos:
                sha_short = gr["commit_sha"][:8] if gr["commit_sha"] else "-"
                md += f"| {gr['name']} | {gr['url']} | {gr['branch']} | `{sha_short}` | {gr['status']} | {gr['last_synced'] or '-'} |\n"
            md += "\n"

        md += "## Indexed File Overview\n\n"
        md += "| Repository | File | Type | Language |\n"
        md += "| --- | --- | --- | --- |\n"
        for f in files[:40]:
            md += f"| {f['repo']} | {f['filepath']} | {f['doc_type']} | {f['language']} |\n"
        if len(files) > 40:
            md += f"\n*...and {len(files) - 40} more files.*"
        return md
    except Exception as e:
        return f"Error generating catalog resource: {str(e)}"


def handle_search_infrastructure_docs(
    topic: Annotated[str, Field(description="The specific infrastructure topic to search for")]
) -> str:
    """Workflow to search system infrastructure documentation, container mappings, or network routes."""
    return f"Please perform a search using the search_docs tool for topic '{topic}' and summarize the matching container mappings, port numbers, reverse proxy routes, or setup instructions."



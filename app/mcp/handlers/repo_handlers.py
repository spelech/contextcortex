import json
import logging
from typing import List, Dict, Any, Optional, Annotated
from pydantic import Field

from app.services.database import get_db_connection, extract_host_from_url, get_adr, list_adrs, create_adr, update_adr, supersede_adr, upsert_adr
from app.services.search import execute_hybrid_search, trace_symbol_path
from app.services.indexing import get_dynamic_catalog_description, sync_single_git_repo, run_full_indexing
from app.services.vector_store import get_vector_store_config
from app.services.git_manager import format_git_permalink, format_git_commit_url
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
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            git_repos = conn.execute("SELECT id, name, url, branch, commit_sha, provider, auth_user, status, last_synced FROM git_repositories").fetchall()
            local_paths = conn.execute("SELECT path, repo, category FROM indexed_paths WHERE enabled = 1").fetchall()
            counts = conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()
            file_count_map = {c["repo"]: c["cnt"] for c in counts}

        repos_list = []
        for gr in git_repos:
            repos_list.append({
                "id": gr["id"],
                "name": gr["name"],
                "url": gr["url"],
                "branch": gr["branch"],
                "commit_sha": gr["commit_sha"],
                "provider": (gr["provider"] or "git").lower(),
                "status": gr["status"],
                "files": file_count_map.get(gr["name"], 0),
                "last_synced": gr["last_synced"],
            })

        monitored_list = []
        for lp in local_paths:
            monitored_list.append({
                "repo": lp["repo"],
                "path": lp["path"],
                "category": lp["category"],
                "files": file_count_map.get(lp["repo"], 0),
            })

        return json.dumps({
            "git_repositories": repos_list,
            "local_paths": monitored_list,
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_list_repositories: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        return json.dumps({"error": f"Error listing repositories: {str(e)}"})


async def handle_sync_repository(
    repo: Annotated[Optional[str], Field(description="Repository name to sync (or omit to sync all).")] = None
) -> str:
    """Trigger an immediate re-fetch and re-indexing of a registered Git repo or local path."""
    target_repo = repo
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.EDITOR)
        from app.services.indexing import sync_single_git_repo, run_full_indexing
        import threading
        if target_repo:
            with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
                row = conn.execute("SELECT id FROM git_repositories WHERE name = ?", (target_repo,)).fetchone()
            if row:
                threading.Thread(target=sync_single_git_repo, args=(row["id"],), daemon=True).start()
                return json.dumps({
                    "status": "triggered",
                    "scope": "repository",
                    "repo": target_repo,
                    "message": f"Triggered background sync for repo: '{target_repo}'",
                })

        threading.Thread(target=run_full_indexing, daemon=True).start()
        return json.dumps({
            "status": "triggered",
            "scope": "full",
            "repo": target_repo,
            "message": "Triggered full background re-indexing.",
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_sync_repository: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        return json.dumps({"error": f"Failed to trigger sync: {str(e)}"})


async def handle_index_status() -> str:
    """Get global index health, vector counts, Git provider auth sources, and active embedding models."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)
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
        vault_failed = False
        try:
            vault_creds = list_git_host_credentials()
        except Exception as e:
            logger.error(f"Failed to list vault credentials for status: {e}")
            vault_creds = []
            vault_failed = True
        rate_info = check_github_rate_limit(gh_tok)

        vault_status = "[Unavailable - Query Failed]" if vault_failed else len(vault_creds)
        payload: Dict[str, Any] = {
            "vector_store": {
                "provider": provider,
                "mode": mode_val,
                "mode_label": mode_str,
                "location": storage_loc,
                "collection": collection_name,
                "total_vectors": points_count,
            },
            "embeddings": {
                "provider": EMBEDDING_PROVIDER.upper(),
                "dense_model": DENSE_MODEL_NAME,
                "sparse_model": SPARSE_MODEL_NAME,
            },
            "counts": {
                "indexed_files": files_count,
                "ast_symbols": symbols_count,
                "git_repositories": git_count,
            },
            "git_auth": {
                "github": {"source": gh_src, "token": mask_token(gh_tok)},
                "gitlab": {"source": gl_src},
                "gitea": {"source": gt_src},
                "host_vaults": vault_status,
            },
        }
        if gh_tok:
            payload["github_rate_limit"] = {
                "remaining": rate_info.get("remaining", 0),
                "limit": rate_info.get("limit", 60),
            }

        return json.dumps(payload)
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_index_status: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        return json.dumps({"error": f"Failed to get status: {str(e)}"})


async def handle_catalog_summary() -> str:
    """Catalog of indexed repositories, documentation files, and AST symbol distributions."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            git_repos = conn.execute("SELECT name, url, branch, commit_sha, status, last_synced FROM git_repositories").fetchall()
            files = conn.execute("SELECT filepath, repo, doc_type, language FROM indexed_files").fetchall()
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]

        repos_data = []
        for gr in git_repos:
            repos_data.append({
                "name": gr["name"],
                "url": gr["url"],
                "branch": gr["branch"],
                "commit_sha": gr["commit_sha"],
                "status": gr["status"],
                "last_synced": gr["last_synced"],
            })

        files_data = []
        for f in files[:40]:
            fp = f["filepath"]
            clean_fp = fp.split("://", 1)[1] if "://" in fp else fp
            files_data.append({
                "repo": f["repo"],
                "file": clean_fp,
                "doc_type": f["doc_type"],
                "language": f["language"],
            })

        return json.dumps({
            "total_files": len(files),
            "total_symbols": symbols_count,
            "git_repositories": repos_data,
            "files": files_data,
            "truncated_files": max(0, len(files) - 40),
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_catalog_summary: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        return json.dumps({"error": f"Error generating catalog resource: {str(e)}"})


def handle_search_infrastructure_docs(
    topic: Annotated[str, Field(description="The specific infrastructure topic to search for")]
) -> str:
    """Workflow to search system infrastructure documentation, container mappings, or network routes."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "search_infrastructure_docs",
        "topic": topic,
        "instructions": f"Perform a search using the search_docs tool for topic '{topic}' and summarize the matching container mappings, port numbers, reverse proxy routes, or setup instructions.",
    })


async def handle_get_recent_changes(
    repo: Annotated[str, Field(description="Repository name to inspect recent commits for.")],
    filepath: Annotated[Optional[str], Field(description="Optional relative file path filter to only return commits touching this file.")] = None,
    symbol: Annotated[Optional[str], Field(description="Optional AST symbol name; resolves symbol's file path and filters commits touching that file.")] = None,
    limit: Annotated[int, Field(description="Max commits to return (default 10, max 50).")] = 10,
) -> str:
    """Returns recent commit history for a repository, optionally filtered by file path or symbol name."""
    try:
        from app.services.auth import enforce_tool_permission, Role
        enforce_tool_permission(Role.VIEWER)

        safe_limit = max(1, min(limit if limit is not None else 10, 50))

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            repo_row = conn.execute(
                "SELECT id, name, url, provider, retain_commits_count FROM git_repositories WHERE name = ?",
                (repo,)
            ).fetchone()

            retained_limit = (
                int(repo_row["retain_commits_count"])
                if repo_row and "retain_commits_count" in repo_row.keys() and repo_row["retain_commits_count"] is not None
                else 20
            )

            # Check if repository has commits in git_commits
            stored_count = 0
            if repo_row:
                count_row = conn.execute("SELECT count(*) as c FROM git_commits WHERE repo = ?", (repo,)).fetchone()
                stored_count = count_row["c"] if count_row else 0

            # If retain_commits_count == 0 or no commits are stored
            if not repo_row or retained_limit == 0 or stored_count == 0:
                fallback_resp = {
                    "repo": repo,
                    "retained": False,
                    "retained_limit": retained_limit if repo_row else 0,
                    "commits": [],
                    "message": f"Commit history is not retained for repository '{repo}' (retain_commits_count={retained_limit if repo_row else 0}). Retrieve commit history directly from the Git repository."
                }
                return json.dumps(fallback_resp, separators=(",", ":"))

            git_url = repo_row["url"]
            provider = repo_row["provider"]

            # Resolve filter filepath
            target_filepath = None
            if filepath and filepath.strip():
                clean_fp = filepath.strip().lstrip("/")
                target_filepath = clean_fp
            elif symbol and symbol.strip():
                sym_row = conn.execute(
                    "SELECT filepath FROM ast_symbols WHERE repo = ? AND (name = ? OR full_symbol = ?) LIMIT 1",
                    (repo, symbol.strip(), symbol.strip())
                ).fetchone()
                if sym_row:
                    raw_fp = sym_row["filepath"]
                    if "://" in raw_fp:
                        target_filepath = raw_fp.split("://", 1)[1]
                    else:
                        target_filepath = raw_fp

            # Query commits from git_commits
            rows = conn.execute(
                "SELECT commit_sha, author, committed_at, message, files_changed FROM git_commits WHERE repo = ? ORDER BY committed_at DESC, id DESC",
                (repo,)
            ).fetchall()

            matched_commits = []
            for r in rows:
                files_raw = r["files_changed"]
                try:
                    files_list = json.loads(files_raw) if files_raw else []
                except Exception:
                    files_list = []

                if target_filepath:
                    norm_target = target_filepath.replace("\\", "/").lstrip("/")
                    matched = False
                    for f in files_list:
                        norm_f = f.replace("\\", "/").lstrip("/")
                        if norm_f == norm_target or norm_f.endswith("/" + norm_target) or norm_target.endswith("/" + norm_f):
                            matched = True
                            break
                    if not matched:
                        continue

                commit_url = format_git_commit_url(git_url, r["commit_sha"], provider=provider)
                matched_commits.append({
                    "sha": r["commit_sha"],
                    "short_sha": r["commit_sha"][:7],
                    "author": r["author"],
                    "date": r["committed_at"],
                    "message": r["message"],
                    "files_changed": files_list,
                    "commit_url": commit_url,
                })

                if len(matched_commits) >= safe_limit:
                    break

            result = {
                "repo": repo,
                "retained_limit": retained_limit,
                "commits": matched_commits,
            }
            if target_filepath:
                result["filter_filepath"] = target_filepath

            return json.dumps(result, separators=(",", ":"))

    except Exception as e:
        logger.error(f"Error in handle_get_recent_changes: {e}")
        return json.dumps({"error": str(e), "repo": repo, "commits": []}, separators=(",", ":"))

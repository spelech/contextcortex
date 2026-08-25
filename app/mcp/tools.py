import json
import logging
from typing import List, Dict, Any, Optional, Annotated
from pydantic import Field

from app.services.db import get_db_connection, extract_host_from_url
from app.services.search import execute_hybrid_search
from app.services.indexer import get_dynamic_catalog_description
from app.services.vector_store import get_vector_store_config
from app.services.git_manager import format_git_permalink
from app.services.chunker import match_route_and_call, normalize_path_pattern
from app.models.schemas import SearchRequest, FindSymbolRequest, GetFileOutlineRequest, SyncRequest

logger = logging.getLogger("contextcortex")




# --- Core Tool Handlers ---

async def handle_search_code(
    query: Annotated[str, Field(description="Natural language question or code concept (e.g. 'JWT token authentication handler').")],
    repo: Annotated[Optional[str], Field(description="Optional repository name/alias to filter by.")] = None,
    language: Annotated[Optional[str], Field(description="Optional language filter (e.g. 'python', 'typescript', 'go').")] = None,
    limit: Annotated[int, Field(description="Max number of code blocks to return (default 5).")] = 5
) -> str:
    """Hybrid semantic and BM25 search over code functions, classes, and logic snippets with line numbers and GitHub links."""
    query = query.strip() if query else ""
    if not query:
        return "Error: search query cannot be empty."

    try:
        hits = execute_hybrid_search(query_text=query, doc_type="code", repo=repo, language=language, limit=limit)
        if not hits:
            return f"No matching code snippets found for query: '{query}'."

        formatted = []
        for hit in hits:
            p = hit.payload
            header = f"### [{p.get('repo')}] {p.get('rel_path')} (Lines {p.get('start_line')}-{p.get('end_line')})"
            if p.get("symbol"):
                header += f" - Symbol: `{p.get('symbol')}`"
            link_url = p.get("permalink_url") or p.get("github_url")
            if link_url:
                header += f"\nSource Link: {link_url}"
            header += f"\nRRF Score: {hit.score:.4f}\n"

            lang = p.get("language", "")
            block = f"{header}```{lang}\n{p.get('content')}\n```"
            formatted.append(block)

        return "\n\n========================\n\n".join(formatted)
    except Exception as e:
        logger.error(f"search_code failed: {e}")
        return f"Error executing code search: {str(e)}"


async def handle_search_docs(
    query: Annotated[str, Field(description="Search query or documentation topic.")],
    repo: Annotated[Optional[str], Field(description="Optional repository/vault filter.")] = None,
    category: Annotated[Optional[str], Field(description="Optional category filter.")] = None,
    tag: Annotated[Optional[str], Field(description="Optional tag filter.")] = None,
    limit: Annotated[int, Field(description="Max documents to return (default 5).")] = 5
) -> str:
    """Hybrid search across system documentation, markdown notes, architectural decisions, and runbooks."""
    query = query.strip() if query else ""
    if not query:
        return "Error: search query cannot be empty."

    try:
        hits = execute_hybrid_search(query_text=query, doc_type="doc", repo=repo, category=category, tag=tag, limit=limit)
        if not hits:
            return f"No matching documentation found for query: '{query}'."

        formatted = []
        for hit in hits:
            p = hit.payload
            tags_str = ", ".join(p.get("tags", []))
            header = f"### [{p.get('repo')}] {p.get('rel_path')}"
            if p.get("heading") and p.get("heading") != "Root":
                header += f" -> {p.get('heading')}"
            if tags_str:
                header += f"\nTags: {tags_str}"
            link_url = p.get("permalink_url") or p.get("github_url")
            if link_url:
                header += f"\nSource Link: {link_url}"
            header += f"\nRRF Score: {hit.score:.4f}\n"

            block = f"{header}---\n{p.get('content')}"
            formatted.append(block)


        return "\n\n========================\n\n".join(formatted)
    except Exception as e:
        logger.error(f"search_docs failed: {e}")
        return f"Error executing doc search: {str(e)}"


async def handle_find_symbol(
    name: Annotated[str, Field(description="Symbol name (e.g. 'extract_symbols_and_chunks' or 'FastAPI').")],
    repo: Annotated[Optional[str], Field(description="Optional repository filter.")] = None,
    exact: Annotated[bool, Field(description="If true, matches exact name. If false, prefix/fuzzy matches.")] = True,
    limit: Annotated[int, Field(description="Max results (default 10).")] = 10
) -> str:
    """Instant exact or prefix symbol lookup (functions, classes, structs, interfaces) from AST index without broad token scans."""
    sym_name = name.strip() if name else ""
    if not sym_name:
        return "Error: symbol name cannot be empty."

    try:
        with get_db_connection() as conn:
            query = "SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols WHERE "
            params = []
            if exact:
                query += "(name = ? OR full_symbol = ?)"
                params.extend([sym_name, sym_name])
            else:
                query += "(name LIKE ? OR full_symbol LIKE ?)"
                params.extend([f"%{sym_name}%", f"%{sym_name}%"])

            if repo:
                query += " AND repo = ?"
                params.append(repo)

            query += f" LIMIT {limit}"
            rows = conn.execute(query, params).fetchall()

        if not rows:
            return f"No symbols found matching '{sym_name}'."

        lines = [f"Found {len(rows)} matching symbols for '{sym_name}':\n"]
        for r in rows:
            lines.append(
                f"- **{r['name']}** (`{r['kind']}`) in `[{r['repo']}] {r['filepath']}` (Lines {r['start_line']}-{r['end_line']})\n"
                f"  Signature: `{r['signature']}`"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"find_symbol error: {e}")
        return f"Error finding symbol: {str(e)}"


async def handle_find_routes(
    query: Annotated[Optional[str], Field(description="Path substring or pattern (e.g. '/api/v1/users' or 'checkout').")] = None,
    method: Annotated[Optional[str], Field(description="Filter by HTTP method (GET, POST, PUT, DELETE, etc.).")] = None,
    repo: Annotated[Optional[str], Field(description="Filter by repository name.")] = None,
    limit: Annotated[int, Field(description="Maximum routes to return (default 20).")] = 20
) -> str:
    """List or search API endpoints and HTTP route handlers across registered repositories."""
    try:
        with get_db_connection() as conn:
            sql = "SELECT r.id, r.repo, r.filepath, r.framework, r.http_method, r.path_pattern, r.handler_symbol, r.start_line, r.end_line, g.url as git_url, g.commit_sha, g.provider FROM api_routes r LEFT JOIN git_repositories g ON r.repo = g.name WHERE 1=1"
            params: List[Any] = []

            if query and query.strip():
                clean_q = query.strip()
                sql += " AND (r.path_pattern LIKE ? OR r.handler_symbol LIKE ?)"
                params.extend([f"%{clean_q}%", f"%{clean_q}%"])

            if method and method.strip():
                sql += " AND (UPPER(r.http_method) = ? OR UPPER(r.http_method) = 'ALL')"
                params.append(method.strip().upper())

            if repo and repo.strip():
                sql += " AND r.repo = ?"
                params.append(repo.strip())

            sql += f" ORDER BY r.repo ASC, r.path_pattern ASC LIMIT {limit}"
            rows = conn.execute(sql, params).fetchall()

        if not rows:
            return f"No API routes found matching query: '{query or ''}'."

        lines = [f"Found {len(rows)} matching API endpoints:\n"]
        for r in rows:
            rel_path = r["filepath"].split("://", 1)[1] if "://" in r["filepath"] else r["filepath"]
            permalink = format_git_permalink(r["git_url"], r["commit_sha"], rel_path, r["start_line"], r["end_line"], provider=r["provider"])
            handler_str = f" Handler: `{r['handler_symbol']}`" if r["handler_symbol"] else ""
            lines.append(
                f"- **[{r['http_method']}] `{r['path_pattern']}`** ({r['framework']}) in `[{r['repo']}] {rel_path}` (Lines {r['start_line']}-{r['end_line']}){handler_str}\n"
                f"  Permalink: {permalink}"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"find_routes failed: {e}")
        return f"Error searching API routes: {str(e)}"


async def handle_find_api_callers(
    path: Annotated[str, Field(description="Endpoint path pattern or URL segment to match (e.g. '/users/{id}' or '/auth/login').")],
    method: Annotated[Optional[str], Field(description="Target HTTP method (GET, POST, etc.).")] = None,
    repo: Annotated[Optional[str], Field(description="Filter client search by repository.")] = None
) -> str:
    """Find client call sites and services that invoke a specific API endpoint or URL pattern."""
    target_path = path.strip() if path else ""
    if not target_path:
        return "Error: endpoint path cannot be empty."

    try:
        with get_db_connection() as conn:
            sql = "SELECT c.id, c.repo, c.filepath, c.http_method, c.url_pattern, c.caller_symbol, c.line_number, g.url as git_url, g.commit_sha, g.provider FROM api_client_calls c LEFT JOIN git_repositories g ON c.repo = g.name WHERE 1=1"
            params: List[Any] = []

            if repo and repo.strip():
                sql += " AND c.repo = ?"
                params.append(repo.strip())

            rows = conn.execute(sql, params).fetchall()

        matching_calls = []
        target_method_clean = method.strip().upper() if method and method.strip() else None

        for r in rows:
            call_method = (r["http_method"] or "").upper()
            if target_method_clean and call_method and call_method != "ALL" and call_method != target_method_clean:
                continue

            if match_route_and_call(target_path, r["url_pattern"]):
                matching_calls.append(r)

        if not matching_calls:
            return f"No client call sites found invoking endpoint pattern: '{target_path}'."

        lines = [f"Found {len(matching_calls)} call sites invoking endpoint `{target_path}`:\n"]
        for c in matching_calls:
            rel_path = c["filepath"].split("://", 1)[1] if "://" in c["filepath"] else c["filepath"]
            permalink = format_git_permalink(c["git_url"], c["commit_sha"], rel_path, c["line_number"], c["line_number"], provider=c["provider"])
            caller_str = f" Caller: `{c['caller_symbol']}`" if c["caller_symbol"] else ""
            method_str = f"[{c['http_method']}] " if c["http_method"] else ""
            lines.append(
                f"- **{method_str}`{c['url_pattern']}`** in `[{c['repo']}] {rel_path}` (Line {c['line_number']}){caller_str}\n"
                f"  Permalink: {permalink}"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"find_api_callers failed: {e}")
        return f"Error searching API callers: {str(e)}"


async def handle_get_file_outline(
    filepath: Annotated[str, Field(description="File path (e.g. 'src/server.py' or 'repo_name://src/server.py').")],
    repo: Annotated[Optional[str], Field(description="Repository identifier (optional).")] = None
) -> str:
    """Get the AST outline (classes, methods, functions, line numbers) of a file without retrieving its entire token body."""
    fp = filepath.strip() if filepath else ""
    try:
        with get_db_connection() as conn:
            if repo:
                rows = conn.execute(
                    "SELECT name, full_symbol, kind, start_line, end_line, signature FROM ast_symbols WHERE (filepath = ? OR filepath LIKE ?) AND repo = ? ORDER BY start_line ASC",
                    (fp, f"%{fp}", repo)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature FROM ast_symbols WHERE filepath = ? OR filepath LIKE ? ORDER BY start_line ASC",
                    (fp, f"%{fp}")
                ).fetchall()

        if not rows:
            return f"No outline available for '{fp}'."

        outline_text = f"# File Outline: {fp}\n\n"
        for r in rows:
            outline_text += f"- **{r['name']}** ({r['kind']}, lines {r['start_line']}-{r['end_line']}): `{r['signature']}`\n"
        return outline_text
    except Exception as e:
        return f"Failed to get outline: {str(e)}"


async def handle_list_repositories() -> str:
    """Lists all indexed local paths and remote Git repositories, including active branches, commit SHAs, and file counts."""
    try:
        with get_db_connection() as conn:
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
        from app.services.indexer import sync_single_git_repo, run_full_indexing
        import threading
        if target_repo:
            with get_db_connection() as conn:
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
        from app.services.db import get_effective_git_token, list_git_host_credentials
        from app.services.embeddings import EMBEDDING_PROVIDER, DENSE_MODEL_NAME, SPARSE_MODEL_NAME

        with get_db_connection() as conn:
            files_count = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]
            git_count = conn.execute("SELECT count(*) FROM git_repositories").fetchone()[0]

        vs_cfg = get_vector_store_config()
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
        with get_db_connection() as conn:
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


def handle_find_implementation_symbol(
    symbol: Annotated[str, Field(description="Function or class name to find")],
    repo: Annotated[Optional[str], Field(description="Target repository (optional)")] = None
) -> str:
    """Workflow to locate functions, classes, and logic across registered codebases."""
    return f"Please use find_symbol for '{symbol}' in repo '{repo}' and inspect its declaration, line numbers, and implementation details."


# --- Registration on FastMCP Server ---

def register_mcp_tools_and_resources(server=None):
    """Register all 7 tools, resources, and prompts onto the FastMCP server instance."""
    if server is None:
        from app.mcp.mcp_server import mcp_server
        server = mcp_server

    existing_tools = {t.name for t in server._tool_manager.list_tools()}

    if "search_code" not in existing_tools:
        server.tool(
            name="search_code",
            description="Hybrid semantic and BM25 search over code functions, classes, and logic snippets with line numbers and GitHub links."
        )(handle_search_code)

    if "search_docs" not in existing_tools:
        server.tool(
            name="search_docs",
            description="Hybrid search across system documentation, markdown notes, architectural decisions, and runbooks."
        )(handle_search_docs)

    if "find_symbol" not in existing_tools:
        server.tool(
            name="find_symbol",
            description="Instant exact or prefix symbol lookup (functions, classes, structs, interfaces) from AST index without broad token scans."
        )(handle_find_symbol)

    if "find_routes" not in existing_tools:
        server.tool(
            name="find_routes",
            description="List or search API endpoints and HTTP route handlers across registered repositories."
        )(handle_find_routes)

    if "find_api_callers" not in existing_tools:
        server.tool(
            name="find_api_callers",
            description="Find client call sites and services that invoke a specific API endpoint or URL pattern."
        )(handle_find_api_callers)

    if "get_file_outline" not in existing_tools:
        server.tool(
            name="get_file_outline",
            description="Get the AST outline (classes, methods, functions, line numbers) of a file without retrieving its entire token body."
        )(handle_get_file_outline)

    if "list_repositories" not in existing_tools:
        server.tool(
            name="list_repositories",
            description="Lists all indexed local paths and remote Git repositories, including active branches, commit SHAs, and file counts."
        )(handle_list_repositories)

    if "sync_repository" not in existing_tools:
        server.tool(
            name="sync_repository",
            description="Trigger an immediate re-fetch and re-indexing of a registered Git repo or local path."
        )(handle_sync_repository)

    if "index_status" not in existing_tools:
        server.tool(
            name="index_status",
            description="Get global index health, vector counts, Git provider auth sources, and active embedding models."
        )(handle_index_status)

    existing_resources = {str(r.uri) for r in server._resource_manager.list_resources()}
    if "knowledge://catalog/summary" not in existing_resources:
        server.resource(
            "knowledge://catalog/summary",
            name="knowledge_catalog_summary",
            description="Catalog of indexed repositories, documentation files, and AST symbol distributions.",
            mime_type="text/markdown"
        )(handle_catalog_summary)

    existing_prompts = {p.name for p in server._prompt_manager.list_prompts()}
    if "search_infrastructure_docs" not in existing_prompts:
        server.prompt(
            name="search_infrastructure_docs",
            description="Workflow to search system infrastructure documentation, container mappings, or network routes."
        )(handle_search_infrastructure_docs)

    if "find_implementation_symbol" not in existing_prompts:
        server.prompt(
            name="find_implementation_symbol",
            description="Workflow to locate functions, classes, and logic across registered codebases."
        )(handle_find_implementation_symbol)

    return server


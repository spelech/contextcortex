import json
import logging
from typing import List, Dict, Any, Optional, Annotated
from pydantic import Field
from mcp.types import Tool, TextContent, Resource, Prompt, PromptMessage, PromptArgument

from app.services.db import get_db_connection
from app.services.search import execute_hybrid_search
from app.services.indexer import get_dynamic_catalog_description
from app.models.schemas import SearchRequest, FindSymbolRequest, GetFileOutlineRequest, SyncRequest

logger = logging.getLogger("notes-rag-mcp")


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
            if p.get("github_url"):
                header += f"\nGitHub Link: {p.get('github_url')}"
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
            if p.get("github_url"):
                header += f"\nGitHub Link: {p.get('github_url')}"
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
    """Get global index health, vector counts, GitHub rate limits, and active embedding models."""
    try:
        from app.services.git_manager import check_github_rate_limit, mask_token
        from app.services.db import get_effective_github_token, get_token_source
        from app.services.embeddings import EMBEDDING_PROVIDER, DENSE_MODEL_NAME, SPARSE_MODEL_NAME
        from app.services.indexer import COLLECTION_NAME, qdrant

        with get_db_connection() as conn:
            files_count = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]
            git_count = conn.execute("SELECT count(*) FROM git_repositories").fetchone()[0]

        points_count = 0
        if qdrant.collection_exists(COLLECTION_NAME):
            info = qdrant.get_collection(COLLECTION_NAME)
            points_count = info.points_count

        eff_token = get_effective_github_token()
        rate_info = check_github_rate_limit(eff_token)

        status_text = (
            f"Collection: {COLLECTION_NAME}\n"
            f"Embedding Provider: {EMBEDDING_PROVIDER.upper()} ({DENSE_MODEL_NAME} + {SPARSE_MODEL_NAME})\n"
            f"Total Hybrid Vectors: {points_count}\n"
            f"Total Indexed Files: {files_count}\n"
            f"Total AST Symbols: {symbols_count}\n"
            f"Registered Git Repos: {git_count}\n"
            f"GitHub Token Source: {get_token_source()} (Masked: {mask_token(eff_token)})\n"
            f"GitHub API Rate Limit: {rate_info.get('remaining', 0)} / {rate_info.get('limit', 60)}"
        )
        return status_text
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
            description="Get global index health, vector counts, GitHub rate limits, and active embedding models."
        )(handle_index_status)

    existing_resources = {str(r.uri) for r in server._resource_manager.list_resources()}
    if "notes://catalog/summary" not in existing_resources:
        server.resource(
            "notes://catalog/summary",
            name="catalog_summary",
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


# --- Backward Compatibility Helpers ---

async def execute_tool(name: str, arguments: dict) -> List[TextContent]:
    """Backward compatibility wrapper for calling tools directly."""
    if name == "search_code":
        res = await handle_search_code(**arguments)
    elif name == "search_docs":
        res = await handle_search_docs(**arguments)
    elif name == "find_symbol":
        res = await handle_find_symbol(**arguments)
    elif name == "get_file_outline":
        res = await handle_get_file_outline(**arguments)
    elif name == "list_repositories":
        res = await handle_list_repositories()
    elif name == "sync_repository":
        res = await handle_sync_repository(**arguments)
    elif name == "index_status":
        res = await handle_index_status()
    else:
        raise ValueError(f"Unknown tool: {name}")

    return [TextContent(type="text", text=res)]


async def read_resource(uri: str) -> str:
    """Backward compatibility wrapper for reading resources directly."""
    if uri == "notes://catalog/summary":
        return await handle_catalog_summary()
    raise ValueError(f"Unknown resource URI: {uri}")


async def get_tools() -> List[Tool]:
    """Backward compatibility helper for listing tools as Tool objects."""
    catalog_desc = get_dynamic_catalog_description()
    return [
        Tool(
            name="search_code",
            description=f"Hybrid semantic and BM25 search over code functions, classes, and logic snippets with line numbers and GitHub links. {catalog_desc}",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language question or code concept (e.g. 'JWT token authentication handler')."},
                    "repo": {"type": "string", "description": "Optional repository name/alias to filter by."},
                    "language": {"type": "string", "description": "Optional language filter (e.g. 'python', 'typescript', 'go')."},
                    "limit": {"type": "integer", "description": "Max number of code blocks to return (default 5).", "default": 5}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="search_docs",
            description=f"Hybrid search across system documentation, markdown notes, architectural decisions, and runbooks. {catalog_desc}",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query or documentation topic."},
                    "repo": {"type": "string", "description": "Optional repository/vault filter."},
                    "category": {"type": "string", "description": "Optional category filter."},
                    "tag": {"type": "string", "description": "Optional tag filter."},
                    "limit": {"type": "integer", "description": "Max documents to return (default 5).", "default": 5}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="find_symbol",
            description="Instant exact or prefix symbol lookup (functions, classes, structs, interfaces) from AST index without broad token scans.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Symbol name (e.g. 'extract_symbols_and_chunks' or 'FastAPI')."},
                    "repo": {"type": "string", "description": "Optional repository filter."},
                    "exact": {"type": "boolean", "description": "If true, matches exact name. If false, prefix/fuzzy matches.", "default": True},
                    "limit": {"type": "integer", "description": "Max results (default 10).", "default": 10}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="get_file_outline",
            description="Get the AST outline (classes, methods, functions, line numbers) of a file without retrieving its entire token body.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "File path (e.g. 'src/server.py' or 'repo_name://src/server.py')."},
                    "repo": {"type": "string", "description": "Repository identifier (optional)."}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="list_repositories",
            description="Lists all indexed local paths and remote Git repositories, including active branches, commit SHAs, and file counts.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="sync_repository",
            description="Trigger an immediate re-fetch and re-indexing of a registered Git repo or local path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository name to sync (or omit to sync all)."}
                }
            }
        ),
        Tool(
            name="index_status",
            description="Get global index health, vector counts, GitHub rate limits, and active embedding models.",
            inputSchema={"type": "object", "properties": {}}
        )
    ]


async def get_resources() -> List[Resource]:
    """Backward compatibility helper for listing resources."""
    return [
        Resource(
            uri="notes://catalog/summary",
            name="Repository & Documentation Topic Catalog",
            description="Catalog of indexed repositories, documentation files, and AST symbol distributions.",
            mimeType="text/markdown"
        )
    ]


async def get_prompts() -> List[Prompt]:
    """Backward compatibility helper for listing prompts."""
    prompts = []
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT name, description, arguments_json FROM custom_prompts ORDER BY name ASC").fetchall()
        for r in rows:
            args_list = []
            if r["arguments_json"]:
                try:
                    for a in json.loads(r["arguments_json"]):
                        args_list.append(PromptArgument(
                            name=a.get("name", ""),
                            description=a.get("description", ""),
                            required=a.get("required", False)
                        ))
                except Exception:
                    pass
            prompts.append(Prompt(name=r["name"], description=r["description"], arguments=args_list))
    except Exception as e:
        logger.error(f"Error listing prompts: {e}")
    return prompts


async def get_prompt(name: str, arguments: dict = None) -> List[PromptMessage]:
    """Backward compatibility helper for resolving prompts."""
    arguments = arguments or {}
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT template FROM custom_prompts WHERE name = ?", (name,)).fetchone()
        if not row:
            raise ValueError(f"Unknown prompt: {name}")
        formatted = row["template"]
        for k, v in arguments.items():
            formatted = formatted.replace(f"{{{k}}}", str(v))
        return [PromptMessage(role="user", content=TextContent(type="text", text=formatted))]
    except Exception as e:
        raise ValueError(f"Failed to get prompt '{name}': {e}")

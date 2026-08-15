import json
import logging
from typing import List, Dict, Any
from mcp.types import Tool, TextContent, Resource, Prompt, PromptMessage, PromptArgument

from app.services.db import get_db_connection
from app.services.search import execute_hybrid_search
from app.services.indexer import get_dynamic_catalog_description

logger = logging.getLogger("notes-rag-mcp")

async def get_tools() -> List[Tool]:
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

async def execute_tool(name: str, arguments: dict) -> List[TextContent]:
    if name == "search_code":
        query = arguments.get("query", "").strip()
        repo = arguments.get("repo")
        language = arguments.get("language")
        limit = arguments.get("limit", 5)

        if not query:
            return [TextContent(type="text", text="Error: search query cannot be empty.")]

        try:
            hits = execute_hybrid_search(query_text=query, doc_type="code", repo=repo, language=language, limit=limit)
            if not hits:
                return [TextContent(type="text", text=f"No matching code snippets found for query: '{query}'.")]

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

            return [TextContent(type="text", text="\n\n========================\n\n".join(formatted))]
        except Exception as e:
            logger.error(f"search_code failed: {e}")
            return [TextContent(type="text", text=f"Error executing code search: {str(e)}")]

    elif name == "search_docs":
        query = arguments.get("query", "").strip()
        repo = arguments.get("repo")
        category = arguments.get("category")
        tag = arguments.get("tag")
        limit = arguments.get("limit", 5)

        if not query:
            return [TextContent(type="text", text="Error: search query cannot be empty.")]

        try:
            hits = execute_hybrid_search(query_text=query, doc_type="doc", repo=repo, category=category, tag=tag, limit=limit)
            if not hits:
                return [TextContent(type="text", text=f"No matching documentation found for query: '{query}'.")]

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

            return [TextContent(type="text", text="\n\n========================\n\n".join(formatted))]
        except Exception as e:
            logger.error(f"search_docs failed: {e}")
            return [TextContent(type="text", text=f"Error executing doc search: {str(e)}")]

    elif name == "find_symbol":
        sym_name = arguments.get("name", "").strip()
        repo = arguments.get("repo")
        exact = arguments.get("exact", True)
        limit = arguments.get("limit", 10)

        if not sym_name:
            return [TextContent(type="text", text="Error: symbol name cannot be empty.")]

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
                return [TextContent(type="text", text=f"No symbols found matching '{sym_name}'.")]

            lines = [f"Found {len(rows)} matching symbols for '{sym_name}':\n"]
            for r in rows:
                lines.append(
                    f"- **{r['name']}** (`{r['kind']}`) in `[{r['repo']}] {r['filepath']}` (Lines {r['start_line']}-{r['end_line']})\n"
                    f"  Signature: `{r['signature']}`"
                )
            return [TextContent(type="text", text="\n".join(lines))]
        except Exception as e:
            logger.error(f"find_symbol error: {e}")
            return [TextContent(type="text", text=f"Error finding symbol: {str(e)}")]

    elif name == "get_file_outline":
        filepath = arguments.get("filepath", "").strip()
        repo = arguments.get("repo")

        try:
            with get_db_connection() as conn:
                if repo:
                    rows = conn.execute(
                        "SELECT name, full_symbol, kind, start_line, end_line, signature FROM ast_symbols WHERE (filepath = ? OR filepath LIKE ?) AND repo = ? ORDER BY start_line ASC",
                        (filepath, f"%{filepath}", repo)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature FROM ast_symbols WHERE filepath = ? OR filepath LIKE ? ORDER BY start_line ASC",
                        (filepath, f"%{filepath}")
                    ).fetchall()

            if not rows:
                return [TextContent(type="text", text=f"No outline available for '{filepath}'.")]

            outline_text = f"# File Outline: {filepath}\n\n"
            for r in rows:
                outline_text += f"- **{r['name']}** ({r['kind']}, lines {r['start_line']}-{r['end_line']}): `{r['signature']}`\n"
            return [TextContent(type="text", text=outline_text)]
        except Exception as e:
            return [TextContent(type="text", text=f"Failed to get outline: {str(e)}")]

    elif name == "list_repositories":
        try:
            with get_db_connection() as conn:
                git_repos = conn.execute("SELECT id, name, url, branch, commit_sha, status, last_synced FROM git_repositories").fetchall()
                local_paths = conn.execute("SELECT path, repo, category FROM indexed_paths WHERE enabled = 1").fetchall()
                counts = conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()
                file_count_map = {c["repo"]: c["cnt"] for c in counts}

            out = "# Registered Sources & Repositories\n\n"
            if git_repos:
                out += "### Git Repositories\n"
                for gr in git_repos:
                    fc = file_count_map.get(gr["name"], 0)
                    sha = gr["commit_sha"][:8] if gr["commit_sha"] else "None"
                    out += f"- **{gr['name']}** ({gr['url']} @ `{gr['branch']}` | SHA: `{sha}`) - Status: `{gr['status']}` | Files: {fc} | Last Synced: {gr['last_synced'] or 'Never'}\n"
                out += "\n"

            if local_paths:
                out += "### Local Monitored Paths\n"
                for lp in local_paths:
                    fc = file_count_map.get(lp["repo"], 0)
                    out += f"- **{lp['repo']}** (`{lp['path']}`) - Category: `{lp['category']}` | Files: {fc}\n"

            return [TextContent(type="text", text=out)]
        except Exception as e:
            return [TextContent(type="text", text=f"Error listing repositories: {str(e)}")]

    elif name == "sync_repository":
        target_repo = arguments.get("repo")
        try:
            from app.services.indexer import sync_single_git_repo, run_full_indexing
            import threading
            if target_repo:
                with get_db_connection() as conn:
                    row = conn.execute("SELECT id FROM git_repositories WHERE name = ?", (target_repo,)).fetchone()
                if row:
                    threading.Thread(target=sync_single_git_repo, args=(row["id"],), daemon=True).start()
                    return [TextContent(type="text", text=f"Triggered background sync for repo: '{target_repo}'")]
            
            threading.Thread(target=run_full_indexing, daemon=True).start()
            return [TextContent(type="text", text="Triggered full background re-indexing.")]
        except Exception as e:
            return [TextContent(type="text", text=f"Failed to trigger sync: {str(e)}")]

    elif name == "index_status":
        try:
            from app.services.git_manager import check_github_rate_limit, mask_token
            from app.services.db import get_effective_github_token, get_token_source
            from app.services.embeddings import COLLECTION_NAME, EMBEDDING_PROVIDER, DENSE_MODEL_NAME, SPARSE_MODEL_NAME, qdrant
            
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
            return [TextContent(type="text", text=status_text)]
        except Exception as e:
            return [TextContent(type="text", text=f"Failed to get status: {str(e)}")]

    else:
        raise ValueError(f"Unknown tool: {name}")

async def get_resources() -> List[Resource]:
    return [
        Resource(
            uri="notes://catalog/summary",
            name="Repository & Documentation Topic Catalog",
            description="Catalog of indexed repositories, documentation files, and AST symbol distributions.",
            mimeType="text/markdown"
        )
    ]

async def read_resource(uri: str) -> str:
    if uri == "notes://catalog/summary":
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
    raise ValueError(f"Unknown resource URI: {uri}")

async def get_prompts() -> List[Prompt]:
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

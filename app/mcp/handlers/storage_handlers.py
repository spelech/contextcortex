import json
import logging
import sys
from typing import Optional, Annotated
from pydantic import Field

from app.services.auth import enforce_tool_permission, Role, ForbiddenError
from app.services.local_storage import get_local_storage_service
from app.services.database import get_db_connection

logger = logging.getLogger("contextcortex.mcp")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


async def handle_manage_local_file(
    action: Annotated[str, Field(description="Action to perform: 'upload', 'replace', 'delete', or 'read'")],
    file_path: Annotated[str, Field(description="Relative path of file in local storage (e.g. 'docs/spec.md')")],
    content: Annotated[Optional[str], Field(description="Content to write for upload or replace actions")] = None,
    repo: Annotated[str, Field(description="Repository or namespace tag (default: 'local_storage')")] = "local_storage",
    category: Annotated[Optional[str], Field(description="Category tag for document")] = None
) -> str:
    """Manage files in ContextCortex local storage: upload, replace, read, or delete files with immediate vector indexing."""
    try:
        storage = _get_tools_attr("get_local_storage_service", get_local_storage_service)()
        act = (action or "").strip().lower()

        if act in ("upload", "replace", "delete"):
            enforce_tool_permission(Role.EDITOR)
        else:
            enforce_tool_permission(Role.VIEWER)

        if act in ("upload", "replace"):
            if content is None:
                return f"Error: 'content' parameter is required for action '{action}'."
            res = storage.save_file(file_path, content, repo=repo, category=category)
            past_act = "uploaded" if act == "upload" else "replaced"
            return (
                f"Successfully {past_act} and indexed file: `{res['rel_path']}`\n"
                f"- Repository: `{res['repo']}`\n"
                f"- Category: `{res['category']}`\n"
                f"- Size: {res['size_bytes']} bytes\n"
                f"- Chunks Indexed: {res.get('chunks_indexed', 0)}"
            )
        elif act == "delete":
            storage.delete_file(file_path, repo=repo)
            return f"Successfully deleted `{file_path}` and purged associated vector embeddings."
        elif act == "read":
            res = storage.read_file_content(file_path)
            return f"### File: `{res['rel_path']}` ({res['size_bytes']} bytes)\n\n```\n{res['content']}\n```"
        else:
            return f"Error: Unsupported action '{action}'. Valid actions are 'upload', 'replace', 'delete', 'read'."
    except ForbiddenError as e:
        logger.warning(f"Forbidden error executing manage_local_file ({action}): {e}")
        return f"Forbidden: {str(e)}"
    except Exception as e:
        logger.error(f"Error executing manage_local_file ({action}): {e}")
        return f"Error executing manage_local_file: {str(e)}"


async def handle_what_is_ingested(
    source_type: Annotated[str, Field(description="Filter source type: 'all', 'git', 'monitored_path', or 'local_storage'")] = "all",
    repo_name: Annotated[Optional[str], Field(description="Filter by repository or namespace name")] = None,
    path_prefix: Annotated[Optional[str], Field(description="Filter files matching path prefix")] = None,
    file_extension: Annotated[Optional[str], Field(description="Filter by file extension (e.g. '.md', '.py')")] = None,
    detail_level: Annotated[str, Field(description="Granularity: 'summary' or 'detailed'")] = "summary"
) -> str:
    """Inspect all ingested Git repositories, monitored local paths, and uploaded local storage files with optional filtering and detailed file trees."""
    try:
        enforce_tool_permission(Role.VIEWER)
        st = (source_type or "all").strip().lower()
        detail = (detail_level or "summary").strip().lower()

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            git_repos = conn.execute("SELECT id, name, url, branch, commit_sha, provider, status, last_synced FROM git_repositories").fetchall()
            indexed_paths = conn.execute("SELECT path, repo, category FROM indexed_paths WHERE enabled = 1").fetchall()
            
            # Fetch file counts grouped by repo
            f_counts = conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()
            repo_file_counts = {r["repo"]: r["cnt"] for r in f_counts}

            # Fetch symbol counts grouped by repo
            s_counts = conn.execute("SELECT repo, count(*) as cnt FROM ast_symbols GROUP BY repo").fetchall()
            repo_symbol_counts = {s["repo"]: s["cnt"] for s in s_counts}

            # Filtered file list query if detailed
            detailed_files = []
            if detail == "detailed":
                query = "SELECT filepath, repo, doc_type, language, mtime FROM indexed_files WHERE 1=1"
                params = []
                if repo_name:
                    query += " AND repo = ?"
                    params.append(repo_name)
                if path_prefix:
                    query += " AND filepath LIKE ?"
                    params.append(f"%{path_prefix}%")
                if file_extension:
                    query += " AND filepath LIKE ?"
                    params.append(f"%{file_extension}")
                query += " ORDER BY repo, filepath LIMIT 200"
                detailed_files = conn.execute(query, params).fetchall()

        out = "# ContextCortex Ingestion Catalog\n\n"

        # 1. Git Repositories
        if st in ("all", "git"):
            out += "## Git Repositories\n"
            filtered_repos = [r for r in git_repos if not repo_name or r["name"] == repo_name]
            if filtered_repos:
                for gr in filtered_repos:
                    fc = repo_file_counts.get(gr["name"], 0)
                    sc = repo_symbol_counts.get(gr["name"], 0)
                    sha = gr["commit_sha"][:8] if gr["commit_sha"] else "None"
                    out += f"- **{gr['name']}** (`{gr['branch']}` @ `{sha}`) - Status: `{gr['status']}` | Files: {fc} | Symbols: {sc} | URL: {gr['url']}\n"
            else:
                out += "_No git repositories match the criteria._\n"
            out += "\n"

        # 2. Monitored Local Paths
        if st in ("all", "monitored_path"):
            out += "## Monitored Paths\n"
            filtered_paths = [p for p in indexed_paths if not repo_name or p["repo"] == repo_name]
            if filtered_paths:
                for p in filtered_paths:
                    fc = repo_file_counts.get(p["repo"], 0)
                    out += f"- **{p['repo']}** (`{p['path']}`) - Category: `{p['category']}` | Files: {fc}\n"
            else:
                out += "_No monitored paths match the criteria._\n"
            out += "\n"

        # 3. Local Storage Uploads
        if st in ("all", "local_storage"):
            out += "## Local Storage (Uploaded Files)\n"
            storage = _get_tools_attr("get_local_storage_service", get_local_storage_service)()
            tree = storage.get_file_tree(subfolder=path_prefix if path_prefix and not path_prefix.startswith("/") else None)
            total_ls_files = repo_file_counts.get("local_storage", len(tree.get("files", [])))
            out += f"- **Root Storage Path**: `{storage.get_storage_root()}`\n"
            out += f"- **Total Uploaded Files**: {total_ls_files}\n"
            if tree.get("directories"):
                out += f"- **Subdirectories**: {', '.join(d['name'] for d in tree['directories'])}\n"
            out += "\n"

        # Detailed file list if requested
        if detail == "detailed" and detailed_files:
            out += f"## Ingested File Details (Showing top {len(detailed_files)} files)\n"
            for df in detailed_files:
                out += f"- `[{df['repo']}]` `{df['filepath']}` ({df['doc_type']} | {df['language']})\n"
            out += "\n"

        return out
    except ForbiddenError as e:
        logger.warning(f"Forbidden error retrieving ingestion catalog: {e}")
        return f"Forbidden: {str(e)}"
    except Exception as e:
        logger.error(f"Error retrieving ingestion catalog: {e}")
        return f"Error retrieving ingestion catalog: {str(e)}"

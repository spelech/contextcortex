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
        from app.services.auth import enforce_tool_permission, Role
        enforce_tool_permission(Role.VIEWER)
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
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


async def handle_trace_path(
    symbol: Annotated[str, Field(description="The target function, method, or class name to trace.")],
    repo: Annotated[Optional[str], Field(description="Specific repository to trace within. If omitted, searches across all indexed repositories.")] = None,
    direction: Annotated[str, Field(description="Direction of traversal: 'callers' (inbound), 'callees' (outbound), or 'both' (default 'both').")] = "both",
    depth: Annotated[int, Field(description="Maximum hops in the BFS traversal (min 1, max 5, default 2).")] = 2,
    limit: Annotated[int, Field(description="Maximum total relationships returned to avoid token bloat (default 25).")] = 25
) -> str:
    """Deterministically traverse function call graphs, module imports, and inheritance hierarchies using AST relationships (BFS)."""
    try:
        from app.services.auth import enforce_tool_permission, Role
        enforce_tool_permission(Role.VIEWER)
        return trace_symbol_path(
            symbol=symbol,
            repo=repo,
            direction=direction,
            depth=depth,
            limit=limit
        )
    except Exception as e:
        logger.error(f"trace_path tool execution failed: {e}")
        return f"Error executing trace_path: {str(e)}"



async def handle_get_file_outline(
    filepath: Annotated[str, Field(description="File path (e.g. 'src/server.py' or 'repo_name://src/server.py').")],
    repo: Annotated[Optional[str], Field(description="Repository identifier (optional).")] = None
) -> str:
    """Get the AST outline (classes, methods, functions, line numbers) of a file without retrieving its entire token body."""
    fp = filepath.strip() if filepath else ""
    try:
        from app.services.auth import enforce_tool_permission, Role
        enforce_tool_permission(Role.VIEWER)
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
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



def handle_find_implementation_symbol(
    symbol: Annotated[str, Field(description="Function or class name to find")],
    repo: Annotated[Optional[str], Field(description="Target repository (optional)")] = None
) -> str:
    """Workflow to locate functions, classes, and logic across registered codebases."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return f"Please use find_symbol for '{symbol}' in repo '{repo}' and inspect its declaration, line numbers, and implementation details."


# --- Registration on FastMCP Server ---


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


async def handle_search_code(
    query: Annotated[str, Field(description="Natural language question or code concept (e.g. 'JWT token authentication handler').")],
    repo: Annotated[Optional[str], Field(description="Optional repository name/alias to filter by.")] = None,
    language: Annotated[Optional[str], Field(description="Optional language filter (e.g. 'python', 'typescript', 'go').")] = None,
    limit: Annotated[int, Field(description="Max number of code blocks to return (default 5).")] = 5,
    dense_weight: Annotated[Optional[float], Field(description="Weight between 0.0 (pure lexical BM25) and 1.0 (pure semantic vector). Default is 0.5 balanced.")] = None,
    mode: Annotated[Optional[str], Field(description="Search mode: 'hybrid' (default), 'semantic', or 'lexical'.")] = "hybrid"
) -> str:
    """Hybrid semantic and BM25 search over code functions, classes, and logic snippets with line numbers, AST signatures, and GitHub links."""
    query = query.strip() if query else ""
    if not query:
        return json.dumps({"error": "search query cannot be empty."})

    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        requested_mode = (mode or "hybrid").lower().strip()
        hits = _get_tools_attr("execute_hybrid_search", execute_hybrid_search)(
            query_text=query,
            doc_type="code",
            repo=repo,
            language=language,
            limit=limit,
            dense_weight=dense_weight,
            search_mode=requested_mode
        )
        results = []
        for hit in (hits or []):
            p = hit.payload or {}
            raw_path = p.get("rel_path") or p.get("path") or p.get("filepath") or ""
            rel_path = raw_path.split("://", 1)[1] if "://" in raw_path else raw_path
            start_l = p.get("start_line")
            end_l = p.get("end_line")
            lines_range = [start_l, end_l] if start_l is not None and end_l is not None else None
            score_val = round(float(hit.score), 4) if isinstance(getattr(hit, "score", None), (int, float)) else 0.0
            d_val = round(float(hit.dense_score), 4) if isinstance(getattr(hit, "dense_score", None), (int, float)) else None
            s_val = round(float(hit.sparse_score), 4) if isinstance(getattr(hit, "sparse_score", None), (int, float)) else None

            results.append({
                "repo": p.get("repo"),
                "file": rel_path,
                "lines": lines_range,
                "symbol": p.get("full_symbol") or p.get("symbol"),
                "kind": p.get("kind"),
                "signature": p.get("signature"),
                "language": p.get("language"),
                "score": score_val,
                "dense_score": d_val,
                "sparse_score": s_val,
                "permalink": p.get("permalink_url") or p.get("github_url"),
                "content": p.get("content") or "",
            })

        return json.dumps({
            "query": query,
            "mode": requested_mode,
            "results": results,
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_search_code: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"search_code failed: {e}")
        return json.dumps({"error": f"Error executing code search: {str(e)}"})


async def handle_search_docs(
    query: Annotated[str, Field(description="Search query or documentation topic.")],
    repo: Annotated[Optional[str], Field(description="Optional repository/vault filter.")] = None,
    category: Annotated[Optional[str], Field(description="Optional category filter.")] = None,
    tag: Annotated[Optional[str], Field(description="Optional tag filter.")] = None,
    limit: Annotated[int, Field(description="Max documents to return (default 5).")] = 5,
    dense_weight: Annotated[Optional[float], Field(description="Weight between 0.0 (pure lexical BM25) and 1.0 (pure semantic vector). Default is 0.5 balanced.")] = None,
    mode: Annotated[Optional[str], Field(description="Search mode: 'hybrid' (default), 'semantic', or 'lexical'.")] = "hybrid"
) -> str:
    """Hybrid search across system documentation, markdown notes, architectural decisions, and runbooks."""
    query = query.strip() if query else ""
    if not query:
        return json.dumps({"error": "search query cannot be empty."})

    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        requested_mode = (mode or "hybrid").lower().strip()
        hits = _get_tools_attr("execute_hybrid_search", execute_hybrid_search)(
            query_text=query,
            doc_type="doc",
            repo=repo,
            category=category,
            tag=tag,
            limit=limit,
            dense_weight=dense_weight,
            search_mode=requested_mode
        )
        results = []
        for hit in (hits or []):
            p = hit.payload or {}
            raw_path = p.get("rel_path") or p.get("path") or p.get("filepath") or ""
            rel_path = raw_path.split("://", 1)[1] if "://" in raw_path else raw_path
            score_val = round(float(hit.score), 4) if isinstance(getattr(hit, "score", None), (int, float)) else 0.0
            d_val = round(float(hit.dense_score), 4) if isinstance(getattr(hit, "dense_score", None), (int, float)) else None
            s_val = round(float(hit.sparse_score), 4) if isinstance(getattr(hit, "sparse_score", None), (int, float)) else None

            results.append({
                "repo": p.get("repo"),
                "file": rel_path,
                "heading": p.get("heading"),
                "tags": p.get("tags", []),
                "score": score_val,
                "dense_score": d_val,
                "sparse_score": s_val,
                "permalink": p.get("permalink_url") or p.get("github_url"),
                "content": p.get("content") or "",
            })

        return json.dumps({
            "query": query,
            "mode": requested_mode,
            "results": results,
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_search_docs: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"search_docs failed: {e}")
        return json.dumps({"error": f"Error executing doc search: {str(e)}"})

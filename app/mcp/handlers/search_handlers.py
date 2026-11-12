import json
import logging
import sys
from typing import Optional, Annotated, Tuple
from pydantic import Field

from app.services.search import execute_hybrid_search, normalize_search_mode

logger = logging.getLogger("contextcortex")

_SNIPPET_SUFFIX = "\n...[snippet truncated]"


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


def _truncate_snippet(content: str, max_chars: int) -> Tuple[str, bool]:
    if not content or len(content) <= max_chars:
        return content or "", False
    keep = max(1, max_chars - len(_SNIPPET_SUFFIX))
    cut = content[:keep]
    last_nl = cut.rfind("\n")
    if last_nl >= int(keep * 0.7):
        cut = cut[:last_nl]
    return cut.rstrip() + _SNIPPET_SUFFIX, True


async def handle_search_code(
    query: Annotated[str, Field(description="Natural-language code concept or identifier query (e.g. 'JWT bearer validation' or 'UnitOfWork.Run') across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++.")],
    repo: Annotated[Optional[str], Field(description="Optional repository name or namespace to scope code retrieval.")] = None,
    language: Annotated[Optional[str], Field(description="Optional language filter (e.g. 'python', 'typescript', 'tsx', 'csharp', 'cobol', 'go', 'rust', 'java', 'cpp', 'c').")] = None,
    limit: Annotated[int, Field(description="Maximum code chunks per page, clamped to 1..25 (default 5). Alias for top_k.")] = 5,
    dense_weight: Annotated[Optional[float], Field(description="Optional fusion weight in 0.0..1.0 between lexical BM25 (0.0) and dense semantic vectors (1.0); default 0.5 balanced.")] = None,
    mode: Annotated[Optional[str], Field(description="Retrieval mode: 'hybrid' (default), 'semantic' ('vector'), or 'lexical' ('keyword', 'bm25', 'fts').")] = "hybrid",
    top_k: Annotated[Optional[int], Field(description="Maximum code chunks per page, clamped to 1..25 (default 5). Overrides limit when provided.")] = None,
    offset: Annotated[int, Field(description="0-based result offset for pagination (default 0). Advance using next_offset when has_more is True.")] = 0,
    max_snippet_chars: Annotated[int, Field(description="Maximum characters per returned code snippet, clamped to 200..6000 (default 2000).")] = 2000,
) -> str:
    """Hybrid semantic + BM25 code retrieval across AST-chunked functions, classes, and modules with bounded snippets and pagination."""
    query = query.strip() if query else ""
    if not query:
        return json.dumps({"error": "search query cannot be empty."})

    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        raw_k = top_k if top_k is not None else limit
        safe_limit = max(1, min(int(raw_k if raw_k is not None else 5), 25))
        safe_offset = max(0, int(offset if offset is not None else 0))
        safe_max_chars = max(200, min(int(max_snippet_chars if max_snippet_chars is not None else 2000), 6000))
        fetch_limit = safe_offset + safe_limit + 1

        requested_mode = normalize_search_mode(mode)
        hits = _get_tools_attr("execute_hybrid_search", execute_hybrid_search)(
            query_text=query,
            doc_type="code",
            repo=repo,
            language=language,
            limit=fetch_limit,
            dense_weight=dense_weight,
            search_mode=requested_mode,
        ) or []

        has_more = len(hits) > (safe_offset + safe_limit)
        page_hits = hits[safe_offset : safe_offset + safe_limit]
        next_offset = (safe_offset + safe_limit) if has_more else None

        results = []
        for hit in page_hits:
            p = hit.payload or {}
            raw_path = p.get("rel_path") or p.get("path") or p.get("filepath") or ""
            rel_path = (raw_path.split("://", 1)[1] if "://" in raw_path else raw_path).replace("\\", "/")
            start_l = p.get("start_line")
            end_l = p.get("end_line")
            lines_range = [start_l, end_l] if start_l is not None and end_l is not None else None
            score_val = round(float(hit.score), 4) if isinstance(getattr(hit, "score", None), (int, float)) else 0.0
            d_val = round(float(hit.dense_score), 4) if isinstance(getattr(hit, "dense_score", None), (int, float)) else None
            s_val = round(float(hit.sparse_score), 4) if isinstance(getattr(hit, "sparse_score", None), (int, float)) else None
            raw_permalink = p.get("permalink_url") or p.get("github_url")
            permalink = raw_permalink.replace("\\", "/") if isinstance(raw_permalink, str) else raw_permalink
            snippet_text, was_truncated = _truncate_snippet(p.get("content") or "", safe_max_chars)

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
                "permalink": permalink,
                "content_truncated": was_truncated,
                "content": snippet_text,
            })

        return json.dumps({
            "query": query,
            "mode": requested_mode,
            "total": len(hits),
            "offset": safe_offset,
            "limit": safe_limit,
            "top_k": safe_limit,
            "max_snippet_chars": safe_max_chars,
            "has_more": has_more,
            "next_offset": next_offset,
            "results": results,
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_search_code: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"search_code failed: {e}")
        return json.dumps({"error": f"Error executing code search: {str(e)}"})


async def handle_search_docs(
    query: Annotated[str, Field(description="Natural-language question or topic for Markdown runbooks, architecture specs, ADRs, and extracted PDF documentation.")],
    repo: Annotated[Optional[str], Field(description="Optional repository, documentation vault, or 'local_storage' filter.")] = None,
    category: Annotated[Optional[str], Field(description="Optional document category filter (e.g. 'architecture', 'runbook', 'notes').")] = None,
    tag: Annotated[Optional[str], Field(description="Optional frontmatter tag filter.")] = None,
    limit: Annotated[int, Field(description="Maximum document chunks per page, clamped to 1..25 (default 5). Alias for top_k.")] = 5,
    dense_weight: Annotated[Optional[float], Field(description="Optional fusion weight in 0.0..1.0 between lexical BM25 (0.0) and dense semantic vectors (1.0); default 0.5 balanced.")] = None,
    mode: Annotated[Optional[str], Field(description="Retrieval mode: 'hybrid' (default), 'semantic' ('vector'), or 'lexical' ('keyword', 'bm25', 'fts').")] = "hybrid",
    top_k: Annotated[Optional[int], Field(description="Maximum document chunks per page, clamped to 1..25 (default 5). Overrides limit when provided.")] = None,
    offset: Annotated[int, Field(description="0-based result offset for pagination (default 0). Advance using next_offset when has_more is True.")] = 0,
    max_snippet_chars: Annotated[int, Field(description="Maximum characters per returned document snippet, clamped to 200..6000 (default 2000).")] = 2000,
) -> str:
    """Hybrid semantic + BM25 search across Markdown specs, runbooks, ADRs, and PDFs with bounded snippets and pagination."""
    query = query.strip() if query else ""
    if not query:
        return json.dumps({"error": "search query cannot be empty."})

    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        raw_k = top_k if top_k is not None else limit
        safe_limit = max(1, min(int(raw_k if raw_k is not None else 5), 25))
        safe_offset = max(0, int(offset if offset is not None else 0))
        safe_max_chars = max(200, min(int(max_snippet_chars if max_snippet_chars is not None else 2000), 6000))
        fetch_limit = safe_offset + safe_limit + 1

        requested_mode = normalize_search_mode(mode)
        hits = _get_tools_attr("execute_hybrid_search", execute_hybrid_search)(
            query_text=query,
            doc_type="doc",
            repo=repo,
            category=category,
            tag=tag,
            limit=fetch_limit,
            dense_weight=dense_weight,
            search_mode=requested_mode,
        ) or []

        has_more = len(hits) > (safe_offset + safe_limit)
        page_hits = hits[safe_offset : safe_offset + safe_limit]
        next_offset = (safe_offset + safe_limit) if has_more else None

        results = []
        for hit in page_hits:
            p = hit.payload or {}
            raw_path = p.get("rel_path") or p.get("path") or p.get("filepath") or ""
            rel_path = (raw_path.split("://", 1)[1] if "://" in raw_path else raw_path).replace("\\", "/")
            score_val = round(float(hit.score), 4) if isinstance(getattr(hit, "score", None), (int, float)) else 0.0
            d_val = round(float(hit.dense_score), 4) if isinstance(getattr(hit, "dense_score", None), (int, float)) else None
            s_val = round(float(hit.sparse_score), 4) if isinstance(getattr(hit, "sparse_score", None), (int, float)) else None
            raw_permalink = p.get("permalink_url") or p.get("github_url")
            permalink = raw_permalink.replace("\\", "/") if isinstance(raw_permalink, str) else raw_permalink
            snippet_text, was_truncated = _truncate_snippet(p.get("content") or "", safe_max_chars)

            results.append({
                "repo": p.get("repo"),
                "file": rel_path,
                "heading": p.get("heading"),
                "tags": p.get("tags", []),
                "score": score_val,
                "dense_score": d_val,
                "sparse_score": s_val,
                "permalink": permalink,
                "content_truncated": was_truncated,
                "content": snippet_text,
            })

        return json.dumps({
            "query": query,
            "mode": requested_mode,
            "total": len(hits),
            "offset": safe_offset,
            "limit": safe_limit,
            "top_k": safe_limit,
            "max_snippet_chars": safe_max_chars,
            "has_more": has_more,
            "next_offset": next_offset,
            "results": results,
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_search_docs: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"search_docs failed: {e}")
        return json.dumps({"error": f"Error executing doc search: {str(e)}"})

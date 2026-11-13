import json
import logging
import sys
from typing import Literal, Optional, Annotated, Tuple
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


def _resolve_doc_type(scope: Optional[str]) -> Tuple[str, Optional[str]]:
    clean = (scope or "all").strip().lower()
    if clean == "code":
        return "code", "code"
    if clean in ("docs", "doc"):
        return "docs", "doc"
    if clean == "all":
        return "all", None
    raise ValueError(f"Unsupported scope '{scope}'. Valid scopes are 'code', 'docs', or 'all'.")


async def handle_search(
    query: Annotated[str, Field(description="Natural-language code/doc concept or exact identifier (e.g. 'JWT bearer validation' or 'OrderProcessor.retry_payment') across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, C/C++, Markdown, ADRs, and PDFs.")],
    scope: Annotated[Literal["code", "docs", "all"], Field(description="Retrieval scope: 'code' (AST code chunks), 'docs' (Markdown, ADRs, PDFs), or 'all' (default, searches both).")] = "all",
    repo: Annotated[Optional[str], Field(description="Optional repository name, documentation vault, or 'local_storage' filter.")] = None,
    language: Annotated[Optional[str], Field(description="Optional language filter for code results (e.g. 'python', 'typescript', 'tsx', 'csharp', 'cobol', 'go', 'rust', 'java', 'cpp', 'c').")] = None,
    category: Annotated[Optional[str], Field(description="Optional document category filter (e.g. 'architecture', 'runbook', 'notes').")] = None,
    tag: Annotated[Optional[str], Field(description="Optional frontmatter tag filter.")] = None,
    mode: Annotated[Optional[str], Field(description="Retrieval mode: 'hybrid' (default), 'semantic' ('vector'), or 'lexical' ('keyword', 'bm25', 'fts').")] = "hybrid",
    dense_weight: Annotated[Optional[float], Field(description="Optional fusion weight in 0.0..1.0 between lexical BM25 (0.0) and dense semantic vectors (1.0); default 0.5 balanced.")] = None,
    limit: Annotated[int, Field(description="Maximum chunks per page, clamped to 1..25 (default 5).")] = 5,
    offset: Annotated[int, Field(description="0-based result offset for pagination (default 0). Advance using next_offset when has_more is True.")] = 0,
    max_snippet_chars: Annotated[int, Field(description="Maximum characters per returned snippet, clamped to 200..6000 (default 2000).")] = 2000,
) -> str:
    """Hybrid semantic + BM25 search across AST-chunked source code and documentation with bounded snippets and pagination."""
    clean_query = query.strip() if query else ""
    if not clean_query:
        return json.dumps({"error": "search query cannot be empty."})

    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        clean_scope, doc_type = _resolve_doc_type(scope)
        safe_limit = max(1, min(int(limit if limit is not None else 5), 25))
        safe_offset = max(0, int(offset if offset is not None else 0))
        safe_max_chars = max(200, min(int(max_snippet_chars if max_snippet_chars is not None else 2000), 6000))
        fetch_limit = safe_offset + safe_limit + 1

        requested_mode = normalize_search_mode(mode)
        hits = _get_tools_attr("execute_hybrid_search", execute_hybrid_search)(
            query_text=clean_query,
            doc_type=doc_type,
            repo=repo,
            language=language,
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
            start_l = p.get("start_line")
            end_l = p.get("end_line")
            lines_range = [start_l, end_l] if start_l is not None and end_l is not None else None
            score_val = round(float(hit.score), 4) if isinstance(getattr(hit, "score", None), (int, float)) else 0.0
            d_val = round(float(hit.dense_score), 4) if isinstance(getattr(hit, "dense_score", None), (int, float)) else None
            s_val = round(float(hit.sparse_score), 4) if isinstance(getattr(hit, "sparse_score", None), (int, float)) else None
            raw_permalink = p.get("permalink_url") or p.get("github_url")
            permalink = raw_permalink.replace("\\", "/") if isinstance(raw_permalink, str) else raw_permalink
            snippet_text, was_truncated = _truncate_snippet(p.get("content") or "", safe_max_chars)
            hit_doc_type = p.get("doc_type") or ("code" if p.get("symbol") or p.get("language") else "doc")

            item = {
                "repo": p.get("repo"),
                "file": rel_path,
                "doc_type": hit_doc_type,
                "lines": lines_range,
                "symbol": p.get("full_symbol") or p.get("symbol"),
                "kind": p.get("kind"),
                "signature": p.get("signature"),
                "language": p.get("language"),
                "heading": p.get("heading"),
                "tags": p.get("tags", []),
                "score": score_val,
                "dense_score": d_val,
                "sparse_score": s_val,
                "permalink": permalink,
                "content_truncated": was_truncated,
                "content": snippet_text,
            }
            results.append(item)

        return json.dumps({
            "query": clean_query,
            "scope": clean_scope,
            "mode": requested_mode,
            "total": len(hits),
            "offset": safe_offset,
            "limit": safe_limit,
            "max_snippet_chars": safe_max_chars,
            "has_more": has_more,
            "next_offset": next_offset,
            "results": results,
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_search: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except ValueError as ve:
        return json.dumps({"error": str(ve)})
    except Exception as e:
        logger.error(f"search failed: {e}")
        return json.dumps({"error": f"Error executing search: {str(e)}"})

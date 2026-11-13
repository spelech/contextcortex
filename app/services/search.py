import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from app.services.database import get_db_connection
from app.services.git_manager import format_git_permalink
from app.services.graph_traversal import (
    _clean_path,
    _methods_compatible,
    trace_symbol_path,
)
from app.services.lexical_retriever import run_fast_lexical_track
from app.services.query_router import (
    classify_query_intent,
    fuse_search_results,
    should_early_return_lexical,
    strip_internal_metadata,
)
from app.services.vector_store import VectorSearchResult, get_vector_store

logger = logging.getLogger("contextcortex.search")

_TRACK_B_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ctx-search-track-b")


def _enrich_code_ast_metadata(results: List[VectorSearchResult]) -> None:
    """Enriches code hits with AST symbol details (signature, clean kind, ast_symbol_id)."""
    if not results:
        return

    code_results = [r for r in results if r.payload.get("doc_type") == "code" or r.payload.get("symbol")]
    if not code_results:
        return

    try:
        with get_db_connection() as conn:
            for r in code_results:
                p = r.payload
                repo = p.get("repo")
                rel_path = p.get("rel_path") or p.get("path")
                sym_name = p.get("symbol")
                start_l = p.get("start_line")
                end_l = p.get("end_line")

                clean_fp = rel_path.lstrip("/").replace("\\", "/") if rel_path else ""

                row = None
                if sym_name and repo:
                    member_name = sym_name.split(".")[-1]
                    row = conn.execute(
                        """
                        SELECT id, name, full_symbol, kind, signature, start_line, end_line
                        FROM ast_symbols
                        WHERE repo = ?
                          AND (name = ? OR full_symbol = ? OR name = ?)
                          AND (REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') LIKE ?)
                        ORDER BY (CASE WHEN full_symbol = ? THEN 1 WHEN name = ? THEN 2 ELSE 3 END),
                                 abs(start_line - ?) ASC
                        LIMIT 1
                        """,
                        (repo, sym_name, sym_name, member_name, clean_fp, f"/{clean_fp}", f"%/{clean_fp}", sym_name, member_name, start_l or 0),
                    ).fetchone()

                if not row and repo and clean_fp and start_l is not None and end_l is not None:
                    row = conn.execute(
                        """
                        SELECT id, name, full_symbol, kind, signature, start_line, end_line
                        FROM ast_symbols
                        WHERE repo = ?
                          AND (REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') LIKE ?)
                          AND start_line <= ? AND end_line >= ?
                        ORDER BY (end_line - start_line) ASC
                        LIMIT 1
                        """,
                        (repo, clean_fp, f"/{clean_fp}", f"%/{clean_fp}", end_l, start_l),
                    ).fetchone()

                if row:
                    if row["signature"] and not p.get("signature"):
                        p["signature"] = row["signature"]
                    if row["full_symbol"] and not p.get("full_symbol"):
                        p["full_symbol"] = row["full_symbol"]
                    if row["kind"] and (not p.get("kind") or p.get("kind") == "module"):
                        p["kind"] = row["kind"]
                    if "ast_symbol_id" not in p and row["id"]:
                        p["ast_symbol_id"] = row["id"]
    except Exception as e:
        logger.debug(f"AST enrichment skipped due to error: {e}")


SEARCH_MODE_ALIASES = {
    "keyword": "lexical",
    "keywords": "lexical",
    "bm25": "lexical",
    "fulltext": "lexical",
    "fts": "lexical",
    "dense": "semantic",
    "vector": "semantic",
}


def normalize_search_mode(search_mode: Optional[str]) -> str:
    mode = (search_mode or "hybrid").lower().strip()
    return SEARCH_MODE_ALIASES.get(mode, mode)


def execute_hybrid_search(
    query_text: str,
    doc_type: Optional[str] = None,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 5,
    dense_weight: Optional[float] = None,
    search_mode: str = "hybrid",
) -> List[VectorSearchResult]:
    """Executes parallel query-routed retrieval (Track A AST+ripgrep lexical, Track B dense/hybrid) with AST enrichment."""
    if not query_text or not query_text.strip():
        return []

    clean_query = query_text.strip()
    try:
        store = get_vector_store()
        try:
            caps = store.get_capabilities()
            if isinstance(caps, dict):
                supported = caps.get("search_modes", ["hybrid", "semantic", "lexical"])
            else:
                supported = ["hybrid", "semantic", "lexical"]
        except Exception:
            supported = ["hybrid", "semantic", "lexical"]

        mode = normalize_search_mode(search_mode)
        if mode not in supported:
            if mode == "hybrid" and "semantic" in supported:
                mode = "semantic"
            else:
                raise ValueError(
                    f"Search mode '{search_mode}' is not supported by the active vector store backend ({store.__class__.__name__}). Supported modes: {supported} (aliases: 'keyword', 'bm25')"
                )

        # Explicit pure semantic search bypasses lexical shortcutting
        if mode == "semantic":
            results = store.search(
                query_text=clean_query,
                doc_type=doc_type,
                repo=repo,
                language=language,
                category=category,
                tag=tag,
                limit=limit,
                dense_weight=dense_weight,
                search_mode=mode,
            )
            _enrich_code_ast_metadata(results)
            return results

        plan = classify_query_intent(clean_query)

        # Explicit lexical mode combines Track A (AST + rg) with store lexical FTS/BM25 (zero dense embeddings)
        if mode == "lexical":
            track_a = run_fast_lexical_track(
                plan=plan,
                store=store,
                doc_type=doc_type,
                repo=repo,
                language=language,
                category=category,
                tag=tag,
                limit=limit,
                allow_store_chunk_hydration=True,
            )
            store_lex = store.search(
                query_text=clean_query,
                doc_type=doc_type,
                repo=repo,
                language=language,
                category=category,
                tag=tag,
                limit=limit,
                dense_weight=0.0,
                search_mode="lexical",
            )
            fused = fuse_search_results(track_a, store_lex, limit=limit, intent="lexical_keywords")
            _enrich_code_ast_metadata(fused)
            return fused

        # Exact-identifier / quoted / code-syntax queries: run Track A first with 0 dense embeddings on hit
        if plan.intent == "lexical_exact" and dense_weight is None:
            track_a = run_fast_lexical_track(
                plan=plan,
                store=store,
                doc_type=doc_type,
                repo=repo,
                language=language,
                category=category,
                tag=tag,
                limit=limit,
                allow_store_chunk_hydration=True,
            )
            if not track_a and "lexical" in supported:
                track_a = store.search(
                    query_text=clean_query,
                    doc_type=doc_type,
                    repo=repo,
                    language=language,
                    category=category,
                    tag=tag,
                    limit=limit,
                    dense_weight=0.0,
                    search_mode="lexical",
                )
            if should_early_return_lexical(plan, track_a):
                early = strip_internal_metadata(track_a[:limit])
                _enrich_code_ast_metadata(early)
                return early

            track_b = store.search(
                query_text=clean_query,
                doc_type=doc_type,
                repo=repo,
                language=language,
                category=category,
                tag=tag,
                limit=limit,
                dense_weight=dense_weight,
                search_mode=mode,
            )
            fused = fuse_search_results(track_a, track_b, limit=limit, intent=plan.intent)
            _enrich_code_ast_metadata(fused)
            return fused

        # Parallel execution at t=0: launch Track B in background while Track A runs locally
        ctx = contextvars.copy_context()
        track_b_future = _TRACK_B_EXECUTOR.submit(
            ctx.run,
            store.search,
            query_text=clean_query,
            doc_type=doc_type,
            repo=repo,
            language=language,
            category=category,
            tag=tag,
            limit=limit,
            dense_weight=dense_weight,
            search_mode=mode,
        )

        # Avoid concurrent access to local file/memory QdrantClient while Track B uses it
        store_mode = getattr(store, "mode", None)
        allow_hydration = store_mode not in ("memory", "embedded")
        track_a = run_fast_lexical_track(
            plan=plan,
            store=store,
            doc_type=doc_type,
            repo=repo,
            language=language,
            category=category,
            tag=tag,
            limit=limit,
            allow_store_chunk_hydration=allow_hydration,
        )

        if dense_weight is None and plan.intent == "lexical_keywords" and should_early_return_lexical(plan, track_a):
            if track_b_future.done():
                try:
                    track_b_done = track_b_future.result()
                    fused = fuse_search_results(track_a, track_b_done, limit=limit, intent=plan.intent)
                    _enrich_code_ast_metadata(fused)
                    return fused
                except ValueError:
                    raise
                except Exception as exc:
                    logger.warning(f"Track B failed after Track A succeeded; returning Track A hits: {exc}")
            early = strip_internal_metadata(track_a[:limit])
            _enrich_code_ast_metadata(early)
            return early

        try:
            track_b_results = track_b_future.result()
        except ValueError:
            raise
        except Exception as exc:
            logger.error(f"Error executing Track B vector search: {exc}")
            if track_a:
                fallback = strip_internal_metadata(track_a[:limit])
                _enrich_code_ast_metadata(fallback)
                return fallback
            return []

        fused = fuse_search_results(track_a, track_b_results, limit=limit, intent=plan.intent)
        _enrich_code_ast_metadata(fused)
        return fused
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error executing vector search: {e}")
        return []


__all__ = [
    "SEARCH_MODE_ALIASES",
    "_clean_path",
    "_enrich_code_ast_metadata",
    "_methods_compatible",
    "classify_query_intent",
    "execute_hybrid_search",
    "format_git_permalink",
    "get_db_connection",
    "normalize_search_mode",
    "trace_symbol_path",
]

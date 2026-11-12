import fnmatch
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.services.vector_store.base import VectorSearchResult

logger = logging.getLogger("contextcortex.vector_store.qdrant")

_QDRANT_MODE_ALIASES = {
    "keyword": "lexical",
    "keywords": "lexical",
    "bm25": "lexical",
    "fulltext": "lexical",
    "fts": "lexical",
    "vector": "semantic",
    "dense": "semantic",
    "sparse": "lexical",
}


def build_qdrant_filter(
    doc_type: Optional[str] = None,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
) -> Optional[qmodels.Filter]:
    must_conditions = []
    if doc_type:
        clean_dt = doc_type.replace("\x00", "")
        if clean_dt == "doc":
            must_conditions.append(qmodels.FieldCondition(key="doc_type", match=qmodels.MatchAny(any=["doc", "pdf"])))
        else:
            must_conditions.append(qmodels.FieldCondition(key="doc_type", match=qmodels.MatchValue(value=clean_dt)))
    if repo:
        must_conditions.append(qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo.replace("\x00", ""))))
    if language:
        must_conditions.append(qmodels.FieldCondition(key="language", match=qmodels.MatchValue(value=language.replace("\x00", ""))))
    if category:
        must_conditions.append(qmodels.FieldCondition(key="category", match=qmodels.MatchValue(value=category.replace("\x00", ""))))
    if tag:
        must_conditions.append(qmodels.FieldCondition(key="tags", match=qmodels.MatchAny(any=[tag.replace("\x00", "")])))
    return qmodels.Filter(must=must_conditions) if must_conditions else None


def execute_qdrant_search(
    client: QdrantClient,
    collection_name: str,
    supported_modes: List[str],
    dense_embed_fn: Callable[[str], List[float]],
    sparse_embed_fn: Callable[[str], Any],
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
    clean_query = (query_text or "").replace("\x00", " ").strip()
    if not clean_query:
        return []

    try:
        if not client.collection_exists(collection_name):
            logger.warning(f"Collection '{collection_name}' does not exist in Qdrant.")
            return []

        query_filter = build_qdrant_filter(doc_type=doc_type, repo=repo, language=language, category=category, tag=tag)

        raw_mode = (search_mode or "hybrid").lower().strip()
        mode = _QDRANT_MODE_ALIASES.get(raw_mode, raw_mode)
        if mode not in supported_modes:
            mode = "hybrid"

        if mode == "semantic":
            alpha = 1.0
        elif mode == "lexical":
            alpha = 0.0
        elif dense_weight is not None:
            try:
                alpha = max(0.0, min(1.0, float(dense_weight)))
            except (ValueError, TypeError):
                alpha = 0.5
        else:
            try:
                env_alpha = os.getenv("HYBRID_DENSE_WEIGHT")
                alpha = max(0.0, min(1.0, float(env_alpha) if env_alpha is not None else 0.5))
            except (ValueError, TypeError):
                alpha = 0.5

        dense_vec = dense_embed_fn(clean_query) if mode in ("hybrid", "semantic") else None
        sparse_vec = sparse_embed_fn(clean_query) if mode in ("hybrid", "lexical") else None

        if dense_vec is not None:
            info = client.get_collection(collection_name)
            vectors_config = getattr(info.config.params, "vectors", None)
            if isinstance(vectors_config, dict) and "dense" in vectors_config:
                col_dim = getattr(vectors_config["dense"], "size", None)
                if col_dim is not None and len(dense_vec) != col_dim:
                    msg = f"Vector dimension mismatch: query vector ({len(dense_vec)}d) does not match collection '{collection_name}' ({col_dim}d). An index rebuild is required."
                    logger.error(msg)
                    raise ValueError(msg)

        candidate_limit = max(limit * 5, 50)

        if mode == "lexical":
            if sparse_vec is None or len(sparse_vec.indices) == 0:
                logger.warning(f"Lexical search requested for '{clean_query}', but no sparse BM25 tokens were generated.")
                return []

        if mode == "semantic" or (mode == "hybrid" and (sparse_vec is None or len(sparse_vec.indices) == 0)):
            if dense_vec is None:
                dense_vec = dense_embed_fn(clean_query)
            response = client.query_points(
                collection_name=collection_name,
                query=dense_vec,
                using="dense",
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            results: List[VectorSearchResult] = []
            for rank_idx, pt in enumerate(response.points, start=1):
                clamped_score = max(0.0, min(1.0, float(pt.score) if pt.score is not None else 0.0))
                results.append(
                    VectorSearchResult(
                        id=str(pt.id), score=round(clamped_score, 4),
                        dense_score=round(clamped_score, 4), sparse_score=0.0,
                        dense_rank=rank_idx, sparse_rank=None,
                        payload=pt.payload or {},
                    )
                )
            return results

        if mode == "lexical":
            response = client.query_points(
                collection_name=collection_name,
                query=sparse_vec,
                using="sparse",
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            sparse_scores = [p.score for p in response.points if p.score is not None]
            max_sparse = max(sparse_scores, default=1.0)
            if max_sparse <= 0.0:
                max_sparse = 1.0

            results = []
            for rank_idx, pt in enumerate(response.points, start=1):
                raw_s = float(pt.score) if pt.score is not None else 0.0
                norm_s = max(0.0, min(1.0, raw_s / max_sparse))
                results.append(
                    VectorSearchResult(
                        id=str(pt.id), score=round(norm_s, 4),
                        dense_score=0.0, sparse_score=round(norm_s, 4),
                        dense_rank=None, sparse_rank=rank_idx,
                        payload=pt.payload or {},
                    )
                )
            return results

        batch_response = client.query_batch_points(
            collection_name=collection_name,
            requests=[
                qmodels.QueryRequest(
                    query=dense_vec, using="dense", limit=candidate_limit,
                    filter=query_filter, with_payload=True,
                ),
                qmodels.QueryRequest(
                    query=sparse_vec, using="sparse", limit=candidate_limit,
                    filter=query_filter, with_payload=True,
                ),
            ],
        )

        dense_pts = {str(p.id): p for p in batch_response[0].points}
        sparse_pts = {str(p.id): p for p in batch_response[1].points}
        dense_ranks = {str(p.id): idx for idx, p in enumerate(batch_response[0].points, start=1)}
        sparse_ranks = {str(p.id): idx for idx, p in enumerate(batch_response[1].points, start=1)}

        sparse_scores = [p.score for p in sparse_pts.values() if p.score is not None]
        max_sparse = max(sparse_scores, default=1.0)
        if max_sparse <= 0.0:
            max_sparse = 1.0

        all_uids = set(dense_pts.keys()).union(sparse_pts.keys())
        scored_results: List[VectorSearchResult] = []
        for uid in all_uids:
            d_score = max(0.0, min(1.0, float(dense_pts[uid].score))) if uid in dense_pts and dense_pts[uid].score is not None else 0.0
            s_score = (float(sparse_pts[uid].score) / max_sparse) if uid in sparse_pts and sparse_pts[uid].score is not None and max_sparse > 0 else 0.0
            s_score = max(0.0, min(1.0, s_score))

            if uid in dense_pts and uid in sparse_pts:
                final_score = alpha * d_score + (1.0 - alpha) * s_score
            elif uid in dense_pts:
                final_score = alpha * d_score
            else:
                final_score = (1.0 - alpha) * s_score

            final_score = max(0.0, min(1.0, final_score))
            pt = dense_pts.get(uid) or sparse_pts.get(uid)
            payload = (pt.payload or {}) if pt else {}
            scored_results.append(
                VectorSearchResult(
                    id=uid, score=round(final_score, 4),
                    dense_score=round(d_score, 4), sparse_score=round(s_score, 4),
                    dense_rank=dense_ranks.get(uid), sparse_rank=sparse_ranks.get(uid),
                    payload=payload,
                )
            )

        scored_results.sort(key=lambda r: r.score, reverse=True)
        return scored_results[:limit]
    except ValueError:
        raise
    except Exception as e:
        err_str = str(e).lower()
        if "dimension" in err_str or "size" in err_str or "mismatch" in err_str:
            msg = f"Vector dimension mismatch during Qdrant search in collection '{collection_name}': {e}. An index rebuild is required."
            logger.error(msg)
            raise ValueError(msg) from e
        logger.error(f"Error searching Qdrant collection '{collection_name}': {e}")
        return []


def execute_qdrant_file_chunks(
    client: QdrantClient,
    collection_name: str,
    path: str,
    repo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    try:
        if not client.collection_exists(collection_name):
            return []

        raw_path = (path or "").replace("\x00", "")
        clean_path = raw_path.replace("\\", "/").strip("/")
        rel_path = clean_path.split("://", 1)[1] if "://" in clean_path else clean_path
        if repo and rel_path.startswith(f"{repo}/"):
            rel_path = rel_path[len(repo) + 1:]

        must_conditions = []
        if repo and repo not in ("__all__", "all"):
            must_conditions.append(qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo)))

        should_conditions = [
            qmodels.FieldCondition(key="rel_path", match=qmodels.MatchValue(value=rel_path)),
            qmodels.FieldCondition(key="path", match=qmodels.MatchValue(value=raw_path)),
            qmodels.FieldCondition(key="rel_path", match=qmodels.MatchValue(value=raw_path)),
            qmodels.FieldCondition(key="path", match=qmodels.MatchValue(value=rel_path)),
        ]
        if clean_path != raw_path:
            should_conditions.append(qmodels.FieldCondition(key="path", match=qmodels.MatchValue(value=clean_path)))
            should_conditions.append(qmodels.FieldCondition(key="rel_path", match=qmodels.MatchValue(value=clean_path)))
        if repo and repo not in ("__all__", "all"):
            should_conditions.extend([
                qmodels.FieldCondition(key="path", match=qmodels.MatchValue(value=f"git://{repo}/{rel_path}")),
                qmodels.FieldCondition(key="path", match=qmodels.MatchValue(value=f"{repo}://{rel_path}")),
                qmodels.FieldCondition(key="path", match=qmodels.MatchValue(value=f"{repo}/{rel_path}")),
            ])

        filter_obj = qmodels.Filter(
            must=must_conditions if must_conditions else None,
            should=should_conditions,
        )

        all_records = []
        next_page_offset = None
        while True:
            records, next_page_offset = client.scroll(
                collection_name=collection_name,
                scroll_filter=filter_obj,
                limit=250,
                offset=next_page_offset,
                with_payload=True,
                with_vectors=False,
            )
            if records:
                all_records.extend(records)
            if not next_page_offset:
                break

        payloads = [dict(r.payload or {}) for r in all_records]
        payloads.sort(key=lambda p: (p.get("start_line") or 0, p.get("end_line") or 0))
        return payloads
    except Exception as e:
        logger.error(f"Error fetching file chunks from Qdrant: {e}")
        return []


def execute_qdrant_grep_chunks(
    client: QdrantClient,
    collection_name: str,
    pattern: str,
    repo: Optional[str] = None,
    path_glob: Optional[str] = None,
    is_regex: bool = False,
    case_sensitive: bool = False,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    clean_pattern = (pattern or "").replace("\x00", "")
    if not clean_pattern:
        return []

    flags = 0 if case_sensitive else re.IGNORECASE
    regex_pat = clean_pattern if is_regex else re.escape(clean_pattern)
    try:
        compiled = re.compile(regex_pat, flags)
    except re.error as e:
        raise ValueError(f"Invalid regular expression pattern: {e}") from e

    try:
        if not client.collection_exists(collection_name):
            return []

        must_conditions = []
        if repo and repo not in ("__all__", "all"):
            must_conditions.append(qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo.replace("\x00", ""))))
        scroll_filter = qmodels.Filter(must=must_conditions) if must_conditions else None

        matched_chunks: List[Dict[str, Any]] = []
        next_offset = None
        while True:
            records, next_offset = client.scroll(
                collection_name=collection_name,
                scroll_filter=scroll_filter,
                limit=250,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            for r in (records or []):
                payload = dict(r.payload or {})
                chunk_path = payload.get("rel_path") or payload.get("path") or ""
                if path_glob:
                    norm_p = chunk_path.replace("\\", "/")
                    norm_glob = path_glob.replace("\\", "/")
                    if not (fnmatch.fnmatch(norm_p, norm_glob) or fnmatch.fnmatch(os.path.basename(norm_p), norm_glob)):
                        continue

                text_content = payload.get("content") or payload.get("text") or ""
                if compiled.search(text_content):
                    matched_chunks.append(payload)
                    if len(matched_chunks) >= limit:
                        break
            if len(matched_chunks) >= limit or not next_offset:
                break
        return matched_chunks[:limit]
    except Exception as e:
        logger.error(f"Error running grep_chunks on Qdrant: {e}")
        raise

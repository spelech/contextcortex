import json
import logging
import math
import os
import re
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy import Engine, text

from app.services.vector_store.base import VectorSearchResult
from app.services.vector_store.pgvector_chunk_scanner import (
    execute_pgvector_file_chunks,
    execute_pgvector_grep_chunks,
    hydrate_chunk_row as _hydrate_chunk_row,
    parse_json_payload,
)

logger = logging.getLogger("contextcortex.vector_store.pgvector")

_SEARCH_MODE_ALIASES = {
    "keyword": "lexical",
    "keywords": "lexical",
    "bm25": "lexical",
    "fulltext": "lexical",
    "fts": "lexical",
    "vector": "semantic",
    "dense": "semantic",
    "sparse": "lexical",
}

_FTS_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could",
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "if",
    "in", "into", "is", "it", "its", "may", "might", "not", "of", "on", "or",
    "our", "should", "so", "such", "than", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "to", "too", "up", "use", "used",
    "using", "was", "we", "were", "what", "when", "where", "which", "who",
    "why", "will", "with", "would", "you", "your",
})


def sanitize_fts_query_text(query_text: str) -> str:
    """Removes NUL bytes and normalizes control characters for safe PostgreSQL websearch_to_tsquery execution."""
    if not query_text:
        return ""
    return query_text.replace("\x00", " ").strip()


def _build_or_tsquery(query_text: str) -> str:
    """Builds a safe PostgreSQL tsquery string joining significant alphanumeric tokens with '|' (OR)."""
    cleaned = sanitize_fts_query_text(query_text).lower()
    if not cleaned:
        return ""

    raw_tokens = re.findall(r"[a-z0-9_]{2,}", cleaned)
    if re.search(r"(?<![a-z0-9_])c#", cleaned):
        raw_tokens.insert(0, "c")
    if re.search(r"(?<![a-z0-9_])f#", cleaned):
        raw_tokens.insert(0, "f")

    if not raw_tokens:
        single_tokens = re.findall(r"[a-z0-9_]+", cleaned)
        raw_tokens = single_tokens

    if not raw_tokens:
        return ""

    filtered = [t for t in raw_tokens if t not in _FTS_STOPWORDS]
    tokens = filtered if filtered else raw_tokens
    seen: List[str] = []
    for t in tokens:
        if re.fullmatch(r"[a-z0-9_]+", t) and t not in seen:
            seen.append(t)
        if len(seen) >= 16:
            break
    return " | ".join(seen)



def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a <= 1e-12 or norm_b <= 1e-12:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _execute_sqlite_fallback_search(
    engine: Engine,
    table_name: str,
    collection_name: str,
    dimension: int,
    clean_query: str,
    mode: str,
    alpha: float,
    limit: int,
    doc_type: Optional[str],
    repo: Optional[str],
    language: Optional[str],
    category: Optional[str],
    tag: Optional[str],
    embed_fn: Callable[[str], List[float]],
) -> List[VectorSearchResult]:
    conditions = ["collection_name = :collection_name"]
    params: Dict[str, Any] = {"collection_name": collection_name}
    if doc_type:
        if doc_type == "doc":
            conditions.append("doc_type IN ('doc', 'pdf')")
        else:
            conditions.append("doc_type = :doc_type")
            params["doc_type"] = doc_type
    if repo:
        conditions.append("repo = :repo")
        params["repo"] = repo
    if language:
        conditions.append("language = :language")
        params["language"] = language
    if category:
        conditions.append("category = :category")
        params["category"] = category

    sql = text(
        f"SELECT id, title, symbol, path, content, tags, embedding, payload "
        f"FROM {table_name} WHERE {' AND '.join(conditions)}"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().fetchall()

    query_vec: Optional[List[float]] = None
    if mode in ("semantic", "hybrid") and alpha > 0.0:
        query_vec = embed_fn(clean_query)
        if len(query_vec) != dimension:
            raise ValueError(
                f"Vector dimension mismatch: query vector ({len(query_vec)}d) does not match "
                f"PgVectorStore table '{table_name}' ({dimension}d). An index rebuild is required."
            )

    tsq_str = _build_or_tsquery(clean_query)
    lex_tokens = [t for t in tsq_str.split(" | ") if t] if tsq_str else []
    needle_low = clean_query.lower()

    scored = []
    for row in rows:
        if tag:
            raw_tags = parse_json_payload(row["tags"]) if isinstance(row["tags"], str) else row["tags"]
            tag_list = raw_tags if isinstance(raw_tags, list) else (json.loads(row["tags"]) if isinstance(row["tags"], str) and row["tags"].startswith("[") else [])
            if tag not in tag_list:
                continue

        d_score = 0.0
        if query_vec is not None and row["embedding"]:
            try:
                emb_val = json.loads(row["embedding"]) if isinstance(row["embedding"], str) else row["embedding"]
                d_score = _cosine_similarity(query_vec, emb_val)
            except Exception:
                d_score = 0.0

        blob = " ".join(str(row[k] or "") for k in ("title", "symbol", "path", "content")).lower()
        s_score = 0.0
        if lex_tokens:
            hits = sum(1 for tok in lex_tokens if tok in blob)
            s_score = hits / len(lex_tokens)
        elif needle_low and needle_low in blob:
            s_score = 1.0

        if mode == "lexical" and s_score <= 0.0 and needle_low not in blob:
            continue
        if needle_low and needle_low in blob and mode in ("lexical", "hybrid"):
            s_score = max(s_score, 1.0)

        scored.append({
            "id": str(row["id"]),
            "dense_score": d_score,
            "sparse_score": s_score,
            "payload": parse_json_payload(row["payload"]),
        })

    if mode == "semantic":
        scored.sort(key=lambda x: x["dense_score"], reverse=True)
        return [
            VectorSearchResult(
                id=it["id"], score=round(it["dense_score"], 4), dense_score=round(it["dense_score"], 4),
                sparse_score=0.0, dense_rank=idx, sparse_rank=None, payload=it["payload"],
            )
            for idx, it in enumerate(scored[:limit], start=1)
        ]
    if mode == "lexical":
        scored.sort(key=lambda x: x["sparse_score"], reverse=True)
        return [
            VectorSearchResult(
                id=it["id"], score=round(it["sparse_score"], 4), dense_score=0.0,
                sparse_score=round(it["sparse_score"], 4), dense_rank=None, sparse_rank=idx, payload=it["payload"],
            )
            for idx, it in enumerate(scored[:limit], start=1)
        ]

    for it in scored:
        it["combined"] = (alpha * it["dense_score"]) + ((1.0 - alpha) * it["sparse_score"])
    scored.sort(key=lambda x: x["combined"], reverse=True)
    return [
        VectorSearchResult(
            id=it["id"], score=round(it["combined"], 4), dense_score=round(it["dense_score"], 4),
            sparse_score=round(it["sparse_score"], 4), dense_rank=idx, sparse_rank=idx if it["sparse_score"] > 0 else None,
            payload=it["payload"],
        )
        for idx, it in enumerate(scored[:limit], start=1)
    ]


def execute_pgvector_search(
    engine: Engine,
    table_name: str,
    collection_name: str,
    dimension: int,
    supported_modes: List[str],
    embed_fn: Callable[[str], List[float]],
    query_text: str,
    doc_type: Optional[str] = None,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 5,
    dense_weight: Optional[float] = None,
    search_mode: str = "semantic",
) -> List[VectorSearchResult]:
    clean_query = sanitize_fts_query_text(query_text)
    if not clean_query:
        return []

    raw_mode = (search_mode or "semantic").lower().strip()
    mode = _SEARCH_MODE_ALIASES.get(raw_mode, raw_mode)
    if mode not in supported_modes:
        raise ValueError(
            f"Search mode '{search_mode}' is not supported by PgVector vector store. "
            f"Supported modes: {supported_modes}"
        )

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

    if getattr(engine.dialect, "name", "") == "sqlite":
        return _execute_sqlite_fallback_search(
            engine=engine, table_name=table_name, collection_name=collection_name,
            dimension=dimension, clean_query=clean_query, mode=mode, alpha=alpha,
            limit=limit, doc_type=doc_type, repo=repo, language=language,
            category=category, tag=tag, embed_fn=embed_fn,
        )

    try:
        conditions = ["collection_name = :collection_name"]
        params: Dict[str, Any] = {"collection_name": collection_name, "limit": limit}

        if doc_type:
            if doc_type == "doc":
                conditions.append("doc_type IN ('doc', 'pdf')")
            else:
                conditions.append("doc_type = :doc_type")
                params["doc_type"] = doc_type.replace("\x00", "")
        if repo:
            conditions.append("repo = :repo")
            params["repo"] = repo.replace("\x00", "")
        if language:
            conditions.append("language = :language")
            params["language"] = language.replace("\x00", "")
        if category:
            conditions.append("category = :category")
            params["category"] = category.replace("\x00", "")
        if tag:
            clean_tag = tag.replace("\x00", "")
            esc_tag = clean_tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("(tags @> CAST(:tag_json AS jsonb) OR tags::text LIKE :tag_like ESCAPE '\\')")
            params["tag_json"] = json.dumps([clean_tag])
            params["tag_like"] = f'%"{esc_tag}"%'

        where_clause = " AND ".join(conditions)
        fts_expr = (
            "to_tsvector('simple', COALESCE(title, '') || ' ' || COALESCE(symbol, '') || ' ' || COALESCE(path, '') || ' ' || COALESCE(content, ''))"
        )
        or_tsq = _build_or_tsquery(clean_query)
        if or_tsq:
            params["tsq_or"] = or_tsq
            tsq_expr = "(websearch_to_tsquery('simple', :query_text) || to_tsquery('simple', :tsq_or))"
        else:
            tsq_expr = "websearch_to_tsquery('simple', :query_text)"

        # 1. Pure Semantic Search
        if mode == "semantic" or (mode == "hybrid" and alpha >= 1.0):
            query_vec = embed_fn(clean_query)
            if len(query_vec) != dimension:
                msg = f"Vector dimension mismatch: query vector ({len(query_vec)}d) does not match PgVectorStore table '{table_name}' ({dimension}d). An index rebuild is required."
                logger.error(msg)
                raise ValueError(msg)

            params["query_vec"] = str(query_vec)
            search_sql = text(f"""
            SELECT id, (1 - (embedding <=> CAST(:query_vec AS vector))) AS score, payload
            FROM {table_name}
            WHERE {where_clause}
            ORDER BY embedding <=> CAST(:query_vec AS vector)
            LIMIT :limit;
            """)
            with engine.connect() as conn:
                rows = conn.execute(search_sql, params).mappings().fetchall()

            results: List[VectorSearchResult] = []
            for rank_idx, row in enumerate(rows, start=1):
                score = max(0.0, min(1.0, float(row["score"]) if row["score"] is not None else 0.0))
                results.append(
                    VectorSearchResult(
                        id=str(row["id"]), score=round(score, 4), dense_score=round(score, 4),
                        sparse_score=0.0, dense_rank=rank_idx, sparse_rank=None,
                        payload=parse_json_payload(row["payload"]),
                    )
                )
            return results

        # 2. Pure Lexical Search
        if mode == "lexical" or (mode == "hybrid" and alpha <= 0.0):
            params["query_text"] = clean_query
            lexical_sql = text(f"""
            SELECT id, ts_rank_cd({fts_expr}, {tsq_expr}) AS sparse_score, payload
            FROM {table_name}
            WHERE {where_clause} AND {fts_expr} @@ {tsq_expr}
            ORDER BY sparse_score DESC
            LIMIT :limit;
            """)
            with engine.connect() as conn:
                rows = conn.execute(lexical_sql, params).mappings().fetchall()

            max_sparse = max((float(r["sparse_score"] or 0.0) for r in rows), default=1.0) or 1.0
            results = []
            for rank_idx, row in enumerate(rows, start=1):
                norm_s = max(0.0, min(1.0, float(row["sparse_score"] or 0.0) / max_sparse))
                results.append(
                    VectorSearchResult(
                        id=str(row["id"]), score=round(norm_s, 4), dense_score=0.0,
                        sparse_score=round(norm_s, 4), dense_rank=None, sparse_rank=rank_idx,
                        payload=parse_json_payload(row["payload"]),
                    )
                )
            return results

        # 3. Hybrid Search
        query_vec = embed_fn(clean_query)
        if len(query_vec) != dimension:
            msg = f"Vector dimension mismatch: query vector ({len(query_vec)}d) does not match PgVectorStore table '{table_name}' ({dimension}d). An index rebuild is required."
            logger.error(msg)
            raise ValueError(msg)

        params["query_vec"] = str(query_vec)
        params["query_text"] = clean_query
        params["candidate_limit"] = max(limit * 5, 50)

        dense_sql = text(f"""
        SELECT id, (1 - (embedding <=> CAST(:query_vec AS vector))) AS score, payload
        FROM {table_name}
        WHERE {where_clause}
        ORDER BY embedding <=> CAST(:query_vec AS vector)
        LIMIT :candidate_limit;
        """)
        lexical_sql = text(f"""
        SELECT id, ts_rank_cd({fts_expr}, {tsq_expr}) AS sparse_score, payload
        FROM {table_name}
        WHERE {where_clause} AND {fts_expr} @@ {tsq_expr}
        ORDER BY sparse_score DESC
        LIMIT :candidate_limit;
        """)

        with engine.connect() as conn:
            dense_rows = conn.execute(dense_sql, params).mappings().fetchall()
            lexical_rows = conn.execute(lexical_sql, params).mappings().fetchall()

        merged: Dict[str, Dict[str, Any]] = {}
        for d_rank, row in enumerate(dense_rows, start=1):
            doc_id = str(row["id"])
            merged[doc_id] = {
                "id": doc_id,
                "dense_score": max(0.0, min(1.0, float(row["score"] or 0.0))),
                "sparse_score": 0.0,
                "dense_rank": d_rank,
                "sparse_rank": None,
                "payload": parse_json_payload(row["payload"]),
            }

        max_sparse = max((float(r["sparse_score"] or 0.0) for r in lexical_rows), default=1.0) or 1.0
        for s_rank, row in enumerate(lexical_rows, start=1):
            doc_id = str(row["id"])
            norm_s = max(0.0, min(1.0, float(row["sparse_score"] or 0.0) / max_sparse))
            if doc_id in merged:
                merged[doc_id]["sparse_score"] = norm_s
                merged[doc_id]["sparse_rank"] = s_rank
            else:
                merged[doc_id] = {
                    "id": doc_id, "dense_score": 0.0, "sparse_score": norm_s,
                    "dense_rank": None, "sparse_rank": s_rank,
                    "payload": parse_json_payload(row["payload"]),
                }

        fused: List[VectorSearchResult] = []
        for item in merged.values():
            combined = (alpha * item["dense_score"]) + ((1.0 - alpha) * item["sparse_score"])
            fused.append(
                VectorSearchResult(
                    id=item["id"], score=round(combined, 4),
                    dense_score=round(item["dense_score"], 4), sparse_score=round(item["sparse_score"], 4),
                    dense_rank=item["dense_rank"], sparse_rank=item["sparse_rank"],
                    payload=item["payload"],
                )
            )
        fused.sort(key=lambda r: r.score, reverse=True)
        return fused[:limit]
    except ValueError:
        raise
    except Exception as e:
        err_str = str(e).lower()
        if "dimension" in err_str or "different size" in err_str or "mismatch" in err_str:
            msg = f"Vector dimension mismatch during PgVector search in table '{table_name}': {e}. An index rebuild is required."
            logger.error(msg)
            raise ValueError(msg) from e
        logger.error(f"Error searching PgVectorStore table '{table_name}': {e}", exc_info=True)
        return []


__all__ = [
    "_FTS_STOPWORDS",
    "_SEARCH_MODE_ALIASES",
    "_build_or_tsquery",
    "execute_pgvector_file_chunks",
    "execute_pgvector_grep_chunks",
    "execute_pgvector_search",
    "parse_json_payload",
    "sanitize_fts_query_text",
]


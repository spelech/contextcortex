import json
import logging
from typing import List, Dict, Any, Optional
from app.services.database.connection import get_db_connection

logger = logging.getLogger("contextcortex.db.embedding_cache")

def get_cached_embeddings_batch(chunk_hashes: List[str], model_name: str) -> Dict[str, Dict[str, Any]]:
    if not chunk_hashes:
        return {}
    results: Dict[str, Dict[str, Any]] = {}
    placeholders = ",".join("?" for _ in chunk_hashes)
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT chunk_hash, dense_vector, sparse_indices, sparse_values FROM embedding_cache WHERE model_name = ? AND chunk_hash IN ({placeholders})",
            [model_name] + list(chunk_hashes)
        ).fetchall()
        for r in rows:
            try:
                dense = json.loads(r["dense_vector"]) if r["dense_vector"] else None
                s_indices = json.loads(r["sparse_indices"]) if r["sparse_indices"] else None
                s_values = json.loads(r["sparse_values"]) if r["sparse_values"] else None
                results[r["chunk_hash"]] = {
                    "dense": dense,
                    "sparse_indices": s_indices,
                    "sparse_values": s_values
                }
            except Exception as e:
                logger.warning(f"Error decoding cached embedding for hash {r['chunk_hash']}: {e}")
    return results

def set_cached_embeddings_batch(items: List[Dict[str, Any]]) -> None:
    if not items:
        return
    rows_to_insert = []
    for item in items:
        dense_json = json.dumps(item["dense_vector"]) if item.get("dense_vector") is not None else None
        sparse_indices_json = json.dumps(item["sparse_indices"]) if item.get("sparse_indices") is not None else None
        sparse_values_json = json.dumps(item["sparse_values"]) if item.get("sparse_values") is not None else None
        model = item.get("model_name", "BAAI/bge-small-en-v1.5")
        rows_to_insert.append((
            item["chunk_hash"],
            dense_json,
            sparse_indices_json,
            sparse_values_json,
            model
        ))
    with get_db_connection() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO embedding_cache (chunk_hash, dense_vector, sparse_indices, sparse_values, model_name)
               VALUES (?, ?, ?, ?, ?)""",
            rows_to_insert
        )
        conn.commit()

def invalidate_cache_by_model(model_name: Optional[str] = None) -> int:
    with get_db_connection() as conn:
        if model_name:
            cur = conn.execute("DELETE FROM embedding_cache WHERE model_name = ?", (model_name,))
        else:
            cur = conn.execute("DELETE FROM embedding_cache")
        conn.commit()
        return cur.rowcount

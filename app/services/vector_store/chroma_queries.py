import fnmatch
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

from app.services.vector_store.base import VectorSearchResult

logger = logging.getLogger("contextcortex.vector_store.chroma")


def build_chroma_where_filter(
    doc_type: Optional[str] = None,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    conditions: List[Dict[str, Any]] = []
    if doc_type:
        clean_dt = doc_type.replace("\x00", "")
        if clean_dt == "doc":
            conditions.append({"doc_type": {"$in": ["doc", "pdf"]}})
        else:
            conditions.append({"doc_type": {"$eq": clean_dt}})
    if repo:
        conditions.append({"repo": {"$eq": repo.replace("\x00", "")}})
    if language:
        conditions.append({"language": {"$eq": language.replace("\x00", "")}})
    if category:
        conditions.append({"category": {"$eq": category.replace("\x00", "")}})
    if tag:
        conditions.append({"tags": {"$contains": tag.replace("\x00", "")}})

    if len(conditions) == 1:
        return conditions[0]
    if len(conditions) > 1:
        return {"$and": conditions}
    return None


def execute_chroma_search(
    collection: Any,
    collection_name: str,
    supported_modes: List[str],
    dense_embed_fn: Callable[[str], List[float]],
    query_text: str,
    doc_type: Optional[str] = None,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 5,
    search_mode: str = "semantic",
) -> List[VectorSearchResult]:
    clean_query = (query_text or "").replace("\x00", " ").strip()
    if not clean_query:
        return []

    mode = (search_mode or "semantic").lower().strip()
    if mode not in supported_modes:
        raise ValueError(
            f"Search mode '{search_mode}' is not supported by Chroma vector store. "
            f"Supported modes: {supported_modes}"
        )

    try:
        dense_vec = dense_embed_fn(clean_query)
        where_filter = build_chroma_where_filter(
            doc_type=doc_type, repo=repo, language=language, category=category, tag=tag,
        )

        query_kwargs: Dict[str, Any] = {
            "query_embeddings": [dense_vec],
            "n_results": limit,
        }
        if where_filter:
            query_kwargs["where"] = where_filter

        response = collection.query(**query_kwargs)
        results: List[VectorSearchResult] = []
        if response and response.get("ids") and len(response["ids"]) > 0:
            ids_list = response["ids"][0]
            distances = response.get("distances", [[]])[0] if response.get("distances") else []
            metadatas = response.get("metadatas", [[]])[0] if response.get("metadatas") else []
            documents = response.get("documents", [[]])[0] if response.get("documents") else []

            for i, doc_id in enumerate(ids_list):
                dist = distances[i] if i < len(distances) and distances[i] is not None else 0.0
                score = float(max(0.0, 1.0 - dist))
                payload = dict(metadatas[i]) if i < len(metadatas) and metadatas[i] is not None else {}
                if "content" not in payload and i < len(documents) and documents[i]:
                    payload["content"] = documents[i]

                results.append(
                    VectorSearchResult(
                        id=str(doc_id), score=round(score, 4),
                        dense_score=round(score, 4), sparse_score=0.0,
                        dense_rank=i + 1, sparse_rank=None,
                        payload=payload,
                    )
                )
        return results
    except ValueError:
        raise
    except Exception as e:
        err_str = str(e).lower()
        if "dimension" in err_str or "size" in err_str or "mismatch" in err_str:
            msg = f"Vector dimension mismatch during Chroma search in collection '{collection_name}': {e}. An index rebuild is required."
            logger.error(msg)
            raise ValueError(msg) from e
        logger.error(f"Error searching Chroma collection '{collection_name}': {e}")
        return []


def execute_chroma_file_chunks(
    collection: Any,
    path: str,
    repo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    try:
        raw_path = (path or "").replace("\x00", "")
        clean_path = raw_path.replace("\\", "/").strip("/")
        rel_path = clean_path.split("://", 1)[1] if "://" in clean_path else clean_path
        if repo and rel_path.startswith(f"{repo}/"):
            rel_path = rel_path[len(repo) + 1:]

        candidates = {raw_path, clean_path, rel_path}
        if repo and repo not in ("__all__", "all"):
            candidates.update({f"{repo}://{rel_path}", f"git://{repo}/{rel_path}", f"{repo}/{rel_path}"})

        res = collection.get(include=["metadatas", "documents"])
        chunks = []
        if res and res.get("metadatas"):
            for idx, meta in enumerate(res["metadatas"]):
                payload = dict(meta or {})
                doc_text = res["documents"][idx] if res.get("documents") and idx < len(res["documents"]) else ""
                if "content" not in payload and doc_text:
                    payload["content"] = doc_text
                p_repo = payload.get("repo")
                p_path = (payload.get("path") or "").replace("\\", "/")
                p_rel = (payload.get("rel_path") or "").replace("\\", "/")
                if repo and repo not in ("__all__", "all") and p_repo != repo:
                    continue
                if payload.get("path") in candidates or payload.get("rel_path") in candidates or p_path in candidates or p_rel in candidates:
                    chunks.append(payload)

        chunks.sort(key=lambda p: (p.get("start_line") or 0, p.get("end_line") or 0))
        return chunks
    except Exception as e:
        logger.error(f"Error fetching file chunks from Chroma: {e}")
        return []


def execute_chroma_grep_chunks(
    collection: Any,
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
        res = collection.get(include=["metadatas", "documents"])
        matched = []
        if res and res.get("metadatas"):
            for idx, meta in enumerate(res["metadatas"]):
                payload = dict(meta or {})
                doc_text = res["documents"][idx] if res.get("documents") and idx < len(res["documents"]) else ""
                if "content" not in payload and doc_text:
                    payload["content"] = doc_text

                if repo and repo not in ("__all__", "all") and payload.get("repo") != repo:
                    continue

                chunk_path = payload.get("rel_path") or payload.get("path") or ""
                if path_glob:
                    norm_p = chunk_path.replace("\\", "/")
                    norm_glob = path_glob.replace("\\", "/")
                    if not (fnmatch.fnmatch(norm_p, norm_glob) or fnmatch.fnmatch(os.path.basename(norm_p), norm_glob)):
                        continue

                content = payload.get("content") or ""
                if compiled.search(content):
                    matched.append(payload)
                    if len(matched) >= limit:
                        break
        return matched[:limit]
    except Exception as e:
        logger.error(f"Error in Chroma grep_chunks: {e}")
        raise

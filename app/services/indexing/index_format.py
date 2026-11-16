"""Index format fingerprint: detects when stored chunks were built with other chunking settings.

When the fingerprint of a source (the local paths, or one Git repository) differs from the
current one, the next full indexing pass reprocesses all files of that source once.
"""
import hashlib
import json

import app.services.database as db_service
import app.services.indexing.state as idx_state

# Increase this value when a change to chunking or symbol extraction makes old chunks stale.
INDEX_FORMAT_VERSION = 1

_KEY_PREFIX = "index_format"


def current_fingerprint() -> str:
    """Returns a stable hash of the settings that control how files become chunks."""
    try:
        import app.services.embeddings as emb
        dense_model = getattr(emb, "REQUESTED_DENSE_MODEL", "") or ""
    except Exception:
        dense_model = ""
    payload = {
        "version": INDEX_FORMAT_VERSION,
        "chunk_size": idx_state.CHUNK_SIZE,
        "code_chunk_size": idx_state.CODE_CHUNK_SIZE,
        "chunk_overlap": idx_state.CHUNK_OVERLAP,
        "dense_model": dense_model,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _key(source: str) -> str:
    return f"{_KEY_PREFIX}:{source}"


def is_stale(source: str, fingerprint: str) -> bool:
    """True if the source has no stored fingerprint or a different one."""
    return db_service.get_metadata(_key(source), None) != fingerprint


def mark_current(source: str, fingerprint: str) -> None:
    db_service.set_metadata(_key(source), fingerprint)

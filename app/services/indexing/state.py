import os
import threading
import asyncio
import logging
from typing import Set
from app.services.vector_store import get_vector_store

logger = logging.getLogger('contextcortex.indexer')

VAULT_PATH = os.getenv("VAULT_PATH", "/docs")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "knowledge_rag_v1")

active_sessions = set()
main_event_loop = None

async def notify_list_changed():
    if not active_sessions:
        return
    logger.info(f"Sending list_changed notifications to {len(active_sessions)} active sessions...")
    for session in list(active_sessions):
        try:
            await session.send_tool_list_changed()
            await session.send_prompt_list_changed()
            await session.send_resource_list_changed()
        except Exception as e:
            logger.warning(f"Failed to send list_changed notification to session: {e}")

def trigger_list_changed_notification():
    import sys
    idx_mod = sys.modules.get("app.services.indexer")
    loop = getattr(idx_mod, "main_event_loop", main_event_loop) if idx_mod else main_event_loop
    if loop and loop.is_running():
        asyncio_mod = getattr(idx_mod, "asyncio", asyncio) if idx_mod else asyncio
        asyncio_mod.run_coroutine_threadsafe(notify_list_changed(), loop)

indexing_lock = threading.Lock()
is_indexing = False

def ensure_collection() -> bool:
    """Ensures that the vector store collection/index exists."""
    try:
        import sys
        idx_mod = sys.modules.get("app.services.indexer")
        _g_store = getattr(idx_mod, "get_vector_store", get_vector_store) if idx_mod else get_vector_store
        store = _g_store()
        return store.ensure_collection()
    except Exception as e:
        logger.error(f"Failed to ensure vector store collection: {e}")
        return False

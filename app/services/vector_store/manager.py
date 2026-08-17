"""Vector store manager and dynamic backend switcher."""

import os
import logging
import threading
from typing import Optional, Dict, Any, Tuple, Callable, List

from app.services.db import get_vector_store_db_config, set_vector_store_db_config
from app.services.vector_store.base import VectorStore
from app.services.vector_store.qdrant_store import QdrantVectorStore
from app.services.vector_store.chroma_store import ChromaVectorStore

logger = logging.getLogger("notes-rag-mcp.vector_store.manager")

SUPPORTED_PROVIDERS = {"qdrant", "chroma", "chromadb"}
SUPPORTED_MODES = {"embedded", "persistent", "memory", "remote"}


class VectorStoreManager:
    """
    Thread-safe manager for VectorStore instances, providing dynamic backend switching,
    configuration persistence in SQLite system_metadata, and health/stats aggregation.
    """

    _instance_lock = threading.RLock()
    _active_store: Optional[VectorStore] = None
    _active_config: Optional[Dict[str, str]] = None
    _reindex_callbacks: List[Callable[[], None]] = []

    @classmethod
    def reset_instance(cls):
        """Resets the singleton store instance (useful for test isolation)."""
        with cls._instance_lock:
            if cls._active_store is not None:
                try:
                    cls._active_store.close()
                except Exception:
                    pass
            cls._active_store = None
            cls._active_config = None

    @classmethod
    def register_reindex_callback(cls, callback: Callable[[], None]):
        """Registers a callback to be invoked when the vector store backend is switched."""
        with cls._instance_lock:
            if callback not in cls._reindex_callbacks:
                cls._reindex_callbacks.append(callback)

    @classmethod
    def unregister_reindex_callback(cls, callback: Callable[[], None]):
        """Unregisters a previously registered reindex callback."""
        with cls._instance_lock:
            if callback in cls._reindex_callbacks:
                cls._reindex_callbacks.remove(callback)

    @classmethod
    def _create_store(cls, config: Dict[str, str]) -> VectorStore:
        """Instantiates a VectorStore implementation according to the given config dict."""
        provider = config.get("provider", "qdrant").lower().strip()
        mode = config.get("mode", "embedded").lower().strip()
        storage_path = config.get("storage_path")
        url = config.get("url", "").strip()
        collection = config.get("collection", "knowledge_rag_v1").strip()

        if provider == "qdrant":
            if mode == "remote":
                return QdrantVectorStore(
                    url=url if url else None,
                    collection_name=collection,
                    prefer_remote=True,
                    auto_init=True,
                )
            else:
                return QdrantVectorStore(
                    storage_path=storage_path,
                    collection_name=collection,
                    prefer_remote=False,
                    auto_init=True,
                )
        elif provider in ("chroma", "chromadb"):
            if mode == "remote":
                return ChromaVectorStore(
                    url=url if url else None,
                    collection_name=collection,
                    prefer_remote=True,
                    auto_init=True,
                )
            else:
                return ChromaVectorStore(
                    storage_path=storage_path,
                    collection_name=collection,
                    prefer_remote=False,
                    auto_init=True,
                )
        else:
            raise ValueError(f"Unsupported vector store provider: {provider}")

    @classmethod
    def get_vector_store(cls, force_reload: bool = False) -> VectorStore:
        """
        Retrieves the active VectorStore singleton instance based on SQLite system_metadata.
        If force_reload is True or the configuration has changed, re-instantiates the store.
        """
        with cls._instance_lock:
            current_config = get_vector_store_db_config()
            if (
                cls._active_store is None
                or force_reload
                or cls._active_config != current_config
            ):
                if cls._active_store is not None:
                    try:
                        cls._active_store.close()
                    except Exception:
                        pass
                logger.info(
                    f"Instantiating vector store: provider={current_config['provider']}, "
                    f"mode={current_config['mode']}, collection={current_config['collection']}"
                )
                cls._active_store = cls._create_store(current_config)
                cls._active_config = current_config
            return cls._active_store


    @classmethod
    def get_vector_store_config(cls) -> Dict[str, Any]:
        """
        Returns the active vector store configuration along with live health check and stats.
        """
        with cls._instance_lock:
            cfg = get_vector_store_db_config()
            try:
                store = cls.get_vector_store()
                healthy, health_msg = store.health_check()
                stats = store.get_stats()
            except Exception as e:
                healthy = False
                health_msg = f"Error connecting to vector store: {e}"
                stats = {"error": str(e)}

            return {
                "provider": cfg["provider"],
                "mode": cfg["mode"],
                "storage_path": cfg["storage_path"],
                "url": cfg["url"],
                "collection": cfg["collection"],
                "healthy": healthy,
                "health_message": health_msg,
                "stats": stats,
            }

    @classmethod
    def switch_vector_store(
        cls,
        provider: str,
        mode: Optional[str] = None,
        storage_path: Optional[str] = None,
        url: Optional[str] = None,
        collection: Optional[str] = None,
        reindex_callback: Optional[Callable[[], None]] = None,
    ) -> Tuple[bool, str]:
        """
        Validates parameters, updates SQLite system_metadata, re-initializes the active
        VectorStore instance, verifies collection health, and invokes re-index callbacks.
        """
        with cls._instance_lock:
            prov = (provider or "").lower().strip()
            if prov not in SUPPORTED_PROVIDERS:
                return False, f"Unsupported provider: '{provider}'. Supported: {sorted(SUPPORTED_PROVIDERS)}"

            current_cfg = get_vector_store_db_config()
            target_mode = (mode.lower().strip() if mode else current_cfg.get("mode", "embedded"))
            if target_mode not in SUPPORTED_MODES:
                return False, f"Unsupported mode: '{mode}'. Supported: {sorted(SUPPORTED_MODES)}"

            target_storage = storage_path if storage_path is not None else current_cfg.get("storage_path")
            target_url = url if url is not None else current_cfg.get("url", "")
            target_collection = collection.strip() if collection else current_cfg.get("collection", "knowledge_rag_v1")

            if target_mode == "remote" and not target_url.strip():
                return False, "Remote mode requires a valid non-empty URL."

            new_config = {
                "provider": prov,
                "mode": target_mode,
                "storage_path": target_storage,
                "url": target_url.strip(),
                "collection": target_collection,
            }

            try:
                # Test creating store and ensuring collection
                new_store = cls._create_store(new_config)
                ok = new_store.ensure_collection()
                if not ok:
                    return False, f"Failed to ensure collection '{target_collection}' on {prov} ({target_mode})"

                is_healthy, health_msg = new_store.health_check()
                if not is_healthy:
                    return False, f"Health check failed for {prov}: {health_msg}"

                # Persist settings in SQLite system_metadata
                set_vector_store_db_config(
                    provider=prov,
                    mode=target_mode,
                    storage_path=target_storage,
                    url=target_url.strip(),
                    collection=target_collection,
                )

                if cls._active_store is not None:
                    try:
                        cls._active_store.close()
                    except Exception:
                        pass

                cls._active_store = new_store
                cls._active_config = new_config


                # Execute re-index callbacks if provided
                if reindex_callback:
                    try:
                        reindex_callback()
                    except Exception as r_err:
                        logger.warning(f"Re-index callback encountered an error: {r_err}")

                for cb in cls._reindex_callbacks:
                    try:
                        cb()
                    except Exception as cb_err:
                        logger.warning(f"Registered re-index callback encountered an error: {cb_err}")

                return True, f"Successfully switched vector store to {prov} ({target_mode})"

            except Exception as e:
                logger.error(f"Failed to switch vector store: {e}", exc_info=True)
                return False, f"Failed to switch vector store: {str(e)}"

    @classmethod
    def test_connection(
        cls,
        provider: str,
        mode: Optional[str] = None,
        storage_path: Optional[str] = None,
        url: Optional[str] = None,
        collection: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Tests a candidate vector store connection without applying changes or modifying state.
        """
        prov = (provider or "").lower().strip()
        if prov not in SUPPORTED_PROVIDERS:
            return False, f"Unsupported provider: '{provider}'. Supported: {sorted(SUPPORTED_PROVIDERS)}"

        current_cfg = get_vector_store_db_config()
        target_mode = (mode.lower().strip() if mode else current_cfg.get("mode", "embedded"))
        if target_mode not in SUPPORTED_MODES:
            return False, f"Unsupported mode: '{mode}'. Supported: {sorted(SUPPORTED_MODES)}"

        target_storage = storage_path if storage_path is not None else current_cfg.get("storage_path")
        target_url = url if url is not None else current_cfg.get("url", "")
        target_collection = collection.strip() if collection else current_cfg.get("collection", "knowledge_rag_v1")

        if target_mode == "remote" and not target_url.strip():
            return False, "Remote mode requires a valid non-empty URL."

        test_config = {
            "provider": prov,
            "mode": target_mode,
            "storage_path": target_storage,
            "url": target_url.strip(),
            "collection": target_collection,
        }

        test_store = None
        try:
            test_store = cls._create_store(test_config)
            is_healthy, health_msg = test_store.health_check()
            return is_healthy, health_msg
        except Exception as e:
            return False, f"Connection test failed for {prov}: {str(e)}"
        finally:
            if test_store is not None:
                try:
                    test_store.close()
                except Exception:
                    pass


# Module-level convenience functions
def get_vector_store(force_reload: bool = False) -> VectorStore:
    """Retrieves the active VectorStore singleton."""
    return VectorStoreManager.get_vector_store(force_reload=force_reload)


def get_vector_store_config() -> Dict[str, Any]:
    """Retrieves the vector store configuration, health, and stats."""
    return VectorStoreManager.get_vector_store_config()


def switch_vector_store(
    provider: str,
    mode: Optional[str] = None,
    storage_path: Optional[str] = None,
    url: Optional[str] = None,
    collection: Optional[str] = None,
    reindex_callback: Optional[Callable[[], None]] = None,
) -> Tuple[bool, str]:
    """Dynamically switches the active vector store backend."""
    return VectorStoreManager.switch_vector_store(
        provider=provider,
        mode=mode,
        storage_path=storage_path,
        url=url,
        collection=collection,
        reindex_callback=reindex_callback,
    )


def test_vector_store_connection(
    provider: str,
    mode: Optional[str] = None,
    storage_path: Optional[str] = None,
    url: Optional[str] = None,
    collection: Optional[str] = None,
) -> Tuple[bool, str]:
    """Tests a candidate vector store connection."""
    return VectorStoreManager.test_connection(
        provider=provider,
        mode=mode,
        storage_path=storage_path,
        url=url,
        collection=collection,
    )


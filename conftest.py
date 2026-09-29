import os
import pytest
from unittest.mock import patch

if "QDRANT_URL" not in os.environ:
    os.environ["QDRANT_URL"] = "http://localhost:8010"


@pytest.fixture(autouse=True)
def stop_background_poller():
    from app.services.poller import stop_poller_daemon
    stop_poller_daemon()
    yield
    stop_poller_daemon()


@pytest.fixture(autouse=True)
def isolate_test_db(tmp_path, monkeypatch):
    """
    Prevents tests from mutating production/live database index_cache.db.
    Supplies an isolated SQLite DB and resets singleton engines between tests.
    """
    temp_db = str(tmp_path / "test_isolated_cache.db")
    temp_storage = str(tmp_path / "test_vector_storage")
    os.makedirs(temp_storage, exist_ok=True)

    monkeypatch.setenv("CACHE_DB_PATH", temp_db)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", temp_db, raising=False)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", temp_db, raising=False)
    monkeypatch.setenv("VECTOR_STORE_STORAGE_PATH", temp_storage)

    from app.services.database import init_db, get_db_engine
    from app.services.vector_store import VectorStoreManager

    get_db_engine(reset=True)
    try:
        init_db()
    except Exception:
        pass
    VectorStoreManager.reset_instance()

    yield temp_db

    get_db_engine(reset=True)
    VectorStoreManager.reset_instance()

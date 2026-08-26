import pytest
from app.services.database.connection import init_db, get_db_connection
from app.services.database.embedding_cache import (
    get_cached_embeddings_batch,
    set_cached_embeddings_batch,
    invalidate_cache_by_model,
)

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_cache.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", test_db)
    init_db()

def test_embedding_cache_set_and_get():
    items = [
        {
            "chunk_hash": "hash_abc_1",
            "dense_vector": [0.1, 0.2, 0.3],
            "sparse_indices": [10, 20],
            "sparse_values": [0.5, 0.8],
            "model_name": "BAAI/bge-small-en-v1.5",
        },
        {
            "chunk_hash": "hash_abc_2",
            "dense_vector": [0.4, 0.5, 0.6],
            "sparse_indices": None,
            "sparse_values": None,
            "model_name": "BAAI/bge-small-en-v1.5",
        },
    ]
    set_cached_embeddings_batch(items)

    res = get_cached_embeddings_batch(
        ["hash_abc_1", "hash_abc_2", "missing_hash"],
        model_name="BAAI/bge-small-en-v1.5",
    )
    assert "hash_abc_1" in res
    assert "hash_abc_2" in res
    assert "missing_hash" not in res
    assert res["hash_abc_1"]["dense"] == [0.1, 0.2, 0.3]
    assert res["hash_abc_1"]["sparse_indices"] == [10, 20]
    assert res["hash_abc_1"]["sparse_values"] == [0.5, 0.8]
    assert res["hash_abc_2"]["dense"] == [0.4, 0.5, 0.6]
    assert res["hash_abc_2"]["sparse_indices"] is None
    assert res["hash_abc_2"]["sparse_values"] is None

def test_embedding_cache_model_isolation():
    items = [
        {
            "chunk_hash": "hash_model_test",
            "dense_vector": [0.1, 0.2],
            "sparse_indices": None,
            "sparse_values": None,
            "model_name": "model_a",
        }
    ]
    set_cached_embeddings_batch(items)
    assert "hash_model_test" in get_cached_embeddings_batch(
        ["hash_model_test"], model_name="model_a"
    )
    assert "hash_model_test" not in get_cached_embeddings_batch(
        ["hash_model_test"], model_name="model_b"
    )

def test_embedding_cache_invalidation():
    items = [
        {
            "chunk_hash": "hash_inv_1",
            "dense_vector": [0.1, 0.2],
            "model_name": "model_a",
        },
        {
            "chunk_hash": "hash_inv_2",
            "dense_vector": [0.3, 0.4],
            "model_name": "model_b",
        },
    ]
    set_cached_embeddings_batch(items)
    # Invalidate model_a only
    deleted = invalidate_cache_by_model("model_a")
    assert deleted == 1
    assert "hash_inv_1" not in get_cached_embeddings_batch(
        ["hash_inv_1"], model_name="model_a"
    )
    assert "hash_inv_2" in get_cached_embeddings_batch(
        ["hash_inv_2"], model_name="model_b"
    )

    # Invalidate all
    deleted_all = invalidate_cache_by_model()
    assert deleted_all == 1
    assert "hash_inv_2" not in get_cached_embeddings_batch(
        ["hash_inv_2"], model_name="model_b"
    )

def test_embedding_cache_empty_inputs():
    assert get_cached_embeddings_batch([], model_name="model_a") == {}
    set_cached_embeddings_batch([])

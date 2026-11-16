"""Reindex when the index format (chunking settings) changes, and forced local sync."""
import os
from unittest.mock import patch

import pytest

import app.services.database as db_service
import app.services.indexing.index_format as index_format
from app.services.indexing.git_syncer import run_full_indexing
from app.services.indexing.local_syncer import sync_local_paths, sync_local_repo


class RecordingStore:
    """In-memory vector store that keeps chunks by id and counts upserts per path."""

    def __init__(self):
        self.docs = {}
        self.upserted_paths = []

    def ensure_collection(self):
        return True

    def delete_by_path(self, filepath):
        self.docs = {k: d for k, d in self.docs.items() if d.path != filepath}
        return True

    def upsert_documents(self, docs):
        for d in docs:
            self.docs[d.id] = d
            self.upserted_paths.append(d.path)
        return True

    def chunks_for(self, path):
        return [d for d in self.docs.values() if d.path == path]


def _fake_embeddings(texts, *args, **kwargs):
    return [{"dense": [0.1] * 384, "sparse": None} for _ in texts]


@pytest.fixture(autouse=True)
def setup_env(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_reindex.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", test_db)
    db_service.init_db()


@pytest.fixture
def store():
    s = RecordingStore()
    with patch("app.services.vector_store.get_vector_store", return_value=s), \
         patch("app.services.indexing.processor.get_hybrid_embeddings_batch", side_effect=_fake_embeddings):
        yield s


def _add_local_path(path, repo):
    with db_service.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, enabled, repo, category) VALUES (?, 'directory', 1, 1, ?, 'notes')",
            (str(path), repo),
        )
        conn.commit()


def _write_doc(folder, name="guide.md"):
    folder.mkdir(exist_ok=True)
    body = "# Guide\n\n" + "\n\n".join(
        f"## Section {i}\n\n" + ("Paragraph text about the indexing pipeline. " * 12) for i in range(12)
    )
    f = folder / name
    f.write_text(body, encoding="utf-8")
    return os.path.abspath(str(f))


def test_fingerprint_changes_with_chunk_settings_and_version():
    base = index_format.current_fingerprint()
    assert base == index_format.current_fingerprint()
    with patch("app.services.indexing.state.CODE_CHUNK_SIZE", 1500):
        assert index_format.current_fingerprint() != base
    with patch("app.services.indexing.state.CHUNK_SIZE", 999):
        assert index_format.current_fingerprint() != base
    with patch.object(index_format, "INDEX_FORMAT_VERSION", index_format.INDEX_FORMAT_VERSION + 1):
        assert index_format.current_fingerprint() != base


def test_full_indexing_reprocesses_local_files_once_after_format_change(tmp_path, store):
    vault = tmp_path / "vault"
    doc_path = _write_doc(vault)
    _add_local_path(vault, "notes-repo")

    # The old release made small chunks (older format version).
    with patch("app.services.indexing.processor.CHUNK_SIZE", 300), \
         patch("app.services.indexing.processor.CHUNK_OVERLAP", 0), \
         patch.object(index_format, "INDEX_FORMAT_VERSION", index_format.INDEX_FORMAT_VERSION - 1):
        old_fingerprint = index_format.current_fingerprint()
        assert run_full_indexing() is True
        old_chunks = store.chunks_for(doc_path)
        assert not index_format.is_stale("local", old_fingerprint)

        # Unchanged files and unchanged format: nothing is reprocessed.
        store.upserted_paths.clear()
        assert run_full_indexing() is True
        assert doc_path not in store.upserted_paths

    # After the upgrade, chunks are larger. The mtime is the same, but the file is reprocessed
    # and all old chunks are removed (no stale or duplicate chunks).
    new_fingerprint = index_format.current_fingerprint()
    assert new_fingerprint != old_fingerprint
    assert index_format.is_stale("local", new_fingerprint)

    store.upserted_paths.clear()
    assert run_full_indexing() is True
    new_chunks = store.chunks_for(doc_path)
    assert doc_path in store.upserted_paths
    assert len(new_chunks) == store.upserted_paths.count(doc_path)
    assert len(new_chunks) < len(old_chunks)
    assert not index_format.is_stale("local", new_fingerprint)

    # The new fingerprint is stored: the next pass skips the file again.
    store.upserted_paths.clear()
    assert run_full_indexing() is True
    assert doc_path not in store.upserted_paths


def test_full_indexing_forces_stale_git_repos_and_stores_fingerprint_on_success(store):
    with db_service.get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, status, enabled) VALUES ('ok-repo', 'http://a', 'main', 'synced', 1)")
        conn.execute("INSERT INTO git_repositories (name, url, branch, status, enabled) VALUES ('bad-repo', 'http://b', 'main', 'synced', 1)")
        conn.commit()
        ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM git_repositories").fetchall()}

    calls = []

    def fake_sync(repo_id, force=False):
        calls.append((repo_id, force))
        return repo_id == ids["ok-repo"]

    fingerprint = index_format.current_fingerprint()
    with patch("app.services.indexing.git_syncer.sync_single_git_repo", side_effect=fake_sync):
        run_full_indexing()
        assert sorted(calls) == sorted([(ids["ok-repo"], True), (ids["bad-repo"], True)])
        assert not index_format.is_stale(f"git:{ids['ok-repo']}", fingerprint)
        assert index_format.is_stale(f"git:{ids['bad-repo']}", fingerprint)

        # Only the repo that failed is forced again.
        calls.clear()
        run_full_indexing()
        assert sorted(calls) == sorted([(ids["ok-repo"], False), (ids["bad-repo"], True)])

        # An explicit force reprocesses every repo.
        calls.clear()
        run_full_indexing(force=True)
        assert sorted(calls) == sorted([(ids["ok-repo"], True), (ids["bad-repo"], True)])


def test_forced_local_sync_ignores_mtime_cache_without_duplicates(tmp_path, store):
    vault = tmp_path / "vault"
    doc_path = _write_doc(vault)
    _add_local_path(vault, "notes-repo")

    assert sync_local_paths() is True
    first_ids = {d.id for d in store.chunks_for(doc_path)}
    assert first_ids

    store.upserted_paths.clear()
    assert sync_local_paths() is True
    assert doc_path not in store.upserted_paths

    store.upserted_paths.clear()
    assert sync_local_paths(force=True) is True
    assert doc_path in store.upserted_paths
    assert {d.id for d in store.chunks_for(doc_path)} == first_ids
    assert len(store.chunks_for(doc_path)) == store.upserted_paths.count(doc_path)
    with db_service.get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM file_summaries WHERE filepath = ?", (doc_path,)).fetchone()["n"] == 1


def test_sync_local_repo_forces_only_that_repo(tmp_path, store):
    doc_a = _write_doc(tmp_path / "a")
    doc_b = _write_doc(tmp_path / "b")
    _add_local_path(tmp_path / "a", "repo-a")
    _add_local_path(tmp_path / "b", "repo-b")
    assert sync_local_paths() is True

    store.upserted_paths.clear()
    assert sync_local_repo("repo-a") is True
    assert doc_a in store.upserted_paths
    assert doc_b not in store.upserted_paths


def test_sync_local_repo_skips_when_indexing_is_running(tmp_path, store):
    import app.services.indexing.state as idx_state
    _write_doc(tmp_path / "a")
    _add_local_path(tmp_path / "a", "repo-a")
    idx_state.indexing_lock.acquire()
    try:
        assert sync_local_repo("repo-a") is False
        assert store.upserted_paths == []
    finally:
        idx_state.indexing_lock.release()

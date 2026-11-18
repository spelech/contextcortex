"""Tests for complete relational and vector cleanup when deleting local paths and git repositories (#170, #171)."""

import sqlite3
from unittest.mock import MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.routes import router
from app.services.database.schema import metadata
from app.services.vector_store.base import VectorDocument
from app.services.vector_store.pgvector_store import PgVectorStore

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture
def isolated_env(tmp_path):
    """Provides an isolated SQLite relational DB and SQLite-backed PgVectorStore."""
    db_file = tmp_path / "test_cleanup.db"
    rel_engine = create_engine(f"sqlite:///{db_file}")
    metadata.create_all(rel_engine)

    vec_db_file = tmp_path / "test_vec.db"
    vec_engine = create_engine(f"sqlite:///{vec_db_file}")

    with patch("app.services.vector_store.pgvector_store.get_dense_dim", return_value=4):
        store = PgVectorStore(engine=vec_engine, collection_name="test_coll", dimension=4, auto_init=True)

    def _get_conn():
        c = sqlite3.connect(str(db_file))
        c.row_factory = sqlite3.Row
        return c

    with patch("app.services.database.get_db_connection", side_effect=_get_conn), \
         patch("app.services.vector_store.get_vector_store", return_value=store):
        yield _get_conn, store


def _seed_path_artifacts(conn, store: PgVectorStore, repo: str, folder_path: str, use_backslashes: bool = False):
    """Seeds all 6 file-scoped tables and vector store for a given folder path and repo."""
    sep = "\\" if use_backslashes else "/"
    base = folder_path.replace("/", "\\") if use_backslashes else folder_path
    py_file = f"{base}{sep}app{sep}service.py"
    md_file = f"{base}{sep}README.md"

    conn.execute(
        "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime, hash) VALUES (?, ?, 'code', 'python', 1.0, 'h1')",
        (py_file, repo),
    )
    conn.execute(
        "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime, hash) VALUES (?, ?, 'doc', 'markdown', 1.0, 'h2')",
        (md_file, repo),
    )
    conn.execute(
        "INSERT INTO file_summaries (filepath, repo, title, summary_text, mtime) VALUES (?, ?, 'README', 'summary', 1.0)",
        (md_file, repo),
    )
    cur = conn.execute(
        "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, language) VALUES (?, ?, 'run', 'service.run', 'function', 1, 10, 'python')",
        (repo, py_file),
    )
    sym_id = cur.lastrowid
    conn.execute(
        "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, 'service.run', 'db.query', 'CALLS', 5)",
        (repo, sym_id, py_file),
    )
    conn.execute(
        "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES (?, ?, 'fastapi', 'GET', '/items', 'get_items', 1, 8)",
        (repo, py_file),
    )
    conn.execute(
        "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES (?, ?, 'POST', '/api/v1/sync', 'trigger', 12)",
        (repo, py_file),
    )
    conn.commit()

    store.upsert_documents([
        VectorDocument(
            id=f"{repo}:{py_file}:0",
            text="def run(): pass",
            dense_vector=[0.1, 0.2, 0.3, 0.4],
            repo=repo,
            doc_type="code",
            path=py_file,
        ),
        VectorDocument(
            id=f"{repo}:{md_file}:0",
            text="# README",
            dense_vector=[0.4, 0.3, 0.2, 0.1],
            repo=repo,
            doc_type="doc",
            path=md_file,
        ),
    ])


def test_delete_local_path_cleans_all_relational_tables_and_vectors(isolated_env):
    """Verify DELETE /admin/api/paths/{id} removes rows from all 6 file-scoped tables and the vector store."""
    get_conn, store = isolated_env
    folder = r"C:\Users\dev\project_alpha"

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, category, repo) VALUES (?, 'directory', 1, 'code', 'alpha-repo')",
            (folder,),
        )
        path_id = cur.lastrowid
        _seed_path_artifacts(conn, store, repo="alpha-repo", folder_path=folder, use_backslashes=True)

    assert store.get_stats()["points_count"] == 2

    res = client.delete(f"/admin/api/paths/{path_id}")
    assert res.status_code == 200
    assert res.json()["deleted"] == folder

    with get_conn() as conn:
        for table in (
            "indexed_paths",
            "indexed_files",
            "file_summaries",
            "ast_symbols",
            "ast_relationships",
            "api_routes",
            "api_client_calls",
        ):
            cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert cnt == 0, f"Expected 0 rows in {table} after deleting local path, found {cnt}"

    assert store.get_stats()["points_count"] == 0


def test_delete_local_path_with_shared_repo_only_purges_deleted_path_prefix(isolated_env):
    """Verify deleting one local path that shares a repo name ('local') removes only its own files and vectors."""
    get_conn, store = isolated_env
    path_a = "/workspace/team_a"
    path_b = "/workspace/team_a_sibling"

    with get_conn() as conn:
        cur_a = conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, category, repo) VALUES (?, 'directory', 1, 'code', 'local')",
            (path_a,),
        )
        id_a = cur_a.lastrowid
        conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, category, repo) VALUES (?, 'directory', 1, 'code', 'local')",
            (path_b,),
        )
        _seed_path_artifacts(conn, store, repo="local", folder_path=path_a, use_backslashes=True)
        _seed_path_artifacts(conn, store, repo="local", folder_path=path_b, use_backslashes=False)

    assert store.get_stats()["points_count"] == 4

    res = client.delete(f"/admin/api/paths/{id_a}")
    assert res.status_code == 200

    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM file_summaries").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM ast_symbols").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM ast_relationships").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM api_routes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM api_client_calls").fetchone()[0] == 1

    assert store.get_stats()["points_count"] == 2


def test_delete_git_repo_cleans_file_summaries_and_api_client_calls(isolated_env):
    """Verify DELETE /admin/api/repos/{id} deletes file_summaries, api_client_calls, and all repo-scoped tables."""
    get_conn, store = isolated_env
    repo_name = "my-service-repo"

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO git_repositories (name, url, branch) VALUES (?, 'https://github.com/org/repo.git', 'main')",
            (repo_name,),
        )
        repo_id = cur.lastrowid
        _seed_path_artifacts(conn, store, repo=repo_name, folder_path="/clones/my-service-repo")
        conn.execute(
            "INSERT INTO git_commits (repo, commit_sha, author, message) VALUES (?, 'abc1234', 'dev', 'init')",
            (repo_name,),
        )
        conn.commit()

    with patch("app.services.git_manager.cleanup_persistent_repo"):
        res = client.delete(f"/admin/api/repos/{repo_id}")
        assert res.status_code == 200
        assert res.json()["deleted"] == repo_name

    with get_conn() as conn:
        for table in (
            "git_repositories",
            "indexed_files",
            "file_summaries",
            "ast_symbols",
            "ast_relationships",
            "api_routes",
            "api_client_calls",
            "git_commits",
        ):
            cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert cnt == 0, f"Expected 0 rows in {table} after deleting repo, found {cnt}"

    assert store.get_stats()["points_count"] == 0


def test_pgvector_upsert_batches_missing_embeddings_and_deletes_by_folder_prefix(isolated_env):
    """Verify PgVectorStore.upsert_documents batches missing dense vectors and delete_by_path supports prefixes."""
    _, store = isolated_env

    docs = [
        VectorDocument(id="d1", text="chunk one", dense_vector=None, repo="r1", path="/dir/sub/a.py"),
        VectorDocument(id="d2", text="chunk two", dense_vector=None, repo="r1", path="/dir/sub/b.py"),
        VectorDocument(id="d3", text="chunk three", dense_vector=[0.9, 0.8, 0.7, 0.6], repo="r1", path="/dir/sub_other/c.py"),
    ]

    with patch(
        "app.services.vector_store.pgvector_store.get_dense_embeddings_batch",
        return_value=[[0.1, 0.1, 0.1, 0.1], [0.2, 0.2, 0.2, 0.2]],
    ) as mock_batch, patch(
        "app.services.vector_store.pgvector_store.get_dense_embedding",
    ) as mock_single:
        assert store.upsert_documents(docs) is True
        mock_batch.assert_called_once_with(["chunk one", "chunk two"])
        mock_single.assert_not_called()

    assert store.get_stats()["points_count"] == 3

    # Deleting folder /dir/sub (even with Windows backslashes and trailing slash) deletes d1 and d2 but keeps d3
    assert store.delete_by_path(r"\dir\sub\\") is True
    assert store.get_stats()["points_count"] == 1

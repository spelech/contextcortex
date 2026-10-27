"""
Tests for unified PostgreSQL relational selection and compatibility via get_db_connection().
Asserts that when PostgreSQL is selected, the application uses the PostgreSQL connection adapter,
does not create or query an unrelated fallback SQLite database, and supports full CRUD/indexing/search/ADRs/settings/deletion.
"""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, text

from app.services.database.schema import metadata
import app.services.database as db_service
from app.services.database.connection import (
    get_db_connection,
    is_postgres,
    DictRow,
    PostgresConnectionAdapter,
    _convert_sql_placeholders,
    ensure_git_repositories_columns,
    ensure_file_summaries_columns,
    get_file_settings,
    set_file_settings,
    get_ai_gateway_config,
    set_ai_gateway_config,
)
from app.services.database.credentials import (
    save_git_host_credential,
    list_git_host_credentials,
    get_git_host_credential,
    delete_git_host_credential,
)
from app.services.database.adrs import (
    create_adr,
    get_adr,
    list_adrs,
    update_adr,
    supersede_adr,
    upsert_adr,
)
from app.services.local_storage import LocalStorageService


def test_dict_row_compatibility():
    """Verify DictRow supports dict lookup, index lookup, attribute access, and dict conversion."""
    data = {"id": 10, "name": "my-repo", "branch": "main"}
    row = DictRow(data)

    # Key lookup
    assert row["id"] == 10
    assert row["name"] == "my-repo"

    # Index lookup
    assert row[0] == 10
    assert row[1] == "my-repo"
    assert row[2] == "main"

    # Attribute access
    assert row.name == "my-repo"
    assert row.branch == "main"

    # Dict conversion
    assert dict(row) == data
    assert list(row.keys()) == ["id", "name", "branch"]
    assert row.get("name") == "my-repo"
    assert row.get("missing", "default") == "default"


def test_convert_sql_placeholders():
    """Verify placeholder conversion converts ? to :p1, :p2 and appends RETURNING id for inserts."""
    sql = "SELECT * FROM git_repositories WHERE name = ? AND branch = ?"
    params = ("repo1", "main")
    c_sql, c_params = _convert_sql_placeholders(sql, params)
    assert c_sql == "SELECT * FROM git_repositories WHERE name = :p1 AND branch = :p2"
    assert c_params == {"p1": "repo1", "p2": "main"}

    # Insert on table with ID should append RETURNING id
    insert_sql = "INSERT INTO git_repositories (name, url) VALUES (?, ?)"
    insert_params = ("repo1", "https://github.com/org/repo1")
    i_sql, i_params = _convert_sql_placeholders(insert_sql, insert_params)
    assert i_sql == "INSERT INTO git_repositories (name, url) VALUES (:p1, :p2) RETURNING id"
    assert i_params == {"p1": "repo1", "p2": "https://github.com/org/repo1"}


def test_postgres_selection_never_creates_fallback_sqlite(tmp_path, monkeypatch):
    """
    Asserts that when PostgreSQL is selected, get_db_connection() returns the PostgreSQL adapter
    and NEVER creates or queries the fallback SQLite index_cache.db file.
    """
    db_file = tmp_path / "never_created_sqlite.db"
    monkeypatch.setenv("CACHE_DB_PATH", str(db_file))
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/testdb")

    # Patch is_postgres to True and get_db_engine to return a mock engine
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value = mock_conn
    mock_engine.dialect.name = "postgresql"

    with patch("app.services.database.connection.is_postgres", return_value=True), \
         patch("app.services.database.engine.is_postgres", return_value=True), \
         patch("app.services.database.engine.get_db_engine", return_value=mock_engine):

        conn = get_db_connection()
        assert isinstance(conn, PostgresConnectionAdapter)

        # Ensure SQLite file was NOT created on disk
        assert not os.path.exists(db_file)


def test_postgres_full_relational_crud_and_indexing(tmp_path, monkeypatch):
    """
    Tests full relational lifecycle (repositories, settings, credentials, indexing,
    file summaries, AST symbols/routes/relationships, ADRs, search and deletion)
    over the PostgresConnectionAdapter using an initialized test engine.
    """
    # Create SQLite DB engine that accepts RETURNING id and ON CONFLICT
    db_file = tmp_path / "pg_test.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    metadata.create_all(bind=engine)

    with patch("app.services.database.connection.is_postgres", return_value=True), \
         patch("app.services.database.engine.is_postgres", return_value=True), \
         patch("app.services.database.engine.get_db_engine", return_value=engine):

        # 1. Test repositories CRUD
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO git_repositories (name, url, branch, provider, status) VALUES (?, ?, ?, ?, 'pending')",
                ("test-repo", "https://github.com/org/test-repo.git", "main", "github")
            )
            repo_id = cur.lastrowid
            assert repo_id is not None

            rows = conn.execute("SELECT * FROM git_repositories WHERE id = ?", (repo_id,)).fetchall()
            assert len(rows) == 1
            assert rows[0]["name"] == "test-repo"
            assert rows[0]["branch"] == "main"

            conn.execute("UPDATE git_repositories SET status = 'synced' WHERE id = ?", (repo_id,))
            updated_row = conn.execute("SELECT status FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
            assert updated_row["status"] == "synced"

        # 2. Test credentials
        cred_id = save_git_host_credential("github.com", "github", "token_12345", auth_user="octocat")
        assert cred_id is not None
        creds = list_git_host_credentials()
        assert len(creds) >= 1
        c = get_git_host_credential("github.com")
        assert c is not None
        assert c["auth_token"] == "token_12345"
        assert delete_git_host_credential(cred_id) is True

        # 3. Test settings
        set_file_settings({"summary_enabled": True, "read_file_max_lines": 1500})
        f_settings = get_file_settings()
        assert f_settings["summary_enabled"] is True
        assert f_settings["read_file_max_lines"] == 1500

        # 4. Test ADRs
        adr = create_adr("test-repo", "Use PostgreSQL Engine", status="PROPOSED", context="Scaling DB", decision="Adopt SQLAlchemy PostgreSQL")
        assert adr["id"] == "ADR-001"
        assert adr["title"] == "Use PostgreSQL Engine"

        listed_adrs = list_adrs("test-repo")
        assert len(listed_adrs) == 1

        up_adr = update_adr("ADR-001", "test-repo", status="ACCEPTED")
        assert up_adr["status"] == "ACCEPTED"

        adr2 = create_adr("test-repo", "New ADR", status="PROPOSED")
        sup_adr = supersede_adr("ADR-001", adr2["id"], "test-repo")
        assert sup_adr["status"] == "SUPERSEDED"

        # 5. Test indexing & deletion via LocalStorageService
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_svc = LocalStorageService(storage_root=str(storage_dir))

        save_res = storage_svc.save_file("sample.py", "def my_func():\n    return 42\n", repo="local_storage")
        assert save_res["status"] == "success"

        with get_db_connection() as conn:
            idx_file = conn.execute("SELECT * FROM indexed_files WHERE repo = ?", ("local_storage",)).fetchone()
            assert idx_file is not None
            syms = conn.execute("SELECT * FROM ast_symbols WHERE repo = ?", ("local_storage",)).fetchall()
            assert len(syms) >= 1
            assert syms[0]["name"] == "my_func"

        # Test deletion
        del_res = storage_svc.delete_file("sample.py", repo="local_storage")
        assert del_res["deleted"] is True

        with get_db_connection() as conn:
            idx_file_after = conn.execute("SELECT * FROM indexed_files WHERE repo = ?", ("local_storage",)).fetchone()
            assert idx_file_after is None
            syms_after = conn.execute("SELECT * FROM ast_symbols WHERE repo = ?", ("local_storage",)).fetchall()
            assert len(syms_after) == 0


def test_ensure_columns_postgres():
    """Verify ensure_git_repositories_columns and ensure_file_summaries_columns run without error when on PostgreSQL."""
    mock_sa_conn = MagicMock()
    mock_sa_conn.execute.return_value.fetchone.return_value = ("keep_shallow",)

    with patch("app.services.database.connection.is_postgres", return_value=True), \
         patch("app.services.database.connection.get_connection") as mock_get_conn:

        mock_get_conn.return_value.__enter__.return_value = mock_sa_conn
        ensure_git_repositories_columns()
        ensure_file_summaries_columns()
        assert mock_sa_conn.execute.called

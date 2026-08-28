import os
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import Table, inspect
from sqlalchemy.exc import OperationalError, IntegrityError

from app.services.database.schema import metadata, TABLES
from app.services.database.engine import (
    get_db_engine,
    init_db,
    get_connection,
    get_db_url,
    wait_for_db,
    is_postgres,
)
from app.services.database.connection import (
    get_metadata,
    set_metadata,
    get_vector_store_db_config,
    set_vector_store_db_config,
    get_embedding_db_config,
    set_embedding_db_config,
)


def test_schema_metadata_contains_all_tables():
    expected_tables = {
        "indexed_paths",
        "git_repositories",
        "git_host_credentials",
        "indexed_files",
        "file_summaries",
        "embedding_cache",
        "ast_symbols",
        "ast_relationships",
        "api_routes",
        "api_client_calls",
        "system_metadata",
        "architecture_decision_records",
        "custom_prompts",
        "api_keys",
    }
    assert expected_tables.issubset(set(metadata.tables.keys()))
    for tbl_name in expected_tables:
        assert tbl_name in TABLES
        assert isinstance(TABLES[tbl_name], Table)


def test_schema_api_keys_columns():
    api_keys = TABLES["api_keys"]
    col_names = {c.name for c in api_keys.columns}
    expected_cols = {
        "id",
        "name",
        "key_prefix",
        "key_hash",
        "role",
        "group_name",
        "expires_at",
        "created_at",
        "last_used_at",
        "is_active",
    }
    assert expected_cols.issubset(col_names)


def test_sqlite_engine_initialization_and_crud(tmp_path):
    db_file = tmp_path / "test_engine.db"
    db_url = f"sqlite:///{db_file}"
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    with get_connection(engine) as conn:
        conn.execute(
            TABLES["system_metadata"].insert().values(key="version", value="2.12.0")
        )
        conn.commit()

        row = conn.execute(
            TABLES["system_metadata"].select().where(TABLES["system_metadata"].c.key == "version")
        ).mappings().fetchone()

        assert row is not None
        assert row["value"] == "2.12.0"


def test_sqlite_engine_seeds_default_prompts_and_configs(tmp_path):
    db_file = tmp_path / "test_seed.db"
    db_url = f"sqlite:///{db_file}"
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    with get_connection(engine) as conn:
        prompts = conn.execute(TABLES["custom_prompts"].select()).mappings().fetchall()
        assert len(prompts) >= 2
        prompt_names = {p["name"] for p in prompts}
        assert "search_infrastructure_docs" in prompt_names
        assert "find_implementation_symbol" in prompt_names

        # Check seeded system_metadata
        meta_rows = conn.execute(TABLES["system_metadata"].select()).mappings().fetchall()
        meta_dict = {r["key"]: r["value"] for r in meta_rows}
        assert "vector_store_provider" in meta_dict
        assert "embedding_provider" in meta_dict


def test_ast_relationship_foreign_key_and_cascade(tmp_path):
    db_file = tmp_path / "test_fk.db"
    db_url = f"sqlite:///{db_file}"
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    with get_connection(engine) as conn:
        # Insert symbol
        res = conn.execute(
            TABLES["ast_symbols"].insert().values(
                repo="local",
                filepath="main.py",
                name="my_func",
                kind="function",
                start_line=1,
                end_line=10,
            )
        )
        sym_id = res.inserted_primary_key[0]

        # Insert relationship
        conn.execute(
            TABLES["ast_relationships"].insert().values(
                repo="local",
                source_symbol_id=sym_id,
                source_filepath="main.py",
                source_symbol="my_func",
                target_symbol="other_func",
                relationship_type="calls",
                line_number=5,
            )
        )
        conn.commit()

        # Delete symbol
        conn.execute(
            TABLES["ast_symbols"].delete().where(TABLES["ast_symbols"].c.id == sym_id)
        )
        conn.commit()

        # Verify relationship was deleted via CASCADE
        rel = conn.execute(
            TABLES["ast_relationships"].select().where(TABLES["ast_relationships"].c.source_symbol_id == sym_id)
        ).first()
        assert rel is None


def test_api_keys_unique_hash_constraint(tmp_path):
    db_file = tmp_path / "test_keys.db"
    db_url = f"sqlite:///{db_file}"
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    with get_connection(engine) as conn:
        conn.execute(
            TABLES["api_keys"].insert().values(
                name="Test Key 1",
                key_prefix="cc_live_1234",
                key_hash="hash_abc123",
                role="admin",
            )
        )
        conn.commit()

        with pytest.raises(IntegrityError):
            conn.execute(
                TABLES["api_keys"].insert().values(
                    name="Test Key 2",
                    key_prefix="cc_live_5678",
                    key_hash="hash_abc123",
                    role="viewer",
                )
            )
            conn.commit()


def test_connection_helpers_with_engine(tmp_path, monkeypatch):
    db_file = tmp_path / "test_helpers.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    # test get_metadata / set_metadata
    set_metadata("test_k", "test_v")
    assert get_metadata("test_k") == "test_v"
    assert get_metadata("non_existent", "default_val") == "default_val"

    # test vector store config
    set_vector_store_db_config(provider="qdrant", mode="embedded", collection="my_collection")
    v_cfg = get_vector_store_db_config()
    assert v_cfg["provider"] == "qdrant"
    assert v_cfg["mode"] == "embedded"
    assert v_cfg["collection"] == "my_collection"

    # test embedding config
    set_embedding_db_config(provider="local", dense_model="BAAI/bge-large-en-v1.5", threads=4)
    e_cfg = get_embedding_db_config()
    assert e_cfg["provider"] == "local"
    assert e_cfg["dense_model"] == "BAAI/bge-large-en-v1.5"
    assert e_cfg["threads"] == 4


def test_get_db_url_normalization():
    assert get_db_url("postgresql://user:pass@localhost:5432/db") == "postgresql+psycopg://user:pass@localhost:5432/db"
    assert get_db_url("postgres://user:pass@localhost:5432/db") == "postgresql+psycopg://user:pass@localhost:5432/db"
    assert get_db_url("postgresql+psycopg://user:pass@localhost:5432/db") == "postgresql+psycopg://user:pass@localhost:5432/db"
    assert get_db_url("sqlite:////tmp/test.db") == "sqlite:////tmp/test.db"


def test_is_postgres_detection():
    assert is_postgres("postgresql://user:pass@localhost:5432/db") is True
    assert is_postgres("postgresql+psycopg://user:pass@localhost:5432/db") is True
    assert is_postgres("sqlite:////tmp/test.db") is False


def test_wait_for_db_retries_and_success():
    mock_engine = MagicMock()
    # First attempt fails with OperationalError, second succeeds
    conn_mock = MagicMock()
    mock_engine.connect.side_effect = [
        OperationalError("connection failed", None, Exception("could not connect")),
        conn_mock,
    ]

    success = wait_for_db(engine=mock_engine, max_retries=3, initial_delay=0.01, max_delay=0.05)
    assert success is True
    assert mock_engine.connect.call_count == 2


def test_wait_for_db_exhausts_retries():
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = OperationalError("connection failed", None, Exception("refused"))

    with pytest.raises(OperationalError):
        wait_for_db(engine=mock_engine, max_retries=2, initial_delay=0.01, max_delay=0.05)

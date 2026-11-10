import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

import app.services.database as db_service
from app.services.database.engine import dispose_global_engine
from main import app


@pytest.fixture
def postgres_readiness_db(monkeypatch, tmp_path):
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is required for native PostgreSQL tests")

    schema = f"readiness_{uuid.uuid4().hex}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    isolated_url = make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema},public"}
    )
    monkeypatch.setenv(
        "DATABASE_URL", isolated_url.render_as_string(hide_password=False)
    )
    dispose_global_engine()
    try:
        db_service.init_db(vault_path=str(tmp_path))
        yield
    finally:
        dispose_global_engine()
        with admin_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


def test_native_postgres_readiness_accepts_initialized_schema(postgres_readiness_db):
    client = TestClient(app)
    for endpoint in ("/ready", "/readiness", "/health/ready", "/healthz/ready"):
        response = client.get(endpoint)
        assert response.status_code == 200
        assert response.json()["database"] == {"status": "ok", "type": "postgresql"}


def test_native_postgres_missing_schema_is_sanitized(postgres_readiness_db):
    from app.services.database.engine import get_db_engine

    with get_db_engine().begin() as conn:
        conn.execute(text("DROP TABLE indexed_files"))

    client = TestClient(app)
    response = client.get("/readiness")
    assert response.status_code == 503
    assert response.json()["database"] == {"status": "error", "type": "postgresql"}
    assert response.json()["error"] == "Required database schema or metadata unavailable"
    assert "indexed_files" not in response.text
    assert client.get("/health").status_code == 200

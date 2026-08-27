"""
Unit and integration tests for Task 6: Docker Compose & Container Orchestration.
Tests docker-compose.yml configuration, .env.example documentation,
database connection startup retry, and initial admin key bootstrapping.
"""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import yaml

from app.services.database.engine import get_db_engine, init_db, wait_for_db
from app.services.auth.models import Role
from app.services.auth.key_service import ApiKeyService
from app.services.auth.service import AuthService, get_auth_service
from main import init_application_database


@pytest.fixture(autouse=True)
def reset_auth_singleton():
    """Ensures AuthService singleton is clean after each test."""
    yield
    get_auth_service(reset=True, auth_enabled=False)


@pytest.fixture
def db_engine(tmp_path):
    """Provides a fresh isolated SQLite database engine for testing."""
    db_file = tmp_path / "test_orchestration.db"
    engine = get_db_engine(f"sqlite:///{db_file}", reset=True)
    init_db(engine=engine)
    return engine


class TestDockerComposeConfig:
    """Validates docker-compose.yml structure, services, and healthchecks."""

    @pytest.fixture(scope="class")
    def compose_data(self):
        compose_path = Path("/containers/dev/contexthub/docker-compose.yml")
        assert compose_path.exists(), "docker-compose.yml does not exist"
        with open(compose_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_compose_version_and_services(self, compose_data):
        assert "services" in compose_data
        services = compose_data["services"]
        assert "postgres" in services
        assert "contextcortex" in services

    def test_postgres_service_config(self, compose_data):
        pg = compose_data["services"]["postgres"]
        assert pg["image"] == "pgvector/pgvector:pg16"
        assert "contextcortex-postgres" in pg.get("container_name", "")
        assert "healthcheck" in pg
        assert "pg_isready" in str(pg["healthcheck"]["test"])
        assert any("postgres_data" in v for v in pg.get("volumes", []))

    def test_contextcortex_service_config(self, compose_data):
        cc = compose_data["services"]["contextcortex"]
        assert "build" in cc
        assert cc["build"]["dockerfile"] == "Dockerfile"
        assert "depends_on" in cc
        assert cc["depends_on"]["postgres"]["condition"] == "service_healthy"

        env = cc.get("environment", {})
        assert "DATABASE_URL" in env
        assert "AUTH_ENABLED" in env
        assert "AUTH_OIDC_ISSUER" in env
        assert "AUTH_JWKS_URI" in env
        assert "AUTH_RESOURCE_INDICATOR" in env
        assert "ADMIN_INITIAL_KEY" in env

    def test_volumes_declared(self, compose_data):
        volumes = compose_data.get("volumes", {})
        assert "postgres_data" in volumes
        assert "repo_cache" in volumes


class TestEnvExampleDocumentation:
    """Validates .env.example contains all required configuration options."""

    @pytest.fixture(scope="class")
    def env_content(self):
        env_path = Path("/containers/dev/contexthub/.env.example")
        assert env_path.exists(), ".env.example does not exist"
        with open(env_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_contains_database_vars(self, env_content):
        assert "DATABASE_URL=" in env_content
        assert "POSTGRES_USER=" in env_content
        assert "POSTGRES_PASSWORD=" in env_content
        assert "POSTGRES_DB=" in env_content

    def test_contains_auth_vars(self, env_content):
        assert "AUTH_ENABLED=" in env_content
        assert "AUTH_OIDC_ISSUER=" in env_content
        assert "AUTH_JWKS_URI=" in env_content
        assert "AUTH_RESOURCE_INDICATOR=" in env_content
        assert "ADMIN_INITIAL_KEY=" in env_content

    def test_contains_vector_store_vars(self, env_content):
        assert "VECTOR_STORE_PROVIDER=" in env_content
        assert "EMBEDDING_PROVIDER=" in env_content


class TestAdminKeyBootstrap:
    """Validates initial admin API key bootstrapping behaviors."""

    def test_bootstrap_empty_does_nothing(self, db_engine):
        key_srv = ApiKeyService(engine=db_engine)
        result = key_srv.bootstrap_admin_key(initial_key=None)
        assert result is None
        assert len(key_srv.list_api_keys(engine=db_engine)) == 0

    def test_bootstrap_auto_generates_admin_key(self, db_engine):
        key_srv = ApiKeyService(engine=db_engine)
        result = key_srv.bootstrap_admin_key(initial_key="auto")

        assert result is not None
        assert result.role == "admin"
        assert result.secret_key is not None
        assert result.secret_key.startswith("cc_live_")

        # Validate that the generated secret authenticates with admin role
        ctx = key_srv.validate_api_key(result.secret_key, engine=db_engine)
        assert ctx.role == Role.ADMIN
        assert ctx.has_role(Role.ADMIN)

    def test_bootstrap_auto_is_idempotent(self, db_engine):
        key_srv = ApiKeyService(engine=db_engine)
        first_key = key_srv.bootstrap_admin_key(initial_key="generate")
        assert first_key is not None

        # Second invocation should not create duplicate keys
        second_result = key_srv.bootstrap_admin_key(initial_key="generate")
        assert second_result is None
        assert len(key_srv.list_api_keys(engine=db_engine)) == 1

    def test_bootstrap_custom_secret_key(self, db_engine):
        key_srv = ApiKeyService(engine=db_engine)
        custom_token = "cc_live_mycustomsecretkey12345"
        result = key_srv.bootstrap_admin_key(initial_key=custom_token, name="Custom Admin")

        assert result is not None
        assert result.role == "admin"
        assert result.name == "Custom Admin"
        assert result.secret_key == custom_token

        # Verify validation
        ctx = key_srv.validate_api_key(custom_token, engine=db_engine)
        assert ctx.role == Role.ADMIN
        assert ctx.name == "Custom Admin"

    def test_bootstrap_custom_secret_key_without_prefix(self, db_engine):
        key_srv = ApiKeyService(engine=db_engine)
        raw_token = "supersecretcustomadminkey"
        result = key_srv.bootstrap_admin_key(initial_key=raw_token)

        assert result is not None
        assert result.secret_key == f"cc_live_{raw_token}"

        ctx = key_srv.validate_api_key(result.secret_key, engine=db_engine)
        assert ctx.role == Role.ADMIN

    def test_bootstrap_custom_secret_key_idempotent(self, db_engine):
        key_srv = ApiKeyService(engine=db_engine)
        custom_token = "cc_live_idempotentkey123"
        result1 = key_srv.bootstrap_admin_key(initial_key=custom_token)
        assert result1 is not None

        result2 = key_srv.bootstrap_admin_key(initial_key=custom_token)
        assert result2 is not None
        assert result2.id == result1.id
        assert result2.secret_key == custom_token
        assert len(key_srv.list_api_keys(engine=db_engine)) == 1

    def test_auth_service_bootstrap_delegation(self, db_engine):
        key_srv = ApiKeyService(engine=db_engine)
        auth_srv = AuthService(key_service=key_srv)

        result = auth_srv.bootstrap_admin_key(initial_key="auto")
        assert result is not None
        assert result.role == "admin"


class TestStartupDatabaseInitialization:
    """Validates startup database retry and bootstrap initialization in main.py."""

    def test_init_application_database_without_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADMIN_INITIAL_KEY", None)
            init_application_database()

    def test_init_application_database_with_admin_key_env(self, db_engine):
        key_srv = ApiKeyService(engine=db_engine)
        auth_srv = AuthService(key_service=key_srv)

        with patch("main.get_auth_service", return_value=auth_srv):
            with patch.dict(os.environ, {"ADMIN_INITIAL_KEY": "cc_live_bootstraptestkey999"}):
                init_application_database()

        keys = key_srv.list_api_keys(engine=db_engine)
        assert any(k.key_prefix.startswith("cc_live_bootstra") for k in keys)

    def test_wait_for_db_retry_success(self, db_engine):
        """Ensures wait_for_db returns True upon successful database connectivity."""
        assert wait_for_db(engine=db_engine, max_retries=3, initial_delay=0.01) is True

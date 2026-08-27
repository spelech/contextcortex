# PostgreSQL pgvector & MCP 2026-07-28 Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a pluggable containerized PostgreSQL + pgvector backend alongside MCP 2026-07-28 OAuth 2.1 Protected Resource Server and multi-user API-Key RBAC authentication in ContextCortex.

**Architecture:** 
1. Abstract all database schemas and connection pooling using SQLAlchemy Core 2.0 (`schema.py` and `engine.py`), ensuring single-source-of-truth DDL parity across SQLite and PostgreSQL.
2. Introduce `PgVectorStore` with pgvector HNSW cosine similarity search into `VectorStoreManager`.
3. Implement MCP 2026-07-28 OAuth 2.1 Protected Resource Server publishing RFC 9728 metadata (`/.well-known/oauth-protected-resource`), validating OIDC JWKS tokens and internal database-backed API keys across `admin`, `editor`, and `viewer` roles.
4. Provide an orchestrated `docker-compose.yml` coupling `contextcortex` with `pgvector/pgvector:pg16` and resilient cold-boot retry handling.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0+, psycopg 3.1+, pgvector 0.3+, PyJWT 2.8+, httpx, FastAPI, FastMCP 2.0+, Docker Compose, PostgreSQL 16.

## Global Constraints

- Strict sub-500 LOC per file limit for maintainability.
- Zero regressions on default SQLite + embedded Qdrant/Chroma developer workflow.
- FastMCP 2.0 SSE and Streamable HTTP transport compatibility.
- MCP 2026-07-28 Auth compliance (RFC 9728, RFC 8707, RFC 6750).

---

### Task 1: Add PostgreSQL, pgvector, and Auth Dependencies

**Files:**
- Modify: `requirements.txt`
- Modify: `Dockerfile`

**Interfaces:**
- Consumes: Existing base dependencies (`fastapi`, `uvicorn`, `mcp`, `fastembed`, etc.)
- Produces: `sqlalchemy`, `psycopg[binary]`, `pgvector`, `pyjwt[crypto]`, `httpx`, `cryptography` runtime packages

- [ ] **Step 1: Update requirements.txt with new dependencies**

Add to `requirements.txt`:
```
sqlalchemy>=2.0.30
psycopg[binary]>=3.1.18
pgvector>=0.3.0
pyjwt[crypto]>=2.8.0
cryptography>=42.0.0
httpx>=0.27.0
```

- [ ] **Step 2: Update Dockerfile for PostgreSQL client build readiness**

Ensure `Dockerfile` has system packages if required:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 3000

CMD ["python", "main.py"]
```

- [ ] **Step 3: Install dependencies in local virtual environment**

Run: `pip install -r requirements.txt`

- [ ] **Step 4: Verify package imports**

Run: `python -c "import sqlalchemy, psycopg, pgvector, jwt, httpx; print('Dependencies OK')"`
Expected: `Dependencies OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt Dockerfile
git commit -m "build: add sqlalchemy, psycopg, pgvector, and auth dependencies"
```

---

### Task 2: Canonical SQLAlchemy Core Schema and Database Engine

**Files:**
- Create: `app/services/database/schema.py`
- Create: `app/services/database/engine.py`
- Modify: `app/services/database/connection.py`
- Modify: `app/services/database/__init__.py`
- Test: `tests/test_database_engine.py`

**Interfaces:**
- Consumes: `DATABASE_URL` / `CACHE_DB_PATH`
- Produces: `get_db_engine()`, `get_db_connection()`, `init_db()`, `TABLES` dict with all SQLAlchemy Table definitions

- [ ] **Step 1: Write failing test for database engine and schema creation**

Create `tests/test_database_engine.py`:
```python
import pytest
from app.services.database.engine import get_db_engine, init_db, get_connection
from app.services.database.schema import metadata, TABLES

def test_schema_metadata_contains_all_tables():
    expected_tables = {
        "indexed_paths", "git_repositories", "git_host_credentials",
        "indexed_files", "file_summaries", "embedding_cache",
        "ast_symbols", "ast_relationships", "api_routes", "api_client_calls",
        "system_metadata", "architecture_decision_records", "custom_prompts",
        "api_keys"
    }
    assert expected_tables.issubset(set(metadata.tables.keys()))

def test_sqlite_engine_initialization_and_crud(tmp_path):
    db_file = tmp_path / "test_engine.db"
    db_url = f"sqlite:///{db_file}"
    engine = get_db_engine(db_url)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_database_engine.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `app/services/database/schema.py`**

Define SQLAlchemy Core `MetaData` and `Table` instances for:
- `indexed_paths`
- `git_repositories`
- `git_host_credentials`
- `indexed_files`
- `file_summaries`
- `embedding_cache`
- `ast_symbols`
- `ast_relationships`
- `api_routes`
- `api_client_calls`
- `system_metadata`
- `architecture_decision_records`
- `custom_prompts`
- `api_keys`

- [ ] **Step 4: Implement `app/services/database/engine.py`**

Implement `get_db_engine(database_url=None)`, `get_connection(engine=None)`, `init_db(vault_path=None, engine=None)`, with retry loop for PostgreSQL connection boots and `metadata.create_all(bind=engine)`.

- [ ] **Step 5: Adapt `app/services/database/connection.py` to route through engine**

Maintain backwards compatibility for existing modules calling `get_db_connection()`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_database_engine.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/services/database/schema.py app/services/database/engine.py app/services/database/connection.py app/services/database/__init__.py tests/test_database_engine.py
git commit -m "feat(db): add SQLAlchemy Core schema single source of truth and engine manager"
```

---

### Task 3: Implement `PgVectorStore` and Register in `VectorStoreManager`

**Files:**
- Create: `app/services/vector_store/pgvector_store.py`
- Modify: `app/services/vector_store/manager.py`
- Modify: `app/services/vector_store/__init__.py`
- Test: `tests/test_pgvector_store.py`

**Interfaces:**
- Consumes: `VectorStore` base class (`app/services/vector_store/base.py`), `get_db_engine()`
- Produces: `PgVectorStore` instance, dynamic dispatch in `VectorStoreManager.get_vector_store()`

- [ ] **Step 1: Write test for `PgVectorStore`**

Create `tests/test_pgvector_store.py` testing:
- Schema setup (`ensure_collection`)
- Document upsert (`upsert_documents` with `VectorDocument`)
- Document search (`search` with cosine ranking and payload retrieval)
- Document deletion (`delete_by_path`, `delete_by_repo`)
- Health check and stats (`get_stats`, `health_check`)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pgvector_store.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `PgVectorStore`**

Create `app/services/vector_store/pgvector_store.py`:
- Inherits from `VectorStore`.
- Implements `ensure_collection()` creating `vector_documents` table and `HNSW` index.
- Implements `upsert_documents()`, `delete_by_path()`, `delete_by_repo()`, `search()`, `get_stats()`, `health_check()`.

- [ ] **Step 4: Update `VectorStoreManager`**

In `app/services/vector_store/manager.py`:
- Add `"postgres"` and `"pgvector"` to `SUPPORTED_PROVIDERS`.
- Auto-instantiate `PgVectorStore` when `DATABASE_URL` points to PostgreSQL.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pgvector_store.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/vector_store/pgvector_store.py app/services/vector_store/manager.py app/services/vector_store/__init__.py tests/test_pgvector_store.py
git commit -m "feat(vector): implement PgVectorStore backend with HNSW cosine search"
```

---

### Task 4: Implement MCP 2026-07-28 Auth & RBAC Security Engine

**Files:**
- Create: `app/services/auth/models.py`
- Create: `app/services/auth/key_service.py`
- Create: `app/services/auth/jwt_validator.py`
- Create: `app/services/auth/service.py`
- Create: `app/services/auth/__init__.py`
- Test: `tests/test_auth_service.py`

**Interfaces:**
- Consumes: `api_keys` table in database, OIDC environment config (`AUTH_OIDC_ISSUER`, `AUTH_JWKS_URI`)
- Produces: `AuthUser`, `Role` (`admin`, `editor`, `viewer`), `authenticate_token()`, `issue_api_key()`, `revoke_api_key()`, `list_api_keys()`

- [ ] **Step 1: Write test for API Key management and JWT validation**

Create `tests/test_auth_service.py`:
- Test generating, hashing, and validating API keys (`cc_live_...`).
- Test role assignment (`admin`, `editor`, `viewer`).
- Test key expiration and revocation.
- Test OIDC JWT token verification and claims extraction.
- Test bypass when `AUTH_ENABLED=false`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth_service.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Auth Models and Key Service**

Create:
- `app/services/auth/models.py`: `Role`, `AuthContext`, `ApiKeyCreate`, `ApiKeyOut`.
- `app/services/auth/key_service.py`: Secure key generation (`secrets.token_urlsafe`), SHA-256 hashing, DB storage, role mapping.
- `app/services/auth/jwt_validator.py`: JWKS key fetcher & PyJWT validator.
- `app/services/auth/service.py`: Master `AuthService` routing tokens to Key Service or JWT Validator.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_auth_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/auth/ tests/test_auth_service.py
git commit -m "feat(auth): implement MCP 2026-07-28 OAuth 2.1 and API key RBAC engine"
```

---

### Task 5: Protected Resource Metadata Endpoint & Auth API Routers

**Files:**
- Create: `app/api/routers/auth.py`
- Modify: `app/api/routes.py`
- Modify: `app/mcp/tools.py`
- Modify: `app/mcp/handlers/*`
- Modify: `main.py`
- Test: `tests/test_auth_endpoints.py`

**Interfaces:**
- Consumes: `AuthService`, FastAPI Dependency Injection
- Produces: `/.well-known/oauth-protected-resource` route, `/admin/api/auth/*` REST API, Role-guarded MCP tools

- [ ] **Step 1: Write tests for Protected Resource metadata and Auth REST APIs**

Create `tests/test_auth_endpoints.py`:
- Test `GET /.well-known/oauth-protected-resource` returns RFC 9728 JSON.
- Test protected endpoints return `401 Unauthorized` with `WWW-Authenticate` header when unauthenticated and `AUTH_ENABLED=true`.
- Test `POST /admin/api/auth/keys` generates new key.
- Test `GET /admin/api/auth/keys` lists keys with masked secrets.
- Test `DELETE /admin/api/auth/keys/{id}` revokes key.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth_endpoints.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `app/api/routers/auth.py`**

Implement RFC 9728 metadata route and API key management routes.

- [ ] **Step 4: Wire Auth Middleware into FastAPI and FastMCP endpoints**

Update `main.py`, `app/api/routes.py`, and `app/mcp/tools.py` with role checks (`admin`, `editor`, `viewer`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_auth_endpoints.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/auth.py app/api/routes.py app/mcp/tools.py main.py tests/test_auth_endpoints.py
git commit -m "feat(api): expose RFC 9728 protected resource metadata and API key management"
```

---

### Task 6: Docker Compose & Container Orchestration

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Modify: `main.py` (database connection retry loop & initial admin key bootstrap)

**Interfaces:**
- Consumes: `pgvector/pgvector:pg16` image, ContextCortex application image
- Produces: Production-ready multi-container deployment configuration

- [ ] **Step 1: Implement `docker-compose.yml`**

Create `docker-compose.yml` with `postgres` and `contextcortex` services, healthchecks, and volume mounts.

- [ ] **Step 2: Create `.env.example`**

Document all environment variables: `DATABASE_URL`, `AUTH_ENABLED`, `AUTH_OIDC_ISSUER`, `AUTH_JWKS_URI`, `AUTH_RESOURCE_INDICATOR`, `ADMIN_INITIAL_KEY`.

- [ ] **Step 3: Add startup DB retry and bootstrap logic in `main.py`**

In `main.py`, ensure database initialization retries with exponential backoff on cold starts and auto-generates the initial admin key if requested.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example main.py
git commit -m "feat(deploy): add containerized postgres pgvector compose configuration and startup bootstrap"
```

---

### Task 7: Comprehensive Integration & Regression Verification

**Files:**
- Test: `tests/`
- Modify: `ARCHITECTURE.md`
- Modify: `README.md`

- [ ] **Step 1: Run full test suite**

Run: `pytest -v --cov=app`
Expected: All tests PASS with no regressions on existing functionality.

- [ ] **Step 2: Update documentation**

Update `ARCHITECTURE.md` and `README.md` with PostgreSQL + pgvector profile documentation, Docker Compose instructions, and MCP 2026-07-28 Auth usage.

- [ ] **Step 3: Commit**

```bash
git add ARCHITECTURE.md README.md
git commit -m "docs: update architecture and readme for postgres pgvector and mcp auth support"
```

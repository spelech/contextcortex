# ContextCortex Rebrand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebrand the entire application, backend loggers, FastMCP server, frontend UI, tests, documentation, Git remote, and MCP compose stack from `ContextHub` / `contexthub` (and residual `knowledge-rag-mcp` / `notes-rag`) to `ContextCortex` / `contextcortex`.

**Architecture:** Systematic multi-layer refactoring across backend Python modules, React 19 frontend components, documentation generators, test suites, git configuration, and Docker Compose deployment manifests.

**Tech Stack:** Python 3.12, FastMCP 2.0, FastAPI, React 19, Vite, TypeScript, Pytest, Vitest, Docker Compose.

## Global Constraints
- Target brand name: `ContextCortex` (PascalCase for UI/MCP display/FastAPI title)
- Target slug: `contextcortex` (lowercase for logger namespaces, package names, Docker images, GitHub slugs)
- Git Remote: `git@github.com:spelech/contextcortex.git`
- Preserve backward-compatible ingress aliases (`contexthub.wileyriley.com`, `notesrag.wileyriley.com`) in Caddy labels.
- All existing 242 backend tests and 74 frontend tests must pass cleanly.

---

### Task 1: Backend FastMCP, FastAPI App, and Subsystem Loggers Rebrand

**Files:**
- Modify: `app/mcp/mcp_server.py`
- Modify: `main.py`
- Modify: `app/api/webhooks.py`
- Modify: `app/mcp/tools.py`
- Modify: `app/services/db.py`
- Modify: `app/services/embeddings.py`
- Modify: `app/services/git_manager.py`
- Modify: `app/services/indexer.py`
- Modify: `app/services/poller.py`
- Modify: `app/services/search.py`
- Modify: `app/services/vector_store/chroma_store.py`
- Modify: `app/services/vector_store/manager.py`
- Modify: `app/services/vector_store/qdrant_store.py`
- Modify: `tests/backend/test_mcp_v2.py`
- Modify: `tests/backend/test_diagnostic_logger.py`

**Interfaces:**
- Produces: FastMCP server named `"ContextCortex"`, root logger `"contextcortex"`, subsystem loggers `"contextcortex.<subsystem>"`.

- [ ] **Step 1: Update FastMCP server registration in `app/mcp/mcp_server.py`**
  Set server name to `"ContextCortex"` and instruction string to `"ContextCortex: Universal Code & Knowledge RAG server providing hybrid search, AST code symbols, documentation retrieval, and repository indexing."`

- [ ] **Step 2: Update FastAPI title and loggers in `main.py`**
  Set `logger = logging.getLogger("contextcortex")`, update startup/shutdown log messages to `"ContextCortex Server starting up..."` / `"ContextCortex Server shutting down..."`, and set `FastAPI(title="ContextCortex", version="2.7.0", lifespan=lifespan)`.

- [ ] **Step 3: Update logger names across backend services**
  Replace `logging.getLogger("knowledge-rag-mcp...")` with `logging.getLogger("contextcortex...")` in:
  - `app/api/webhooks.py` -> `"contextcortex.webhook"`
  - `app/mcp/tools.py` -> `"contextcortex"`
  - `app/services/db.py` -> `"contextcortex.db"`
  - `app/services/embeddings.py` -> `"contextcortex.embeddings"`
  - `app/services/git_manager.py` -> `"contextcortex.git"`
  - `app/services/indexer.py` -> `"contextcortex"`
  - `app/services/poller.py` -> `"contextcortex.poller"`
  - `app/services/search.py` -> `"contextcortex"`
  - `app/services/vector_store/chroma_store.py` -> `"contextcortex.vector_store.chroma"`
  - `app/services/vector_store/manager.py` -> `"contextcortex.vector_store.manager"`
  - `app/services/vector_store/qdrant_store.py` -> `"contextcortex.vector_store.qdrant"`

- [ ] **Step 4: Update backend test assertions**
  - In `tests/backend/test_mcp_v2.py`, update `assert "ContextHub" in resp.text` to `assert "ContextCortex" in resp.text`.
  - In `tests/backend/test_diagnostic_logger.py`, update test loggers to `contextcortex.test`, `contextcortex.exception_test`, and `contextcortex.api_test`.

- [ ] **Step 5: Run backend tests to verify**
  Run: `pytest tests/backend/test_mcp_v2.py tests/backend/test_diagnostic_logger.py -v`
  Expected: PASS

- [ ] **Step 6: Commit backend changes**
  Run: `git commit -am "chore(backend): rename FastMCP server and loggers to ContextCortex"`

---

### Task 2: Frontend Branding, Package Name, and Build Distribution

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/index.html`
- Modify: `frontend/package.json`
- Modify: `frontend/src/GitRepoManager.tsx`
- Modify: `frontend/src/tests/App.test.tsx`
- Modify: `frontend/src/tests/DiagnosticsViewer.test.tsx`
- Modify: `frontend/e2e/dashboard.spec.ts`

**Interfaces:**
- Produces: Header `<h1>ContextCortex</h1>`, footer `ContextCortex MCP`, title `<title>ContextCortex</title>`, package `"contextcortex-frontend"`, updated compiled build in `frontend/dist/`.

- [ ] **Step 1: Update UI components in `frontend/src/App.tsx` and `frontend/src/GitRepoManager.tsx`**
  - In `frontend/src/App.tsx`: Replace `<h1>ContextHub</h1>` with `<h1>ContextCortex</h1>` and footer with `<p>ContextCortex MCP &bull; Universal Code & Knowledge RAG &bull; 2026</p>`.
  - In `frontend/src/GitRepoManager.tsx`: Update input placeholder to `placeholder="e.g. backend-api or contextcortex"`.

- [ ] **Step 2: Update HTML and package.json**
  - In `frontend/index.html`: Update `<title>ContextCortex</title>`.
  - In `frontend/package.json`: Update `"name": "contextcortex-frontend"`.

- [ ] **Step 3: Update frontend test specs**
  - In `frontend/src/tests/App.test.tsx`: Update `screen.getByText('ContextHub')` to `screen.getByText('ContextCortex')`.
  - In `frontend/src/tests/DiagnosticsViewer.test.tsx`: Update mock loggers to `contextcortex.server`, `contextcortex.indexer`, `contextcortex.git`.
  - In `frontend/e2e/dashboard.spec.ts`: Update `page.locator('h1', { hasText: 'ContextHub' })` to `page.locator('h1', { hasText: 'ContextCortex' })`.

- [ ] **Step 4: Run frontend tests**
  Run: `npm test --prefix frontend`
  Expected: All 74 tests PASS

- [ ] **Step 5: Rebuild production distribution**
  Run: `npm run build --prefix frontend`
  Verify: `frontend/dist/index.html` has `<title>ContextCortex</title>`

- [ ] **Step 6: Commit frontend changes**
  Run: `git commit -am "chore(frontend): update branding to ContextCortex and rebuild bundle"`

---

### Task 3: Documentation, Specification Generation, and Git Remote Update

**Files:**
- Modify: `scripts/generate_requirements.py`
- Modify: `REQUIREMENTS.md`
- Modify: `docs/REQUIREMENTS.md`
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `DEVELOPER_DOCS.md`

- [ ] **Step 1: Update `scripts/generate_requirements.py` and regenerate specifications**
  - Update title to `# Software Requirements Specification: ContextCortex (v2.7.0)` and description to `ContextCortex provides high-precision...`.
  - Run `.venv/bin/python scripts/generate_requirements.py`.
  - Run `pytest tests/backend/test_requirements_sync.py` to confirm sync.

- [ ] **Step 2: Update documentation markdown files**
  - In `README.md`: Update title, docker image badges/links to `spelech/contextcortex`, docker-compose sample, client config examples.
  - In `ARCHITECTURE.md`: Update title and overview text to ContextCortex.
  - In `DEVELOPER_DOCS.md`: Update title, git clone command to `spelech/contextcortex.git`, and client config examples.

- [ ] **Step 3: Update Git remote URL**
  - Run `git remote set-url origin git@github.com:spelech/contextcortex.git`
  - Verify with `git remote -v`

- [ ] **Step 4: Commit documentation and requirements**
  Run: `git commit -am "docs: update documentation, SRS requirements, and git remote for ContextCortex"`

---

### Task 4: MCP Compose Stack Update

**Files:**
- Modify: `/containers/mcp/docker-compose.yaml`

- [ ] **Step 1: Update ContextCortex service in `/containers/mcp/docker-compose.yaml`**
  - Service key: `contextcortex`
  - Image: `ghcr.io/spelech/contextcortex:latest`
  - Container name: `contextcortex`
  - Caddy label: `caddy=contextcortex.wileyriley.com, contexthub.wileyriley.com, notesrag.wileyriley.com`
  - Tinyauth label: `tinyauth.apps.contextcortex.config.domain=contextcortex.wileyriley.com`
  - Tinyauth groups: `tinyauth.apps.contextcortex.oauth.groups=full_admin`
  - Portal labels: `portal.contextcortex.name=ContextCortex`, `portal.contextcortex.description=...`
  - Kuma labels: `kuma.contextcortex.http.name=ContextCortex`, `kuma.contextcortex.http.url=https://contextcortex.wileyriley.com/health`
  - MCP labels: `mcp.id=contextcortex`, `mcp.displayName=ContextCortex`

- [ ] **Step 2: Commit `/containers/mcp/docker-compose.yaml`**
  - In `/containers`: `git add mcp/docker-compose.yaml && git commit -m "chore(mcp): rebrand contexthub service to contextcortex in compose stack"`

---

### Task 5: End-to-End Test Suite Verification

**Files:**
- None (Verification only)

- [ ] **Step 1: Run complete backend Pytest suite**
  Run: `pytest`
  Expected: 242 passed

- [ ] **Step 2: Run complete frontend Vitest suite**
  Run: `npm test --prefix frontend`
  Expected: 74 passed

- [ ] **Step 3: Verify clean git status**
  Run: `git status`

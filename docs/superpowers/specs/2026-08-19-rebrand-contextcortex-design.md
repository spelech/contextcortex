# Design Specification: Rebranding to ContextCortex (v2.7.0)

**Date:** 2026-08-19  
**Status:** Approved  
**Topic:** Rebrand project from `ContextHub` / `contexthub` (and residual `knowledge-rag-mcp` / `notes-rag`) to `ContextCortex` / `contextcortex`.

---

## 1. Overview & Goals

This specification details the comprehensive rebranding of the project to **ContextCortex**. The scope covers backend FastMCP definitions, FastAPI application titles, logging namespaces, React 19 frontend UI headers/footers/titles, documentation, requirement generators, test suites, git remote references, and the deployment configuration in `/containers/mcp/docker-compose.yaml`.

---

## 2. Naming Standards & Conventions

| Context | Target Identifier / Name | Previous Values |
| :--- | :--- | :--- |
| **Product & UI Brand** | `ContextCortex` | `ContextHub`, `Knowledge RAG Hub` |
| **FastMCP Server Name** | `ContextCortex` | `ContextHub`, `knowledge-rag-mcp` |
| **FastAPI App Title** | `ContextCortex` | `ContextHub`, `Knowledge RAG MCP Server` |
| **Python Root Logger** | `contextcortex` | `contexthub`, `knowledge-rag-mcp` |
| **Backend Subsystem Loggers** | `contextcortex.<subsystem>` (e.g. `contextcortex.indexer`, `contextcortex.git`, `contextcortex.db`, `contextcortex.webhook`, `contextcortex.poller`, `contextcortex.vector_store.*`) | `knowledge-rag-mcp.<subsystem>` |
| **Frontend Package Name** | `contextcortex-frontend` | `contexthub-frontend`, `knowledge-rag-mcp-frontend` |
| **Frontend Page Titles** | `<title>ContextCortex</title>` | `<title>ContextHub</title>` |
| **GitHub Repository Slug** | `spelech/contextcortex` | `spelech/contexthub`, `spelech/knowledge-rag-mcp` |
| **Git Remote Origin** | `git@github.com:spelech/contextcortex.git` | `git@github.com:spelech/contexthub.git` |
| **Docker Image Registry** | `ghcr.io/spelech/contextcortex:latest` | `ghcr.io/spelech/contexthub:latest`, `ghcr.io/spelech/knowledge-rag-mcp:latest` |
| **MCP Compose Service Name** | `contextcortex` (in `/containers/mcp/docker-compose.yaml`) | `contexthub` |
| **Caddy Ingress Domains** | `contextcortex.wileyriley.com, contexthub.wileyriley.com, notesrag.wileyriley.com` | `contexthub.wileyriley.com, notesrag.wileyriley.com` |
| **Portal / Kuma Labels** | `portal.contextcortex.*`, `kuma.contextcortex.*`, `tinyauth.apps.contextcortex.*` | `portal.contexthub.*`, `kuma.contexthub.*` |

---

## 3. Detailed Component Changes

### 3.1 Backend & Server Architecture
1. **`app/mcp/mcp_server.py`**:
   - Update FastMCP server initialization:
     ```python
     mcp_server = FastMCP(
         "ContextCortex",
         instructions="ContextCortex: Universal Code & Knowledge RAG server providing hybrid search, AST code symbols, documentation retrieval, and repository indexing.",
     )
     ```
2. **`main.py`**:
   - `logger = logging.getLogger("contextcortex")`
   - `logger.info("ContextCortex Server starting up...")`
   - `logger.info("ContextCortex Server shutting down...")`
   - `app = FastAPI(title="ContextCortex", version="2.7.0", lifespan=lifespan)`
3. **Backend Service Loggers**:
   - Update all backend `logging.getLogger(...)` calls across `app/api/webhooks.py`, `app/mcp/tools.py`, `app/services/db.py`, `app/services/embeddings.py`, `app/services/git_manager.py`, `app/services/indexer.py`, `app/services/poller.py`, `app/services/search.py`, and `app/services/vector_store/*.py` to `contextcortex.*`.

### 3.2 Frontend UI & Dashboard
1. **`frontend/src/App.tsx`**:
   - Main header: `<h1>ContextCortex</h1>`
   - Footer: `<p>ContextCortex MCP &bull; Universal Code & Knowledge RAG &bull; 2026</p>`
2. **`frontend/index.html` & `frontend/dist/index.html`**:
   - `<title>ContextCortex</title>`
3. **`frontend/package.json`**:
   - `"name": "contextcortex-frontend"`
4. **`frontend/src/GitRepoManager.tsx`**:
   - Update repository alias input placeholder: `placeholder="e.g. backend-api or contextcortex"`
5. **Rebuild Bundle**:
   - Recompile frontend assets via `npm run build --prefix frontend`.

### 3.3 Documentation & Requirements Generator
1. **`scripts/generate_requirements.py`**:
   - Update SRS document header to `# Software Requirements Specification: ContextCortex (v2.7.0)`
   - Update System Vision to `ContextCortex provides high-precision...`
   - Execute `.venv/bin/python scripts/generate_requirements.py` to regenerate `REQUIREMENTS.md` and `docs/REQUIREMENTS.md`.
2. **`README.md`**:
   - Title: `# ContextCortex (v2.7.0)`
   - GitHub Action badge: `https://github.com/spelech/contextcortex/actions/workflows/docker-publish.yml`
   - Docker image badge: `https://github.com/spelech/contextcortex/pkgs/container/contextcortex`
   - Description: `with an integrated Web Admin Dashboard (ContextCortex)`
   - Docker Compose example: service name `contextcortex`, image `ghcr.io/spelech/contextcortex:latest`
   - MCP client config examples: `"contextcortex"` and `"contextcortex-http"`
3. **`ARCHITECTURE.md`**:
   - Title: `# Architecture: ContextCortex (v2.7.0)`
   - Overview: `ContextCortex provides fast, local...`
   - Component references: FastMCP server `ContextCortex`, logger namespaces `contextcortex.*`, and dashboard references.
4. **`DEVELOPER_DOCS.md`**:
   - Title: `# Developer Documentation: ContextCortex (v2.7.0)`
   - Clone command: `git clone git@github.com:spelech/contextcortex.git` and `cd contextcortex`
   - MCP Client configuration examples: `"contextcortex-sse"` and `"contextcortex-http"`.

### 3.4 MCP Compose Stack (`/containers/mcp/docker-compose.yaml`)
1. Update service definition from `contexthub` to `contextcortex`.
2. Update image to `ghcr.io/spelech/contextcortex:latest`.
3. Update container name to `contextcortex`.
4. Update Caddy reverse proxy label to include `contextcortex.wileyriley.com` (while keeping fallback aliases `contexthub.wileyriley.com, notesrag.wileyriley.com`).
5. Update TinyAuth domain `tinyauth.apps.contextcortex.config.domain=contextcortex.wileyriley.com`.
6. Update Homelab Portal labels (`portal.contextcortex.name=ContextCortex`, `portal.contextcortex.description=...`).
7. Update Kuma health check labels (`kuma.contextcortex.http.name=ContextCortex`, `url=https://contextcortex.wileyriley.com/health`).
8. Update MCP metadata labels (`mcp.id=contextcortex`, `mcp.displayName=ContextCortex`).

### 3.5 Git Remote Configuration
1. Run `git remote set-url origin git@github.com:spelech/contextcortex.git`.
2. Confirm with `git remote -v`.

### 3.6 Automated Tests & Verification
1. **`tests/backend/test_mcp_v2.py`**:
   - `assert "ContextCortex" in resp.text`
2. **`tests/backend/test_diagnostic_logger.py`**:
   - Update test logger names to `contextcortex.test`, `contextcortex.exception_test`, `contextcortex.api_test`.
3. **`frontend/src/tests/App.test.tsx`**:
   - `expect(screen.getByText('ContextCortex')).toBeInTheDocument();`
4. **`frontend/src/tests/DiagnosticsViewer.test.tsx`**:
   - Update mock logger names to `contextcortex.server`, `contextcortex.indexer`, `contextcortex.git`.
5. **`frontend/e2e/dashboard.spec.ts`**:
   - `await expect(page.locator('h1', { hasText: 'ContextCortex' })).toBeVisible();`
6. **Execution Verification**:
   - Run `pytest` across all 242 backend tests.
   - Run `npm test --prefix frontend` across all 74 Vitest tests.
   - Run `pytest tests/backend/test_requirements_sync.py`.

---

## 4. Risks & Mitigations

- **Risk:** Caddy routing interruption if external DNS isn't pointed yet.  
  **Mitigation:** Retain existing `contexthub.wileyriley.com` and `notesrag.wileyriley.com` in Caddy domains label.
- **Risk:** Breakages in test suites due to mismatched logger names.  
  **Mitigation:** Full test suite execution across backend and frontend before completion.

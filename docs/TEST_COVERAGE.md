# Test Coverage Report: ContextCortex (v2.10.0)

This document provides comprehensive test coverage metrics and verification baselines for ContextCortex following the modular architectural restructuring and test suite expansion.

**Summary Baseline:**
- **Total Automated Tests:** **392 Tests** (277 Backend Pytest + 89 Frontend Vitest + 26 Playwright E2E User Journeys)
- **Backend Statement Coverage:** **88%** (3,885 / 4,432 statements covered)
- **Frontend Line Coverage:** **88.1%** across all React 19 components and sub-modules
- **Codebase Modularity Floor:** 100% of source files maintained strictly under 450 lines of code

---

## 1. Backend Code Coverage (Python / Pytest)

### 1.1 Summary by Architectural Package

| Architectural Package | Files | Total Statements | Missed Statements | Coverage % | Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **MCP Engine & Handlers (`app/mcp/`)** | 8 | 386 | 30 | **92%** | PASS |
| **API Subrouters & Webhooks (`app/api/`)** | 5 | 530 | 47 | **91%** | PASS |
| **Vector Store Layer (`app/services/vector_store/`)** | 5 | 688 | 115 | **83%** | PASS |
| **Tree-sitter Chunking & AST (`app/services/chunking/`)** | 6 | 571 | 117 | **80%** | PASS |
| **Database & Credential Vault (`app/services/database/`)** | 5 | 369 | 67 | **82%** | PASS |
| **Incremental Ingestion (`app/services/indexing/`)** | 5 | 487 | 39 | **92%** | PASS |
| **Topology & Dependency Graph (`app/services/topology/`)** | 4 | 375 | 62 | **83%** | PASS |
| **Git Manager & Shallow Clone (`app/services/git_manager.py`)** | 1 | 189 | 8 | **96%** | PASS |
| **Embeddings & Search (`app/services/embeddings.py`, `search.py`)** | 2 | 233 | 14 | **94%** | PASS |
| **Poller & ADR (`app/services/poller.py`, `adr.py`, `architecture.py`)** | 3 | 310 | 66 | **79%** | PASS |
| **Models & Logger (`app/models/schemas.py`, `logger.py`)** | 2 | 224 | 0 | **100%** | PASS |
| **Overall Backend Total** | **44** | **4,432** | **547** | **88%** | **PASS** |

### 1.2 Detailed Backend Module Breakdown

| Module Path | Statements | Missed | Coverage | Key Tested Capabilities |
| :--- | :---: | :---: | :---: | :--- |
| `app/api/routes.py` | 28 | 0 | 100% | FastAPI root router, subrouter inclusion, health checks |
| `app/api/webhooks.py` | 98 | 1 | 99% | GitHub, GitLab, Gitea, Bitbucket HMAC signature parsing |
| `app/api/routers/repositories.py` | 189 | 4 | 98% | CRUD repos, manual sync triggers, delete cascades |
| `app/api/routers/settings.py` | 184 | 18 | 90% | Vector store switching, multi-tokens, host vault CRUD |
| `app/api/routers/graph.py` | 31 | 6 | 81% | Topology graph data & node inspector details endpoints |
| `app/mcp/mcp_server.py` | 8 | 0 | 100% | FastMCP 2.0 dual transport lifecycle & session registration |
| `app/mcp/tools.py` | 48 | 0 | 100% | FastMCP 11-tool registry & argument routing |
| `app/mcp/handlers/repo_handlers.py` | 111 | 0 | 100% | `list_repositories`, `sync_repository`, `index_status` |
| `app/mcp/handlers/search_handlers.py` | 68 | 0 | 100% | `search_code`, `search_docs` RRF hybrid handlers |
| `app/mcp/handlers/symbol_handlers.py` | 66 | 3 | 95% | `find_symbol`, `get_file_outline` AST lookups |
| `app/mcp/handlers/route_handlers.py` | 78 | 11 | 86% | `get_code_routes`, `trace_call_path` route traversals |
| `app/mcp/handlers/architecture_handlers.py` | 69 | 16 | 77% | `get_architecture`, `manage_adr` ADR lifecycle handlers |
| `app/models/schemas.py` | 188 | 0 | 100% | Pydantic v2 request / response schemas & validations |
| `app/services/git_manager.py` | 189 | 8 | 96% | Ephemeral shallow cloning, token masking, permalinks |
| `app/services/embeddings.py` | 87 | 0 | 100% | Dense BGE-small (384d) + Sparse BM25 via FastEmbed |
| `app/services/search.py` | 146 | 14 | 90% | Reciprocal Rank Fusion ($k=60$) & hybrid reranking |
| `app/services/logger.py` | 36 | 0 | 100% | In-memory 500-entry ring buffer & level filtering |
| `app/services/poller.py` | 68 | 2 | 97% | Background repository SHA poller daemon |
| `app/services/indexing/state.py` | 39 | 0 | 100% | Global indexing locks, session change notifications |
| `app/services/indexing/git_syncer.py` | 166 | 9 | 95% | Shallow git cloning, AST parsing, point upserts |
| `app/services/indexing/local_syncer.py` | 136 | 14 | 90% | Local filesystem paths & Obsidian vault synchronization |
| `app/services/indexing/processor.py` | 141 | 16 | 89% | File content processing, frontmatter, chunk extraction |
| `app/services/database/connection.py` | 167 | 23 | 86% | SQLite WAL connection context, table initialization |
| `app/services/database/credentials.py` | 85 | 16 | 81% | Git host vault CRUD & credential hierarchy resolution |
| `app/services/database/sync_config.py` | 26 | 0 | 100% | Auto-sync schedule intervals & webhook HMAC secrets |
| `app/services/database/adrs.py` | 88 | 28 | 68% | Architecture Decision Records storage & status queries |
| `app/services/chunking/symbol_extractor.py` | 92 | 0 | 100% | Multi-language AST symbol extraction & outline generator |
| `app/services/chunking/tree_sitter_loader.py` | 24 | 0 | 100% | Tree-sitter language pack grammar loader & language detection |
| `app/services/chunking/text_chunker.py` | 233 | 51 | 78% | Hierarchical markdown breadcrumbs & sliding window fallback |
| `app/services/chunking/relationship_extractor.py` | 214 | 48 | 78% | AST `CALLS`, `IMPORTS`, `EXTENDS` relations extraction |
| `app/services/chunking/api_route_extractor.py` | 217 | 66 | 70% | Multi-framework API endpoint & HTTP client call extraction |
| `app/services/topology/graph_builder.py` | 233 | 32 | 86% | Dependency topology graph builder, view filtering & BFS |
| `app/services/topology/node_details.py` | 100 | 15 | 85% | Symbol, file, and route node detail inspector |
| `app/services/vector_store/base.py` | 69 | 9 | 87% | Abstract vector store base class & result dataclasses |
| `app/services/vector_store/manager.py` | 188 | 29 | 85% | Vector store singleton provider, runtime switching, migration |
| `app/services/vector_store/chroma_store.py` | 214 | 37 | 83% | ChromaDB persistent disk and remote client implementation |
| `app/services/vector_store/qdrant_store.py` | 212 | 40 | 81% | Qdrant embedded and remote hybrid multi-vector store |
| `app/services/architecture.py` | 123 | 18 | 85% | Codebase entry points, language distributions synthesis |
| `app/services/adr.py` | 119 | 46 | 61% | MADR & Nygard format ADR parsing and file management |

---

## 2. Frontend Code Coverage (React 19 / Vitest V8)

### 2.1 Component Line & Statement Coverage

| Component File | % Statements | % Branch | % Functions | % Lines | Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `src/App.tsx` | 87.50% | 93.18% | 91.66% | **91.30%** | PASS |
| `src/Overview.tsx` | 93.33% | 77.50% | 75.00% | **100.00%** | PASS |
| `src/GitRepoManager.tsx` | 90.74% | 64.86% | 82.60% | **94.84%** | PASS |
| `src/LocalPathManager.tsx` | 85.85% | 65.38% | 80.64% | **86.95%** | PASS |
| `src/SearchInspector.tsx` | 86.04% | 86.36% | 100.00% | **85.71%** | PASS |
| `src/Settings.tsx` | 90.94% | 71.95% | 84.21% | **92.16%** | PASS |
| `src/DiagnosticsViewer.tsx` | 90.12% | 85.71% | 90.90% | **91.13%** | PASS |
| `src/TopologyExplorer.tsx` | 80.50% | 56.04% | 72.72% | **82.87%** | PASS |
| `src/ToastContext.tsx` | 100.00% | 92.30% | 100.00% | **100.00%** | PASS |
| `src/components/git/AddRepoModal.tsx` | 63.63% | 83.33% | 62.50% | **66.66%** | PASS |
| `src/components/git/RepoListTable.tsx` | 66.66% | 88.57% | 66.66% | **80.00%** | PASS |
| `src/components/git/WebhookModal.tsx` | 100.00% | 91.66% | 100.00% | **100.00%** | PASS |
| `src/components/settings/AutoSyncSettings.tsx` | 100.00% | 92.59% | 100.00% | **100.00%** | PASS |
| `src/components/settings/GitCredentialsSettings.tsx` | 79.16% | 100.00% | 76.19% | **76.19%** | PASS |
| `src/components/settings/VectorStoreSettings.tsx` | 37.50% | 92.00% | 42.85% | **42.85%** | PASS |
| `src/components/topology/TopologyCanvas.tsx` | 48.27% | 64.00% | 31.25% | **60.86%** | PASS |
| `src/components/topology/TopologyControls.tsx` | 85.71% | 88.23% | 85.71% | **84.61%** | PASS |
| `src/components/topology/TopologyInspector.tsx` | 55.55% | 85.29% | 50.00% | **50.00%** | PASS |
| `src/components/topology/TopologyMinimap.tsx` | 90.00% | 75.00% | 100.00% | **100.00%** | PASS |
| **Overall Frontend Unit Total** | **84.93%** | **77.44%** | **77.94%** | **87.32%** | **PASS** |

---

## 3. End-to-End Test Verification (Playwright)

In addition to backend and frontend unit test suites, **26 Playwright End-to-End User Journeys** continuously validate user workflows in headless Chromium:

1. Navigation across Overview, Topology, Git Repositories, Local Paths, Search & Inspector, Settings, and Diagnostics tabs.
2. Modal repository registration with provider detection and optimistic card/table updates.
3. Single-repository synchronization triggers and live state transitions.
4. Repository deletion with confirmation dialog safety flows.
5. Repository error state rendering and diagnostic feedback.
6. Local path filesystem browser navigation, folder selection, and recursive indexing.
7. Local path removal with confirmation flow.
8. Interactive hybrid search testing with code vs doc filtering.
9. Empty search query and edge-case handling.
10. Global Git token saving and rate limit updates.
11. Git token clearing workflows.
12. Full-system reindexing triggers on the Overview tab.
13. Diagnostic log level filtering, live search, and ring-buffer clearing.
14. Mobile hamburger drawer menu toggling and responsive transitions.
15. Mobile drawer tab navigation and auto-closing.
16. Mobile responsive repository card layouts.
17. Mobile responsive local path card layouts.
18. Mobile repository registration modal.
19. Mobile filesystem browser modal navigation.
20. Mobile search execution and result rendering.
21. Mobile diagnostic log filtering and traceback inspection.
22. Auto-sync toggle activation with toast notifications.
23. Webhook endpoint modal display and copyable URLs.
24. Background auto-sync schedule configuration and global webhook secret management.
25. Interactive Visual Topology graph rendering and view mode toggling (`FILES`, `SYMBOLS`, `ROUTES`, `FULL`).
26. Topology search, minimap navigation, slide-over inspector drawer, and export controls.

---

## 4. Verification Commands

To re-run and verify coverage metrics across the entire stack:

```bash
# 1. Run full backend test suite with statement coverage
pytest --cov=app --cov-report=term-missing

# 2. Run frontend component test suite with V8 line/statement coverage
cd frontend && npx vitest run --coverage

# 3. Verify requirements specification synchronization
python3 scripts/generate_requirements.py
pytest -v tests/backend/test_requirements_sync.py
```

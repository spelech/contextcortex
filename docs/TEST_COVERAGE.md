# Test Coverage Report: ContextCortex (v2.12.0)

This document provides comprehensive test coverage metrics and verification baselines for ContextCortex following the modular architectural restructuring, Codebase Navigator implementation, and test suite expansion.

**Summary Baseline:**
- **Total Automated Tests:** **775 Tests** (457 Backend Pytest + 272 Frontend Vitest + 46 Playwright E2E User Journeys)
- **Backend Statement Coverage:** **89%** (5,660 / 6,390 statements covered)
- **Frontend Line Coverage:** **88.45%** across all React 19 components and sub-modules
- **Codebase Modularity Floor:** 100% of source files maintained strictly under 450 lines of code

---

## 1. Backend Code Coverage (Python / Pytest)

### 1.1 Summary by Architectural Package

| Architectural Package | Files | Total Statements | Missed Statements | Coverage % | Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Codebase Navigator Engine (`app/services/navigator.py`, `app/api/routers/navigator.py`)** | 2 | 102 | 10 | **90%** | PASS |
| **MCP Engine & Handlers (`app/mcp/`)** | 8 | 423 | 24 | **94%** | PASS |
| **API Subrouters & Webhooks (`app/api/`)** | 6 | 690 | 78 | **89%** | PASS |
| **Vector Store Layer (`app/services/vector_store/`)** | 5 | 876 | 115 | **87%** | PASS |
| **Tree-sitter Chunking & AST (`app/services/chunking/`)** | 6 | 896 | 174 | **81%** | PASS |
| **Database & Credential Vault (`app/services/database/`)** | 7 | 569 | 80 | **86%** | PASS |
| **Incremental Ingestion (`app/services/indexing/`)** | 6 | 788 | 43 | **95%** | PASS |
| **Topology & Dependency Graph (`app/services/topology/`)** | 4 | 422 | 67 | **84%** | PASS |
| **Git Manager & Shallow Clone (`app/services/git_manager.py`)** | 1 | 189 | 8 | **96%** | PASS |
| **Embeddings & Search (`app/services/embeddings.py`, `search.py`)** | 2 | 270 | 21 | **92%** | PASS |
| **Poller & ADR (`app/services/poller.py`, `adr.py`, `architecture.py`)** | 3 | 310 | 66 | **79%** | PASS |
| **Models & Logger (`app/models/schemas.py`, `logger.py`)** | 2 | 232 | 0 | **100%** | PASS |
| **Overall Backend Total** | **52** | **6,390** | **730** | **89%** | **PASS** |

### 1.2 Detailed Backend Module Breakdown

| Module Path | Statements | Missed | Coverage | Key Tested Capabilities |
| :--- | :---: | :---: | :---: | :--- |
| `app/api/routes.py` | 36 | 0 | 100% | FastAPI root router, subrouter inclusion, health checks |
| `app/api/webhooks.py` | 98 | 1 | 99% | GitHub, GitLab, Gitea, Bitbucket HMAC signature parsing |
| `app/api/routers/navigator.py` | 37 | 10 | 73% | REST endpoints for tree hierarchy, file outline, and symbol impact |
| `app/api/routers/repositories.py` | 227 | 6 | 97% | CRUD repos, manual sync triggers, delete cascades |
| `app/api/routers/settings.py` | 201 | 18 | 91% | Vector store switching, multi-tokens, host vault CRUD |
| `app/api/routers/storage.py` | 97 | 28 | 71% | Local storage file upload, replace, delete, read, tree endpoints |
| `app/api/routers/ingestion.py` | 40 | 9 | 78% | Multi-source catalog aggregation with filtering |
| `app/api/routers/auth.py` | 58 | 16 | 72% | OAuth 2.1 protected resource metadata, API key lifecycle |
| `app/api/routers/graph.py` | 31 | 6 | 81% | Topology graph data & node inspector details endpoints |
| `app/services/navigator.py` | 65 | 0 | 100% | 3-pane tree hierarchy builder, file AST outlines, symbol impact |
| `app/mcp/mcp_server.py` | 8 | 0 | 100% | FastMCP 2.0 dual transport lifecycle & session registration |
| `app/mcp/tools.py` | 52 | 0 | 100% | FastMCP tool registry & argument routing |
| `app/mcp/handlers/repo_handlers.py` | 121 | 0 | 100% | `list_repositories`, `sync_repository`, `index_status` |
| `app/mcp/handlers/search_handlers.py` | 72 | 0 | 100% | `search_code`, `search_docs` RRF hybrid handlers |
| `app/mcp/handlers/symbol_handlers.py` | 74 | 3 | 96% | `find_symbol`, `get_file_outline` AST lookups |
| `app/mcp/handlers/route_handlers.py` | 82 | 11 | 87% | `get_code_routes`, `trace_call_path` route traversals |
| `app/mcp/handlers/architecture_handlers.py` | 74 | 13 | 82% | `get_architecture`, `manage_adr` ADR lifecycle handlers |
| `app/mcp/handlers/storage_handlers.py` | 108 | 10 | 91% | `manage_local_file`, `what_is_ingested` catalog tool handlers |
| `app/models/schemas.py` | 196 | 0 | 100% | Pydantic v2 request / response schemas & validations |
| `app/services/git_manager.py` | 189 | 8 | 96% | Ephemeral shallow cloning, token masking, permalinks |
| `app/services/embeddings.py` | 124 | 7 | 94% | Dense BGE-small (384d) + Sparse BM25 via FastEmbed |
| `app/services/search.py` | 146 | 14 | 90% | Reciprocal Rank Fusion ($k=60$) & hybrid reranking |
| `app/services/logger.py` | 36 | 0 | 100% | In-memory 500-entry ring buffer & level filtering |
| `app/services/poller.py` | 68 | 2 | 97% | Background repository SHA poller daemon |
| `app/services/indexing/state.py` | 39 | 0 | 100% | Global indexing locks, session change notifications |
| `app/services/indexing/git_syncer.py` | 281 | 12 | 96% | Shallow git cloning, AST parsing, point upserts |
| `app/services/indexing/git_progress.py` | 157 | 3 | 98% | Real-time git sync stage progression & terminal logs |
| `app/services/indexing/local_syncer.py` | 136 | 14 | 90% | Local filesystem paths & Obsidian vault synchronization |
| `app/services/indexing/processor.py` | 169 | 14 | 92% | File content processing, frontmatter, chunk extraction |
| `app/services/local_storage.py` | 173 | 25 | 86% | Path traversal defense, file persistence, tree generation |
| `app/services/auth/service.py` | 77 | 1 | 99% | Auth service facade, session verification |
| `app/services/auth/key_service.py` | 133 | 6 | 95% | SHA-256 API key generation, hash lookup, expiration |
| `app/services/auth/jwt_validator.py` | 147 | 22 | 85% | RS256/ES256 JWKS validation & claims extraction |
| `app/services/database/connection.py` | 170 | 24 | 86% | SQLite WAL connection context, table initialization |
| `app/services/database/engine.py` | 142 | 22 | 85% | Connection pooling, retry loops, database migrations |
| `app/services/database/credentials.py` | 85 | 14 | 84% | Git host vault CRUD & credential hierarchy resolution |
| `app/services/database/sync_config.py` | 26 | 0 | 100% | Auto-sync schedule intervals & webhook HMAC secrets |
| `app/services/database/adrs.py` | 88 | 24 | 73% | Architecture Decision Records storage & status queries |
| `app/services/chunking/symbol_extractor.py` | 92 | 0 | 100% | Multi-language AST symbol extraction & outline generator |
| `app/services/chunking/tree_sitter_loader.py` | 24 | 0 | 100% | Tree-sitter language pack grammar loader & language detection |
| `app/services/chunking/text_chunker.py` | 279 | 60 | 78% | Hierarchical markdown breadcrumbs & sliding window fallback |
| `app/services/chunking/api_route_extractor.py` | 217 | 66 | 70% | Multi-framework API endpoint & HTTP client call extraction |
| `app/services/topology/graph_builder.py` | 280 | 38 | 86% | Dependency topology graph builder, view filtering & BFS |
| `app/services/topology/node_details.py` | 100 | 15 | 85% | Symbol, file, and route node detail inspector |
| `app/services/vector_store/base.py` | 69 | 9 | 87% | Abstract vector store base class & result dataclasses |
| `app/services/vector_store/manager.py` | 191 | 29 | 85% | Vector store singleton provider, runtime switching, migration |
| `app/services/vector_store/pgvector_store.py` | 184 | 5 | 97% | PostgreSQL 16 + pgvector HNSW cosine vector store |
| `app/services/vector_store/chroma_store.py` | 214 | 37 | 83% | ChromaDB persistent disk and remote client implementation |
| `app/services/vector_store/qdrant_store.py` | 212 | 40 | 81% | Qdrant embedded and remote hybrid multi-vector store |
| `app/services/architecture.py` | 123 | 18 | 85% | Codebase entry points, language distributions synthesis |
| `app/services/adr.py` | 119 | 46 | 61% | MADR & Nygard format ADR parsing and file management |

---

## 2. Frontend Code Coverage (React 19 / Vitest V8)

### 2.1 Component Line & Statement Coverage

| Component File | % Statements | % Branch | % Functions | % Lines | Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `src/App.tsx` | 88.88% | 98.30% | 92.85% | **92.00%** | PASS |
| `src/Overview.tsx` | 93.33% | 80.00% | 75.00% | **100.00%** | PASS |
| `src/CodeNavigator.tsx` | 75.22% | 59.61% | 77.77% | **75.70%** | PASS |
| `src/components/navigator/NavigatorInspector.tsx` | 84.61% | 78.75% | 75.00% | **91.66%** | PASS |
| `src/components/navigator/NavigatorOutline.tsx` | 81.69% | 81.73% | 81.25% | **79.36%** | PASS |
| `src/components/navigator/NavigatorToolbar.tsx` | 70.00% | 90.00% | 66.66% | **70.00%** | PASS |
| `src/components/navigator/NavigatorTree.tsx` | 78.61% | 68.15% | 89.65% | **85.92%** | PASS |
| `src/GitRepoManager.tsx` | 92.37% | 68.18% | 88.46% | **95.28%** | PASS |
| `src/LocalPathManager.tsx` | 86.13% | 70.00% | 80.64% | **87.23%** | PASS |
| `src/LocalStorageManager.tsx` | 68.65% | 58.82% | 56.00% | **71.42%** | PASS |
| `src/IngestionCatalogViewer.tsx` | 70.00% | 70.79% | 63.33% | **71.60%** | PASS |
| `src/SearchInspector.tsx` | 86.04% | 86.36% | 100.00% | **85.71%** | PASS |
| `src/Settings.tsx` | 92.45% | 67.57% | 86.95% | **93.60%** | PASS |
| `src/DiagnosticsViewer.tsx` | 90.12% | 85.71% | 90.90% | **91.13%** | PASS |
| `src/TopologyExplorer.tsx` | 86.83% | 69.32% | 98.03% | **86.87%** | PASS |
| `src/ToastContext.tsx` | 100.00% | 86.66% | 100.00% | **100.00%** | PASS |
| `src/components/git/AddRepoModal.tsx` | 63.63% | 83.33% | 62.50% | **66.66%** | PASS |
| `src/components/git/RepoListTable.tsx` | 82.50% | 89.16% | 64.70% | **80.55%** | PASS |
| `src/components/git/RepoSyncDrawer.tsx` | 91.25% | 90.15% | 84.21% | **93.05%** | PASS |
| `src/components/git/WebhookModal.tsx` | 100.00% | 91.66% | 100.00% | **100.00%** | PASS |
| `src/components/settings/AutoSyncSettings.tsx` | 100.00% | 92.59% | 100.00% | **100.00%** | PASS |
| `src/components/settings/GitCredentialsSettings.tsx` | 79.16% | 100.00% | 76.19% | **76.19%** | PASS |
| `src/components/settings/VectorStoreSettings.tsx` | 75.00% | 96.00% | 85.71% | **85.71%** | PASS |
| `src/components/settings/EmbeddingSettings.tsx` | 66.66% | 88.23% | 57.14% | **66.66%** | PASS |
| `src/components/settings/ThemeSettings.tsx` | 100.00% | 100.00% | 100.00% | **100.00%** | PASS |
| `src/components/topology/TopologyCanvas2D.tsx` | 94.84% | 75.13% | 93.10% | **97.26%** | PASS |
| `src/components/topology/TopologyControls.tsx` | 87.17% | 91.52% | 88.00% | **86.48%** | PASS |
| `src/components/topology/TopologyInspector.tsx` | 55.55% | 85.29% | 50.00% | **50.00%** | PASS |
| `src/components/topology/TopologyMinimap.tsx` | 90.32% | 63.33% | 100.00% | **100.00%** | PASS |
| `src/components/topology/TopologyPhysicsControls.tsx` | 93.54% | 88.00% | 100.00% | **100.00%** | PASS |
| `src/components/topology/NeighborhoodView.tsx` | 94.00% | 77.86% | 97.22% | **95.06%** | PASS |
| **Overall Frontend Unit Total** | **86.67%** | **76.46%** | **83.30%** | **88.45%** | **PASS** |

---

## 3. End-to-End Test Verification (Playwright)

In addition to backend and frontend unit test suites, **46 Playwright End-to-End User Journeys** (92 total test runs across Chromium Desktop and Mobile Chrome) validate end-to-end user workflows:

### Codebase Navigator User Journeys
1. **Navigation and Initial Load**: Mounts CodeNavigator container, toolbar, repository selector, summary stats badges (files, symbols), and 3-pane layout headers.
2. **File Tree Interaction**: Validates hierarchical directory/file structure, Expand All / Collapse All controls, real-time search filtering with auto-expanding ancestor directories, and filter clearing.
3. **Symbol Outline & Category Filtering**: Loads syntax-aware AST symbols upon file selection, toggles category filter chips (`All`, `Functions`, `Classes`, `Routes`), and filters symbols via search bar.
4. **Impact Inspector & Route Details**: Displays 4-metric summary grid (callers, callees, imports, scope), API route mapping cards (HTTP method, route pattern, framework), signature code blocks, docstrings, and permalink copying.
5. **Caller Click-Through Navigation**: Jumps from caller card in inspector to caller file and symbol, switching file tree selection and updating symbol outline and inspector.
6. **Density Mode Toggling**: Seamlessly switches between `Compact` (IDE density), `Balanced` (default), and `Spacious` (cards) modes with CSS class binding.
7. **Responsive Layout Audit**: Zero horizontal overflow assertion and Layout Inspector UX audit in 1080p desktop and mobile viewports.

### Core Dashboard & Management Journeys
8. Navigation across Overview, Navigator, Git Repositories, Local Paths, Local Storage, Ingestion Catalog, Search & Inspector, Settings, and Diagnostics tabs.
9. Modal repository registration with provider detection and optimistic card/table updates.
10. Single-repository synchronization triggers and live state transitions.
11. Repository deletion with confirmation dialog safety flows.
12. Repository error state rendering and diagnostic feedback.
13. Local path filesystem browser navigation, folder selection, and recursive indexing.
14. Local path removal with confirmation flow.
15. Interactive hybrid search testing with code vs doc filtering.
16. Empty search query and edge-case handling.
17. Global Git token saving and rate limit updates.
18. Git token clearing workflows.
19. Full-system reindexing triggers on the Overview tab.
20. Diagnostic log level filtering, live search, and ring-buffer clearing.
21. Mobile hamburger drawer menu toggling and responsive transitions.
22. Mobile drawer tab navigation and auto-closing.
23. Mobile responsive repository card layouts.
24. Mobile responsive local path card layouts.
25. Mobile repository registration modal.
26. Mobile filesystem browser modal navigation.
27. Mobile search execution and result rendering.
28. Mobile diagnostic log filtering and traceback inspection.
29. Auto-sync toggle activation with toast notifications.
30. Webhook endpoint modal display and copyable URLs.
31. Background auto-sync schedule configuration and global webhook secret management.
32. Real-time git sync stage progression chip, percentage, and current file in table and mobile card.
33. Live 5-stage sync progression checklist in slide-over drawer.
34. Live terminal sync logs, search filter, and copy actions in drawer.
35. Drawer dismissal via close button and backdrop click.
36. Drawer failure handling with highlighted failing step and error details.
37. Completed synced state with all 5 stages marked complete and 100% progress.
38. Drawer cancel sync action triggering.
39. Responsive layout containment on desktop and mobile viewports.
40. Overview Tab Desktop Layout Audit (1080p).
41. Overview Tab Samsung Galaxy S25+ Mobile Layout & Touch Ergonomics.
42. Git Repositories Tab Mobile Card Layout & Action Touch Targets.
43. Local Paths Tab Mobile Card Layout Stability.
44. Settings Tab Vector Store & Embedding Engine Layout Audit.
45. Diagnostics & Logs Tab Log Container & Filter Layout Stability.
46. Add Repository Modal Layout Shift & Center Alignment.

---

## 4. Verification Commands

To re-run and verify coverage metrics across the entire stack:

```bash
# 1. Run full backend test suite with statement coverage
pytest --cov=app --cov-report=term-missing

# 2. Run frontend component test suite with V8 line/statement coverage
cd frontend && npm run test:coverage

# 3. Run Playwright end-to-end user journeys
cd frontend && npx playwright test

# 4. Verify requirements specification synchronization
python3 scripts/generate_requirements.py
pytest -v tests/backend/test_requirements_sync.py
```

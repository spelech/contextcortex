# Multi-Provider Git and Multi-Vector Store Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all code review findings: resolve embedded Qdrant file lock contention during connection tests and backend switching, ensure correct permalink generation for custom/self-hosted Git providers, add missing MCP list-changed notifications on single-repo syncs, generalize MCP tools to multi-provider formatting, clean up dashboard header and overview, and update Settings and Search Inspector UI.

**Architecture:** 
1. `VectorStoreManager`: Handle active embedded directory lock collisions gracefully in `test_connection` and `switch_vector_store`.
2. `Indexer`: Thread `provider` down through `process_file_content` to `format_git_permalink`, invoke `trigger_list_changed_notification()` on single repo sync completions, and support `permalink_url` in `VectorDocument`.
3. `MCP Tools`: Generalize `index_status`, `search_code`, and `search_docs` to multi-provider naming and register `knowledge://catalog/summary`.
4. `Frontend`: Remove hardcoded GitHub rate limit from the main header, keep all provider auth/rate info in Settings, add dynamic retrieval strategy in Overview, and dynamic provider permalink buttons in Search Inspector.

**Tech Stack:** Python 3.12, FastMCP 2.0, FastAPI, Qdrant Client, ChromaDB, React, TypeScript, Vitest, Vite, pytest.

---

### Task 1: VectorStoreManager Embedded Lock Handling & Test Connection
**Files:**
- Modify: `app/services/vector_store/manager.py`
- Test: `tests/backend/test_vector_store_manager.py`
- Test: `tests/backend/test_api_vector_store.py`

**Interfaces:**
- Consumes: `VectorStoreManager.test_connection`, `VectorStoreManager.switch_vector_store`
- Produces: Robust connection testing and switching without `portalocker` directory collisions on embedded backends

- [ ] **Step 1: Write unit tests for active embedded store test_connection and in-place switching**
Add test in `tests/backend/test_vector_store_manager.py` testing `test_connection` when the active store is embedded Qdrant on the same directory, and switching collection on the same embedded Qdrant directory.

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/backend/test_vector_store_manager.py -k "test_test_connection_active_embedded or test_switch_same_embedded_directory"`

- [ ] **Step 3: Fix VectorStoreManager in app/services/vector_store/manager.py**
Update `test_connection` to delegate to `_active_store.health_check()` if testing the active embedded storage path, and update `switch_vector_store` to safely close `_active_store` prior to creating `new_store` when modifying the active embedded directory.

- [ ] **Step 4: Run backend vector store tests**
Run: `pytest tests/backend/test_vector_store_manager.py tests/backend/test_api_vector_store.py`

---

### Task 2: Multi-Git Provider Permalinks, VectorDocument Alias & MCP Sync Notifications
**Files:**
- Modify: `app/services/indexer.py`
- Modify: `app/services/vector_store/base.py`
- Test: `tests/backend/test_multi_git_providers.py`
- Test: `tests/backend/test_indexer_and_embeddings.py`

**Interfaces:**
- Consumes: `process_file_content(..., provider=provider)`, `sync_single_git_repo`, `VectorDocument.permalink_url`
- Produces: Correct GitLab/Gitea/Bitbucket permalinks for self-hosted domains, SSE notification on single repo sync

- [ ] **Step 1: Write test for self-hosted domain permalink and single repo sync notification**
Add tests in `tests/backend/test_multi_git_providers.py` and `tests/backend/test_indexer_sync.py` verifying `process_file_content` generates GitLab-style `/-/blob/` URLs for custom host with `provider="gitlab"`, and `sync_single_git_repo` triggers `trigger_list_changed_notification`.

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/backend/test_multi_git_providers.py tests/backend/test_indexer_sync.py`

- [ ] **Step 3: Implement fixes in app/services/indexer.py and app/services/vector_store/base.py**
Add `provider` argument to `process_file_content` and pass `provider=provider` to `format_git_permalink`. Add `trigger_list_changed_notification()` call in `sync_single_git_repo` on success. Add `permalink_url` property/field to `VectorDocument`.

- [ ] **Step 4: Run tests to verify they pass**
Run: `pytest tests/backend/test_multi_git_providers.py tests/backend/test_indexer_and_embeddings.py tests/backend/test_indexer_sync.py`

---

### Task 3: Multi-Provider MCP Tools & Index Status Updates
**Files:**
- Modify: `app/mcp/tools.py`
- Test: `tests/backend/test_db_and_tools.py`
- Test: `tests/backend/test_mcp_v2.py`

**Interfaces:**
- Consumes: `handle_index_status`, `handle_search_code`, `handle_search_docs`, FastMCP resource registration
- Produces: Multi-provider status output and `knowledge://catalog/summary` resource URI

- [ ] **Step 1: Write unit tests for updated handle_index_status and tool output**
Update tests in `tests/backend/test_db_and_tools.py` and `tests/backend/test_mcp_v2.py` to verify multi-provider auth sources in `handle_index_status` and dual resource registration (`notes://` and `knowledge://`).

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/backend/test_mcp_v2.py tests/backend/test_db_and_tools.py`

- [ ] **Step 3: Implement updates in app/mcp/tools.py**
Update `handle_index_status`, `handle_search_code`, `handle_search_docs`, and `register_mcp_tools_and_resources`.

- [ ] **Step 4: Run tests to verify they pass**
Run: `pytest tests/backend/test_mcp_v2.py tests/backend/test_db_and_tools.py`

---

### Task 4: Frontend UI Polish (Header, Overview, Search Inspector, Settings)
**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/Overview.tsx`
- Modify: `frontend/src/SearchInspector.tsx`
- Modify: `frontend/src/Settings.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/tests/App.test.tsx`
- Modify: `frontend/src/tests/Overview.test.tsx`
- Modify: `frontend/src/tests/SearchInspector.test.tsx`
- Modify: `frontend/src/tests/Settings.test.tsx`

**Interfaces:**
- Clean header without hardcoded GitHub-only rate limit box
- Dynamic retrieval strategy in Overview
- Dynamic provider permalink buttons in Search Inspector
- Unified provider tokens & Host Vault display in Settings

- [ ] **Step 1: Update frontend component tests**
Update test expectations in `frontend/src/tests/`.

- [ ] **Step 2: Implement UI component updates**
Update `App.tsx`, `Overview.tsx`, `SearchInspector.tsx`, and `Settings.tsx`.

- [ ] **Step 3: Run frontend vitest test suite**
Run: `npm test -- --run` in `frontend/`

---

### Task 5: Frontend Build & End-to-End Verification
**Files:**
- Build: `frontend/dist/*`
- Run: `pytest` and `npm test`

- [ ] **Step 1: Build frontend bundle**
Run: `npm run build` in `frontend/`

- [ ] **Step 2: Run full backend pytest suite**
Run: `pytest`

- [ ] **Step 3: Run full frontend vitest suite**
Run: `npm test -- --run` in `frontend/`

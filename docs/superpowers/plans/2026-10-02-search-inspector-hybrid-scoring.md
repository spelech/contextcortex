# Hybrid Search Inspector & Dynamic Scoring Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement dynamic hybrid search scoring calibration, score breakdown transparency (dense vs sparse), AST context enrichment (signatures, kind, symbol), and a redesigned Web Search Inspector with interactive split sliders, repo dropdowns, and 1-click navigation into Code Navigator.

**Architecture:** Extend `VectorSearchResult` and `VectorStore.search` to track `dense_score` and `sparse_score` and accept `dense_weight` / `search_mode`. In `search_service`, join code hits with SQLite `ast_symbols` to inject function signatures. Expose these controls via MCP tools (`search_code`, `search_docs`), `/admin/api/search/test`, and the React frontend (`SearchInspector.tsx`).

**Tech Stack:** Python 3.11, FastAPI, Qdrant Client, SQLite, React 19, TypeScript, Vitest, Vite.

## Global Constraints
- **CRITICAL**: Never push directly to `main`. Work on branch `feat/search-inspector-hybrid-scoring`.
- **CRITICAL**: No version bump or GitHub release. Keep package versions unchanged.
- Preserve full code chunk bodies in search returns for AI agents.
- All tests must pass before opening the PR.

---

### Task 1: Vector Store & Backend Scoring Calibration

**Files:**
- Modify: `app/services/vector_store/base.py`
- Modify: `app/services/vector_store/qdrant_store.py`
- Modify: `app/services/vector_store/chroma_store.py`
- Modify: `app/services/vector_store/pgvector_store.py`
- Modify: `app/services/search.py`
- Test: `tests/test_vector_store.py`

**Interfaces:**
- `VectorSearchResult` gains fields: `dense_score: Optional[float] = None`, `sparse_score: Optional[float] = None`.
- `VectorStore.search(query_text, doc_type=None, repo=None, language=None, category=None, tag=None, limit=5, dense_weight=None, search_mode="hybrid") -> List[VectorSearchResult]`.
- `execute_hybrid_search(..., dense_weight=None, search_mode="hybrid") -> List[VectorSearchResult]`.

- [ ] **Step 1: Write unit tests for dynamic weights and score decomposition**
  - Add tests in `tests/test_vector_store.py` verifying `dense_weight=0.0` (pure lexical), `dense_weight=1.0` (pure semantic), `dense_weight=0.5`, and that `dense_score` and `sparse_score` are recorded.
- [ ] **Step 2: Update `VectorSearchResult` in `app/services/vector_store/base.py`**
  - Add `dense_score` and `sparse_score` attributes.
- [ ] **Step 3: Update `qdrant_store.py` search logic**
  - Handle `dense_weight` parameter with default 0.5.
  - Handle `search_mode` (`"hybrid"`, `"semantic"`, `"lexical"`).
  - Record normalized `dense_score` and `sparse_score` on each `VectorSearchResult`.
- [ ] **Step 4: Update Chroma and PgVector store backends for signature compatibility**
- [ ] **Step 5: Enrich code search results with AST signatures in `app/services/search.py`**
  - When returning code hits, query SQLite `ast_symbols` for extracted `signature`, `full_symbol`, and `ast_symbol_id`.
- [ ] **Step 6: Run tests and verify**
  - Run pytest on `tests/test_vector_store.py` and `tests/test_search_service.py`.
- [ ] **Step 7: Commit Task 1 changes**

---

### Task 2: API & MCP Tools Enhancement

**Files:**
- Modify: `app/models/schemas.py`
- Modify: `app/api/routers/repositories.py`
- Modify: `app/mcp/handlers/search_handlers.py`
- Modify: `app/mcp/tools.py`
- Test: `tests/test_mcp_tools.py`

**Interfaces:**
- `SearchRequest` schema accepts `dense_weight: Optional[float]` and `search_mode: Optional[str] = "hybrid"`.
- `handle_search_code` accepts `dense_weight` and `mode`, returning markdown with AST signature, kind, score breakdown, and source link.
- `handle_search_docs` accepts `dense_weight` and `mode`, returning markdown with score breakdown and source link.

- [ ] **Step 1: Update `SearchRequest` schema in `app/models/schemas.py`**
- [ ] **Step 2: Update `/admin/api/search/test` in `app/api/routers/repositories.py`**
  - Pass `dense_weight` and `search_mode` to `search_service`.
  - Include `dense_score`, `sparse_score`, `search_mode`, and `dense_weight` in API response.
- [ ] **Step 3: Update MCP tool handlers in `app/mcp/handlers/search_handlers.py` & `app/mcp/tools.py`**
  - Add `dense_weight` and `mode` parameters.
  - Enrich formatted markdown output with AST signature, kind, and score breakdown.
- [ ] **Step 4: Run MCP and router unit tests**
  - Run `pytest tests/test_mcp_tools.py` and API tests.
- [ ] **Step 5: Commit Task 2 changes**

---

### Task 3: Redesign Search & Inspector Web UI

**Files:**
- Modify: `frontend/src/SearchInspector.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles/components.css`
- Test: `frontend/src/tests/SearchInspector.test.tsx`

**Interfaces:**
- Mode buttons: `Hybrid Fusion`, `Semantic (Dense)`, `Lexical (BM25)`.
- Split slider: range input $[0.0, 1.0]$ with quick preset buttons (`Balanced 50/50`, `Semantic 70/30`, `Keyword 30/70`, `Pure Semantic 100/0`, `Pure Keyword 0/100`).
- Repo dropdown loaded dynamically from `/admin/api/repos` + limit filter (`5`, `10`, `25`).
- Score chips: Hybrid %, Dense %, BM25 %.
- "Open in Navigator" button invoking navigation callback to open file at symbol lines.
- Code blocks with line numbering and copy action.

- [ ] **Step 1: Update TypeScript types in `frontend/src/types.ts`**
  - Add `dense_score`, `sparse_score`, `signature`, `ast_symbol_id` to search hit types.
- [ ] **Step 2: Update `frontend/src/SearchInspector.tsx`**
  - Implement mode toggle (`hybrid` | `semantic` | `lexical`).
  - Implement dynamic slider with presets.
  - Fetch repo list from `/admin/api/repos` for dropdown.
  - Add "Open in Navigator" bridging callback.
  - Add line numbers and copy code functionality.
- [ ] **Step 3: Wire up navigation bridge in `frontend/src/App.tsx`**
  - Pass callback or navigate state from `SearchInspector` to `CodeNavigator`.
- [ ] **Step 4: Add styles in `frontend/src/styles/components.css`**
- [ ] **Step 5: Update Vitest tests in `frontend/src/tests/SearchInspector.test.tsx`**
  - Run `npm --prefix frontend test` and ensure all suites pass.
- [ ] **Step 6: Commit Task 3 changes**

---

### Task 4: End-to-End Build, Local Verification & PR Creation

**Files:**
- Build frontend: `npm --prefix frontend run build`
- Deploy to local container and verify
- Git push and GitHub PR creation

- [ ] **Step 1: Build frontend bundle and copy to local container**
- [ ] **Step 2: Verify live local container on port 8021 and dev preview on 5173**
  - Test `/admin/api/search/test` with various `dense_weight` and `search_mode` values.
  - Verify UI renders scores, split slider, repo dropdown, and "Open in Navigator".
- [ ] **Step 3: Push branch `feat/search-inspector-hybrid-scoring` to GitHub**
- [ ] **Step 4: Open Pull Request against `main`**
- [ ] **Step 5: Monitor and confirm CI checks pass**

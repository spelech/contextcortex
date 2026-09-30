# Navigator Omni-Search & Synchronized Full-File Code Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a global Omni-Search engine that searches across AST symbols, files, and raw code text with confidence scores, paired with a floating non-shifting dropdown palette and a synchronized full-file code viewer in Pane 3.

**Architecture:** A unified backend SQLite query searches indexed symbols, files, and code chunks with confidence scoring. The frontend introduces `NavigatorOmniSearch` as an absolute floating overlay (`z-index: 50`) in the toolbar, and `NavigatorCodeViewer` in Pane 3 with syntax highlighting, 1-based line numbers, auto-scroll to target symbols, and a docked impact drawer.

**Tech Stack:** FastAPI, SQLite, React 19, TypeScript, Vitest, Playwright Layout Inspector.

## Global Constraints
- Target version: 2.16.0 (or incremented in release)
- Omni-Search dropdown must have `position: absolute; z-index: 50` and NEVER expand `NavigatorToolbar` height or shift the 3 panes.
- All backend tests must use real SQLite database fixtures (zero mock theatre).
- Line numbers in code viewer are 1-based.
- Zero layout collisions across desktop (1080p) and mobile (Samsung Galaxy S25+).

---

### Task 1: Backend Omni-Search Service & API Endpoint

**Files:**
- Modify: `app/services/navigator.py`
- Modify: `app/api/routers/navigator.py`
- Test: `tests/backend/test_navigator_router.py`

**Interfaces:**
- Produces: `get_omni_search(repo: str, query: str, limit: int = 25) -> dict`
- API Route: `GET /admin/api/navigator/omni-search?repo=...&q=...&limit=25`

- [ ] **Step 1: Write the failing backend test**
Add tests in `tests/backend/test_navigator_router.py` for `api_get_omni_search` asserting symbol matches, file matches, and code matches with scores.

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/backend/test_navigator_router.py::test_omni_search_endpoint -v`
Expected: FAIL with 404 Not Found.

- [ ] **Step 3: Implement `get_omni_search` and router endpoint**
Implement multi-layer SQLite search in `app/services/navigator.py` and mount `GET /admin/api/navigator/omni-search` in `app/api/routers/navigator.py`.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/backend/test_navigator_router.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
`git commit -m "feat(navigator): implement backend omni-search service and API endpoint"`

---

### Task 2: Frontend Types & `NavigatorOmniSearch` Floating Palette Component

**Files:**
- Modify: `frontend/src/components/navigator/types.ts`
- Create: `frontend/src/components/navigator/NavigatorOmniSearch.tsx`
- Modify: `frontend/src/styles/navigator.css`
- Test: `frontend/src/tests/NavigatorOmniSearch.test.tsx`

**Interfaces:**
- Produces: `<NavigatorOmniSearch repo={selectedRepo} onSelectResult={handleSelectResult} />`
- Overlay: `.nav-omni-dropdown` with `position: absolute; top: calc(100% + 4px); z-index: 50`.

- [ ] **Step 1: Write failing component tests**
Create `frontend/src/tests/NavigatorOmniSearch.test.tsx` testing input debounce, match list rendering, keyboard cycling, and outside dismissal.

- [ ] **Step 2: Run test to verify it fails**
Run: `npm --prefix frontend run test -- NavigatorOmniSearch.test.tsx`
Expected: FAIL with component missing.

- [ ] **Step 3: Implement `NavigatorOmniSearch` and CSS**
Implement floating overlay with type badges, confidence labels, and keyboard listeners.

- [ ] **Step 4: Run test to verify it passes**
Run: `npm --prefix frontend run test -- NavigatorOmniSearch.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**
`git commit -m "feat(navigator): add NavigatorOmniSearch floating command palette"`

---

### Task 3: Full-File Code Viewer (`NavigatorCodeViewer`) with Target Line Highlight & Impact Drawer

**Files:**
- Create: `frontend/src/components/navigator/NavigatorCodeViewer.tsx`
- Modify: `frontend/src/components/navigator/NavigatorInspector.tsx`
- Modify: `frontend/src/styles/navigator.css`
- Test: `frontend/src/tests/NavigatorCodeViewer.test.tsx`

**Interfaces:**
- Produces: `<NavigatorCodeViewer filepath={...} content={...} targetStartLine={...} targetEndLine={...} impact={...} />`

- [ ] **Step 1: Write failing unit test**
Create `frontend/src/tests/NavigatorCodeViewer.test.tsx` verifying line rendering, auto-scrolling ref, target range highlighting, and impact drawer toggle.

- [ ] **Step 2: Run test to verify it fails**
Run: `npm --prefix frontend run test -- NavigatorCodeViewer.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement `NavigatorCodeViewer`**
Implement line-numbered code viewer with target range styling and collapsible impact drawer.

- [ ] **Step 4: Run test to verify it passes**
Run: `npm --prefix frontend run test -- NavigatorCodeViewer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**
`git commit -m "feat(navigator): implement NavigatorCodeViewer with target line highlight and impact drawer"`

---

### Task 4: Integrate Omni-Search & Code Viewer in `CodeNavigator` and `NavigatorToolbar`

**Files:**
- Modify: `frontend/src/components/navigator/NavigatorToolbar.tsx`
- Modify: `frontend/src/CodeNavigator.tsx`
- Modify: `frontend/src/styles/navigator.css`
- Test: `frontend/src/tests/NavigatorInspector.test.tsx`

- [ ] **Step 1: Update `NavigatorToolbar` and `CodeNavigator` wiring**
Replace simple text input with `NavigatorOmniSearch`. Wire result click to open file, sync outline, and jump to line.

- [ ] **Step 2: Run all frontend unit tests**
Run: `npm --prefix frontend run test`
Expected: All 29+ test files pass.

- [ ] **Step 3: Commit**
`git commit -m "feat(navigator): integrate omni-search and full code viewer into CodeNavigator"`

---

### Task 5: Playwright E2E & Layout Inspector Verification

**Files:**
- Modify: `frontend/e2e/navigator.spec.ts`

- [ ] **Step 1: Add E2E tests for Omni-Search overlay and line jump**
Add test in `navigator.spec.ts` verifying overlay opens, has `position: absolute`, header height remains unchanged, and selecting match updates all 3 panes.

- [ ] **Step 2: Run Playwright layout tests**
Run: `npm --prefix frontend run test:layout`
Expected: All tests pass.

- [ ] **Step 3: Build frontend bundle & commit**
Run: `npm --prefix frontend run build`
`git add -f frontend/dist/ && git commit -m "test(navigator): verify omni-search overlay and full file viewer in layout e2e"`

---

### Task 6: Documentation, Full CI Quality Verification & PR Submission

**Files:**
- Modify: `docs/guide/user-guide/navigator.md`
- Modify: `README.md`

- [ ] **Step 1: Update user documentation**
Document Omni-Search with match scores and Full Code Viewer with line jumps.

- [ ] **Step 2: Run full verification suite**
Run `python3 scripts/verify_release.py --ci`, `pytest tests/`, `npm run docs:build`.

- [ ] **Step 3: Push branch and create Pull Request**
`git push -u origin feat/navigator-omni-search-viewer`
`gh pr create --title "feat(navigator): add omni-search floating palette and full-file code viewer" ...`

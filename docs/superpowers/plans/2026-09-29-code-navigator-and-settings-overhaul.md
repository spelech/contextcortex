# Code Navigator Hero Layout, Stable Toolbar, OpenAI Gateway, and Settings Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul the Code Navigator into an IDE/GitHub-style code-hero experience with breadcrumbs and back/forward history, lock the toolbar to a non-wrapping single row, eliminate phantom root empty folders, replace broken search spinners, introduce a UI-first OpenAI-compatible model gateway, and reorganize Settings into a clean sidebar dashboard with no emojis.

**Architecture:**
- **Backend:** Update `app/services/navigator.py` to sanitize protocol prefixes (`repo://`) and discard empty path segments when constructing repository trees. Create dedicated OpenAI-compatible gateway endpoints (`/admin/api/settings/ai-gateway`) storing URL, masked key, and model choices in SQLite `system_metadata` with one-time env seeding.
- **Frontend Navigator:** Re-architect `CodeNavigator.tsx` into a two-section view: collapsible left sidebar (~260px) switching between Files and Outline, and a primary Hero Code/Document Viewer (~75–80% width). Add a dedicated `NavigatorBreadcrumbs` component with Back/Forward history traversal. Lock `NavigatorToolbar` to a single 44px non-wrapping flex row.
- **Frontend Settings:** Redesign `Settings.tsx` into a two-pane layout with a vertical category sub-navigation sidebar (~220px) using Material/SVG icons (strictly zero emojis) and dedicated views for AI Gateway, Vector DB, Embedding Engine, Auto-Sync, Git Hosts, File Settings, and Appearance.
- **Frontend Catalog & Search:** Format Ingestion Catalog stat cards, filter pills, and tables with consistent SVG icons. Replace font-dependent spinners with standalone SVG `animate-spin` components.

**Tech Stack:**
- Backend: Python 3.11, FastAPI, SQLite 3, Pydantic 2, Pytest
- Frontend: React 19, TypeScript 5, Vite, Vitest, Testing Library, Playwright E2E

## Global Constraints
- Strictly NO emojis in navigation, buttons, titles, or settings; use clean SVG or FontAwesome/Material icons.
- Toolbar must remain a single row (`<= 48px` height) across desktop viewports (1280px, 1024px, 768px).
- Database is the sole source of truth for runtime AI Gateway settings; env vars serve only as initial seed if uninitialized.
- Selecting any file (code or document) must render its full content immediately without dead buttons or empty states.

---

### Task 1: Backend Navigator Tree Protocol Sanitization (Fix Root Empty Folder)

**Files:**
- Modify: `app/services/navigator.py:45-85`
- Test: `tests/backend/test_navigator_router.py`

**Interfaces:**
- Consumes: SQLite `indexed_files` rows with filepath formats like `mcp-router-code://path/to/file.py` or `/path/to/file.py`.
- Produces: `get_navigator_tree(repo: str) -> Dict[str, Any]` where `tree` contains only valid top-level directories and files, with no node having `name == ""` or `path.endswith(":/")`.

- [ ] **Step 1: Write failing test in `tests/backend/test_navigator_router.py`**

```python
def test_navigator_tree_has_no_empty_folder_root(client, sample_repo_with_protocol):
    """Verify get_navigator_tree strips URI schemes and never produces empty name root folders."""
    resp = client.get("/admin/api/navigator/tree?repo=mcp-router-code")
    assert resp.status_code == 200
    data = resp.json()
    assert "tree" in data
    # Root level children must not contain empty string name or URI scheme artifacts
    for node in data["tree"]:
        assert node["name"] != "", f"Found node with empty name: {node}"
        assert not node["name"].endswith(":"), f"Found raw scheme node: {node}"
        if node.get("children"):
            for child in node["children"]:
                assert child["name"] != "", f"Found child with empty name: {child}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_navigator_router.py::test_navigator_tree_has_no_empty_folder_root -v`
Expected: FAIL with assertion error (`node['name'] == ''` or scheme node).

- [ ] **Step 3: Implement path sanitization in `app/services/navigator.py`**

```python
def _sanitize_tree_path(filepath: str, repo: str) -> List[str]:
    cleaned = filepath.strip()
    # Strip protocol prefix e.g. repo:// or storage://
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1]
    elif cleaned.startswith(f"{repo}:"):
        cleaned = cleaned[len(repo) + 1:]
    cleaned = cleaned.lstrip("/")
    return [part for part in cleaned.split("/") if part.strip()]
```
Update tree construction in `get_navigator_tree` to use `_sanitize_tree_path`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_navigator_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/navigator.py tests/backend/test_navigator_router.py
git commit -m "fix(navigator): sanitize tree filepath protocols to eliminate empty root folder"
```

---

### Task 2: Backend OpenAI-Compatible Model Gateway & Settings Endpoints

**Files:**
- Modify: `app/services/database/connection.py`
- Modify: `app/api/routers/settings.py`
- Create: `tests/backend/test_ai_gateway_settings.py`

**Interfaces:**
- Produces:
  - `GET /admin/api/settings/ai-gateway` -> `{"url": str, "has_api_key": bool, "masked_api_key": str, "chat_model": str, "vision_ocr_model": str, "embedding_model": str}`
  - `POST /admin/api/settings/ai-gateway` -> updates SQLite `system_metadata` without clobbering existing API key if left empty.

- [ ] **Step 1: Write failing test in `tests/backend/test_ai_gateway_settings.py`**

```python
def test_ai_gateway_settings_lifecycle(client):
    # Initial read
    resp = client.get("/admin/api/settings/ai-gateway")
    assert resp.status_code == 200
    data = resp.json()
    assert "masked_api_key" in data
    assert "url" in data

    # Update settings
    payload = {
        "url": "http://my-litellm:4000/v1",
        "api_key": "sk-secret12345678",
        "chat_model": "gpt-4o",
        "vision_ocr_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small"
    }
    update_resp = client.post("/admin/api/settings/ai-gateway", json=payload)
    assert update_resp.status_code == 200
    updated = update_resp.json()["config"]
    assert updated["url"] == "http://my-litellm:4000/v1"
    assert updated["has_api_key"] is True
    assert updated["masked_api_key"].startswith("sk-")
    assert "12345678" not in updated["masked_api_key"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_ai_gateway_settings.py -v`
Expected: FAIL with 404 Not Found for `/admin/api/settings/ai-gateway`.

- [ ] **Step 3: Implement database metadata helpers & routes**

In `app/services/database/connection.py`:
- Implement `get_ai_gateway_config()` and `set_ai_gateway_config(...)`.
- Include initial seed logic from `LITELLM_URL` and `LITELLM_API_KEY` only when DB metadata does not exist.

In `app/api/routers/settings.py`:
- Add `GET /admin/api/settings/ai-gateway` and `POST /admin/api/settings/ai-gateway`.
- Ensure `POST /admin/api/settings/embedding` does not touch or clobber `openai_api_url` or `openai_api_key`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_ai_gateway_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/database/connection.py app/api/routers/settings.py tests/backend/test_ai_gateway_settings.py
git commit -m "feat(settings): add dedicated openai-compatible ai gateway persistence and endpoints"
```

---

### Task 3: Search & Navigator SVG Loading Spinners (Fix Broken Spinners)

**Files:**
- Modify: `frontend/src/components/navigator/NavigatorOmniSearch.tsx`
- Modify: `frontend/src/SearchInspector.tsx`
- Modify: `frontend/src/styles/navigator.css`
- Modify: `frontend/src/tests/NavigatorOmniSearch.test.tsx`
- Modify: `frontend/src/tests/SearchInspector.test.tsx`

**Interfaces:**
- Produces: Resilient SVG spinner component with CSS `animate-spin` that renders reliably across browsers without relying on external webfonts.

- [ ] **Step 1: Write failing test in `frontend/src/tests/NavigatorOmniSearch.test.tsx`**

```tsx
it('renders standalone svg spinner when searching', async () => {
  render(<NavigatorOmniSearch repo="test-repo" onSelectResult={vi.fn()} />);
  const input = screen.getByRole('textbox', { name: /omni-search/i });
  fireEvent.change(input, { target: { value: 'query' } });
  
  const spinner = await screen.findByTestId('omni-search-spinner');
  expect(spinner).toBeInTheDocument();
  expect(spinner.tagName.toLowerCase()).toBe('svg');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test -- NavigatorOmniSearch.test.tsx`
Expected: FAIL (no element with `data-testid="omni-search-spinner"` or tag is `div`).

- [ ] **Step 3: Update `NavigatorOmniSearch.tsx`, `SearchInspector.tsx`, and CSS**

Replace FontAwesome icon / div spinner with inline SVG with `data-testid="omni-search-spinner"` and `data-testid="search-inspector-spinner"`.
Add keyframes in `navigator.css` and `index.css`:
```css
@keyframes nav-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.nav-svg-spinner {
  animation: nav-spin 0.8s linear infinite;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test -- NavigatorOmniSearch.test.tsx SearchInspector.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/navigator/NavigatorOmniSearch.tsx frontend/src/SearchInspector.tsx frontend/src/styles/navigator.css frontend/src/tests/NavigatorOmniSearch.test.tsx frontend/src/tests/SearchInspector.test.tsx
git commit -m "fix(ui): replace font-dependent search spinners with robust svg animation"
```

---

### Task 4: Stable Single-Row Navigator Toolbar (Fix Height Resizing/Wrapping)

**Files:**
- Modify: `frontend/src/components/navigator/NavigatorToolbar.tsx`
- Modify: `frontend/src/styles/navigator.css`
- Modify: `frontend/src/tests/NavigatorToolbar.test.tsx`

**Interfaces:**
- Produces: Single-row toolbar (`height: 44px`, `flex-wrap: nowrap`) with compact repo selector, responsive omni-search, density selector, and refresh button.

- [ ] **Step 1: Write failing test in `frontend/src/tests/NavigatorToolbar.test.tsx`**

```tsx
it('renders as a single row toolbar container with nowrap styling class', () => {
  render(
    <NavigatorToolbar
      repos={[{ name: 'repo-1' }]}
      selectedRepo="repo-1"
      onSelectRepo={vi.fn()}
      density="balanced"
      onChangeDensity={vi.fn()}
    />
  );
  const toolbar = screen.getByTestId('navigator-toolbar');
  expect(toolbar).toHaveClass('nav-toolbar-single-row');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test -- NavigatorToolbar.test.tsx`
Expected: FAIL with class missing.

- [ ] **Step 3: Implement single-row styling and structure**

In `NavigatorToolbar.tsx`:
- Add `nav-toolbar-single-row` class.
- Structure elements with flex-shrink constraints.
In `frontend/src/styles/navigator.css`:
- Lock `.nav-toolbar` to `height: 44px; flex-wrap: nowrap; align-items: center;`.
- Set center omni-search container to `max-width: 380px; flex: 1 1 auto;`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test -- NavigatorToolbar.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/navigator/NavigatorToolbar.tsx frontend/src/styles/navigator.css frontend/src/tests/NavigatorToolbar.test.tsx
git commit -m "fix(navigator): lock toolbar to single non-wrapping row to prevent height jumping"
```

---

### Task 5: Code Navigator Layout: Code as Hero, Breadcrumbs, History, & Collapsible Sidebar

**Files:**
- Create: `frontend/src/components/navigator/NavigatorBreadcrumbs.tsx`
- Modify: `frontend/src/CodeNavigator.tsx`
- Modify: `frontend/src/components/navigator/NavigatorOutline.tsx`
- Modify: `frontend/src/styles/navigator.css`
- Create: `frontend/src/tests/NavigatorBreadcrumbs.test.tsx`
- Modify: `frontend/src/tests/CodeNavigator.test.tsx`
- Modify: `frontend/src/tests/NavigatorOutline.test.tsx`

**Interfaces:**
- `NavigatorBreadcrumbs`: `(props: { repo: string, path: string | null, symbol: string | null, onNavigatePath: (path: string) => void, canGoBack: boolean, canGoForward: boolean, onGoBack: () => void, onGoForward: () => void, onToggleSidebar: () => void, isSidebarOpen: boolean }) => JSX.Element`
- `CodeNavigator`: Renders left sidebar (Files/Outline tabs) and Hero Code Viewer (75–80%). Auto-renders Markdown for docs with zero dead buttons.

- [ ] **Step 1: Write failing test in `frontend/src/tests/NavigatorBreadcrumbs.test.tsx`**

```tsx
it('renders breadcrumb segments and fires callbacks on click', () => {
  const onNavigatePath = vi.fn();
  render(
    <NavigatorBreadcrumbs
      repo="my-repo"
      path="src/components/Button.tsx"
      symbol="Button"
      onNavigatePath={onNavigatePath}
      canGoBack={true}
      canGoForward={false}
      onGoBack={vi.fn()}
      onGoForward={vi.fn()}
      onToggleSidebar={vi.fn()}
      isSidebarOpen={true}
    />
  );
  expect(screen.getByText('my-repo')).toBeInTheDocument();
  expect(screen.getByText('src')).toBeInTheDocument();
  expect(screen.getByText('components')).toBeInTheDocument();
  expect(screen.getByText('Button.tsx')).toBeInTheDocument();
  expect(screen.getByText('Button')).toBeInTheDocument();

  fireEvent.click(screen.getByText('src'));
  expect(onNavigatePath).toHaveBeenCalledWith('src');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test -- NavigatorBreadcrumbs.test.tsx`
Expected: FAIL (component not found).

- [ ] **Step 3: Implement `NavigatorBreadcrumbs.tsx` and refactor `CodeNavigator.tsx`**

1. Build `NavigatorBreadcrumbs.tsx` with Material/SVG icons (strictly no emoji), Back/Forward history buttons, path tokens, and sidebar toggle.
2. In `CodeNavigator.tsx`:
   - Implement navigation history stack (`historyPaths`, `historyIndex`, `pushHistory`).
   - Implement left sidebar tab switching (`sidebarTab: 'files' | 'outline'`).
   - When a file is clicked, immediately fetch and display full code/document content in the Hero Viewer.
   - For Markdown/text files, outline generates section titles or document overview rather than empty dead-end card.
3. In `NavigatorOutline.tsx`:
   - Remove dead "Read Full Document" button; replace with active document outline headings or immediate full viewer indicator.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test -- NavigatorBreadcrumbs.test.tsx NavigatorOutline.test.tsx CodeNavigator.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/navigator/NavigatorBreadcrumbs.tsx frontend/src/CodeNavigator.tsx frontend/src/components/navigator/NavigatorOutline.tsx frontend/src/styles/navigator.css frontend/src/tests/NavigatorBreadcrumbs.test.tsx frontend/src/tests/CodeNavigator.test.tsx frontend/src/tests/NavigatorOutline.test.tsx
git commit -m "feat(navigator): implement code-first hero layout with breadcrumbs and history navigation"
```

---

### Task 6: Redesigned Settings Dashboard: Category Left Sidebar & UI-First AI Gateway

**Files:**
- Create: `frontend/src/components/settings/AIGatewaySettings.tsx`
- Modify: `frontend/src/Settings.tsx`
- Modify: `frontend/src/styles/settings.css`
- Create: `frontend/src/tests/AIGatewaySettings.test.tsx`
- Modify: `frontend/src/tests/Settings.test.tsx`

**Interfaces:**
- `AIGatewaySettings`: Pure UI management of OpenAI-compatible endpoints (`http://litellm:4000/v1`), masked API key with Change Key workflow, Test Connection & Discover Models button, and model selection.
- `Settings.tsx`: Sub-navigation sidebar with 7 categories (AI Gateway, Vector DB, Embedding Engine, Auto-Sync, Git Hosts, File Settings, Appearance) using clean Material/SVG icons (no emojis).

- [ ] **Step 1: Write failing test in `frontend/src/tests/AIGatewaySettings.test.tsx`**

```tsx
it('renders masked api key and exposes change key input when clicked', async () => {
  render(
    <AIGatewaySettings
      config={{
        url: 'http://litellm:4000/v1',
        has_api_key: true,
        masked_api_key: 'sk-••••••••••••3a9f',
        chat_model: 'gemini-2.5-flash',
        vision_ocr_model: 'gemini-2.5-flash',
        embedding_model: 'BAAI/bge-small-en-v1.5'
      }}
      onSave={vi.fn()}
      onTestConnection={vi.fn()}
    />
  );
  expect(screen.getByText(/sk-••••••••••••3a9f/i)).toBeInTheDocument();
  const changeBtn = screen.getByRole('button', { name: /change key/i });
  fireEvent.click(changeBtn);
  expect(screen.getByPlaceholderText(/enter new api key/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test -- AIGatewaySettings.test.tsx`
Expected: FAIL (component not found).

- [ ] **Step 3: Implement `AIGatewaySettings.tsx` and refactor `Settings.tsx`**

1. Create `AIGatewaySettings.tsx`:
   - Connection status badge with latency in ms.
   - Endpoint URL input.
   - Masked key display + "Change Key" & "Clear Key" actions.
   - "Test Connection & Discover Models" button triggering live `/admin/api/models/discover`.
   - Dropdown selectors for Chat, Vision, and Embedding models populated from discovered models + manual input toggle.
2. Refactor `Settings.tsx`:
   - Add left sidebar with category buttons:
     - `ai-gateway` (AI & Model Gateway)
     - `vector-store` (Vector Database)
     - `embedding` (Embedding Engine)
     - `auto-sync` (Auto-Sync & Webhooks)
     - `git-hosts` (Git & Host Credentials)
     - `files` (File Processing & Summaries)
     - `appearance` (Appearance & Theme)
   - Render only active section card on the right.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test -- AIGatewaySettings.test.tsx Settings.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/settings/AIGatewaySettings.tsx frontend/src/Settings.tsx frontend/src/styles/settings.css frontend/src/tests/AIGatewaySettings.test.tsx frontend/src/tests/Settings.test.tsx
git commit -m "feat(settings): redesign settings dashboard with category sidebar and ui-first ai gateway"
```

---

### Task 7: Ingestion Catalog UI Formatting Fixes

**Files:**
- Modify: `frontend/src/IngestionCatalogViewer.tsx`
- Modify: `frontend/src/styles/components.css`
- Modify: `frontend/src/tests/IngestionCatalogViewer.test.tsx`

**Interfaces:**
- Produces: Polished 4-card statistics grid with aligned SVG icons, consistent 36px filter bar, and clean monospace table chips without text clipping.

- [ ] **Step 1: Write failing test in `frontend/src/tests/IngestionCatalogViewer.test.tsx`**

```tsx
it('renders 4 distinct aligned stat cards with formatted badges and no emojis', async () => {
  render(<IngestionCatalogViewer />);
  const cards = screen.getAllByTestId('catalog-stat-card');
  expect(cards).toHaveLength(4);
  for (const card of cards) {
    expect(card.textContent).not.toMatch(/[\u{1F300}-\u{1F9FF}]/u); // zero emojis
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test -- IngestionCatalogViewer.test.tsx`
Expected: FAIL (no `data-testid="catalog-stat-card"`).

- [ ] **Step 3: Update `IngestionCatalogViewer.tsx` markup and CSS**

- Format the stat cards with `data-testid="catalog-stat-card"`.
- Clean up filter pill spacing and unify input heights to 36px.
- Use clean SVGs / Material icons.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test -- IngestionCatalogViewer.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/IngestionCatalogViewer.tsx frontend/src/styles/components.css frontend/src/tests/IngestionCatalogViewer.test.tsx
git commit -m "fix(catalog): polish ingestion catalog stat cards, filters, and table formatting"
```

---

### Task 8: End-to-End Verification & Playwright Layout Inspection

**Files:**
- Modify: `frontend/e2e/navigator.spec.ts`
- Modify: `frontend/e2e/layout-inspector.spec.ts`
- Modify: `scripts/generate_requirements.py`

**Interfaces:**
- Produces: Passing end-to-end tests validating:
  - Document viewing on `.md` file click (zero dead buttons).
  - Single-row toolbar height stability (`<= 48px`) across 1280px, 1024px, 768px.
  - Settings category sidebar switching.

- [ ] **Step 1: Write E2E assertions for document reading and single-row toolbar**

In `frontend/e2e/navigator.spec.ts`:
- Assert clicking `README.md` immediately renders markdown text in the Hero Viewer.
- Assert toolbar bounding box height is `<= 48px`.

- [ ] **Step 2: Run Playwright tests and layout inspection**

Run: `npm --prefix frontend run test:e2e`
Run: `npm --prefix frontend run inspect:layout`
Expected: All E2E and layout tests PASS.

- [ ] **Step 3: Sync requirements and verify full test baseline**

Run: `python3 scripts/generate_requirements.py`
Run: `pytest -v`
Run: `npm --prefix frontend test`
Expected: 100% PASS across all suites.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/navigator.spec.ts frontend/e2e/layout-inspector.spec.ts REQUIREMENTS.md docs/TEST_COVERAGE.md
git commit -m "test(e2e): verify code-first hero layout, toolbar height stability, and requirements sync"
```

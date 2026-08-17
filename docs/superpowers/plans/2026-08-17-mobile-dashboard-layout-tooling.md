# Mobile Dashboard Responsiveness & LLM Layout Visualization Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul the Knowledge RAG Hub dashboard for complete mobile responsiveness (<768px down to 320px) and build an automated Playwright layout inspector tool that detects element bounding box overflows/collisions and outputs interactive visual HTML reports and machine-readable JSON audits.

**Architecture:** 
1. **Frontend Mobile Architecture**: Vanilla CSS modern responsive design with glassmorphism styling, a collapsible navigation drawer (`.dashboard-nav.drawer-open`), dual-view table/card components (`.data-mobile-card` on `<768px`), and fluid auto-stacking form grids and spec rows.
2. **Layout Inspection Tooling**: Standalone Playwright script (`scripts/inspect_layout.ts`) executing DOM evaluation across multiple standard viewports (`375x667`, `390x844`, `768x1024`, `1280x800`) to compute bounding box geometry, detect horizontal viewport overflows and unplanned collisions, and generate a self-contained interactive visual HTML report (`dist/layout-report/index.html`) with bounding box canvas overlays alongside a JSON diagnostic summary (`layout-audit.json`).

**Tech Stack:** React 19, TypeScript, Vanilla CSS (Outfit & JetBrains Mono), Vitest, Playwright, Node.js.

## Global Constraints
- Pure Vanilla CSS without introducing utility frameworks (Tailwind, Bootstrap).
- Preserve existing desktop layout integrity, styling, and functionality without regressions.
- Support viewports down to 320px width (iPhone SE 1st gen) without horizontal viewport scrolling.
- All interactive touch targets must meet minimum accessibility dimensions (≥44px height).
- Clean separation of concerns with full test coverage (Vitest component tests and Playwright E2E tests).

---

### Task 1: Mobile Header, Collapsible Navigation Drawer & Base CSS Setup

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/index.css`
- Test: `frontend/src/tests/App.test.tsx`

**Interfaces:**
- Consumes: `App.tsx` tab state (`activeTab`, `setActiveTab`).
- Produces: `isMobileNavOpen` state, hamburger toggle button (`.menu-toggle-btn`), mobile drawer menu (`.dashboard-nav.drawer-open`), and responsive header status badges.

- [ ] **Step 1: Write the failing tests in `src/tests/App.test.tsx`**

```tsx
// Add test verifying hamburger toggle button renders on mobile and toggles drawer
it('toggles mobile navigation drawer and closes upon tab selection', async () => {
  render(<App />);
  const menuToggle = screen.getByRole('button', { name: /toggle navigation/i });
  expect(menuToggle).toBeInTheDocument();
  
  // Drawer should initially be closed
  const nav = screen.getByRole('navigation');
  expect(nav).not.toHaveClass('drawer-open');
  
  // Click toggle to open drawer
  fireEvent.click(menuToggle);
  expect(nav).toHaveClass('drawer-open');
  
  // Click a navigation tab to select and auto-close drawer
  const settingsTab = screen.getByRole('button', { name: /settings/i });
  fireEvent.click(settingsTab);
  expect(nav).not.toHaveClass('drawer-open');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/tests/App.test.tsx`
Expected: FAIL with "Unable to find an accessible element with role "button" and name `/toggle navigation/i`"

- [ ] **Step 3: Update `App.tsx` and `index.css` with responsive header and drawer navigation**

In `App.tsx`:
Add state `const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);`
In header, add `<button className="menu-toggle-btn" aria-label="Toggle navigation" onClick={() => setIsMobileNavOpen(!isMobileNavOpen)}><i className={`fa-solid ${isMobileNavOpen ? 'fa-xmark' : 'fa-bars'}`}></i></button>`.
In `<nav className={`dashboard-nav ${isMobileNavOpen ? 'drawer-open' : ''}`}>`, wrap tab clicks with `setActiveTab(tab); setIsMobileNavOpen(false);`.

In `index.css`:
Add responsive styles for `.menu-toggle-btn`, `.dashboard-header`, `.header-status`, `.dashboard-nav`, and `.drawer-open`:
```css
.menu-toggle-btn {
  display: none;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid var(--border-card);
  color: var(--text);
  font-size: 1.25rem;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
}

@media (max-width: 768px) {
  .menu-toggle-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .dashboard-header {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 14px;
    padding: 16px;
  }
  .header-top-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
  }
  .header-status {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 14px;
    justify-content: space-between;
    width: 100%;
    padding-top: 10px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }
  .status-item {
    align-items: flex-start;
  }
  .dashboard-nav {
    display: none;
    flex-direction: column;
    gap: 6px;
    background: var(--bg-card);
    border: 1px solid var(--border-card);
    border-radius: var(--radius);
    padding: 12px;
    backdrop-filter: blur(16px);
  }
  .dashboard-nav.drawer-open {
    display: flex;
    animation: drawer-slide-down 0.25s ease-out forwards;
  }
  .nav-tab {
    width: 100%;
    padding: 12px 16px;
    justify-content: flex-start;
  }
}

@keyframes drawer-slide-down {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- src/tests/App.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/App.tsx src/index.css src/tests/App.test.tsx
git commit -m "feat: add responsive mobile header and collapsible navigation drawer"
```

---

### Task 2: Responsive Overview, Fluid Metric Cards & System Specs

**Files:**
- Modify: `frontend/src/Overview.tsx`
- Modify: `frontend/src/index.css`
- Test: `frontend/src/tests/Overview.test.tsx`

**Interfaces:**
- Consumes: `Overview` component with `Stats` prop.
- Produces: Responsive metric cards grid (`.overview-grid`) and auto-stacking system spec list (`.specs-list`, `.spec-row`).

- [ ] **Step 1: Write test in `src/tests/Overview.test.tsx`**

```tsx
it('renders system specs with responsive word wrapping and badge elements', () => {
  render(<Overview stats={mockStats} refreshStats={vi.fn()} />);
  expect(screen.getByText('System & Embedding Specs')).toBeInTheDocument();
  expect(screen.getByText(/Dense \+ BM25 Reciprocal Rank Fusion/i)).toBeInTheDocument();
  const specRows = document.querySelectorAll('.spec-row');
  expect(specRows.length).toBeGreaterThan(0);
});
```

- [ ] **Step 2: Run test to verify baseline**

Run: `npm run test -- src/tests/Overview.test.tsx`
Expected: PASS

- [ ] **Step 3: Update `Overview.tsx` and `index.css` with responsive spec list and metric grid**

In `index.css`:
```css
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
  gap: 16px;
}

.spec-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 0.9rem;
  padding: 10px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.spec-row span:first-child {
  color: var(--text-muted);
  font-weight: 500;
  flex-shrink: 0;
}

.spec-row span:last-child,
.spec-row code {
  text-align: right;
  word-break: break-word;
  max-width: 100%;
}

@media (max-width: 576px) {
  .spec-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
  .spec-row span:last-child,
  .spec-row code {
    text-align: left;
  }
  .stat-metric {
    padding: 16px;
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- src/tests/Overview.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/Overview.tsx src/index.css src/tests/Overview.test.tsx
git commit -m "feat: make overview metric grid and system spec rows fully responsive"
```

---

### Task 3: Git Repositories Manager Mobile Cards & Fluid Modals

**Files:**
- Modify: `frontend/src/GitRepoManager.tsx`
- Modify: `frontend/src/index.css`
- Test: `frontend/src/tests/GitRepoManager.test.tsx`

**Interfaces:**
- Consumes: `Repo` list state, add repo modal form.
- Produces: Dual desktop table (`.desktop-table-view`) and mobile card list (`.mobile-card-list`) with `.data-mobile-card`, plus single-column fluid modal forms on mobile.

- [ ] **Step 1: Write test for mobile cards in `src/tests/GitRepoManager.test.tsx`**

```tsx
it('renders mobile cards for repositories with action buttons', async () => {
  render(<GitRepoManager refreshStats={vi.fn()} />);
  await screen.findByText('test-repo');
  
  // Verify mobile cards exist in DOM alongside desktop table
  const mobileCards = document.querySelectorAll('.data-mobile-card');
  expect(mobileCards.length).toBeGreaterThan(0);
  
  // Verify action buttons inside mobile cards
  const mobileSyncBtns = screen.getAllByRole('button', { name: /sync/i });
  expect(mobileSyncBtns.length).toBeGreaterThan(0);
});
```

- [ ] **Step 2: Run test to verify failure**

Run: `npm run test -- src/tests/GitRepoManager.test.tsx`
Expected: FAIL with "expected 0 to be greater than 0" for `.data-mobile-card`

- [ ] **Step 3: Update `GitRepoManager.tsx` and `index.css`**

In `GitRepoManager.tsx`:
Add `.mobile-card-list` rendering `.data-mobile-card` for mobile viewports alongside the existing desktop table.
Refactor modal form classes so 3-column auth grid stacks on mobile:
```tsx
<div className="form-row form-row-3col">
  <div className="form-group">
    <label htmlFor="repo-branch">Branch / Tag</label>
    <input type="text" id="repo-branch" placeholder="main" value={branch} onChange={e => setBranch(e.target.value)} />
  </div>
  <div className="form-group">
    <label htmlFor="repo-user">Auth User (Optional)</label>
    <input type="text" id="repo-user" placeholder="e.g. oauth2" value={authUser} onChange={e => setAuthUser(e.target.value)} />
  </div>
  <div className="form-group">
    <label htmlFor="repo-token">Auth Token (Optional)</label>
    <input type="password" id="repo-token" placeholder="Token override" value={token} onChange={e => setToken(e.target.value)} />
  </div>
</div>
```

In `index.css`:
```css
.desktop-table-view {
  display: block;
}
.mobile-card-list {
  display: none;
  flex-direction: column;
  gap: 14px;
}

.data-mobile-card {
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid var(--border-card);
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.data-mobile-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.data-mobile-card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 0.85rem;
}

.data-mobile-card-actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.data-mobile-card-actions .btn {
  flex: 1;
  justify-content: center;
}

@media (max-width: 768px) {
  .desktop-table-view {
    display: none;
  }
  .mobile-card-list {
    display: flex;
  }
  .card-header-btn {
    flex-direction: column;
    align-items: stretch;
    gap: 14px;
  }
  .form-row, .form-row-3col {
    flex-direction: column;
    display: flex !important;
    gap: 12px;
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- src/tests/GitRepoManager.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/GitRepoManager.tsx src/index.css src/tests/GitRepoManager.test.tsx
git commit -m "feat: implement responsive mobile cards and fluid forms for Git repository manager"
```

---

### Task 4: Local Paths Manager Mobile Cards & Directory Browser

**Files:**
- Modify: `frontend/src/LocalPathManager.tsx`
- Modify: `frontend/src/index.css`
- Test: `frontend/src/tests/LocalPathManager.test.tsx`

**Interfaces:**
- Consumes: Local paths state, directory browser modal state.
- Produces: Dual desktop table / mobile card view for local paths, mobile-responsive directory browser modal and breadcrumbs.

- [ ] **Step 1: Write test in `src/tests/LocalPathManager.test.tsx`**

```tsx
it('renders mobile cards for local search paths with delete button', async () => {
  render(<LocalPathManager refreshStats={vi.fn()} />);
  await screen.findByText('/containers/dev/workspace/docs');
  
  const pathCards = document.querySelectorAll('.data-mobile-card');
  expect(pathCards.length).toBeGreaterThan(0);
});
```

- [ ] **Step 2: Run test to verify failure**

Run: `npm run test -- src/tests/LocalPathManager.test.tsx`
Expected: FAIL with `.data-mobile-card` count 0

- [ ] **Step 3: Update `LocalPathManager.tsx` and `index.css`**

In `LocalPathManager.tsx`:
Add `.mobile-card-list` rendering `.data-mobile-card` containing path string (`code` with `word-break: break-all`), repository chip, type badge, recursive indicator, and delete button.
In directory browser modal, ensure breadcrumbs and path list wrap cleanly.

In `index.css`:
```css
.path-input-row {
  display: flex;
  gap: 8px;
}

@media (max-width: 576px) {
  .path-input-row {
    flex-direction: column;
  }
  .browser-breadcrumbs {
    word-break: break-all;
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- src/tests/LocalPathManager.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/LocalPathManager.tsx src/index.css src/tests/LocalPathManager.test.tsx
git commit -m "feat: add mobile cards and responsive directory browser to local path manager"
```

---

### Task 5: Mobile Search Inspector, Settings & Diagnostics Viewer

**Files:**
- Modify: `frontend/src/SearchInspector.tsx`
- Modify: `frontend/src/Settings.tsx`
- Modify: `frontend/src/DiagnosticsViewer.tsx`
- Modify: `frontend/src/index.css`
- Test: `frontend/src/tests/SearchInspector.test.tsx`, `frontend/src/tests/Settings.test.tsx`, `frontend/src/tests/DiagnosticsViewer.test.tsx`

**Interfaces:**
- Consumes: Search test forms, vector store backend configs, global tokens, diagnostics log stream.
- Produces: Fully responsive Search Inspector query bar and hit cards, single-column Settings panels, and fluid Diagnostics toolbar and log viewer.

- [ ] **Step 1: Write tests for responsive layouts in Search, Settings, Diagnostics**

In `src/tests/SearchInspector.test.tsx`:
Verify search form and hit card headers render responsive container classes.
In `src/tests/Settings.test.tsx`:
Verify vector store box specs and host credential cards render cleanly.
In `src/tests/DiagnosticsViewer.test.tsx`:
Verify log search input and toolbar wrap without overflowing.

- [ ] **Step 2: Run tests to verify baseline**

Run: `npm run test -- src/tests/SearchInspector.test.tsx src/tests/Settings.test.tsx src/tests/DiagnosticsViewer.test.tsx`
Expected: PASS

- [ ] **Step 3: Update `SearchInspector.tsx`, `Settings.tsx`, `DiagnosticsViewer.tsx`, and `index.css`**

In `SearchInspector.tsx`:
- Refactor search query form to use responsive CSS classes.
- Search hit cards: update `.search-hit-header` to wrap metadata elements (`display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px;`).
- Search hit code: ensure `white-space: pre-wrap; word-break: break-all; overflow-x: auto;`.

In `Settings.tsx`:
- Update `.vs-config-layout` to stack vertically on `< 960px`.
- Update provider token boxes to stack gracefully on `< 768px` with masked token wrapping.
- Add mobile cards for host credentials list.

In `DiagnosticsViewer.tsx`:
- Update `.log-toolbar` and `.log-search-wrapper` to have `min-width: 0; width: 100%;`.
- Update `.log-filter-pills` to allow smooth wrapping or touch scrolling.
- Ensure log timestamps and logger names wrap cleanly above the message.

In `index.css`:
```css
@media (max-width: 768px) {
  .search-hit-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .log-viewer-header {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .log-viewer-actions {
    justify-content: space-between;
    width: 100%;
  }
  .log-toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .log-search-wrapper {
    min-width: 0;
    max-width: 100%;
    width: 100%;
  }
  .log-entry-main {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test`
Expected: All 8 test suites pass (53+ tests)

- [ ] **Step 5: Commit changes**

```bash
git add src/SearchInspector.tsx src/Settings.tsx src/DiagnosticsViewer.tsx src/index.css src/tests/
git commit -m "feat: complete mobile responsiveness across search inspector, settings, and diagnostics viewer"
```

---

### Task 6: Playwright Multi-Viewport E2E Tests

**Files:**
- Modify: `frontend/playwright.config.ts`
- Modify: `frontend/e2e/dashboard.spec.ts`

**Interfaces:**
- Consumes: Playwright configuration and test specs.
- Produces: Automated E2E verification across Desktop (`Desktop Chrome`) and Mobile (`Pixel 5` / `Mobile Chrome`).

- [ ] **Step 1: Update `playwright.config.ts` with mobile device project**

In `frontend/playwright.config.ts`:
```ts
projects: [
  {
    name: 'chromium',
    use: { ...devices['Desktop Chrome'] },
  },
  {
    name: 'mobile-chrome',
    use: { ...devices['Pixel 5'] },
  }
]
```

- [ ] **Step 2: Add mobile E2E test cases to `e2e/dashboard.spec.ts`**

Add tests for:
- Hamburger button opening drawer and navigating between tabs on mobile.
- Mobile card rendering and interaction in Git Repos and Local Paths.
- Modal opening and form submission on mobile viewports.

- [ ] **Step 3: Run Playwright tests**

Run: `npm run test:e2e`
Expected: All desktop and mobile tests pass.

- [ ] **Step 4: Commit changes**

```bash
git add playwright.config.ts e2e/dashboard.spec.ts
git commit -m "test: add mobile-chrome e2e test project and mobile interaction specs"
```

---

### Task 7: LLM Layout Visualization & Bounding-Box Detection Script

**Files:**
- Create: `frontend/scripts/inspect_layout.ts`
- Create: `frontend/scripts/report_template.html`
- Modify: `frontend/package.json`

**Interfaces:**
- Consumes: Running dev/preview server or headless mock server.
- Produces: `dist/layout-report/layout-audit.json` (machine/LLM-readable) and `dist/layout-report/index.html` (interactive visual bounding-box inspector).

- [ ] **Step 1: Create layout analysis algorithm in `scripts/inspect_layout.ts`**

```ts
// scripts/inspect_layout.ts
// Headless Playwright script that navigates all tabs across viewports:
// 1) Evaluates DOM bounding boxes:
//    - Viewport overflows: rect.right > viewport.width + 0.5
//    - Container scroll clipping: scrollWidth > clientWidth + 1
//    - Element collisions: pairwise non-contained 2D rectangle intersections
// 2) Takes high-DPI screenshots
// 3) Emits dist/layout-report/layout-audit.json
// 4) Compiles dist/layout-report/index.html with interactive SVG bounding-box overlays
```

- [ ] **Step 2: Create interactive HTML report template in `scripts/report_template.html`**

Create a self-contained HTML page featuring:
- Viewport switcher (375x667, 390x844, 768x1024, 1280x800).
- Tab switcher (Overview, Git Repos, Local Paths, Search, Settings, Diagnostics).
- High-res screenshot display with SVG bounding-box toggle (🟩 clean elements, 🟥 overflow errors, 🟨 collision warnings).
- Interactive sidebar list: hovering highlights element on screenshot and displays CSS selector, coordinates, and pixel delta.
- "Copy LLM Context Summary" markdown button.

- [ ] **Step 3: Add `inspect:layout` script to `package.json`**

In `frontend/package.json`:
`"inspect:layout": "npx playwright test e2e/layout-inspector.spec.ts || npx tsx scripts/inspect_layout.ts"` (or direct Playwright script runner).

- [ ] **Step 4: Run layout inspection script and verify outputs**

Run: `npm run inspect:layout` (or equivalent execution)
Expected: Successfully generates `dist/layout-report/layout-audit.json` and `dist/layout-report/index.html`.

- [ ] **Step 5: Commit changes**

```bash
git add scripts/ package.json
git commit -m "feat: add automated layout bounding-box inspection engine and visual HTML reporter"
```

---

### Task 8: Full Verification, Layout Audit Execution & Walkthrough

**Files:**
- Update: Test results and documentation

- [ ] **Step 1: Run complete automated test suite**
Run `npm run test` (Vitest unit tests) and `npm run test:e2e` (Playwright tests).

- [ ] **Step 2: Run layout inspector tool across all viewports**
Run `npm run inspect:layout` and inspect `dist/layout-report/layout-audit.json` to verify 0 critical overflow violations.

- [ ] **Step 3: Run production build**
Run `npm run build` to verify TypeScript compile and Vite bundling succeed cleanly.

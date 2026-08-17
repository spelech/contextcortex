# Mobile Dashboard Responsiveness & LLM Layout Visualization Tooling Design

**Date**: 2026-08-17  
**Status**: Approved  
**Topic**: Mobile Responsive UI Overhaul & Automated Bounding-Box Layout Inspection Tooling

---

## 1. Overview & Objectives

While the desktop version of Knowledge RAG Hub is functional and visually polished, mobile viewports (< 768px down to 320px) suffer from severe text clipping, horizontal overflows, misaligned status bars, cramped data tables, and rigid multi-column form layouts.

This project delivers:
1. **Phase 1: Full Mobile Responsive Dashboard Overhaul**: Modernize layout architecture across all 6 tabs (`Overview`, `Git Repositories`, `Local Paths`, `Search & Inspector`, `Settings`, `Diagnostics & Logs`), introducing a mobile navigation drawer, responsive card layouts for data-dense tables, fluid forms/modals, and robust text-wrapping architecture.
2. **Phase 2: LLM Visual Layout & Bounding-Box Detection Tooling**: Build an automated Playwright inspection engine that scans the dashboard across multiple viewports (`375x667`, `390x844`, `768x1024`, `1280x800`), evaluates bounding boxes to detect viewport overflows, container clipping, and element collisions, and outputs both machine-readable JSON audits and a self-contained Interactive Visual HTML Inspector report.

---

## 2. Phase 1: Mobile Responsive Dashboard Architecture

### 2.1 Header & Navigation Drawer (`App.tsx`, `index.css`)
* **Breakpoints**: Desktop (`≥ 768px`), Mobile (`< 768px`), Small Mobile (`< 480px`).
* **Header Layout**:
  * Brand title, logo icon, and version badge aligned horizontally.
  * Status items (`Engine State`, `Vector Backend`, `Collection`) organized into a responsive flex-wrap badge row with clear label/value hierarchy.
  * On mobile (`< 768px`), a hamburger menu button (`fa-solid fa-bars` / `fa-solid fa-xmark`) toggles the navigation menu.
* **Navigation Drawer**:
  * Mobile navigation transforms from horizontal tabs into a slide-down glassmorphism menu (`.dashboard-nav.drawer-open`).
  * Tapping any tab selects the view and automatically collapses the drawer.
  * Touch targets are optimized to ≥44px height for touch accessibility.

### 2.2 Overview & System Specifications (`Overview.tsx`, `index.css`)
* **Metric Grid (`.overview-grid`)**:
  * Uses `grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr))` to avoid fixed-width overflow on 320px–375px screens.
* **System Specs (`.specs-list`, `.spec-row`)**:
  * On viewports `< 576px`, rows adapt to stacked vertical orientation (`flex-direction: column; align-items: flex-start; gap: 4px;`).
  * Long strings (e.g. `Dense + BM25 Reciprocal Rank Fusion (RRF)`, embedding models, collection IDs) wrap cleanly using `word-break: break-word` and proper badge margins.

### 2.3 Data-Dense Tables: Git Repositories & Local Paths (`GitRepoManager.tsx`, `LocalPathManager.tsx`)
* **Dual Display Strategy**:
  * **Desktop (`≥ 768px`)**: Standard desktop `<table>` view.
  * **Mobile (`< 768px`)**: Render `.mobile-card-list` containing `.data-mobile-card` items.
* **Git Repository Mobile Cards**:
  * Header: Git provider icon + Repo Alias + Status badge (`Synced`, `Syncing`, `Error`).
  * Body: Clickable Git URL with ellipsis and copy/open button, branch and commit SHA chips, file count, and last-synced timestamp.
  * Actions: Full-width touch buttons for `Sync` and `Delete`.
* **Local Paths Mobile Cards**:
  * Path code display with `word-break: break-all`.
  * Metadata chips for Repo Alias, Type (`Directory`/`File`), Recursive flag, and Category.
  * Delete button in bottom action bar.
* **Modals & Directory Browser**:
  * Modal cards (`.modal-card`) adjust to fluid width (`width: 95%; max-width: 500px; margin: 16px auto`).
  * Forms (`.form-row`, `.path-input-row`) stack single-column on mobile with full-width input controls.
  * Directory browser breadcrumb and file list adapt to mobile screen height with scroll constraints.

### 2.4 Search Inspector, Settings & Diagnostics (`SearchInspector.tsx`, `Settings.tsx`, `DiagnosticsViewer.tsx`)
* **Search Inspector**:
  * Search query, type selector, and repo filter stack into full-width mobile form fields.
  * Search hit cards display metadata (repo badge, file path, line numbers, RRF score) in wrapping header flex rows.
* **Settings**:
  * Vector Database Engine panel stacks into single-column layout on mobile.
  * Global Git provider auth boxes adapt to 1-column grids on `< 768px` with masked token wrapping.
  * Stored host credentials display as responsive cards on mobile.
* **Diagnostics & Server Logs**:
  * Filter pills scroll or wrap gracefully.
  * Log search bar expands fluidly (`width: 100%; min-width: 0`).
  * Log entries wrap timestamps and logger names above log messages without pushing text off-screen.
  * Traceback viewports maintain bounded scrolling without horizontal page stretching.

---

## 3. Phase 2: LLM Layout Visualization & Bounding-Box Detection Tooling

### 3.1 Architecture & Runner (`scripts/inspect_layout.ts`)
* **Engine**: Headless Playwright Chromium test/inspection script.
* **Command**: `npm run inspect:layout` (or `npx tsx scripts/inspect_layout.ts`).
* **Target Viewports**:
  * `mobile-small`: 375 × 667 (iPhone SE)
  * `mobile-standard`: 390 × 844 (iPhone 14 / modern Android)
  * `tablet`: 768 × 1024 (iPad Mini)
  * `desktop`: 1280 × 800 (Desktop reference)
* **Target States**: All 6 tabs (`overview`, `git-repos`, `local-paths`, `search-inspector`, `settings`, `diagnostics`) and interactive modal dialogs.

### 3.2 Violation Detection Algorithms
1. **Horizontal Viewport Overflow**:
   * Evaluates `rect.right > viewport.width + 0.5` or `rect.left < -0.5`.
   * Computes exact overflow delta in pixels: `overflowPixels = rect.right - viewport.width`.
2. **Container Scroll Clipping**:
   * Evaluates `element.scrollWidth > element.clientWidth + 1` for content containers, excluding designated scrollable elements.
3. **Bounding Box Collisions**:
   * Checks pairwise 2D bounding box intersections between distinct leaf elements:
     $$\text{Intersection} = (\max(0, \min(x_{A2}, x_{B2}) - \max(x_{A1}, x_{B1}))) \times (\max(0, \min(y_{A2}, y_{B2}) - \max(y_{A1}, y_{B1})))$$
   * Filters out valid parent-child containers and modal backdrops.

### 3.3 Generated Inspection Artifacts
* **`dist/layout-report/layout-audit.json`**:
  * Structured JSON schema documenting viewports, tabs, violation categories (`VIEWPORT_OVERFLOW`, `CONTAINER_CLIPPING`, `ELEMENT_COLLISION`), element selectors, bounding box `{ x, y, width, height }`, and pixel deltas.
* **`dist/layout-report/index.html` (Interactive Visual HTML Inspector)**:
  * Self-contained HTML report with embedded high-DPI screenshots.
  * Interactive SVG bounding box overlays (Green = In bounds, Red = Overflow violation, Amber = Collision).
  * Interactive violation explorer with sidebar hover-to-highlight functionality.
  * "Copy LLM Context Summary" button for one-click markdown prompt generation.

---

## 4. Verification & Testing Strategy

1. **Unit & Component Tests**:
   * Run Vitest suite (`npm run test`) to verify all tab state management, modal handling, drawer toggles, and responsive card rendering.
2. **Playwright End-to-End Tests**:
   * Run Playwright suite (`npm run test:e2e`) across Desktop and Mobile viewports (using Playwright mobile device descriptors `Pixel 5` / `iPhone 12`).
3. **Layout Inspection Script Validation**:
   * Execute `npm run inspect:layout` and verify that `dist/layout-report/layout-audit.json` and `dist/layout-report/index.html` are generated with 0 critical overflow violations on mobile viewports.
4. **Manual Visual Verification**:
   * Validate mobile drawer navigation, responsive cards, modals, search inspector, settings, and diagnostics logs in browser.

# Sub-Navigation Bar & UI Workflow Redesign Spec

**Date:** 2026-09-30  
**Status:** Approved  
**Topic:** Separate Top Header and Dedicated Sub-Navigation Bar with Rapid Vite Dev Workflow  

---

## 1. Problem Statement & Motivation
In an earlier iteration, all 9 navigation tabs, the brand logo, and 3 status badges were compressed into a single 48px header row. This forced navigation tabs down to `0.73rem` (~11px) with abbreviated labels (e.g. "Repos", "Paths", "Logs"), making the interface hard to read and visually cramped. Additionally, iterating via Docker image builds was unnecessarily slow for pure UI development.

## 2. Goals & Constraints
- **Readability**: Restore standard, comfortable tab typography (`0.875rem` / 14px) and full descriptive labels.
- **Clean Structure**: Separate the top brand/system header from the application tab navigation.
- **Fast Development Loop**: Use the local Vite dev server (`http://localhost:5173`) proxying to the running backend on port 8021 for rapid, instant UI iteration.
- **Responsiveness**: Maintain smooth horizontal scrolling on tablet/narrow viewports and a collapsible mobile drawer for phones without layout overflow violations.

---

## 3. Component & Layout Architecture

### A. Top Header Bar (`.dashboard-header`)
- **Brand & Logo (Left)**: Icon, ContextCortex title, and version tag (`v2.16.0`).
- **System Status (Right)**:
  - Engine State (`Idle` / `Syncing...`)
  - Vector Backend (`Qdrant (Remote) Healthy`)
  - Collection Name (`notes_rag`)
  - Full labels restored for maximum legibility.
- **Mobile Menu Toggle**: Visible only on mobile/narrow screens to toggle the navigation drawer.

### B. Dedicated Sub-Navigation Bar (`.dashboard-nav`)
- **Placement**: Directly below the main header in its own card/bar container.
- **Tabs**:
  1. `Overview` (`fa-chart-pie`)
  2. `Navigator` (`fa-code-fork`)
  3. `Git Repositories` (`fa-github`)
  4. `Local Paths` (`fa-folder-tree`)
  5. `Local Storage` (`fa-hard-drive`)
  6. `Ingestion Catalog` (`fa-book-bookmark`)
  7. `Search & Inspector` (`fa-magnifying-glass`)
  8. `Settings` (`fa-gear`)
  9. `Diagnostics & Logs` (`fa-terminal`)
- **Sizing & Styling**:
  - `font-size: 0.875rem; font-weight: 500;`
  - `padding: 8px 14px; min-height: 38px; gap: 8px;`
  - Fully removed `.tab-short` label truncation hacks.
  - Active tab highlighted with accent background and border.
  - `overflow-x: auto; scrollbar-width: none;` for smooth touch/wheel panning on mid-sized viewports.

---

## 4. Development & Verification Strategy
1. **Live UI Iteration**: Start Vite dev server in the background:
   ```bash
   npm --prefix frontend run dev -- --host 0.0.0.0 --port 5173
   ```
2. **Automated Verification**:
   - Vitest unit tests: `npm --prefix frontend test -- --run`
   - Playwright E2E & Layout Inspector: `npm --prefix frontend run inspect:layout` & `npx playwright test`
   - Production bundle build: `npm --prefix frontend run build`

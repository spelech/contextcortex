# Specification: Navigator Omni-Search & Synchronized Full-File Code Viewer

**Date:** 2026-09-29  
**Status:** Approved  
**Target Version:** 2.17.0  
**Initiative:** ContextCortex Codebase Navigator Enhancement  

---

## 1. Executive Summary
The Codebase Navigator currently operates with siloed, in-memory filters (tree path filter in Pane 1 and active-file symbol filter in Pane 2) and isolates file inspection to single-symbol snippets. 

This specification introduces:
1. **Unified Omni-Search Engine**: A global search endpoint and UI that searches across Files, AST Symbols, and Raw Code text in parallel with match-type badges and confidence scoring.
2. **Floating Absolute Overlay (`position: absolute; z-index: 50`)**: A non-disruptive command palette dropdown that overlays the 3-pane layout without expanding headers or causing layout shifts.
3. **Synchronized Full-File Code Viewer**: A full source viewer in Pane 3 with language syntax highlighting, 1-based line numbers, auto-scrolling to target line ranges, and a docked "Symbol Intelligence & Impact" drawer for callers and callees.

---

## 2. Architecture & Data Contracts

### 2.1 Backend API Endpoint
- **Route:** `GET /admin/api/navigator/omni-search`
- **Parameters:**
  - `repo` (`str`, required): Target repository or `"__all__"`
  - `q` (`str`, required): Search query string
  - `limit` (`int`, optional, default `25`): Maximum matches to return

#### Response Schema:
```json
{
  "query": "api_read_file",
  "repo": "__all__",
  "total_matches": 3,
  "execution_ms": 8.4,
  "matches": [
    {
      "id": "sym_42",
      "type": "symbol",
      "name": "api_read_file",
      "kind": "function",
      "filepath": "app/api/routers/files.py",
      "repo": "contextcortex",
      "start_line": 22,
      "end_line": 49,
      "score": 0.99,
      "score_label": "99% AST exact match",
      "preview": "async def api_read_file(path: str = Query(...), repo: Optional[str] = None...)"
    },
    {
      "id": "code_108",
      "type": "code",
      "name": "res = await api_read_file(path=target_path)",
      "kind": "code_chunk",
      "filepath": "app/mcp/handlers/file_handlers.py",
      "repo": "contextcortex",
      "start_line": 45,
      "end_line": 46,
      "score": 0.88,
      "score_label": "88% Substring match",
      "preview": "res = await api_read_file(path=target_path)"
    },
    {
      "id": "file_12",
      "type": "file",
      "name": "files.py",
      "kind": "file",
      "filepath": "app/api/routers/files.py",
      "repo": "contextcortex",
      "start_line": 1,
      "end_line": 83,
      "score": 0.92,
      "score_label": "92% Filename match",
      "preview": "app/api/routers/files.py (83 lines)"
    }
  ]
}
```

### 2.2 Matching Engine Logic (SQLite)
The service executes three queries against the local SQLite store:
1. **AST Symbols**:
   - `SELECT id, name, kind, filepath, start_line, end_line, repo FROM symbols WHERE repo = ? AND name LIKE ? LIMIT ?`
   - Exact case-insensitive match = score `0.99`, prefix match = `0.92`, substring = `0.85`.
2. **File Paths**:
   - Matches filename or directory paths from indexed files table.
   - Exact basename match = score `0.95`, path match = `0.85`.
3. **Full-Text / Code Chunks**:
   - Queries `code_chunks` / `file_summaries` using SQLite `LIKE` or FTS.
   - Scores normalized between `0.70` and `0.88`.
4. Merges and sorts results by `score DESC`, sliced to `limit`.

---

## 3. Frontend Component Design

### 3.1 `NavigatorOmniSearch` (Floating Palette)
- **Placement:** Integrated directly into `NavigatorToolbar`.
- **Overlay Positioning:**
  ```css
  .nav-omni-dropdown {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    right: 0;
    z-index: 50;
    max-height: 420px;
    overflow-y: auto;
    background: var(--bg-card, #0f172a);
    border: 1px solid var(--border-color, #334155);
    border-radius: 8px;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
  }
  ```
  - **Constraint:** Must NEVER change the layout height of `NavigatorToolbar` or cause layout shifts on the 3 panes below.
- **Interactions:**
  - `ArrowDown` / `ArrowUp` to cycle through matches.
  - `Enter` to select highlighted match.
  - `Escape` or clicking outside dismisses the dropdown.
  - Type badges (`SYMBOL` in blue, `CODE` in purple, `DOCS` in amber, `FILE` in teal).
  - Confidence pills with descriptive match rationale.

### 3.2 Synchronized 3-Pane Navigation on Selection
When a match is selected:
1. **Pane 1 (File Tree)**:
   - Expands parent directories and highlights the target file node.
2. **Pane 2 (Outline)**:
   - Loads the file's AST symbols and sets the selected symbol chip.
3. **Pane 3 (Full Code Viewer)**:
   - Loads complete file text via `GET /admin/api/files/read`.
   - Scrolls smoothly to `start_line` with line range highlight styling.
   - Displays header bar: file path, line count, copy permalink button, and "Callers & Impact" toggle button.

### 3.3 Pane 3 Symbol Intelligence Drawer
- A toggle button in the Pane 3 header: `"Callers & Callees (N)"`.
- When clicked, a docked drawer slides in at the bottom (or side) displaying incoming callers, outgoing callees, and route specifications without displacing the main code viewing area.

---

## 4. Error Handling & Edge Cases
1. **Empty Query / No Results:**
   - Clearing search closes the overlay immediately.
   - Zero matches displays a clean empty state: *"No matching files, symbols, or code found for '{query}'"*.
2. **Network / Debouncing:**
   - Input debounced by 150ms.
   - In-flight requests cancelled via `AbortController` on new keystrokes.
3. **Large File Protection:**
   - For files $> 1\text{MB}$ or $> 10,000$ lines, renders line pagination with a notice, preventing DOM lockup.

---

## 5. Verification & Testing Strategy (Anti-Theatre)

### 5.1 Backend Verification (`pytest tests/backend/test_navigator_router.py`)
- Test `GET /admin/api/navigator/omni-search` with real SQLite database populated with multiple files, AST symbols, and code chunks.
- Assert exact symbol matches return `type: "symbol"` and score $\ge 0.95$.
- Assert substring code matches return `type: "code"` and line ranges.
- Assert filename matches return `type: "file"`.
- Assert empty results return 200 with `matches: []`.

### 5.2 Frontend Component Tests (`vitest frontend/src/tests/`)
- `NavigatorOmniSearch.test.tsx`:
  - Renders input with placeholder.
  - Fires debounced query on typing.
  - Renders match cards with type badges and confidence scores.
  - Navigates items with `ArrowDown`/`ArrowUp` and triggers selection callback on `Enter` / click.
  - Closes on `Escape` and outside click.
- `NavigatorCodeViewer.test.tsx`:
  - Renders line numbers 1 to N.
  - Highlights specified line range (`targetStartLine` to `targetEndLine`).
  - Toggles callers/callees impact drawer.

### 5.3 Playwright Layout & E2E Tests (`frontend/e2e/navigator.spec.ts`)
- Use `layout-inspector` to assert `NavigatorToolbar` height remains static when the omni-search overlay opens.
- Assert overlay has `position: absolute` and does not intersect or push Pane 1, Pane 2, or Pane 3.
- Assert selecting a match navigates and highlights target lines across desktop (1080p) and mobile (Samsung Galaxy S25+).

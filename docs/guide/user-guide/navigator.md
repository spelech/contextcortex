# 3-Pane Codebase Navigator

The **Codebase Navigator** provides high-performance exploration of project directory structures, Tree-sitter AST declarations, API endpoints, and caller/callee code relationships.

---

![Codebase Navigator](/assets/desktop_codebase-navigator.png)

## The Three Synchronized Panes

The Codebase Navigator organizes project structure into three synchronized interactive panes:

### Pane 1: Files & Modules Tree
- Browse directory hierarchies and file trees with instant search filtering.
- Displays AST symbol badges and REST route counts next to each file.
- Filter by file extension or path fragment using the quick search bar.
- Selecting any file automatically populates Panes 2 and 3.

### Pane 2: Symbols & Routes Outline
- Lists all declared functions, classes, interfaces, and API routes extracted by Tree-sitter.
- Filter symbols with quick category chips:
  - **All Symbols**
  - **Functions** (`def`, `function`, `fn`)
  - **Classes & Structs** (`class`, `struct`, `interface`)
  - **API Routes** (`@app.get`, `app.post`, etc.)
- View parameter signatures, return types, and starting/ending line ranges.

### Universal Omni-Search
- **Global Command Palette**: Search across AST symbols, files, API routes, and raw code text in real time from the center toolbar.
- **Match Types & Confidence Scoring**:
  - `[symbol]` – High confidence AST matches (e.g., `99% AST exact match`, `94% AST prefix match`).
  - `[file]` – File path and module matches (`92% filename match`).
  - `[route]` – REST endpoint paths (`95% route match`).
  - `[code]` – Raw source code substring occurrences (`88% code match`).
- **Keyboard Navigation**: Navigate results with <kbd>&uarr;</kbd> and <kbd>&darr;</kbd>, press <kbd>Enter</kbd> to jump, or <kbd>Esc</kbd> to dismiss.
- **Zero-Shift Floating Overlay**: Floats smoothly over the 3 panes without shifting header layout or altering pane heights.

### Pane 3: Code Intelligence & Full Source Viewer (or Document Reader)
- **Symbol Intelligence Mode**:
  - **Callers & Callees**: Inspect incoming callers and outgoing references identified by AST cross-file analysis.
  - **Click-Through Navigation**: Click any caller or callee chip to jump directly to its declaration in Pane 1 and Pane 2.
  - **HTTP Route Specifications**: View endpoint paths, HTTP verbs, and request/response models.
  - **Syntax Preview**: Read formatted implementation code blocks with line numbers and syntax highlighting.
- **Full Source Code Viewer**:
  - Automatically loads full file contents with line numbering.
  - **Target Line Highlighting**: Seamlessly scrolls to and highlights target line ranges (`targetStartLine` / `targetEndLine`) when jumping from Omni-Search or symbols outline.
  - **Docked Symbol Impact Drawer**: Collapsible bottom drawer showing caller and callee counts with instant click-to-jump.
  - **Copy Code & Link**: One-click actions to copy clean source code or deep links to specific lines.
- **Full Document & Markdown Reader Mode**:
  - Automatically activates when selecting non-code files (`.md`, `.markdown`, `.txt`, `.json`, etc.) or clicking **Read Full Document** from Pane 2.
  - **Rendered View**: Safe Markdown parser supporting formatted headings, lists, blockquotes, inline code, and fenced code blocks.
  - **Raw Source View**: Full file content display with line-by-line numbering.
  - **One-Click Copy**: Copy complete document contents to clipboard with instant visual confirmation.

---

## Layout Density & Mobile Responsiveness

- **Density Options**: Customize visual density using the header selector:
  - **Compact**: Tight row spacing and minimal margins designed for high-density multi-file refactoring on laptops and widescreen monitors.
  - **Balanced** *(Default)*: Optimal spacing and font sizing for general architectural review.
  - **Spacious**: Card-based presentation with generous padding and expanded docstring summaries.
- **Responsive Stacking**: On mobile and narrow viewports ($<900\text{px}$), the 3 panes seamlessly stack vertically with word-wrapping and container safeguards, guaranteeing zero horizontal overflow and zero element collisions.

---

## Next Steps

- Test vector and keyword retrieval queries in [Search & Inspector](/guide/user-guide/search).
- Register and synchronize remote repositories in [Git Repositories Management](/guide/user-guide/git-repositories).

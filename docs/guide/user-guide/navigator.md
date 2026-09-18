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

### Pane 3: Code Intelligence & Impact Analysis
- **Callers & Callees**: Inspect incoming callers and outgoing references identified by AST cross-file analysis.
- **Click-Through Navigation**: Click any caller or callee chip to jump directly to its declaration in Pane 1 and Pane 2.
- **HTTP Route Specifications**: View endpoint paths, HTTP verbs, and request/response models.
- **Syntax Preview**: Read formatted implementation code blocks with line numbers and syntax highlighting.

---

## Layout Density Options

Customize the visual density of the three panes using the density selector in the top-right header:

- **Compact**: Tight row spacing and minimal margins designed for high-density multi-file refactoring on laptops and widescreen monitors.
- **Balanced** *(Default)*: Optimal spacing and font sizing for general architectural review.
- **Spacious**: Card-based presentation with generous padding and expanded docstring summaries.

---

## Next Steps

- Test vector and keyword retrieval queries in [Search & Inspector](/guide/user-guide/search).
- Register and synchronize remote repositories in [Git Repositories Management](/guide/user-guide/git-repositories).

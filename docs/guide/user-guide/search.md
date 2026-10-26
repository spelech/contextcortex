# Search and Inspector

The **Search and Inspector** view lets administrators and AI engineers test hybrid semantic and lexical search queries interactively, calibrate dense-to-sparse scoring weights, inspect decomposed score chips and AST signatures, and jump directly to matched symbols in the Codebase Navigator.

---

![Search and Inspector](/assets/desktop_search-inspector.png)

## Executing & Calibrating a Search Query

Follow these steps to run and tune a retrieval test:

1. Click the **Search & Inspector** tab in the main navigation.
2. Enter your query in the search bar (for example: `vector database connection pool` or `FastMCP tool registration`).
3. Select the target search category:
   - **Code**: Searches source code AST chunks across all indexed languages and enriches matches with AST signatures and symbol metadata.
   - **Docs**: Searches architectural documents, ADR records, specifications, executive file summaries, and indexed PDF manuals.
4. Select the **Search Mode**:
   - **Hybrid Fusion** *(Default)*: Combines dense semantic vector similarity (`BGE-Small`) and sparse lexical keyword matching (`BM25`).
   - **Semantic (Dense)**: Queries dense vector embeddings only (`dense_weight = 1.0`).
   - **Lexical (BM25)**: Queries sparse keyword embeddings only (`dense_weight = 0.0`).
5. *(In Hybrid Fusion mode)* Adjust the **Hybrid Split Calibration**:
   - Drag the interactive slider between `0.0` (100% Lexical) and `1.0` (100% Semantic), or click a quick preset chip:
     - **Balanced (50/50)** — `dense_weight = 0.5`
     - **Semantic Bias (70/30)** — `dense_weight = 0.7`
     - **Lexical Bias (30/70)** — `dense_weight = 0.3`
6. *(Optional)* Select a **Repository** from the populated dropdown (`All Repositories` or a specific indexed repo) and choose a **Result Limit** (`5`, `10`, or `25`).
7. Click **Run Search** or press <kbd>Enter</kbd>.

---

## Interpreting Search Results & Score Decomposition

Each result card displays comprehensive AST metadata, decomposed relevance scores, and quick actions:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ [contextcortex] app/services/database/connection.py (Lines 12-45)            │
│ [function] get_db_connection()                                               │
│ Hybrid: 88.4%   Dense: 91.2%   BM25: 85.6%         [Open in Navigator] [Git] │
├──────────────────────────────────────────────────────────────────────────────┤
│ Signature: def get_db_connection(db_url: Optional[str] = None) -> Connection │
├──────────────────────────────────────────────────────────────────────────────┤
│ 12 │ def get_db_connection(db_url: Optional[str] = None) -> Connection:      │
│ 13 │     """Returns an active SQLite or PostgreSQL database connection."""   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Result Card Elements

- **Decomposed Score Badges**:
  - **Hybrid**: Final calibrated fusion score (`α × Dense + (1 - α) × BM25`) expressed as a percentage (`0.0% – 100%`).
  - **Dense**: Normalized semantic cosine similarity score from the dense embedding model.
  - **BM25**: Normalized lexical keyword score from the sparse BM25 model.
- **AST Signature & Container Path**: Code search results automatically join against `ast_symbols` to display the qualified symbol name (`Class.Method`), AST kind badge (`function`, `method`, `class`), and extracted parameter/return signature.
- **Open in Navigator Bridge**: Click **Open in Navigator** on any code result to switch directly to the [Codebase Navigator](/guide/user-guide/navigator) with that repository, file, and target line range (`start_line`–`end_line`) highlighted in view.
- **Upstream Git Permalink & Copy**: Click the external link icon to open the exact file and line span in GitHub, GitLab, Gitea, or Bitbucket, or click **Copy Code** to copy the snippet.

---

## Next Steps

- Explore full files and symbol call graphs in the [Codebase Navigator](/guide/user-guide/navigator).
- Register new upstream repositories in [Git Repositories Management](/guide/user-guide/git-repositories).
- Learn how to configure local filesystem vaults in [Local Paths and Vaults](/guide/user-guide/local-paths).

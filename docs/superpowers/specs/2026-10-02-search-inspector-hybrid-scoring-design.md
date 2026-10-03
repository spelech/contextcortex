# Design Spec: Hybrid Search Inspector & Dynamic Scoring Calibration

**Date:** 2026-10-02  
**Branch:** `feat/search-inspector-hybrid-scoring`  
**Status:** In Review  

---

## 1. Problem Statement & Motivation
ContextCortex combines dense vector embeddings (BGE-Small cosine similarity) and sparse lexical embeddings (FastEmbed / BM25 SPLADE) to perform hybrid search across indexed repositories and documentation.

Currently, hybrid scoring suffers from several limitations:
1. **Lexical / BM25 Overpowering / Suppression**: In `qdrant_store.py`, fusion is hardcoded as `0.7 * dense + 0.3 * sparse`. An exact keyword match (BM25 score 1.0) is capped at `0.30`, so mediocre semantic matches (0.72 * 0.7 = 0.504) easily overpower exact identifier hits. Furthermore, users cannot customize the dense/sparse weight split.
2. **Opaque Scores**: Both the Web Search Inspector and MCP search tools return a single aggregated score. Users and AI agents cannot see whether a match came from semantic concept matching or lexical keyword hits.
3. **Missing AST Signatures in Search Returns**: While search returns the symbol name and line numbers, it lacks extracted function signatures (parameters, return types) and container hierarchy, forcing AI agents to parse raw code bodies to understand the API surface.
4. **Isolated Search Inspector**: In the admin UI (`SearchInspector.tsx`), results are rendered in raw `<pre>` tags without line numbers, repo selection is an unassisted text box rather than a populated dropdown, and there is no direct action to inspect a matched code snippet inside the Code Navigator.

---

## 2. Goals & Non-Goals

### Goals
- **Configurable Hybrid Split**: Support a dynamic `dense_weight` / $\alpha \in [0.0, 1.0]$ in backend search queries, MCP tools, and the Web UI, with an interactive slider and quick presets (`Balanced 50/50`, `Semantic 70/30`, `Keyword 30/70`, `Pure Semantic 100/0`, `Pure Keyword 0/100`).
- **Score Transparency & Diagnostics**: Expose individual component scores (`dense_score` and `sparse_score`) alongside the fused `score` across `VectorSearchResult`, `/admin/api/search/test`, and MCP tool outputs.
- **Search Mode Selection**: Allow querying in `hybrid` (fused), `semantic` (dense only), or `lexical` (BM25 only) mode.
- **AST Context Enrichment**: Automatically enrich code search returns with extracted signatures, container paths, clean AST kind badges, and line spans from `ast_symbols`.
- **Search-to-Navigator Bridging**: Provide a 1-click "Open in Navigator" action on every code search hit in the UI, seamlessly switching to the Code Navigator tab with the file and symbol highlighted.
- **Search Inspector UI Polish**: Replace plain text repo filter with a dropdown populated from `/admin/api/repos`, add a limit selector (`5`, `10`, `25`), and format code snippets with line numbers and a copy button.

### Non-Goals
- No changes to embedding models or vector index schemas (BGE-Small and FastEmbed stay as configured).
- No version bump or GitHub release until explicitly requested.
- No changes to `main` branch directly.

---

## 3. Architecture & Detailed Design

### 3.1 Vector Store & Scoring Model
In `app/services/vector_store/base.py`:
- Update `VectorSearchResult`:
  ```python
  class VectorSearchResult(BaseModel):
      id: str
      score: float = 0.0
      dense_score: Optional[float] = None
      sparse_score: Optional[float] = None
      dense_rank: Optional[int] = None
      sparse_rank: Optional[int] = None
      payload: Dict[str, Any] = Field(default_factory=dict)
  ```

In `app/services/vector_store/qdrant_store.py`:
- `search()` accepts `dense_weight: Optional[float] = None` and `search_mode: str = "hybrid"`.
- Determine effective weight:
  - If `search_mode == "semantic"`: $\alpha = 1.0$ (query dense only).
  - If `search_mode == "lexical"`: $\alpha = 0.0$ (query sparse only).
  - If `dense_weight` is provided: $\alpha = \max(0.0, \min(1.0, \text{dense\_weight}))$.
  - Otherwise fallback to `HYBRID_DENSE_WEIGHT` environment variable or default `0.5` (balanced).
- When computing fusion:
  - Store normalized `d_score` and normalized `s_score` on each `VectorSearchResult`.
  - Calculate `final_score = alpha * d_score + (1.0 - alpha) * s_score`.

### 3.2 Search Service & AST Context Enrichment
In `app/services/search.py`:
- `execute_hybrid_search(query_text, doc_type, repo, language, category, tag, limit, dense_weight=None, search_mode="hybrid")`.
- When `doc_type == "code"`:
  - For each result, query SQLite `ast_symbols` for matching `repo`, `filepath` (normalized), and overlapping `start_line` / `end_line`.
  - Enrich payload with `signature`, `full_symbol`, and `ast_symbol_id` if available.

### 3.3 HTTP API (`/admin/api/search/test`)
In `app/api/routers/repositories.py`:
- Update `SearchRequest` schema to accept:
  - `dense_weight: Optional[float] = Field(default=None, ge=0.0, le=1.0)`
  - `search_mode: Optional[str] = Field(default="hybrid")`
- Response payload:
  ```json
  {
    "query": "...",
    "type": "code",
    "search_mode": "hybrid",
    "dense_weight": 0.5,
    "results": [
      {
        "score": 0.7842,
        "dense_score": 0.8210,
        "sparse_score": 0.6950,
        "payload": {
          "repo": "mcp-router-code",
          "rel_path": "Components/Providers/ProvidersController.cs",
          "symbol": "ProvidersController.GetAuthProviders",
          "signature": "[HttpGet(\"auth\")] public async Task<IActionResult> GetAuthProviders()",
          "kind": "method_declaration",
          "start_line": 195,
          "end_line": 212,
          "ast_symbol_id": 24010,
          "content": "..."
        }
      }
    ]
  }
  ```

### 3.4 MCP Tools (`search_code`, `search_docs`)
In `app/mcp/handlers/search_handlers.py`:
- Update `handle_search_code`:
  - New parameters:
    - `dense_weight: Annotated[Optional[float], Field(description="Weight between 0.0 (pure lexical BM25) and 1.0 (pure semantic vector). Default is 0.5 balanced.")] = None`
    - `mode: Annotated[Optional[str], Field(description="Search mode: 'hybrid' (default), 'semantic', or 'lexical'.")] = "hybrid"`
  - Rich markdown header:
    ````markdown
    ### [mcp-router-code] Components/Providers/ProvidersController.cs (Lines 195-212)
    - **Symbol**: `ProvidersController.GetAuthProviders` (`method`)
    - **Signature**: `[HttpGet("auth")] public async Task<IActionResult> GetAuthProviders()`
    - **Score**: 78.4% (Semantic: 82.1% | Lexical: 69.5%)
    - **Source Link**: https://github.com/...#L195-L212

    ```c_sharp
    [HttpGet("auth")]
    public async Task<IActionResult> GetAuthProviders()
    ...
    ```
    ````
- Update `handle_search_docs` similarly with `dense_weight` and `mode`.

### 3.5 Web UI (`SearchInspector.tsx`)
1. **Search Mode Segmented Control**:
   - `[ Hybrid Fusion ]` | `[ Semantic (Dense) ]` | `[ Lexical (BM25) ]`
2. **Interactive Hybrid Split Slider (in Hybrid mode)**:
   - Slider ranging from 0.0 to 1.0 with dynamic label: `Semantic X% / Lexical Y%`.
   - Preset chips: `Balanced (50/50)`, `Semantic Bias (70/30)`, `Lexical Bias (30/70)`.
3. **Repo Dropdown & Limit Filter**:
   - Fetches repos from `/admin/api/repos` to provide a clean `<select>` (defaulting to "All Repositories").
   - Result limit `<select>`: `5`, `10`, `25`.
4. **Enhanced Search Hit Cards**:
   - Header with: Repo badge, `rel_path`, AST kind badge, Symbol badge, line span, and git host link.
   - Signature box displaying the extracted syntax signature if present.
   - Score chips:
     `<span class="badge badge-hybrid">Hybrid: 78.4%</span>`
     `<span class="badge badge-semantic">Dense: 82.1%</span>`
     `<span class="badge badge-lexical">BM25: 69.5%</span>`
   - "Open in Navigator" action button that invokes a callback or updates URL/context to switch tabs to Navigator, selecting the repo, file, and targeting the line span.
   - Code block with line number column and "Copy Code" button.

---

## 4. Testing & Verification Plan

### Backend Tests
- `tests/test_vector_store.py`:
  - Test `search()` with `search_mode="hybrid"`, `"semantic"`, and `"lexical"`.
  - Test custom `dense_weight=0.0` (pure BM25), `dense_weight=1.0` (pure dense), and `dense_weight=0.5`.
  - Verify `dense_score` and `sparse_score` are accurately recorded on `VectorSearchResult`.
- `tests/test_search_service.py` & `tests/test_mcp_tools.py`:
  - Verify AST signature enrichment joins correctly.
  - Verify `search_code` and `search_docs` MCP outputs contain the new markdown format and score breakdown.
- API route test: `POST /admin/api/search/test` verifies handling of `dense_weight` and `search_mode`.

### Frontend Tests
- `frontend/src/tests/SearchInspector.test.tsx`:
  - Verify rendering of search mode buttons and hybrid split slider.
  - Verify preset buttons update the slider value.
  - Verify search submission passes `dense_weight` and `search_mode`.
  - Verify score breakdown badges and AST signature rendering.
  - Verify "Open in Navigator" triggers tab transition.
- Full Vitest suite passes without regression.

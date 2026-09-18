# Normalized Weighted Search Scoring Design

## Overview
Currently, Qdrant Hybrid Search (`Dense + BM25 Sparse`) combines search candidates using Reciprocal Rank Fusion (`Fusion.RRF`). Because RRF calculates scores based strictly on reciprocal ranks ($1 / (1 + \text{rank})$), the theoretical maximum score for a single modality is 0.50, and rank 2–4 results score between 0.20 and 0.33. This produces counter-intuitive scores in the Search Inspector and MCP search tool output (e.g. `RRF Score: 0.3333`), which look like 33% relevance even for top-ranked results, and differs from single-vector engines (Chroma and pgvector) which use cosine similarity (0.70 – 0.95).

This design transitions Qdrant Hybrid Search to **Normalized Linear Weighted Fusion** ($\alpha \cdot \text{Dense} + (1 - \alpha) \cdot \text{Sparse}$, with $\alpha = 0.7$), keeping all search scores strictly bounded on a **0.0 to 1.0 (0% to 100%)** scale, expanding prefetch candidate pools for higher cross-stream intersection recall, and updating UI/MCP labels to clearly display the score.

---

## Architecture & Scoring Formula

### 1. Multi-Stream Batch Candidate Retrieval
Instead of performing server-side RRF fusion via `FusionQuery`, `QdrantVectorStore.search` will execute a single batch query via `client.query_batch_points` requesting candidates from both streams simultaneously:
- **Dense stream**: `qmodels.QueryRequest(query=dense_vec, using="dense", limit=candidate_limit, filter=query_filter, with_payload=True)`
- **Sparse stream**: `qmodels.QueryRequest(query=sparse_vec, using="sparse", limit=candidate_limit, filter=query_filter, with_payload=True)`

The candidate pool depth is expanded from `limit * 2` to:
$$\text{candidate\_limit} = \max(\text{limit} \times 5, 50)$$
This ensures that documents ranked beyond position 10 in either dense or sparse have adequate opportunity to intersect and achieve multi-stream reinforcement.

### 2. Score Normalization
- **Dense Cosine Score** ($S_{\text{dense}}$):
  Since Qdrant dense vectors use Cosine distance, point scores are cosine similarity. Values are clamped to $[0.0, 1.0]$:
  $$S_{\text{dense\_norm}} = \max(0.0, \min(1.0, S_{\text{dense}}))$$
- **Sparse BM25 Score** ($S_{\text{sparse}}$):
  BM25 scores in FastEmbed/Qdrant are unbounded non-negative values. Scores within the retrieved candidate set are normalized relative to the maximum BM25 score observed for the query:
  $$S_{\text{sparse\_max}} = \max(\{S_{\text{sparse}}(p) \mid p \in \text{sparse\_points}\}, 1.0)$$
  $$S_{\text{sparse\_norm}} = \frac{S_{\text{sparse}}}{S_{\text{sparse\_max}}}$$

### 3. Weighted Score Fusion
For each candidate document $d$ appearing in either stream:
$$S_{\text{final}}(d) = \alpha \cdot S_{\text{dense\_norm}}(d) + (1 - \alpha) \cdot S_{\text{sparse\_norm}}(d)$$

- **Dense weight**: $\alpha = 0.7$ by default, configurable via `HYBRID_DENSE_WEIGHT` environment variable.
- If document $d$ only matched in dense (e.g. sparse did not match), $S_{\text{sparse\_norm}}(d) = 0.0$.
- If document $d$ only matched in sparse (e.g. dense did not rank it in top candidates), $S_{\text{dense\_norm}}(d) = 0.0$.
- If sparse is unavailable or query produces no sparse tokens, the search executes a standard dense query and returns $S_{\text{final}} = S_{\text{dense\_norm}}$.
- All resulting scores are guaranteed to be in the range $[0.0, 1.0]$.

---

## Component Changes

### 1. Vector Store Backend (`app/services/vector_store/qdrant_store.py`)
- Update `QdrantVectorStore.search()`:
  - If `sparse_vec is not None and len(sparse_vec.indices) > 0`:
    - Dispatch batch query with dense and sparse `QueryRequest`.
    - Apply normalized weighted fusion formula.
    - Sort combined unique results descending by $S_{\text{final}}$.
    - Slice to `limit` items and return as `VectorSearchResult(id=..., score=round(final_score, 4), payload=...)`.
  - If sparse is not used:
    - Execute dense `query_points` directly with cosine score clamped to $[0.0, 1.0]$.

### 2. Frontend Search Inspector (`frontend/src/SearchInspector.tsx`)
- Update result badge display:
  - Change `RRF Score: {hit.score.toFixed(4)}` to:
    `Score: {(hit.score * 100).toFixed(1)}% ({hit.score.toFixed(4)})`
  - Example rendering: `Score: 80.5% (0.8049)`.

### 3. MCP Search Handlers (`app/mcp/handlers/search_handlers.py`)
- In `handle_search_code` and `handle_search_docs`:
  - Change markdown header:
    `Relevance Score: {hit.score:.4f} ({hit.score * 100:.1f}%)`

---

## Testing & Verification Plan

### Backend Unit Tests (`tests/backend/test_vector_store_qdrant.py`)
- Add `test_search_weighted_score_fusion`:
  - Verify hybrid search scores are in $[0.0, 1.0]$.
  - Verify that matching both dense and sparse yields higher scores than single-stream match.
  - Verify candidate limit expansion and dense fallback.

### Frontend Unit Tests (`frontend/src/tests/SearchInspector.test.tsx`)
- Update mock test data and expectations to match the new `Score: XX.X% (X.XXXX)` badge format.

### End-to-End Regression Tests
- Run complete pytest test suite: `pytest`.
- Run complete vitest test suite: `npm test` in `frontend/`.

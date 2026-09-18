# Normalized Weighted Search Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement normalized weighted score fusion ($\alpha \cdot \text{Dense} + (1-\alpha) \cdot \text{Sparse}$, $\alpha = 0.7$) in Qdrant hybrid search, expand prefetch candidate depth, and update UI/MCP score badge formatting.

**Architecture:** Replace server-side Qdrant RRF fusion with multi-stream batch querying via `query_batch_points` requesting $\max(\text{limit} \times 5, 50)$ candidates for dense and sparse streams in a single roundtrip. Normalize sparse BM25 scores relative to the query's max BM25 score, clamp dense cosine scores to $[0.0, 1.0]$, and combine linearly into a final score in $[0.0, 1.0]$. Update Search Inspector and MCP search output to display normalized percentages alongside raw 4-decimal scores.

**Tech Stack:** Python 3.12, FastAPI, Qdrant Client (`qmodels`), React 18, TypeScript, Vitest, Pytest.

## Global Constraints
- Scores must strictly fall in the range $[0.0, 1.0]$.
- Default dense weight $\alpha = 0.7$, configurable via `HYBRID_DENSE_WEIGHT` environment variable.
- Maintain fallback to single-stream dense search when sparse tokens are empty or unavailable.
- Do not introduce extra network roundtrips: use `query_batch_points` for concurrent multi-stream retrieval.
- Preserve 100% test pass rate across all existing backend and frontend test suites.

---

### Task 1: Normalized Weighted Fusion in `QdrantVectorStore`

**Files:**
- Modify: `app/services/vector_store/qdrant_store.py:280-345`
- Test: `tests/backend/test_vector_store_qdrant.py`

**Interfaces:**
- Consumes: `get_dense_embedding(text: str) -> List[float]`, `get_sparse_embedding(text: str) -> Optional[SparseVector]`
- Produces: `QdrantVectorStore.search(query_text, doc_type, repo, language, category, tag, limit) -> List[VectorSearchResult]` where `score` is in $[0.0, 1.0]$.

- [ ] **Step 1: Write the failing test**

In `tests/backend/test_vector_store_qdrant.py`, add a test verifying weighted score fusion:

```python
    def test_search_weighted_score_fusion_range_and_boost(self, memory_store):
        doc1 = VectorDocument(
            id=str(uuid.uuid4()),
            text="High performance docker container orchestration and deployment.",
            repo="devops",
            path="/docs/docker.md",
            doc_type="doc"
        )
        doc2 = VectorDocument(
            id=str(uuid.uuid4()),
            text="Kubernetes cluster management without any docker keywords.",
            repo="k8s",
            path="/docs/k8s.md",
            doc_type="doc"
        )
        memory_store.upsert_documents([doc1, doc2])

        results = memory_store.search("docker container deployment", limit=5)
        assert len(results) > 0
        top = results[0]
        # Score must be bounded in [0.0, 1.0]
        assert 0.0 <= top.score <= 1.0
        # The document matching both dense semantics and BM25 keywords should score significantly higher than RRF fractions
        assert top.score >= 0.50
        assert top.payload["repo"] == "devops"
```

- [ ] **Step 2: Run test to verify it fails or asserts legacy behavior**

Run: `pytest tests/backend/test_vector_store_qdrant.py::TestQdrantVectorStoreOperations::test_search_weighted_score_fusion_range_and_boost -v`
Expected: FAIL (legacy RRF produced `top.score == 0.50` or `0.3333` which fails the `>= 0.50` threshold with multi-modal match, or fails if dense/sparse weighting is not yet implemented).

- [ ] **Step 3: Implement normalized weighted fusion in `QdrantVectorStore.search`**

In `app/services/vector_store/qdrant_store.py`:
Read `HYBRID_DENSE_WEIGHT` (float, default `0.7`).
Calculate `candidate_limit = max(limit * 5, 50)`.
If `sparse_vec is not None and len(sparse_vec.indices) > 0`:
Use `self.client.query_batch_points(collection_name=self.collection_name, requests=[qmodels.QueryRequest(query=dense_vec, using="dense", limit=candidate_limit, filter=query_filter, with_payload=True), qmodels.QueryRequest(query=sparse_vec, using="sparse", limit=candidate_limit, filter=query_filter, with_payload=True)])`.
Extract `dense_pts = {str(p.id): p for p in batch_response[0].points}`.
Extract `sparse_pts = {str(p.id): p for p in batch_response[1].points}`.
Compute `max_sparse = max((p.score for p in sparse_pts.values() if p.score is not None), default=1.0)`.
For all unique IDs across dense and sparse:
- `d_score = max(0.0, min(1.0, float(dense_pts[uid].score))) if uid in dense_pts and dense_pts[uid].score is not None else 0.0`
- `s_score = (float(sparse_pts[uid].score) / max_sparse) if uid in sparse_pts and sparse_pts[uid].score is not None and max_sparse > 0 else 0.0`
- `final_score = (alpha * d_score + (1.0 - alpha) * s_score) if (uid in dense_pts and uid in sparse_pts) else (alpha * d_score if uid in dense_pts else (1.0 - alpha) * s_score)`
Sort descending by `final_score`, slice `[:limit]`, and wrap in `VectorSearchResult(id=uid, score=round(final_score, 4), payload=pt.payload or {})`.
If `sparse_vec` is empty, query `dense` directly, clamp score to $[0.0, 1.0]$, and return top `limit`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_vector_store_qdrant.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/vector_store/qdrant_store.py tests/backend/test_vector_store_qdrant.py
git commit -m "feat(search): implement normalized weighted score fusion in QdrantVectorStore"
```

---

### Task 2: MCP Search Tool Output Formatting

**Files:**
- Modify: `app/mcp/handlers/search_handlers.py:49,92`
- Test: `tests/backend/test_mcp_v2.py`

**Interfaces:**
- Consumes: `execute_hybrid_search(...) -> List[VectorSearchResult]`
- Produces: Formatted markdown containing `Relevance Score: {hit.score:.4f} ({hit.score * 100:.1f}%)`

- [ ] **Step 1: Write failing test assertion for MCP search output**

In `tests/backend/test_mcp_v2.py`, update any assertion expecting `RRF Score:` to expect `Relevance Score:`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_mcp_v2.py -v`
Expected: FAIL on string mismatch (`RRF Score:` vs `Relevance Score:`).

- [ ] **Step 3: Update `search_handlers.py` formatting**

In `app/mcp/handlers/search_handlers.py`:
Line 49:
Change: `header += f"\nRRF Score: {hit.score:.4f}\n"`
To: `header += f"\nRelevance Score: {hit.score:.4f} ({hit.score * 100:.1f}%)\n"`
Line 92:
Change: `header += f"\nRRF Score: {hit.score:.4f}\n"`
To: `header += f"\nRelevance Score: {hit.score:.4f} ({hit.score * 100:.1f}%)\n"`

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/test_mcp_v2.py tests/backend/test_db_and_tools.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add app/mcp/handlers/search_handlers.py tests/backend/test_mcp_v2.py
git commit -m "feat(mcp): update search output badge to display relevance percentage"
```

---

### Task 3: Frontend Search Inspector Badge & Tests

**Files:**
- Modify: `frontend/src/SearchInspector.tsx:116`
- Test: `frontend/src/tests/SearchInspector.test.tsx:9,67`

**Interfaces:**
- Consumes: `/admin/api/search/test` JSON response with `hit.score`
- Produces: UI badge `<span className="badge badge-success">Score: {(hit.score * 100).toFixed(1)}% ({hit.score.toFixed(4)})</span>`

- [ ] **Step 1: Write failing test assertion for SearchInspector UI**

In `frontend/src/tests/SearchInspector.test.tsx`:
Change line 9 mock score to `0.825`.
Change line 67 expectation to:
`expect(screen.getByText('Score: 82.5% (0.8250)')).toBeInTheDocument();`

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test -- src/tests/SearchInspector.test.tsx`
Expected: FAIL on `Score: 82.5% (0.8250)` not found.

- [ ] **Step 3: Update `SearchInspector.tsx` badge rendering**

In `frontend/src/SearchInspector.tsx` line 116:
Change:
`<span className="badge badge-success">RRF Score: {hit.score.toFixed(4)}</span>`
To:
`<span className="badge badge-success">Score: {(hit.score * 100).toFixed(1)}% ({hit.score.toFixed(4)})</span>`

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test -- src/tests/SearchInspector.test.tsx`
Expected: ALL PASS.

- [ ] **Step 5: Rebuild frontend distribution**

Run: `cd frontend && npm run build && cd ..`
Stage the updated `frontend/dist` bundle assets.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/SearchInspector.tsx frontend/src/tests/SearchInspector.test.tsx frontend/dist/
git commit -m "feat(ui): update Search Inspector score badge to percentage and rebuild dist"
```

---

### Task 4: Full System Verification & Requirements Sync

**Files:**
- Verification only

- [ ] **Step 1: Run complete backend test suite**

Run: `pytest`
Expected: 498 passed (100%).

- [ ] **Step 2: Run complete frontend vitest suite**

Run: `npm --prefix frontend test -- --run`
Expected: All test files passing (100%).

- [ ] **Step 3: Verify requirements sync**

Run: `python3 scripts/generate_requirements.py && pytest tests/backend/test_requirements_sync.py`
Expected: In sync, PASS.

- [ ] **Step 4: Commit any documentation/requirements updates**

```bash
git add REQUIREMENTS.md docs/REQUIREMENTS.md
git commit -m "chore: sync requirements baseline following search scoring enhancement"
```

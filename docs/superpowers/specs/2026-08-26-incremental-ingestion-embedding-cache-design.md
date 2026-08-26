# Incremental Ingestion, Chunk Embedding Cache & Doc Graph Linking Design

**Date:** 2026-08-26  
**Status:** Approved  
**Author:** Pair Programming Session (Antigravity & spelech)  

---

## 1. Problem Statement & Motivation

ContextCortex (v2.10.0) provides hybrid semantic and AST code symbol search across repositories and markdown documentation. However, in large repositories:
1. **Recurring Re-indexing Waste**: When a git repository detects a new remote commit (`remote_sha != commit_sha`), ContextCortex currently deletes the entire repository index (`store.delete_by_repo(repo_name)` and SQLite tables) and re-embeds all files from scratch, incurring high latency, CPU/GPU saturation, and unnecessary API token costs.
2. **Synchronous Unbatched Processing**: `process_file_content` synchronously generates embeddings file-by-file with 1-5 chunks per API/ONNX call, instead of bulk-vectorized pipelining across the repository.
3. **Disjoint Documentation Graph**: While documentation files (`.md`, `.txt`, ADRs) exist as nodes in the topology graph, internal relative links `[Arch](docs/arch.md)` and Obsidian wikilinks `[[Concept]]` are not parsed as graph edges (`ast_relationships`), leaving doc nodes isolated from one another.

---

## 2. Architecture & Solution Overview

This feature delivers a three-part optimization:
1. **True Incremental Git Syncing**: Compute file-level SHA256 content hashes (or git tree diffs). Categorize files into Added ($A$), Modified ($M$), Deleted ($D$), and Unchanged ($U$). Only prune and re-index $A$, $M$, and $D$.
2. **Chunk-Level Hash Embedding Cache (`embedding_cache`)**: Store `(chunk_hash PRIMARY KEY, dense_vector, sparse_indices, sparse_values)`. Reuse vectors across commits, branch switches, and re-indexes so identical text is never embedded twice.
3. **Markdown & Wikilink Graph Extraction**: Extract relative markdown links and wikilinks into `ast_relationships` with relationship type `DOC_LINKS_TO`. Connect document nodes in `graph_builder.py`.
4. **Optimized Pipeline Batching**: Batch AST extraction and chunk collection across files, perform bulk cache lookups, embed missing chunks in configurable bulk batches (e.g. 64-128 chunks), and commit in atomic database chunks.

---

## 3. Database Schema Updates

In `app/services/database/connection.py`:

```sql
CREATE TABLE IF NOT EXISTS embedding_cache (
    chunk_hash TEXT PRIMARY KEY,
    dense_vector TEXT NOT NULL,       -- JSON serialized float list
    sparse_indices TEXT,              -- JSON serialized int list (optional)
    sparse_values TEXT,               -- JSON serialized float list (optional)
    model_name TEXT,                  -- Dense model identifier
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_embedding_cache_hash ON embedding_cache(chunk_hash);
CREATE INDEX IF NOT EXISTS idx_indexed_files_repo_hash ON indexed_files(repo, hash);
```

---

## 4. Detailed Component Changes

### A. `app/services/database/embedding_cache.py` (New / Enhanced Service)
- `get_cached_embeddings_batch(chunk_hashes: List[str], model_name: str) -> Dict[str, Dict[str, Any]]`: Bulk retrieves vectors by SHA256 chunk hash.
- `set_cached_embeddings_batch(items: List[Tuple[str, List[float], Optional[List[int]], Optional[List[float]], str]])`: Bulk persists new vectors.
- `invalidate_cache_by_model(model_name: Optional[str] = None)`: Prunes mismatched vector entries on model switch.

### B. `app/services/indexing/git_syncer.py`
- On sync: shallow clone repo, walk all files, compute SHA256 for each.
- Compare with existing `indexed_files` for the repo:
  - Identify $A$ (Added), $M$ (Modified), $D$ (Deleted), $U$ (Unchanged).
- If no files changed ($A=0, M=0, D=0$), immediately update `git_repositories.commit_sha` and exit.
- For $D$ and $M$: call `store.delete_by_path(filepath)` and delete SQLite rows for those specific files.
- For $A$ and $M$: parse and chunk files, query `embedding_cache` for chunk hashes, bulk embed missing chunks, upsert vectors to vector store, and insert metadata to SQLite.

### C. `app/services/chunking/text_chunker.py` & `processor.py`
- Parse markdown links `[text](target.md)` and wikilinks `[[target]]`.
- Generate `CodeRelationship(repo=repo, source_filepath=filepath, source_symbol=title, target_symbol=target, relationship_type='DOC_LINKS_TO', line_number=line)`.
- Skip oversized files (>500KB) and ignored patterns (`package-lock.json`, `.min.js`, `.bundle.js`).

### D. `app/services/topology/graph_builder.py`
- In `graph_builder.py`, handle `rel_type == 'DOC_LINKS_TO'`: resolve target to file node in `file_id_by_path` and add edge with type `DOC_LINKS_TO` and label `LINKS_TO`.

---

## 5. Testing & Verification Plan

1. Unit test `test_embedding_cache.py`: Verifies bulk cache retrieval, insertion, and hit rate.
2. Unit test `test_doc_links.py`: Verifies extraction of standard markdown relative links and Obsidian wikilinks into `DOC_LINKS_TO`.
3. Unit test `test_git_incremental.py`: Verifies file diff categorization ($A, M, D, U$) and single-file update behavior.
4. Integration test `test_incremental_pipeline.py`: Simulates commit 1 $\rightarrow$ commit 2 updates, asserting zero re-embeddings for untouched files and correct graph connectivity.

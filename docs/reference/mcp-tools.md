# MCP Tools and Resources Reference

This document provides complete reference specifications for all **16 Model Context Protocol (MCP) tools**, dynamic resources, and guided prompts exposed by ContextCortex (`app/mcp/tools.py`).

---

## MCP Tools Summary Matrix

| Tool Name | Minimum Role | Category | Primary Parameters | Description |
| :--- | :---: | :--- | :--- | :--- |
| [`search_code`](#1-search-code) | `viewer` | Search & Retrieval | `query`, `repo`, `language`, `limit`, `dense_weight`, `mode` | Hybrid semantic + BM25 search over code chunks with AST signatures, score decomposition, and Git permalinks. |
| [`search_docs`](#2-search-docs) | `viewer` | Search & Retrieval | `query`, `repo`, `category`, `tag`, `limit`, `dense_weight`, `mode` | Hybrid search across Markdown documentation, architectural decision records, summaries, and PDFs. |
| [`find_symbol`](#3-find-symbol) | `viewer` | AST Symbols & Graphs | `name`, `repo`, `exact`, `limit` | Sub-50ms exact or prefix lookup of AST symbols (functions, classes, methods, interfaces). |
| [`get_file_outline`](#4-get-file-outline) | `viewer` | AST Symbols & Graphs | `filepath`, `repo` | Structural AST outline of a file (classes, methods, signatures, line ranges) without full token costs. |
| [`trace_path`](#5-trace-path) | `viewer` | AST Symbols & Graphs | `symbol`, `repo`, `direction`, `depth`, `limit` | Breadth-first traversal of function call graphs, imports, and inheritance relationships. |
| [`find_routes`](#6-find-routes) | `viewer` | API Route Discovery | `query`, `method`, `repo`, `limit` | Lists or searches HTTP route declarations across backend frameworks (FastAPI, Express, ASP.NET, Flask, Gin). |
| [`find_api_callers`](#7-find-api-callers) | `viewer` | API Route Discovery | `path`, `method`, `repo` | Finds client call sites and services that invoke a specific HTTP endpoint or URL pattern. |
| [`list_repositories`](#8-list-repositories) | `viewer` | Repositories & Architecture | *None* | Lists all registered Git repositories and monitored local paths with branches, commit SHAs, and sync status. |
| [`sync_repository`](#9-sync-repository) | `editor` | Repositories & Architecture | `repo` | Triggers an immediate re-fetch and incremental re-indexing of a specific repository or all sources. |
| [`index_status`](#10-index-status) | `viewer` | Repositories & Architecture | *None* | Returns global vector counts, active vector backend, embedding models, and provider rate limits. |
| [`get_architecture`](#11-get-architecture) | `viewer` | Repositories & Architecture | `repo` | Synthesizes language distributions, entry points, core modules, route counts, and active ADRs. |
| [`manage_adr`](#12-manage-adr) | `editor` / `viewer` | Repositories & Architecture | `action`, `repo`, `id`, `title`, `status`, `context`, `decision`, `consequences` | Reads, lists, creates, updates, or supersedes Architectural Decision Records (MADR format). |
| [`what_is_ingested`](#13-what-is-ingested) | `viewer` | Storage & File Access | `source_type`, `repo_name`, `path_prefix`, `file_extension`, `detail_level` | Inspects all ingested Git repositories, monitored local paths, and uploaded local storage files. |
| [`manage_local_file`](#14-manage-local-file) | `editor` / `viewer` | Storage & File Access | `action`, `file_path`, `content`, `repo`, `category` | Uploads, replaces, reads, previews, or deletes files in managed local storage with immediate indexing. |
| [`read_file`](#15-read-file) | `viewer` | Storage & File Access | `path`, `repo`, `start_line`, `end_line` | Reads full file content or bounded 1-indexed line ranges from monitored directories, persistent repos, or storage. |
| [`summarize_file`](#16-summarize-file) | `viewer` | Storage & File Access | `path`, `repo`, `force_refresh` | Retrieves a cached summary or generates a structured LLM executive summary for a large file. |

---

## Search & Retrieval Tools

### 1. `search_code`
Performs calibrated hybrid semantic and BM25 lexical search over indexed source code chunks and enriches matches with AST symbol metadata.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `query` (*string, required*): Natural language question or code concept (e.g. `"JWT token authentication handler"`).
  - `repo` (*string, optional*): Restrict results to a specific repository alias.
  - `language` (*string, optional*): Filter by programming language (e.g. `python`, `typescript`, `c_sharp`, `go`).
  - `limit` (*integer, default: 5*): Maximum number of ranked code blocks to return.
  - `dense_weight` (*float, optional*): Hybrid weight between `0.0` (pure lexical BM25) and `1.0` (pure semantic vector). Defaults to `0.5` balanced.
  - `mode` (*string, default: `"hybrid"`*): Search mode: `"hybrid"`, `"semantic"`, or `"lexical"`.
- **Returns**: Formatted Markdown cards containing the repository, file path, 1-indexed line span, qualified AST symbol (`Class.Method`), extracted signature, decomposed score breakdown (`Score: 78.4% (Semantic: 82.1% | Lexical: 69.5%)`), clickable Git permalink, and syntax-fenced code block.

### 2. `search_docs`
Performs calibrated hybrid search across Markdown documentation, architectural decision records, executive summaries, and indexed PDF documents.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `query` (*string, required*): Search query or documentation topic.
  - `repo` (*string, optional*): Repository or vault alias filter.
  - `category` (*string, optional*): Category filter (e.g. `architecture`, `guides`, `notes`).
  - `tag` (*string, optional*): Frontmatter tag filter.
  - `limit` (*integer, default: 5*): Maximum number of document chunks to return.
  - `dense_weight` (*float, optional*): Weight between `0.0` (lexical) and `1.0` (semantic). Defaults to `0.5`.
  - `mode` (*string, default: `"hybrid"`*): Search mode: `"hybrid"`, `"semantic"`, or `"lexical"`.
- **Returns**: Ranked documentation sections with heading breadcrumbs (`# > ## > ###`), decomposed relevance scores, and source paths.

---

## AST Symbols & Call Graph Tools

### 3. `find_symbol`
Performs deterministic sub-50ms symbol lookup from the relational `ast_symbols` index without vector search overhead.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `name` (*string, required*): Symbol identifier to find (e.g. `FastEmbedEngine` or `execute_hybrid_search`).
  - `repo` (*string, optional*): Repository alias filter.
  - `exact` (*boolean, default: true*): Perform exact matching when `true`, prefix/fuzzy matching when `false`.
  - `limit` (*integer, default: 10*): Maximum matches to return.
- **Returns**: Symbol declarations with qualified names, parameter signatures, 1-indexed starting and ending lines, and file paths.

### 4. `get_file_outline`
Returns the structural AST outline of a file without retrieving its full token body.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `filepath` (*string, required*): Relative file path (e.g. `app/services/search.py` or `repo_name://app/services/search.py`).
  - `repo` (*string, optional*): Repository identifier.
- **Returns**: Hierarchical list of classes, functions, methods, signatures, and line spans defined in the file.

### 5. `trace_path`
Deterministically traverses function call graphs, module imports, and inheritance hierarchies using AST relationships (`ast_relationships`) via breadth-first search (BFS).

- **Minimum Role**: `viewer`
- **Parameters**:
  - `symbol` (*string, required*): Target function, method, or class name to trace.
  - `repo` (*string, optional*): Specific repository to trace within (searches across all repositories when omitted).
  - `direction` (*string, default: `"both"`*): Traversal direction: `"callers"` (inbound), `"callees"` (outbound), or `"both"`.
  - `depth` (*integer, default: 2*): Maximum BFS traversal hops (`1` to `5`).
  - `limit` (*integer, default: 25*): Maximum relationships returned.
- **Returns**: Directed call/import graph edges with source files, target symbols, relationship types (`CALLS`, `IMPORTS`, `EXTENDS`), and line numbers.

---

## API Route Discovery Tools

### 6. `find_routes`
Lists or searches declared HTTP endpoints and route handlers across indexed backend frameworks.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `query` (*string, optional*): URL path substring or pattern (e.g. `"/api/v1/users"` or `"search"`).
  - `method` (*string, optional*): HTTP method filter (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`).
  - `repo` (*string, optional*): Repository alias filter.
  - `limit` (*integer, default: 20*): Maximum routes to return.
- **Returns**: Matched HTTP routes with framework name, HTTP method, normalized path template, handler symbol, file path, and line numbers.

### 7. `find_api_callers`
Finds client call sites and services that invoke a specific HTTP endpoint or URL pattern (`api_client_calls`).

- **Minimum Role**: `viewer`
- **Parameters**:
  - `path` (*string, required*): Endpoint path pattern or URL segment to match (e.g. `"/users/{id}"` or `"/admin/api/search/test"`).
  - `method` (*string, optional*): Target HTTP method (`GET`, `POST`, etc.).
  - `repo` (*string, optional*): Filter client search by repository.
- **Returns**: Matching client invocations with caller symbol, file path, HTTP method, and line number alongside matching backend route handlers.

---

## Repositories, Architecture & ADR Tools

### 8. `list_repositories`
Lists all registered Git repositories and monitored local filesystem paths.

- **Minimum Role**: `viewer`
- **Parameters**: None.
- **Returns**: Repository aliases, provider badges (`[GITHUB]`, `[GITLAB]`, `[GITEA]`, `[BITBUCKET]`), active branches, latest indexed commit SHAs, shallow retention flags, and file counts.

### 9. `sync_repository`
Triggers an immediate synchronization and incremental re-indexing run for a registered Git repository or local path.

- **Minimum Role**: `editor`
- **Parameters**:
  - `repo` (*string, optional*): Repository alias to synchronize (synchronizes all enabled sources when omitted).
- **Returns**: Synchronization status and updated commit SHA.

### 10. `index_status`
Returns global index health, vector collection statistics, active embedding models, and GitHub API rate limits.

- **Minimum Role**: `viewer`
- **Parameters**: None.
- **Returns**: Active vector store provider (`qdrant`, `pgvector`, `chroma`), total vector count, dense/sparse model names, and rate limit counters.

### 11. `get_architecture`
Synthesizes a high-level architectural overview of a repository or the entire indexed workspace.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `repo` (*string, optional*): Specific repository alias (returns a multi-repository overview when omitted).
- **Returns**: Language breakdown, detected entry points, primary directory modules, API route counts, and active Architectural Decision Records.

### 12. `manage_adr`
Reads, lists, creates, updates, or supersedes Architectural Decision Records (MADR / Nygard format).

- **Minimum Role**: `viewer` for `list`/`get`; `editor` for `create`/`update`/`supersede`.
- **Parameters**:
  - `action` (*string, required*): `"list"`, `"get"`, `"create"`, `"update"`, or `"supersede"`.
  - `repo` (*string, required*): Repository identifier.
  - `id` (*string, optional*): ADR identifier (e.g. `"ADR-001"`).
  - `title` (*string, optional*): Title of the ADR.
  - `status` (*string, optional*): `"PROPOSED"`, `"ACCEPTED"`, `"REJECTED"`, `"SUPERSEDED"`, or `"DEPRECATED"`.
  - `context`, `decision`, `consequences`, `superseded_by` (*string, optional*): ADR body sections.
- **Returns**: ADR record details or confirmation of lifecycle update.

---

## Storage, Catalog & File Reading Tools

### 13. `what_is_ingested`
Inspects all ingested Git repositories, monitored local paths, and uploaded local storage files with multi-dimensional filtering.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `source_type` (*string, default: `"all"`*): Filter by `"all"`, `"git"`, `"monitored_path"`, or `"local_storage"`.
  - `repo_name` (*string, optional*): Filter by specific repository or storage namespace.
  - `path_prefix` (*string, optional*): Filter files matching a directory prefix.
  - `file_extension` (*string, optional*): Filter by extension (e.g. `".py"`, `".md"`).
  - `detail_level` (*string, default: `"summary"`*): `"summary"` (aggregate counts and statuses) or `"detailed"` (file-by-file inventory).
- **Returns**: Consolidated multi-source catalog inventory.

### 14. `manage_local_file`
Manages files inside the managed local storage directory (`LOCAL_STORAGE_PATH`) with real-time incremental indexing.

- **Minimum Role**: `viewer` for `read`; `editor` for `upload`, `replace`, `delete`.
- **Parameters**:
  - `action` (*string, required*): `"upload"`, `"replace"`, `"read"`, or `"delete"`.
  - `file_path` (*string, required*): Relative file path within local storage (path traversal tokens `..` are rejected).
  - `content` (*string, optional*): File text content for `upload` or `replace`.
  - `repo` (*string, default: `"local_storage"`*): Logical namespace alias.
  - `category` (*string, optional*): Optional document category tag.
- **Returns**: File operation status, byte size, and immediate vector/AST indexing confirmation.

### 15. `read_file`
Reads entire file contents or bounded 1-indexed line ranges from monitored local directories, persistent shallow repositories, or managed local storage.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `path` (*string, required*): Relative or absolute file path within an indexed source.
  - `repo` (*string, optional*): Repository or storage namespace identifier.
  - `start_line` (*integer, optional*): 1-based starting line number (inclusive).
  - `end_line` (*integer, optional*): 1-based ending line number (inclusive).
- **Returns**: Numbered source lines with truncation safeguards (`max_lines_per_read`, default `2,000` lines).

### 16. `summarize_file`
Retrieves a cached executive summary or generates a structured LLM summary for a large source or documentation file.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `path` (*string, required*): Path to the file to summarize.
  - `repo` (*string, optional*): Repository or storage namespace filter.
  - `force_refresh` (*boolean, default: false*): When `true`, bypasses the SQLite cache and generates a fresh summary via the configured chat model.
- **Returns**: Structured Markdown summary covering file purpose, exported symbols, dependencies, and architectural role.

---

## Dynamic Catalog Resources & Guided Prompts

### Dynamic Catalog Resources

| Resource URI | MIME Type | Description |
| :--- | :--- | :--- |
| `knowledge://catalog/summary` | `text/markdown` | Real-time Markdown report summarizing all indexed repositories, document distributions, and AST symbol totals. |

### Guided Prompts

#### 1. `search_infrastructure_docs`
- **Arguments**: `topic` (*string*)
- **Description**: Guides an AI assistant to retrieve system architecture notes, container port mappings, and reverse proxy routes.

#### 2. `find_implementation_symbol`
- **Arguments**: `symbol` (*string*), `repo` (*string, optional*)
- **Description**: Guides an AI assistant to locate symbol declarations, parameter signatures, and call sites across registered codebases.

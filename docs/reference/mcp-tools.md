# MCP Tools and Resources Reference

This document provides complete reference specifications for all **19 Model Context Protocol (MCP) tools**, dynamic resources, and guided prompts exposed by ContextCortex (`app/mcp/tools.py`).

---

## MCP Tools Summary Matrix

| Tool Name | Minimum Role | Category | Primary Parameters | Description |
| :--- | :---: | :--- | :--- | :--- |
| [`search_code`](#1-search-code) | `viewer` | Search & Retrieval | `query`, `repo`, `language`, `limit`, `dense_weight`, `mode` | Hybrid semantic + BM25 search over code chunks with AST signatures, score decomposition, and Git permalinks. |
| [`search_docs`](#2-search-docs) | `viewer` | Search & Retrieval | `query`, `repo`, `category`, `tag`, `limit`, `dense_weight`, `mode` | Hybrid search across Markdown documentation, architectural decision records, summaries, and PDFs. |
| [`grep_code`](#3-grep-code) | `viewer` | Search & Retrieval | `pattern`, `repo`, `path_glob`, `is_regex`, `case_sensitive`, `context_lines`, `limit` | Deterministic literal and regex pattern matching across one or all indexed repositories with context lines and AST symbol attribution. |
| [`diagnose_issue`](#4-diagnose-issue) | `viewer` | Forensic Triage | `issue_text`, `repo`, `context_lines`, `limit` | Forensic triage tool that parses stack traces, resolves AST frames, matches error literals and HTTP routes, and retrieves semantic code candidates. |
| [`find_symbol`](#5-find-symbol) | `viewer` | AST Symbols & Graphs | `name`, `repo`, `exact`, `limit` | Sub-50ms exact or prefix lookup of AST symbols (functions, classes, methods, interfaces). |
| [`get_file_outline`](#6-get-file-outline) | `viewer` | AST Symbols & Graphs | `filepath`, `repo` | Structural AST outline of a file (classes, methods, signatures, line ranges) without full token costs. |
| [`trace_path`](#7-trace-path) | `viewer` | AST Symbols & Graphs | `symbol`, `repo`, `direction`, `depth`, `limit` | Breadth-first traversal of function call graphs, imports, inheritance, and cross-repo HTTP boundaries (`external_callers`, `external_handlers`). |
| [`find_routes`](#8-find-routes) | `viewer` | API Route Discovery | `query`, `method`, `repo`, `limit` | Lists or searches HTTP route declarations across backend frameworks (FastAPI, Express, ASP.NET, Flask, Gin). |
| [`find_api_callers`](#9-find-api-callers) | `viewer` | API Route Discovery | `path`, `method`, `repo` | Finds client call sites and services that invoke a specific HTTP endpoint or URL pattern. |
| [`list_repositories`](#10-list-repositories) | `viewer` | Repositories & Architecture | *None* | Lists all registered Git repositories and monitored local paths with branches, commit SHAs, and sync status. |
| [`get_recent_changes`](#11-get-recent-changes) | `viewer` | Repositories & Architecture | `repo`, `filepath`, `symbol`, `limit` | Returns recent commits for a Git repository, optionally filtered by file path or AST symbol name. |
| [`sync_repository`](#12-sync-repository) | `editor` | Repositories & Architecture | `repo` | Triggers an immediate re-fetch and incremental re-indexing of a specific repository or all sources. |
| [`index_status`](#13-index-status) | `viewer` | Repositories & Architecture | *None* | Returns global vector counts, active vector backend, embedding models, and provider rate limits. |
| [`get_architecture`](#14-get-architecture) | `viewer` | Repositories & Architecture | `repo` | Synthesizes language distributions, entry points, core modules, route counts, and active ADRs. |
| [`manage_adr`](#15-manage-adr) | `editor` / `viewer` | Repositories & Architecture | `action`, `repo`, `id`, `title`, `status`, `context`, `decision`, `consequences` | Reads, lists, creates, updates, or supersedes Architectural Decision Records (MADR format). |
| [`what_is_ingested`](#16-what-is-ingested) | `viewer` | Storage & File Access | `source_type`, `repo_name`, `path_prefix`, `file_extension`, `detail_level` | Inspects all ingested Git repositories, monitored local paths, and uploaded local storage files. |
| [`manage_local_file`](#17-manage-local-file) | `editor` / `viewer` | Storage & File Access | `action`, `file_path`, `content`, `repo`, `category` | Uploads, replaces, reads, previews, or deletes files in managed local storage with immediate indexing. |
| [`read_file`](#18-read-file) | `viewer` | Storage & File Access | `path`, `repo`, `start_line`, `end_line` | Reads full file content or bounded 1-indexed line ranges from disk or reconstructed from vector chunks. |
| [`summarize_file`](#19-summarize-file) | `viewer` | Storage & File Access | `path`, `repo`, `force_refresh` | Retrieves a cached summary or generates a structured LLM executive summary for a large file. |

---

## Search, Retrieval & Forensic Triage Tools

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
- **Returns**: Compact JSON object containing the repository, file path, 1-indexed line span, qualified AST symbol (`Class.Method`), extracted signature, decomposed score breakdown (`score`, `dense_score`, `sparse_score`), clickable Git permalink, and code content.

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

### 3. `grep_code`
Performs deterministic literal string or regular expression matching across one or all indexed repositories, scanning both on-disk files and vector-reconstructed files from ephemeral repositories.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `pattern` (*string, required*): Exact substring or regular expression pattern to search for across repositories.
  - `repo` (*string, optional*): Repository identifier or storage namespace filter (searches all indexed sources when omitted).
  - `path_glob` (*string, optional*): Optional `fnmatch` file path glob filter (e.g. `"*.py"` or `"app/services/*"`).
  - `is_regex` (*boolean, default: false*): When `true`, compiles `pattern` as a regular expression; when `false`, performs literal substring matching.
  - `case_sensitive` (*boolean, default: false*): When `true`, performs case-sensitive matching.
  - `context_lines` (*integer, default: 2*): Number of surrounding context lines before and after each match (`0` to `10`).
  - `limit` (*integer, default: 30*): Maximum number of matched lines to return (`1` to `100`).
- **Returns**: Compact JSON object containing `pattern`, `total_matches`, `truncated`, and `matches` (each with `repo`, `file`, `line`, `content`, `context_before`, `context_after`, and enclosing `symbol`).

### 4. `diagnose_issue`
Forensic triage tool that accepts stack traces, error logs, or user bug reports and correlates them against indexed AST symbols, HTTP routes, error string literals, and semantic vector candidates.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `issue_text` (*string, required*): Raw stack trace, error log, user symptom report, or combination to triage.
  - `repo` (*string, optional*): Optional repository identifier to scope diagnostics and resolution.
  - `context_lines` (*integer, default: 5*): Number of surrounding code lines to include for resolved stack frames (`1` to `15`).
  - `limit` (*integer, default: 5*): Maximum number of semantic code candidate blocks to retrieve (`1` to `20`).
- **Returns**: Structured JSON payload containing `resolved_frames` (stack frames mapped to indexed files, line numbers, enclosing AST symbols, and code context), `matched_routes` (HTTP routes referenced in the error log), `matched_symbols`, `literal_matches` (exact error strings found in source code), and `semantic_candidates`.

---

## AST Symbols & Call Graph Tools

### 5. `find_symbol`
Performs deterministic sub-50ms symbol lookup from the relational `ast_symbols` index without vector search overhead.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `name` (*string, required*): Symbol identifier to find (e.g. `QdrantVectorStore` or `execute_hybrid_search`).
  - `repo` (*string, optional*): Repository alias filter.
  - `exact` (*boolean, default: true*): Perform exact matching when `true`, prefix/fuzzy matching when `false`.
  - `limit` (*integer, default: 10*): Maximum matches to return.
- **Returns**: Symbol declarations with qualified names, parameter signatures, 1-indexed starting and ending lines, and file paths.

### 6. `get_file_outline`
Returns the structural AST outline of a file without retrieving its full token body.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `filepath` (*string, required*): Relative file path (e.g. `app/services/search.py` or `repo_name://app/services/search.py`).
  - `repo` (*string, optional*): Repository identifier.
- **Returns**: Hierarchical list of classes, functions, methods, signatures, and line spans defined in the file.

### 7. `trace_path`
Deterministically traverses function call graphs, module imports, inheritance hierarchies, and cross-repository HTTP route boundaries using AST relationships (`ast_relationships`), `api_routes`, and `api_client_calls` via breadth-first search (BFS).

- **Minimum Role**: `viewer`
- **Parameters**:
  - `symbol` (*string, required*): Target function, method, or class name to trace.
  - `repo` (*string, optional*): Specific repository to trace within (searches across all repositories when omitted).
  - `direction` (*string, default: `"both"`*): Traversal direction: `"callers"` (inbound), `"callees"` (outbound), or `"both"`.
  - `depth` (*integer, default: 2*): Maximum BFS traversal hops (`1` to `5`).
  - `limit` (*integer, default: 25*): Maximum relationships returned.
- **Returns**: Directed call/import graph edges (`inbound`, `outbound`) with source files, target symbols, relationship types (`CALLS`, `IMPORTS`, `EXTENDS`), line numbers, and cross-repository HTTP links (`external_callers` for client calls invoking a route handler, and `external_handlers` for backend route handlers matching an outbound HTTP call).

---

## API Route Discovery Tools

### 8. `find_routes`
Lists or searches declared HTTP endpoints and route handlers across indexed backend frameworks.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `query` (*string, optional*): URL path substring or pattern (e.g. `"/api/v1/users"` or `"search"`).
  - `method` (*string, optional*): HTTP method filter (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`).
  - `repo` (*string, optional*): Repository alias filter.
  - `limit` (*integer, default: 20*): Maximum routes to return.
- **Returns**: Matched HTTP routes with framework name, HTTP method, normalized path template, handler symbol, file path, and line numbers.

### 9. `find_api_callers`
Finds client call sites and services that invoke a specific HTTP endpoint or URL pattern (`api_client_calls`).

- **Minimum Role**: `viewer`
- **Parameters**:
  - `path` (*string, required*): Endpoint path pattern or URL segment to match (e.g. `"/users/{id}"` or `"/admin/api/search/test"`).
  - `method` (*string, optional*): Target HTTP method (`GET`, `POST`, etc.).
  - `repo` (*string, optional*): Filter client search by repository.
- **Returns**: Matching client invocations with caller symbol, file path, HTTP method, and line number alongside matching backend route handlers.

---

## Repositories, Architecture & ADR Tools

### 10. `list_repositories`
Lists all registered Git repositories and monitored local filesystem paths.

- **Minimum Role**: `viewer`
- **Parameters**: None.
- **Returns**: Repository aliases, provider types (`github`, `gitlab`, `gitea`, `bitbucket`, `git`), active branches, latest indexed commit SHAs, sync status, and file counts.

### 11. `get_recent_changes`
Returns recent commit history for a registered Git repository from the `git_commits` table, optionally filtered by file path or AST symbol name.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `repo` (*string, required*): Repository name to inspect recent commits for.
  - `filepath` (*string, optional*): Relative file path filter to only return commits touching that file.
  - `symbol` (*string, optional*): AST symbol name; resolves the symbol's declaring file path and filters commits touching that file.
  - `limit` (*integer, default: 10*): Maximum commits to return (`1` to `50`).
- **Returns**: Compact JSON object containing `repo`, `retained_limit`, and `commits` (each with `sha`, `short_sha`, `author`, `date`, `message`, `files_changed`, and provider-aware `commit_url`).

### 12. `sync_repository`
Triggers an immediate synchronization and incremental re-indexing run for a registered Git repository or local path.

- **Minimum Role**: `editor`
- **Parameters**:
  - `repo` (*string, optional*): Repository alias to synchronize (synchronizes all enabled sources when omitted).
- **Returns**: Synchronization status and scope confirmation.

### 13. `index_status`
Returns global index health, vector collection statistics, active embedding models, and GitHub API rate limits.

- **Minimum Role**: `viewer`
- **Parameters**: None.
- **Returns**: Active vector store provider (`qdrant` or `pgvector`), total vector count, dense/sparse model names, and rate limit counters.

### 14. `get_architecture`
Synthesizes a high-level architectural overview of a repository or the entire indexed workspace.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `repo` (*string, optional*): Specific repository alias (returns a multi-repository overview when omitted).
- **Returns**: Language breakdown, detected entry points, primary directory modules, API route counts, and active Architectural Decision Records.

### 15. `manage_adr`
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

### 16. `what_is_ingested`
Inspects all ingested Git repositories, monitored local paths, and uploaded local storage files with multi-dimensional filtering.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `source_type` (*string, default: `"all"`*): Filter by `"all"`, `"git"`, `"monitored_path"`, or `"local_storage"`.
  - `repo_name` (*string, optional*): Filter by specific repository or storage namespace.
  - `path_prefix` (*string, optional*): Filter files matching a directory prefix.
  - `file_extension` (*string, optional*): Filter by extension (e.g. `".py"`, `".md"`).
  - `detail_level` (*string, default: `"summary"`*): `"summary"` (aggregate counts and statuses) or `"detailed"` (file-by-file inventory).
- **Returns**: Consolidated multi-source catalog inventory.

### 17. `manage_local_file`
Manages files inside the managed local storage directory (`LOCAL_STORAGE_PATH`) with real-time incremental indexing.

- **Minimum Role**: `viewer` for `read`; `editor` for `upload`, `replace`, `delete`.
- **Parameters**:
  - `action` (*string, required*): `"upload"`, `"replace"`, `"read"`, or `"delete"`.
  - `file_path` (*string, required*): Relative file path within local storage (path traversal tokens `..` are rejected).
  - `content` (*string, optional*): File text content for `upload` or `replace`.
  - `repo` (*string, default: `"local_storage"`*): Logical namespace alias.
  - `category` (*string, optional*): Optional document category tag.
- **Returns**: File operation status, byte size, and immediate vector/AST indexing confirmation.

### 18. `read_file`
Reads entire file contents or bounded 1-indexed line ranges from monitored local directories, persistent shallow repositories, managed local storage, or reconstructed directly from indexed vector chunks when an ephemeral repository is not stored on disk.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `path` (*string, required*): Relative or absolute file path within an indexed source.
  - `repo` (*string, optional*): Repository or storage namespace identifier.
  - `start_line` (*integer, optional*): 1-based starting line number (inclusive).
  - `end_line` (*integer, optional*): 1-based ending line number (inclusive).
- **Returns**: JSON object with `file`, `repo`, `source` (`local_storage`, `persistent_repo`, `monitored_path`, or `vector_store`), `lines`, `total_lines`, `size_bytes`, `truncated`, and `content`.

### 19. `summarize_file`
Retrieves a cached executive summary or generates a structured LLM summary for a large source or documentation file.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `path` (*string, required*): Path to the file to summarize.
  - `repo` (*string, optional*): Repository or storage namespace filter.
  - `force_refresh` (*boolean, default: false*): When `true`, bypasses the SQLite cache and generates a fresh summary via the configured chat model.
- **Returns**: Structured Markdown summary covering file purpose, exported symbols, dependencies, and architectural role.

---

## Bounded Payload & Pagination Conventions

All list- and search-oriented MCP tools enforce safe upper bounds and return standardized pagination metadata:
- **Inputs**: `limit` (or `top_k` / `max_results`, clamped per tool) and `offset` (0-based integer, default `0`).
- **Outputs**: `total` (or `total_matches` / `total_symbols` / `total_files`), `offset`, `limit`, `has_more` (`boolean`), and `next_offset` (`integer | null`).
- **Snippet & Line Caps**: `search_code` and `search_docs` accept `max_snippet_chars` (`200..6000`, default `2000`, marking `content_truncated: true` when clipped). `grep_code` caps individual matched/context lines at `400` characters (`...[line truncated]`). `read_file` returns `has_more` and `next_start_line` for chunked file reading.

---

## Dynamic Catalog Resources, Paginated Templates & Guided Prompts

### Dynamic Resources & Repository Resource Templates

| Resource URI / Template | MIME Type | Description |
| :--- | :--- | :--- |
| `knowledge://catalog/summary` | `application/json` | Compact global catalog (`≤ 40` sample files) listing repositories, status, language/symbol totals, and sub-resource templates. |
| `knowledge://repo/{repo}/summary` | `application/json` | Single-repository overview with commit SHA, sync status, language distribution, symbol/route/ADR counts, and sub-resource URIs. |
| `knowledge://repo/{repo}/architecture` | `application/json` | Synthesized entry points, hub symbols, directory breakdown, API surface summary, and active ADRs for `{repo}`. |
| `knowledge://repo/{repo}/files/{page}` | `application/json` | Paginated indexed file inventory (`100` files per 1-indexed `page`) with `total_files`, `total_pages`, `has_more`, and `next_uri`. |
| `knowledge://repo/{repo}/routes/{page}` | `application/json` | Paginated HTTP route table (`50` routes per 1-indexed `page`) with `total_routes`, `total_pages`, `has_more`, and `next_uri`. |
| `knowledge://repo/{repo}/adrs` | `application/json` | Architectural Decision Records (`ADR` id, title, status, date, filepath) registered for `{repo}`. |

### Guided Prompts

#### 1. `search_infrastructure_docs`
- **Arguments**: `topic` (*string*)
- **Description**: Guides an AI assistant to retrieve system architecture notes, container port mappings, and reverse proxy routes.

#### 2. `find_implementation_symbol`
- **Arguments**: `symbol` (*string*), `repo` (*string, optional*)
- **Description**: Guides an AI assistant to locate symbol declarations, parameter signatures, and call sites across registered codebases (including Python, TypeScript/JS/TSX, C#, and COBOL).

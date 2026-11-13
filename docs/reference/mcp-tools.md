# MCP Tools and Resources Reference

This document provides complete reference specifications for the **10 default Model Context Protocol (MCP) tools** (plus the gated `manage` write tool when `MCP_ENABLE_WRITE_TOOLS=true`), dynamic resources, and guided prompts exposed by ContextCortex (`app/mcp/tools.py`).

---

## MCP Tools Summary Matrix

| Tool Name | Minimum Role | Category | Primary Parameters | Description |
| :--- | :---: | :--- | :--- | :--- |
| [`search`](#1-search) | `viewer` | Search & Retrieval | `query`, `scope`, `repo`, `language`, `category`, `tag`, `limit`, `offset`, `dense_weight`, `mode`, `max_snippet_chars` | Hybrid semantic + BM25 search across AST code chunks (`scope='code'`), documentation (`scope='docs'`), or both (`scope='all'`). |
| [`grep_code`](#2-grep-code) | `viewer` | Search & Retrieval | `pattern`, `repo`, `path_glob`, `is_regex`, `case_sensitive`, `context_lines`, `limit`, `offset` | Deterministic literal and regex pattern matching across indexed repositories with context lines and AST symbol attribution. |
| [`diagnose_issue`](#3-diagnose-issue) | `viewer` | Forensic Triage | `issue_text`, `repo`, `context_lines`, `limit` | Forensic triage tool that parses stack traces, resolves AST frames, matches error literals and HTTP routes, and retrieves semantic code candidates. |
| [`find_symbol`](#4-find-symbol) | `viewer` | AST Symbols & Graphs | `name`, `repo`, `exact`, `limit`, `offset` | Sub-50ms exact or prefix lookup of AST symbols (functions, classes, methods, interfaces). |
| [`read_file`](#5-read-file) | `viewer` | Storage & File Access | `path`, `repo`, `start_line`, `end_line`, `outline_only`, `limit`, `offset` | Reads bounded 1-indexed line ranges or inspects AST symbol outlines (`outline_only=True`). |
| [`trace_path`](#6-trace-path) | `viewer` | AST Symbols & Graphs | `symbol`, `repo`, `direction`, `depth`, `limit`, `offset`, `include_permalinks` | Breadth-first traversal of function call graphs, imports, inheritance, and cross-repo HTTP boundaries (`external_callers`, `external_handlers`). |
| [`find_routes`](#7-find-routes) | `viewer` | API Route Discovery | `query`, `kind`, `method`, `repo`, `limit`, `offset` | Discovers backend HTTP route handlers (`kind='handlers'`), client call sites (`kind='callers'`), or both (`kind='both'`). |
| [`list_repositories`](#8-list-repositories) | `viewer` | Repositories & Architecture | `repo`, `source_type`, `path_prefix`, `file_extension`, `include_files`, `include_status`, `limit`, `offset` | Lists registered Git repos, local paths, and storage inventory, with optional paginated file lists or global index health. |
| [`get_architecture`](#9-get-architecture) | `viewer` | Repositories & Architecture | `repo` | Synthesizes language distributions, entry points, core modules, route counts, and active ADRs. |
| [`execute_script`](#10-execute-script) | `viewer` | Code Mode | `script`, `arguments` | Runs one sandboxed JavaScript script that chains several tool calls and returns only the final result. |
| [`manage`](#11-manage-gated) *(gated)* | `editor` / `viewer` | Admin & Storage | `action`, `repo`, `file_path`, `content`, `category` | Exposed when `MCP_ENABLE_WRITE_TOOLS=true`. Triggers `sync_repo` or performs local storage CRUD (`upload`, `replace`, `delete`, `read`, `preview`). |

---

## Search, Retrieval & Forensic Triage Tools

### 1. `search`
Performs calibrated hybrid semantic and BM25 lexical search across AST-chunked source code (`scope='code'`), Markdown documentation/ADRs/PDFs (`scope='docs'`), or both (`scope='all'`).

- **Minimum Role**: `viewer`
- **Parameters**:
  - `query` (*string, required*): Natural language question or exact identifier (e.g. `"JWT bearer validation"` or `"OrderProcessor.retry_payment"`).
  - `scope` (*string, default: `"all"`*): Retrieval scope: `"code"`, `"docs"`, or `"all"`.
  - `repo` (*string, optional*): Restrict results to a specific repository alias or `"local_storage"`.
  - `language` (*string, optional*): Filter code results by programming language (e.g. `python`, `typescript`, `csharp`, `go`).
  - `category` (*string, optional*): Document category filter (e.g. `architecture`, `runbook`, `notes`).
  - `tag` (*string, optional*): Frontmatter tag filter.
  - `mode` (*string, default: `"hybrid"`*): Search mode: `"hybrid"`, `"semantic"` (`"vector"`), or `"lexical"` (`"keyword"`, `"bm25"`, `"fts"`).
  - `dense_weight` (*float, optional*): Hybrid weight between `0.0` (pure lexical BM25) and `1.0` (pure semantic vector). Defaults to `0.5` balanced.
  - `limit` (*integer, default: 5*): Maximum chunks per page, clamped `1..25`.
  - `offset` (*integer, default: 0*): 0-based result offset for pagination.
  - `max_snippet_chars` (*integer, default: 2000*): Maximum characters per snippet, clamped `200..6000`.
- **Returns**: Compact JSON object containing `repo`, `file`, `doc_type`, `lines`, `symbol`, `signature`, `heading`, decomposed scores (`score`, `dense_score`, `sparse_score`), clickable Git permalink, and snippet content.

### 2. `grep_code`
Performs deterministic literal string or regular expression matching across one or all indexed repositories, using an in-process ripgrep fast path when all target repositories exist on disk and falling back to vector chunks for ephemeral repositories.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `pattern` (*string, required*): Exact substring or regular expression pattern to search for across repositories.
  - `repo` (*string, optional*): Repository identifier or storage namespace filter (searches all indexed sources when omitted).
  - `path_glob` (*string, optional*): Optional `fnmatch` file path glob (e.g. `"*.py"`) or literal path substring (alias `path`).
  - `is_regex` (*boolean, default: false*): When `true`, compiles `pattern` as a regular expression; when `false`, performs literal substring matching.
  - `case_sensitive` (*boolean, default: false*): When `true`, performs case-sensitive matching.
  - `context_lines` (*integer, default: 2*): Number of surrounding context lines before and after each match (`0` to `10`).
  - `limit` (*integer, default: 30*): Maximum number of matched lines to return (`1` to `100`).
  - `offset` (*integer, default: 0*): 0-based match offset for pagination.
- **Returns**: Compact JSON object containing `pattern`, `pattern_mode`, `total_matches`, `has_more`, `next_offset`, and `matches` (each with `repo`, `file`, `line`, `match_text`, `context`, and enclosing `symbol`).

### 3. `diagnose_issue`
Forensic triage tool that accepts stack traces, error logs, or user bug reports and correlates them against indexed AST symbols, HTTP routes, error string literals, and semantic vector candidates.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `issue_text` (*string, required*): Raw stack trace, error log, user symptom report, or combination to triage.
  - `repo` (*string, optional*): Optional repository identifier to scope diagnostics and resolution.
  - `context_lines` (*integer, default: 5*): Number of surrounding code lines to include for resolved stack frames (`1` to `15`).
  - `limit` (*integer, default: 5*): Maximum number of semantic code candidate blocks to retrieve (`1` to `20`).
- **Returns**: Structured JSON payload containing `resolved_frames`, `matched_routes`, `matched_symbols`, `literal_matches`, and `semantic_candidates`.

---

## AST Symbols & Call Graph Tools

### 4. `find_symbol`
Performs deterministic sub-50ms symbol lookup from the relational `ast_symbols` index without vector search overhead.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `name` (*string, required*): Symbol identifier to find (e.g. `QdrantVectorStore` or `execute_hybrid_search`).
  - `repo` (*string, optional*): Repository alias filter.
  - `exact` (*boolean, default: true*): Perform exact matching when `true`, prefix/fuzzy matching when `false`.
  - `limit` (*integer, default: 30*): Maximum matches to return (`1..100`).
  - `offset` (*integer, default: 0*): 0-based offset for pagination.
- **Returns**: Symbol declarations with qualified names, parameter signatures, 1-indexed starting and ending lines, and file paths.

### 5. `read_file`
Reads bounded 1-indexed line slices from monitored local directories, persistent shallow clones, managed local storage, or reconstructed vector chunks — or returns the file's deduplicated AST symbol outline when `outline_only=True`.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `path` (*string, required*): Relative or absolute file path within an indexed source.
  - `repo` (*string, optional*): Repository or storage namespace identifier.
  - `start_line` (*integer, optional*): 1-based starting line number (inclusive, when `outline_only=False`).
  - `end_line` (*integer, optional*): 1-based ending line number (inclusive, window `<= 2000` lines).
  - `outline_only` (*boolean, default: false*): When `true`, returns the AST outline (classes, methods, functions, signatures, line ranges) instead of source text.
  - `limit` (*integer, default: 150*): Maximum AST symbols returned per page when `outline_only=True` (`1..500`).
  - `offset` (*integer, default: 0*): 0-based AST symbol offset when `outline_only=True`.
- **Returns**: In read mode: `file`, `repo`, `source`, `lines`, `total_lines`, `has_more`, `next_start_line`, `size_bytes`, `truncated`, and `content`. In outline mode: `file`, `repo`, `outline_only: true`, `total_symbols`, `has_more`, `next_offset`, and `symbols`.

### 6. `trace_path`
Deterministically traverses function call graphs, module imports, inheritance hierarchies, and cross-repository HTTP route boundaries using AST relationships (`ast_relationships`), `api_routes`, and `api_client_calls` via breadth-first search (BFS).

- **Minimum Role**: `viewer`
- **Parameters**:
  - `symbol` (*string, required*): Target function, method, or class name to trace.
  - `repo` (*string, optional*): Specific repository to trace within (searches across all repositories when omitted).
  - `direction` (*string, default: `"both"`*): Traversal direction: `"callers"`, `"callees"`, or `"both"`.
  - `depth` (*integer, default: 2*): Maximum BFS traversal hops (`1` to `5`).
  - `limit` (*integer, default: 50*): Maximum relationships returned (`1` to `200`).
  - `offset` (*integer, default: 0*): 0-based pagination offset.
  - `include_permalinks` (*boolean, default: false*): Include Git permalinks on neighbor nodes (target always includes its permalink).
- **Returns**: Directed call/import graph edges (`callers`, `callees`) alongside cross-repository HTTP links (`external_callers`, `external_handlers`).

---

## API Route Discovery (`find_routes`)

### 7. `find_routes`
Discovers declared backend HTTP route handlers (`kind='handlers'`), frontend/microservice client call sites (`kind='callers'`), or both (`kind='both'`, default).

- **Minimum Role**: `viewer`
- **Parameters**:
  - `query` (*string, optional*): Route URL path pattern, endpoint substring, or handler keyword (e.g. `"/api/v1/users/{id}"` or `"search"`).
  - `kind` (*string, default: `"both"`*): `"handlers"`, `"callers"`, or `"both"`.
  - `method` (*string, optional*): HTTP method filter (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`).
  - `repo` (*string, optional*): Repository alias filter.
  - `limit` (*integer, default: 50*): Maximum items per page (`1..200`).
  - `offset` (*integer, default: 0*): 0-based pagination offset.
- **Returns**: Matched `routes` (for `handlers`/`both`) and `callers` (for `callers`/`both`) with route specificity enforcement so each client call maps only to its most specific route.

---

## Repositories, Architecture & Administration

### 8. `list_repositories`
Lists registered Git repositories, monitored local paths, and managed local storage inventory, optionally including paginated file paths (`include_files=True`) or vector store / embedding / Git auth health status (`include_status=True`).

- **Minimum Role**: `viewer`
- **Parameters**:
  - `repo` (*string, optional*): Filter by specific repository or storage namespace.
  - `source_type` (*string, default: `"all"`*): `"all"`, `"git"`, `"monitored_path"`, or `"local_storage"`.
  - `path_prefix` (*string, optional*): Filter file paths matching a directory prefix when `include_files=True`.
  - `file_extension` (*string, optional*): Filter file paths by extension when `include_files=True` (e.g. `".py"`, `".md"`).
  - `include_files` (*boolean, default: false*): Include paginated file inventory per source and at top level.
  - `include_status` (*boolean, default: false*): Include global vector store health, point counts, active embedding models, and masked Git auth status.
  - `limit` (*integer, default: 100*): Maximum files returned per page when `include_files=True` (`1..500`).
  - `offset` (*integer, default: 0*): 0-based file offset when `include_files=True`.
- **Returns**: Consolidated repository inventory with optional paginated `files` and `vector_store` / `embeddings` / `counts` health fields.

### 9. `get_architecture`
Synthesizes a high-level architectural overview of a repository or the entire indexed workspace.

- **Minimum Role**: `viewer`
- **Parameters**:
  - `repo` (*string, optional*): Specific repository alias (returns a multi-repository overview when omitted).
- **Returns**: Language breakdown, detected entry points, primary directory modules, hub symbols, API route counts, and active Architectural Decision Records.

---

### 10. `execute_script`
Code Mode. Runs one async JavaScript body that calls other ContextCortex tools and returns only the final result. Use it when a question needs several dependent calls (for example: find a route, trace its handler, read each callee). The design is the same as Code Mode (`execute_script`) in model-context-gateway, so a script also runs there unchanged.

- **Minimum Role**: `viewer`. Each tool call in the script goes through the normal handler and its own role check.
- **Parameters**:
  - `script` (*string, required*; alias `code`): async JavaScript body. Top-level `await` and `return` work.
  - `arguments` (*object, optional*; alias `args`): input object, available in the script as `args` and `arguments`.
- **In the script**:
  - `await tools.<tool>(args)` or `await cc.callTool("<tool>", args)` calls a tool. `tools.contextcortex.<tool>(args)` and `mcg.callTool(...)` also work.
  - Tool results are parsed JSON. A tool error (an unknown tool or argument, or a result with an `error` field) throws an `Error`; catch it with `try`/`catch`.
  - `console.log`, `console.warn`, and `console.error` add entries to `logs` (at most `100`).
  - The script cannot call `execute_script`, and it has no file, network, or process access.
- **Limits** (environment settings): `CODE_MODE_TIMEOUT_SECONDS` (`30`, `1..300`), `CODE_MODE_MAX_TOOL_CALLS` (`50`, `1..500`), `CODE_MODE_MAX_MEMORY_MB` (`64`, `8..512`). `CODE_MODE_ENABLED=false` turns Code Mode off. Scripts are at most `50,000` characters; results larger than `100,000` characters are cut and marked `truncated`.
- **Returns**: `{"result", "logs", "executionTimeMs", "toolCallsCount"}`. On a failure: `{"error": "script_failed", "message", "logs", "executionTimeMs", "toolCallsCount"}`. Line numbers in error messages count from the first line of the script.
- **Types**: read the resource `contextcortex://code-mode/sdk.d.ts` for one typed function per tool.

```javascript
// Which classes call each repository method that a route handler reaches?
const routes = await tools.find_routes({ query: args.route, kind: "handlers", repo: args.repo });
const handler = routes.routes[0].handler;
const down = await tools.trace_path({ symbol: handler, repo: args.repo, direction: "callees", depth: 3 });
const repoCalls = down.callees.flatMap(function walk(n) { return [n, ...(n.callees || []).flatMap(walk)]; })
  .filter(n => n.symbol.includes("Repository."));
const out = {};
for (const c of repoCalls.slice(0, 10)) {
  const up = await tools.trace_path({ symbol: c.symbol, repo: args.repo, direction: "callers", depth: 1 });
  out[c.symbol] = up.callers.map(x => x.symbol);
}
return { handler, repositoryCallers: out };
```

---

### 11. `manage` *(Gated)*
Registered only when `MCP_ENABLE_WRITE_TOOLS=true` (disabled by default so the default tool surface remains 10 read/search/code-mode tools). Triggers background repository synchronization or performs local storage CRUD with real-time incremental indexing.

- **Minimum Role**: `editor` for `sync_repo`, `upload`, `replace`, `delete`; `viewer` for `read`, `preview`.
- **Parameters**:
  - `action` (*string, required*): `"sync_repo"`, `"upload"`, `"replace"`, `"delete"`, `"read"`, or `"preview"`.
  - `repo` (*string, optional*): Repository alias (for `sync_repo`) or local storage namespace (default `"local_storage"`).
  - `file_path` (*string, optional*): Relative file path within local storage (required for file actions; `..` traversal is rejected).
  - `content` (*string, optional*): UTF-8 file text content for `upload` or `replace`.
  - `category` (*string, optional*): Optional document category tag for `upload` or `replace`.
- **Returns**: Sync trigger status or local storage operation confirmation / preview payload.

---

## Bounded Payload & Pagination Conventions

All list- and search-oriented MCP tools enforce safe upper bounds and return standardized pagination metadata:
- **Inputs**: `limit` (clamped per tool) and `offset` (0-based integer, default `0`).
- **Outputs**: `total` (or `total_matches` / `total_symbols` / `total_files`), `offset`, `limit`, `has_more` (`boolean`), and `next_offset` (`integer | null`).
- **Snippet & Line Caps**: `search` accepts `max_snippet_chars` (`200..6000`, default `2000`, marking `content_truncated: true` when clipped). `grep_code` caps individual matched/context lines at `400` characters (`...[line truncated]`). `read_file` returns `has_more` and `next_start_line` for chunked file reading, and `total_symbols`/`has_more`/`next_offset` when `outline_only=True`.

---

## Dynamic Catalog Resources, Paginated Templates & Guided Prompts

### Dynamic Resources & Repository Resource Templates

| Resource URI / Template | MIME Type | Description |
| :--- | :--- | :--- |
| `contextcortex://code-mode/sdk.d.ts` | `text/plain` | TypeScript declarations of every tool that an `execute_script` script can call. |
| `knowledge://catalog/summary` | `application/json` | Compact global catalog (`<= 40` sample files) listing repositories, status, language/symbol totals, and sub-resource templates. |
| `knowledge://repo/{repo}/summary` | `application/json` | Single-repository overview with commit SHA, sync status, language distribution, symbol/route/ADR counts, and sub-resource URIs. |
| `knowledge://repo/{repo}/architecture` | `application/json` | Synthesized entry points, hub symbols, directory breakdown, API surface summary, and active ADRs for `{repo}`. |
| `knowledge://repo/{repo}/files/{page}` | `application/json` | Paginated indexed file inventory (`100` files per 1-indexed `page`) with `total_files`, `total_pages`, `has_more`, and `next_uri`. |
| `knowledge://repo/{repo}/routes/{page}` | `application/json` | Paginated HTTP route table (`50` routes per 1-indexed `page`) with `total_routes`, `total_pages`, `has_more`, and `next_uri`. |
| `knowledge://repo/{repo}/adrs` | `application/json` | Architectural Decision Records (`ADR` id, title, status, date, filepath) registered for `{repo}`. |

### Guided Prompts

#### 1. `search_infrastructure_docs`
- **Arguments**: `topic` (*string*)
- **Description**: Guides an AI assistant to run `search(scope='docs')`, check `knowledge://repo/{repo}/adrs`, and slice exact lines with `read_file`.

#### 2. `find_implementation_symbol`
- **Arguments**: `symbol` (*string*), `repo` (*string, optional*)
- **Description**: Guides an AI assistant to locate symbol declarations (`find_symbol`), inspect outlines (`read_file(..., outline_only=True)`), slice source (`read_file`), and trace dependencies (`trace_path`).

#### 3. `onboard_repository`
- **Arguments**: `repo` (*string*)
- **Description**: Guides an AI assistant through `get_architecture`, `find_routes(kind='handlers')`, and `read_file(..., outline_only=True)`.

#### 4. `triage_error`
- **Arguments**: `issue_text` (*string*), `repo` (*string, optional*)
- **Description**: Guides forensic triage through `diagnose_issue`, `trace_path`, and `read_file`.

#### 5. `investigate_change_impact`
- **Arguments**: `symbol` (*string*), `repo` (*string, optional*)
- **Description**: Evaluates change blast radius with `find_symbol`, `trace_path(direction='callers')`, `find_routes(kind='callers')`, and `grep_code`.

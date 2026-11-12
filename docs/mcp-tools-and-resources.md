# MCP Tools, Resources, and Pagination Reference

ContextCortex exposes 19 MCP tools, 1 catalog resource, 5 repository resource templates, and 5 guided workflow prompts over SSE (`/sse`) and Streamable HTTP (`/mcp`). Every response emits bounded, deterministic JSON to protect AI agent context windows.

---

## Supported Languages and Source Types

ContextCortex extracts AST symbols, call relationships, HTTP routes, and semantic chunks across:

- **Primary AST & Code Languages**: Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++.
- **Documentation & Configuration**: Markdown (`.md`), Architecture Decision Records (MADR / Nygard), PDFs (with optional Vision OCR), SQL, YAML, TOML, and JSON.
- **Ingested Source Types**: Remote Git repositories (`git_repositories`), monitored local directories (`indexed_paths`), and managed local file storage (`local_storage`).

---

## Pagination Conventions

ContextCortex enforces strict upper bounds on every multi-item tool and resource response. Clients never receive unbounded multi-thousand-line payloads in a single call.

### Offset-Based Tool Pagination

List and search tools accept `limit` (or `top_k` / `max_results`) and `offset` (0-based integer, default `0`). Responses include standard pagination fields:

| Response Key | Type | Description |
| :--- | :--- | :--- |
| `total` / `total_files` / `total_symbols` | `int` | Total matching items available across all pages. |
| `offset` | `int` | Applied 0-based starting index (`>= 0`). |
| `limit` | `int` | Clamped page size applied to the current response. |
| `has_more` | `bool` | `true` when additional items exist beyond `offset + limit`. |
| `next_offset` | `int \| null` | Exact `offset` value for the next call when `has_more` is `true`; otherwise `null`. |

### Line-Window File Pagination

`read_file` uses 1-based inclusive line ranges (`start_line` and `end_line`, capped at `<= 2000` lines per call). Responses return `total_lines`, `start_line`, `end_line`, `has_more`, and `next_start_line`. Pass `start_line=next_start_line` to read the next window.

### Page-Indexed Resource Templates

Paginated MCP resource templates (`files/{page}` and `routes/{page}`) use 1-indexed page numbers in the URI. Responses return `page`, `page_size`, `total_pages`, `has_more`, and `next_uri`. Read `next_uri` directly when `has_more` is `true`.

---

## MCP Tools Reference

### Summary Matrix (19 Tools)

| Tool | Role | Default / Clamped Bounds | Pagination Keys |
| :--- | :---: | :--- | :--- |
| `search_code` | `viewer` | `top_k`/`limit`: `5` (`1..25`), `max_snippet_chars`: `2000` (`200..6000`) | `offset`, `total`, `has_more`, `next_offset` |
| `search_docs` | `viewer` | `top_k`/`limit`: `5` (`1..25`), `max_snippet_chars`: `2000` (`200..6000`) | `offset`, `total`, `has_more`, `next_offset` |
| `find_symbol` | `viewer` | `limit`: `30` (`1..100`) | `offset`, `total`, `has_more`, `next_offset` |
| `get_file_outline` | `viewer` | `limit`: `150` (`1..500`) | `offset`, `total_symbols`, `has_more`, `next_offset` |
| `trace_path` | `viewer` | `depth`: `2` (`1..5`), `limit`: `50` (`1..200`), `include_permalinks`: `False` | `offset`, `total_callers`, `total_callees`, `has_more`, `next_offset` |
| `find_routes` | `viewer` | `limit`: `50` (`1..200`) | `offset`, `total`, `has_more`, `next_offset` |
| `find_api_callers` | `viewer` | `limit`: `50` (`1..200`) | `offset`, `total`, `has_more`, `next_offset` |
| `grep_code` | `viewer` | `max_results`/`limit`: `30` (`1..100`), `context_lines`: `2` (`0..10`), line `<= 400` chars | `offset`, `total_matches`, `has_more`, `next_offset` |
| `read_file` | `viewer` | `start_line` `>= 1`, window `<= 2000` lines | `total_lines`, `start_line`, `end_line`, `has_more`, `next_start_line` |
| `summarize_file` | `viewer` | Cached or fresh executive summary | Bounded executive summary text |
| `what_is_ingested` | `viewer` | `limit`: `100` (`1..500`) when `include_files=True` | Per-source & top-level `total_files`, `offset`, `limit`, `has_more`, `next_offset` |
| `get_recent_changes` | `viewer` | `limit`: `10` (`1..50`), `<= 25` `files_changed` per commit | `offset`, `total`, `has_more`, `next_offset`, `files_changed_truncated` |
| `manage_adr` | `viewer`/`editor` | `limit`: `25` (`1..100`) on `list`/`search` | `offset`, `total`, `has_more`, `next_offset` |
| `manage_local_file` | `viewer`/`editor` | Preview capped at `1000` chars | Single-file CRUD and preview |
| `diagnose_issue` | `viewer` | `context_lines`: `5` (`1..15`), `limit`: `5` (`1..20`) | Bounded stack frames & semantic candidates |
| `get_architecture` | `viewer` | Synthesized `< 4000` char overview | Compact per-repo or global summary |
| `list_repositories` | `viewer` | Registered repos & monitored paths | Compact repository metadata list |
| `sync_repository` | `editor` | Asynchronous background job | Immediate trigger confirmation |
| `index_status` | `viewer` | Global health & vector metrics | Single status payload |

---

### Hybrid Search Tools

- **`search_code`**: Runs hybrid dense + BM25 code search across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++. Supports `mode` (`hybrid`, `semantic`, `lexical`/`keyword`/`bm25`), `repo`, `language`, `dense_weight` (`0.0..1.0`), `top_k`/`limit` (`1..25`, default `5`), `offset` (`>= 0`), and `max_snippet_chars` (`200..6000`, default `2000`). Snippets exceeding `max_snippet_chars` end with `...[snippet truncated]` and set `content_truncated: true`.
- **`search_docs`**: Runs hybrid dense + BM25 search over Markdown notes, runbooks, ADRs, and PDFs. Supports `repo`, `category`, `tag`, `mode`, `top_k`/`limit` (`1..25`, default `5`), `offset` (`>= 0`), and `max_snippet_chars` (`200..6000`, default `2000`).

### AST Symbol and Call Graph Tools

- **`find_symbol`**: Queries `ast_symbols` directly by `name` (`exact=True` or substring `exact=False`) and optional `repo`. Clamps `limit` to `1..100` (default `30`) with `offset` pagination. Use this tool first when you know an identifier name.
- **`get_file_outline`**: Returns deduplicated classes, methods, functions, signatures, and `[start_line, end_line]` spans for `filepath`. Clamps `limit` to `1..500` (default `150`) with `offset` pagination (`total_symbols`, `has_more`, `next_offset`).
- **`trace_path`**: Traverses AST `callers`, `callees`, or `both` via BFS (`depth` clamped `1..5`, default `2`) and resolves cross-repository HTTP route/caller boundaries (`external_callers`, `external_handlers`). Clamps `limit` to `1..200` (default `50`) with `offset`, returning `total_callers`, `total_callees`, `has_more`, and `next_offset`. Caller/callee nodes omit their Git permalinks unless `include_permalinks=True` (the target always keeps its permalink), which keeps deep traces compact.

### HTTP Route and Client Discovery Tools

- **`find_routes`**: Searches declared backend endpoints (`api_routes`) by `query`, `method`, and `repo` while excluding unit test fixtures. Clamps `limit` to `1..200` (default `50`) with `offset`.
- **`find_api_callers`**: Matches frontend and service HTTP client calls (`api_client_calls`) against `path` (including `{id}` / `:id` parameter templates), `method`, and `repo`. Client calls are recognized for `fetch`, `axios`, Python `requests`/`httpx`, Go `http`, C# `HttpClient`, and JS/TS request helpers whose name suggests HTTP (for example ``getJson(`/api/items/${id}`)`` or `apiClient.post('/api/items', ...)`); the method comes from the helper name or a `method:` option. Clamps `limit` to `1..200` (default `50`) with `offset`.

### File Inspection and Pattern Matching Tools

- **`read_file`**: Reads `path` from watched directories, persistent shallow clones, local storage, or reconstructed vector chunks. Accepts `start_line` (`>= 1`) and `end_line` (`<= 2000` lines per call). Always returns `total_lines`, `start_line`, `end_line`, `has_more`, and `next_start_line`.
- **`summarize_file`**: Returns a cached LLM executive summary for `path` or regenerates one when `force_refresh=True`.
- **`grep_code`**: Matches literal strings or regular expressions (`is_regex=True`) across disk and vector-backed repositories. Supports `repo`, `path_glob`, `case_sensitive`, `context_lines` (`0..10`, default `2`), `max_results`/`limit` (`1..100`, default `30`), and `offset`. Truncates any matched or context line `> 400` characters with `...[line truncated]`.

### Repository, Architecture, and ADR Tools

- **`list_repositories`**: Lists all registered Git repositories and monitored local paths with commit SHAs, sync status, and indexed file counts.
- **`get_recent_changes`**: Returns retained commits for `repo`, optionally filtered by `filepath` or AST `symbol`. Clamps `limit` to `1..50` (default `10`) with `offset`. Caps `files_changed` per commit at `25` entries and includes `files_changed_total` and `files_changed_truncated`.
- **`sync_repository`**: Triggers an immediate background sync for `repo` or all registered sources (`editor` role required).
- **`index_status`**: Reports vector database provider/mode, point totals, active dense/sparse models, and masked Git auth status.
- **`get_architecture`**: Synthesizes language distribution, package manifests, entry points, primary modules, hub symbols, route totals, and active ADRs.
- **`manage_adr`**: Supports `list`, `search`, `get` (`viewer` role) and `create`, `update`, `supersede` (`editor` role). `list` and `search` accept `query`, `status`, `limit` (`1..100`, default `25`), and `offset`.

### Storage, Catalog, and Forensic Triage Tools

- **`manage_local_file`**: Supports `upload`, `replace`, `delete` (`editor` role) and `read`, `preview` (`viewer` role) inside `LOCAL_STORAGE_PATH` with immediate vector and AST indexing.
- **`what_is_ingested`**: Inspects `all`, `git`, `monitored_path`, or `local_storage` sources. Set `include_files=True` (or `detail_level='detailed'`) with `limit` (`1..500`, default `100`) and `offset` (`>= 0`) to paginate file paths per source (`total_files`, `offset`, `limit`, `has_more`, `next_offset`) without dumping thousands of paths.
- **`diagnose_issue`**: Resolves stack traces, error string literals, HTTP routes, and semantic code candidates across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++. Clamps `context_lines` (`1..15`, default `5`) and `limit` (`1..20`, default `5`).

---

## MCP Resources and Templates

ContextCortex splits repository metadata into granular, bounded JSON resources (`application/json`) so MCP clients only fetch the slices they need.

| Resource URI / Template | Page Size | Key Response Fields | Purpose |
| :--- | :---: | :--- | :--- |
| `knowledge://catalog/summary` | Sample `<= 40` | `total_files`, `total_symbols`, `git_repositories`, `resource_templates` | Compact global catalog and discovery index for per-repo URIs. |
| `knowledge://repo/{repo}/summary` | Single | `status`, `commit_sha`, `file_count`, `languages`, `symbol_count`, `route_count`, `adr_count`, `sub_resources` | Lightweight per-repository health, counts, and sub-resource links. |
| `knowledge://repo/{repo}/architecture` | Single | `languages`, `manifests`, `entry_points`, `modules`, `hub_symbols`, `routes_count`, `active_adrs` | Synthesized repository architecture overview. |
| `knowledge://repo/{repo}/files/{page}` | `100` / page | `page`, `total_files`, `total_pages`, `has_more`, `next_uri`, `files` | 1-indexed paginated file inventory for `{repo}`. |
| `knowledge://repo/{repo}/routes/{page}` | `50` / page | `page`, `total_routes`, `total_pages`, `has_more`, `next_uri`, `routes` | 1-indexed paginated HTTP/API route list for `{repo}`. |
| `knowledge://repo/{repo}/adrs` | Bounded | `repo`, `total_adrs`, `adrs` | Architecture Decision Records registered for `{repo}`. |

---

## MCP Workflow Prompts

| Prompt Name | Arguments | Guided Tool Sequence |
| :--- | :--- | :--- |
| `search_infrastructure_docs` | `topic` | `search_docs` -> `manage_adr(action='search')` -> `read_file` |
| `find_implementation_symbol` | `symbol`, `repo` (opt) | `find_symbol` -> `read_file` -> `trace_path` |
| `onboard_repository` | `repo` | `get_architecture` -> `find_routes` -> `get_file_outline` -> `get_recent_changes` |
| `triage_error` | `issue_text`, `repo` (opt) | `diagnose_issue` -> `trace_path` -> `read_file` -> `get_recent_changes` |
| `investigate_change_impact` | `symbol`, `repo` (opt) | `find_symbol` -> `trace_path(direction='callers')` -> `find_api_callers` -> `grep_code` |

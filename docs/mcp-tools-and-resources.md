# MCP Tools, Resources, and Pagination Reference

ContextCortex exposes **10 default MCP tools** (plus the gated `manage` write tool when `MCP_ENABLE_WRITE_TOOLS=true`), **2 resources** (the catalog and the Code Mode SDK types), **5 repository resource templates**, and **5 guided workflow prompts** over SSE (`/sse`) and Streamable HTTP (`/mcp`). Every response emits bounded, deterministic JSON to protect AI agent context windows.

---

## Supported Languages and Source Types

ContextCortex extracts AST symbols, call relationships, HTTP routes, and semantic chunks across:

- **Primary AST & Code Languages**: Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++.
- **Documentation & Configuration**: Markdown (`.md`), Architecture Decision Records (MADR / Nygard), PDFs (with optional Vision OCR), SQL, YAML, TOML, and JSON.
- **Ingested Source Types**: Remote Git repositories (`git_repositories`), monitored local directories (`indexed_paths`), and managed local file storage (`local_storage`).
- **File Paths in Tool Output**: `find_symbol`, `trace_path`, `find_routes`, `search`, `read_file(..., outline_only=True)`, and `diagnose_issue` give each file as a path relative to the root of its source (for example `server/Controllers/ToolsController.cs`), for Git repositories and for monitored local directories. This is the same form that `read_file` and `grep_code` accept with the `repo` argument. The index keeps absolute disk paths for local directories; the tools remove the `indexed_paths` root when they make the output, so no re-index is necessary.

---

## Pagination Conventions

ContextCortex enforces strict upper bounds on every multi-item tool and resource response. Clients never receive unbounded multi-thousand-line payloads in a single call.

### Offset-Based Tool Pagination

List and search tools accept `limit` and `offset` (0-based integer, default `0`). Responses include standard pagination fields:

| Response Key | Type | Description |
| :--- | :--- | :--- |
| `total` / `total_files` / `total_symbols` | `int` | Total matching items available across all pages. |
| `offset` | `int` | Applied 0-based starting index (`>= 0`). |
| `limit` | `int` | Clamped page size applied to the current response. |
| `has_more` | `bool` | `true` when additional items exist beyond `offset + limit`. |
| `next_offset` | `int \| null` | Exact `offset` value for the next call when `has_more` is `true`; otherwise `null`. |

### Line-Window File Pagination

`read_file` (when `outline_only=False`) uses 1-based inclusive line ranges (`start_line` and `end_line`, capped at `<= 2000` lines per call). Responses return `total_lines`, `start_line`, `end_line`, `has_more`, and `next_start_line`. Pass `start_line=next_start_line` to read the next window. When `outline_only=True`, `read_file` uses `limit` (`1..500`, default `150`) and `offset` (`total_symbols`, `has_more`, `next_offset`).

### Page-Indexed Resource Templates

Paginated MCP resource templates (`files/{page}` and `routes/{page}`) use 1-indexed page numbers in the URI. Responses return `page`, `page_size`, `total_pages`, `has_more`, and `next_uri`. Read `next_uri` directly when `has_more` is `true`.

---

## MCP Tools Reference

### Summary Matrix (10 Default Tools + 1 Gated Write Tool)

| Tool | Role | Default / Clamped Bounds | Pagination Keys |
| :--- | :---: | :--- | :--- |
| `diagnose_issue` | `viewer` | `context_lines`: `5` (`1..15`), `limit`: `5` (`1..20`) | Bounded stack frames & semantic candidates |
| `execute_script` | `viewer` | One sandboxed script (`30` s, `50` tool calls, `64` MB) | The value the script returns (`< 100,000` chars) |
| `find_routes` | `viewer` | `kind`: `both`\|`handlers`\|`callers`; `limit`: `50` (`1..200`) | `offset`, `total` / `total_routes` / `total_callers`, `has_more`, `next_offset` |
| `find_symbol` | `viewer` | `limit`: `30` (`1..100`) | `offset`, `total`, `has_more`, `next_offset` |
| `get_architecture` | `viewer` | Synthesized `< 4000` char overview | Compact per-repo or global summary |
| `grep_code` | `viewer` | `limit`: `30` (`1..100`), `context_lines`: `2` (`0..10`), line `<= 400` chars | `offset`, `total_matches`, `has_more`, `next_offset` |
| `list_repositories` | `viewer` | `limit`: `100` (`1..500`) when `include_files=True`; `include_status=True` adds global health | Per-source & top-level `total_files`, `offset`, `limit`, `has_more`, `next_offset` |
| `read_file` | `viewer` | `start_line` `>= 1`, window `<= 2000` lines; `outline_only=True`: `limit` `150` (`1..500`) | `total_lines`, `has_more`, `next_start_line` (or `total_symbols`, `next_offset`) |
| `search` | `viewer` | `scope`: `all`\|`code`\|`docs`; `limit`: `5` (`1..25`), `max_snippet_chars`: `2000` (`200..6000`) | `offset`, `total`, `has_more`, `next_offset` |
| `trace_path` | `viewer` | `depth`: `2` (`1..5`), `limit`: `50` (`1..200`), `include_permalinks`: `False` | `offset`, `total_callers`, `total_callees`, `has_more`, `next_offset` |
| `manage` *(requires `MCP_ENABLE_WRITE_TOOLS=true`)* | `viewer`/`editor` | `action`: `sync_repo`\|`upload`\|`replace`\|`delete`\|`read`\|`preview`; preview capped at `1000` chars | Single sync trigger or file operation status |

---

### Hybrid Search (`search`)

- **`search`**: Runs calibrated hybrid dense + BM25 search across AST-chunked code (`scope='code'`), Markdown notes/runbooks/ADRs/PDFs (`scope='docs'`), or both (`scope='all'`, default). Supports `mode` (`hybrid`, `semantic`, `lexical`/`keyword`/`bm25`), `repo`, `language`, `category`, `tag`, `dense_weight` (`0.0..1.0`), `limit` (`1..25`, default `5`), `offset` (`>= 0`), and `max_snippet_chars` (`200..6000`, default `2000`). Snippets exceeding `max_snippet_chars` end with `...[snippet truncated]` and set `content_truncated: true`.

### AST Symbol and Call Graph Tools

- **`find_symbol`**: Queries `ast_symbols` directly by `name` (`exact=True` or substring `exact=False`) and optional `repo`. Clamps `limit` to `1..100` (default `30`) with `offset` pagination. Use this tool first when you know an identifier name.
- **`trace_path`**: Traverses AST `callers`, `callees`, or `both` via BFS (`depth` clamped `1..5`, default `2`) and resolves cross-repository HTTP route/caller boundaries (`external_callers`, `external_handlers`). Clamps `limit` to `1..200` (default `50`) with `offset`, returning `total_callers`, `total_callees`, `has_more`, and `next_offset`. Caller/callee nodes omit their Git permalinks unless `include_permalinks=True` (the target always keeps its permalink), which keeps deep traces compact. In C#, a call such as `_toolService.PublishInstance()` is indexed with the receiver's declared type (`ToolService.PublishInstance`), so methods with the same name in different classes are not mixed up.

### HTTP Route and Client Discovery (`find_routes`)

- **`find_routes`**: Unified route handler (`kind='handlers'`) and client call-site (`kind='callers'`) discovery across FastAPI, Flask, Django, Express/NestJS, ASP.NET Core, Go, Rust, Java, and JS/TS/C#/Python/Go HTTP clients (default `kind='both'`). Supports `query`, `method`, `repo`, and `limit` (`1..200`, default `50`) / `offset` pagination. When matching client invocations against `query`, each call belongs only to its most specific matching route in `api_routes` (literal segments beat mixed segments which beat `{param}` segments). Test files do not participate in route resolution.

### File Reading, Outlines, and Pattern Matching

- **`read_file`**: Reads `path` from watched directories, persistent shallow clones, local storage, or reconstructed vector chunks, or returns deduplicated AST classes, methods, functions, signatures, and `[start_line, end_line]` spans when `outline_only=True`.
  - Line slicing mode (`outline_only=False`): accepts `start_line` (`>= 1`) and `end_line` (`<= 2000` lines per call), returning `total_lines`, `start_line`, `end_line`, `has_more`, and `next_start_line`.
  - Outline mode (`outline_only=True`): clamps `limit` to `1..500` (default `150`) with `offset` pagination (`total_symbols`, `has_more`, `next_offset`).
- **`grep_code`**: Matches literal strings or regular expressions (`is_regex=True`) across disk and vector-backed repositories (using an in-process ripgrep fast path when all target repositories exist on disk). Supports `repo`, `path_glob` (alias `path`; with wildcards an fnmatch glob such as `*.cs`, without wildcards a file or folder such as `Services_V2`), `case_sensitive`, `context_lines` (`0..10`, default `2`), `limit` (`1..100`, default `30`), and `offset`. Truncates any matched or context line `> 400` characters with `...[line truncated]`. If a literal search finds nothing and the pattern looks like a regex (for example `A|B` or `foo.*bar`), the search runs again as a regex; `pattern_mode` in the result says which mode was used.

### Repository Inventory, Architecture, and Administration

- **`list_repositories`**: Consolidates registered Git repositories, monitored local paths, and managed local storage inventory. Supports `repo`, `source_type` (`all`, `git`, `monitored_path`, `local_storage`), `path_prefix`, `file_extension`, `include_files=True` (with `limit` `1..500`, default `100`, and `offset`), and `include_status=True` (adds vector database provider/mode, point totals, active dense/sparse models, and masked Git auth status).
- **`get_architecture`**: Synthesizes language distribution, package manifests, entry points, primary modules, hub symbols, route totals, and active ADRs.
- **`manage`** *(gated behind `MCP_ENABLE_WRITE_TOOLS=true`, default `false`)*: Single admin/write tool supporting `action='sync_repo'` (`editor` role — triggers background sync for `repo` or all sources) and local storage operations inside `LOCAL_STORAGE_PATH` (`upload`, `replace`, `delete` requiring `editor` role; `read`, `preview` requiring `viewer` role) with immediate vector and AST indexing.

> [!NOTE]
> Large-file summarization, recent git commit history, and ADR mutations remain available via the Web UI, REST endpoints (`/admin/api/files/summarize`, `/admin/api/repositories/{id}/commits`, `/admin/api/adrs`), and the `knowledge://repo/{repo}/adrs` MCP resource.

### Code Mode and Forensic Triage

- **`execute_script`** (Code Mode): runs one async JavaScript body that calls other tools with `await tools.<tool>(args)` and returns only the final result, so several dependent calls take one round trip. Tool results are parsed JSON, and a tool error throws. Limits: `CODE_MODE_TIMEOUT_SECONDS` (`30`), `CODE_MODE_MAX_TOOL_CALLS` (`50`), `CODE_MODE_MAX_MEMORY_MB` (`64`). Types: resource `contextcortex://code-mode/sdk.d.ts`. See [the reference](reference/mcp-tools.md#10-execute-script).
- **`diagnose_issue`**: Resolves stack traces, error string literals, HTTP routes, and semantic code candidates across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++. Clamps `context_lines` (`1..15`, default `5`) and `limit` (`1..20`, default `5`). When `repo` is set, every result section stays in that repo. When an HTTP route matches, `semantic_candidates` starts with the route handler and its callees (`source`: `route_handler` / `route_callee`, `depth`, `score`: `null`), followed by semantic hits in the same language (excluding test files).

---

## MCP Resources and Templates

ContextCortex splits repository metadata into granular, bounded JSON resources (`application/json`) so MCP clients only fetch the slices they need.

| Resource URI / Template | Page Size | Key Response Fields | Purpose |
| :--- | :---: | :--- | :--- |
| `contextcortex://code-mode/sdk.d.ts` | Single | One `tools.<tool>(args)` declaration per tool, with JSDoc | TypeScript types for `execute_script` (Code Mode) scripts. |
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
| `search_infrastructure_docs` | `topic` | `search(scope='docs')` -> `knowledge://repo/{repo}/adrs` -> `read_file` |
| `find_implementation_symbol` | `symbol`, `repo` (opt) | `find_symbol` -> `read_file(outline_only=True)` -> `read_file` -> `trace_path` |
| `onboard_repository` | `repo` | `get_architecture` -> `find_routes(kind='handlers')` -> `read_file(outline_only=True)` |
| `triage_error` | `issue_text`, `repo` (opt) | `diagnose_issue` -> `trace_path` -> `read_file` |
| `investigate_change_impact` | `symbol`, `repo` (opt) | `find_symbol` -> `trace_path(direction='callers')` -> `find_routes(kind='callers')` -> `grep_code` |

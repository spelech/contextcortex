# MCP Tools and Resources Reference

This document provides complete reference specifications for all 14 Model Context Protocol (MCP) tools, dynamic resources, and guided prompts exposed by ContextCortex.

---

## MCP Tools Matrix

| Tool Name | Minimum Role | Primary Parameters | Description |
| :--- | :---: | :--- | :--- |
| `search_code` | `viewer` | `query`, `repo`, `language`, `limit` | Performs hybrid dense and sparse search over indexed source code chunks. |
| `search_docs` | `viewer` | `query`, `repo`, `category`, `tag`, `limit` | Searches markdown documents, system architecture notes, and runbooks. |
| `find_symbol` | `viewer` | `name`, `repo`, `exact`, `limit` | Looks up AST symbols (functions, classes, interfaces) with exact or prefix matching. |
| `get_file_outline` | `viewer` | `filepath`, `repo` | Returns the structural outline of a file without full token payload costs. |
| `list_repositories` | `viewer` | None | Lists all registered Git repositories and local monitored paths with sync status. |
| `sync_repository` | `editor` | `repo` | Initiates background shallow clone synchronization for a repository. |
| `index_status` | `viewer` | None | Returns vector collection totals, embedding model details, and GitHub rate limits. |
| `get_architecture` | `viewer` | `repo` | Synthesizes repository entry points, language distributions, and structural layouts. |
| `manage_adr` | `editor` | `action`, `repo`, `title`, `decision`, `status` | Lists, creates, or updates Architectural Decision Records (MADR format). |
| `get_code_routes` | `viewer` | `repo`, `framework`, `http_method` | Returns declared HTTP route definitions and endpoint handlers across backend frameworks. |
| `trace_call_path` | `viewer` | `target`, `repo`, `direction`, `depth` | Traces AST symbol calls, imports, and cross-repo connections via breadth-first search. |
| `manage_local_file` | `editor` / `viewer` | `action`, `file_path`, `content`, `repo` | Manages files in local storage: upload, replace, read, or delete with real-time indexing. |
| `what_is_ingested` | `viewer` | `source_type`, `repo_name`, `path_prefix`, `detail_level` | Inspects all ingested sources with multidimensional filtering and file tree hierarchies. |

---

## Detailed Tool Specifications

### 1. `search_code`
Performs hybrid semantic and BM25 search over indexed code blocks.

- **Parameters**:
  - `query` (*string, required*): The natural language or code snippet search query.
  - `repo` (*string, optional*): Restrict results to a specific repository alias.
  - `language` (*string, optional*): Filter by programming language (e.g. `python`, `typescript`).
  - `limit` (*integer, default: 5*): Maximum number of ranked results to return.
- **Returns**: Array of code chunks with file paths, line ranges, RRF scores, and clickable Git permalinks.

### 2. `find_symbol`
Deterministic symbol lookup from the AST index.

- **Parameters**:
  - `name` (*string, required*): Symbol name to find (e.g. `FastEmbedEngine` or `search_code`).
  - `repo` (*string, optional*): Repository alias filter.
  - `exact` (*boolean, default: true*): Perform exact matching when true, prefix search when false.
  - `limit` (*integer, default: 10*): Maximum matches to return.
- **Returns**: Symbol declarations with signatures, starting and ending lines, and docstrings.

### 3. `manage_local_file`
Uploads, reads, updates, or deletes files in the managed local storage directory.

- **Parameters**:
  - `action` (*string, required*): Operation to execute (`upload`, `replace`, `read`, `delete`).
  - `file_path` (*string, required*): Relative file path within storage. Path traversal tokens (`..`) are rejected.
  - `content` (*string, optional*): Text file content for `upload` or `replace` actions.
  - `repo` (*string, optional*): Logical repository namespace.
- **Returns**: File status, file size in bytes, and indexing confirmation.

### 4. `what_is_ingested`
Returns an inventory of all indexed sources in the system.

- **Parameters**:
  - `source_type` (*string, optional*): Filter by `all`, `git`, `monitored_path`, or `local_storage`.
  - `repo_name` (*string, optional*): Filter by specific repository.
  - `path_prefix` (*string, optional*): Path prefix filter.
  - `file_extension` (*string, optional*): File extension filter (e.g. `.py`, `.ts`).
  - `detail_level` (*string, default: `summary`*): Detail level (`summary` or `detailed`).
- **Returns**: Aggregated file counts, source statuses, or hierarchical directory trees.

---

## Dynamic Catalog Resources

ContextCortex exposes dynamic resources for AI agents:

| Resource URI | MIME Type | Description |
| :--- | :--- | :--- |
| `knowledge://catalog/summary` | `text/markdown` | Real-time markdown report summarizing all indexed repositories, document distributions, and AST symbol totals. |

---

## Guided Prompts

ContextCortex exposes guided workflows via MCP prompts:

### 1. `search_infrastructure_docs`
- **Arguments**: `topic` (string)
- **Description**: Guides an AI assistant to retrieve container configurations, port mappings, and reverse proxy routes.

### 2. `find_implementation_symbol`
- **Arguments**: `symbol` (string), `repo` (string, optional)
- **Description**: Guides an AI assistant to locate symbol definitions, parameter signatures, and implementations.

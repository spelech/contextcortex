# Design Specification: File Reading and Large File Summarization

## 1. Overview & Goals
This feature provides two major capabilities for AI coding agents and human users in ContextCortex:
1. **Full & Sliced File Retrieval (`read_file`)**: An MCP tool and REST API enabling agents to read entire files or bounded line slices (`start_line` / `end_line`) across both monitored local directories (`indexed_paths`) and uploaded local storage files (`/data/storage`), with strict path traversal security.
2. **Large File Summarization Pipeline (`summarize_file`)**: An automated and on-demand LLM summarization system for files that exceed standard chunking thresholds (default: >500 KB). Large files are summarized using the configured LiteLLM chat model, cached in SQLite (`file_summaries.summary_text`), and embedded into the vector store so they remain discoverable via hybrid search rather than being silently omitted.
3. **Configurable Thresholds in UI**: File size thresholds, line retrieval limits, and chat model selections are fully customizable via the Settings UI and stored in SQLite metadata.

---

## 2. Architecture & Components

### 2.1 File Reader Service (`app/services/file_reader.py`)
- **Responsibilities**:
  - Resolves target file paths safely against:
    - Registered, enabled local paths from `indexed_paths`.
    - Local storage directory (`LOCAL_STORAGE_PATH`, default `/data/storage`).
  - Strict security validation:
    - Rejects path traversal (`..`, null bytes, symlink breakout).
    - Ensures path resolves strictly within an authorized root directory.
  - Reads text files with fallback encoding (`utf-8`, `errors='replace'`).
  - Detects binary content (e.g. null bytes in head sample) and rejects reading non-text files with an informative error.
  - Line-range slicing:
    - Supports optional `start_line` (1-based, inclusive) and `end_line` (inclusive).
    - Enforces a configurable ceiling `max_lines` (default 2,000 lines).
    - Returns structured payload:
      ```python
      {
          "filepath": rel_or_abs_path,
          "content": sliced_text,
          "start_line": s_line,
          "end_line": e_line,
          "total_lines": total_lines,
          "size_bytes": size_bytes,
          "truncated": is_truncated,
          "source": "indexed_path" | "local_storage"
      }
      ```

### 2.2 Summarizer Service (`app/services/summarizer.py`)
- **Responsibilities**:
  - Interacts with LiteLLM gateway (`/v1/chat/completions`) using the active chat model configured in settings or environment (`LITELLM_URL`, `LITELLM_API_KEY`).
  - Summarizes large documents and source code into structured markdown:
    - High-level executive overview / purpose.
    - Key exports, functions, classes, or sections.
    - Architectural dependencies and data flow notes.
  - Caches generated markdown summaries in SQLite `file_summaries.summary_text`.
  - Embeds the generated summary text into the vector store (Qdrant / Chroma) as a `doc_type="summary"` document, tagged with repo, category, and original file path.
  - Provides on-demand summary generation or retrieval via `get_or_create_summary(filepath, repo, force_refresh)`.

### 2.3 Indexing Processor Integration (`app/services/indexing/processor.py`)
- **Integration**:
  - In `process_file_content(...)`:
    - Checks file size against `summary_threshold_kb` (default: 500 KB).
    - If `summary_enabled` is true and file size exceeds threshold (up to `summary_max_file_size_mb`, default 10 MB):
      - Triggers `SummarizerService.generate_file_summary(...)`.
      - Adds the resulting summary vector document to `points` so it is indexed immediately alongside other vector points.
      - Sets `summary_text` in the `summary_tuple` inserted into `file_summaries`.
    - If file exceeds `summary_max_file_size_mb`, it logs a warning and skips embedding to protect memory.

### 2.4 MCP Tools (`app/mcp/handlers/file_handlers.py` & `app/mcp/tools.py`)
1. **`read_file`**:
   - Parameters:
     - `path`: (str, required) Target file path (relative to repo/storage, or absolute path matching an indexed root).
     - `repo`: (str, optional) Specific repository or storage namespace.
     - `start_line`: (int, optional) 1-based start line.
     - `end_line`: (int, optional) 1-based end line.
   - Output: Formatted markdown block with header, line numbers, and file statistics.
2. **`summarize_file`**:
   - Parameters:
     - `path`: (str, required) Target file path.
     - `repo`: (str, optional) Repository or storage namespace.
     - `force_refresh`: (bool, optional, default False) Whether to regenerate the LLM summary even if a cached summary exists.
   - Output: Markdown summary of the file.

### 2.5 REST API Endpoints (`app/api/routers/files.py` & `app/api/routers/settings.py`)
- `GET /admin/api/files/read`: Query params `path`, `repo`, `start_line`, `end_line`. Returns JSON payload from `FileReaderService`.
- `POST /admin/api/files/summarize`: Body `{ "path": str, "repo": Optional[str], "force_refresh": bool }`. Returns JSON summary result.
- `GET /admin/api/settings/files`: Returns current configuration for thresholds and file reading.
- `POST /admin/api/settings/files`: Updates threshold configuration in SQLite metadata.

### 2.6 Frontend Settings UI (`frontend/src/components/FileSettings.tsx` & `Settings.tsx`)
- New "Files & Summarization" card/tab under Settings:
  - **Auto-Summarize Large Files**: Toggle switch (`summary_enabled`).
  - **Large File Threshold (KB)**: Numeric input (default `500`).
  - **Max File Size for Summarization (MB)**: Numeric input (default `10`).
  - **Max Lines Per Read**: Numeric input (default `2000`).
  - **Summarization Chat Model**: Dropdown of models discovered from LiteLLM + write-in override.

---

## 3. Database Schema Changes

### 3.1 Migration in SQLite (`app/services/database/schema.py` & `connection.py`)
Add `summary_text` column to `file_summaries` table:
```sql
ALTER TABLE file_summaries ADD COLUMN summary_text TEXT;
```
For migration compatibility on startup:
```python
def ensure_file_summaries_columns(conn):
    cursor = conn.cursor()
    columns = [row[1] for row in cursor.execute("PRAGMA table_info(file_summaries)").fetchall()]
    if "summary_text" not in columns:
        cursor.execute("ALTER TABLE file_summaries ADD COLUMN summary_text TEXT")
        conn.commit()
```

### 3.2 Settings Metadata Keys
- `file_summary_enabled`: `"1"` or `"0"` (default `"1"`)
- `file_summary_threshold_kb`: integer as string, e.g. `"500"`
- `file_summary_max_size_mb`: integer as string, e.g. `"10"`
- `file_read_max_lines`: integer as string, e.g. `"2000"`
- `file_summary_model`: model identifier string (defaults to `chat_model` or `gpt-4o-mini`)

---

## 4. Security & Error Handling

1. **Path Traversal Protection**:
   All paths passed to `FileReaderService` are canonicalized (`os.path.realpath`) and verified against authorized roots:
   ```python
   target = os.path.realpath(resolved_path)
   if not any(target.startswith(root) for root in authorized_roots):
       raise ForbiddenError("Path traversal or unauthorized directory access attempt.")
   ```
2. **Binary File Protection**:
   The service inspects the first 1,024 bytes for null bytes `\x00`. If detected, file reading returns a `400 Bad Request` or an explicit MCP warning.
3. **LiteLLM Failure Resilience**:
   If LiteLLM is unreachable or times out during indexing:
   - File indexing does not abort or fail the sync job.
   - An error is logged, `summary_text` is left null, and indexing completes normally.
   - Users or agents can re-request summarization on-demand once LiteLLM is accessible.
4. **Token & Line Bounds**:
   If a client requests lines beyond `read_file_max_lines`, output is automatically truncated at the limit with `truncated: true` and an explanatory header.

---

## 5. Testing Strategy
1. **Unit Tests (`tests/test_file_reader.py`)**:
   - Safe path resolution within watched paths and local storage.
   - Path traversal attempts (`../../etc/passwd`, absolute paths outside roots) are blocked.
   - Line slicing (`start_line`, `end_line`, `max_lines` capping, bounds checking).
   - Binary file rejection.
2. **Unit Tests (`tests/test_summarizer.py`)**:
   - Prompt construction and mock LiteLLM completion calls.
   - Summary caching into SQLite and vector store payload formatting.
   - `force_refresh` behavior.
3. **Integration Tests (`tests/test_file_mcp_tools.py`)**:
   - FastMCP tool registration for `read_file` and `summarize_file`.
   - Tool execution with various parameters and permission validation.
4. **Frontend Settings Tests (`frontend/src/tests/FileSettings.test.tsx`)**:
   - Loading threshold settings from `/admin/api/settings/files`.
   - Updating and submitting threshold values.

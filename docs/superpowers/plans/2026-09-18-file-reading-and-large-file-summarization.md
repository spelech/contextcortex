# File Reading and Large File Summarization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement full and sliced file retrieval (`read_file`), automated and on-demand large file LLM summarization (`summarize_file`), and configurable UI thresholds for ContextCortex.

**Architecture:** 
- `FileReaderService` securely reads and line-slices files across watched paths and local storage.
- `SummarizerService` queries LiteLLM to generate structured markdown summaries for large files (>500KB or on-demand), stores them in SQLite (`file_summaries.summary_text`), and embeds them into the vector store.
- FastMCP exposes `read_file` and `summarize_file` tools.
- Settings UI and backend provide configurable thresholds (`summary_enabled`, `summary_threshold_kb`, `summary_max_file_size_mb`, `read_file_max_lines`, `summary_chat_model`).

**Tech Stack:** Python 3.11, FastAPI, SQLite / SQLAlchemy, FastMCP, LiteLLM / OpenAI client, React, TypeScript, TailwindCSS, Vite.

## Global Constraints
- Do not introduce breaking changes to existing MCP tools or APIs.
- Path resolution must strictly prevent directory traversal (`..`, null bytes, symlink escape).
- Large file summarization failure (e.g. LiteLLM timeout) must not abort indexing.
- Maintain test coverage across new services, tools, and endpoints.

---

### Task 1: Database Schema Migration & Settings Configuration

**Files:**
- Modify: `app/services/database/schema.py`
- Modify: `app/services/database/connection.py`
- Modify: `app/api/routers/settings.py`
- Test: `tests/test_file_settings.py`

**Interfaces:**
- Produces: 
  - `ensure_file_summaries_columns(conn)`
  - `get_file_settings() -> Dict[str, Any]`
  - `set_file_settings(payload: Dict[str, Any])`
  - Endpoints: `GET /admin/api/settings/files`, `POST /admin/api/settings/files`

- [ ] **Step 1: Write the failing test for schema and file settings**
- [ ] **Step 2: Run pytest to verify test failure**
- [ ] **Step 3: Add `summary_text` column to schema and migration in `connection.py`**
- [ ] **Step 4: Implement `get_file_settings` and `set_file_settings` in `connection.py`**
- [ ] **Step 5: Add `GET/POST /admin/api/settings/files` in `settings.py`**
- [ ] **Step 6: Run tests and verify they pass**
- [ ] **Step 7: Commit changes**

---

### Task 2: File Reader Service & MCP Tool (`read_file`)

**Files:**
- Create: `app/services/file_reader.py`
- Create: `app/mcp/handlers/file_handlers.py`
- Modify: `app/mcp/tools.py`
- Create: `app/api/routers/files.py`
- Modify: `main.py` (include files router)
- Test: `tests/test_file_reader.py`

**Interfaces:**
- Produces:
  - `FileReaderService.read_file(path: str, repo: Optional[str] = None, start_line: Optional[int] = None, end_line: Optional[int] = None, max_lines: Optional[int] = None) -> Dict[str, Any]`
  - `handle_read_file(...) -> str`
  - `GET /admin/api/files/read`

- [ ] **Step 1: Write unit tests for `FileReaderService` (path traversal, line slicing, binary check)**
- [ ] **Step 2: Run pytest to verify tests fail**
- [ ] **Step 3: Implement `FileReaderService` with path security and line slicing**
- [ ] **Step 4: Implement `handle_read_file` in `file_handlers.py` and register in `tools.py`**
- [ ] **Step 5: Create `app/api/routers/files.py` with `GET /admin/api/files/read`**
- [ ] **Step 6: Register files router in `main.py`**
- [ ] **Step 7: Run tests and verify they pass**
- [ ] **Step 8: Commit changes**

---

### Task 3: Large File Summarizer Service & MCP Tool (`summarize_file`)

**Files:**
- Create: `app/services/summarizer.py`
- Modify: `app/mcp/handlers/file_handlers.py`
- Modify: `app/mcp/tools.py`
- Modify: `app/api/routers/files.py`
- Test: `tests/test_summarizer.py`

**Interfaces:**
- Produces:
  - `SummarizerService.generate_file_summary(filepath: str, content: str, repo: str = "local") -> Tuple[str, VectorDocument]`
  - `SummarizerService.get_or_create_summary(filepath: str, repo: Optional[str] = None, force_refresh: bool = False) -> str`
  - `handle_summarize_file(...) -> str`
  - `POST /admin/api/files/summarize`

- [ ] **Step 1: Write unit tests for `SummarizerService` (mocking LiteLLM completion, caching, vector doc generation)**
- [ ] **Step 2: Run pytest to verify tests fail**
- [ ] **Step 3: Implement `SummarizerService` in `app/services/summarizer.py`**
- [ ] **Step 4: Implement `handle_summarize_file` in `file_handlers.py` and register in `tools.py`**
- [ ] **Step 5: Add `POST /admin/api/files/summarize` in `app/api/routers/files.py`**
- [ ] **Step 6: Run tests and verify they pass**
- [ ] **Step 7: Commit changes**

---

### Task 4: Ingestion & Indexing Processor Integration

**Files:**
- Modify: `app/services/indexing/processor.py`
- Modify: `app/services/local_storage.py`
- Test: `tests/test_processor_summarization.py`

**Interfaces:**
- Consumes: `SummarizerService`, `get_file_settings()`
- Updates: `process_file_content` to auto-summarize files > threshold instead of skipping them

- [ ] **Step 1: Write integration tests for `processor.py` with large file auto-summarization**
- [ ] **Step 2: Run pytest to verify test failure**
- [ ] **Step 3: Update `process_file_content` in `processor.py` to trigger `SummarizerService` when file exceeds `summary_threshold_kb`**
- [ ] **Step 4: Ensure vector points include the summary doc and SQLite `file_summaries` records `summary_text`**
- [ ] **Step 5: Run tests and verify they pass**
- [ ] **Step 6: Commit changes**

---

### Task 5: Frontend Settings UI & Web Build

**Files:**
- Create: `frontend/src/components/FileSettings.tsx`
- Modify: `frontend/src/Settings.tsx`
- Create: `frontend/src/tests/FileSettings.test.tsx`
- Build output: `www/`

**Interfaces:**
- Consumes: `/admin/api/settings/files`, `/admin/api/litellm/models`
- Produces: UI inputs for `summary_enabled`, `summary_threshold_kb`, `summary_max_file_size_mb`, `read_file_max_lines`, `summary_chat_model`

- [ ] **Step 1: Write frontend component test for `FileSettings.tsx`**
- [ ] **Step 2: Implement `FileSettings.tsx` and embed in `Settings.tsx`**
- [ ] **Step 3: Run Vitest frontend test suite**
- [ ] **Step 4: Rebuild frontend bundle (`npm run build`) into `www/`**
- [ ] **Step 5: Commit changes**

---

### Task 6: Comprehensive Verification, Branch Push & PR Creation

**Files:**
- Test: Entire test suite (`pytest`, `npm test`)
- Remote Git: Branch `feat/file-reading-and-large-file-summarization` -> Origin

- [ ] **Step 1: Run full backend test suite (`pytest`)**
- [ ] **Step 2: Run full frontend test suite (`npm test -- --run`)**
- [ ] **Step 3: Verify git status and commit any remaining changes**
- [ ] **Step 4: Push branch to origin**
- [ ] **Step 5: Create Pull Request with `gh pr create`**

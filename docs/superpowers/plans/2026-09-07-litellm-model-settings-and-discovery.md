# LiteLLM Model Settings & Dynamic Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all model settings for LiteLLM (embeddings, vision AI OCR, chat completion) into the ContextCortex UI with dynamic model discovery (`GET /admin/api/models/discover`), categorized model selection dropdowns, custom manual overrides, and SQLite persistent storage.

**Architecture:** 
1. Expand SQLite `system_metadata` schema and accessors in `app/services/database/connection.py` to persist `vision_ocr_model` and `chat_model` alongside existing embedding parameters.
2. Build `app/services/litellm_service.py` to query LiteLLM's `GET /v1/models` endpoint, categorize models by capability (Embedding, Vision/OCR, Chat), and handle offline/timeout states gracefully.
3. Expose `GET /admin/api/models/discover` and update `/admin/api/settings/embedding` in `app/api/routers/settings.py`.
4. Modernize `frontend/src/components/settings/EmbeddingSettings.tsx` and `frontend/src/Settings.tsx` with a dynamic "Discover Models" trigger, model dropdowns with instant custom switching, connection badges, and responsive inputs.

**Tech Stack:** Python 3.12, FastAPI, `httpx`, Pydantic v2, SQLite, React 18, Vite, TypeScript, Vitest, Pytest.

---

## Global Constraints

- Never break existing FastEmbed local embedding mode defaults (`BAAI/bge-small-en-v1.5`, `Qdrant/bm25`).
- Ensure all model configurations gracefully fall back to environment variables (`LITELLM_URL`, `LITELLM_API_KEY`, `VISION_OCR_MODEL`, `EMBEDDING_MODEL`) if SQLite records are empty.
- Keep network calls to LiteLLM resilient with strict timeouts (<= 6 seconds) to prevent UI or API blocking.
- 100% test pass rate across backend (`pytest`) and frontend (`vitest`), plus successful production build (`npm run build`).

---

## Task Decomposition

### Task 1: SQLite Metadata Persistence & Dynamic Model Retrieval

- [ ] Write failing unit test `tests/test_model_metadata_persistence.py` testing `get_embedding_db_config()`, `set_embedding_db_config()`, and `get_vision_ocr_model()` persistence.
- [ ] Run pytest to verify test failure: `pytest tests/test_model_metadata_persistence.py`.
- [ ] In `app/services/database/connection.py`:
  - Add `vision_ocr_model` and `chat_model` to `_resolve_default_embedding_config()`, `get_embedding_db_config()`, and `set_embedding_db_config()`.
  - Add and export `get_vision_ocr_model() -> str` and `get_chat_model() -> str`.
- [ ] In `app/services/database/__init__.py`:
  - Export `get_vision_ocr_model` and `get_chat_model`.
- [ ] In `app/services/embeddings.py`:
  - Update `get_embedding_config()` and `update_embedding_config()` to accept and return `vision_ocr_model` and `chat_model`.
- [ ] In `app/services/pdf_extractor.py`:
  - Update `_call_vision_ocr` to use `get_vision_ocr_model()` dynamically.
- [ ] In `app/models/schemas.py`:
  - Add `vision_ocr_model: Optional[str] = None` and `chat_model: Optional[str] = None` to `EmbeddingSettingsRequest`.
- [ ] Run pytest to verify test passes: `pytest tests/test_model_metadata_persistence.py tests/test_pdf_extractor.py`.
- [ ] Commit: `git commit -m "feat(models): add vision_ocr_model and chat_model persistence to system_metadata"`

---

### Task 2: LiteLLM Model Discovery Service (`app/services/litellm_service.py`)

- [ ] Write failing unit test `tests/test_litellm_service.py` testing `discover_models` with mock LiteLLM API responses:
  - Successful response with mixed models (chat, embedding, vision)
  - Classification check: `gemini-embedding-2` in `embedding_models`, `gemini-2.5-flash` in `vision_models` and `chat_models`
  - Connection refused / timeout handling returning structured fallback.
- [ ] Run pytest to verify test failure: `pytest tests/test_litellm_service.py`.
- [ ] Implement `app/services/litellm_service.py`:
  - Function `async def discover_models(url: Optional[str] = None, api_key: Optional[str] = None) -> Dict[str, Any]`
  - Use `httpx.AsyncClient(timeout=6.0)` to request `{url}/models` with `Authorization: Bearer {api_key}` header.
  - Categorization algorithm for `embedding_models`, `vision_models`, `chat_models`.
  - Graceful exception trapping for `httpx.TimeoutException`, `httpx.ConnectError`, `httpx.HTTPStatusError`.
- [ ] Run pytest to verify test passes: `pytest tests/test_litellm_service.py`.
- [ ] Commit: `git commit -m "feat(litellm): add dynamic model discovery service with classification and resilient fallbacks"`

---

### Task 3: Backend API Routes for Model Discovery and Unified Settings

- [ ] Write failing test `tests/test_model_discovery_api.py` testing:
  - `GET /admin/api/models/discover`
  - `GET /admin/api/settings/embedding` (returns `vision_ocr_model` and `chat_model`)
  - `POST /admin/api/settings/embedding` (saves and updates `vision_ocr_model` and `chat_model`)
- [ ] Run pytest to verify failure: `pytest tests/test_model_discovery_api.py`.
- [ ] In `app/api/routers/settings.py`:
  - Add route `@router.get("/admin/api/models/discover")` calling `litellm_service.discover_models`.
  - Update `api_save_embedding_settings` to pass `payload.vision_ocr_model` and `payload.chat_model` to `emb_service.update_embedding_config`.
- [ ] Run pytest to verify test passes: `pytest tests/test_model_discovery_api.py`.
- [ ] Commit: `git commit -m "feat(api): expose /admin/api/models/discover and update embedding settings route"`

---

### Task 4: Frontend UI for Model Discovery & Dynamic Selection

- [ ] In `frontend/src/types.ts`:
  - Extend `EmbeddingConfig` with `vision_ocr_model?: string` and `chat_model?: string`.
  - Add `ModelDiscoveryResult` interface.
- [ ] In `frontend/src/components/settings/EmbeddingSettings.tsx`:
  - Add "Discover Models" button next to LiteLLM URL and API Key inputs.
  - When models are discovered, display count badge (e.g. `42 models detected`).
  - Render dynamic `<select>` dropdowns for Dense Embedding Model, Vision AI OCR Model, and Chat Model.
  - Provide a `Custom / Enter Model Name...` option that seamlessly reveals a manual text input.
  - Support fallback text input if discovery is idle or fails.
- [ ] In `frontend/src/Settings.tsx`:
  - Manage state for `embVisionOcrModel`, `embChatModel`, `discoveredModels`, `isDiscoveringModels`, `discoveryStatus`.
  - Implement `handleDiscoverModels` calling `/admin/api/models/discover`.
  - Include new fields in `handleSaveEmbeddingSettings` payload.
- [ ] Update frontend tests `frontend/src/tests/EmbeddingSettings.test.tsx` and `frontend/src/tests/Settings.test.tsx`.
- [ ] Run Vitest suite: `npm --prefix frontend test run`.
- [ ] Build production assets: `npm --prefix frontend run build`.
- [ ] Commit: `git commit -m "feat(ui): add LiteLLM model discovery button, dynamic model dropdowns, and custom selectors"`

---

### Task 5: End-to-End Verification, Documentation, and Pull Request

- [ ] Test live discovery against the running LiteLLM instance at `http://10.0.0.10:8448/v1`.
- [ ] Run the complete backend test suite: `pytest`.
- [ ] Run the complete frontend test suite: `npm --prefix frontend test run`.
- [ ] Update `README.md` and `REQUIREMENTS.md` documenting the new model discovery API and settings fields.
- [ ] Push `feat/litellm-model-settings-and-discovery` to origin.
- [ ] Open Pull Request using GitHub CLI (`gh pr create`).
- [ ] Output `<!-- GOAL_COMPLETE -->`.

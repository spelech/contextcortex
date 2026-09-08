# Dynamic LiteLLM Model Discovery & Unified Model Settings Design Specification

**Feature:** LiteLLM Dynamic Model Discovery & UI Model Management  
**Status:** Approved  
**Date:** 2026-09-07  
**Branch:** `feat/litellm-model-settings-and-discovery`  

---

## 1. Overview & Motivation

ContextCortex utilizes LiteLLM as its unified gateway for:
1. **Remote Dense Vector Embeddings** (`/v1/embeddings`), offloading heavy mathematical vectorization from local CPUs.
2. **Vision AI OCR Fallback** (`/v1/chat/completions`), converting scanned or image-dense document pages (such as complex technical manuals like ASD-STE100) into searchable text.
3. **General LLM Queries & Completions** (future RAG synthesis and analysis).

Previously, these model configurations were fragmented across environment variables (`EMBEDDING_MODEL`, `VISION_OCR_MODEL`, `LITELLM_URL`, `LITELLM_API_KEY`) and manual text inputs in the web UI. Users had no visibility into which models were actually registered, online, or supported on their LiteLLM instance.

This feature moves **all LiteLLM model settings directly into the web UI** and introduces **dynamic model discovery** (`GET /admin/api/models/discover`), querying LiteLLM's `GET /v1/models` endpoint to populate intuitive dropdown selectors with categorized embedding, vision, and chat models, while retaining custom manual overrides.

---

## 2. Architecture & Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      ContextCortex UI                       │
│    (Settings -> Embedding & Model Configuration Component)  │
│                                                             │
│   [LiteLLM URL: http://litellm:4000/v1] [API Key: ••••••••]  │
│               [ ⚡ Discover Available Models ]              │
└──────────────┬───────────────────────────────▲──────────────┘
               │ 1. GET /admin/api/models/     │ 4. Populates dynamic
               │    discover                   │    categorized dropdowns
               ▼                               │    (Embeddings, Vision, Chat)
┌──────────────────────────────────────────────┴──────────────┐
│                  ContextCortex Backend                      │
│                                                             │
│  app/api/routers/settings.py                                │
│    ├── GET  /admin/api/models/discover                      │
│    ├── GET  /admin/api/settings/embedding (expanded)        │
│    └── POST /admin/api/settings/embedding (expanded)        │
│                                                             │
│  app/services/litellm_service.py                            │
│    └── discover_models(url, api_key)                        │
│                                                             │
│  app/services/database/connection.py                        │
│    └── SQLite system_metadata:                              │
│        - embedding_litellm_url                              │
│        - embedding_litellm_api_key                          │
│        - embedding_dense_model                              │
│        - embedding_sparse_model                             │
│        - vision_ocr_model                                   │
│        - chat_model                                         │
└──────────────┬──────────────────────────────────────────────┘
               │ 2. GET /v1/models (Bearer auth)
               ▼
┌─────────────────────────────────────────────────────────────┐
│                       LiteLLM Proxy                         │
│                  (http://litellm:4000/v1)                   │
│   Returns: List of active models, modes & capabilities      │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Component Specifications

### 3.1 SQLite System Metadata Keys
All model settings are persisted in SQLite `system_metadata` so they survive restarts and update at runtime without container rebuilds:
- `embedding_provider`: `"local"` | `"api"`
- `embedding_litellm_url`: e.g. `"http://litellm:4000/v1"`
- `embedding_litellm_api_key`: e.g. `"sk-..."`
- `embedding_dense_model`: e.g. `"gemini-embedding-2"` or `"BAAI/bge-small-en-v1.5"`
- `embedding_sparse_model`: e.g. `"Qdrant/bm25"`
- `vision_ocr_model`: e.g. `"gemini-2.5-flash"`
- `chat_model`: e.g. `"gemini-2.5-flash"`

### 3.2 Discovery Service (`app/services/litellm_service.py`)
- Communicates with LiteLLM's standard OpenAI-compatible `/v1/models` endpoint using `httpx` with a 6-second timeout.
- Classifies models based on `mode` and name patterns:
  - **Embedding Models:** `mode == "embedding"`, or contains `"embed"`, `"bge"`, `"text-embedding"`.
  - **Vision / Multimodal Models:** contains `"vision"`, `"-vl"`, `"gemini"`, `"gpt-4"`, `"claude"`, `"qwen3-vl"`.
  - **Chat Models:** `mode == "chat"` or standard chat/completion LLMs.
- Response payload:
  ```json
  {
    "status": "success",
    "total_models": 42,
    "models": [
      {"id": "gemini-embedding-2", "mode": "embedding", "owned_by": "openai"},
      {"id": "gemini-2.5-flash", "mode": "chat", "owned_by": "openai"}
    ],
    "embedding_models": ["gemini-embedding-2"],
    "vision_models": ["gemini-2.5-flash", "qwen3-vl-32b-instruct"],
    "chat_models": ["gemini-2.5-flash", "deepseek-v3.2"]
  }
  ```
- Error Handling: Catches `httpx.RequestError`, `httpx.HTTPStatusError`, connection timeouts, and authentication failures. Returns structured error messages (`status: "error"`, `message: "..."`) with safe fallback defaults so the UI displays actionable diagnostic feedback.

### 3.3 Dynamic Model Consumers
1. **`app/services/pdf_extractor.py`**:
   - Replaces static `os.getenv("VISION_OCR_MODEL", "gemini-2.0-flash")` with dynamic `get_vision_ocr_model()`:
     Checks SQLite `system_metadata["vision_ocr_model"]` -> env `VISION_OCR_MODEL` -> fallback `"gemini-2.5-flash"`.
2. **`app/services/embeddings.py`**:
   - Manages active dense/sparse embedding models and LiteLLM connection parameters.

### 3.4 Frontend Settings Interface (`EmbeddingSettings.tsx`)
- **API Connection Controls**:
  - `API Endpoint URL` and `API Key` fields.
  - **"Discover Models"** button with spinning indicator and status message.
  - Automatically attempts discovery when switching to API provider or when the user triggers the action.
- **Model Selectors**:
  - **Dense Embedding Model Selector**:
    - If models discovered: Dropdown grouped with discovered embedding models, plus a `Custom / Enter Model Name...` option.
    - If local provider: Standard local model input with common FastEmbed recommendations (`BAAI/bge-small-en-v1.5`, `BAAI/bge-large-en-v1.5`, `sentence-transformers/all-MiniLM-L6-v2`).
  - **Vision AI OCR Model Selector**:
    - Grouped dropdown populated with discovered vision models (`gemini-2.5-flash`, `qwen3-vl-32b-instruct`, etc.) plus custom text entry option.
  - **General Chat Model Selector**:
    - Grouped dropdown populated with discovered chat models.
- **Visual Feedback**:
  - Badge indicating current discovery status (e.g. `✓ Connected (42 models detected)` or `⚠ LiteLLM unreachable at http://litellm:4000/v1`).

---

## 5. Testing Strategy

1. **Backend Tests:**
   - `tests/test_litellm_service.py`: Unit tests for model fetching, classification logic, timeouts, and error handling.
   - `tests/test_model_settings_api.py`: Tests for `GET /admin/api/models/discover`, `GET /admin/api/settings/embedding`, and `POST /admin/api/settings/embedding` with `vision_ocr_model` and `chat_model`.
   - `tests/test_pdf_extractor.py`: Verify PDF extractor honors dynamic vision OCR model from DB.
2. **Frontend Tests:**
   - `frontend/src/tests/EmbeddingSettings.test.tsx`: Test rendering of discover button, model dropdowns, custom model toggle, and form submission.
3. **Integration Verification:**
   - Live discovery call against homelab LiteLLM at `http://10.0.0.10:8448/v1`.
   - Full Vitest suite (`npm test`) and production bundle build (`npm run build`).

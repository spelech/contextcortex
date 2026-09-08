# Design Specification: Vector DB Health Check Fix & PDF Ingestion with Extraction Preview

- **Date:** 2026-09-07
- **Branch:** `feat/health-check-and-pdf-ingestion`
- **Repository:** `contextcortex` (`/containers/dev/contexthub`)
- **Status:** Approved

---

## 1. Overview & Problem Statement

ContextCortex serves as the centralized Code & Documentation RAG Hub for homelab services and developer workflows. Two key issues currently exist:
1. **Vector DB Status Regression:** The `/admin/api/stats` endpoint inspects `stats.get("healthy", False)`, but vector store implementations (`qdrant_store.py`, `chroma_store.py`) return collection-level metadata without a `"healthy"` key. Consequently, healthy vector backends (such as Qdrant with active collections) are reported as `"Unhealthy"` on the dashboard overview badge.
2. **Missing PDF Document Ingestion:** The platform only processes plain text, markdown, and programming language source files capped at 500 KB. Technical standards, specifications, and manuals (specifically **ASD-STE100** — Simplified Technical English, typically 5–15 MB) cannot currently be uploaded, inspected, or embedded into the vector store.
3. **Lack of Extraction Inspection:** Users need the ability to inspect exactly what text was extracted from a PDF (including page-by-page breakdown, OCR flags, and proposed chunks) **before** committing vectors into the database.

---

## 2. Goals & Non-Goals

### Goals
- **Fix Health Check Reporting:** Ensure `/admin/api/stats` accurately reports `"Healthy"` when `store.health_check()` succeeds.
- **Support High-Capacity PDF Ingestion:** Permit PDF uploads up to 50 MB (configurable via `MAX_PDF_SIZE_MB`).
- **Hybrid Text Extraction:**
  - Fast, digital text extraction using PyMuPDF (`pymupdf`).
  - Automatic AI OCR fallback via LiteLLM Vision (e.g. `gemini-2.0-flash` or OpenAI-compatible vision model) for pages with minimal or no embedded text (< 50 characters).
- **Pre-Ingestion Extraction Preview:**
  - Dedicated preview endpoint (`POST /admin/api/storage/pdf/preview`) to inspect extracted text, page count, and chunking before saving to disk or vector database.
  - Interactive Preview Modal in the Web UI allowing inspection of each page's text and sample chunks.
- **Page-Aware Vector Indexing:**
  - Tag each vector chunk with metadata: `page_number`, `total_pages`, `headings: ["Page X"]`, and `doc_type: "pdf"`.
- **MCP Tooling:** Support `action="preview"` and `action="read"` for PDFs in `manage_local_file`.

### Non-Goals
- Full layout-preserving PDF reconstruction or diagram image re-generation.
- External heavy OCR engines (e.g., Tesseract C-libraries) requiring system-level package bloat.

---

## 3. Architecture & Detailed Component Design

### 3.1 Vector DB Health Check Fix
In `app/api/routers/settings.py`:
```python
store = vs_service.get_vector_store()
healthy, health_msg = store.health_check()
stats = store.get_stats()
total_chunks = stats.get("points_count", 0)
vector_db_healthy = healthy
vector_db_status = "Healthy" if vector_db_healthy else "Unhealthy"
```
This aligns the status computation with `manager.get_vector_store_config()`, accurately reflecting Qdrant/Chroma readiness.

---

### 3.2 PDF Extraction Service (`app/services/pdf_extractor.py`)

A dedicated service wrapping PyMuPDF (`pymupdf`) and LiteLLM Vision:

```
                          ┌───────────────────────┐
                          │   Input PDF Stream    │
                          └───────────┬───────────┘
                                      │
                                      ▼
                           pymupdf.open(stream)
                                      │
                       ┌──────────────┴──────────────┐
                       ▼                             ▼
             page.get_text()                  len(text) < 50 chars?
                       │                             │
                       │                             ├─► Yes: Render page to PNG pixmap
                       │                             │        Call LiteLLM Vision API
                       │                             │        ocr_applied = True
                       ▼                             ▼
                ┌──────────────────────────────────────────┐
                │   PdfPageResult(page_num, text, ocr)     │
                └─────────────────────┬────────────────────┘
                                      │
                                      ▼
                        Page-Aware Chunker (Sliding Window)
```

#### Interfaces:
```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class PdfPageResult:
    page_number: int
    text: str
    char_count: int
    ocr_applied: bool

@dataclass
class PdfExtractionResult:
    filename: str
    total_pages: int
    total_characters: int
    ocr_pages_count: int
    pages: List[PdfPageResult]
    preview_chunks: List[dict]
```

#### AI OCR Fallback Implementation:
When `len(page_text.strip()) < 50`:
1. `pixmap = page.get_pixmap(dpi=150)`
2. `img_bytes = pixmap.tobytes("png")`
3. Convert to Base64 `data:image/png;base64,...`
4. Post to LiteLLM endpoint using OpenAI client:
   - System prompt: `"Transcribe all text, numbers, specifications, and tables from this document page verbatim. Do not summarize or extrapolate."`
   - User content: `[{"type": "image_url", "image_url": {"url": b64_data}}]`
5. If vision call fails or is unconfigured, return original sparse text gracefully with warning log.

---

### 3.3 Storage & Ingestion Pipeline

1. **File Size Limits (`app/services/indexing/processor.py` & `local_storage.py`):**
   - Standard text/code limit: `500 * 1024` bytes (500 KB).
   - PDF limit: `MAX_PDF_SIZE_BYTES = int(os.getenv("MAX_PDF_SIZE_MB", "50")) * 1024 * 1024` (50 MB).
2. **Local Storage Service (`app/services/local_storage.py`):**
   - `save_file`: Saves raw binary bytes for `.pdf`.
   - `index_file`: Detects `.pdf` extension, routes through `pdf_extractor.extract_pdf_pages()`, and constructs `VectorDocument` objects per page/chunk with headings `["Page X"]` and `doc_type="pdf"`.
   - `read_file_content`: If target is `.pdf`, extracts and returns formatted text pages rather than raw binary data.

---

### 3.4 API Endpoints (`app/api/routers/storage.py`)

#### `POST /admin/api/storage/pdf/preview`
- **Request:** `multipart/form-data` with `file: UploadFile`.
- **Action:** Runs `extract_pdf_pages()` and chunk simulation **in-memory without writing to disk or vector DB**.
- **Response:**
  ```json
  {
    "filename": "ASD-STE100.pdf",
    "total_pages": 412,
    "total_characters": 625400,
    "ocr_pages_count": 0,
    "pages": [
      {
        "page_number": 1,
        "text": "ASD-STE100 ISSUE 8...",
        "char_count": 1420,
        "ocr_applied": false
      }
    ],
    "sample_chunks": [
      {
        "chunk_index": 0,
        "page_number": 1,
        "heading": "Page 1",
        "preview": "ASD-STE100 ISSUE 8..."
      }
    ]
  }
  ```

#### `POST /admin/api/storage/upload`
- Extended to accept `multipart/form-data` with `.pdf` files up to 50 MB.
- Invokes `storage.save_file()` and triggers immediate vector indexing into the active vector store (Qdrant).

---

### 3.5 Frontend UI Workflow (`frontend/src/`)

1. **Upload Modal in `Storage.tsx`:**
   - File selector allows `.pdf,.md,.txt,...`.
   - When a `.pdf` file is chosen, the UI immediately displays a **"Preview Extraction"** step.
   - Shows progress bar while calling `/admin/api/storage/pdf/preview`.
2. **PDF Preview Modal (`frontend/src/PdfPreviewModal.tsx`):**
   - Header with document metrics: total pages, total characters, OCR pages count.
   - Page navigation tabs/slider to review page text.
   - Sample chunks tab showing how the vector store will chunk and tag the document.
   - Primary action: **"Confirm & Ingest to Vector DB"** (submits the file for persistent storage and indexing).
3. **Storage File Table:**
   - Files with `.pdf` display a red PDF badge/icon (`fa-file-pdf`).
   - Clicking "View" opens the extracted text viewer.

---

## 4. Error Handling & Edge Cases

| Scenario | Behavior |
|---|---|
| File exceeds 50MB | API returns HTTP 413 / 400 with clear message `"PDF file exceeds 50MB limit"`. |
| Encrypted/Password-protected PDF | Returns HTTP 400 `"PDF is encrypted or password-protected"`. |
| Corrupt or non-PDF file renamed `.pdf` | Caught during PyMuPDF stream open; returns HTTP 400 `"Invalid or corrupted PDF file"`. |
| Scanned image-only page, LiteLLM unreachable | Logs warning; proceeds with available text (or empty string) without failing entire ingestion. |
| Re-indexing existing PDF | Hashes each chunk; only embeddings with cache misses are computed, saving LiteLLM/local tokens. |

---

## 5. Testing & Verification Plan

1. **Health Check Test (`test_health_check_status.py`):**
   - Verify `/admin/api/stats` returns `"vector_db_status": "Healthy"` when Qdrant is mock-healthy.
2. **Digital PDF Extraction Test (`test_pdf_extractor.py`):**
   - Generate a digital multi-page PDF in test fixtures.
   - Verify page counts, text fidelity, and chunk tagging (`page_number`, `doc_type="pdf"`).
3. **AI OCR Fallback Test (`test_pdf_extractor_ocr.py`):**
   - Create a blank/image PDF page.
   - Mock LiteLLM Vision response.
   - Verify that vision transcription is invoked and `ocr_applied` is set to `True`.
4. **Storage API & Preview Tests (`test_pdf_storage_api.py`):**
   - Test `POST /admin/api/storage/pdf/preview` returns valid JSON preview without altering disk.
   - Test `POST /admin/api/storage/upload` ingests PDF and registers in `indexed_files`.
5. **Full Regression Suite:**
   - Run `pytest` across all 457+ existing tests to confirm 100% pass rate.

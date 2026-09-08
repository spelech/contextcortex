# Vector DB Health Check Fix & PDF Ingestion with Extraction Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the Vector DB Health Check reporting regression in `/admin/api/stats`, and introduce high-capacity (up to 50MB) PDF document ingestion with pre-ingestion extraction preview, PyMuPDF digital extraction, LiteLLM Vision AI OCR fallback, and page-aware vector indexing.

**Architecture:** 
1. Fix the health status computation in `app/api/routers/settings.py` by checking `store.health_check()`.
2. Introduce `app/services/pdf_extractor.py` wrapping PyMuPDF for fast digital page text extraction and LiteLLM Vision API for automatic OCR fallback on sparse/scanned pages (< 50 chars).
3. Expose a pre-ingestion preview endpoint `POST /admin/api/storage/pdf/preview` and extend `POST /admin/api/storage/upload` to store and index PDFs into the vector store.
4. Enhance `frontend/src/Storage.tsx` with a `PdfPreviewModal.tsx` allowing page-by-page review and chunk preview before confirming ingestion.

**Tech Stack:** Python 3.12, FastAPI, PyMuPDF (`pymupdf`), OpenAI client / LiteLLM, Qdrant Client, React 18, Vite, TypeScript, Pytest.

## Global Constraints
- Python 3.12 compatibility.
- PDF file size limit: Default 50 MB, configurable via `MAX_PDF_SIZE_MB`.
- Standard plain text/code file size limit remains 500 KB (`MAX_FILE_SIZE_BYTES`).
- All tests must pass cleanly (`pytest` 100% pass rate).
- Do not introduce external system-level packages (like C Tesseract) into the Docker container.

---

### Task 1: Fix Vector Database Health Check Reporting

**Files:**
- Modify: `app/api/routers/settings.py:59-70`
- Test: `tests/backend/test_health_check_status.py`

**Interfaces:**
- Consumes: `vs_service.get_vector_store()`, `store.health_check() -> Tuple[bool, str]`, `store.get_stats() -> Dict[str, Any]`
- Produces: `/admin/api/stats` returning `"vector_db_status": "Healthy"` when vector store is healthy.

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_health_check_status.py
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app

@pytest.fixture
def client():
    return TestClient(app)

def test_api_stats_reports_healthy_when_store_is_healthy(client):
    mock_store = MagicMock()
    mock_store.health_check.return_value = (True, "Qdrant is healthy")
    mock_store.get_stats.return_value = {
        "backend": "qdrant",
        "mode": "remote",
        "collection_name": "notes_rag",
        "exists": True,
        "points_count": 2641,
        "status": "green"
    }
    
    with patch("app.services.vector_store.get_vector_store", return_value=mock_store):
        response = client.get("/admin/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["vector_db_status"] == "Healthy"
        assert data["vector_store"]["healthy"] is True

def test_api_stats_reports_unhealthy_when_store_fails(client):
    mock_store = MagicMock()
    mock_store.health_check.return_value = (False, "Connection refused")
    mock_store.get_stats.return_value = {
        "backend": "qdrant",
        "mode": "remote",
        "exists": False,
        "error": "Connection refused"
    }
    
    with patch("app.services.vector_store.get_vector_store", return_value=mock_store):
        response = client.get("/admin/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["vector_db_status"] == "Unhealthy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_health_check_status.py -v`
Expected: FAIL (`assert 'Unhealthy' == 'Healthy'`)

- [ ] **Step 3: Implement the fix in `app/api/routers/settings.py`**

Replace lines 59–70 in `app/api/routers/settings.py`:
```python
            total_chunks = 0
            vector_db_healthy = False
            vector_db_status = "Unknown"
            try:
                store = vs_service.get_vector_store()
                healthy, health_msg = store.health_check()
                stats = store.get_stats()
                total_chunks = stats.get("points_count", 0)
                vector_db_healthy = healthy
                vector_db_status = "Healthy" if vector_db_healthy else "Unhealthy"
            except Exception as e:
                vector_db_status = f"Error: {e}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_health_check_status.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/settings.py tests/backend/test_health_check_status.py
git commit -m "fix(health): query store.health_check() directly in stats router"
```

---

### Task 2: PDF Extractor Service with PyMuPDF & LiteLLM Vision OCR Fallback

**Files:**
- Modify: `requirements.txt`
- Create: `app/services/pdf_extractor.py`
- Test: `tests/test_pdf_extractor.py`

**Interfaces:**
- Consumes: PyMuPDF (`fitz` / `pymupdf`), `app.services.embeddings.LITELLM_URL`, `LITELLM_API_KEY`, `_get_openai_client()`
- Produces: `extract_pdf_pages(file_bytes_or_path, ocr_fallback: bool = True) -> PdfExtractionResult`

- [ ] **Step 1: Add `pymupdf>=1.24.0` to `requirements.txt` and install in environment**

Add `pymupdf>=1.24.0` to `requirements.txt` and install via `pip install pymupdf`.

- [ ] **Step 2: Write tests for PDF extraction and OCR fallback**

```python
# tests/test_pdf_extractor.py
import pytest
import pymupdf
from unittest.mock import patch, MagicMock
from app.services.pdf_extractor import (
    extract_pdf_pages, PdfExtractionResult, PdfPageResult
)

def create_sample_pdf(pages_text: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            page.insert_text((50, 50), text)
    return doc.tobytes()

def test_extract_digital_pdf_text():
    pdf_bytes = create_sample_pdf(["ASD-STE100 Section 1: Overview", "ASD-STE100 Section 2: Approved Words"])
    res = extract_pdf_pages(pdf_bytes, filename="ste100.pdf", ocr_fallback=False)
    
    assert isinstance(res, PdfExtractionResult)
    assert res.total_pages == 2
    assert res.ocr_pages_count == 0
    assert "Overview" in res.pages[0].text
    assert res.pages[0].page_number == 1
    assert "Approved Words" in res.pages[1].text
    assert res.pages[1].page_number == 2
    assert len(res.preview_chunks) >= 2

def test_extract_scanned_pdf_triggers_vision_ocr():
    # Empty page triggers fallback when ocr_fallback=True
    pdf_bytes = create_sample_pdf([""])
    
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="Transcribed STE rule text via OCR"))
    ]
    
    with patch("app.services.pdf_extractor._call_vision_ocr", return_value="Transcribed STE rule text via OCR"):
        res = extract_pdf_pages(pdf_bytes, filename="scanned.pdf", ocr_fallback=True)
        assert res.total_pages == 1
        assert res.ocr_pages_count == 1
        assert res.pages[0].ocr_applied is True
        assert "Transcribed STE rule text via OCR" in res.pages[0].text

def test_extract_corrupted_pdf_raises_value_error():
    with pytest.raises(ValueError, match="Invalid or corrupted PDF"):
        extract_pdf_pages(b"not a real pdf content", filename="corrupt.pdf")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_pdf_extractor.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'app.services.pdf_extractor')

- [ ] **Step 4: Implement `app/services/pdf_extractor.py`**

```python
# app/services/pdf_extractor.py
import os
import io
import base64
import logging
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Union, Optional
import pymupdf
from openai import OpenAI

logger = logging.getLogger("contextcortex.pdf")

MAX_PDF_SIZE_BYTES = int(os.getenv("MAX_PDF_SIZE_MB", "50")) * 1024 * 1024
OCR_TEXT_THRESHOLD_CHARS = 50

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
    preview_chunks: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _call_vision_ocr(png_bytes: bytes, model_name: str = "gemini-2.0-flash") -> str:
    """Invokes LiteLLM / OpenAI compatible vision model to transcribe document page."""
    litellm_url = os.getenv("LITELLM_URL", "http://litellm:4000/v1").strip()
    litellm_key = os.getenv("LITELLM_API_KEY", "sk-default").strip()
    client = OpenAI(base_url=litellm_url, api_key=litellm_key)
    
    b64_data = base64.b64encode(png_bytes).decode("utf-8")
    data_url = f"data:image/png;base64,{b64_data}"
    
    system_prompt = (
        "Transcribe all text, numbers, specifications, headings, and tables from this document page verbatim. "
        "Preserve list structures and code blocks where applicable. Do not summarize or extrapolate."
    )
    
    response = client.chat.completions.create(
        model=os.getenv("VISION_OCR_MODEL", model_name),
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Please transcribe this page."},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]
            }
        ],
        max_tokens=4096,
        temperature=0.0
    )
    return response.choices[0].message.content or ""


def extract_pdf_pages(
    source: Union[str, bytes],
    filename: str = "document.pdf",
    ocr_fallback: bool = True,
    chunk_size: int = 1500,
    chunk_overlap: int = 200
) -> PdfExtractionResult:
    """Extracts text page-by-page from PDF with optional AI OCR fallback on sparse pages."""
    try:
        if isinstance(source, bytes):
            if len(source) > MAX_PDF_SIZE_BYTES:
                raise ValueError(f"PDF exceeds size limit of {MAX_PDF_SIZE_BYTES // (1024*1024)}MB")
            doc = pymupdf.open(stream=source, filetype="pdf")
        else:
            if not os.path.exists(source):
                raise FileNotFoundError(f"PDF file not found: {source}")
            if os.path.getsize(source) > MAX_PDF_SIZE_BYTES:
                raise ValueError(f"PDF exceeds size limit of {MAX_PDF_SIZE_BYTES // (1024*1024)}MB")
            doc = pymupdf.open(source)
    except Exception as e:
        if isinstance(e, (ValueError, FileNotFoundError)):
            raise
        raise ValueError(f"Invalid or corrupted PDF file: {e}")

    total_pages = len(doc)
    page_results: List[PdfPageResult] = []
    ocr_pages_count = 0
    total_characters = 0
    preview_chunks: List[Dict[str, Any]] = []

    for idx, page in enumerate(doc):
        page_num = idx + 1
        raw_text = page.get_text() or ""
        text = raw_text.strip()
        ocr_applied = False

        if len(text) < OCR_TEXT_THRESHOLD_CHARS and ocr_fallback:
            try:
                pixmap = page.get_pixmap(dpi=150)
                png_bytes = pixmap.tobytes("png")
                ocr_text = _call_vision_ocr(png_bytes)
                if len(ocr_text.strip()) > len(text):
                    text = ocr_text.strip()
                    ocr_applied = True
                    ocr_pages_count += 1
            except Exception as ocr_err:
                logger.warning(f"OCR fallback failed for page {page_num}: {ocr_err}")

        char_count = len(text)
        total_characters += char_count
        page_results.append(PdfPageResult(
            page_number=page_num,
            text=text,
            char_count=char_count,
            ocr_applied=ocr_applied
        ))

        # Generate preview chunks for this page
        if text:
            page_header = f"Page {page_num}"
            chunks_in_page = [text[i:i+chunk_size] for i in range(0, max(len(text), 1), chunk_size - chunk_overlap)]
            for c_idx, c_text in enumerate(chunks_in_page):
                if c_text.strip():
                    preview_chunks.append({
                        "chunk_index": len(preview_chunks),
                        "page_number": page_num,
                        "heading": page_header,
                        "char_count": len(c_text),
                        "preview": c_text[:200] + ("..." if len(c_text) > 200 else "")
                    })

    return PdfExtractionResult(
        filename=filename,
        total_pages=total_pages,
        total_characters=total_characters,
        ocr_pages_count=ocr_pages_count,
        pages=page_results,
        preview_chunks=preview_chunks
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pdf_extractor.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add requirements.txt app/services/pdf_extractor.py tests/test_pdf_extractor.py
git commit -m "feat(pdf): add PyMuPDF extraction service with LiteLLM Vision OCR fallback"
```

---

### Task 3: Two-Stage Preview & Ingestion Endpoints with Storage Indexing

**Files:**
- Modify: `app/api/routers/storage.py`
- Modify: `app/services/local_storage.py`
- Modify: `app/services/indexing/processor.py`
- Test: `tests/test_pdf_storage_api.py`

**Interfaces:**
- Consumes: `pdf_extractor.extract_pdf_pages()`, `storage.save_file()`, `storage.index_file()`
- Produces: `POST /admin/api/storage/pdf/preview`, `POST /admin/api/storage/upload` handling PDFs up to 50MB.

- [ ] **Step 1: Write tests for PDF preview endpoint and PDF storage indexing**

```python
# tests/test_pdf_storage_api.py
import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app
import pymupdf

@pytest.fixture
def client():
    return TestClient(app)

def create_dummy_pdf():
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((50, 50), "ASD-STE100 Rules for Simplified Technical English")
    return doc.tobytes()

def test_pdf_preview_endpoint(client):
    pdf_bytes = create_dummy_pdf()
    files = {"file": ("rules.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    response = client.post("/admin/api/storage/pdf/preview", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "rules.pdf"
    assert data["total_pages"] == 1
    assert "ASD-STE100" in data["pages"][0]["text"]
    assert len(data["sample_chunks"]) >= 1

def test_pdf_upload_and_indexing(client):
    pdf_bytes = create_dummy_pdf()
    files = {"file": ("ste_standard.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"repo": "local_storage", "category": "Standards"}
    
    with patch("app.services.indexing.processor.get_vector_store") as mock_get_store:
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store
        
        response = client.post("/admin/api/storage/upload", files=files, data=data)
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["status"] == "success"
        assert res_data["rel_path"] == "ste_standard.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pdf_storage_api.py -v`
Expected: FAIL (404 on `/admin/api/storage/pdf/preview`)

- [ ] **Step 3: Update `local_storage.py` and `indexing/processor.py` to support `.pdf` files**

In `app/services/local_storage.py`:
- In `save_file_content`: If `rel_path.endswith('.pdf')`, write bytes directly and bypass text string conversion.
- In `index_file`:
  ```python
  if abs_path.endswith(".pdf"):
      from app.services.pdf_extractor import extract_pdf_pages
      pdf_res = extract_pdf_pages(abs_path, filename=os.path.basename(rel_path))
      # Pass combined page contents with page headers into process_file_content
      # or construct VectorDocuments directly per page chunk
      content = "\n\n".join([f"# Page {p.page_number}\n{p.text}" for p in pdf_res.pages])
      doc_type = "doc"
  ```
- In `read_file_content`:
  ```python
  if abs_path.endswith(".pdf"):
      from app.services.pdf_extractor import extract_pdf_pages
      pdf_res = extract_pdf_pages(abs_path, filename=os.path.basename(rel_path), ocr_fallback=False)
      return {
          "status": "success",
          "rel_path": rel_path,
          "content": "\n\n".join([f"--- Page {p.page_number} ---\n{p.text}" for p in pdf_res.pages]),
          "total_pages": pdf_res.total_pages,
          "is_pdf": True
      }
  ```

In `app/services/indexing/processor.py`:
- Adjust `MAX_FILE_SIZE_BYTES`:
  ```python
  from app.services.pdf_extractor import MAX_PDF_SIZE_BYTES
  
  effective_limit = MAX_PDF_SIZE_BYTES if filepath.endswith(".pdf") else MAX_FILE_SIZE_BYTES
  if content and len(content.encode("utf-8")) > effective_limit:
      ...
  ```

- [ ] **Step 4: Implement `/admin/api/storage/pdf/preview` in `app/api/routers/storage.py`**

```python
@router.post("/admin/api/storage/pdf/preview")
async def api_preview_pdf(request: Request):
    try:
        form = await request.form()
        file = form.get("file")
        if not file or not hasattr(file, "read"):
            return JSONResponse(status_code=400, content={"error": "Missing PDF file in upload"})
        
        filename = getattr(file, "filename", "document.pdf")
        if not filename.lower().endswith(".pdf"):
            return JSONResponse(status_code=400, content={"error": "Uploaded file must have .pdf extension"})
            
        content_bytes = await file.read()
        from app.services.pdf_extractor import extract_pdf_pages
        res = extract_pdf_pages(content_bytes, filename=filename, ocr_fallback=True)
        return {
            "filename": res.filename,
            "total_pages": res.total_pages,
            "total_characters": res.total_characters,
            "ocr_pages_count": res.ocr_pages_count,
            "pages": [asdict(p) for p in res.pages],
            "sample_chunks": res.preview_chunks[:25]
        }
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Error previewing PDF: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pdf_storage_api.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/storage.py app/services/local_storage.py app/services/indexing/processor.py tests/test_pdf_storage_api.py
git commit -m "feat(api): add PDF preview endpoint and high-capacity storage ingestion"
```

---

### Task 4: MCP Tool Support for PDF Preview & Inspection

**Files:**
- Modify: `app/mcp/handlers/storage_handlers.py`
- Test: `tests/test_mcp_pdf_tools.py`

**Interfaces:**
- Consumes: `get_local_storage_service()`, `extract_pdf_pages()`
- Produces: `manage_local_file(action="preview", file_path="...")` returning extracted page metrics and sample text.

- [ ] **Step 1: Write test for MCP PDF tool handling**

```python
# tests/test_mcp_pdf_tools.py
import os
import pymupdf
import pytest
from app.mcp.handlers.storage_handlers import handle_manage_local_file
from app.services.local_storage import get_local_storage_service

def test_mcp_preview_pdf():
    storage = get_local_storage_service()
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((50, 50), "Rule 1.1: Use approved words from dictionary.")
    pdf_bytes = doc.tobytes()
    storage.save_file_content("specs/ste_rule.pdf", pdf_bytes)
    
    res = handle_manage_local_file(action="preview", file_path="specs/ste_rule.pdf")
    assert "PDF Preview: specs/ste_rule.pdf" in res
    assert "Total Pages: 1" in res
    assert "Rule 1.1" in res
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_pdf_tools.py -v`
Expected: FAIL (`Unsupported action 'preview'`)

- [ ] **Step 3: Update `app/mcp/handlers/storage_handlers.py`**

In `handle_manage_local_file`:
- Allow `preview` in valid actions: `("upload", "replace", "delete", "read", "preview")`.
- When `action == "preview"`:
  - If `file_path.endswith(".pdf")`, call `extract_pdf_pages()` and format clean markdown response:
    ```
    ### PDF Preview: {file_path}
    - **Total Pages:** {res.total_pages}
    - **Total Characters:** {res.total_characters}
    - **OCR Applied Pages:** {res.ocr_pages_count}
    
    #### Page 1:
    {first_page_text}
    ```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_pdf_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/mcp/handlers/storage_handlers.py tests/test_mcp_pdf_tools.py
git commit -m "feat(mcp): add PDF preview action to manage_local_file"
```

---

### Task 5: Web UI PDF Extraction Preview Modal & Storage Integration

**Files:**
- Create: `frontend/src/PdfPreviewModal.tsx`
- Modify: `frontend/src/Storage.tsx`
- Modify: `frontend/src/types.ts`
- Test: `frontend/src/tests/Storage.test.tsx`

**Interfaces:**
- Consumes: `/admin/api/storage/pdf/preview`, `/admin/api/storage/upload`
- Produces: Interactive modal displaying page selector, OCR indicators, chunk simulator, and confirm ingestion button.

- [ ] **Step 1: Write test for frontend PDF preview interaction**

Add test in `frontend/src/tests/Storage.test.tsx` verifying:
- Selecting a `.pdf` file triggers preview modal.
- Shows page count, text preview, and "Confirm & Ingest" button.

- [ ] **Step 2: Create `frontend/src/PdfPreviewModal.tsx`**

Modal features:
- Tabs for "Page-by-Page View" and "Vector Chunks".
- Page selector dropdown / next-previous arrows.
- Highlight badge when `ocr_applied: true`.
- "Confirm & Ingest to Vector DB" button which submits the stored file via `fetch('/admin/api/storage/upload')`.

- [ ] **Step 3: Integrate `PdfPreviewModal` into `Storage.tsx`**

- Update file input to `accept=".md,.markdown,.txt,.json,.yaml,.yml,.pdf"`.
- When user drops/selects a `.pdf`, intercept submission and open `PdfPreviewModal`.
- Display PDF red badge icon (`fa-file-pdf`) in the storage table.

- [ ] **Step 4: Build frontend assets**

Run: `npm --prefix frontend run build`
Expected: Successful build generating `frontend/dist/`.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat(ui): add PDF preview extraction modal and table icons"
```

---

### Task 6: Full Regression Verification & Live Homelab Testing

**Files:**
- Test: Full backend test suite `pytest`
- Test: Frontend tests `npm --prefix frontend test`

- [ ] **Step 1: Run full pytest suite**

Run: `pytest`
Expected: All 465+ tests PASS.

- [ ] **Step 2: Run frontend tests and linter**

Run: `npm --prefix frontend test` and `npm --prefix frontend run build`
Expected: All tests PASS and build succeeds.

- [ ] **Step 3: Test with ASD-STE100 sample document**

Upload or index a sample ASD-STE100 PDF specification page through the `/admin/api/storage/pdf/preview` endpoint and verify page extraction accuracy and chunking.

- [ ] **Step 4: Commit and finalize**

```bash
git add -A
git commit -m "chore: complete health check fix and PDF ingestion with preview"
```

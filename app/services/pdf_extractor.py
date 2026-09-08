import os
import io
import base64
import logging
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Union, Optional
import pymupdf
from openai import OpenAI
from app.services.database import get_vision_ocr_model

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


def _call_vision_ocr(png_bytes: bytes, model_name: Optional[str] = None) -> str:
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

    active_model = model_name or get_vision_ocr_model()

    response = client.chat.completions.create(
        model=active_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Please transcribe this page."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        max_tokens=4096,
        temperature=0.0,
    )
    if response.choices and len(response.choices) > 0:
        return response.choices[0].message.content or ""
    return ""


def extract_pdf_pages(
    source: Union[str, bytes],
    filename: str = "document.pdf",
    ocr_fallback: bool = True,
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
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

    try:
        total_pages = len(doc)
        page_results: List[PdfPageResult] = []
        ocr_pages_count = 0
        total_characters = 0
        preview_chunks: List[Dict[str, Any]] = []

        step = max(chunk_size - chunk_overlap, 1)

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
            page_results.append(
                PdfPageResult(
                    page_number=page_num,
                    text=text,
                    char_count=char_count,
                    ocr_applied=ocr_applied,
                )
            )

            # Generate preview chunks for this page
            if text:
                page_header = f"Page {page_num}"
                chunks_in_page = [
                    text[i : i + chunk_size]
                    for i in range(0, max(len(text), 1), step)
                ]
                for c_text in chunks_in_page:
                    if c_text.strip():
                        preview_chunks.append(
                            {
                                "chunk_index": len(preview_chunks),
                                "page_number": page_num,
                                "heading": page_header,
                                "char_count": len(c_text),
                                "preview": c_text[:200] + ("..." if len(c_text) > 200 else ""),
                            }
                        )

        return PdfExtractionResult(
            filename=filename,
            total_pages=total_pages,
            total_characters=total_characters,
            ocr_pages_count=ocr_pages_count,
            pages=page_results,
            preview_chunks=preview_chunks,
        )
    finally:
        doc.close()

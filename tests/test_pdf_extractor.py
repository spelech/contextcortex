import os
import pytest
import pymupdf
from unittest.mock import patch, MagicMock

from app.services.pdf_extractor import (
    extract_pdf_pages,
    PdfExtractionResult,
    PdfPageResult,
)


def create_sample_pdf(pages_text: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            page.insert_text((50, 50), text)
    return doc.tobytes()


def test_extract_digital_pdf_text():
    pdf_bytes = create_sample_pdf([
        "ASD-STE100 Section 1: Overview and Specifications",
        "ASD-STE100 Section 2: Approved Words and Dictionary",
    ])
    res = extract_pdf_pages(pdf_bytes, filename="ste100.pdf", ocr_fallback=False)

    assert isinstance(res, PdfExtractionResult)
    assert res.total_pages == 2
    assert res.ocr_pages_count == 0
    assert "Overview" in res.pages[0].text
    assert res.pages[0].page_number == 1
    assert res.pages[0].ocr_applied is False
    assert "Approved Words" in res.pages[1].text
    assert res.pages[1].page_number == 2
    assert res.pages[1].ocr_applied is False
    assert len(res.preview_chunks) >= 2
    assert res.to_dict()["total_pages"] == 2


def test_extract_scanned_pdf_triggers_vision_ocr():
    # Empty page (< 50 chars) triggers fallback when ocr_fallback=True
    pdf_bytes = create_sample_pdf([""])

    with patch("app.services.pdf_extractor._call_vision_ocr", return_value="Transcribed STE rule text via OCR") as mock_ocr:
        res = extract_pdf_pages(pdf_bytes, filename="scanned.pdf", ocr_fallback=True)
        assert mock_ocr.called
        assert res.total_pages == 1
        assert res.ocr_pages_count == 1
        assert res.pages[0].ocr_applied is True
        assert "Transcribed STE rule text via OCR" in res.pages[0].text


def test_extract_corrupted_pdf_raises_value_error():
    with pytest.raises(ValueError, match="Invalid or corrupted PDF"):
        extract_pdf_pages(b"not a real pdf content", filename="corrupt.pdf")


def test_extract_nonexistent_file_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        extract_pdf_pages("/nonexistent/path/to/missing.pdf")


def test_extract_real_pdf_asd_ste100():
    real_pdf_path = "/drives/nfs/ASD-STE100_ISSUE9.pdf"
    if not os.path.exists(real_pdf_path):
        pytest.skip(f"Real PDF file not found at {real_pdf_path}")

    res = extract_pdf_pages(real_pdf_path, filename="ASD-STE100_ISSUE9.pdf", ocr_fallback=False)

    assert isinstance(res, PdfExtractionResult)
    assert res.total_pages == 434
    assert res.pages[0].page_number == 1
    # Check that ASD-STE100 appears in the document text
    all_text = " ".join(page.text for page in res.pages[:10])
    assert "ASD-STE100" in all_text or "STE100" in all_text
    assert len(res.preview_chunks) > 0


def test_call_vision_ocr_unit():
    from app.services.pdf_extractor import _call_vision_ocr

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Recognized Table Content"
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("app.services.pdf_extractor.OpenAI", return_value=mock_client):
        ocr_result = _call_vision_ocr(b"fake_png_bytes")
        assert ocr_result == "Recognized Table Content"
        mock_client.chat.completions.create.assert_called_once()


def test_extract_pdf_ocr_failure_graceful_recovery():
    pdf_bytes = create_sample_pdf([""])
    with patch("app.services.pdf_extractor._call_vision_ocr", side_effect=RuntimeError("Vision model timed out")):
        res = extract_pdf_pages(pdf_bytes, filename="fallback_fail.pdf", ocr_fallback=True)
        assert res.total_pages == 1
        assert res.ocr_pages_count == 0
        assert res.pages[0].ocr_applied is False
        assert res.pages[0].text == ""


def test_extract_oversized_pdf_raises_value_error(tmp_path):
    with patch("app.services.pdf_extractor.MAX_PDF_SIZE_BYTES", 100):
        with pytest.raises(ValueError, match="exceeds size limit"):
            extract_pdf_pages(b"a" * 200, filename="large.pdf")

        large_file = tmp_path / "large.pdf"
        large_file.write_bytes(b"a" * 200)
        with pytest.raises(ValueError, match="exceeds size limit"):
            extract_pdf_pages(str(large_file), filename="large.pdf")

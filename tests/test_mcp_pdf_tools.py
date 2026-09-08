import os
import pymupdf
import pytest
from app.mcp.handlers.storage_handlers import handle_manage_local_file
from app.services.auth import set_current_auth_context, AuthContext, Role
from app.services.local_storage import LocalStorageService
import app.services.local_storage as ls_mod


def create_sample_pdf(text: str = "ASD-STE100 Rules for Simplified Technical English.\nRule 1.1: Use approved words from dictionary.") -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), text)
    return doc.tobytes()


@pytest.fixture
def storage_env(tmp_path, monkeypatch):
    storage = LocalStorageService(storage_root=str(tmp_path))
    monkeypatch.setattr(ls_mod, "_storage_service", storage)
    return storage


@pytest.mark.asyncio
async def test_mcp_manage_local_file_preview_pdf(storage_env):
    pdf_bytes = create_sample_pdf()
    storage_env.save_file_content("sample.pdf", pdf_bytes)

    set_current_auth_context(AuthContext(role=Role.VIEWER))
    res = await handle_manage_local_file(action="preview", file_path="sample.pdf")

    assert "### PDF Extraction Preview: sample.pdf" in res
    assert "**Total Pages:** 1" in res
    assert "**Total Characters:**" in res
    assert "**OCR Applied Pages:** 0" in res
    assert "**Sample Chunks:**" in res
    assert "#### Page 1:" in res
    assert "ASD-STE100 Rules" in res


@pytest.mark.asyncio
async def test_mcp_manage_local_file_read_pdf(storage_env):
    pdf_bytes = create_sample_pdf()
    storage_env.save_file_content("sample.pdf", pdf_bytes)

    set_current_auth_context(AuthContext(role=Role.VIEWER))
    res = await handle_manage_local_file(action="read", file_path="sample.pdf")

    assert "# Page 1" in res
    assert "Rule 1.1: Use approved words from dictionary." in res


@pytest.mark.asyncio
async def test_mcp_manage_local_file_preview_markdown(storage_env):
    md_content = "# System Architecture\nThis is line 2.\nThis is line 3."
    storage_env.save_file_content("doc.md", md_content)

    set_current_auth_context(AuthContext(role=Role.VIEWER))
    res = await handle_manage_local_file(action="preview", file_path="doc.md")

    assert "### File Preview: doc.md" in res
    assert "**Line Count:** 3" in res
    assert "**Character Count:**" in res
    assert "# System Architecture" in res


@pytest.mark.asyncio
async def test_mcp_manage_local_file_preview_nonexistent(storage_env):
    set_current_auth_context(AuthContext(role=Role.VIEWER))
    res = await handle_manage_local_file(action="preview", file_path="missing.pdf")

    assert "Error executing manage_local_file" in res or "Error:" in res
    assert "does not exist" in res or "not found" in res


@pytest.mark.asyncio
async def test_mcp_manage_local_file_preview_missing_path(storage_env):
    set_current_auth_context(AuthContext(role=Role.VIEWER))
    res = await handle_manage_local_file(action="preview", file_path="")

    assert "Error:" in res or "Error executing manage_local_file" in res

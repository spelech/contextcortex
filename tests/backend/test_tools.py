import pytest
from unittest.mock import patch, MagicMock
from app.mcp.tools import get_tools, get_resources, get_prompts

@pytest.mark.asyncio
async def test_get_tools():
    with patch("app.mcp.tools.get_dynamic_catalog_description", return_value="Test desc"):
        tools = await get_tools()
        assert len(tools) > 0
        names = [t.name for t in tools]
        assert "search_code" in names
        assert "search_docs" in names

@pytest.mark.asyncio
async def test_get_resources():
    resources = await get_resources()
    assert len(resources) > 0
    assert str(resources[0].uri) == "notes://catalog/summary"

@pytest.mark.asyncio
async def test_get_prompts():
    with patch("app.mcp.tools.get_db_connection") as mock_conn:
        mock_db = MagicMock()
        mock_conn.return_value.__enter__.return_value = mock_db
        mock_db.execute.return_value.fetchall.return_value = [
            {"name": "test", "description": "test desc", "arguments_json": "[]"}
        ]
        prompts = await get_prompts()
        assert len(prompts) == 1
        assert prompts[0].name == "test"

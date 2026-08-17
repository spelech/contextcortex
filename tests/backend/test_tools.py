import pytest
import json
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
        assert "find_symbol" in names
        assert "get_file_outline" in names
        assert "list_repositories" in names
        assert "sync_repository" in names
        assert "index_status" in names

@pytest.mark.asyncio
async def test_get_resources():
    resources = await get_resources()
    assert len(resources) > 0
    assert str(resources[0].uri) == "notes://catalog/summary"

@pytest.mark.asyncio
async def test_get_prompts():
    # Valid prompts with arguments and malformed arguments
    with patch("app.mcp.tools.get_db_connection") as mock_conn:
        mock_db = MagicMock()
        mock_conn.return_value.__enter__.return_value = mock_db
        mock_db.execute.return_value.fetchall.return_value = [
            {
                "name": "prompt_a",
                "description": "desc a",
                "arguments_json": json.dumps([{"name": "arg1", "description": "arg1 desc", "required": True}])
            },
            {
                "name": "prompt_b",
                "description": "desc b",
                "arguments_json": "corrupted_json_string{"
            }
        ]
        prompts = await get_prompts()
        assert len(prompts) == 2
        assert prompts[0].name == "prompt_a"
        assert len(prompts[0].arguments) == 1
        assert prompts[0].arguments[0].name == "arg1"
        assert prompts[1].name == "prompt_b"

    # Prompts DB error
    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Prompts DB down")):
        prompts_err = await get_prompts()
        assert prompts_err == []

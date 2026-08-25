import pytest
from unittest.mock import patch
from app.mcp.mcp_server import mcp_server
from app.services.indexing import get_dynamic_catalog_description

@pytest.mark.asyncio
async def test_dynamic_catalog_description():
    with patch("app.services.database.get_db_connection") as mock_conn:
        mock_db = mock_conn.return_value.__enter__.return_value
        mock_db.execute.return_value.fetchall.return_value = [
            {"name": "repo1", "url": "https://github.com/org/repo1", "status": "synced"}
        ]
        desc = get_dynamic_catalog_description()
        assert isinstance(desc, str)

@pytest.mark.asyncio
async def test_mcp_server_tools_list():
    tools = await mcp_server.list_tools()
    assert len(tools) >= 7
    names = [t.name for t in tools]
    assert "search_code" in names
    assert "search_docs" in names
    assert "find_symbol" in names
    assert "get_file_outline" in names
    assert "list_repositories" in names
    assert "sync_repository" in names
    assert "index_status" in names

@pytest.mark.asyncio
async def test_mcp_server_resources_list():
    resources = await mcp_server.list_resources()
    assert len(resources) >= 1
    uris = [str(r.uri) for r in resources]
    assert "knowledge://catalog/summary" in uris


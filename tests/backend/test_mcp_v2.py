import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
from pydantic import AnyUrl

from app.mcp.mcp_server import mcp_server
from app.mcp.tools import register_mcp_tools_and_resources
from app.services.db import init_db, get_db_connection, set_metadata
from main import app, lifespan


@pytest.fixture
def temp_mcp_db(tmp_path):
    db_file = str(tmp_path / "test_mcp_rag.db")
    with patch("app.services.db.CACHE_DB_PATH", db_file):
        init_db()
        yield db_file


@pytest.mark.asyncio
async def test_fastmcp_tools_registered():
    tools = await mcp_server.list_tools()
    tool_names = [t.name for t in tools]
    assert "search_code" in tool_names
    assert "search_docs" in tool_names
    assert "find_symbol" in tool_names
    assert "get_file_outline" in tool_names
    assert "list_repositories" in tool_names
    assert "sync_repository" in tool_names
    assert "index_status" in tool_names


@pytest.mark.asyncio
async def test_fastmcp_resources_and_prompts():
    resources = await mcp_server.list_resources()
    assert any(str(r.uri) == "knowledge://catalog/summary" for r in resources)

    prompts = await mcp_server.list_prompts()
    prompt_names = [p.name for p in prompts]
    assert "search_infrastructure_docs" in prompt_names
    assert "find_implementation_symbol" in prompt_names


@pytest.mark.asyncio
async def test_fastmcp_tool_execution(temp_mcp_db):
    mock_hit = MagicMock()
    mock_hit.score = 0.08
    mock_hit.payload = {
        "repo": "demo-repo",
        "rel_path": "main.py",
        "start_line": 1,
        "end_line": 10,
        "symbol": "main",
        "github_url": "https://github.com/demo/main.py",
        "language": "python",
        "content": "def main(): pass"
    }

    with patch("app.mcp.tools.execute_hybrid_search", return_value=[mock_hit]):
        res, structured = await mcp_server.call_tool("search_code", {"query": "main entry point"})
        assert len(res) == 1
        assert "main.py" in res[0].text
        assert "demo-repo" in res[0].text


@pytest.mark.asyncio
async def test_fastmcp_resource_read(temp_mcp_db):
    contents = await mcp_server.read_resource(AnyUrl("knowledge://catalog/summary"))
    assert len(contents) > 0
    assert "Repository & Documentation Catalog" in contents[0].content



@pytest.mark.asyncio
async def test_fastmcp_prompt_get():
    p1 = await mcp_server.get_prompt("search_infrastructure_docs", {"topic": "kubernetes"})
    assert len(p1.messages) == 1
    assert "kubernetes" in p1.messages[0].content.text

    p2 = await mcp_server.get_prompt("find_implementation_symbol", {"symbol": "FastMCP", "repo": "mcp-core"})
    assert len(p2.messages) == 1
    assert "FastMCP" in p2.messages[0].content.text


@pytest.mark.asyncio
async def test_fastmcp_streamable_http_transport():
    async with lifespan(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
            resp = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest-client", "version": "1.0"}
                    },
                    "id": 1
                },
                headers={"accept": "application/json, text/event-stream"}
            )
            assert resp.status_code == 200
            assert "knowledge-rag-mcp" in resp.text

import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
from pydantic import AnyUrl

from app.mcp.mcp_server import mcp_server
from app.mcp.tools import register_mcp_tools_and_resources
from app.services.database import init_db, get_db_connection, set_metadata
from main import app, lifespan


@pytest.fixture
def temp_mcp_db(tmp_path):
    db_file = str(tmp_path / "test_mcp_rag.db")
    with patch("app.services.database.CACHE_DB_PATH", db_file):
        init_db()
        yield db_file
        from app.services.database.engine import dispose_global_engine
        dispose_global_engine()


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
    import json
    mock_hit = MagicMock()
    mock_hit.score = 0.08
    mock_hit.dense_score = None
    mock_hit.sparse_score = None
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
        data = json.loads(res[0].text)
        assert data["results"][0]["file"] == "main.py"
        assert data["results"][0]["repo"] == "demo-repo"
        assert data["results"][0]["score"] == 0.08


@pytest.mark.asyncio
async def test_fastmcp_resource_read(temp_mcp_db):
    import json
    contents = await mcp_server.read_resource(AnyUrl("knowledge://catalog/summary"))
    assert len(contents) > 0
    data = json.loads(contents[0].content)
    assert "total_files" in data
    assert "git_repositories" in data



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
            assert "ContextCortex" in resp.text


@pytest.mark.asyncio
async def test_search_code_with_dense_weight_and_score_breakdown(temp_mcp_db):
    import json
    mock_hit = MagicMock()
    mock_hit.score = 0.82
    mock_hit.dense_score = 0.88
    mock_hit.sparse_score = 0.74
    mock_hit.payload = {
        "repo": "demo-repo",
        "rel_path": "services/auth.py",
        "start_line": 20,
        "end_line": 35,
        "symbol": "AuthService.login",
        "signature": "def login(self, username: str, password: str) -> Token:",
        "kind": "method_declaration",
        "github_url": "https://github.com/demo/auth.py#L20-L35",
        "language": "python",
        "content": "def login(...): return token"
    }

    with patch("app.mcp.tools.execute_hybrid_search", return_value=[mock_hit]) as mock_exec:
        res, structured = await mcp_server.call_tool(
            "search_code",
            {"query": "user login", "dense_weight": 0.6, "mode": "hybrid"}
        )
        assert len(res) == 1
        data = json.loads(res[0].text)
        hit = data["results"][0]
        assert hit["file"] == "services/auth.py"
        assert hit["symbol"] == "AuthService.login"
        assert "def login(self, username: str, password: str)" in hit["signature"]
        assert hit["dense_score"] == 0.88
        assert hit["sparse_score"] == 0.74
        mock_exec.assert_called_once_with(
            query_text="user login",
            doc_type="code",
            repo=None,
            language=None,
            limit=5,
            dense_weight=0.6,
            search_mode="hybrid"
        )

@pytest.mark.asyncio
async def test_search_code_empty_and_missing_ast_boundaries(temp_mcp_db):
    import json
    # 1. Empty results returns empty results list in JSON
    with patch("app.mcp.tools.execute_hybrid_search", return_value=[]):
        res, _ = await mcp_server.call_tool("search_code", {"query": "nonexistent_func"})
        data = json.loads(res[0].text)
        assert data["query"] == "nonexistent_func"
        assert data["results"] == []

    # 2. Hit without AST signature/symbol renders cleanly without crashing
    mock_hit_no_ast = MagicMock()
    mock_hit_no_ast.score = 0.70
    mock_hit_no_ast.dense_score = 0.70
    mock_hit_no_ast.sparse_score = 0.0
    mock_hit_no_ast.payload = {
        "repo": "raw-repo",
        "rel_path": "scripts/build.sh",
        "start_line": 1,
        "end_line": 10,
        "symbol": None,
        "signature": None,
        "content": "#!/usr/bin/env bash\necho 'building'"
    }
    with patch("app.mcp.tools.execute_hybrid_search", return_value=[mock_hit_no_ast]):
        res, _ = await mcp_server.call_tool("search_code", {"query": "build.sh"})
        assert len(res) == 1
        data = json.loads(res[0].text)
        hit = data["results"][0]
        assert hit["file"] == "scripts/build.sh"
        assert "echo 'building'" in hit["content"]
        assert hit["signature"] is None

@pytest.mark.asyncio
async def test_search_docs_with_dense_weight_and_score_breakdown(temp_mcp_db):
    import json
    mock_doc = MagicMock()
    mock_doc.score = 0.82
    mock_doc.dense_score = 0.80
    mock_doc.sparse_score = 0.85
    mock_doc.payload = {
        "repo": "docs-repo",
        "rel_path": "docs/architecture.md",
        "title": "Architecture Guide",
        "heading": "Microservices",
        "start_line": 12,
        "end_line": 30,
        "content": "ContextCortex microservices routing and gateways"
    }

    with patch("app.mcp.tools.execute_hybrid_search", return_value=[mock_doc]) as mock_exec:
        res, _ = await mcp_server.call_tool(
            "search_docs",
            {"query": "microservices", "dense_weight": 0.4, "mode": "lexical"}
        )
        assert len(res) == 1
        data = json.loads(res[0].text)
        hit = data["results"][0]
        assert hit["file"] == "docs/architecture.md"
        assert hit["heading"] == "Microservices"
        assert hit["score"] == 0.82
        assert hit["dense_score"] == 0.8
        assert hit["sparse_score"] == 0.85
        mock_exec.assert_called_once_with(
            query_text="microservices",
            doc_type="doc",
            repo=None,
            category=None,
            tag=None,
            limit=5,
            dense_weight=0.4,
            search_mode="lexical"
        )


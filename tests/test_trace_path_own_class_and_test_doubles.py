"""trace_path follows calls to the own class and ignores test doubles (fakes in test projects)."""

import json
from unittest.mock import patch

import pytest

from app.services.chunking import extract_symbols_and_chunks
from app.services.chunking.route_specificity import is_test_route_file
from app.services.chunking.tree_sitter_loader import get_tree_sitter_parser
from app.services.search import trace_symbol_path
from tests.test_multilanguage_cs_ts_py import _conn_factory, _setup_sqlite_repo

pytestmark = pytest.mark.skipif(get_tree_sitter_parser("c_sharp") is None, reason="needs the C# tree-sitter grammar")

CONTROLLER = """\
public class ToolsController
{
    private readonly ToolService _toolService;
    public async Task<IActionResult> PublishInstance(Guid id) { return Ok(await _toolService.PublishInstance(id)); }
}
"""
SERVICE = """\
public class ToolService
{
    private readonly IToolInstanceReader _reader;
    private readonly ToolSuperRepository _toolRepository;

    public async Task<int> PublishInstance(Guid id)
    {
        var transaction = _toolRepository.SqlConnection.BeginTransaction();
        var tool = await GetByInstanceId(id, transaction);
        transaction.Commit();
        return tool;
    }

    public async Task<int> GetByInstanceId(Guid id, IDbTransaction transaction)
    {
        return await _reader.GetByInstanceId(id, transaction);
    }
}
"""
READER = """\
public interface IToolInstanceReader
{
    Task<int> GetByInstanceId(Guid id, IDbTransaction transaction);
}

public sealed class ToolInstanceReader(ToolSuperRepository toolRepository) : IToolInstanceReader
{
    public async Task<int> GetAccessPreflightAsync(Guid id)
    {
        return await toolRepository.GetToolAccessPreflight(id);
    }

    public async Task<int> GetByInstanceId(Guid id, IDbTransaction transaction)
    {
        var access = await this.GetAccessPreflightAsync(id);
        return access;
    }
}
"""
REPOSITORY = """\
public class ToolSuperRepository
{
    public Task<int> GetToolAccessPreflight(Guid id) => Task.FromResult(1);
}
"""
TEST_DOUBLES = """\
public sealed class FakeToolInstanceReader : IToolInstanceReader
{
    public Task<int> GetByInstanceId(Guid id, IDbTransaction transaction) => Task.FromResult(0);
}

public sealed class RecordingTransaction
{
    public void Commit() { }
}
"""


def test_test_projects_and_folders_count_as_test_code():
    assert is_test_route_file("server/App.Tests/Services_V2/FakeToolInstanceReader.cs")
    assert is_test_route_file("server/Orchestrator/Unit Tests/Complex/Routing_Tests.cs")
    assert is_test_route_file("server/App/Services/ToolServiceTest.cs")
    assert not is_test_route_file("server/App/Services/ToolService.cs")
    assert not is_test_route_file("server/App/Contests/Scoreboard.cs")


def test_calls_without_a_receiver_get_the_own_class():
    targets = {r.target_symbol for r in extract_symbols_and_chunks(SERVICE, "ToolService.cs", repo="r").relationships
               if r.relationship_type == "CALLS"}
    assert "ToolService.GetByInstanceId" in targets
    reader_targets = {r.target_symbol for r in extract_symbols_and_chunks(READER, "ToolInstanceReader.cs", repo="r").relationships
                      if r.relationship_type == "CALLS"}
    assert "ToolInstanceReader.GetAccessPreflightAsync" in reader_targets  # this.Method()
    assert "ToolSuperRepository.GetToolAccessPreflight" in reader_targets  # primary-constructor parameter


def test_a_method_the_class_does_not_declare_stays_bare():
    source = "public class A : Base { public void Run() { Inherited(); Local(); void Local() { } } }"
    targets = {r.target_symbol for r in extract_symbols_and_chunks(source, "A.cs", repo="r").relationships
               if r.relationship_type == "CALLS"}
    assert "Inherited" in targets and "A.Inherited" not in targets


@pytest.fixture
def tool_publish_db(tmp_path):
    db_path = str(tmp_path / "tool_publish.db")
    _setup_sqlite_repo(db_path, "hub", [
        ("server/App/Controllers/ToolsController.cs", CONTROLLER),
        ("server/App/Services/ToolService.cs", SERVICE),
        ("server/App/Services/ToolInstanceReader.cs", READER),
        ("server/Data/ToolSuperRepository.cs", REPOSITORY),
        ("server/App.Tests/Services/TestDoubles.cs", TEST_DOUBLES),
    ])
    return _conn_factory(db_path)


def _walk(nodes, key):
    for node in nodes:
        yield node["symbol"]
        yield from _walk(node.get(key) or [], key)


def test_trace_reaches_the_repository_through_own_class_calls_and_the_real_implementation(tool_publish_db):
    with patch("app.services.search.get_db_connection", side_effect=tool_publish_db):
        down = json.loads(trace_symbol_path("ToolsController.PublishInstance", repo="hub", direction="callees", depth=5))
        up = json.loads(trace_symbol_path("ToolSuperRepository.GetToolAccessPreflight", repo="hub", direction="callers", depth=5))
    reached = list(_walk(down["callees"], "callees"))
    assert "ToolService.GetByInstanceId" in reached
    assert "ToolInstanceReader.GetByInstanceId" in reached
    assert "ToolInstanceReader.GetAccessPreflightAsync" in reached
    assert "ToolSuperRepository.GetToolAccessPreflight" in reached
    assert not [s for s in reached if "Fake" in s or "RecordingTransaction" in s], reached
    callers = list(_walk(up["callers"], "callers"))
    assert callers[:2] == ["ToolInstanceReader.GetAccessPreflightAsync", "ToolInstanceReader.GetByInstanceId"]
    assert "ToolsController.PublishInstance" in callers

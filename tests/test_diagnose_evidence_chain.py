"""diagnose_issue returns a ranked call chain with evidence lines (from the entry point to the likely fault)."""

import asyncio
import json
from unittest.mock import patch

import pytest

from app.mcp.handlers.diagnostic_handlers import handle_diagnose_issue
from app.services.database import get_db_connection
from app.services.database.engine import get_db_engine, init_db
from app.services.diagnostic_error_terms import extract_error_terms, line_term_hits
from app.services.diagnostics import diagnose_issue
from app.services.file_reader import reset_file_reader_service

REPO = "shop"
ISSUE = (
    "Publishing a tool fails. `POST /api/v2/Tools/{id}/publish` returns HTTP 500. The API log shows:\n"
    "System.InvalidOperationException: ExecuteReader requires the command to have a transaction when the "
    "connection assigned to the command is in a pending local transaction."
)

# Controller -> service (opens a transaction) -> reader (through an interface) -> GetAccess drops the
# transaction -> repository query. A logger interface with two implementations must not be followed.
SOURCES = {
    "Controllers/ToolsController.cs": """public class ToolsController
{
    public async Task<IActionResult> PublishInstance(Guid id)
    {
        _logger.LogWarning("publishing");
        var saved = await _toolService.PublishInstance(id);
        return Ok(saved);
    }
}
""",
    "Services/ToolService.cs": """public class ToolService : IToolService
{
    public async Task<ToolDTO> PublishInstance(Guid id)
    {
        using (var transaction = _repo.SqlConnection.BeginTransaction())
        {
            var tool = await GetByInstanceId(id, transaction);
            await _repo.SaveVersion(id, transaction);
            transaction.Commit();
            return tool;
        }
    }

    public Task<ToolDTO> GetByInstanceId(Guid id, IDbTransaction transaction = null) =>
        _reader.GetByInstanceId(id, transaction);
}
""",
    "Services/IToolReader.cs": """public interface IToolReader
{
    Task<ToolDTO> GetByInstanceId(Guid id, IDbTransaction transaction = null);
}
""",
    "Services/ToolReader.cs": """public class ToolReader : IToolReader
{
    public async Task<ToolDTO> GetByInstanceId(Guid id, IDbTransaction transaction = null)
    {
        var access = await GetAccess(id);
        return await _repo.GetTool(id, transaction);
    }

    public async Task<bool> GetAccess(Guid id)
    {
        var rows = await _repo.GetToolAccess(id);
        return rows.Any();
    }
}
""",
    "Data/ToolRepository.cs": """public class ToolRepository
{
    public async Task<IEnumerable<Row>> GetToolAccess(Guid id, IDbTransaction transaction = null)
    {
        var command = new CommandDefinition("GetToolAccess", new { id }, transaction: transaction);
        return await _connection.QueryAsync<Row>(command);
    }

    public async Task<ToolDTO> GetTool(Guid id, IDbTransaction transaction = null)
    {
        var command = new CommandDefinition("GetTool", new { id }, transaction: transaction);
        return await _connection.QuerySingleAsync<ToolDTO>(command);
    }

    public async Task SaveVersion(Guid id, IDbTransaction transaction = null)
    {
        var command = new CommandDefinition("SaveVersion", new { id }, transaction: transaction);
        await _connection.ExecuteAsync(command);
    }
}
""",
    "Logging/AppLogger.cs": """public interface IAppLogger
{
    void LogWarning(string message);
}
public class AppLogger : IAppLogger
{
    public void LogWarning(string message) { _sink.Write(message); }
}
public class ConsoleLogger : IAppLogger
{
    public void LogWarning(string message) { Console.WriteLine(message); }
}
""",
    "Tests/FakeToolReader.cs": """public class FakeToolReader : IToolReader
{
    public Task<ToolDTO> GetByInstanceId(Guid id, IDbTransaction transaction = null) => Task.FromResult(new ToolDTO());
}
""",
}

SYMBOLS = [
    ("Controllers/ToolsController.cs", "ToolsController", "ToolsController", "class_declaration", 1, 9),
    ("Controllers/ToolsController.cs", "PublishInstance", "ToolsController.PublishInstance", "method_declaration", 3, 8),
    ("Services/ToolService.cs", "PublishInstance", "ToolService.PublishInstance", "method_declaration", 3, 12),
    ("Services/ToolService.cs", "GetByInstanceId", "ToolService.GetByInstanceId", "method_declaration", 14, 15),
    ("Services/IToolReader.cs", "IToolReader", "IToolReader", "interface_declaration", 1, 4),
    ("Services/IToolReader.cs", "GetByInstanceId", "IToolReader.GetByInstanceId", "method_declaration", 3, 3),
    ("Services/ToolReader.cs", "GetByInstanceId", "ToolReader.GetByInstanceId", "method_declaration", 3, 7),
    ("Services/ToolReader.cs", "GetAccess", "ToolReader.GetAccess", "method_declaration", 9, 13),
    ("Data/ToolRepository.cs", "GetToolAccess", "ToolRepository.GetToolAccess", "method_declaration", 3, 7),
    ("Data/ToolRepository.cs", "GetTool", "ToolRepository.GetTool", "method_declaration", 9, 13),
    ("Data/ToolRepository.cs", "SaveVersion", "ToolRepository.SaveVersion", "method_declaration", 15, 19),
    ("Logging/AppLogger.cs", "IAppLogger", "IAppLogger", "interface_declaration", 1, 4),
    ("Logging/AppLogger.cs", "LogWarning", "IAppLogger.LogWarning", "method_declaration", 3, 3),
    ("Logging/AppLogger.cs", "LogWarning", "AppLogger.LogWarning", "method_declaration", 7, 7),
    ("Logging/AppLogger.cs", "LogWarning", "ConsoleLogger.LogWarning", "method_declaration", 11, 11),
    ("Tests/FakeToolReader.cs", "GetByInstanceId", "FakeToolReader.GetByInstanceId", "method_declaration", 3, 3),
]
CALLS = [
    ("Controllers/ToolsController.cs", "PublishInstance", "IAppLogger.LogWarning", 5),
    ("Controllers/ToolsController.cs", "PublishInstance", "ToolService.PublishInstance", 6),
    ("Controllers/ToolsController.cs", "PublishInstance", "Ok", 7),
    ("Services/ToolService.cs", "PublishInstance", "BeginTransaction", 5),
    ("Services/ToolService.cs", "PublishInstance", "GetByInstanceId", 7),
    ("Services/ToolService.cs", "PublishInstance", "ToolRepository.SaveVersion", 8),
    ("Services/ToolService.cs", "PublishInstance", "Commit", 9),
    ("Services/ToolService.cs", "GetByInstanceId", "IToolReader.GetByInstanceId", 15),
    ("Services/ToolReader.cs", "GetByInstanceId", "GetAccess", 5),
    ("Services/ToolReader.cs", "GetByInstanceId", "ToolRepository.GetTool", 6),
    ("Services/ToolReader.cs", "GetAccess", "ToolRepository.GetToolAccess", 11),
    ("Services/ToolReader.cs", "GetAccess", "Any", 12),
    ("Data/ToolRepository.cs", "GetToolAccess", "QueryAsync", 6),
    ("Data/ToolRepository.cs", "GetTool", "QuerySingleAsync", 12),
    ("Data/ToolRepository.cs", "SaveVersion", "ExecuteAsync", 18),
]
IMPLEMENTS = [("ToolReader", "IToolReader", "Services/ToolReader.cs"), ("AppLogger", "IAppLogger", "Logging/AppLogger.cs"),
              ("ConsoleLogger", "IAppLogger", "Logging/AppLogger.cs"), ("FakeToolReader", "IToolReader", "Tests/FakeToolReader.cs")]


@pytest.fixture
def chain_db(tmp_path, monkeypatch):
    src = tmp_path / "shop"
    for rel, text in SOURCES.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text, encoding="utf-8")
    db_file = tmp_path / "chain.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))
    reset_file_reader_service()

    def abs_path(rel):
        return str(src / rel)

    with get_db_connection() as conn:
        conn.execute("INSERT INTO indexed_paths (path, type, recursive, category, repo) VALUES (?, 'directory', 1, 'code', ?)",
                     (str(src), REPO))
        ids = {}
        for rel, name, full, kind, start, end in SYMBOLS:
            ids[(rel, name)] = conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'c_sharp')",
                (REPO, abs_path(rel), name, full, kind, start, end, name),
            ).lastrowid
        for rel, source, target, line in CALLS:
            conn.execute(
                "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, "
                "relationship_type, line_number) VALUES (?, ?, ?, ?, ?, 'CALLS', ?)",
                (REPO, ids[(rel, source)], abs_path(rel), source, target, line),
            )
        for cls, iface, rel in IMPLEMENTS:
            conn.execute(
                "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
                "VALUES (?, ?, ?, ?, 'IMPLEMENTS', 1)",
                (REPO, abs_path(rel), cls, iface),
            )
        conn.execute(
            "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) "
            "VALUES (?, ?, 'aspnet', 'POST', '/api/v2/tools/{id}/publish', 'ToolsController.PublishInstance', 3, 8)",
            (REPO, abs_path("Controllers/ToolsController.cs")),
        )
        conn.commit()
    yield src
    reset_file_reader_service()


def _diagnose(**kwargs):
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=[]):
        return diagnose_issue(ISSUE, repo=REPO, **kwargs)


def test_chain_follows_the_call_path_to_the_query_that_drops_the_transaction(chain_db):
    chain = _diagnose()["call_chain"]
    assert chain["entry"] == "route_handler"
    assert [s["symbol"] for s in chain["steps"]] == [
        "ToolsController.PublishInstance", "ToolService.PublishInstance", "ToolService.GetByInstanceId",
        "ToolReader.GetByInstanceId", "ToolReader.GetAccess", "ToolRepository.GetToolAccess",
    ]
    steps = {s["symbol"]: s for s in chain["steps"]}
    assert steps["ToolReader.GetByInstanceId"]["via"] == "IToolReader.GetByInstanceId"
    assert any("BeginTransaction" in e["text"] and e["line"] == 5 for e in steps["ToolService.PublishInstance"]["evidence"])
    last = steps["ToolRepository.GetToolAccess"]
    assert last["file"] == "Data/ToolRepository.cs" and last["lines"] == [3, 7]
    assert last["call_site"] == {"file": "Services/ToolReader.cs", "line": 11, "text": "var rows = await _repo.GetToolAccess(id);"}
    assert last["not_passed"] == ["transaction"]
    assert steps["ToolReader.GetAccess"]["not_passed"] == ["transaction"]
    assert "not_passed" not in steps["ToolService.GetByInstanceId"]
    assert any("QueryAsync" in e["text"] for e in last["evidence"])
    assert all(len(s["evidence"]) <= 3 for s in chain["steps"])


def test_chain_skips_loggers_interfaces_with_many_implementations_and_test_doubles(chain_db):
    text = json.dumps(_diagnose())
    for noise in ("LogWarning", "FakeToolReader", "Tests/"):
        assert noise not in text


def test_compact_by_default_and_detail_adds_method_bodies(chain_db):
    compact = _diagnose()
    assert all("code" not in s for s in compact["call_chain"]["steps"])
    detailed = _diagnose(detail=True)
    last = detailed["call_chain"]["steps"][-1]
    assert "QueryAsync<Row>(command)" in last["code"]


def test_route_candidates_are_left_out_when_the_chain_covers_the_route(chain_db):
    assert _diagnose()["semantic_candidates"] == []


def test_handler_returns_compact_json_with_the_call_chain(chain_db):
    payload = asyncio.run(handle_diagnose_issue(ISSUE, repo=REPO))
    data = json.loads(payload)
    assert data["call_chain"]["steps"][-1]["symbol"] == "ToolRepository.GetToolAccess"
    assert "\n" not in payload
    detailed = json.loads(asyncio.run(handle_diagnose_issue(ISSUE, repo=REPO, detail=True)))
    assert "code" in detailed["call_chain"]["steps"][0]


def test_no_entry_point_gives_an_empty_chain(chain_db):
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=[]):
        chain = diagnose_issue("Something is slow sometimes", repo=REPO)["call_chain"]
    assert chain["steps"] == [] and chain["entry"] is None


def test_error_terms_expand_common_error_words():
    terms = extract_error_terms(ISSUE)
    for word in ("transaction", "query", "command", "connection", "execute"):
        assert terms[word] == 3.0
    assert "the" not in terms and "system" not in terms
    assert "requires" not in terms


@pytest.mark.parametrize("line, term, hit", [
    ("return await _connection.QueryAsync<Row>(command);", "query", True),
    ("using (var transaction = conn.BeginTransaction())", "transaction", True),
    ("var rows = await _repo.GetToolAccess(id);", "transaction", False),
    ("var builder = new Builder();", "null", False),
    ("if (value is null) return;", "null", True),
])
def test_line_term_hits_match_identifier_parts(line, term, hit):
    assert (term in line_term_hits(line, {term: 3.0})) is hit

"""
trace_path stays on production code: no test doubles, no library calls as tree nodes, and no private
methods of other classes matched by name. The fixture copies the shape of `ToolService.PublishInstance`
in a C# hub API (ast rows as the C# extractor writes them: bare targets for receivers of unknown type).
"""

import asyncio
import json

import pytest

import app.mcp.tools  # noqa: F401  (registers the module that _get_tools_attr reads)
from app.mcp.handlers.symbol_handlers import handle_trace_path
from app.services.database import get_db_connection
from app.services.database.engine import get_db_engine, init_db
from app.services.graph_traversal import trace_symbol_path
from app.services.trace_call_filters import is_private_member, member_visible_from

REPO = "hub"
API = "server/Hub.API/Services_V2"
TESTS = "server/Hub.API.Tests/Services_V2"

# (file, class, method, start, end, signature)
METHODS = [
    (f"{API}/ToolService.cs", "ToolService", "PublishInstance", 254, 400, "public async Task<ToolInstanceDTO?> PublishInstance(Guid draftInstanceId, string unparsedUsername)"),
    (f"{API}/ToolService.cs", "ToolService", "GetByInstanceId", 220, 240, "public async Task<ToolInstanceDTO?> GetByInstanceId(Guid id, IDbTransaction transaction)"),
    (f"{API}/ToolService.cs", "ToolService", "ensureSystemToolAuthoringAllowed", 1095, 1112, "private void ensureSystemToolAuthoringAllowed(string name)"),
    ("server/Hub.API/Controllers/ToolsController.cs", "ToolsController", "PublishInstance", 182, 205, "public async Task<ActionResult> PublishInstance([FromRoute] Guid id)"),
    (f"{API}/ToolInstanceReader.cs", "IToolInstanceReader", "GetByInstanceId", 5, 5, "Task<ToolInstanceDTO?> GetByInstanceId(Guid id, IDbTransaction transaction);"),
    (f"{API}/ToolInstanceReader.cs", "ToolInstanceReader", "GetByInstanceId", 20, 30, "public async Task<ToolInstanceDTO?> GetByInstanceId(Guid id, IDbTransaction transaction)"),
    ("server/Hub.API/Utilities/ServiceUtilities.cs", "ServiceUtilities", "ParseUserName", 10, 25, "public static string ParseUserName(string unparsedUserName)"),
    ("server/Hub.API/Utilities/ServiceUtilities.cs", "ServiceUtilities", "getCurrentCentralTime", 65, 72, "public static DateTime getCurrentCentralTime()"),
    (f"{API}/AssistantService.cs", "AssistantService", "getCurrentCentralTime", 762, 766, "private static DateTime getCurrentCentralTime()"),
    (f"{API}/ToolFileValidationService.cs", "ToolFileValidationService", "ValidateLocalToolFiles", 20, 80, "public static void ValidateLocalToolFiles(IReadOnlyList<ToolFileDTO> files)"),
    (f"{API}/ToolFileValidationService.cs", "ToolFileValidationService", "normalizeToolFileName", 95, 97, "private static string normalizeToolFileName(string fileName)"),
    ("server/Orchestration/Logging/RunLogStatsCalculator.cs", "RunLogStatsCalculator", "Calculate", 10, 30, "public static RunLogStats Calculate(IReadOnlyList<RunLogEvent> events)"),
    ("server/Orchestration/Logging/RunLogStatsCalculator.cs", "RunLogStatsCalculator", "Count", 32, 35, "private static int Count(IReadOnlyList<RunLogEvent> events, RunLogEventType type)"),
    ("server/Orchestration/Logging/SerilogWriter.cs", "SerilogWriter", "LogError", 26, 30, "public void LogError(string message)"),
    ("server/WPWorkloadAssistant/WPLogger.cs", "WPLogger", "LogError", 40, 47, "public void LogError(string message)"),
    # Test doubles and tests in test projects.
    (f"{TESTS}/ToolExecutionAuthorizationTests.cs", "RecordingConnection", "BeginTransaction", 100, 104, "public IDbTransaction BeginTransaction()"),
    (f"{TESTS}/ToolExecutionAuthorizationTests.cs", "RecordingTransaction", "Commit", 110, 110, "public void Commit() { }"),
    (f"{TESTS}/ToolServiceTests.cs", "ToolServiceTests", "PublishInstance_ReturnsTheNewInstance", 40, 60, "public async Task PublishInstance_ReturnsTheNewInstance()"),
    ("server/Orchestration.Tests/Helpers/CapturingLogWriter.cs", "CapturingLogWriter", "LogError", 15, 20, "public void LogError(string message)"),
    (f"{TESTS}/FakeToolInstanceReader.cs", "FakeToolInstanceReader", "GetByInstanceId", 8, 9, "public Task<ToolInstanceDTO?> GetByInstanceId(Guid id, IDbTransaction transaction)"),
]
# (caller "Class.Method", target as stored, line)
CALLS = [
    ("ToolService.PublishInstance", "BeginTransaction", 256),
    ("ToolService.PublishInstance", "ParseUserName", 260),
    ("ToolService.PublishInstance", "ToolService.GetByInstanceId", 261),
    ("ToolService.PublishInstance", "LogError", 269),
    ("ToolService.PublishInstance", "ValidateLocalToolFiles", 278),
    ("ToolService.PublishInstance", "ToolService.ensureSystemToolAuthoringAllowed", 281),
    ("ToolService.PublishInstance", "IsNullOrEmpty", 283),
    ("ToolService.PublishInstance", "LogError", 285),
    ("ToolService.PublishInstance", "getCurrentCentralTime", 292),
    ("ToolService.PublishInstance", "NewGuid", 293),
    ("ToolService.GetByInstanceId", "IToolInstanceReader.GetByInstanceId", 230),
    ("ToolService.ensureSystemToolAuthoringAllowed", "UnauthorizedAccessException", 1103),
    ("ToolsController.PublishInstance", "ToolService.PublishInstance", 194),
    ("ServiceUtilities.ParseUserName", "IsNullOrEmpty", 14),
    ("ServiceUtilities.ParseUserName", "LastIndexOf", 19),
    ("ServiceUtilities.ParseUserName", "Substring", 23),
    ("ServiceUtilities.getCurrentCentralTime", "FindSystemTimeZoneById", 69),
    ("ToolFileValidationService.ValidateLocalToolFiles", "ToList", 24),
    ("ToolFileValidationService.ValidateLocalToolFiles", "InvalidOperationException", 28),
    ("ToolFileValidationService.ValidateLocalToolFiles", "Where", 31),
    ("ToolFileValidationService.ValidateLocalToolFiles", "Join", 50),
    ("ToolFileValidationService.ValidateLocalToolFiles", "GroupBy", 53),
    ("ToolFileValidationService.ValidateLocalToolFiles", "ToolFileValidationService.normalizeToolFileName", 54),
    ("ToolFileValidationService.ValidateLocalToolFiles", "Count", 55),
    ("ToolFileValidationService.ValidateLocalToolFiles", "Any", 68),
    ("ToolFileValidationService.ValidateLocalToolFiles", "InvalidOperationException", 70),
    ("RunLogStatsCalculator.Calculate", "RunLogStatsCalculator.Count", 18),
    ("SerilogWriter.LogError", "Error", 28),
    ("RecordingConnection.BeginTransaction", "RecordingTransaction", 102),
    ("CapturingLogWriter.LogError", "List.Add", 18),
    ("ToolServiceTests.PublishInstance_ReturnsTheNewInstance", "ToolService.PublishInstance", 50),
]
IMPLEMENTS = [
    (f"{API}/ToolInstanceReader.cs", "ToolInstanceReader", "IToolInstanceReader"),
    (f"{TESTS}/FakeToolInstanceReader.cs", "FakeToolInstanceReader", "IToolInstanceReader"),
]


@pytest.fixture
def hub_graph(tmp_path, monkeypatch):
    db_file = tmp_path / "callee_noise.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))

    ids, files = {}, {}
    with get_db_connection() as conn:
        def add_symbol(fp, name, full, kind, start, end, sig):
            return conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'c_sharp')",
                (REPO, f"{REPO}://{fp}", name, full, kind, start, end, sig),
            ).lastrowid

        classes = {}
        for fp, cls, method, start, end, sig in METHODS:
            if cls not in classes:
                kind = "interface_declaration" if cls.startswith("I") and cls[1].isupper() else "class_declaration"
                classes[cls] = add_symbol(fp, cls, cls, kind, 1, 2000, f"public class {cls}")
            ids[f"{cls}.{method}"] = add_symbol(fp, method, f"{cls}.{method}", "method_declaration", start, end, sig)
            files[f"{cls}.{method}"] = fp
        for caller, target, line in CALLS:
            conn.execute(
                "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
                "VALUES (?, ?, ?, ?, ?, 'CALLS', ?)",
                (REPO, ids[caller], f"{REPO}://{files[caller]}", caller.split(".")[-1], target, line),
            )
        for fp, cls, iface in IMPLEMENTS:
            conn.execute(
                "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
                "VALUES (?, ?, ?, ?, 'IMPLEMENTS', 1)",
                (REPO, f"{REPO}://{fp}", cls, iface),
            )
        conn.commit()
    return ids


def _symbols(nodes, key="callees"):
    for node in nodes:
        yield node["symbol"]
        yield from _symbols(node.get(key) or [], key)


def _trace(symbol, direction="callees", **kwargs):
    return json.loads(trace_symbol_path(symbol, repo=REPO, direction=direction, depth=2, **kwargs))


def test_private_members_are_visible_only_from_their_own_class():
    assert is_private_member("private static int Count(IReadOnlyList<RunLogEvent> events)")
    assert is_private_member("[Pure] private int Count()")
    assert not is_private_member("private protected int Count()")
    assert not is_private_member("public static int Count()")
    assert not is_private_member(None)
    count = {"full_symbol": "RunLogStatsCalculator.Count", "signature": "private static int Count()"}
    assert member_visible_from(count, "RunLogStatsCalculator.Calculate")
    assert member_visible_from(count, "Ns.RunLogStatsCalculator.Nested.Run")
    assert not member_visible_from(count, "ToolFileValidationService.ValidateLocalToolFiles")


def test_callees_keep_production_symbols_and_group_library_calls(hub_graph):
    result = _trace("ToolService.PublishInstance")
    tree = {n["symbol"]: n for n in result["callees"]}
    assert list(tree) == [
        "ServiceUtilities.ParseUserName",
        "ToolService.GetByInstanceId",
        "ToolFileValidationService.ValidateLocalToolFiles",
        "ToolService.ensureSystemToolAuthoringAllowed",
        "ServiceUtilities.getCurrentCentralTime",  # the private AssistantService method of the same name is not a candidate
    ]
    # `transaction.BeginTransaction()` has only a test double as candidate, and `Logger.LogError` matches two classes.
    assert result["unresolved"] == ["BeginTransaction", "LogError", "IsNullOrEmpty", "NewGuid"]
    assert [n["symbol"] for n in tree["ToolService.GetByInstanceId"]["callees"]] == ["ToolInstanceReader.GetByInstanceId"]
    validation = tree["ToolFileValidationService.ValidateLocalToolFiles"]
    # `group.Count()` (LINQ) is not the private `RunLogStatsCalculator.Count`.
    assert [n["symbol"] for n in validation["callees"]] == ["ToolFileValidationService.normalizeToolFileName"]
    assert validation["unresolved"] == ["ToList", "InvalidOperationException", "Where", "Join", "GroupBy", "Count", "Any"]
    assert tree["ServiceUtilities.ParseUserName"]["unresolved"] == ["IsNullOrEmpty", "LastIndexOf", "Substring"]
    reached = list(_symbols(result["callees"]))
    assert not [s for s in reached if "Recording" in s or "Capturing" in s or "Fake" in s or "RunLogStats" in s], reached


def test_include_unresolved_shows_every_call_as_a_node(hub_graph):
    reached = list(_symbols(_trace("ToolService.PublishInstance", include_unresolved=True)["callees"]))
    assert "IsNullOrEmpty" in reached and "BeginTransaction" in reached
    assert "RecordingTransaction" in reached  # the bare name `BeginTransaction` expands into the test double


def test_callers_skip_test_code_and_calls_that_cannot_reach_a_private_member(hub_graph):
    callers = _trace("ToolService.PublishInstance", direction="callers")
    assert list(_symbols(callers["callers"], "callers")) == ["ToolsController.PublishInstance"]
    assert callers["hidden_test_calls"] == 1
    with_tests = _trace("ToolService.PublishInstance", direction="callers", include_unresolved=True)
    assert "ToolServiceTests.PublishInstance_ReturnsTheNewInstance" in list(_symbols(with_tests["callers"], "callers"))
    count_callers = _trace("RunLogStatsCalculator.Count", direction="callers")
    assert list(_symbols(count_callers["callers"], "callers")) == ["RunLogStatsCalculator.Calculate"]


def test_a_test_target_still_shows_its_test_callees(hub_graph):
    result = _trace("RecordingConnection.BeginTransaction")
    assert [n["symbol"] for n in result["callees"]] == ["RecordingTransaction"]


def test_mcp_answer_is_smaller_by_default(hub_graph):
    args = {"symbol": "ToolService.PublishInstance", "repo": REPO, "direction": "callees", "depth": 2}
    compact = asyncio.run(handle_trace_path(**args))
    full = asyncio.run(handle_trace_path(**args, include_unresolved=True))
    assert json.loads(compact)["total_callees"] == 7
    assert json.loads(full)["total_callees"] > 25
    assert len(compact) < len(full) * 0.6


def test_callee_nodes_show_the_call_site_and_where_the_callee_is_defined(hub_graph):
    nodes = {n["symbol"]: n for n in _trace("ToolService.PublishInstance")["callees"]}
    get = nodes["ToolService.GetByInstanceId"]
    assert (get["file"], get["line"]) == (f"{API}/ToolService.cs", 261)
    assert get["defined_at"] == f"{API}/ToolService.cs:220"
    parse = nodes["ServiceUtilities.ParseUserName"]
    assert (parse["file"], parse["line"]) == (f"{API}/ToolService.cs", 260)
    assert parse["defined_at"] == "server/Hub.API/Utilities/ServiceUtilities.cs:10"
    reader = {n["symbol"]: n for n in get["callees"]}["ToolInstanceReader.GetByInstanceId"]
    assert reader["defined_at"] == f"{API}/ToolInstanceReader.cs:20"

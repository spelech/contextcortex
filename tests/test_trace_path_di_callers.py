"""trace_path callers must not mix up same-named methods of different classes (controller -> service -> repository)."""

import json

import pytest

from app.services.database.engine import get_db_engine, init_db
from app.services.database import get_db_connection
from app.services.graph_traversal import trace_symbol_path

REPO = "hub"
# class -> (file, constructor signature with the injected interface)
CLASSES = {
    "AssistantsController": ("Controllers/AssistantsController.cs", "AssistantsController(IAssistantService assistantService)"),
    "ToolsController": ("Controllers/ToolsController.cs", "ToolsController(IToolService toolService)"),
    "AssistantService": ("Services/AssistantService.cs", "AssistantService(IAssistantRepository assistantRepository)"),
    "ToolService": ("Services/ToolService.cs", "ToolService(IToolRepository toolRepository)"),
    "AssistantRepository": ("Data/AssistantRepository.cs", "AssistantRepository(IDbConnection connection)"),
    "ToolRepository": ("Data/ToolRepository.cs", "ToolRepository(IDbConnection connection)"),
}
IMPLEMENTS = {
    "AssistantService": "IAssistantService", "ToolService": "IToolService",
    "AssistantRepository": "IAssistantRepository", "ToolRepository": "IToolRepository",
}
# Each class's PublishInstance calls `<field>.PublishInstance(...)`, stored as the bare name.
CALLERS = ["AssistantsController", "ToolsController", "AssistantService", "ToolService"]


@pytest.fixture
def di_graph(tmp_path, monkeypatch):
    db_file = tmp_path / "di_trace.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))

    method_ids = {}
    with get_db_connection() as conn:
        def add_symbol(fp, name, full, kind, start, end, sig):
            cur = conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'c_sharp')",
                (REPO, f"{REPO}://{fp}", name, full, kind, start, end, sig),
            )
            return cur.lastrowid

        for cls, (fp, ctor_sig) in CLASSES.items():
            add_symbol(fp, cls, cls, "class_declaration", 1, 100, f"public class {cls}")
            add_symbol(fp, cls, f"{cls}.{cls}", "constructor_declaration", 5, 9, ctor_sig)
            method_ids[cls] = add_symbol(fp, "PublishInstance", f"{cls}.PublishInstance", "method_declaration", 20, 40, "PublishInstance(Guid id)")
        for iface in set(IMPLEMENTS.values()):
            add_symbol(f"Interfaces/{iface}.cs", iface, iface, "interface_declaration", 1, 10, f"public interface {iface}")
            add_symbol(f"Interfaces/{iface}.cs", "PublishInstance", f"{iface}.PublishInstance", "method_declaration", 3, 3, "PublishInstance(Guid id)")
        for cls, iface in IMPLEMENTS.items():
            conn.execute(
                "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
                "VALUES (?, ?, ?, ?, 'IMPLEMENTS', 1)",
                (REPO, f"{REPO}://{CLASSES[cls][0]}", cls, iface),
            )
        for cls in CALLERS:
            conn.execute(
                "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
                "VALUES (?, ?, ?, 'PublishInstance', 'PublishInstance', 'CALLS', 30)",
                (REPO, method_ids[cls], f"{REPO}://{CLASSES[cls][0]}"),
            )
        conn.commit()
    return method_ids


def _callers(symbol: str):
    result = json.loads(trace_symbol_path(symbol=symbol, repo=REPO, direction="callers", depth=1, limit=50))
    return sorted(node["symbol"] for node in result["callers"])


@pytest.mark.parametrize(
    "target, expected",
    [
        ("AssistantService.PublishInstance", ["AssistantsController.PublishInstance"]),
        ("ToolService.PublishInstance", ["ToolsController.PublishInstance"]),
        ("AssistantRepository.PublishInstance", ["AssistantService.PublishInstance"]),
        ("ToolRepository.PublishInstance", ["ToolService.PublishInstance"]),
    ],
)
def test_same_named_methods_get_only_their_injected_callers(di_graph, target, expected):
    assert _callers(target) == expected


def test_undecidable_calls_are_kept(di_graph):
    # A class with no injected interface for PublishInstance cannot be resolved: keep the edge (no false negatives).
    with get_db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) "
            "VALUES (?, 'hub://Jobs/Nightly.cs', 'Run', 'NightlyJob.Run', 'method_declaration', 10, 20, 'Run()', 'c_sharp')",
            (REPO,),
        )
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
            "VALUES (?, ?, 'hub://Jobs/Nightly.cs', 'Run', 'PublishInstance', 'CALLS', 15)",
            (REPO, cur.lastrowid),
        )
        conn.commit()
    assert "NightlyJob.Run" in _callers("AssistantService.PublishInstance")

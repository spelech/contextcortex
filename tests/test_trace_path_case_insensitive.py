"""trace_path: a symbol in another letter case resolves, with SQL that PostgreSQL accepts (no SQLite-only COLLATE NOCASE)."""

import inspect
import json

import app.services.graph_traversal as graph_traversal
from app.services.graph_traversal import trace_symbol_path

# Same database setup as the DI caller tests: the method rows and CALLS rows of a small C# graph.
from tests.test_trace_path_di_callers import REPO, di_graph  # noqa: F401  (pytest fixture)


def test_lowercase_symbol_resolves_to_the_indexed_symbol(di_graph):  # noqa: F811
    result = json.loads(trace_symbol_path(symbol="assistantservice.publishinstance", repo=REPO, direction="callers", depth=1))
    assert "error" not in result
    assert result["target"]["symbol"] == "AssistantService.PublishInstance"
    assert [c["symbol"] for c in result["callers"]] == ["AssistantsController.PublishInstance"]


def test_graph_traversal_sql_has_no_sqlite_only_collation():
    # PostgreSQL rejects `COLLATE NOCASE` ("collation nocase for encoding UTF8 does not exist").
    assert "NOCASE" not in inspect.getsource(graph_traversal).upper()

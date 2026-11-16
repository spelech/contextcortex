"""diagnose_issue compares the failing call chain with a similar path that the report says still works."""

from unittest.mock import patch

import pytest

from app.services.database import get_db_connection
from app.services.diagnostic_working_path import working_statements
from app.services.diagnostics import diagnose_issue
from tests.test_diagnose_evidence_chain import ISSUE, REPO, chain_db  # noqa: F401  (pytest fixture)

WORKING_ISSUE = ISSUE + "\nPublishing an assistant still works."
SOURCES = {
    "Controllers/AssistantsController.cs": """public class AssistantsController
{
    public async Task<IActionResult> PublishInstance(Guid id)
    {
        var saved = await _assistantService.PublishInstance(id);
        return Ok(saved);
    }
}
""",
    "Services/AssistantService.cs": """public class AssistantService
{
    public async Task<AssistantDTO> PublishInstance(Guid id)
    {
        using (var transaction = _repo.SqlConnection.BeginTransaction())
        {
            var assistant = await GetByInstanceId(id, transaction);
            transaction.Commit();
            return assistant;
        }
    }

    public async Task<AssistantDTO> GetByInstanceId(Guid id, IDbTransaction transaction = null)
    {
        return await _repo.GetAssistant(id, transaction);
    }
}
""",
    "Data/AssistantRepository.cs": """public class AssistantRepository
{
    public async Task<AssistantDTO> GetAssistant(Guid id, IDbTransaction transaction = null)
    {
        var command = new CommandDefinition("GetAssistant", new { id }, transaction: transaction);
        return await _connection.QuerySingleAsync<AssistantDTO>(command);
    }
}
""",
}
SYMBOLS = [
    ("Controllers/AssistantsController.cs", "PublishInstance", "AssistantsController.PublishInstance", 3, 7),
    ("Services/AssistantService.cs", "PublishInstance", "AssistantService.PublishInstance", 3, 11),
    ("Services/AssistantService.cs", "GetByInstanceId", "AssistantService.GetByInstanceId", 13, 16),
    ("Data/AssistantRepository.cs", "GetAssistant", "AssistantRepository.GetAssistant", 3, 7),
]
CALLS = [
    ("Controllers/AssistantsController.cs", "PublishInstance", "AssistantService.PublishInstance", 5),
    ("Services/AssistantService.cs", "PublishInstance", "BeginTransaction", 5),
    ("Services/AssistantService.cs", "PublishInstance", "GetByInstanceId", 7),
    ("Services/AssistantService.cs", "GetByInstanceId", "AssistantRepository.GetAssistant", 15),
]


def _add_assistant_path(src, with_route=True):
    def abs_path(rel):
        return str(src / rel)

    for rel, text in SOURCES.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text, encoding="utf-8")
    with get_db_connection() as conn:
        ids = {}
        for rel, name, full, start, end in SYMBOLS:
            ids[(rel, name)] = conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) "
                "VALUES (?, ?, ?, ?, 'method_declaration', ?, ?, ?, 'c_sharp')",
                (REPO, abs_path(rel), name, full, start, end, name),
            ).lastrowid
        for rel, source, target, line in CALLS:
            conn.execute(
                "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, "
                "relationship_type, line_number) VALUES (?, ?, ?, ?, ?, 'CALLS', ?)",
                (REPO, ids[(rel, source)], abs_path(rel), source, target, line),
            )
        if with_route:
            conn.execute(
                "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) "
                "VALUES (?, ?, 'aspnet', 'POST', '/api/v2/assistants/{id}/publish', 'AssistantsController.PublishInstance', 3, 7)",
                (REPO, abs_path("Controllers/AssistantsController.cs")),
            )
        conn.commit()


def _diagnose(text):
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=[]):
        return diagnose_issue(text, repo=REPO)


def test_sibling_route_is_aligned_and_the_first_divergence_shows_the_dropped_transaction(chain_db):  # noqa: F811
    _add_assistant_path(chain_db)
    cmp = _diagnose(WORKING_ISSUE)["working_path_comparison"]
    assert cmp["statement"] == "Publishing an assistant still works."
    assert cmp["entry"] == {"symbol": "AssistantsController.PublishInstance", "aligned_with": "ToolsController.PublishInstance",
                            "route": "POST /api/v2/assistants/{id}/publish"}
    assert [s["symbol"] for s in cmp["steps"]] == [
        "AssistantsController.PublishInstance", "AssistantService.PublishInstance", "AssistantService.GetByInstanceId",
    ]
    assert cmp["steps"][2]["call_site"] == {"line": 7, "text": "var assistant = await GetByInstanceId(id, transaction);"}
    div = cmp["first_divergence"]
    assert div["step"] == 3 and div["failing"]["symbol"] == "ToolReader.GetByInstanceId"
    assert div["working"]["passing_call"] == {"target": "AssistantRepository.GetAssistant", "line": 15,
                                              "text": "return await _repo.GetAssistant(id, transaction);"}
    assert div["failing_drop"]["symbol"] == "ToolReader.GetAccess"
    assert div["failing_drop"]["call_site"]["line"] == 5 and div["failing_drop"]["not_passed"] == ["transaction"]


def test_sibling_class_by_name_when_no_route_matches(chain_db):  # noqa: F811
    _add_assistant_path(chain_db, with_route=False)
    text = WORKING_ISSUE.replace("`POST /api/v2/Tools/{id}/publish`", "ToolService.PublishInstance")
    result = _diagnose(text)
    assert result["call_chain"]["steps"][0]["symbol"] == "ToolService.PublishInstance"
    cmp = result["working_path_comparison"]
    assert cmp["entry"] == {"symbol": "AssistantService.PublishInstance", "aligned_with": "ToolService.PublishInstance"}
    assert cmp["first_divergence"]["working"]["passing_call"]["target"] == "AssistantRepository.GetAssistant"


def test_no_working_statement_gives_no_comparison(chain_db):  # noqa: F811
    _add_assistant_path(chain_db)
    assert _diagnose(ISSUE)["working_path_comparison"] is None


def test_working_path_without_a_sibling_is_reported_as_not_found(chain_db):  # noqa: F811
    cmp = _diagnose(ISSUE + "\nPublishing a workflow still works.")["working_path_comparison"]
    assert cmp == {"statement": "Publishing a workflow still works.", "entry": None, "steps": [], "first_divergence": None}


@pytest.mark.parametrize("text, expected", [
    ("Publishing a tool fails, but publishing an assistant still works.", ["publishing an assistant still works."]),
    ("Saving works for assistants.", ["Saving works for assistants."]),
    ("Exports are fine.", ["Exports are fine."]),
    ("Assistants do not work either.", []),
    ("It no longer works.", []),
    ("Assistant publish doesn't work at all.", []),
    ("Saving an assistant does not fail.", ["Saving an assistant does not fail."]),
    ("Publishing fails.", []),
])
def test_working_statements(text, expected):
    assert working_statements(text) == expected

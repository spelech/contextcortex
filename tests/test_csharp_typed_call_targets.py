"""C# call targets carry the receiver's declared type, so same-named methods of different classes stay apart."""

import json
from unittest.mock import patch

import pytest

from app.services.chunking import extract_symbols_and_chunks
from app.services.chunking.tree_sitter_loader import get_tree_sitter_parser
from app.services.search import trace_symbol_path
from tests.test_multilanguage_cs_ts_py import _conn_factory, _setup_sqlite_repo

pytestmark = pytest.mark.skipif(get_tree_sitter_parser("c_sharp") is None, reason="needs the C# tree-sitter grammar")

TYPES_CS = """\
public class Worker(IClock clock)
{
    private readonly ToolService _toolService;
    private readonly Ns.Data.ToolRepository? _repo;
    public ILogger<Worker> Logger { get; }

    public async Task Run(Bar bar, string name)
    {
        var made = new Baz();
        var unknown = Factory.Create();
        await _toolService.PublishInstance(1);
        await this._repo.Save(2);
        bar.Go();
        made.Spin();
        unknown.Spin();
        clock.Tick();
        Logger.LogInformation("x");
        name.Trim();
        StaticHelpers.Format(3);
        foreach (Item item in bar.Items) { item.Touch(); }
        LocalCall();
    }

    public void Shadow(ToolRepository _toolService)
    {
        _toolService.PublishInstance(4);
    }
}
"""


def _call_targets(source: str):
    res = extract_symbols_and_chunks(source, "Worker.cs", repo="r")
    return {r.target_symbol for r in res.relationships if r.relationship_type == "CALLS"}


def test_receiver_types_come_from_fields_parameters_locals_and_properties():
    targets = _call_targets(TYPES_CS)
    for expected in (
        "ToolService.PublishInstance",   # field
        "ToolRepository.Save",           # this.field, namespace and nullable removed
        "Bar.Go",                        # method parameter
        "Baz.Spin",                      # var x = new T()
        "IClock.Tick",                   # primary-constructor parameter
        "ILogger.LogInformation",        # property, generic arguments removed
        "Item.Touch",                    # foreach variable
        "ToolRepository.PublishInstance",  # parameter hides the field of the same name
    ):
        assert expected in targets, expected
    # Unknown receivers keep the bare name.
    assert {"Spin", "Format", "LocalCall", "Trim"} <= targets
    assert "string.Trim" not in targets and "String.Trim" not in targets


# The real layout that showed the problem: concrete classes injected into fields, no interfaces.
CONTROLLERS_CS = """\
public class AssistantsController
{
    private readonly AssistantService _assistantService;
    public AssistantsController(AssistantService assistantService) { _assistantService = assistantService; }

    [HttpPost("{id}/publish")]
    public async Task<IActionResult> PublishInstance(Guid id)
    {
        return Ok(await _assistantService.PublishInstance(id));
    }
}

public class ToolsController
{
    private readonly ToolService _toolService;
    private readonly AssistantService _assistantService;
    public ToolsController(ToolService toolService, AssistantService assistantService) { _toolService = toolService; _assistantService = assistantService; }

    [HttpPost("{id}/publish")]
    public async Task<IActionResult> PublishInstance(Guid id)
    {
        return Ok(await _toolService.PublishInstance(id));
    }
}
"""
SERVICES_CS = """\
public class AssistantService
{
    private readonly AssistantSuperRepository _assistantRepository;
    public AssistantService(AssistantSuperRepository assistantRepository) { _assistantRepository = assistantRepository; }

    public async Task<int> PublishInstance(Guid id)
    {
        return await _assistantRepository.PublishInstance(id);
    }
}

public class ToolService
{
    private readonly ToolSuperRepository _toolRepository;
    public ToolService(ToolSuperRepository toolRepository) { _toolRepository = toolRepository; }

    public async Task<int> PublishInstance(Guid id)
    {
        return await _toolRepository.PublishInstance(id);
    }
}
"""
REPOSITORIES_CS = """\
public class AssistantSuperRepository
{
    public Task<int> PublishInstance(Guid id) => Task.FromResult(1);
}

public class ToolSuperRepository
{
    public Task<int> PublishInstance(Guid id) => Task.FromResult(2);
}
"""


@pytest.fixture
def hub_db(tmp_path):
    db_path = str(tmp_path / "hub.db")
    _setup_sqlite_repo(db_path, "hub", [
        ("Controllers/Controllers.cs", CONTROLLERS_CS),
        ("Services/Services.cs", SERVICES_CS),
        ("Data/Repositories.cs", REPOSITORIES_CS),
    ])
    return _conn_factory(db_path)


def _trace(get_conn, symbol: str, direction: str):
    with patch("app.services.search.get_db_connection", side_effect=get_conn):
        return json.loads(trace_symbol_path(symbol, repo="hub", direction=direction, depth=1))


@pytest.mark.parametrize("target, caller", [
    ("AssistantService.PublishInstance", "AssistantsController.PublishInstance"),
    ("ToolService.PublishInstance", "ToolsController.PublishInstance"),
    ("AssistantSuperRepository.PublishInstance", "AssistantService.PublishInstance"),
    ("ToolSuperRepository.PublishInstance", "ToolService.PublishInstance"),
])
def test_callers_of_same_named_methods_with_concrete_injection(hub_db, target, caller):
    callers = [c["symbol"] for c in _trace(hub_db, target, "callers")["callers"]]
    assert callers == [caller]


def test_callees_follow_the_field_type(hub_db):
    callees = [c["symbol"] for c in _trace(hub_db, "ToolsController.PublishInstance", "callees")["callees"]]
    assert "ToolService.PublishInstance" in callees
    assert "AssistantService.PublishInstance" not in callees

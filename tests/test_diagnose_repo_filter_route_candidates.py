"""diagnose_issue must respect `repo` everywhere and rank the matched route's call path first."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.database import get_db_connection
from app.services.database.engine import get_db_engine, init_db
from app.services.diagnostic_route_path import keep_semantic_hit, language_family
from app.services.diagnostics import diagnose_issue, match_routes_and_callers, resolve_stack_frames

REPO = "hub-prefix"
OTHER = "assistant-hub"
ISSUE = (
    "Publishing a tool from the UI fails. `POST /api/v2/Tools/{id}/publish` returns HTTP 500. "
    "The API log shows: System.InvalidOperationException: ExecuteReader requires the command to have a "
    "transaction when the connection assigned to the command is in a pending local transaction."
)
CLASSES = {
    "ToolsController": ("Controllers/ToolsController.cs", "ToolsController(IToolService toolService)"),
    "ToolService": ("Services/ToolService.cs", "ToolService(IToolRepository toolRepository)"),
    "ToolRepository": ("Data/ToolRepository.cs", "ToolRepository(IDbConnection connection)"),
}
IMPLEMENTS = {"ToolService": "IToolService", "ToolRepository": "IToolRepository"}


def _add_symbol(conn, repo, fp, name, full, kind, start, end, sig, lang="c_sharp"):
    return conn.execute(
        "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (repo, f"{repo}://{fp}", name, full, kind, start, end, sig, lang),
    ).lastrowid


@pytest.fixture
def hub_db(tmp_path, monkeypatch):
    db_file = tmp_path / "diag_repo_filter.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))

    with get_db_connection() as conn:
        ids = {}
        for repo in (REPO, OTHER):
            for cls, (fp, ctor_sig) in CLASSES.items():
                _add_symbol(conn, repo, fp, cls, cls, "class_declaration", 1, 100, f"public class {cls}")
                _add_symbol(conn, repo, fp, cls, f"{cls}.{cls}", "constructor_declaration", 5, 9, ctor_sig)
                ids[(repo, cls)] = _add_symbol(
                    conn, repo, fp, "PublishInstance", f"{cls}.PublishInstance", "method_declaration", 20, 40,
                    "PublishInstance(Guid id)",
                )
            for cls, iface in IMPLEMENTS.items():
                _add_symbol(conn, repo, f"Interfaces/{iface}.cs", iface, iface, "interface_declaration", 1, 10, iface)
                _add_symbol(conn, repo, f"Interfaces/{iface}.cs", "PublishInstance", f"{iface}.PublishInstance",
                            "method_declaration", 3, 3, "PublishInstance(Guid id)")
                conn.execute(
                    "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
                    "VALUES (?, ?, ?, ?, 'IMPLEMENTS', 1)",
                    (repo, f"{repo}://{CLASSES[cls][0]}", cls, iface),
                )
            # Controller -> service -> repository; the repository calls a framework method (not indexed).
            for cls, target, line in (("ToolsController", "PublishInstance", 30), ("ToolService", "PublishInstance", 30),
                                      ("ToolRepository", "ExecuteReader", 32)):
                conn.execute(
                    "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
                    "VALUES (?, ?, ?, 'PublishInstance', ?, 'CALLS', ?)",
                    (repo, ids[(repo, cls)], f"{repo}://{CLASSES[cls][0]}", target, line),
                )
            conn.execute(
                "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) "
                "VALUES (?, ?, 'aspnet', 'POST', '/api/v2/tools/{id}/publish', 'ToolsController.PublishInstance', 20, 40)",
                (repo, f"{repo}://Controllers/ToolsController.cs"),
            )
            conn.execute(
                "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) "
                "VALUES (?, ?, 'POST', '/api/v2/tools/{id}/publish', ?, 12)",
                (repo, f"{repo}://ClientApp/src/api/tools.ts", f"publishTool_{repo}"),
            )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES (?, ?, 'code', 'python')",
            (f"{OTHER}://scripts/only_here.py", OTHER),
        )
        conn.commit()


def _hit(repo, path, symbol, score, language):
    hit = MagicMock()
    hit.score = score
    hit.payload = {"repo": repo, "rel_path": path, "start_line": 1, "end_line": 9, "symbol": symbol,
                   "full_symbol": symbol, "kind": "method", "language": language, "content": "..."}
    return hit


NOISE_HITS = [
    _hit(OTHER, "Models/SystemToolId.cs", "SystemToolId", 0.61, "c_sharp"),
    _hit(REPO, "scripts/static_analysis.py", "main", 0.58, "python"),
    _hit(REPO, "Models/SystemToolNames.cs", "SystemToolNames", 0.55, "c_sharp"),
    _hit(REPO, "Tests/ToolTests.cs", "ToolTests.Publish", 0.54, "c_sharp"),
]


def test_external_callers_respect_repo(hub_db):
    routes = match_routes_and_callers([("POST", "/api/v2/Tools/{id}/publish")], repo=REPO)
    assert [r["handler"]["repo"] for r in routes] == [REPO]
    assert [c["repo"] for c in routes[0]["external_callers"]] == [REPO]


def test_external_callers_cross_repo_without_filter(hub_db):
    routes = match_routes_and_callers([("POST", "/api/v2/Tools/{id}/publish")])
    callers = {c["repo"] for r in routes for c in r["external_callers"]}
    assert callers == {REPO, OTHER}


def test_stack_frame_does_not_fall_back_to_other_repo(hub_db):
    frames = [{"path": "scripts/only_here.py", "line": 3, "function": None}]
    assert resolve_stack_frames(frames, repo=REPO)[0]["repo"] == REPO
    assert resolve_stack_frames(frames)[0]["repo"] == OTHER


def test_route_call_path_ranks_first_and_noise_is_filtered(hub_db):
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=NOISE_HITS):
        result = diagnose_issue(ISSUE, repo=REPO, limit=5)

    assert result["resolved_frames"] == []
    assert [r["handler"]["symbol"] for r in result["matched_routes"]] == ["ToolsController.PublishInstance"]
    cands = result["semantic_candidates"]
    assert {c["repo"] for c in cands} == {REPO}
    assert [(c["symbol"], c["source"], c["depth"]) for c in cands] == [
        ("ToolsController.PublishInstance", "route_handler", 0),
        ("ToolService.PublishInstance", "route_callee", 1),
        ("ToolRepository.PublishInstance", "route_callee", 2),
        ("SystemToolNames", "semantic", None),
    ]
    assert cands[0]["score"] is None and cands[3]["score"] == 0.55
    assert cands[0]["file"].endswith("Controllers/ToolsController.cs")
    assert cands[0]["lines"] == [20, 40]


def test_route_call_path_fills_limit_and_skips_search(hub_db):
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=NOISE_HITS) as search:
        cands = diagnose_issue(ISSUE, repo=REPO, limit=2)["semantic_candidates"]
    assert [c["symbol"] for c in cands] == ["ToolsController.PublishInstance", "ToolService.PublishInstance"]
    search.assert_not_called()


def test_semantic_hits_without_route_still_filter_repo(hub_db):
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=NOISE_HITS):
        cands = diagnose_issue("Publishing fails with an InvalidOperationException", repo=REPO)["semantic_candidates"]
    # No route matched: no language filter, but other repos and test files are dropped.
    assert [c["symbol"] for c in cands] == ["main", "SystemToolNames"]


@pytest.mark.parametrize("language, path, expected", [
    ("c_sharp", "a.cs", "csharp"), (None, "x/Foo.cs", "csharp"), ("python", "", "python"),
    ("text", "README.md", None), (None, "lib/app.tsx", "typescript"),
])
def test_language_family(language, path, expected):
    assert language_family(language, path) == expected


def test_keep_semantic_hit_rules():
    assert keep_semantic_hit({"repo": REPO, "rel_path": "a.cs", "language": "c_sharp"}, REPO, {"csharp"})
    assert not keep_semantic_hit({"repo": OTHER, "rel_path": "a.cs"}, REPO, set())
    assert not keep_semantic_hit({"repo": REPO, "rel_path": "a.py", "language": "python"}, REPO, {"csharp"})
    assert keep_semantic_hit({"repo": REPO, "rel_path": "notes"}, REPO, {"csharp"})

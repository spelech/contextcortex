"""grep_code: folder and file path filters without wildcards, the `path` alias, and the regex retry for `A|B` patterns."""

import asyncio
import json

import pytest

from app.mcp.handlers.grep_handlers import handle_grep_code
from app.services.code_grep_scanner import looks_like_regex, path_matches_filter
from app.services.database.engine import get_db_engine, init_db
from app.services.file_reader import FileReaderService


@pytest.mark.parametrize("path, path_filter, expected", [
    ("server/Api/Services_V2/AssistantService.cs", "Services_V2", True),
    ("server/Api/Services_V2/AssistantService.cs", "server/Api/Services_V2", True),
    ("server/Api/Services_V2/AssistantService.cs", "server/Api/Services_V2/AssistantService.cs", True),
    ("server/Api/Services_V2/AssistantService.cs", "AssistantService.cs", True),
    ("server/Api/Services_V2/AssistantService.cs", "services_v2/", True),
    ("server/Api/Services_V2/AssistantService.cs", "Services", False),
    ("server/Api/Services_V2/AssistantService.cs", "Service.cs", False),
    ("server/Api/Services_V2/AssistantService.cs", "*.cs", True),
    ("server/Api/Services_V2/AssistantService.cs", "server/*", True),
    ("server/Api/Services_V2/AssistantService.cs", "*.py", False),
    ("server/Api/Services_V2/AssistantService.cs", None, True),
])
def test_path_filter(path, path_filter, expected):
    assert path_matches_filter(path, path_filter) is expected


@pytest.mark.parametrize("pattern, expected", [
    ("PublishInstance|GetLatestAssistantPublishedVersion", True),
    ("Publish.*Version", True),
    (r"\bPublishInstance\b", True),
    ("PublishInstance", False),
    ("a + b", False),
    ("foo(", False),
    ("x|(", False),  # does not compile
])
def test_looks_like_regex(pattern, expected):
    assert looks_like_regex(pattern) is expected


@pytest.fixture
def grep_storage(tmp_path, monkeypatch):
    db_file = tmp_path / "grep_filters.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))

    storage = tmp_path / "storage"
    (storage / "Services_V2").mkdir(parents=True)
    (storage / "Controllers").mkdir()
    (storage / "Services_V2" / "AssistantService.cs").write_text(
        "var v = await repo.GetLatestAssistantPublishedVersion(id);\nawait repo.PublishInstance(id);\n", encoding="utf-8")
    (storage / "Controllers" / "AssistantsController.cs").write_text(
        "return await svc.PublishInstance(id);\n// a|b is literal text here\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(storage))
    monkeypatch.setattr("app.services.local_storage.LOCAL_STORAGE_PATH", str(storage), raising=False)
    monkeypatch.setattr(
        "app.mcp.handlers.grep_handlers._resolve_reader_factory",
        lambda: (lambda: FileReaderService(storage_root=str(storage))),
    )
    return storage


def _grep(**kwargs):
    return json.loads(asyncio.run(handle_grep_code(**kwargs)))


def _files(result):
    return sorted({m["file"] for m in result["matches"]})


def test_path_alias_limits_the_search_to_a_folder(grep_storage):
    result = _grep(pattern="PublishInstance", path="Services_V2")
    assert _files(result) == ["Services_V2/AssistantService.cs"]
    assert result["path_filter"] == "Services_V2"


def test_path_glob_wins_over_path(grep_storage):
    result = _grep(pattern="PublishInstance", path_glob="Controllers", path="Services_V2")
    assert _files(result) == ["Controllers/AssistantsController.cs"]


def test_alternation_without_is_regex_runs_as_regex(grep_storage):
    result = _grep(pattern="GetLatestAssistantPublishedVersion|svc.PublishInstance")
    assert result["total_matches"] == 2
    assert result["pattern_mode"].startswith("regex (")
    assert _files(result) == ["Controllers/AssistantsController.cs", "Services_V2/AssistantService.cs"]


def test_literal_text_with_regex_characters_stays_literal_when_it_matches(grep_storage):
    result = _grep(pattern="a|b")
    assert result["pattern_mode"] == "literal"
    assert [m["line"] for m in result["matches"]] == [2]

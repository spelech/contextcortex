"""grep_code and read_file give compact output: one path per file, ripgrep-style lines, and no null or repeated fields."""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from app.mcp.handlers.file_handlers import handle_read_file
from app.mcp.handlers.grep_handlers import handle_grep_code
from app.services.compact_results import group_grep_matches, number_lines
from app.services.script_sdk_types import build_sdk_declarations

SOURCE = [
    "public sealed class ToolInstanceReader",
    "{",
    "    public async Task<ToolAccessPreflightDTO> GetAccessPreflightAsync(",
    "        Guid instanceId)",
    "    {",
    "        return await GetAccessPreflightAsync(instanceId, null);",
    "    }",
    "",
    "",
    "",
    "",
    "    // GetAccessPreflightAsync is cached",
]


def _match(repo, file, line, symbol=None, permalink=None, context=1, lines=SOURCE):
    first, last = max(1, line - context), min(len(lines), line + context)
    return {
        "repo": repo, "file": file, "line": line, "match_text": lines[line - 1],
        "context": [{"line": n, "text": lines[n - 1]} for n in range(first, last + 1)],
        "symbol": symbol, "kind": "method_declaration" if symbol else None, "permalink": permalink,
    }


def test_matches_group_by_file_with_merged_context_and_block_separators():
    link = "https://git.example/org/hub/blob/abc/Reader.cs"
    shared_repo, files = group_grep_matches([
        _match("hub", "Reader.cs", 3, "Reader.GetAccessPreflightAsync", f"{link}#L3"),
        _match("hub", "Reader.cs", 6, "Reader.GetByInstanceId", f"{link}#L6"),
        _match("hub", "Reader.cs", 12),
    ])
    assert shared_repo == "hub"
    assert files == [{
        "file": "Reader.cs",
        "permalink": link,
        "symbols": {"3": "Reader.GetAccessPreflightAsync", "6": "Reader.GetByInstanceId"},
        "lines": [
            "2-{",
            "3:    public async Task<ToolAccessPreflightDTO> GetAccessPreflightAsync(",
            "4-        Guid instanceId)",
            "5-    {",
            "6:        return await GetAccessPreflightAsync(instanceId, null);",
            "7-    }",
            "--",
            "11-",
            "12:    // GetAccessPreflightAsync is cached",
        ],
    }]


def test_contiguous_blocks_have_no_separator_and_a_match_line_wins_over_context():
    _, files = group_grep_matches([_match("hub", "a.cs", 3, context=2), _match("hub", "a.cs", 4, context=2)])
    assert files[0]["lines"] == ["1-" + SOURCE[0], "2-{", "3:" + SOURCE[2], "4:" + SOURCE[3], "5-    {", "6-" + SOURCE[5]]
    assert "symbols" not in files[0] and "permalink" not in files[0] and "repo" not in files[0]


def test_files_from_different_repos_keep_their_repo():
    shared_repo, files = group_grep_matches([_match("api", "a.cs", 3, context=0), _match("web", "a.cs", 3, context=0)])
    assert shared_repo is None
    assert [(f["repo"], f["file"], f["lines"]) for f in files] == [("api", "a.cs", ["3:" + SOURCE[2]]), ("web", "a.cs", ["3:" + SOURCE[2]])]


def test_number_lines_prefixes_each_line():
    assert number_lines("alpha\n\nomega", 41) == "41:alpha\n42:\n43:omega"
    assert number_lines("", 1) == ""


@pytest.fixture
def hub_folder(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    (hub / "Services_V2").mkdir(parents=True)
    (hub / "Services_V2" / "ToolInstanceReader.cs").write_text("\n".join(SOURCE) + "\n", encoding="utf-8")
    (hub / "Services_V2" / "Catalog.cs").write_text("tools.GetAccessPreflightAsync(id);\n", encoding="utf-8")

    class _Reader:
        storage_root = str(tmp_path / "storage")

        def grep_code(self, **kwargs):
            from app.services.code_grep_scanner import execute_code_grep

            return execute_code_grep(
                storage_root=self.storage_root, indexed_paths=[{"path": str(hub), "repo": "hub-prefix"}],
                persistent_repos={}, is_binary_fn=lambda p: False, db_conn_factory=_NoDb, **kwargs)

        def read_file(self, path, repo=None, start_line=None, end_line=None):
            lines = (hub / path).read_text(encoding="utf-8").splitlines()
            start, end = start_line or 1, min(end_line or len(lines), len(lines))
            return {"filepath": path, "content": "\n".join(lines[start - 1:end]), "start_line": start, "end_line": end,
                    "total_lines": len(lines), "size_bytes": 1, "truncated": False, "source": "indexed_path"}

    reader = _Reader()
    monkeypatch.setattr("app.mcp.handlers.grep_handlers._resolve_reader_factory", lambda: (lambda: reader))
    monkeypatch.setattr("app.mcp.handlers.file_handlers.get_file_reader_service", lambda: reader)
    tools_module = sys.modules.get("app.mcp.tools")
    if tools_module is not None:
        monkeypatch.setattr(tools_module, "get_file_reader_service", lambda: reader, raising=False)
    return hub


class _NoDb:
    def __enter__(self):
        raise RuntimeError("no database in this test")

    def __exit__(self, *exc):
        return False


def test_grep_code_output_gives_each_path_once(hub_folder):
    result = json.loads(asyncio.run(handle_grep_code(pattern="GetAccessPreflight", repo="hub-prefix", context_lines=0)))
    assert set(result) == {"total_matches", "has_more", "repo", "files"}
    assert (result["total_matches"], result["has_more"], result["repo"]) == (4, False, "hub-prefix")
    by_file = {group["file"]: group["lines"] for group in result["files"]}
    assert by_file == {
        "Services_V2/Catalog.cs": ["1:tools.GetAccessPreflightAsync(id);"],
        "Services_V2/ToolInstanceReader.cs": ["3:" + SOURCE[2], "6:" + SOURCE[5], "12:" + SOURCE[11]],
    }
    text = json.dumps(result, separators=(",", ":"))
    assert text.count("ToolInstanceReader.cs") == 1 and ":null" not in text and "match_text" not in text


def test_grep_code_pagination_fields_appear_only_when_needed(hub_folder):
    page = json.loads(asyncio.run(handle_grep_code(pattern="GetAccessPreflight", repo="hub-prefix", limit=1, offset=1)))
    assert (page["offset"], page["has_more"], page["next_offset"]) == (1, True, 2)


def test_read_file_returns_numbered_text_and_minimal_metadata(hub_folder):
    result = json.loads(asyncio.run(handle_read_file(
        path="Services_V2/ToolInstanceReader.cs", repo="hub-prefix", start_line=2, end_line=4)))
    assert result == {
        "file": "Services_V2/ToolInstanceReader.cs",
        "lines": [2, 4],
        "total_lines": len(SOURCE),
        "next_start_line": 5,
        "content": "2:{\n3:" + SOURCE[2] + "\n4:" + SOURCE[3],
    }
    last = json.loads(asyncio.run(handle_read_file(path="Services_V2/ToolInstanceReader.cs", start_line=11)))
    assert set(last) == {"file", "lines", "total_lines", "content"}


def test_code_mode_sdk_types_grep_code_and_read_file_results():
    tools = [SimpleNamespace(name=name, description="", parameters={"type": "object", "properties": {}})
             for name in ("grep_code", "read_file", "get_architecture")]
    sdk = build_sdk_declarations(tools)
    assert "grep_code(args?: {\n  }): Promise<GrepCodeResult>;" in sdk
    assert "read_file(args?: {\n  }): Promise<ReadFileResult | ReadFileOutline>;" in sdk
    assert "get_architecture(args?: {\n  }): Promise<any>;" in sdk
    assert "interface GrepCodeFile { file: string; repo?: string; symbols?: Record<string, string>" in sdk

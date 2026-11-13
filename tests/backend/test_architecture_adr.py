import pytest
import asyncio
from app.services.database import get_db_connection, init_db, create_adr, update_adr, supersede_adr, get_adr, list_adrs
from app.services.adr import parse_adr_markdown, sync_adr_file
from app.services.architecture import detect_entry_points, synthesize_architecture
from app.mcp.tools import handle_get_architecture, handle_repo_adrs_resource
from app.mcp.mcp_server import mcp_server


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_architecture_adr.db"
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file))
    init_db()
    yield
    if db_file.exists():
        try:
            db_file.unlink()
        except Exception:
            pass


# --- Unit Tests ---

def test_entry_point_detection_heuristics():
    filepaths = [
        "repo://src/utils/helpers.py",
        "repo://main.py",
        "repo://cmd/server/main.go",
        "repo://frontend/index.ts",
        "repo://services/Program.cs",
        "repo://Dockerfile",
        "repo://components/Button.tsx"
    ]
    entry_points = detect_entry_points(filepaths)
    assert "main.py" in entry_points
    assert "cmd/server/main.go" in entry_points
    assert "frontend/index.ts" in entry_points
    assert "services/Program.cs" in entry_points
    assert "Dockerfile" in entry_points
    assert "repo://src/utils/helpers.py" not in entry_points


def test_language_distribution_and_token_limit():
    with get_db_connection() as conn:
        # Seed 100 fake indexed files
        files_data = []
        for i in range(70):
            files_data.append((f"repo_a://src/file_{i}.py", "repo_a", "code", "python"))
        for i in range(20):
            files_data.append((f"repo_a://src/comp_{i}.ts", "repo_a", "code", "typescript"))
        for i in range(10):
            files_data.append((f"repo_a://docs/doc_{i}.md", "repo_a", "doc", "markdown"))
        files_data.append(("repo_a://pyproject.toml", "repo_a", "doc", "toml"))
        files_data.append(("repo_a://main.py", "repo_a", "code", "python"))

        conn.executemany(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES (?, ?, ?, ?)",
            files_data
        )

        # Seed AST symbols
        symbols_data = []
        for i in range(50):
            symbols_data.append(("repo_a", f"repo_a://src/file_{i}.py", f"func_{i}", f"func_{i}()", "function", 1, 10, f"def func_{i}(): pass", "python"))
        conn.executemany(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            symbols_data
        )

    summary = synthesize_architecture("repo_a")
    import json
    data = json.loads(summary)
    langs = {l["language"]: l for l in data["languages"]}
    assert "Python" in langs and langs["Python"]["files"] == 71
    assert "TypeScript" in langs
    assert any("pyproject.toml" in m for m in data["manifests"])
    assert "main.py" in data["entry_points"]

    # Token check: standard prompt token estimate (~4 chars per token)
    # < 1,000 tokens => < 4,000 chars
    assert len(summary) < 4000


def test_madr_nygard_markdown_ingestion():
    nygard_md = """---
id: ADR-001
title: Use SQLite for Caching
status: Accepted
date: 2026-03-30
---

# 1. Use SQLite for Caching

## Context
We need a local persistent cache database.

## Decision
We will use SQLite in WAL mode.

## Consequences
Faster reads, single file storage.
"""
    parsed = parse_adr_markdown(nygard_md, "docs/adr/0001-use-sqlite.md", "my_repo")
    assert parsed["id"] == "ADR-001"
    assert parsed["title"] == "Use SQLite for Caching"
    assert parsed["status"] == "ACCEPTED"
    assert "local persistent cache" in parsed["context"]
    assert "SQLite in WAL mode" in parsed["decision"]
    assert "Faster reads" in parsed["consequences"]

    res = sync_adr_file("docs/adr/0001-use-sqlite.md", "my_repo", content=nygard_md)
    assert res is not None
    assert res["id"] == "ADR-001"
    assert get_adr("ADR-001", "my_repo") is not None


def test_adr_state_transitions():
    # 1. Create ADR-001
    adr1 = create_adr(
        repo="test_repo",
        title="Initial Microservices Architecture",
        status="PROPOSED",
        context="Monolith is scaling down",
        decision="Split into microservices",
        adr_id="ADR-001"
    )
    assert adr1["status"] == "PROPOSED"

    # 2. Update status to ACCEPTED
    adr1_updated = update_adr(
        adr_id="ADR-001",
        repo="test_repo",
        status="ACCEPTED"
    )
    assert adr1_updated["status"] == "ACCEPTED"

    # 3. Create ADR-002 (Modular Monolith)
    adr2 = create_adr(
        repo="test_repo",
        title="Migrate to Modular Monolith",
        status="ACCEPTED",
        context="Microservices overhead was too high",
        decision="Consolidate services into modular monolith",
        adr_id="ADR-002"
    )
    assert adr2["status"] == "ACCEPTED"

    # 4. Supersede ADR-001 with ADR-002
    superseded = supersede_adr(old_id="ADR-001", new_id="ADR-002", repo="test_repo")
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by"] == "ADR-002"

    # Verify list filter
    active_adrs = list_adrs(repo="test_repo", status="ACCEPTED")
    assert len(active_adrs) == 1
    assert active_adrs[0]["id"] == "ADR-002"


# --- Integration Tests (MCP Tools & JSON-RPC Direct Execution) ---

@pytest.mark.asyncio
async def test_mcp_get_architecture_tool():
    import json
    # Without repo argument
    res_all = json.loads(await handle_get_architecture(repo=None))
    assert "total_files" in res_all

    # Seed data
    with get_db_connection() as conn:
        conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES (?, ?, ?, ?)",
                     ("my_app://main.py", "my_app", "code", "python"))

    res_repo = json.loads(await handle_get_architecture(repo="my_app"))
    assert res_repo["repo"] == "my_app"
    assert "main.py" in res_repo["entry_points"]


@pytest.mark.asyncio
async def test_mcp_adrs_resource_and_tool_surface():
    import json
    repo = "mcp_test_repo"
    create_adr(
        repo=repo,
        adr_id="ADR-100",
        title="Use FastMCP Framework",
        status="ACCEPTED",
        context="We need a robust MCP server framework",
        decision="Adopt FastMCP",
    )
    res = json.loads(await handle_repo_adrs_resource(repo=repo))
    assert res["repo"] == repo
    assert res["total_adrs"] == 1
    assert res["adrs"][0]["id"] == "ADR-100"

    tools = {t.name for t in mcp_server._tool_manager.list_tools()}
    assert "get_architecture" in tools
    assert "manage_adr" not in tools

"""
End-to-End Admin UI <-> REST API Consistency & Multi-Language Integration Tests.
Exercises real FastAPI routers via httpx.AsyncClient + ASGITransport against an
ephemeral SQLite database, real LocalStorageService, and real embedded Qdrant store.
"""

import json
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

import app.services.local_storage as ls_mod
from app.services.auth.key_service import ApiKeyService
from app.services.auth.models import Role
from app.services.auth.service import AuthService, get_auth_service, set_current_auth_context
from app.services.database import get_db_connection, set_embedding_db_config
from app.services.database.engine import get_db_engine, init_db
from app.services.embeddings import init_embeddings
from app.services.local_storage import LocalStorageService
from app.services.topology.graph_filters import MAX_TOPOLOGY_EDGES, MAX_TOPOLOGY_NODES
from app.services.vector_store import VectorStoreManager
from app.services.vector_store.base import VectorDocument
from main import app


@pytest.fixture
def ephemeral_admin_env(tmp_path, monkeypatch):
    """Provision an isolated SQLite DB, local storage vault, workspace dir, and embedded Qdrant."""
    db_file = tmp_path / "ui_api_consistency.db"
    db_url = f"sqlite:///{db_file}"
    vs_dir = tmp_path / "qdrant"
    vs_dir.mkdir(parents=True, exist_ok=True)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / "monitored_ws"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("QDRANT_STORAGE_PATH", str(vs_dir))
    monkeypatch.setenv("QDRANT_PREFER_REMOTE", "false")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(storage_dir))
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)
    get_auth_service(reset=True, auth_enabled=False)
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(storage_dir)))
    set_embedding_db_config(provider="local", dense_model="BAAI/bge-small-en-v1.5")
    init_embeddings(provider="local", dense_model="BAAI/bge-small-en-v1.5")
    VectorStoreManager.reset_instance()

    # Seed realistic multi-language files on disk inside monitored workspace
    cobol_src = workspace_dir / "PAYROLL.CBL"
    cobol_src.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PAYROLL-PGM.\n"
        "       DATA DIVISION.\n"
        "       01 EMP-RECORD.\n"
        "       PROCEDURE DIVISION.\n"
        "       CALC-SECTION SECTION.\n"
        "       CALC-TAX-PARA.\n"
        "           PERFORM AUDIT-PARA.\n",
        encoding="utf-8",
    )
    csharp_src = workspace_dir / "LedgerService.cs"
    csharp_src.write_text(
        "namespace Billing;\n"
        "public record InvoiceRecord(string Id, decimal Amount);\n"
        "public class LedgerService {\n"
        "    public LedgerService() {}\n"
        "    public InvoiceRecord CreateInvoice(string id) => new(id, 42m);\n"
        "}\n",
        encoding="utf-8",
    )
    tsx_src = workspace_dir / "Dashboard.tsx"
    tsx_src.write_text(
        "export function DashboardView() { return <div>Active</div>; }\n",
        encoding="utf-8",
    )

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, provider, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("enterprise-mono", "https://github.com/org/enterprise-mono.git", "main", "deadbeef1234", "github", "synced"),
        )
        conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, enabled, category, repo) VALUES (?, 'local', 1, 1, 'architecture', 'local-ws')",
            (str(workspace_dir),),
        )
        # Seed multi-language indexed files + compiled bundles that must be filtered from topology
        seeded_files = [
            (str(cobol_src), "local-ws", "code", "cobol", 1700000100.0),
            (str(csharp_src), "local-ws", "code", "c_sharp", 1700000200.0),
            (str(tsx_src), "local-ws", "code", "tsx", 1700000300.0),
            ("src/PAYROLL.CBL", "enterprise-mono", "code", "cobol", 1700000400.0),
            ("Domain/LedgerService.cs", "enterprise-mono", "code", "c_sharp", 1700000500.0),
            ("ui/Dashboard.tsx", "enterprise-mono", "code", "tsx", 1700000600.0),
            ("app/engine.py", "enterprise-mono", "code", "python", 1700000700.0),
            # Compiled bundle noise that must NEVER pollute topology graphs
            ("www/assets/index-8a9b1c.js", "enterprise-mono", "code", "javascript", 1700000800.0),
            ("wwwroot/_framework/blazor.webassembly.js", "enterprise-mono", "code", "javascript", 1700000900.0),
            ("dist/assets/vendor.min.js", "enterprise-mono", "code", "javascript", 1700001000.0),
        ]
        conn.executemany(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime) VALUES (?, ?, ?, ?, ?)",
            seeded_files,
        )

        # Seed COBOL, C#, TSX, and Python AST symbols ( plus one inside compiled bundle )
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ast_symbols (repo, filepath, kind, name, full_symbol, signature, start_line, end_line, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("enterprise-mono", "src/PAYROLL.CBL", "program_definition", "PAYROLL-PGM", "PAYROLL-PGM", "PROGRAM-ID. PAYROLL-PGM.", 1, 20, "cobol"),
        )
        cobol_pgm_id = cur.lastrowid

        cur.execute(
            "INSERT INTO ast_symbols (repo, filepath, kind, name, full_symbol, signature, start_line, end_line, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("enterprise-mono", "src/PAYROLL.CBL", "paragraph", "CALC-TAX-PARA", "PAYROLL-PGM.CALC-TAX-PARA", "CALC-TAX-PARA.", 7, 15, "cobol"),
        )
        cobol_para_id = cur.lastrowid

        cur.execute(
            "INSERT INTO ast_symbols (repo, filepath, kind, name, full_symbol, signature, start_line, end_line, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("enterprise-mono", "Domain/LedgerService.cs", "record_declaration", "InvoiceRecord", "Billing.InvoiceRecord", "public record InvoiceRecord(string Id, decimal Amount)", 2, 2, "c_sharp"),
        )
        cs_record_id = cur.lastrowid

        cur.execute(
            "INSERT INTO ast_symbols (repo, filepath, kind, name, full_symbol, signature, start_line, end_line, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("enterprise-mono", "Domain/LedgerService.cs", "constructor_declaration", "LedgerService", "Billing.LedgerService.LedgerService", "public LedgerService()", 4, 4, "c_sharp"),
        )
        cs_ctor_id = cur.lastrowid

        cur.execute(
            "INSERT INTO ast_symbols (repo, filepath, kind, name, full_symbol, signature, start_line, end_line, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("enterprise-mono", "www/assets/index-8a9b1c.js", "function_declaration", "minifiedBundleFn", "minifiedBundleFn", "function minifiedBundleFn()", 1, 1, "javascript"),
        )

        # Relationships linking COBOL and C# symbols
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("enterprise-mono", cobol_pgm_id, "src/PAYROLL.CBL", "PAYROLL-PGM", "CALC-TAX-PARA", "CALLS", 12),
        )
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("enterprise-mono", cs_ctor_id, "Domain/LedgerService.cs", "LedgerService", "InvoiceRecord", "CALLS", 5),
        )
        conn.execute(
            "INSERT INTO file_summaries (filepath, repo, title, keywords, mtime) VALUES (?, ?, ?, ?, ?)",
            ("src/PAYROLL.CBL", "enterprise-mono", "Payroll Engine", json.dumps(["cobol", "payroll", "csharp"]), 1700000400.0),
        )
        conn.commit()

    yield {
        "engine": engine,
        "storage_dir": storage_dir,
        "workspace_dir": workspace_dir,
        "cobol_src": cobol_src,
        "cobol_para_id": cobol_para_id,
        "cs_record_id": cs_record_id,
    }

    set_current_auth_context(None)
    get_auth_service(reset=True, auth_enabled=False)
    VectorStoreManager.reset_instance()


@pytest.mark.asyncio
async def test_overview_stats_and_catalog_multi_language_consistency(ephemeral_admin_env):
    """Overview stats and Ingestion Catalog return UI-aligned schemas and multi-language files."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        with patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 4999, "limit": 5000}):
            stats_res = await client.get("/admin/api/stats")
        assert stats_res.status_code == 200
        stats = stats_res.json()
        for key in (
            "repos_count",
            "git_repos",
            "files_count",
            "symbols_count",
            "points_count",
            "vector_store_provider",
            "vector_store_mode",
            "dense_model",
            "top_keywords",
        ):
            assert key in stats
        assert stats["repos_count"] == 1
        assert stats["symbols_count"] >= 4
        assert "cobol" in stats["top_keywords"]

        cat_summary = await client.get("/admin/api/ingestion/catalog?source_type=all&detail_level=summary")
        assert cat_summary.status_code == 200
        summary_body = cat_summary.json()
        assert len(summary_body["git_repositories"]) == 1
        assert len(summary_body["monitored_paths"]) == 1
        assert summary_body["local_storage"]["root_path"] == str(ephemeral_admin_env["storage_dir"])

        cat_detailed = await client.get(
            "/admin/api/ingestion/catalog?source_type=all&detail_level=detailed&repo_name=enterprise-mono"
        )
        assert cat_detailed.status_code == 200
        langs = {f["language"] for f in cat_detailed.json()["files"]}
        assert {"cobol", "c_sharp", "tsx", "python"}.issubset(langs)

        cat_cbl = await client.get(
            "/admin/api/ingestion/catalog?detail_level=detailed&file_extension=.CBL"
        )
        assert cat_cbl.status_code == 200
        assert all(f["filepath"].upper().endswith(".CBL") for f in cat_cbl.json()["files"])


@pytest.mark.asyncio
async def test_navigator_and_file_endpoints_for_cobol_and_csharp(ephemeral_admin_env):
    """Code Navigator tree, outline, symbol-impact, omni-search, file read, and grep work across COBOL & C#."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        tree_res = await client.get("/admin/api/navigator/tree?repo=enterprise-mono")
        assert tree_res.status_code == 200
        tree = tree_res.json()
        assert tree["total_files"] >= 4
        assert tree["total_symbols"] >= 4

        outline_cbl = await client.get(
            "/admin/api/navigator/file-outline",
            params={"repo": "enterprise-mono", "filepath": "src/PAYROLL.CBL"},
        )
        assert outline_cbl.status_code == 200
        cbl_kinds = {s["kind"] for s in outline_cbl.json()["symbols"]}
        assert {"program_definition", "paragraph"}.issubset(cbl_kinds)

        outline_cs = await client.get(
            "/admin/api/navigator/file-outline",
            params={"repo": "enterprise-mono", "filepath": "Domain/LedgerService.cs"},
        )
        assert outline_cs.status_code == 200
        cs_kinds = {s["kind"] for s in outline_cs.json()["symbols"]}
        assert {"record_declaration", "constructor_declaration"}.issubset(cs_kinds)

        impact_res = await client.get(
            "/admin/api/navigator/symbol-impact",
            params={"repo": "enterprise-mono", "symbol_id": ephemeral_admin_env["cobol_para_id"]},
        )
        assert impact_res.status_code == 200
        impact = impact_res.json()
        assert impact["symbol"]["name"] == "CALC-TAX-PARA"
        assert any(c["source_symbol"] == "PAYROLL-PGM" for c in impact["callers"])

        omni_res = await client.get(
            "/admin/api/navigator/omni-search",
            params={"repo": "enterprise-mono", "q": "InvoiceRecord"},
        )
        assert omni_res.status_code == 200
        assert any(m["name"] == "InvoiceRecord" for m in omni_res.json()["matches"])

        read_res = await client.get(
            "/admin/api/files/read",
            params={"path": str(ephemeral_admin_env["cobol_src"]), "repo": "local-ws"},
        )
        assert read_res.status_code == 200
        assert "PROGRAM-ID. PAYROLL-PGM." in read_res.json()["content"]

        grep_res = await client.post(
            "/admin/api/search/grep",
            json={"pattern": "InvoiceRecord", "repo": "local-ws", "limit": 10},
        )
        assert grep_res.status_code == 200
        assert len(grep_res.json()["matches"]) >= 1


@pytest.mark.asyncio
async def test_topology_excludes_compiled_bundles_and_classifies_cobol_csharp(ephemeral_admin_env):
    """Topology graph strips www/assets, wwwroot/_framework, and .min.js bundles and enforces caps."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        files_topo = await client.get("/admin/api/graph/topology?repo=enterprise-mono&view_type=files")
        assert files_topo.status_code == 200
        file_nodes = files_topo.json()["nodes"]
        file_paths = {n.get("filepath") for n in file_nodes}

        assert "src/PAYROLL.CBL" in file_paths
        assert "Domain/LedgerService.cs" in file_paths
        assert "www/assets/index-8a9b1c.js" not in file_paths
        assert "wwwroot/_framework/blazor.webassembly.js" not in file_paths
        assert "dist/assets/vendor.min.js" not in file_paths
        assert len(file_nodes) <= MAX_TOPOLOGY_NODES
        assert len(files_topo.json()["edges"]) <= MAX_TOPOLOGY_EDGES

        sym_topo = await client.get("/admin/api/graph/topology?repo=enterprise-mono&view_type=symbols")
        assert sym_topo.status_code == 200
        sym_nodes = {n["name"]: n for n in sym_topo.json()["nodes"]}
        assert "minifiedBundleFn" not in sym_nodes
        assert sym_nodes["PAYROLL-PGM"]["type"] == "class"
        assert sym_nodes["InvoiceRecord"]["type"] == "class"
        assert sym_nodes["CALC-TAX-PARA"]["type"] == "function"

        details_res = await client.get(
            "/admin/api/graph/node-details",
            params={"id": f"symbol:{ephemeral_admin_env['cs_record_id']}"},
        )
        assert details_res.status_code == 200
        details = details_res.json()
        assert details["type"] == "class"
        assert details["metadata"]["kind"] == "record_declaration"
        assert details["metadata"]["language"] == "c_sharp"


@pytest.mark.asyncio
async def test_storage_repos_paths_and_settings_rebuild_confirmation_lifecycle(ephemeral_admin_env):
    """Verifies storage CRUD, repo/path CRUD, AI/file/auto-sync settings, and embedding rebuild confirmation."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # 1. Local storage upload -> read -> replace -> tree -> delete
        up_res = await client.post(
            "/admin/api/storage/upload",
            json={"path": "notes/runbook.md", "content": "# Runbook v1"},
        )
        assert up_res.status_code == 200

        get_file = await client.get("/admin/api/storage/file", params={"path": "notes/runbook.md"})
        assert get_file.status_code == 200
        assert get_file.json()["content"] == "# Runbook v1"

        put_file = await client.put(
            "/admin/api/storage/file",
            json={"path": "notes/runbook.md", "content": "# Runbook v2"},
        )
        assert put_file.status_code == 200

        tree_res = await client.get("/admin/api/storage/tree", params={"folder": "notes"})
        assert tree_res.status_code == 200
        assert any(f["name"] == "runbook.md" for f in tree_res.json()["files"])

        del_file = await client.delete("/admin/api/storage/file", params={"path": "notes/runbook.md"})
        assert del_file.status_code == 200

        # 2. Git repository & monitored path management
        with patch("app.services.indexing.sync_single_git_repo"):
            add_repo = await client.post(
                "/admin/api/repos",
                json={"name": "billing-cobol", "url": "https://github.com/org/billing-cobol.git", "branch": "main"},
            )
        assert add_repo.status_code == 200
        repos = (await client.get("/admin/api/repos")).json()
        billing = next(r for r in repos if r["name"] == "billing-cobol")
        del_repo = await client.delete(f"/admin/api/repos/{billing['id']}")
        assert del_repo.status_code == 200

        extra_dir = ephemeral_admin_env["workspace_dir"] / "sub"
        extra_dir.mkdir(exist_ok=True)
        with patch("app.services.indexing.run_full_indexing"):
            add_path = await client.post(
                "/admin/api/paths",
                json={"path": str(extra_dir), "repo": "sub-ws", "category": "docs"},
            )
        assert add_path.status_code == 200

        # 3. Settings endpoints (AI gateway, files, auto-sync, logs)
        gw_save = await client.post(
            "/admin/api/settings/ai-gateway",
            json={"url": "http://litellm:4000/v1", "chat_model": "gpt-4o-mini"},
        )
        assert gw_save.status_code == 200
        assert (await client.get("/admin/api/settings/ai-gateway")).status_code == 200

        fs_save = await client.post(
            "/admin/api/settings/files",
            json={"summary_max_file_size_mb": 12, "read_file_max_lines": 2500},
        )
        assert fs_save.status_code == 200
        fs_loaded = (await client.get("/admin/api/settings/files")).json()
        assert fs_loaded["summary_max_file_size_mb"] == 12
        assert fs_loaded["read_file_max_lines"] == 2500

        sync_save = await client.post("/admin/api/settings/auto-sync", json={"interval_mins": 30})
        assert sync_save.status_code == 200
        assert (await client.get("/admin/api/settings/auto-sync")).json()["interval_mins"] == 30
        assert (await client.get("/admin/api/logs")).status_code == 200

        # 4. Embedding dimension transition: 400 without rebuild_index -> 200 with rebuild_index=True
        store = VectorStoreManager.get_vector_store()
        store.upsert_documents([
            VectorDocument(
                id="seed-vec-1",
                text="IDENTIFICATION DIVISION.",
                dense_vector=[0.1] * 384,
                repo="enterprise-mono",
                doc_type="code",
                path="src/PAYROLL.CBL",
            )
        ])
        with patch("app.services.embeddings.get_dense_dim_for_config", return_value=1536), patch(
            "app.services.embeddings.get_dense_embeddings_batch", return_value=[[0.1] * 1536]
        ), patch("app.services.indexing.run_full_indexing"):
            reject_res = await client.post(
                "/admin/api/settings/embedding",
                json={"provider": "api", "dense_model": "openai/text-embedding-3-small", "rebuild_index": False},
            )
            assert reject_res.status_code == 400
            assert "Explicit rebuild confirmation is required" in reject_res.json()["error"]

            confirm_res = await client.post(
                "/admin/api/settings/embedding",
                json={"provider": "api", "dense_model": "openai/text-embedding-3-small", "rebuild_index": True},
            )
            assert confirm_res.status_code == 200
            assert confirm_res.json()["status"] == "success"


@pytest.mark.asyncio
async def test_rbac_enforcement_across_ui_and_admin_endpoints(ephemeral_admin_env, monkeypatch):
    """When AUTH_ENABLED=true, Anonymous gets 401, Viewer gets 200 read / 403 write, Admin gets 200."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    key_service = ApiKeyService(engine=ephemeral_admin_env["engine"])
    auth_srv = AuthService(
        auth_enabled=True,
        resource_indicator="https://contextcortex.local",
        key_service=key_service,
    )
    get_auth_service(reset=True, auth_enabled=True, key_service=key_service)

    viewer_key = auth_srv.issue_api_key(name="UI Viewer", role=Role.VIEWER).secret_key
    editor_key = auth_srv.issue_api_key(name="UI Editor", role=Role.EDITOR).secret_key
    admin_key = auth_srv.issue_api_key(name="UI Admin", role=Role.ADMIN).secret_key

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Anonymous -> 401
        assert (await client.get("/admin/api/stats")).status_code == 401
        assert (await client.get("/admin/api/navigator/tree?repo=enterprise-mono")).status_code == 401

        # Viewer -> 200 on read-only UI endpoints, 403 on storage & admin settings
        v_hdr = {"Authorization": f"Bearer {viewer_key}"}
        assert (await client.get("/admin/api/ingestion/catalog", headers=v_hdr)).status_code == 200
        assert (await client.get("/admin/api/graph/topology?repo=enterprise-mono", headers=v_hdr)).status_code == 200
        assert (
            await client.post("/admin/api/storage/upload", json={"path": "x.md", "content": "hi"}, headers=v_hdr)
        ).status_code == 403
        assert (await client.get("/admin/api/settings/ai-gateway", headers=v_hdr)).status_code == 403

        # Editor -> 200 on storage upload, 403 on admin settings
        e_hdr = {"Authorization": f"Bearer {editor_key}"}
        assert (
            await client.post("/admin/api/storage/upload", json={"path": "x.md", "content": "hi"}, headers=e_hdr)
        ).status_code == 200
        assert (await client.get("/admin/api/settings/embedding", headers=e_hdr)).status_code == 403

        # Admin -> 200 on admin settings
        a_hdr = {"Authorization": f"Bearer {admin_key}"}
        assert (await client.get("/admin/api/settings/ai-gateway", headers=a_hdr)).status_code == 200
        assert (await client.get("/admin/api/settings/embedding", headers=a_hdr)).status_code == 200

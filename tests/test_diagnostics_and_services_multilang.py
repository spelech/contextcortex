import ast
from pathlib import Path
import pytest
from sqlalchemy import create_engine

import app.services.git_manager as git_manager
from app.services.database import check_db_readiness, get_db_connection, init_db
from app.services.database.engine import dispose_global_engine
from app.services.diagnostics import (
    diagnose_issue,
    extract_diagnostic_signals,
    normalize_stack_path,
    parse_stack_frames,
)
from app.services.file_reader import ALLOWED_TEXT_EXTENSIONS as READER_EXTENSIONS, FileReaderService
from app.services.local_storage import ALLOWED_TEXT_EXTENSIONS as STORAGE_EXTENSIONS, LocalStorageService
from app.services.vector_store.base import VectorDocument, VectorSearchResult
from app.services.vector_store.chroma_store import ChromaVectorStore
from app.services.vector_store.pgvector_queries import _build_or_tsquery
from app.services.vector_store.pgvector_store import PgVectorStore
from qdrant_client.http import models as qmodels
from app.services.vector_store.qdrant_store import QdrantVectorStore


def _det_dense_embed(text: str):
    low = (text or "").lower()
    return [
        1.0 if ("c#" in low or "httpget" in low or "foo.cs" in low) else 0.1,
        1.0 if ("customer-record" in low or "payroll" in low) else 0.1,
        1.0 if ("$var" in low or "clientapi" in low) else 0.1,
        0.25,
    ]


def _det_sparse_embed(text: str):
    cleaned = (text or "").lower()
    for ch in ("\\", "/", ":", "[", "]", "(", ")", "{", "}", '"', ";", ","):
        cleaned = cleaned.replace(ch, " ")
    tokens = [t for t in cleaned.split() if t]
    if not tokens:
        return qmodels.SparseVector(indices=[1], values=[0.1])
    indices = sorted({(abs(hash(tok)) % 997) + 1 for tok in tokens})
    return qmodels.SparseVector(indices=indices, values=[1.0 for _ in indices])


def test_parse_csharp_posix_and_windows_frames():
    trace = (
        "System.InvalidOperationException: Charge declined for route POST /api/v1/charges\n"
        "   at Billing.Api.Services.BillingService.ChargeCard(String id) in C:\\agent\\_work\\1\\s\\src\\Services\\BillingService.cs:line 88\n"
        "   at Billing.Api.Components.Foo.Render() in /src/Components/Foo.cs:line 42\n"
    )
    frames = parse_stack_frames(trace)
    assert len(frames) == 2
    assert (frames[0]["path"], frames[0]["line"], frames[0]["function"]) == (
        "src/Services/BillingService.cs", 88, "Billing.Api.Services.BillingService.ChargeCard",
    )
    assert (frames[1]["path"], frames[1]["line"], frames[1]["function"]) == (
        "src/Components/Foo.cs", 42, "Billing.Api.Components.Foo.Render",
    )
    assert normalize_stack_path(r"C:\src\Components\Foo.cs") == "src/Components/Foo.cs"


def test_parse_ts_react_vite_and_bundler_frames():
    trace = (
        "TypeError: Cannot read properties of undefined (reading 'map')\n"
        "    at handleSave (src/GitRepoManager.tsx:67:15)\n"
        "    at Object.fetchClientsApi (/app/frontend/src/api/clientApi.ts:5:20)\n"
        "    at async http://localhost:3000/src/App.tsx?t=1709912:42:10\n"
        "    at eval (webpack-internal:///./src/hooks/useSession.mjs:19:4)\n"
    )
    frames = parse_stack_frames(trace)
    assert [(f["path"], f["line"], f["function"]) for f in frames] == [
        ("src/GitRepoManager.tsx", 67, "handleSave"),
        ("frontend/src/api/clientApi.ts", 5, "Object.fetchClientsApi"),
        ("src/App.tsx", 42, None),
        ("src/hooks/useSession.mjs", 19, "eval"),
    ]


def test_parse_all_four_cobol_diagnostic_and_abend_formats():
    cobol_trace = (
        "PAYROLL.CBL:141: error: 'WS-TAX-RATE' is not defined\n"
        "libcob: PAYROLL.cbl: 142: attempt to reference unallocated memory (signal SIGSEGV)\n"
        "In paragraph 1000-CALC-TAX of program PAYROLL (src/cobol/PAYROLL.CBL:143)\n"
        "ABEND S0C7 in program PAYROLL paragraph 1000-CALC-TAX at statement 144\n"
    )
    frames = parse_stack_frames(cobol_trace)
    assert len(frames) == 4
    assert (frames[0]["path"], frames[0]["line"]) == ("PAYROLL.CBL", 141)
    assert (frames[1]["path"], frames[1]["line"]) == ("PAYROLL.cbl", 142)
    assert (frames[2]["path"], frames[2]["line"], frames[2]["function"], frames[2]["program"]) == (
        "src/cobol/PAYROLL.CBL", 143, "1000-CALC-TAX", "PAYROLL",
    )
    assert (frames[3]["path"], frames[3]["line"], frames[3]["function"], frames[3]["program"]) == (
        "PAYROLL.CBL", 144, "1000-CALC-TAX", "PAYROLL",
    )
    signals = extract_diagnostic_signals(cobol_trace)
    assert "S0C7" in signals["exceptions"]
    assert "WS-TAX-RATE" in signals["quoted_errors"]
    assert {"1000-CALC-TAX", "PAYROLL"}.issubset(set(signals["symbols"]))


def test_diagnose_issue_multilang_end_to_end(tmp_path, monkeypatch):
    db_file = tmp_path / "multilang_diag.db"
    vault_dir = tmp_path / "vault"
    repos_root = vault_dir / "repos"

    cs_file = repos_root / "billing-api" / "src" / "Services" / "BillingService.cs"
    cs_file.parent.mkdir(parents=True, exist_ok=True)
    cs_file.write_text(
        "\n".join([
            "namespace Billing.Api.Services;",
            "public class BillingService {",
            "    public Receipt ChargeCard(string customerId) {",
            "        var ledger = NormalizeLedger(customerId);",
            "        if (ledger == null) throw new InvalidOperationException(\"Ledger missing\");",
            "        return SubmitGateway(ledger);",
            "    }",
            "}",
        ]),
        encoding="utf-8",
    )

    tsx_file = repos_root / "web-ui" / "src" / "App.tsx"
    tsx_file.parent.mkdir(parents=True, exist_ok=True)
    tsx_file.write_text(
        "\n".join([
            "import React from 'react';",
            "export async function App() {",
            "  const data = await fetch('/api/v1/charges', { method: 'POST' });",
            "  if (!data.ok) throw new Error('Failed charge request');",
            "  return <div>{String(data.status)}</div>;",
            "}",
        ]),
        encoding="utf-8",
    )

    cbl_file = repos_root / "core-mainframe" / "src" / "cobol" / "PAYROLL.cbl"
    cbl_file.parent.mkdir(parents=True, exist_ok=True)
    cbl_file.write_text(
        "\n".join([
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. PAYROLL.",
            "       PROCEDURE DIVISION.",
            "       0000-MAIN.",
            "           PERFORM 1000-CALC-TAX.",
            "           STOP RUN.",
            "       1000-CALC-TAX.",
            "           COMPUTE WS-TAX = WS-GROSS * WS-RATE.",
            "           PERFORM 2000-AUDIT-LOG.",
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(git_manager, "PERSISTENT_REPOS_DIR", str(repos_root))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("VAULT_PATH", str(vault_dir))
    dispose_global_engine()
    init_db(str(vault_dir))

    monkeypatch.setattr(
        "app.services.diagnostics.execute_hybrid_search",
        lambda query_text, doc_type=None, repo=None, limit=5: [
            VectorSearchResult(
                id="cand-1",
                score=0.91,
                payload={
                    "repo": repo or "billing-api",
                    "rel_path": "src/Services/BillingService.cs",
                    "start_line": 3,
                    "end_line": 7,
                    "symbol": "ChargeCard",
                    "full_symbol": "BillingService.ChargeCard",
                    "kind": "method",
                    "content": cs_file.read_text(encoding="utf-8"),
                },
            )
        ],
    )

    with get_db_connection() as conn:
        for name, sha in [("billing-api", "111aaaa"), ("web-ui", "222bbbb"), ("core-mainframe", "333cccc")]:
            conn.execute(
                "INSERT INTO git_repositories (name, url, branch, commit_sha, provider) VALUES (?, ?, ?, ?, ?)",
                (name, f"https://github.com/org/{name}", "main", sha, "github"),
            )
        conn.executemany(
            "INSERT INTO indexed_files (filepath, repo, hash, doc_type, language, commit_sha) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("billing-api://src/Services/BillingService.cs", "billing-api", "h1", "code", "csharp", "111aaaa"),
                ("web-ui://src/App.tsx", "web-ui", "h2", "code", "typescript", "222bbbb"),
                ("core-mainframe://src/cobol/PAYROLL.cbl", "core-mainframe", "h3", "code", "cobol", "333cccc"),
            ],
        )
        conn.executemany(
            "INSERT INTO ast_symbols (id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "billing-api", "billing-api://src/Services/BillingService.cs", "ChargeCard", "BillingService.ChargeCard", "method", 3, 7, "public Receipt ChargeCard(string customerId)", "csharp"),
                (2, "web-ui", "web-ui://src/App.tsx", "App", "App", "function", 2, 6, "export async function App()", "typescript"),
                (3, "core-mainframe", "core-mainframe://src/cobol/PAYROLL.cbl", "1000-CALC-TAX", "PAYROLL.1000-CALC-TAX", "paragraph", 7, 9, "1000-CALC-TAX.", "cobol"),
            ],
        )
        conn.executemany(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("billing-api", 1, "billing-api://src/Controllers/BillingController.cs", "BillingController.CreateCharge", "BillingService.ChargeCard", "CALLS", 24),
                ("billing-api", 1, "billing-api://src/Services/BillingService.cs", "BillingService.ChargeCard", "NormalizeLedger", "CALLS", 4),
                ("core-mainframe", 3, "core-mainframe://src/cobol/PAYROLL.cbl", "0000-MAIN", "1000-CALC-TAX", "PERFORMS", 5),
                ("core-mainframe", 3, "core-mainframe://src/cobol/PAYROLL.cbl", "PAYROLL.1000-CALC-TAX", "2000-AUDIT-LOG", "PERFORMS", 9),
            ],
        )
        conn.execute(
            "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("billing-api", "billing-api://src/Controllers/BillingController.cs", "aspnet", "POST", "/api/v1/charges", "BillingController.CreateCharge", 20, 30),
        )
        conn.execute(
            "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES (?, ?, ?, ?, ?, ?)",
            ("web-ui", "web-ui://src/App.tsx", "POST", "/api/v1/charges", "App", 3),
        )

    cs_diag = diagnose_issue(
        "System.InvalidOperationException: Ledger missing on POST /api/v1/charges\n"
        "   at Billing.Api.Services.BillingService.ChargeCard(String customerId) "
        "in C:\\agent\\_work\\1\\s\\src\\Services\\BillingService.cs:line 5"
    )
    cs_frame = cs_diag["resolved_frames"][0]
    assert (cs_frame["repo"], cs_frame["file"], cs_frame["symbol"]) == (
        "billing-api", "src/Services/BillingService.cs", "BillingService.ChargeCard",
    )
    assert "NormalizeLedger" in cs_frame["code"]
    assert cs_frame["callers"][0]["symbol"] == "BillingController.CreateCharge"
    assert [c["symbol"] for c in cs_frame["callees"]] == ["NormalizeLedger"]
    assert "billing-api/blob/111aaaa/src/Services/BillingService.cs#L5" in cs_frame["permalink"]
    assert cs_diag["matched_routes"][0]["handler"]["symbol"] == "BillingController.CreateCharge"
    assert cs_diag["matched_routes"][0]["external_callers"][0]["symbol"] == "App"

    vite_diag = diagnose_issue("Error: Failed charge request\n    at async http://localhost:3000/src/App.tsx:4:11")
    assert (vite_diag["resolved_frames"][0]["repo"], vite_diag["resolved_frames"][0]["file"], vite_diag["resolved_frames"][0]["symbol"]) == (
        "web-ui", "src/App.tsx", "App",
    )
    assert "fetch('/api/v1/charges'" in vite_diag["resolved_frames"][0]["code"]

    cobol_diag = diagnose_issue("ABEND S0C7 in program PAYROLL paragraph 1000-CALC-TAX at statement 8")
    cbl_frame = cobol_diag["resolved_frames"][0]
    assert (cbl_frame["repo"], cbl_frame["file"], cbl_frame["symbol"]) == (
        "core-mainframe", "src/cobol/PAYROLL.cbl", "PAYROLL.1000-CALC-TAX",
    )
    assert "COMPUTE WS-TAX = WS-GROSS * WS-RATE." in cbl_frame["code"]
    assert cbl_frame["callers"][0]["symbol"] == "0000-MAIN"
    assert [c["symbol"] for c in cbl_frame["callees"]] == ["2000-AUDIT-LOG"]
    assert any("1000-CALC-TAX" in s["symbol"] for s in cobol_diag["matched_symbols"])
    dispose_global_engine()


def test_file_reader_and_local_storage_extensions_resolution_and_security(tmp_path, monkeypatch):
    for ext in (".cbl", ".cob", ".cpy", ".mjs", ".cjs"):
        assert ext in READER_EXTENSIONS
        assert ext in STORAGE_EXTENSIONS

    db_file = tmp_path / "reader_test.db"
    vault_dir = tmp_path / "vault"
    storage_dir = tmp_path / "local_docs"
    repos_dir = tmp_path / "persistent_repos"
    outside_dir = tmp_path / "outside_secret"
    for d in (vault_dir, storage_dir, repos_dir, outside_dir):
        d.mkdir(parents=True, exist_ok=True)

    secret_file = outside_dir / "secret.txt"
    secret_file.write_text("TOP_SECRET", encoding="utf-8")

    monkeypatch.setattr(git_manager, "PERSISTENT_REPOS_DIR", str(repos_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("VAULT_PATH", str(vault_dir))
    dispose_global_engine()
    init_db(str(vault_dir))

    with get_db_connection() as conn:
        conn.executemany(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, provider) VALUES (?, ?, ?, ?, ?)",
            [
                ("legacy-ledger", "https://github.com/org/legacy-ledger", "main", "aaa111", "github"),
                ("ephemeral-indexed", "https://github.com/org/ephemeral-indexed", "main", "bbb222", "github"),
                ("missing-clone", "https://github.com/org/missing-clone", "main", "ccc333", "github"),
            ],
        )

    local_svc = LocalStorageService(storage_root=str(storage_dir))
    for rel, body in [
        ("batch/PAYROLL.cbl", "       01 CUSTOMER-RECORD.\n           05 CUST-ID PIC X(10).\n"),
        ("copybooks/CUST.cpy", "       05 CUST-BALANCE PIC S9(7)V99 COMP-3.\n"),
        ("esm/loader.mjs", "export const loadConfig = ($var) => $var;\n"),
        ("cjs/helper.cjs", "module.exports = { ok: true };\n"),
    ]:
        assert local_svc.is_allowed_text_file(rel)
        local_svc.save_file_content(rel, body)
    assert "01 CUSTOMER-RECORD." in local_svc.read_file_content("batch/PAYROLL.cbl")["content"]
    with pytest.raises(ValueError):
        local_svc.read_file_content("../../outside_secret/secret.txt")

    cobol_repo_dir = repos_dir / "legacy-ledger" / "src"
    cobol_repo_dir.mkdir(parents=True, exist_ok=True)
    (cobol_repo_dir / "LEDGER.cob").write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. LEDGER.\n       01 CUSTOMER-RECORD.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("app.services.vector_store.qdrant_store.get_dense_dim", lambda: 4)
    monkeypatch.setattr("app.services.vector_store.qdrant_store.get_dense_embedding", _det_dense_embed)
    monkeypatch.setattr("app.services.vector_store.qdrant_store.get_sparse_embedding", _det_sparse_embed)
    mem_qdrant = QdrantVectorStore(storage_path=":memory:", prefer_remote=False, collection_name="reader_recon")
    mem_qdrant.upsert_documents([
        VectorDocument(
            id="recon-1",
            text="       PROGRAM-ID. RECON.\n       01 WS-TOTAL PIC 9(5).",
            dense_vector=[0.5, 0.5, 0.5, 0.5],
            repo="ephemeral-indexed",
            path="ephemeral-indexed://src/RECON.cbl",
            rel_path="src/RECON.cbl",
            start_line=1,
            end_line=2,
        )
    ])
    monkeypatch.setattr("app.services.vector_store.get_vector_store", lambda: mem_qdrant)

    reader = FileReaderService(storage_root=str(storage_dir))
    res_uri = reader.read_file("legacy-ledger://src/LEDGER.cob")
    assert res_uri["source"] == "persistent_repo"
    assert "PROGRAM-ID. LEDGER." in res_uri["content"]
    assert "01 CUSTOMER-RECORD." in reader.read_file("src/LEDGER.cob", repo="legacy-ledger")["content"]

    grep_hits = reader.grep_code("CUSTOMER-RECORD")
    assert grep_hits["total_matches"] >= 2
    matched_paths = [m["file"] for m in grep_hits["matches"]]
    assert any(p.endswith("LEDGER.cob") for p in matched_paths)
    assert any(p.endswith("PAYROLL.cbl") for p in matched_paths)

    recon = reader.read_file("ephemeral-indexed://src/RECON.cbl")
    assert recon["source"] == "vector_store"
    assert "PROGRAM-ID. RECON." in recon["content"]

    with pytest.raises(FileNotFoundError) as exc_info:
        reader.read_file("missing-clone://src/GHOST.cbl")
    assert "missing-clone" in str(exc_info.value)
    assert "persistent shallow clone" in str(exc_info.value).lower()

    symlink_escape = storage_dir / "escape_link.cbl"
    symlink_escape.symlink_to(secret_file)
    for bad_call in [
        lambda: reader.read_file("../outside_secret/secret.txt"),
        lambda: reader.read_file("legacy-ledger://../../outside_secret/secret.txt"),
        lambda: reader.read_file("batch/PAYROLL.cbl\x00.txt"),
        lambda: reader.read_file("escape_link.cbl", repo="local_storage"),
    ]:
        with pytest.raises((PermissionError, ValueError)):
            bad_call()

    dispose_global_engine()


def test_vector_stores_special_character_hardening(tmp_path, monkeypatch):
    for mod_path in (
        "app.services.vector_store.pgvector_store",
        "app.services.vector_store.qdrant_store",
        "app.services.vector_store.chroma_store",
    ):
        monkeypatch.setattr(f"{mod_path}.get_dense_dim", lambda: 4)
        monkeypatch.setattr(f"{mod_path}.get_dense_embedding", _det_dense_embed)
    monkeypatch.setattr("app.services.vector_store.qdrant_store.get_sparse_embedding", _det_sparse_embed)

    for tricky in ('C# [HttpGet("{id}")]', "01 CUSTOMER-RECORD.", "$var !== undefined && (a | b)", r"C:\src\Components\Foo.cs"):
        tsq = _build_or_tsquery(tricky)
        assert tsq
        for forbidden in ("#", "[", "]", "{", "}", '"', ".", "$", "\\", "(", ")", "!"):
            assert forbidden not in tsq

    sample_docs = [
        VectorDocument(
            id="doc-csharp",
            text='// C:\\src\\Components\\Foo.cs\n[HttpGet("{id}")]\npublic IActionResult GetById(string id) => Ok(id); // C#',
            dense_vector=_det_dense_embed('C# [HttpGet("{id}")] Foo.cs'),
            doc_type="code", repo="win-api", language="csharp", title="Foo.cs", symbol="GetById",
            path=r"C:\src\Components\Foo.cs", rel_path=r"src\Components\Foo.cs",
            start_line=10, end_line=20, tags=["C#", "[HttpGet]"],
        ),
        VectorDocument(
            id="doc-cobol",
            text="       01 CUSTOMER-RECORD.\n           05 CUST-KEY PIC X(12).",
            dense_vector=_det_dense_embed("01 CUSTOMER-RECORD. PAYROLL.CBL"),
            doc_type="code", repo="mainframe-cobol", language="cobol", title="PAYROLL.CBL",
            symbol="CUSTOMER-RECORD", path="mainframe-cobol://src/PAYROLL.CBL", rel_path="src/PAYROLL.CBL",
            start_line=40, end_line=55, tags=["cobol"],
        ),
        VectorDocument(
            id="doc-ts",
            text="export const resolveVar = ($var: string) => `${$var}_ok`;",
            dense_vector=_det_dense_embed("$var clientApi.ts"),
            doc_type="code", repo="web-ui", language="typescript", title="clientApi.ts",
            symbol="fetchClientsApi", path="web-ui://src/api/clientApi.ts", rel_path="src/api/clientApi.ts",
            start_line=1, end_line=12, tags=["$var"], metadata={"$var": "sanitized-meta-key"},
        ),
    ]

    sqlite_engine = create_engine(f"sqlite:///{tmp_path / 'pgvec_compat.sqlite'}")
    stores = [
        ("pgvector", PgVectorStore(engine=sqlite_engine, collection_name="multilang_spec", dimension=4)),
        ("qdrant", QdrantVectorStore(storage_path=":memory:", prefer_remote=False, collection_name="multilang_spec")),
        ("chroma", ChromaVectorStore(storage_path=":memory:", prefer_remote=False, collection_name="multilang_spec")),
    ]

    for backend_name, store in stores:
        assert store.upsert_documents(sample_docs) is True
        modes = store.get_capabilities().get("search_modes", ["semantic"])
        for query_str, expected_title in [
            ("C#", "Foo.cs"),
            ('[HttpGet("{id}")]', "Foo.cs"),
            ("01 CUSTOMER-RECORD.", "PAYROLL.CBL"),
            ("$var", "clientApi.ts"),
            (r"C:\src\Components\Foo.cs", "Foo.cs"),
        ]:
            sem_hits = store.search(query_str, limit=3, search_mode="semantic")
            assert any(h.payload.get("title") == expected_title for h in sem_hits), f"{backend_name} semantic missed on {query_str!r}"
            if "hybrid" in modes:
                hyb_hits = store.search(query_str, limit=3, search_mode="hybrid")
                assert any(h.payload.get("title") == expected_title for h in hyb_hits), f"{backend_name} hybrid missed on {query_str!r}"
            if "lexical" in modes:
                lex_hits = store.search(query_str, limit=3, search_mode="lexical")
                assert any(h.payload.get("title") == expected_title for h in lex_hits), f"{backend_name} lexical missed on {query_str!r}"

        assert len(store.grep_chunks('[HttpGet("{id}")]')) == 1
        assert len(store.grep_chunks("01 CUSTOMER-RECORD.")) == 1
        assert len(store.grep_chunks("$var", repo="web-ui")) == 1
        chunks = store.get_file_chunks(r"src\Components\Foo.cs", repo="win-api")
        assert len(chunks) == 1 and '[HttpGet("{id}")]' in chunks[0]["content"]

    sqlite_engine.dispose()


def test_module_reexports_and_line_count_guardrail():
    from app.services.database import connection as db_conn

    assert callable(check_db_readiness)
    assert callable(db_conn.get_vector_store_db_config)
    assert callable(db_conn.get_embedding_db_config)
    assert callable(db_conn.get_file_settings)

    repo_root = Path(__file__).resolve().parents[1]
    owned_files = [
        repo_root / "app/services/diagnostics.py",
        repo_root / "app/services/stack_trace_parser.py",
        repo_root / "app/services/file_reader.py",
        repo_root / "app/services/file_path_resolver.py",
        repo_root / "app/services/code_grep_scanner.py",
        repo_root / "app/services/local_storage.py",
        repo_root / "app/services/database/connection.py",
        repo_root / "app/services/database/config_store.py",
        repo_root / "app/services/database/__init__.py",
        *sorted((repo_root / "app/services/vector_store").glob("*.py")),
        Path(__file__).resolve(),
    ]
    newly_created = {
        "stack_trace_parser.py", "file_path_resolver.py", "code_grep_scanner.py",
        "config_store.py", "pgvector_queries.py", "pgvector_chunk_scanner.py",
        "qdrant_queries.py", "chroma_queries.py",
    }
    for py_file in owned_files:
        lines = py_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 500, f"{py_file} exceeds 500 LOC ({len(lines)} lines)"
        if py_file.name in newly_created:
            for node in ast.walk(ast.parse(py_file.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ClassDef):
                    assert not node.name.endswith(("Manager", "Helper", "Util", "Data"))

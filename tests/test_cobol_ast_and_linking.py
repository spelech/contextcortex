import json
import os
import sqlite3
from unittest.mock import patch

import pytest

from app.services.architecture import detect_entry_points, synthesize_architecture
from app.services.chunking import (
    detect_language,
    extract_symbols_and_chunks,
    get_tree_sitter_parser,
    is_code_file,
)
from app.services.indexing.git_delta_scanner import (
    DEFAULT_SUPPORTED_EXTENSIONS,
    compute_git_repo_delta,
    persist_sync_batch,
)
from app.services.indexing.processor import compute_text_hash, process_file_content
from app.services.navigator import get_file_outline, get_symbol_impact
from app.services.search import trace_symbol_path

PAYROLL_FIXED_CBL = """\
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. PAYROLL.
000300* Fixed-format mainframe payroll driver
000400 DATA DIVISION.
000500 WORKING-STORAGE SECTION.
000600 COPY CUSTCOPY.
000700 EXEC SQL INCLUDE TAXSQL END-EXEC.
000800 01 WS-PAYROLL-RECORD.
000900    05 WS-EMP-ID        PIC X(10).
001000    05 WS-GROSS-PAY     PIC 9(7)V99.
001100 01 FILLER.
001200    05 WS-TEMP-FLAG     PIC X(1).
001300 01 WS-AUDIT-PGM        PIC X(8) VALUE 'AUDITSB'.
001400 PROCEDURE DIVISION.
001500 1000-MAIN-SECTION SECTION.
001600 1100-INIT.
001700     PERFORM 2000-CALC-TAX THRU 2099-CALC-EXIT.
001800     CALL WS-AUDIT-PGM USING WS-PAYROLL-RECORD.
001900     EXEC CICS LINK PROGRAM('CICSLOG') END-EXEC.
002000     STOP RUN.
002100 2000-CALC-TAX.
002200     CALL 'TAXSUB' USING WS-PAYROLL-RECORD.
002300     EXEC CICS XCTL PROGRAM('CICSNEXT') END-EXEC.
002400 2099-CALC-EXIT.
002500     EXIT.
"""

TAXSUB_FREE_COB = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. TAXSUB.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 LS-TAX-RATE.
   05 LS-FED-RATE PIC V999 VALUE .220.
PROCEDURE DIVISION.
0100-COMPUTE-TAX.
    CALL 'RATESVC' USING LS-TAX-RATE.
    GOBACK.
"""

CUSTCOPY_CPY = """\
      * Shared customer master copybook
       01 CUSTOMER-MASTER.
          05 CUST-ID           PIC X(10).
          05 CUST-NAME         PIC X(40).
       01 FILLER               PIC X(20).
       01 CUSTOMER-ADDRESS.
          05 CUST-CITY         PIC X(25).
"""


def _init_ephemeral_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE git_repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, url TEXT, commit_sha TEXT, provider TEXT,
            enabled INTEGER DEFAULT 1
        );
        CREATE TABLE indexed_paths (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT, type TEXT, recursive INTEGER, category TEXT, repo TEXT, enabled INTEGER DEFAULT 1
        );
        CREATE TABLE indexed_files (
            filepath TEXT PRIMARY KEY, repo TEXT, doc_type TEXT, language TEXT,
            commit_sha TEXT, mtime REAL, hash TEXT
        );
        CREATE TABLE file_summaries (
            filepath TEXT PRIMARY KEY, repo TEXT, title TEXT, folder TEXT,
            category TEXT, tags TEXT, headings TEXT, keywords TEXT, summary_text TEXT, mtime REAL
        );
        CREATE TABLE ast_symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT, filepath TEXT, name TEXT, full_symbol TEXT, kind TEXT,
            start_line INTEGER, end_line INTEGER, signature TEXT, language TEXT
        );
        CREATE TABLE ast_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT, source_symbol_id INTEGER, source_filepath TEXT,
            source_symbol TEXT, target_symbol TEXT, relationship_type TEXT, line_number INTEGER
        );
        CREATE TABLE api_routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT, filepath TEXT, framework TEXT, http_method TEXT, path_pattern TEXT,
            handler_symbol TEXT, start_line INTEGER, end_line INTEGER
        );
        CREATE TABLE api_client_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT, filepath TEXT, http_method TEXT, url_pattern TEXT,
            caller_symbol TEXT, line_number INTEGER
        );
        CREATE TABLE architecture_decision_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT, title TEXT, status TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def _connect_factory(db_path: str):
    def _get_conn():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return _get_conn


def test_cobol_language_registration_and_parser():
    for ext in (".cbl", ".cob", ".cpy", ".CBL", ".COB", ".CPY"):
        fname = f"SRC/MAIN{ext}"
        assert detect_language(fname) == "cobol"
        assert is_code_file(fname) is True
    for ext in (".cbl", ".cob", ".cpy"):
        assert ext in DEFAULT_SUPPORTED_EXTENSIONS
    parser = get_tree_sitter_parser("cobol")
    assert parser is not None


def test_fixed_format_cobol_symbols_lines_and_relationships():
    res = extract_symbols_and_chunks(PAYROLL_FIXED_CBL, "src/PAYROLL.cbl", repo="core_ledger")
    by_full = {s.full_symbol: s for s in res.symbols}

    assert "PAYROLL" in by_full
    prog = by_full["PAYROLL"]
    assert prog.kind == "program_definition"
    assert prog.start_line == 1
    assert prog.end_line == 25

    assert "PAYROLL.WS-PAYROLL-RECORD" in by_full
    rec = by_full["PAYROLL.WS-PAYROLL-RECORD"]
    assert rec.kind == "record_definition"
    assert rec.start_line == 8
    assert rec.end_line == 10

    # FILLER 01-level items must never pollute symbol tables
    assert not any(s.name.upper() == "FILLER" for s in res.symbols)

    sec = by_full["PAYROLL.1000-MAIN-SECTION"]
    assert sec.kind == "section"
    assert sec.start_line == 15
    assert sec.end_line == 25

    p_init = by_full["PAYROLL.1100-INIT"]
    assert p_init.kind == "paragraph"
    assert (p_init.start_line, p_init.end_line) == (16, 20)

    p_tax = by_full["PAYROLL.2000-CALC-TAX"]
    assert p_tax.kind == "paragraph"
    assert (p_tax.start_line, p_tax.end_line) == (21, 23)

    p_exit = by_full["PAYROLL.2099-CALC-EXIT"]
    assert p_exit.kind == "paragraph"
    assert (p_exit.start_line, p_exit.end_line) == (24, 25)

    rels = {(r.source_symbol, r.target_symbol, r.relationship_type, r.line_number) for r in res.relationships}
    # Copybook & SQL INCLUDE imports
    assert ("PAYROLL", "CUSTCOPY", "IMPORTS", 6) in rels
    assert ("PAYROLL", "TAXSQL", "IMPORTS", 7) in rels
    # Intra-program PERFORM + THRU
    assert ("PAYROLL.1100-INIT", "2000-CALC-TAX", "CALLS", 17) in rels
    assert ("PAYROLL.1100-INIT", "2099-CALC-EXIT", "CALLS", 17) in rels
    # Dynamic CALL resolved via WORKING-STORAGE VALUE clause
    assert ("PAYROLL.1100-INIT", "AUDITSB", "CALLS", 18) in rels
    # CICS LINK & XCTL program transfers
    assert ("PAYROLL.1100-INIT", "CICSLOG", "CALLS", 19) in rels
    assert ("PAYROLL.2000-CALC-TAX", "TAXSUB", "CALLS", 22) in rels
    assert ("PAYROLL.2000-CALC-TAX", "CICSNEXT", "CALLS", 23) in rels


def test_free_format_cobol_and_copybook_line_preservation():
    free_res = extract_symbols_and_chunks(TAXSUB_FREE_COB, "src/TAXSUB.cob", repo="core_ledger")
    free_by_full = {s.full_symbol: s for s in free_res.symbols}
    assert "TAXSUB" in free_by_full
    assert free_by_full["TAXSUB"].kind == "program_definition"
    assert free_by_full["TAXSUB.0100-COMPUTE-TAX"].kind == "paragraph"
    assert (free_by_full["TAXSUB.0100-COMPUTE-TAX"].start_line, free_by_full["TAXSUB.0100-COMPUTE-TAX"].end_line) == (8, 10)
    assert any(r.target_symbol == "RATESVC" and r.relationship_type == "CALLS" and r.line_number == 9 for r in free_res.relationships)

    cpy_res = extract_symbols_and_chunks(CUSTCOPY_CPY, "copybooks/CUSTCOPY.cpy", repo="core_ledger")
    cpy_by_name = {s.name: s for s in cpy_res.symbols}
    assert "CUSTCOPY" in cpy_by_name
    assert cpy_by_name["CUSTCOPY"].kind == "copybook"
    assert (cpy_by_name["CUSTOMER-MASTER"].start_line, cpy_by_name["CUSTOMER-MASTER"].end_line) == (2, 4)
    assert (cpy_by_name["CUSTOMER-ADDRESS"].start_line, cpy_by_name["CUSTOMER-ADDRESS"].end_line) == (6, 7)
    assert "FILLER" not in cpy_by_name


def test_cobol_end_to_end_indexing_architecture_and_trace_path(tmp_path):
    repo_dir = tmp_path / "mainframe_repo"
    (repo_dir / "src").mkdir(parents=True)
    (repo_dir / "copybooks").mkdir(parents=True)
    (repo_dir / "src" / "PAYROLL.CBL").write_text(PAYROLL_FIXED_CBL, encoding="utf-8")
    (repo_dir / "src" / "TAXSUB.cob").write_text(TAXSUB_FREE_COB, encoding="utf-8")
    (repo_dir / "copybooks" / "CUSTCOPY.CPY").write_text(CUSTCOPY_CPY, encoding="utf-8")

    db_file = str(tmp_path / "cobol_e2e.db")
    _init_ephemeral_db(db_file)
    get_conn = _connect_factory(db_file)

    repo_name = "mainframe_core"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, commit_sha, provider) VALUES (?, ?, ?, ?)",
            (repo_name, "https://github.com/acme/mainframe-core.git", "deadbeef1234", "github"),
        )
        conn.commit()

    with patch("app.services.database.get_db_connection", side_effect=get_conn), \
         patch("app.services.indexing.git_syncer.db_service.get_db_connection", side_effect=get_conn), \
         patch("app.services.indexing.processor._resolve_cached_or_compute_embeddings", side_effect=lambda chunks, texts: [{"dense": [0.1] * 8, "sparse_indices": None, "sparse_values": None} for _ in chunks]), \
         patch("app.services.architecture.get_db_connection", side_effect=get_conn), \
         patch("app.services.navigator.get_db_connection", side_effect=get_conn), \
         patch("app.services.search.get_db_connection", side_effect=get_conn):

        added, modified, deleted, unchanged = compute_git_repo_delta(str(repo_dir), repo_name)
        assert len(added) == 3
        assert not modified and not deleted and not unchanged

        b_files, b_sums, b_syms, b_rels, b_routes, b_calls = [], [], [], [], [], []
        for full_path in sorted(added):
            rel_path = os.path.relpath(full_path, str(repo_dir)).replace("\\", "/")
            db_fp = f"{repo_name}://{rel_path}"
            content = open(full_path, "r", encoding="utf-8").read()
            _, syms, sum_tup, rels, routes, calls = process_file_content(
                filepath=db_fp,
                rel_path=rel_path,
                content=content,
                repo=repo_name,
                doc_type="code",
                git_url="https://github.com/acme/mainframe-core.git",
                commit_sha="deadbeef1234",
                provider="github",
            )
            b_syms.extend(syms)
            b_sums.append(sum_tup)
            b_rels.extend(rels)
            b_routes.extend(routes)
            b_calls.extend(calls)
            b_files.append((db_fp, repo_name, "code", detect_language(full_path), "deadbeef1234", 0.0, compute_text_hash(content)))

        with get_conn() as conn:
            inserted = persist_sync_batch(conn, b_files, b_sums, b_syms, b_rels, b_routes, b_calls)
            assert inserted >= 9

        # Architecture synthesis & entry point detection
        eps = detect_entry_points(["src/PAYROLL.CBL", "src/TAXSUB.cob", "copybooks/CUSTCOPY.CPY"])
        assert "src/PAYROLL.CBL" in eps
        assert "src/TAXSUB.cob" in eps
        assert "copybooks/CUSTCOPY.CPY" not in eps

        arch = json.loads(synthesize_architecture(repo=repo_name))
        assert any(l["language"] == "COBOL" and l["files"] == 3 for l in arch["languages"])
        assert any(ep.endswith("PAYROLL.CBL") for ep in arch["entry_points"])

        # Navigator outline & impact
        outline = get_file_outline(repo_name, "src/PAYROLL.CBL")
        assert outline is not None
        sym_names = [s["full_symbol"] for s in outline["symbols"]]
        assert "PAYROLL" in sym_names
        assert "PAYROLL.2000-CALC-TAX" in sym_names

        tax_sym_row = next(s for s in outline["symbols"] if s["full_symbol"] == "PAYROLL.2000-CALC-TAX")
        impact = get_symbol_impact(repo_name, tax_sym_row["id"])
        assert any(c["source_symbol"] == "PAYROLL.1100-INIT" for c in impact["callers"])
        assert any(c["target_symbol"] == "TAXSUB" for c in impact["callees"])

        # 1. Intra-program PERFORM + Inter-program CALL via outbound ('outbound' alias)
        out_init = json.loads(trace_symbol_path("PAYROLL.1100-INIT", repo=repo_name, direction="outbound", depth=3))
        assert out_init["direction"] == "callees"
        lvl1 = {c["symbol"]: c for c in out_init["callees"]}
        assert "PAYROLL.2000-CALC-TAX" in lvl1
        assert "AUDITSB" in lvl1
        assert "CICSLOG" in lvl1
        # Hop 2: PAYROLL.2000-CALC-TAX -> TAXSUB -> Hop 3: RATESVC
        lvl2 = {c["symbol"]: c for c in lvl1["PAYROLL.2000-CALC-TAX"]["callees"]}
        assert "TAXSUB" in lvl2
        lvl3 = {c["symbol"]: c for c in lvl2["TAXSUB"]["callees"]}
        assert "RATESVC" in lvl3

        # 2. Inbound ('inbound' alias) from subprogram TAXSUB back to PAYROLL paragraphs
        in_taxsub = json.loads(trace_symbol_path("TAXSUB", repo=repo_name, direction="inbound", depth=2))
        assert in_taxsub["direction"] == "callers"
        callers_lvl1 = {c["symbol"]: c for c in in_taxsub["callers"]}
        assert "PAYROLL.2000-CALC-TAX" in callers_lvl1
        callers_lvl2 = {c["symbol"]: c for c in callers_lvl1["PAYROLL.2000-CALC-TAX"]["callers"]}
        assert "PAYROLL.1100-INIT" in callers_lvl2

        # 3. Copybook COPY tracing ('both' direction + case-insensitive symbol query)
        cpy_trace = json.loads(trace_symbol_path("custcopy", repo=repo_name, direction="both", depth=1))
        assert cpy_trace["target"]["name"] == "CUSTCOPY"
        assert any(c["symbol"] == "PAYROLL" and c["rel"] == "imports" for c in cpy_trace["callers"])

        # 4. Program-level outbound trace surfaces both COPY imports and paragraph CALLs
        prog_trace = json.loads(trace_symbol_path("payroll", repo=repo_name, direction="outbound", depth=1))
        prog_callees = {c["symbol"] for c in prog_trace["callees"]}
        assert "CUSTCOPY" in prog_callees
        assert "TAXSUB" in prog_callees


def test_local_storage_cobol_persists_language_and_relationships(tmp_path, monkeypatch):
    """Uploading COBOL programs via LocalStorageService persists language='cobol' and ast_relationships for trace_path & diagnose_issue."""
    import app.services.database as db_service
    import app.services.database.connection as db_conn
    from app.services.diagnostics import diagnose_issue
    from app.services.local_storage import LocalStorageService
    from app.services.vector_store import VectorStoreManager

    db_file = str(tmp_path / "local_cobol.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr(db_service, "CACHE_DB_PATH", db_file)
    monkeypatch.setattr(db_conn, "CACHE_DB_PATH", db_file)
    VectorStoreManager.reset_instance()
    db_service.get_db_engine(reset=True)
    db_service.init_db()
    db_service.set_vector_store_db_config(
        provider="chroma", mode="embedded",
        storage_path=str(tmp_path / "chroma_cobol"), collection="cobol_local_test",
    )

    storage = LocalStorageService(storage_root=str(tmp_path / "storage"))
    storage.save_file("cobol/CUSTCOPY.CPY", CUSTCOPY_CPY, repo="local_storage")
    storage.save_file("cobol/TAXSUB.cob", TAXSUB_FREE_COB, repo="local_storage")
    res = storage.save_file("cobol/PAYROLL.CBL", PAYROLL_FIXED_CBL, repo="local_storage")
    assert res["status"] == "success"
    assert res["symbols_indexed"] >= 6

    payroll_abs = storage.resolve_safe_path("cobol/PAYROLL.CBL")
    with db_service.get_db_connection() as conn:
        row = conn.execute("SELECT language FROM indexed_files WHERE filepath = ?", (payroll_abs,)).fetchone()
        assert row is not None and row["language"] == "cobol"
        rels = conn.execute("SELECT relationship_type, target_symbol FROM ast_relationships WHERE source_filepath = ?", (payroll_abs,)).fetchall()
        assert len(rels) >= 5

    trace = json.loads(trace_symbol_path("PAYROLL.1100-INIT", repo="local_storage", direction="outbound", depth=2))
    callees = {c["symbol"]: c for c in trace["callees"]}
    assert "PAYROLL.2000-CALC-TAX" in callees
    assert "TAXSUB" in {c["symbol"] for c in callees["PAYROLL.2000-CALC-TAX"]["callees"]}

    diag = diagnose_issue(
        issue_text="PAYROLL.CBL:25: attempt to reference unallocated memory (signal SIGSEGV) in PROGRAM-ID PAYROLL",
        repo="local_storage",
    )
    assert any("PAYROLL.CBL" in f.get("file", "") for f in diag.get("resolved_frames", []))
    VectorStoreManager.reset_instance()
    db_service.get_db_engine(reset=True)


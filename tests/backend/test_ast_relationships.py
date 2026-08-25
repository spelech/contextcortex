import pytest
import sqlite3
from app.services.chunking import extract_symbols_and_chunks
from app.services.database import get_db_connection, init_db

def test_python_relationship_extraction():
    code = """
import math
from os import path

class Base:
    def base_method(self):
        pass

class Derived(Base):
    def process(self):
        self.base_method()
        math.sqrt(16)
"""
    res = extract_symbols_and_chunks(code, "app/main.py", repo="testrepo")
    rels = [r.model_dump() for r in res.relationships]

    types = {r["relationship_type"] for r in rels}
    assert "IMPORTS" in types
    assert "INHERITS" in types
    assert "CALLS" in types

    # Check import targets
    import_targets = {r["target_symbol"] for r in rels if r["relationship_type"] == "IMPORTS"}
    assert "math" in import_targets or "path" in import_targets

    # Check inheritance
    inherits = [r for r in rels if r["relationship_type"] == "INHERITS"]
    assert any(r["source_symbol"] == "Derived" and r["target_symbol"] == "Base" for r in inherits)

    # Check calls
    calls = [r for r in rels if r["relationship_type"] == "CALLS"]
    assert any(r["target_symbol"] in ("base_method", "sqrt") for r in calls)


def test_ts_js_relationship_extraction():
    code = """
import { helper } from './utils';

class Parent {}
class Child extends Parent implements Runnable {
    run() {
        helper();
        this.otherMethod();
    }
}
"""
    res = extract_symbols_and_chunks(code, "src/index.ts", repo="tsrepo")
    rels = [r.model_dump() for r in res.relationships]

    types = {r["relationship_type"] for r in rels}
    assert "IMPORTS" in types
    assert "INHERITS" in types or "IMPLEMENTS" in types
    assert "CALLS" in types

    call_targets = {r["target_symbol"] for r in rels if r["relationship_type"] == "CALLS"}
    assert "helper" in call_targets or "otherMethod" in call_targets


def test_go_rust_csharp_relationship_extraction():
    # Go
    go_code = """
package main
import "fmt"

type Base struct{}
func (b *Base) Process() {
    fmt.Println("test")
    b.Other()
}
"""
    go_res = extract_symbols_and_chunks(go_code, "main.go", repo="gorepo")
    go_rels = [r.model_dump() for r in go_res.relationships]
    assert any(r["relationship_type"] == "CALLS" for r in go_rels)

    # Rust
    rust_code = """
use std::fmt;

trait Speaker {
    fn speak(&self);
}

struct Dog;
impl Speaker for Dog {
    fn speak(&self) {
        println!("woof");
    }
}
"""
    rust_res = extract_symbols_and_chunks(rust_code, "src/lib.rs", repo="rustrepo")
    rust_rels = [r.model_dump() for r in rust_res.relationships]
    assert any(r["relationship_type"] in ("IMPORTS", "IMPLEMENTS", "CALLS") for r in rust_rels)

    # C#
    cs_code = """
using System;

interface IWorker {}
class BaseWorker {}
class CustomWorker : BaseWorker, IWorker {
    public void Work() {
        Console.WriteLine("working");
        DoWork();
    }
}
"""
    cs_res = extract_symbols_and_chunks(cs_code, "Worker.cs", repo="csrepo")
    cs_rels = [r.model_dump() for r in cs_res.relationships]
    assert any(r["relationship_type"] in ("INHERITS", "IMPLEMENTS", "CALLS") for r in cs_rels)


def test_deletion_and_foreign_key_cascades(tmp_path):
    init_db()
    with get_db_connection() as conn:
        conn.execute("DELETE FROM ast_relationships WHERE repo = 'cascaderepo'")
        conn.execute("DELETE FROM ast_symbols WHERE repo = 'cascaderepo'")

        cursor = conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("cascaderepo", "file.py", "parent_fn", "parent_fn", "function", 1, 10, "def parent_fn()", "python")
        )
        sym_id = cursor.lastrowid

        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("cascaderepo", sym_id, "file.py", "parent_fn", "child_fn", "CALLS", 5)
        )
        conn.commit()

        rel_count_before = conn.execute("SELECT count(*) FROM ast_relationships WHERE repo = 'cascaderepo'").fetchone()[0]
        assert rel_count_before == 1

        # Delete symbol -> FK cascade should purge relationship
        conn.execute("DELETE FROM ast_symbols WHERE id = ?", (sym_id,))
        conn.commit()

        rel_count_after = conn.execute("SELECT count(*) FROM ast_relationships WHERE repo = 'cascaderepo'").fetchone()[0]
        assert rel_count_after == 0

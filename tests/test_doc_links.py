import os
import pytest
from app.models.schemas import CodeRelationship
from app.services.chunking.text_chunker import extract_markdown_doc_links
from app.services.indexing.processor import process_file_content
from app.services.topology.graph_builder import get_topology_graph
from app.services.database.connection import init_db, get_db_connection


def test_extract_markdown_doc_links():
    md = """# Title
See [Architecture Spec](../arch/system.md) for details.
Also refer to [[Database Design]] and [[API Routes|Routing Guide]].
External [Google](https://google.com) should be ignored.
"""
    rels = extract_markdown_doc_links(md, filepath="docs/intro.md", repo="test-repo")
    target_names = [r.target_symbol for r in rels]
    assert "arch/system.md" in target_names or "../arch/system.md" in target_names
    assert "Database Design" in target_names
    assert "API Routes" in target_names
    assert all(r.relationship_type == "DOC_LINKS_TO" for r in rels)
    assert all(r.repo == "test-repo" for r in rels)
    assert all(r.source_filepath == "docs/intro.md" for r in rels)


def test_extract_markdown_doc_links_edge_cases():
    md = """# Edge Cases
Image: ![Diagram](../images/arch.png)
Mailto: [Contact](mailto:dev@example.com)
Self anchor: [Jump to Top](#title)
Multiple: Link 1 [One](one.md) and [[Two|Label 2]] on same line.
Wikilink with section: [[Deep Dive#Section 1|Deep Dive Overview]]
Empty: []()
"""
    rels = extract_markdown_doc_links(md, filepath="README.md", repo="test-repo")
    targets = [r.target_symbol for r in rels]
    assert "one.md" in targets
    assert "Two" in targets
    assert "Deep Dive" in targets or "Deep Dive#Section 1" in targets
    assert "mailto:dev@example.com" not in targets
    assert "#title" not in targets
    assert "../images/arch.png" not in targets


def test_process_file_content_doc_links():
    content = """# Overview
Check [Setup Guide](setup.md) and [[Troubleshooting]].
"""
    points, symbols, summary, rels, routes, calls = process_file_content(
        filepath="/tmp/test-repo/docs/readme.md",
        rel_path="docs/readme.md",
        content=content,
        repo="test-repo",
        doc_type="doc"
    )
    assert len(rels) == 2
    target_symbols = [r["target_symbol"] for r in rels]
    assert "setup.md" in target_symbols
    assert "Troubleshooting" in target_symbols
    assert all(r["relationship_type"] == "DOC_LINKS_TO" for r in rels)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_doc_links.db")
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()
    return db_file


def test_graph_builder_doc_links_topology(temp_db):
    with get_db_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO git_repositories (name, url, commit_sha, provider) VALUES (?, ?, ?, ?)",
                     ("test-repo", "https://github.com/example/repo", "sha123", "github"))
        conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language, commit_sha) VALUES (?, ?, ?, ?, ?)",
                     ("docs/intro.md", "test-repo", "doc", "markdown", "sha123"))
        conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language, commit_sha) VALUES (?, ?, ?, ?, ?)",
                     ("arch/system.md", "test-repo", "doc", "markdown", "sha123"))
        conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language, commit_sha) VALUES (?, ?, ?, ?, ?)",
                     ("docs/Database Design.md", "test-repo", "doc", "markdown", "sha123"))

        conn.execute("""
            INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("test-repo", None, "docs/intro.md", "intro.md", "../arch/system.md", "DOC_LINKS_TO", 2))

        conn.execute("""
            INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("test-repo", None, "docs/intro.md", "intro.md", "Database Design", "DOC_LINKS_TO", 3))

    graph = get_topology_graph(repo="test-repo", view_type="files")
    assert graph is not None
    edges = graph.get("edges", [])
    doc_link_edges = [e for e in edges if e.get("type") == "DOC_LINKS_TO"]
    assert len(doc_link_edges) == 2

    edge_targets = [e["target"] for e in doc_link_edges]
    assert "file:test-repo:arch/system.md" in edge_targets
    assert "file:test-repo:docs/Database Design.md" in edge_targets

    # Also test full view type
    graph_full = get_topology_graph(repo="test-repo", view_type="full")
    assert graph_full is not None
    full_doc_edges = [e for e in graph_full.get("edges", []) if e.get("type") == "DOC_LINKS_TO"]
    assert len(full_doc_edges) == 2


def test_graph_builder_wikilink_hyphen_space_matching(temp_db):
    with get_db_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO git_repositories (name, url, commit_sha, provider) VALUES (?, ?, ?, ?)",
                     ("test-repo", "https://github.com/example/repo", "sha123", "github"))
        conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language, commit_sha) VALUES (?, ?, ?, ?, ?)",
                     ("docs/intro.md", "test-repo", "doc", "markdown", "sha123"))
        conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language, commit_sha) VALUES (?, ?, ?, ?, ?)",
                     ("docs/api-routes.md", "test-repo", "doc", "markdown", "sha123"))

        conn.execute("""
            INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("test-repo", None, "docs/intro.md", "intro.md", "API Routes", "DOC_LINKS_TO", 5))

    graph = get_topology_graph(repo="test-repo", view_type="files")
    assert graph is not None
    doc_link_edges = [e for e in graph.get("edges", []) if e.get("type") == "DOC_LINKS_TO"]
    assert len(doc_link_edges) == 1
    assert doc_link_edges[0]["target"] == "file:test-repo:docs/api-routes.md"


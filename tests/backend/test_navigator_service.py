import sqlite3
import pytest
from unittest.mock import patch

from app.services.navigator import get_navigator_tree, get_file_outline, get_symbol_impact


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "test_navigator.db")
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE git_repositories (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            url TEXT,
            branch TEXT,
            auth_token TEXT,
            provider TEXT DEFAULT 'github',
            auth_user TEXT,
            commit_sha TEXT,
            status TEXT DEFAULT 'synced',
            last_error TEXT,
            last_synced TEXT,
            enabled INTEGER DEFAULT 1,
            auto_sync INTEGER DEFAULT 1,
            webhook_secret TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE indexed_paths (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE,
            type TEXT,
            recursive INTEGER,
            enabled INTEGER,
            category TEXT,
            repo TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE indexed_files (
            filepath TEXT PRIMARY KEY,
            repo TEXT DEFAULT 'local',
            doc_type TEXT DEFAULT 'code',
            language TEXT DEFAULT 'python',
            commit_sha TEXT,
            mtime REAL,
            hash TEXT
        );
        CREATE TABLE ast_symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT NOT NULL,
            filepath TEXT NOT NULL,
            name TEXT NOT NULL,
            full_symbol TEXT,
            kind TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            signature TEXT,
            language TEXT
        );
        CREATE TABLE ast_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT NOT NULL,
            source_symbol_id INTEGER,
            source_filepath TEXT NOT NULL,
            source_symbol TEXT NOT NULL,
            target_symbol TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            line_number INTEGER NOT NULL
        );
        CREATE TABLE api_routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT NOT NULL,
            filepath TEXT NOT NULL,
            framework TEXT NOT NULL,
            http_method TEXT NOT NULL,
            path_pattern TEXT NOT NULL,
            handler_symbol TEXT,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Seed repositories
    conn.execute("INSERT INTO git_repositories (name, url) VALUES (?, ?)", ("test-repo", "https://github.com/org/test-repo.git"))
    conn.execute("INSERT INTO git_repositories (name, url) VALUES (?, ?)", ("other-repo", "https://github.com/org/other-repo.git"))

    # Seed indexed files
    conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES (?, ?, ?, ?)",
                 ("app/main.py", "test-repo", "code", "python"))
    conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES (?, ?, ?, ?)",
                 ("app/services/helper.py", "test-repo", "code", "python"))
    conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES (?, ?, ?, ?)",
                 ("src/index.ts", "other-repo", "code", "typescript"))

    # Seed AST symbols
    conn.execute("INSERT INTO ast_symbols (id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (1, "test-repo", "app/main.py", "root_handler", "app.main.root_handler", "function", 10, 20, "def root_handler():", "python"))
    conn.execute("INSERT INTO ast_symbols (id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (2, "test-repo", "app/services/helper.py", "compute_value", "app.services.helper.compute_value", "function", 5, 15, "def compute_value(x):", "python"))
    conn.execute("INSERT INTO ast_symbols (id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (3, "other-repo", "src/index.ts", "initApp", "src.index.initApp", "function", 1, 30, "function initApp(): void", "typescript"))

    # Seed AST relationships
    conn.execute("INSERT INTO ast_relationships (id, repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (1, "test-repo", 1, "app/main.py", "root_handler", "compute_value", "CALLS", 15))
    conn.execute("INSERT INTO ast_relationships (id, repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (2, "test-repo", 1, "app/main.py", "root_handler", "math", "IMPORTS", 2))
    conn.execute("INSERT INTO ast_relationships (id, repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (3, "test-repo", None, "app/other.py", "caller_fn", "root_handler", "CALLS", 50))

    # Seed API routes
    conn.execute("INSERT INTO api_routes (id, repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (1, "test-repo", "app/main.py", "FastAPI", "GET", "/api/v1/root", "root_handler", 10, 20))

    conn.commit()
    conn.close()

    def get_conn():
        c = sqlite3.connect(db_file)
        c.row_factory = sqlite3.Row
        return c

    with patch("app.services.navigator.get_db_connection", side_effect=get_conn):
        yield db_file


def test_navigator_tree_construction(test_db):
    res = get_navigator_tree("test-repo")
    assert res is not None
    assert res["repo"] == "test-repo"
    assert res["total_files"] == 2
    assert res["total_symbols"] == 2
    assert "tree" in res
    assert isinstance(res["tree"], list)

    # Check root level structure
    # Should have 'app' folder
    assert len(res["tree"]) == 1
    app_node = res["tree"][0]
    assert app_node["name"] == "app"
    assert app_node["is_dir"] is True
    assert app_node["path"] == "app"
    assert app_node["symbol_count"] == 2
    assert app_node["route_count"] == 1
    assert "children" in app_node
    assert len(app_node["children"]) == 2

    # Check children of 'app'
    main_file = next(c for c in app_node["children"] if c["name"] == "main.py")
    assert main_file["is_dir"] is False
    assert main_file["path"] == "app/main.py"
    assert main_file["language"] == "python"
    assert main_file["symbol_count"] == 1
    assert main_file["route_count"] == 1

    services_dir = next(c for c in app_node["children"] if c["name"] == "services")
    assert services_dir["is_dir"] is True
    assert services_dir["path"] == "app/services"
    assert services_dir["symbol_count"] == 1
    assert services_dir["route_count"] == 0
    assert len(services_dir["children"]) == 1
    helper_file = services_dir["children"][0]
    assert helper_file["name"] == "helper.py"
    assert helper_file["is_dir"] is False
    assert helper_file["symbol_count"] == 1


def test_navigator_tree_all_repos(test_db):
    res = get_navigator_tree("__all__")
    assert res is not None
    assert res["repo"] == "__all__"
    assert res["total_files"] == 3
    assert res["total_symbols"] == 3
    assert len(res["tree"]) == 2  # 'app' and 'src'


def test_navigator_tree_nonexistent_repo(test_db):
    res = get_navigator_tree("non-existent-repo")
    assert res is None


def test_navigator_tree_empty_existing_repo(test_db):
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO git_repositories (name, url) VALUES ('empty-repo', 'https://github.com/org/empty.git')")
    conn.commit()
    conn.close()

    res = get_navigator_tree("empty-repo")
    assert res is not None
    assert res["repo"] == "empty-repo"
    assert res["total_files"] == 0
    assert res["total_symbols"] == 0
    assert res["tree"] == []


def test_file_outline_retrieval(test_db):
    res = get_file_outline("test-repo", "app/main.py")
    assert res is not None
    assert res["repo"] == "test-repo"
    assert res["filepath"] == "app/main.py"
    assert "symbols" in res
    assert len(res["symbols"]) == 1

    sym = res["symbols"][0]
    assert sym["id"] == 1
    assert sym["name"] == "root_handler"
    assert sym["full_symbol"] == "app.main.root_handler"
    assert sym["kind"] == "function"
    assert sym["start_line"] == 10
    assert sym["end_line"] == 20
    assert sym["signature"] == "def root_handler():"
    assert sym["language"] == "python"
    assert sym["route"] is not None
    assert sym["route"]["http_method"] == "GET"
    assert sym["route"]["path_pattern"] == "/api/v1/root"


def test_file_outline_with_route_mapping_and_cleaning(test_db):
    # Test path with backslashes or leading slash
    res = get_file_outline("test-repo", "\\app\\main.py")
    assert res is not None
    assert res["filepath"] == "app/main.py"
    assert len(res["symbols"]) == 1

    # Test file outline for helper.py with no route
    res_helper = get_file_outline("test-repo", "app/services/helper.py")
    assert res_helper is not None
    assert len(res_helper["symbols"]) == 1
    assert res_helper["symbols"][0]["route"] is None

    # Test all repos
    res_all = get_file_outline("__all__", "app/main.py")
    assert res_all is not None
    assert len(res_all["symbols"]) == 1


def test_symbol_impact_retrieval(test_db):
    res = get_symbol_impact("test-repo", 1)
    assert res is not None
    assert "symbol" in res
    assert res["symbol"]["name"] == "root_handler"

    assert "route" in res
    assert res["route"] is not None
    assert res["route"]["path_pattern"] == "/api/v1/root"
    assert res["route"]["http_method"] == "GET"

    assert "callers" in res
    assert len(res["callers"]) >= 1
    caller_targets = [c["target_symbol"] for c in res["callers"]]
    assert "root_handler" in caller_targets or any(c["source_symbol_id"] == 1 for c in res["callers"])

    assert "callees" in res
    assert len(res["callees"]) == 1
    assert res["callees"][0]["target_symbol"] == "compute_value"
    assert res["callees"][0]["relationship_type"] == "CALLS"

    assert "imports" in res
    assert len(res["imports"]) == 1
    assert res["imports"][0]["target_symbol"] == "math"


def test_symbol_impact_not_found(test_db):
    res = get_symbol_impact("test-repo", 99999)
    assert res is None

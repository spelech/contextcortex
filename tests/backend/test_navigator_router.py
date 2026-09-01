import sqlite3
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes import router

app = FastAPI()
app.include_router(router)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "test_navigator_api.db")
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

    # Seed indexed files
    conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES (?, ?, ?, ?)",
                 ("app/main.py", "test-repo", "code", "python"))
    conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES (?, ?, ?, ?)",
                 ("app/services/helper.py", "test-repo", "code", "python"))

    # Seed AST symbols
    conn.execute("INSERT INTO ast_symbols (id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (1, "test-repo", "app/main.py", "root_handler", "app.main.root_handler", "function", 10, 20, "def root_handler():", "python"))
    conn.execute("INSERT INTO ast_symbols (id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (2, "test-repo", "app/services/helper.py", "compute_value", "app.services.helper.compute_value", "function", 5, 15, "def compute_value(x):", "python"))

    # Seed AST relationships
    conn.execute("INSERT INTO ast_relationships (id, repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (1, "test-repo", 1, "app/main.py", "root_handler", "compute_value", "CALLS", 15))
    conn.execute("INSERT INTO ast_relationships (id, repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (2, "test-repo", 1, "app/main.py", "root_handler", "math", "IMPORTS", 2))

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


def test_api_get_navigator_tree_all(client: TestClient, test_db):
    response = client.get("/admin/api/navigator/tree?repo=__all__")
    assert response.status_code == 200
    data = response.json()
    assert "tree" in data
    assert data["repo"] == "__all__"
    assert data["total_files"] == 2


def test_api_get_navigator_tree_specific_repo(client: TestClient, test_db):
    response = client.get("/admin/api/navigator/tree?repo=test-repo")
    assert response.status_code == 200
    data = response.json()
    assert data["repo"] == "test-repo"
    assert len(data["tree"]) == 1
    assert data["tree"][0]["name"] == "app"


def test_api_get_navigator_tree_not_found(client: TestClient, test_db):
    response = client.get("/admin/api/navigator/tree?repo=nonexistent-repo")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data


def test_api_get_file_outline_success(client: TestClient, test_db):
    response = client.get("/admin/api/navigator/file-outline?repo=test-repo&filepath=app/main.py")
    assert response.status_code == 200
    data = response.json()
    assert data["repo"] == "test-repo"
    assert data["filepath"] == "app/main.py"
    assert len(data["symbols"]) == 1
    assert data["symbols"][0]["name"] == "root_handler"
    assert data["symbols"][0]["route"]["path_pattern"] == "/api/v1/root"


def test_api_get_file_outline_empty(client: TestClient, test_db):
    response = client.get("/admin/api/navigator/file-outline?repo=test-repo&filepath=nonexistent.py")
    assert response.status_code == 200
    data = response.json()
    assert data["symbols"] == []


def test_api_get_symbol_impact_success(client: TestClient, test_db):
    response = client.get("/admin/api/navigator/symbol-impact?repo=test-repo&symbol_id=1")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"]["name"] == "root_handler"
    assert len(data["callees"]) == 1
    assert len(data["imports"]) == 1
    assert data["route"]["http_method"] == "GET"


def test_api_get_symbol_impact_not_found(client: TestClient, test_db):
    response = client.get("/admin/api/navigator/symbol-impact?repo=test-repo&symbol_id=999999")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data

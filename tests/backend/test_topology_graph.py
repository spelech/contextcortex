import time
import sqlite3
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes import router
from app.services.topology import get_topology_graph, get_node_details

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture
def topology_test_db(tmp_path):
    db_file = str(tmp_path / "test_topology.db")
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
        CREATE TABLE indexed_files (
            id INTEGER PRIMARY KEY,
            filepath TEXT,
            repo TEXT,
            doc_type TEXT,
            language TEXT,
            hash TEXT,
            size INTEGER,
            last_modified REAL,
            commit_sha TEXT,
            mtime REAL,
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
        CREATE TABLE ast_symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT,
            filepath TEXT,
            kind TEXT,
            name TEXT,
            full_symbol TEXT,
            signature TEXT,
            start_line INTEGER,
            end_line INTEGER,
            language TEXT
        );
        CREATE TABLE ast_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT,
            source_symbol_id INTEGER,
            source_filepath TEXT,
            source_symbol TEXT,
            target_symbol TEXT,
            relationship_type TEXT,
            line_number INTEGER
        );
        CREATE TABLE api_routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT,
            filepath TEXT,
            framework TEXT,
            http_method TEXT,
            path_pattern TEXT,
            handler_symbol TEXT,
            start_line INTEGER,
            end_line INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE api_client_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT,
            filepath TEXT,
            http_method TEXT,
            url_pattern TEXT,
            caller_symbol TEXT,
            line_number INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE file_summaries (
            filepath TEXT PRIMARY KEY,
            repo TEXT,
            title TEXT,
            folder TEXT,
            category TEXT,
            tags TEXT,
            headings TEXT,
            keywords TEXT,
            mtime REAL
        );
    """)

    # Seed test data
    conn.execute(
        "INSERT INTO git_repositories (name, url, commit_sha, provider) VALUES (?, ?, ?, ?)",
        ("repo-core", "https://github.com/org/repo-core.git", "c0ffee1", "github")
    )
    conn.execute(
        "INSERT INTO git_repositories (name, url, commit_sha, provider) VALUES (?, ?, ?, ?)",
        ("repo-web", "https://github.com/org/repo-web.git", "d0ffee2", "gitlab")
    )

    # Seed files
    conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language, commit_sha) VALUES (?, ?, ?, ?, ?)",
                 ("app/main.py", "repo-core", "code", "python", "c0ffee1"))
    conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language, commit_sha) VALUES (?, ?, ?, ?, ?)",
                 ("app/utils.py", "repo-core", "code", "python", "c0ffee1"))
    conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language, commit_sha) VALUES (?, ?, ?, ?, ?)",
                 ("src/client.ts", "repo-web", "code", "typescript", "d0ffee2"))

    # Seed symbols
    conn.execute("INSERT INTO ast_symbols (id, repo, filepath, kind, name, full_symbol, signature, start_line, end_line, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (1, "repo-core", "app/main.py", "function", "handle_request", "handle_request", "def handle_request(req):", 10, 25, "python"))
    conn.execute("INSERT INTO ast_symbols (id, repo, filepath, kind, name, full_symbol, signature, start_line, end_line, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (2, "repo-core", "app/utils.py", "function", "format_response", "format_response", "def format_response(data):", 5, 15, "python"))
    conn.execute("INSERT INTO ast_symbols (id, repo, filepath, kind, name, full_symbol, signature, start_line, end_line, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (3, "repo-core", "app/utils.py", "class", "ResponseFormatter", "ResponseFormatter", "class ResponseFormatter:", 20, 50, "python"))
    conn.execute("INSERT INTO ast_symbols (id, repo, filepath, kind, name, full_symbol, signature, start_line, end_line, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (4, "repo-web", "src/client.ts", "function", "fetchDashboard", "fetchDashboard", "async function fetchDashboard()", 1, 30, "typescript"))

    # Seed relationships
    conn.execute("INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 ("repo-core", 1, "app/main.py", "handle_request", "format_response", "CALLS", 18))
    conn.execute("INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 ("repo-core", 1, "app/main.py", "handle_request", "ResponseFormatter", "IMPORTS", 11))

    # Seed api_routes
    conn.execute("INSERT INTO api_routes (id, repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (1, "repo-core", "app/main.py", "FastAPI", "GET", "/api/v1/status", "handle_request", 10, 25))

    # Seed api_client_calls
    conn.execute("INSERT INTO api_client_calls (id, repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (1, "repo-web", "src/client.ts", "GET", "/api/v1/status", "fetchDashboard", 15))

    conn.commit()
    conn.close()

    def get_conn():
        c = sqlite3.connect(db_file)
        c.row_factory = sqlite3.Row
        return c

    with patch("app.services.topology.get_db_connection", side_effect=get_conn), \
         patch("app.api.routes.get_db_connection", side_effect=get_conn):
        yield db_file


def test_topology_graph_files_view(topology_test_db):
    """Test topology graph construction for files view."""
    data = get_topology_graph(repo="repo-core", view_type="files")
    assert data is not None
    assert "nodes" in data
    assert "edges" in data
    assert "stats" in data
    assert data["stats"]["node_count"] == 2
    assert any(n["name"] == "main.py" for n in data["nodes"])
    assert any(n["name"] == "utils.py" for n in data["nodes"])
    # Edge between main.py and utils.py
    assert len(data["edges"]) >= 1


def test_topology_graph_symbols_view(topology_test_db):
    """Test topology graph construction for symbols view."""
    data = get_topology_graph(repo="repo-core", view_type="symbols")
    assert data is not None
    assert data["stats"]["node_count"] == 3
    node_types = {n["type"] for n in data["nodes"]}
    assert "function" in node_types
    assert "class" in node_types
    assert any(e["type"] in ("CALLS", "IMPORTS") for e in data["edges"])


def test_topology_graph_routes_view(topology_test_db):
    """Test topology graph construction for routes view."""
    data = get_topology_graph(repo="repo-core", view_type="routes")
    assert data is not None
    route_nodes = [n for n in data["nodes"] if n["type"] == "route"]
    assert len(route_nodes) == 1
    assert route_nodes[0]["name"] == "GET /api/v1/status"
    # Route handles symbol handle_request
    assert any(e["type"] == "HANDLES" for e in data["edges"])


def test_topology_graph_full_view(topology_test_db):
    """Test topology graph construction for full view."""
    data = get_topology_graph(repo="repo-core", view_type="full")
    assert data is not None
    assert data["stats"]["node_count"] >= 5
    types = {n["type"] for n in data["nodes"]}
    assert "file" in types
    assert "function" in types
    assert "route" in types
    edge_types = {e["type"] for e in data["edges"]}
    assert "DEFINES" in edge_types
    assert "CALLS" in edge_types or "IMPORTS" in edge_types or "HANDLES" in edge_types


def test_topology_cross_repo_all(topology_test_db):
    """Test cross-repo topology with repo='__all__' including cross-repo client routes."""
    data = get_topology_graph(repo="__all__", view_type="full")
    assert data is not None
    repos = {n["repo"] for n in data["nodes"]}
    assert "repo-core" in repos
    assert "repo-web" in repos
    # ROUTES_TO edge from repo-web client to repo-core route
    assert any(e["type"] == "ROUTES_TO" for e in data["edges"])


def test_topology_root_node_bfs(topology_test_db):
    """Test BFS traversal focused on a root node with depth limit."""
    data = get_topology_graph(repo="repo-core", view_type="full", root_node="handle_request", depth=1)
    assert data is not None
    node_names = {n["name"] for n in data["nodes"]}
    assert "handle_request" in node_names


def test_topology_invalid_repo_404(topology_test_db):
    """Test 404 response when querying a non-existent repository."""
    response = client.get("/admin/api/graph/topology?repo=nonexistent-repo")
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["stats"]["node_count"] == 0


def test_topology_api_endpoint(topology_test_db):
    """Test REST API GET /admin/api/graph/topology endpoint."""
    response = client.get("/admin/api/graph/topology?repo=repo-core&view_type=symbols")
    assert response.status_code == 200
    data = response.json()
    assert data["stats"]["node_count"] == 3
    assert len(data["nodes"]) == 3


def test_node_details_symbol(topology_test_db):
    """Test GET /admin/api/graph/node-details for symbol node."""
    response = client.get("/admin/api/graph/node-details?id=symbol:1")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "handle_request"
    assert data["type"] == "function"
    assert data["repo"] == "repo-core"
    assert data["start_line"] == 10
    assert "outgoing" in data
    assert len(data["outgoing"]) >= 1


def test_node_details_file(topology_test_db):
    """Test GET /admin/api/graph/node-details for file node."""
    response = client.get("/admin/api/graph/node-details?id=file:repo-core:app/main.py")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "main.py"
    assert data["type"] == "file"
    assert data["repo"] == "repo-core"


def test_node_details_route(topology_test_db):
    """Test GET /admin/api/graph/node-details for route node."""
    response = client.get("/admin/api/graph/node-details?id=route:1")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "GET /api/v1/status"
    assert data["type"] == "route"
    assert len(data["outgoing"]) >= 1


def test_node_details_not_found(topology_test_db):
    """Test 404 response for invalid node id."""
    response = client.get("/admin/api/graph/node-details?id=symbol:999999")
    assert response.status_code == 404


def test_topology_performance_benchmark(topology_test_db):
    """Test performance benchmark ensuring graph construction of 500+ items executes quickly."""
    with patch("app.services.topology.get_db_connection") as mock_conn:
        conn = sqlite3.connect(topology_test_db)
        # Bulk insert 500 symbols & relationships
        sym_records = [
            ("repo-core", f"app/module_{i}.py", "function", f"fn_{i}", f"fn_{i}", f"def fn_{i}():", 1, 10, "python")
            for i in range(10, 510)
        ]
        conn.executemany(
            "INSERT INTO ast_symbols (repo, filepath, kind, name, full_symbol, signature, start_line, end_line, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            sym_records
        )
        rel_records = [
            ("repo-core", 10 + i, f"app/module_{i}.py", f"fn_{i}", f"fn_{i+1}", "CALLS", 5)
            for i in range(490)
        ]
        conn.executemany(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rel_records
        )
        conn.commit()
        conn.close()

    start_time = time.time()
    data = get_topology_graph(repo="repo-core", view_type="symbols", limit=1000)
    duration = time.time() - start_time

    assert data is not None
    assert data["stats"]["node_count"] >= 500
    assert duration < 0.5, f"Topology generation took {duration:.3f}s, expected < 0.5s"

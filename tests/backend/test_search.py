import pytest
from unittest.mock import patch, MagicMock
from app.services.search import execute_hybrid_search
from app.services.vector_store.base import VectorSearchResult

def test_execute_hybrid_search_empty_query():
    assert execute_hybrid_search("") == []
    assert execute_hybrid_search("   ") == []


def test_execute_hybrid_search_end_to_end_real(tmp_path, monkeypatch):
    """
    Validates REAL hybrid retrieval and AST symbol enrichment without mocking
    get_vector_store, get_db_connection, or execute_hybrid_search.
    Asserts both Markdown and PDF docs are matched under doc_type='doc', and
    code results are enriched with signature/kind/ast_symbol_id from SQLite.
    """
    from app.services.vector_store import get_vector_store, VectorStoreManager
    from app.services.vector_store.base import VectorDocument
    from app.services.database import init_db, get_db_connection, set_vector_store_db_config

    db_file = str(tmp_path / "real_search.db")
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()

    qdrant_dir = str(tmp_path / "real_qdrant")
    set_vector_store_db_config(
        provider="qdrant",
        mode="embedded",
        storage_path=qdrant_dir,
        url="",
        collection="test_real_search",
    )
    VectorStoreManager.reset_instance()

    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("backend", "backend://app/auth.py", "authenticate_jwt_user", "AuthService.authenticate_jwt_user", "method_declaration", 1, 5, "def authenticate_jwt_user(token: str) -> bool:", "python"),
        )
        conn.execute(
            """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("backend", "backend://app/utils.py", "helper_interval", "Utils.helper_interval", "function_declaration", 48, 68, "def helper_interval(val: int) -> int:", "python"),
        )
        conn.commit()

    store = get_vector_store(force_reload=True)
    doc1 = VectorDocument(
        id="code-1",
        text="def authenticate_jwt_user(token: str): return True",
        repo="backend",
        doc_type="code",
        language="python",
        path="app/auth.py",
        rel_path="app/auth.py",
        title="auth.py",
        symbol="authenticate_jwt_user",
        start_line=1,
        end_line=2,
    )
    doc_interval = VectorDocument(
        id="code-2",
        text="def helper_interval(val: int): return val * 2",
        repo="backend",
        doc_type="code",
        language="python",
        path="app/utils.py",
        rel_path="app/utils.py",
        title="utils.py",
        symbol=None,
        start_line=50,
        end_line=60,
    )
    doc2 = VectorDocument(
        id="doc-1",
        text="ContextCortex Architecture Decision Record for Hybrid Search Retrieval",
        repo="docs",
        doc_type="doc",
        path="docs/adr/001-search.md",
        rel_path="docs/adr/001-search.md",
        title="001-search.md",
        heading="Architecture Decision",
        start_line=1,
        end_line=5,
    )
    doc3 = VectorDocument(
        id="pdf-1",
        text="Operator Manual and Deployment Runbook for ContextCortex Gateway",
        repo="ops",
        doc_type="pdf",
        path="docs/manual.pdf",
        rel_path="docs/manual.pdf",
        title="manual.pdf",
        heading="Page 1",
        start_line=1,
        end_line=1,
    )
    assert store.upsert_documents([doc1, doc_interval, doc2, doc3]) is True

    # 1. Search code -> enriched via exact symbol match in real SQLite
    code_results = execute_hybrid_search("authenticate user", doc_type="code")
    assert len(code_results) >= 1
    auth_hit = next(h for h in code_results if h.payload.get("rel_path") == "app/auth.py")
    assert auth_hit.payload.get("signature") == "def authenticate_jwt_user(token: str) -> bool:"
    assert auth_hit.payload.get("kind") == "method_declaration"
    assert isinstance(auth_hit.payload.get("ast_symbol_id"), int)

    # 2. Search code -> enriched via line-interval fallback when chunk symbol is None
    interval_results = execute_hybrid_search("helper_interval", doc_type="code")
    assert len(interval_results) >= 1
    util_hit = next(h for h in interval_results if h.payload.get("rel_path") == "app/utils.py")
    assert util_hit.payload.get("full_symbol") == "Utils.helper_interval"
    assert util_hit.payload.get("signature") == "def helper_interval(val: int) -> int:"

    # 3. Search doc -> should return Markdown doc
    doc_results = execute_hybrid_search("Architecture Decision", doc_type="doc")
    assert len(doc_results) >= 1
    assert any(h.payload.get("rel_path") == "docs/adr/001-search.md" for h in doc_results)

    # 4. Search doc -> should also find PDF doc!
    pdf_results = execute_hybrid_search("Deployment Runbook Operator Manual", doc_type="doc")
    assert len(pdf_results) >= 1
    assert any(h.payload.get("rel_path") == "docs/manual.pdf" for h in pdf_results)

    # 5. Exercise /admin/api/search/test against the real embedded Qdrant store
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routers.repositories import router as repo_router

    test_app = FastAPI()
    test_app.include_router(repo_router)
    client = TestClient(test_app)

    resp = client.post(
        "/admin/api/search/test",
        json={
            "query": "authenticate user",
            "type": "code",
            "repo": "backend",
            "dense_weight": 0.65,
            "search_mode": "hybrid",
            "limit": 10,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "authenticate user"
    assert data["dense_weight"] == 0.65
    assert data["search_mode"] == "hybrid"
    assert len(data["results"]) >= 1
    assert any(r["payload"].get("symbol") == "authenticate_jwt_user" for r in data["results"])




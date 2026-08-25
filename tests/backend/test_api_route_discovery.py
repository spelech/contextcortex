import pytest
import sqlite3
import asyncio
from app.services.chunker import (
    extract_api_routes_and_calls,
    normalize_path_pattern,
    match_route_and_call,
    extract_symbols_and_chunks
)
from app.mcp.tools import handle_find_routes, handle_find_api_callers
from app.services.db import get_db_connection, init_db

def test_path_normalization_and_matching():
    # Test path normalization
    assert normalize_path_pattern("/api/users/:id") == "/api/users/{id}"
    assert normalize_path_pattern("/api/users/${userId}") == "/api/users/{userId}"
    assert normalize_path_pattern("api/users/<int:id>") == "/api/users/{id}"
    assert normalize_path_pattern("/api/users/[id]") == "/api/users/{id}"

    # Test route and call matching
    assert match_route_and_call("/api/users/{id}", "/api/users/42")
    assert match_route_and_call("/api/users/:id", "/api/users/${userId}")
    assert match_route_and_call("/api/v1/items/{item_id}", "/api/v1/items/100?q=test")
    assert not match_route_and_call("/api/users/{id}", "/api/posts/42")

def test_fastapi_route_parsing():
    code = """
from fastapi import FastAPI, APIRouter

app = FastAPI()
router = APIRouter(prefix="/items")

@router.get("/{item_id}")
async def read_item(item_id: int, q: str = None):
    return {"item_id": item_id, "q": q}

@app.post("/items/create")
def create_item(data: dict):
    return data
"""
    res = extract_symbols_and_chunks(code, "main.py", repo="backend_py")
    routes = res.api_routes
    assert len(routes) == 2
    r1 = next(r for r in routes if r.http_method == "GET")
    assert r1.path_pattern == "/{item_id}" or r1.path_pattern == "/items/{item_id}"
    assert r1.framework == "fastapi"

    r2 = next(r for r in routes if r.http_method == "POST")
    assert r2.path_pattern == "/items/create"
    assert r2.framework == "fastapi"

def test_express_route_parsing_with_middleware():
    code = """
const express = require('express');
const router = express.Router();

function validate(req, res, next) { next(); }
function handler(req, res) { res.send('ok'); }

router.post('/login', validate, handler);
app.get('/api/v1/users/:id', (req, res) => {
    res.json({ id: req.params.id });
});
"""
    res = extract_symbols_and_chunks(code, "server.js", repo="backend_js")
    routes = res.api_routes
    assert len(routes) == 2
    r_post = next(r for r in routes if r.http_method == "POST")
    assert r_post.path_pattern == "/login"
    assert r_post.framework == "express"

    r_get = next(r for r in routes if r.http_method == "GET")
    assert r_get.path_pattern == "/api/v1/users/{id}"
    assert r_get.framework == "express"

def test_csharp_controller_routes():
    code = """
using Microsoft.AspNetCore.Mvc;

namespace MyApi.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class UserController : ControllerBase
    {
        [HttpPost("save")]
        public IActionResult SaveUser([FromBody] User user)
        {
            return Ok();
        }

        [HttpGet("{id}")]
        public IActionResult GetUser(int id)
        {
            return Ok();
        }
    }
}
"""
    res = extract_symbols_and_chunks(code, "UserController.cs", repo="backend_cs")
    routes = res.api_routes
    assert len(routes) == 2
    r_post = next(r for r in routes if r.http_method == "POST")
    assert r_post.path_pattern == "/api/user/save"
    assert r_post.framework == "aspnet"

    r_get = next(r for r in routes if r.http_method == "GET")
    assert r_get.path_pattern == "/api/user/{id}"
    assert r_get.framework == "aspnet"

def test_client_call_detection():
    code = """
async function fetchData(userId) {
    const res = await fetch(`/api/v1/users/${userId}`, { method: 'GET' });
    const data = await axios.post('/api/v1/users', { name: 'Alice' });
    return data;
}

def call_service():
    resp = requests.get("https://api.internal/v1/health")
    resp2 = httpx.post("http://api.internal/v1/checkout")
"""
    res_js = extract_symbols_and_chunks(code, "client.js", repo="frontend")
    calls_js = res_js.api_client_calls
    assert len(calls_js) >= 2

    c_fetch = next(c for c in calls_js if "users" in c.url_pattern and c.http_method == "GET")
    assert c_fetch.url_pattern == "/api/v1/users/{userId}"

    c_axios = next(c for c in calls_js if c.http_method == "POST")
    assert c_axios.url_pattern == "/api/v1/users"

    res_py = extract_symbols_and_chunks(code, "client.py", repo="py_client")
    calls_py = res_py.api_client_calls
    assert len(calls_py) >= 2
    c_req = next(c for c in calls_py if "health" in c.url_pattern)
    assert c_req.http_method == "GET"

@pytest.mark.asyncio
async def test_multi_repo_contract_linking_and_mcp_tools(tmp_path, monkeypatch):
    # Setup isolated SQLite DB
    db_file = str(tmp_path / "test_api_discovery.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    init_db()

    backend_code = """
from fastapi import FastAPI

app = FastAPI()

@app.get("/api/v1/users/{user_id}")
def get_user(user_id: int):
    return {"id": user_id}

@app.post("/api/v1/orders")
def create_order():
    return {"status": "created"}
"""

    frontend_code = """
async function getUserProfile(userId) {
    const response = await fetch(`/api/v1/users/${userId}`);
    return response.json();
}

async function placeOrder(cart) {
    return axios.post('/api/v1/orders', cart);
}
"""

    res_backend = extract_symbols_and_chunks(backend_code, "app/main.py", repo="backend_service")
    res_frontend = extract_symbols_and_chunks(frontend_code, "src/api.js", repo="frontend_app")

    with get_db_connection() as conn:
        for r in res_backend.api_routes:
            conn.execute(
                "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (r.repo, r.filepath, r.framework, r.http_method, r.path_pattern, r.handler_symbol, r.start_line, r.end_line)
            )
        for c in res_frontend.api_client_calls:
            conn.execute(
                "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES (?, ?, ?, ?, ?, ?)",
                (c.repo, c.filepath, c.http_method, c.url_pattern, c.caller_symbol, c.line_number)
            )
        conn.commit()

    # Test find_routes tool
    routes_output = await handle_find_routes(query="users")
    assert "/api/v1/users/{user_id}" in routes_output
    assert "backend_service" in routes_output

    routes_post = await handle_find_routes(method="POST")
    assert "/api/v1/orders" in routes_post

    # Test find_api_callers tool
    callers_output = await handle_find_api_callers(path="/api/v1/users/{user_id}")
    assert "frontend_app" in callers_output
    assert "/api/v1/users/{userId}" in callers_output
    assert "getUserProfile" in callers_output

    callers_orders = await handle_find_api_callers(path="/api/v1/orders", method="POST")
    assert "placeOrder" in callers_orders

    # Test unindexed path or empty queries
    empty_callers = await handle_find_api_callers(path="/api/v1/nonexistent")
    assert "No client call sites found" in empty_callers

    err_callers = await handle_find_api_callers(path="")
    assert "Error: endpoint path cannot be empty" in err_callers

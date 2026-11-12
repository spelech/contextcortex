import json
import sqlite3
from typing import Dict, List, Tuple
from unittest.mock import patch

from app.services.chunking import (
    detect_language,
    extract_api_routes_and_calls,
    extract_symbols_and_chunks,
    is_code_file,
)
from app.services.indexing.git_delta_scanner import persist_sync_batch
from app.services.indexing.processor import compute_text_hash, process_file_content
from app.services.navigator import get_symbol_impact
from app.services.search import trace_symbol_path


def _setup_sqlite_repo(db_path: str, repo_name: str, files: List[Tuple[str, str]]) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE git_repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, url TEXT, commit_sha TEXT, provider TEXT, enabled INTEGER DEFAULT 1
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
        """
    )
    conn.execute(
        "INSERT INTO git_repositories (name, url, commit_sha, provider) VALUES (?, ?, ?, ?)",
        (repo_name, f"https://github.com/acme/{repo_name}.git", "cafebabe", "github"),
    )

    b_files, b_sums, b_syms, b_rels, b_routes, b_calls = [], [], [], [], [], []
    fake_embed = lambda chunks, texts: [{"dense": [0.2] * 8, "sparse_indices": None, "sparse_values": None} for _ in chunks]
    with patch("app.services.indexing.processor._resolve_cached_or_compute_embeddings", side_effect=fake_embed):
        for rel_path, content in files:
            db_fp = f"{repo_name}://{rel_path}"
            _, syms, sum_tup, rels, routes, calls = process_file_content(
                filepath=db_fp,
                rel_path=rel_path,
                content=content,
                repo=repo_name,
                doc_type="code",
                git_url=f"https://github.com/acme/{repo_name}.git",
                commit_sha="cafebabe",
                provider="github",
            )
            b_syms.extend(syms)
            b_sums.append(sum_tup)
            b_rels.extend(rels)
            b_routes.extend(routes)
            b_calls.extend(calls)
            b_files.append((db_fp, repo_name, "code", detect_language(rel_path), "cafebabe", 0.0, compute_text_hash(content)))

    persist_sync_batch(conn, b_files, b_sums, b_syms, b_routes and b_rels or b_rels, b_routes, b_calls)
    conn.close()


def _conn_factory(db_path: str):
    def _open():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    return _open


def test_ts_js_mjs_cts_jsx_extensions_imports_generics_and_jsx_component_linking(tmp_path):
    assert detect_language("scripts/build.mjs") == "javascript"
    assert detect_language("scripts/legacy.cjs") == "javascript"
    assert detect_language("src/types.mts") == "typescript"
    assert detect_language("src/types.cts") == "typescript"
    assert detect_language("src/View.jsx") == "javascript"
    assert detect_language("src/View.tsx") == "tsx"
    assert all(is_code_file(p) for p in ("a.mjs", "b.cjs", "c.mts", "d.cts", "e.jsx", "f.tsx"))

    card_tsx = """\
import React from 'react';
import { formatKeyMask as maskKey } from './keyFormat.mjs';

export class KeyPresenter extends BasePresenter<KeyConfig> implements IKeyView<KeyConfig>, ns.Auditable {
  renderLabel(raw: string): string {
    return maskKey(raw);
  }
}

export function AppKeysCard({ title }: { title: string }) {
  const masked = maskKey(title);
  return <section className="card">{masked}</section>;
}
"""
    page_jsx = """\
import { AppKeysCard } from './AppKeysCard';
import Layout from './Layout';

export const DashboardPage = () => {
  return (
    <div className="page">
      <Layout.Header title="Admin" />
      <AppKeysCard title="Primary" />
      <button type="button">Refresh</button>
    </div>
  );
};
"""
    mask_mjs = """\
export function formatKeyMask(raw) {
  return raw ? raw.slice(0, 4) : '';
}
"""
    res_card = extract_symbols_and_chunks(card_tsx, "src/AppKeysCard.tsx", repo="web_ui")
    card_rels = {(r.source_symbol, r.target_symbol, r.relationship_type) for r in res_card.relationships}
    assert ("KeyPresenter", "BasePresenter", "INHERITS") in card_rels
    assert ("KeyPresenter", "IKeyView", "IMPLEMENTS") in card_rels
    assert ("KeyPresenter", "Auditable", "IMPLEMENTS") in card_rels
    # Unpacked named + aliased ESM import specifiers
    import_targets = {r.target_symbol for r in res_card.relationships if r.relationship_type == "IMPORTS"}
    assert "./keyFormat.mjs" in import_targets
    assert "formatKeyMask" in import_targets
    assert "maskKey" in import_targets

    res_page = extract_symbols_and_chunks(page_jsx, "src/DashboardPage.jsx", repo="web_ui")
    jsx_calls = {r.target_symbol for r in res_page.relationships if r.relationship_type == "CALLS" and r.source_symbol == "DashboardPage"}
    assert "AppKeysCard" in jsx_calls
    assert "Header" in jsx_calls
    assert "div" not in jsx_calls
    assert "button" not in jsx_calls

    db_path = str(tmp_path / "web_ui.db")
    _setup_sqlite_repo(db_path, "web_ui", [
        ("src/AppKeysCard.tsx", card_tsx),
        ("src/DashboardPage.jsx", page_jsx),
        ("src/keyFormat.mjs", mask_mjs),
    ])
    get_conn = _conn_factory(db_path)

    with patch("app.services.search.get_db_connection", side_effect=get_conn), \
         patch("app.services.navigator.get_db_connection", side_effect=get_conn):
        out_trace = json.loads(trace_symbol_path("DashboardPage", repo="web_ui", direction="outbound", depth=2))
        lvl1 = {c["symbol"]: c for c in out_trace["callees"]}
        assert "AppKeysCard" in lvl1
        assert "Header" in lvl1

        in_trace = json.loads(trace_symbol_path("AppKeysCard", repo="web_ui", direction="inbound", depth=1))
        assert any(c["symbol"] == "DashboardPage" for c in in_trace["callers"])

        with get_conn() as c:
            card_id = c.execute("SELECT id FROM ast_symbols WHERE name = 'AppKeysCard'").fetchone()["id"]
        impact = get_symbol_impact("web_ui", card_id)
        assert any(caller["source_symbol"] == "DashboardPage" for caller in impact["callers"])


def test_csharp_primary_ctors_records_mapgroup_routes_and_di_call_tracing(tmp_path):
    contracts_cs = """\
namespace Commerce.Contracts;

public record CreateOrderRequest(string Sku, int Quantity);
public readonly record struct Money(decimal Amount, string Currency);

public interface IOrderRepository
{
    Task SaveAsync(CreateOrderRequest order);
}

public interface IUserRepository
{
    Task SaveAsync(string username);
}
"""
    repos_cs = """\
using Commerce.Contracts;

namespace Commerce.Infrastructure;

public class SqlOrderRepository : BaseRepo<CreateOrderRequest>, Commerce.Contracts.IOrderRepository
{
    public async Task SaveAsync(CreateOrderRequest order)
    {
        await PersistRowAsync(order);
    }

    private Task PersistRowAsync(CreateOrderRequest order) => Task.CompletedTask;
}

public class InMemoryUserRepository : IUserRepository
{
    public Task SaveAsync(string username) => Task.CompletedTask;
}
"""
    service_cs = """\
using Commerce.Contracts;

namespace Commerce.Application;

public class OrderService(IOrderRepository repo)
{
    public async Task SubmitOrderAsync(CreateOrderRequest req)
    {
        await repo.SaveAsync(req);
    }
}
"""
    endpoints_cs = """\
using Commerce.Application;
using Commerce.Contracts;

var v1 = app.MapGroup("/api/v1");
var ordersGroup = v1.MapGroup("/orders");
ordersGroup.MapGet("/{id:guid}", GetOrderById);
ordersGroup.MapPost("", SubmitOrderEndpoint);
app.MapGroup("/api/v2").MapDelete("/orders/{orderId:int}", DeleteOrderEndpoint);

[Route("api/[controller]")]
public class OrdersController
{
    [HttpPut("{id:guid}")]
    public async Task UpdateOrder(OrderService svc, CreateOrderRequest req)
    {
        await svc.SubmitOrderAsync(req);
    }
}
"""
    c_res = extract_symbols_and_chunks(contracts_cs, "Contracts/OrderContracts.cs", repo="commerce_cs")
    c_kinds: Dict[str, str] = {s.name: s.kind for s in c_res.symbols}
    assert c_kinds["CreateOrderRequest"] == "record_declaration"
    assert c_kinds["Money"] == "record_struct_declaration"
    assert c_kinds["IOrderRepository"] == "interface_declaration"

    r_res = extract_symbols_and_chunks(repos_cs, "Infrastructure/Repositories.cs", repo="commerce_cs")
    r_rels = {(r.source_symbol, r.target_symbol, r.relationship_type) for r in r_res.relationships}
    assert ("SqlOrderRepository", "BaseRepo", "INHERITS") in r_rels
    assert ("SqlOrderRepository", "IOrderRepository", "IMPLEMENTS") in r_rels

    s_res = extract_symbols_and_chunks(service_cs, "Application/OrderService.cs", repo="commerce_cs")
    ctor_syms = [s for s in s_res.symbols if s.kind == "constructor_declaration"]
    assert len(ctor_syms) == 1
    assert ctor_syms[0].full_symbol == "OrderService.OrderService"
    assert "IOrderRepository repo" in ctor_syms[0].signature

    e_res = extract_symbols_and_chunks(endpoints_cs, "Api/Program.cs", repo="commerce_cs")
    routes, _ = extract_api_routes_and_calls(endpoints_cs, "Api/Program.cs", repo="commerce_cs", symbols=e_res.symbols)
    route_set = {(rt.http_method, rt.path_pattern) for rt in routes}
    assert ("GET", "/api/v1/orders/{id}") in route_set
    assert ("POST", "/api/v1/orders") in route_set
    assert ("DELETE", "/api/v2/orders/{orderId}") in route_set
    assert ("PUT", "/api/orders/{id}") in route_set

    db_path = str(tmp_path / "commerce_cs.db")
    _setup_sqlite_repo(db_path, "commerce_cs", [
        ("Contracts/OrderContracts.cs", contracts_cs),
        ("Infrastructure/Repositories.cs", repos_cs),
        ("Application/OrderService.cs", service_cs),
        ("Api/Program.cs", endpoints_cs),
    ])
    get_conn = _conn_factory(db_path)

    with patch("app.services.search.get_db_connection", side_effect=get_conn):
        # Outbound DI resolution: OrdersController.UpdateOrder -> OrderService.SubmitOrderAsync -> SqlOrderRepository.SaveAsync -> PersistRowAsync
        out_cs = json.loads(trace_symbol_path("OrdersController.UpdateOrder", repo="commerce_cs", direction="outbound", depth=3))
        c1 = {c["symbol"]: c for c in out_cs["callees"]}
        assert "OrderService.SubmitOrderAsync" in c1
        c2 = {c["symbol"]: c for c in c1["OrderService.SubmitOrderAsync"]["callees"]}
        assert "SqlOrderRepository.SaveAsync" in c2
        assert "InMemoryUserRepository.SaveAsync" not in c2
        c3 = {c["symbol"]: c for c in c2["SqlOrderRepository.SaveAsync"]["callees"]}
        assert "SqlOrderRepository.PersistRowAsync" in c3

        # Inbound DI resolution from concrete implementation back through interface call site
        in_cs = json.loads(trace_symbol_path("SqlOrderRepository.SaveAsync", repo="commerce_cs", direction="inbound", depth=2))
        in1 = {c["symbol"]: c for c in in_cs["callers"]}
        assert "OrderService.SubmitOrderAsync" in in1
        in2 = {c["symbol"]: c for c in in1["OrderService.SubmitOrderAsync"]["callers"]}
        assert "OrdersController.UpdateOrder" in in2


def test_python_apirouter_prefixes_generics_aliased_imports_and_cross_file_tracing(tmp_path):
    audit_py = """\
from abc import ABC
from typing import Generic, TypeVar
import core.base as pkg

T = TypeVar("T")

class AuditRepository(ABC, Generic[T], pkg.BaseStore[T]):
    def write_event(self, event_name: str) -> bool:
        return True
"""
    service_py = """\
from app.audit import AuditRepository as AuditRepo

class BillingService:
    def __init__(self, repo: AuditRepo) -> None:
        self.repo = repo

    async def charge_account(self, account_id: str) -> bool:
        return self.repo.write_event(account_id)
"""
    router_py = """\
from fastapi import APIRouter
from app.service import BillingService

billing_router = APIRouter(
    prefix="/api/v1/billing",
    tags=["billing"],
)

@billing_router.post("")
async def create_charge(svc: BillingService, account_id: str):
    return await svc.charge_account(account_id)

@billing_router.get("/{invoice_id:int}")
def get_invoice(invoice_id: int):
    return {"id": invoice_id}
"""
    a_res = extract_symbols_and_chunks(audit_py, "app/audit.py", repo="py_billing")
    a_inherits = {r.target_symbol for r in a_res.relationships if r.relationship_type == "INHERITS"}
    a_implements = {r.target_symbol for r in a_res.relationships if r.relationship_type == "IMPLEMENTS"}
    assert "BaseStore" in a_inherits
    assert "ABC" in a_implements

    s_res = extract_symbols_and_chunks(service_py, "app/service.py", repo="py_billing")
    s_imports = {r.target_symbol for r in s_res.relationships if r.relationship_type == "IMPORTS"}
    assert "AuditRepository" in s_imports
    assert "AuditRepo" in s_imports

    r_res = extract_symbols_and_chunks(router_py, "app/router.py", repo="py_billing")
    py_routes, _ = extract_api_routes_and_calls(router_py, "app/router.py", repo="py_billing", symbols=r_res.symbols)
    py_route_map = {(rt.http_method, rt.path_pattern): rt.handler_symbol for rt in py_routes}
    assert py_route_map[("POST", "/api/v1/billing")] == "create_charge"
    assert py_route_map[("GET", "/api/v1/billing/{invoice_id}")] == "get_invoice"

    db_path = str(tmp_path / "py_billing.db")
    _setup_sqlite_repo(db_path, "py_billing", [
        ("app/audit.py", audit_py),
        ("app/service.py", service_py),
        ("app/router.py", router_py),
    ])
    get_conn = _conn_factory(db_path)

    with patch("app.services.search.get_db_connection", side_effect=get_conn):
        trace = json.loads(trace_symbol_path("create_charge", repo="py_billing", direction="outbound", depth=2))
        assert trace["target"]["route"] == {"method": "POST", "path": "/api/v1/billing"}
        lvl1 = {c["symbol"]: c for c in trace["callees"]}
        assert "BillingService.charge_account" in lvl1
        lvl2 = {c["symbol"]: c for c in lvl1["BillingService.charge_account"]["callees"]}
        assert "AuditRepository.write_event" in lvl2


def test_multilang_tsx_ts_csharp_python_extraction_and_asset_filtering():
    """Verify TSX arrow/memo/object methods, C# records/ctors, stacked FastAPI routes, and asset bundle filtering."""
    from app.services.indexing.git_syncer import _should_skip_indexed_file

    tsx_code = """
import React, { memo } from 'react';

export const SecurityView: React.FC = () => {
  const handleSave = async () => {
    await fetch('/admin/api/repos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
  };
  const count = 42;
  return <button onClick={handleSave}>{count}</button>;
};

export const MemoBanner = memo(({ title }: { title: string }) => {
  return <div>{title}</div>;
});

export const clientApi = {
  rotateSecret: async (id: string) => {
    return await apiRequest<{ secret: string }>(`/api/clients/${id}/rotate-secret`, {
      method: 'POST'
    });
  }
};
"""
    tsx_res = extract_symbols_and_chunks(tsx_code, "repo://frontend/src/SecurityView.tsx", repo="repo")
    tsx_syms = {s.full_symbol: s.kind for s in tsx_res.symbols}
    assert "SecurityView" in tsx_syms
    assert "SecurityView.handleSave" in tsx_syms
    assert "MemoBanner" in tsx_syms
    assert "clientApi.rotateSecret" in tsx_syms
    assert "SecurityView.count" not in tsx_syms
    assert "anonymous" not in {s.name for s in tsx_res.symbols}

    calls_by_url = {c.url_pattern: (c.http_method, c.caller_symbol) for c in tsx_res.api_client_calls}
    assert calls_by_url["/admin/api/repos"] == ("POST", "SecurityView.handleSave")
    assert calls_by_url["/api/clients/{id}/rotate-secret"] == ("POST", "clientApi.rotateSecret")

    cs_code = """
namespace Demo.Models;

public record ToolExecutionRequest(string ServerId, string ToolName);

public class GatewayService
{
    public GatewayService() {}
    public void Execute(ToolExecutionRequest req) {}
}
"""
    cs_res = extract_symbols_and_chunks(cs_code, "repo://Server/GatewayService.cs", repo="repo")
    cs_syms = {s.full_symbol: s.kind for s in cs_res.symbols}
    assert "ToolExecutionRequest" in cs_syms
    assert "GatewayService" in cs_syms
    assert "GatewayService.GatewayService" in cs_syms
    assert "GatewayService.Execute" in cs_syms

    py_code = """
from fastapi import APIRouter, Depends

router = APIRouter()

@router.post(
    "/admin/api/repos/{repo_id}/sync",
    dependencies=[],
)
@router.post(
    "/admin/api/repos/sync/{repo_id}",
    dependencies=[],
)
async def api_sync_repo(repo_id: int):
    return {"ok": True}
"""
    py_res = extract_symbols_and_chunks(py_code, "repo://app/api/routers/repositories.py", repo="repo")
    routes_by_path = {r.path_pattern: (r.http_method, r.handler_symbol) for r in py_res.api_routes}
    assert routes_by_path["/admin/api/repos/{repo_id}/sync"] == ("POST", "api_sync_repo")
    assert routes_by_path["/admin/api/repos/sync/{repo_id}"] == ("POST", "api_sync_repo")

    assert _should_skip_indexed_file("www/assets/index-BM8WNlQq.js", "index-BM8WNlQq.js") is True
    assert _should_skip_indexed_file("wwwroot/_framework/dotnet.js", "dotnet.js") is True
    assert _should_skip_indexed_file("static/vendor.min.js", "vendor.min.js") is True
    assert _should_skip_indexed_file("frontend/src/App.tsx", "App.tsx") is False

# High-Performance Codebase Navigator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy 2D force-directed physics graph with a high-performance, deterministic 3-Pane Codebase Navigator for instant codebase and symbol exploration.

**Architecture:** A lightweight FastAPI backend querying indexed SQLite tables (`indexed_files`, `ast_symbols`, `ast_relationships`, `api_routes`) coupled with a responsive React 19 frontend featuring a virtualized file tree, symbol outline, and deep caller/callee relationship inspector with click-through navigation and density toggles.

**Tech Stack:** Python 3.12, FastAPI, SQLite3, React 19, TypeScript, Vitest, React Testing Library, Playwright, CSS Variables.

## Global Constraints
- Target frontend bundle must build with `npm run build` using native Vite/TypeScript.
- Backend queries must use indexed SQLite fields and complete in $<5\text{ms}$.
- Full test coverage: Pytest backend tests, Vitest frontend unit tests, and Playwright E2E tests.
- Maintain existing dark theme (`--bg-base: #07181b`, `--bg-card: #0d2c2f`, Outfit font, JetBrains Mono font).

---

### Task 1: Backend Navigator Service & SQLite Queries

**Files:**
- Create: `app/services/navigator.py`
- Test: `tests/backend/test_navigator_service.py`

**Interfaces:**
- Produces:
  - `get_navigator_tree(repo: str) -> Optional[Dict[str, Any]]`
  - `get_file_outline(repo: str, filepath: str) -> Optional[Dict[str, Any]]`
  - `get_symbol_impact(repo: str, symbol_id: int) -> Optional[Dict[str, Any]]`

- [ ] **Step 1: Write failing backend service tests**

```python
# tests/backend/test_navigator_service.py
import pytest
import sqlite3
from app.services.navigator import get_navigator_tree, get_file_outline, get_symbol_impact

def test_navigator_tree_construction(test_db):
    res = get_navigator_tree("test-repo")
    assert res is not None
    assert res["repo"] == "test-repo"
    assert "tree" in res
    assert isinstance(res["tree"], list)

def test_file_outline_retrieval(test_db):
    res = get_file_outline("test-repo", "app/main.py")
    assert res is not None
    assert "symbols" in res

def test_symbol_impact_retrieval(test_db):
    res = get_symbol_impact("test-repo", 1)
    assert res is not None
    assert "callers" in res
    assert "callees" in res
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_navigator_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.navigator'`

- [ ] **Step 3: Implement `app/services/navigator.py`**

```python
# app/services/navigator.py
import os
import logging
from typing import Optional, Dict, Any, List
from app.services.database import get_db_connection

logger = logging.getLogger("contextcortex.navigator")

def _clean_path(p: str) -> str:
    return p.replace("\\", "/").strip("/")

def get_navigator_tree(repo: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        where = "" if repo == "__all__" else " WHERE repo = ?"
        params = [] if repo == "__all__" else [repo]
        
        file_rows = conn.execute(
            f"SELECT filepath, repo, doc_type, language FROM indexed_files{where} ORDER BY filepath",
            params
        ).fetchall()
        
        if not file_rows and repo != "__all__":
            # Verify if repo exists
            repo_exists = conn.execute(
                "SELECT 1 FROM git_repositories WHERE name = ? UNION SELECT 1 FROM indexed_paths WHERE repo = ?",
                (repo, repo)
            ).fetchone()
            if not repo_exists:
                return None

        # Fetch symbol counts per file
        sym_counts = {}
        for row in conn.execute(
            f"SELECT filepath, count(*) as cnt FROM ast_symbols{where} GROUP BY filepath",
            params
        ).fetchall():
            sym_counts[_clean_path(row["filepath"])] = row["cnt"]

        # Fetch route counts per file
        route_counts = {}
        for row in conn.execute(
            f"SELECT filepath, count(*) as cnt FROM api_routes{where} GROUP BY filepath",
            params
        ).fetchall():
            route_counts[_clean_path(row["filepath"])] = row["cnt"]

    # Build hierarchical tree
    root = {"children": {}}
    for f in file_rows:
        raw_path = _clean_path(f["filepath"])
        parts = raw_path.split("/")
        curr = root
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            if part not in curr["children"]:
                curr["children"][part] = {
                    "id": f"{'file' if is_last else 'dir'}:{'/'.join(parts[:i+1])}",
                    "name": part,
                    "is_dir": not is_last,
                    "path": "/".join(parts[:i+1]),
                    "children": {} if not is_last else None,
                    "language": f["language"] if is_last else None,
                    "symbol_count": sym_counts.get(raw_path, 0) if is_last else 0,
                    "route_count": route_counts.get(raw_path, 0) if is_last else 0,
                }
            curr = curr["children"][part]

    def _format_node(n):
        node = {
            "id": n["id"],
            "name": n["name"],
            "is_dir": n["is_dir"],
            "path": n["path"],
            "language": n["language"],
            "symbol_count": n["symbol_count"],
            "route_count": n["route_count"],
        }
        if n["is_dir"]:
            node["children"] = [_format_node(c) for c in n["children"].values()]
            # Aggregate child counts
            node["symbol_count"] = sum(c["symbol_count"] for c in node["children"])
            node["route_count"] = sum(c["route_count"] for c in node["children"])
        return node

    tree = [_format_node(c) for c in root["children"].values()]
    return {
        "repo": repo,
        "total_files": len(file_rows),
        "total_symbols": sum(sym_counts.values()),
        "tree": tree
    }

def get_file_outline(repo: str, filepath: str) -> Optional[Dict[str, Any]]:
    clean_fp = _clean_path(filepath)
    with get_db_connection() as conn:
        where = " WHERE filepath LIKE ? " if repo == "__all__" else " WHERE repo = ? AND filepath LIKE ? "
        params = [f"%{clean_fp}"] if repo == "__all__" else [repo, f"%{clean_fp}"]
        
        symbols = conn.execute(
            f"SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols{where} ORDER BY start_line ASC",
            params
        ).fetchall()

        routes = conn.execute(
            f"SELECT id, framework, http_method, path_pattern, handler_symbol, start_line, end_line FROM api_routes{where}",
            params
        ).fetchall()

    route_by_handler = {r["handler_symbol"]: dict(r) for r in routes if r["handler_symbol"]}
    route_by_line = {r["start_line"]: dict(r) for r in routes}

    formatted_symbols = []
    for s in symbols:
        route_meta = route_by_handler.get(s["name"]) or route_by_line.get(s["start_line"])
        formatted_symbols.append({
            "id": s["id"],
            "name": s["name"],
            "full_symbol": s["full_symbol"],
            "kind": s["kind"],
            "start_line": s["start_line"],
            "end_line": s["end_line"],
            "signature": s["signature"],
            "language": s["language"],
            "route": route_meta
        })

    return {
        "repo": repo,
        "filepath": clean_fp,
        "symbols": formatted_symbols
    }

def get_symbol_impact(repo: str, symbol_id: int) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        sym = conn.execute(
            "SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols WHERE id = ?",
            (symbol_id,)
        ).fetchone()
        
        if not sym:
            return None

        # Fetch incoming callers
        callers = conn.execute(
            "SELECT id, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number FROM ast_relationships WHERE target_symbol = ? OR source_symbol_id = ?",
            (sym["name"], sym["id"])
        ).fetchall()

        # Fetch outgoing dependencies
        callees = conn.execute(
            "SELECT id, target_symbol, relationship_type, line_number FROM ast_relationships WHERE source_symbol_id = ? AND relationship_type != 'IMPORTS'",
            (sym["id"],)
        ).fetchall()

        imports = conn.execute(
            "SELECT id, target_symbol, line_number FROM ast_relationships WHERE source_symbol_id = ? AND relationship_type = 'IMPORTS'",
            (sym["id"],)
        ).fetchall()

        route = conn.execute(
            "SELECT framework, http_method, path_pattern FROM api_routes WHERE handler_symbol = ? OR (filepath LIKE ? AND start_line <= ? AND end_line >= ?)",
            (sym["name"], f"%{_clean_path(sym['filepath'])}", sym["start_line"], sym["end_line"])
        ).fetchone()

    return {
        "symbol": dict(sym),
        "route": dict(route) if route else None,
        "callers": [dict(c) for c in callers],
        "callees": [dict(c) for c in callees],
        "imports": [dict(i) for i in imports]
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/test_navigator_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/navigator.py tests/backend/test_navigator_service.py
git commit -m "feat(backend): add navigator service with tree, outline, and impact queries"
```

---

### Task 2: Backend Navigator API Router & FastAPI Integration

**Files:**
- Create: `app/api/routers/navigator.py`
- Modify: `app/api/routes.py`
- Test: `tests/backend/test_navigator_router.py`

**Interfaces:**
- Produces:
  - `GET /admin/api/navigator/tree`
  - `GET /admin/api/navigator/file-outline`
  - `GET /admin/api/navigator/symbol-impact`

- [ ] **Step 1: Write failing router integration test**

```python
# tests/backend/test_navigator_router.py
import pytest
from fastapi.testclient import TestClient

def test_api_get_navigator_tree(client: TestClient):
    response = client.get("/admin/api/navigator/tree?repo=__all__")
    assert response.status_code == 200
    data = response.json()
    assert "tree" in data

def test_api_get_file_outline(client: TestClient):
    response = client.get("/admin/api/navigator/file-outline?repo=__all__&filepath=app/main.py")
    assert response.status_code in (200, 404)

def test_api_get_symbol_impact(client: TestClient):
    response = client.get("/admin/api/navigator/symbol-impact?repo=__all__&symbol_id=999999")
    assert response.status_code in (200, 404)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_navigator_router.py -v`
Expected: FAIL 404 (route not found)

- [ ] **Step 3: Implement `app/api/routers/navigator.py` and register in `app/api/routes.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/test_navigator_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/navigator.py app/api/routes.py tests/backend/test_navigator_router.py
git commit -m "feat(api): register navigator endpoints in FastAPI router"
```

---

### Task 3: Frontend Navigator Components & Types

**Files:**
- Create: `frontend/src/components/navigator/types.ts`
- Create: `frontend/src/components/navigator/NavigatorToolbar.tsx`
- Create: `frontend/src/components/navigator/NavigatorTree.tsx`
- Create: `frontend/src/components/navigator/NavigatorOutline.tsx`
- Create: `frontend/src/components/navigator/NavigatorInspector.tsx`
- Create: `frontend/src/styles/navigator.css`
- Create: `frontend/src/CodeNavigator.tsx`
- Modify: `frontend/src/index.css`
- Test: `frontend/src/tests/NavigatorTree.test.tsx`
- Test: `frontend/src/tests/NavigatorOutline.test.tsx`
- Test: `frontend/src/tests/NavigatorInspector.test.tsx`

- [ ] **Step 1: Write failing frontend component unit tests**

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- src/tests/NavigatorTree.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement frontend components and styles**

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/navigator frontend/src/CodeNavigator.tsx frontend/src/styles/navigator.css frontend/src/tests/
git commit -m "feat(frontend): create 3-pane CodeNavigator with tree, outline, and impact inspector"
```

---

### Task 4: App Integration & Navigation Tab Replacement

**Files:**
- Modify: `frontend/src/App.tsx` (replace Topology tab with Code Navigator)
- Test: `frontend/src/tests/App.test.tsx`
- Test: `frontend/src/tests/CodeNavigator.test.tsx`

- [ ] **Step 1: Update `App.tsx` to mount `CodeNavigator` under the Navigation tab**
- [ ] **Step 2: Run unit tests and verify build**

Run: `cd frontend && npm run build && npm test`
Expected: PASS with 0 build errors and all unit tests green.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx frontend/src/tests/App.test.tsx frontend/src/tests/CodeNavigator.test.tsx
git commit -m "feat(ui): integrate CodeNavigator into primary dashboard navigation"
```

---

### Task 5: Playwright End-to-End Tests & Layout Inspection

**Files:**
- Create: `frontend/e2e/navigator.spec.ts`
- Test: Playwright suite

- [ ] **Step 1: Write Playwright E2E tests for CodeNavigator**
- [ ] **Step 2: Run Playwright tests**

Run: `cd frontend && npx playwright test e2e/navigator.spec.ts`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/navigator.spec.ts
git commit -m "test(e2e): add Playwright end-to-end tests for CodeNavigator"
```

---

### Task 6: Documentation Updates, Screenshots & PR Automation

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `DEVELOPER_DOCS.md`
- Modify: `docs/TEST_COVERAGE.md`
- Create: Screenshots / visual artifact

- [ ] **Step 1: Update documentation to reflect CodeNavigator features and API**
- [ ] **Step 2: Capture screenshots of the new CodeNavigator UI**
- [ ] **Step 3: Run full CI test suites (pytest, vitest, playwright)**
- [ ] **Step 4: Push branch `feat/codebase-navigator` to remote**
- [ ] **Step 5: Create Pull Request using `gh pr create`**
- [ ] **Step 6: Confirm CI status and merge into `main`**
- [ ] **Step 7: Pull latest `main` locally**

# Auto-Updating Synced Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement automated incremental repository synchronization in Knowledge RAG via push webhooks (`POST /api/webhooks/git`) and a zero-disk-overhead periodic background poller daemon (`app/services/poller.py`), complete with safe database schema migrations, HMAC signature security, REST endpoints, and interactive dashboard UI controls.

**Architecture:** A FastAPI/FastMCP backend extension with SQLite column migrations for `auto_sync` and `webhook_secret`. The webhook router verifies provider signatures (GitHub, GitLab, Gitea) and extracts pushed branch refs, while the background poller daemon periodically runs non-blocking `get_remote_head_sha()` checks. The React 19 dashboard provides per-repo auto-sync toggles, webhook setup modals, and global polling interval settings.

**Tech Stack:** Python 3.12, FastAPI, SQLite3, HMAC/hashlib, Git CLI (`ls-remote`), React 19, TypeScript, Vitest, pytest.

## Global Constraints
- Database migrations in `app/services/db.py` must use non-destructive `PRAGMA table_info` checks and `ALTER TABLE` additions with zero data loss.
- Vector store operations must preserve compatibility across ChromaDB and Qdrant backends.
- Background polling must use `get_remote_head_sha()` without downloading repository files or creating temporary directories when commits have not changed.
- All webhook and API endpoints must validate input paths and prevent path traversal or secret leakages.

---

### Task 1: Database Schema Migrations & Auto-Sync Configuration Store

**Files:**
- Modify: `app/services/db.py`
- Test: `tests/test_auto_sync_db.py`

**Interfaces:**
- Produces: `set_repo_auto_sync(repo_id: int, enabled: bool) -> bool`, `get_auto_sync_interval() -> int`, `set_auto_sync_interval(interval_mins: int) -> None`, `get_global_webhook_secret() -> Optional[str]`, `set_global_webhook_secret(secret: Optional[str]) -> None`, `list_auto_sync_repos() -> List[Dict[str, Any]]`

- [ ] **Step 1: Write failing unit tests in `tests/test_auto_sync_db.py`**

```python
import pytest
from app.services.db import (
    init_db, get_db_connection, set_repo_auto_sync, 
    get_auto_sync_interval, set_auto_sync_interval,
    get_global_webhook_secret, set_global_webhook_secret,
    list_auto_sync_repos
)

def test_db_migration_and_auto_sync_helpers():
    init_db()
    with get_db_connection() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(git_repositories)").fetchall()]
        assert "auto_sync" in cols
        assert "webhook_secret" in cols

    # Test auto sync interval metadata
    assert get_auto_sync_interval() == 15
    set_auto_sync_interval(30)
    assert get_auto_sync_interval() == 30

    # Test global webhook secret metadata
    assert get_global_webhook_secret() is None
    set_global_webhook_secret("my-secret-123")
    assert get_global_webhook_secret() == "my-secret-123"
    set_global_webhook_secret(None)
    assert get_global_webhook_secret() is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_auto_sync_db.py -v
```
Expected: FAIL with missing helper functions or columns.

- [ ] **Step 3: Implement database migrations and helper functions in `app/services/db.py`**

Update `init_db()` in `app/services/db.py`:
```python
# Check and migrate git_repositories table
repo_cols = [r[1] for r in conn.execute("PRAGMA table_info(git_repositories)").fetchall()]
if "auto_sync" not in repo_cols:
    conn.execute("ALTER TABLE git_repositories ADD COLUMN auto_sync INTEGER DEFAULT 1")
if "webhook_secret" not in repo_cols:
    conn.execute("ALTER TABLE git_repositories ADD COLUMN webhook_secret TEXT")
```

Add helper functions:
```python
def get_auto_sync_interval() -> int:
    try:
        val = get_metadata("auto_sync_interval_mins", "15")
        return int(val)
    except (ValueError, TypeError):
        return 15

def set_auto_sync_interval(interval_mins: int) -> None:
    set_metadata("auto_sync_interval_mins", str(max(0, interval_mins)))

def get_global_webhook_secret() -> Optional[str]:
    sec = get_metadata("global_webhook_secret", "")
    return sec.strip() if sec and sec.strip() else None

def set_global_webhook_secret(secret: Optional[str]) -> None:
    set_metadata("global_webhook_secret", secret.strip() if secret else "")

def set_repo_auto_sync(repo_id: int, enabled: bool) -> bool:
    with get_db_connection() as conn:
        res = conn.execute("UPDATE git_repositories SET auto_sync = ? WHERE id = ?", (1 if enabled else 0, repo_id))
        conn.commit()
        return res.rowcount > 0

def list_auto_sync_repos() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, name, url, branch, commit_sha, provider, auto_sync, webhook_secret FROM git_repositories WHERE auto_sync = 1").fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
pytest tests/test_auto_sync_db.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit changes**

```bash
git add app/services/db.py tests/test_auto_sync_db.py
git commit -m "feat: add auto_sync and webhook_secret migrations and DB helpers"
```

---

### Task 2: Multi-Provider Webhook Ingestion Engine & Signature Verification

**Files:**
- Create: `app/api/webhooks.py`
- Modify: `app/api/routes.py`
- Test: `tests/test_webhooks.py`

**Interfaces:**
- Consumes: `get_global_webhook_secret()`, `get_db_connection()`, `sync_single_git_repo()`
- Produces: `POST /api/webhooks/git` endpoint handling GitHub, GitLab, Gitea, Bitbucket push events.

- [ ] **Step 1: Write failing unit tests in `tests/test_webhooks.py`**

```python
import hmac
import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from main import app
from app.services.db import init_db, get_db_connection, set_global_webhook_secret

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()
    with get_db_connection() as conn:
        conn.execute("DELETE FROM git_repositories WHERE name = 'test-repo'")
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("test-repo", "https://github.com/example/test-repo.git", "main", "sha-old", 1)
        )
        conn.commit()

def test_github_webhook_no_secret():
    set_global_webhook_secret(None)
    payload = {
        "ref": "refs/heads/main",
        "repository": {
            "clone_url": "https://github.com/example/test-repo.git",
            "name": "test-repo"
        }
    }
    headers = {"X-GitHub-Event": "push"}
    res = client.post("/api/webhooks/git", json=payload, headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "sync_triggered"

def test_github_webhook_with_secret_valid_and_invalid():
    secret = "super-secret-key"
    set_global_webhook_secret(secret)
    payload_dict = {
        "ref": "refs/heads/main",
        "repository": {"clone_url": "https://github.com/example/test-repo.git"}
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")
    valid_sig = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # Invalid signature
    res_bad = client.post("/api/webhooks/git", content=raw_body, headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=invalid"})
    assert res_bad.status_code == 401

    # Valid signature
    res_good = client.post("/api/webhooks/git", content=raw_body, headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest(), "Content-Type": "application/json"})
    assert res_good.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_webhooks.py -v
```
Expected: FAIL with 404 endpoint not found.

- [ ] **Step 3: Implement `app/api/webhooks.py` and mount in router**

`app/api/webhooks.py`:
```python
import hmac
import hashlib
import json
import logging
import threading
from typing import Optional, Dict, Any, Tuple
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from app.services.db import get_db_connection, get_global_webhook_secret
from app.services.git_manager import normalize_git_url
from app.services.indexer import sync_single_git_repo

logger = logging.getLogger("knowledge-rag-mcp.webhook")
router = APIRouter()

def verify_hmac_sha256(raw_body: bytes, signature_header: Optional[str], secret: str, prefix: str = "sha256=") -> bool:
    if not signature_header:
        return False
    sig = signature_header.replace(prefix, "").strip()
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)

def parse_webhook_payload(payload: Dict[str, Any], headers: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
    """Extracts (normalized_repo_url, pushed_branch) from payload."""
    ref = payload.get("ref", "")
    branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref

    repo_url = None
    if "repository" in payload and isinstance(payload["repository"], dict):
        rep = payload["repository"]
        repo_url = rep.get("clone_url") or rep.get("git_url") or rep.get("ssh_url") or rep.get("html_url")
    elif "project" in payload and isinstance(payload["project"], dict): # GitLab
        proj = payload["project"]
        repo_url = proj.get("git_http_url") or proj.get("git_ssh_url") or proj.get("web_url")

    return (normalize_git_url(repo_url) if repo_url else None, branch or None)

@router.post("/api/webhooks/git")
async def handle_git_webhook(request: Request):
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    global_secret = get_global_webhook_secret()

    # Signature verification if secret is configured
    if global_secret:
        gh_sig = headers.get("x-hub-signature-256")
        gl_token = headers.get("x-gitlab-token")
        gitea_sig = headers.get("x-gitea-signature")

        authorized = False
        if gh_sig:
            authorized = verify_hmac_sha256(raw_body, gh_sig, global_secret)
        elif gl_token:
            authorized = hmac.compare_digest(gl_token.strip(), global_secret.strip())
        elif gitea_sig:
            authorized = verify_hmac_sha256(raw_body, gitea_sig, global_secret, prefix="")
        
        if not authorized:
            logger.warning("Unauthorized webhook payload received - invalid or missing signature/token")
            return JSONResponse(status_code=401, content={"error": "Invalid webhook signature or token"})

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Invalid JSON payload: {e}"})

    repo_url, pushed_branch = parse_webhook_payload(payload, headers)
    if not repo_url:
        return JSONResponse(status_code=400, content={"error": "Could not identify repository URL from payload"})

    # Match repository in DB
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, name, url, branch, auto_sync FROM git_repositories").fetchall()

    matched_repo = None
    for r in rows:
        norm_db_url = normalize_git_url(r["url"])
        if norm_db_url == repo_url or norm_db_url.rstrip(".git") == repo_url.rstrip(".git"):
            # Check branch match if branch present in payload
            if not pushed_branch or r["branch"] == pushed_branch:
                matched_repo = dict(r)
                break

    if not matched_repo:
        logger.info(f"Webhook received for unregistered or non-matching repository: {repo_url} (branch: {pushed_branch})")
        return JSONResponse(status_code=200, content={"status": "ignored", "message": "Repository or branch not registered"})

    if not matched_repo.get("auto_sync", 1):
        logger.info(f"Webhook received for repo '{matched_repo['name']}' but auto-sync is disabled")
        return JSONResponse(status_code=200, content={"status": "ignored", "message": "Auto-sync disabled for this repository"})

    repo_id = matched_repo["id"]
    repo_name = matched_repo["name"]
    logger.info(f"Webhook triggered sync for repository '{repo_name}' (ID: {repo_id}, Branch: {pushed_branch})")
    threading.Thread(target=sync_single_git_repo, args=(repo_id,), daemon=True).start()

    return {"status": "sync_triggered", "repo": repo_name, "id": repo_id}
```

Include webhook router in `app/api/routes.py` (or mount router directly).

- [ ] **Step 4: Run tests and verify they pass**

```bash
pytest tests/test_webhooks.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit changes**

```bash
git add app/api/webhooks.py app/api/routes.py tests/test_webhooks.py
git commit -m "feat: implement multi-provider git push webhook endpoint with HMAC validation"
```

---

### Task 3: Periodic Background Poller Daemon

**Files:**
- Create: `app/services/poller.py`
- Modify: `app/mcp/mcp_server.py`
- Test: `tests/test_poller.py`

**Interfaces:**
- Consumes: `list_auto_sync_repos()`, `get_auto_sync_interval()`, `get_remote_head_sha()`, `sync_single_git_repo()`, `is_indexing`
- Produces: `start_poller_daemon()`, `stop_poller_daemon()`, `trigger_poller_check_now()`

- [ ] **Step 1: Write unit tests in `tests/test_poller.py`**

```python
import time
import pytest
from app.services.db import init_db, get_db_connection, set_auto_sync_interval
from app.services.poller import check_all_auto_sync_repos

def test_check_all_auto_sync_repos(monkeypatch):
    init_db()
    with get_db_connection() as conn:
        conn.execute("DELETE FROM git_repositories WHERE name = 'poll-test-repo'")
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("poll-test-repo", "https://github.com/example/poll-repo.git", "main", "sha-111", 1)
        )
        conn.commit()

    synced_ids = []
    def mock_get_remote_sha(url, branch, **kwargs):
        return "sha-222" # Changed SHA

    def mock_sync_repo(repo_id):
        synced_ids.append(repo_id)

    monkeypatch.setattr("app.services.poller.get_remote_head_sha", mock_get_remote_sha)
    monkeypatch.setattr("app.services.poller.sync_single_git_repo", mock_sync_repo)

    checked, updated = check_all_auto_sync_repos()
    assert checked >= 1
    assert updated >= 1
    assert len(synced_ids) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_poller.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `app/services/poller.py` and attach to server lifecycle**

`app/services/poller.py`:
```python
import time
import logging
import threading
from typing import Tuple
from app.services.db import list_auto_sync_repos, get_auto_sync_interval, get_effective_git_token
from app.services.git_manager import get_remote_head_sha
from app.services.indexer import sync_single_git_repo, is_indexing

logger = logging.getLogger("knowledge-rag-mcp.poller")

_poller_thread: Optional[threading.Thread] = None
_poller_stop_event = threading.Event()

def check_all_auto_sync_repos() -> Tuple[int, int]:
    """Checks all auto_sync=1 repos for remote commit SHA changes."""
    if is_indexing:
        logger.info("Poller check deferred: indexing engine is currently busy.")
        return (0, 0)

    repos = list_auto_sync_repos()
    if not repos:
        return (0, 0)

    checked = 0
    updated = 0

    for r in repos:
        repo_id = r["id"]
        repo_name = r["name"]
        git_url = r["url"]
        branch = r.get("branch") or "main"
        provider = r.get("provider")
        current_sha = r.get("commit_sha")

        eff_token, eff_user, _ = get_effective_git_token(git_url, provider=provider)

        try:
            remote_sha = get_remote_head_sha(git_url, branch, token=eff_token, username=eff_user, provider=provider)
            checked += 1
            if remote_sha and remote_sha != current_sha:
                logger.info(f"Poller detected update for repo '{repo_name}' ({current_sha} -> {remote_sha}). Triggering sync.")
                sync_single_git_repo(repo_id)
                updated += 1
        except Exception as e:
            logger.error(f"Poller error checking repo '{repo_name}': {e}")

    logger.info(f"Poller check complete: {checked} checked, {updated} updated.")
    return (checked, updated)

def _poller_worker():
    logger.info("Background repository auto-sync poller started.")
    while not _poller_stop_event.is_set():
        interval_mins = get_auto_sync_interval()
        if interval_mins > 0:
            try:
                check_all_auto_sync_repos()
            except Exception as e:
                logger.error(f"Error in poller worker cycle: {e}")

        # Sleep in 5s increments to respond promptly to stop events
        sleep_seconds = (interval_mins * 60) if interval_mins > 0 else 60
        slept = 0
        while slept < sleep_seconds and not _poller_stop_event.is_set():
            time.sleep(min(5, sleep_seconds - slept))
            slept += 5

def start_poller_daemon():
    global _poller_thread
    if _poller_thread and _poller_thread.is_alive():
        return
    _poller_stop_event.clear()
    _poller_thread = threading.Thread(target=_poller_worker, daemon=True, name="GitRepoPoller")
    _poller_thread.start()

def stop_poller_daemon():
    _poller_stop_event.set()
```

In `app/mcp/mcp_server.py` lifespan / startup hook, call `start_poller_daemon()` on startup and `stop_poller_daemon()` on shutdown.

- [ ] **Step 4: Run tests and verify they pass**

```bash
pytest tests/test_poller.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit changes**

```bash
git add app/services/poller.py app/mcp/mcp_server.py tests/test_poller.py
git commit -m "feat: implement background repository auto-sync poller daemon"
```

---

### Task 4: REST API Endpoints for Settings & Auto-Sync Management

**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/models/schemas.py`
- Test: `tests/test_auto_sync_api.py`

**Interfaces:**
- Produces:
  - `PATCH /admin/api/repos/{repo_id}/auto-sync` (`{ "auto_sync": bool }`)
  - `GET /admin/api/settings/auto-sync`
  - `POST /admin/api/settings/auto-sync`

- [ ] **Step 1: Write failing unit tests in `tests/test_auto_sync_api.py`**

```python
import pytest
from fastapi.testclient import TestClient
from main import app
from app.services.db import init_db, get_db_connection

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

def test_repo_auto_sync_toggle_and_settings_endpoints():
    with get_db_connection() as conn:
        conn.execute("DELETE FROM git_repositories WHERE name = 'api-toggle-repo'")
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("api-toggle-repo", "https://github.com/example/toggle.git", "main", "sha-1", 1)
        )
        repo_id = conn.execute("SELECT id FROM git_repositories WHERE name = 'api-toggle-repo'").fetchone()[0]
        conn.commit()

    # Toggle auto sync to False
    res = client.patch(f"/admin/api/repos/{repo_id}/auto-sync", json={"auto_sync": False})
    assert res.status_code == 200
    assert res.json()["auto_sync"] is False

    # Get settings
    res_get = client.get("/admin/api/settings/auto-sync")
    assert res_get.status_code == 200
    assert "interval_mins" in res_get.json()
    assert "webhook_url" in res_get.json()

    # Post settings
    res_post = client.post("/admin/api/settings/auto-sync", json={"interval_mins": 30, "global_webhook_secret": "new-sec"})
    assert res_post.status_code == 200
    assert res_post.json()["interval_mins"] == 30
    assert res_post.json()["has_global_secret"] is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_auto_sync_api.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement endpoints in `app/api/routes.py` and schemas in `app/models/schemas.py`**

`app/models/schemas.py`:
```python
class AutoSyncToggleRequest(BaseModel):
    auto_sync: bool

class AutoSyncSettingsRequest(BaseModel):
    interval_mins: int
    global_webhook_secret: Optional[str] = None
```

`app/api/routes.py`:
```python
@router.patch("/admin/api/repos/{repo_id}/auto-sync")
async def api_toggle_repo_auto_sync(repo_id: int, payload: AutoSyncToggleRequest):
    try:
        from app.services.db import set_repo_auto_sync
        success = set_repo_auto_sync(repo_id, payload.auto_sync)
        if not success:
            return JSONResponse(status_code=404, content={"error": "Repository not found"})
        return {"status": "success", "repo_id": repo_id, "auto_sync": payload.auto_sync}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/settings/auto-sync")
async def api_get_auto_sync_settings():
    try:
        from app.services.db import get_auto_sync_interval, get_global_webhook_secret
        interval = get_auto_sync_interval()
        secret = get_global_webhook_secret()
        return {
            "interval_mins": interval,
            "webhook_url": "/api/webhooks/git",
            "has_global_secret": bool(secret)
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/settings/auto-sync")
async def api_update_auto_sync_settings(payload: AutoSyncSettingsRequest):
    try:
        from app.services.db import set_auto_sync_interval, set_global_webhook_secret
        set_auto_sync_interval(payload.interval_mins)
        if payload.global_webhook_secret is not None:
            set_global_webhook_secret(payload.global_webhook_secret)
        return {
            "status": "success",
            "interval_mins": payload.interval_mins,
            "has_global_secret": bool(payload.global_webhook_secret)
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
pytest tests/test_auto_sync_api.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit changes**

```bash
git add app/models/schemas.py app/api/routes.py tests/test_auto_sync_api.py
git commit -m "feat: implement REST API endpoints for repository auto-sync and webhook settings"
```

---

### Task 5: Frontend UI: Git Repositories Tab Controls & Webhook Modal

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/GitRepoManager.tsx`
- Test: `frontend/src/tests/GitRepoManager.test.tsx`

**Interfaces:**
- Consumes: `auto_sync` field from repo objects, `PATCH /admin/api/repos/{id}/auto-sync`
- Produces: Auto-sync toggle switches and Webhook setup guidance modal in `GitRepoManager`.

- [ ] **Step 1: Update `frontend/src/types.ts`**

Add `auto_sync?: number | boolean; webhook_secret?: string;` to `GitRepo` interface.

- [ ] **Step 2: Implement Auto-Sync toggle & Webhook modal in `GitRepoManager.tsx`**

- Add state `const [webhookModalRepo, setWebhookModalRepo] = useState<GitRepo | null>(null);`
- Add function `toggleAutoSync(repoId: number, currentState: boolean)` sending `PATCH /admin/api/repos/${repoId}/auto-sync`.
- Add Auto-Sync toggle button / badge in desktop table and mobile card view.
- Add Webhook modal rendering copyable webhook endpoint (`window.location.origin + '/api/webhooks/git'`) and provider configuration steps for GitHub (`Settings > Webhooks > Add webhook > Content type: application/json > Push events`), GitLab (`Settings > Webhooks > Push events`), and Gitea (`Settings > Webhooks`).

- [ ] **Step 3: Update `frontend/src/tests/GitRepoManager.test.tsx`**

Add test cases verifying:
- Auto-sync toggle dispatches PATCH request.
- Webhook modal opens, displays correct URL, and closes on backdrop/button click.

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd frontend && npm test
```
Expected: All 8 test files pass.

- [ ] **Step 5: Commit changes**

```bash
git add frontend/src/types.ts frontend/src/GitRepoManager.tsx frontend/src/tests/GitRepoManager.test.tsx
git commit -m "feat: add auto-sync toggle and webhook setup modal to GitRepoManager UI"
```

---

### Task 6: Frontend UI: Settings Tab Auto-Sync & Polling Config

**Files:**
- Modify: `frontend/src/Settings.tsx`
- Test: `frontend/src/tests/Settings.test.tsx`

**Interfaces:**
- Consumes: `GET /admin/api/settings/auto-sync`, `POST /admin/api/settings/auto-sync`
- Produces: Dedicated Auto-Sync & Webhooks panel in Settings tab.

- [ ] **Step 1: Implement Auto-Sync & Webhooks panel in `frontend/src/Settings.tsx`**

- Add state for `intervalMins`, `webhookSecret`, `hasGlobalSecret`, `isSavingAutoSync`.
- Load settings on component mount.
- Render card with:
  - Polling interval dropdown (`Disabled (0m)`, `5 minutes`, `15 minutes (Default)`, `30 minutes`, `1 hour`, `6 hours`).
  - Webhook secret input with password masking toggle.
  - Webhook endpoint display with 1-click copy button.
  - Save button with toast notification.

- [ ] **Step 2: Update `frontend/src/tests/Settings.test.tsx`**

Add tests verifying loading and saving auto-sync interval and webhook secret.

- [ ] **Step 3: Run frontend tests and verify clean build**

```bash
cd frontend && npm test && npm run build
```
Expected: PASS with 0 build errors.

- [ ] **Step 4: Commit changes**

```bash
git add frontend/src/Settings.tsx frontend/src/tests/Settings.test.tsx
git commit -m "feat: add auto-sync schedule and webhook secret configuration to Settings UI"
```

---

### Task 7: Full System Verification & End-to-End Suite

**Files:**
- Test: Full backend and frontend suites

- [ ] **Step 1: Run full backend pytest suite**

```bash
pytest -v
```
Expected: 100% test passing across all existing and new test modules.

- [ ] **Step 2: Run full frontend vitest suite**

```bash
cd frontend && npm test
```
Expected: All test suites pass cleanly.

- [ ] **Step 3: Run frontend build**

```bash
cd frontend && npm run build
```
Expected: Clean production build.

- [ ] **Step 4: Commit and finalize feature branch**

```bash
git add .
git commit -m "chore: complete auto-sync webhooks and poller integration"
```

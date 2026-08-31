# Git Repo Ingestion Real-Time Progress & Live Log Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement granular 5-step progress tracking, real-time Server-Sent Events (SSE) streaming telemetry, and an interactive slide-out log drawer for Git repository ingestion in Contexthub.

**Architecture:** A thread-safe in-memory `GitProgressTracker` registers active sync jobs and per-repo ring buffers (300 lines). `git_syncer.py` is instrumented across 5 stages (Remote Check, Clone, Delta Scan, AST Parse, Vector Index). FastAPI exposes SSE streaming (`/admin/api/repos/sync/stream`) and snapshot REST endpoints. The React frontend consumes the stream via `useGitSyncStream` hook and renders inline row progress bars and a slide-out `RepoSyncDrawer` terminal console.

**Tech Stack:** Python 3.12, FastAPI, `asyncio`, `EventSourceResponse`, React 18, TypeScript, Vitest, Playwright.

## Global Constraints
- Do not use blocking database calls inside high-frequency progress loops; all real-time state and logs are tracked in-memory.
- Preserve all existing database schemas in `git_repositories` while augmenting real-time visibility.
- Ensure all SSE connections include periodic 15s keep-alive heartbeats to prevent proxy timeouts.
- All frontend UI elements must remain fully responsive and properly contained without visual bleeding across desktop and mobile viewports.

---

### Task 1: Backend Progress Registry (`app/services/indexing/git_progress.py`) & Unit Tests

**Files:**
- Create: `app/services/indexing/git_progress.py`
- Test: `tests/backend/test_git_progress.py`

**Interfaces:**
- Produces:
  - `GitSyncJob` dataclass: `repo_id`, `repo_name`, `status`, `step`, `total_steps`, `step_name`, `current_file`, `processed_files`, `total_files`, `percent`, `started_at`, `updated_at`, `error`, `logs`, `cancelled`
  - `GitProgressTracker` singleton with methods:
    - `get_or_create_job(repo_id: int, repo_name: str) -> GitSyncJob`
    - `update_step(repo_id: int, step: int, step_name: str, current_file: Optional[str] = None, processed: int = 0, total: int = 0, pct: Optional[int] = None)`
    - `log(repo_id: int, level: str, message: str)`
    - `finish_job(repo_id: int, status: str = "synced", error: Optional[str] = None)`
    - `cancel_job(repo_id: int) -> bool`
    - `is_cancelled(repo_id: int) -> bool`
    - `get_snapshot(repo_id: Optional[int] = None) -> Any`
    - `subscribe() -> asyncio.Queue`
    - `unsubscribe(queue: asyncio.Queue)`

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_git_progress.py
import pytest
import asyncio
from app.services.indexing.git_progress import GitProgressTracker

def test_tracker_job_lifecycle():
    tracker = GitProgressTracker()
    job = tracker.get_or_create_job(1, "test-repo")
    assert job.status == "pending"
    assert job.step == 1
    assert job.total_steps == 5

    tracker.update_step(1, 2, "Shallow Cloning", processed=1, total=1, pct=20)
    assert job.step == 2
    assert job.step_name == "Shallow Cloning"
    assert job.percent == 20

    tracker.log(1, "INFO", "Cloned successfully in 1.2s")
    assert len(job.logs) == 1
    assert "Cloned successfully" in job.logs[0]["message"]

    tracker.finish_job(1, "synced")
    assert job.status == "synced"

def test_tracker_cancellation():
    tracker = GitProgressTracker()
    tracker.get_or_create_job(2, "cancel-repo")
    assert not tracker.is_cancelled(2)
    tracker.cancel_job(2)
    assert tracker.is_cancelled(2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_git_progress.py -v`
Expected: FAIL with ModuleNotFoundError or import error

- [ ] **Step 3: Implement `app/services/indexing/git_progress.py`**

```python
import time
import asyncio
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Set

@dataclass
class GitSyncJob:
    repo_id: int
    repo_name: str
    status: str = "pending"
    step: int = 1
    total_steps: int = 5
    step_name: str = "Connecting & Remote Check"
    current_file: Optional[str] = None
    processed_files: int = 0
    total_files: int = 0
    percent: int = 0
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: Optional[str] = None
    logs: deque = field(default_factory=lambda: deque(maxlen=300))
    cancelled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["logs"] = list(self.logs)
        return d

class GitProgressTracker:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(GitProgressTracker, cls).__new__(cls)
                cls._instance._init_tracker()
            return cls._instance

    def _init_tracker(self):
        self.jobs: Dict[int, GitSyncJob] = {}
        self.subscribers: Set[asyncio.Queue] = set()
        self.sub_lock = threading.Lock()

    def get_or_create_job(self, repo_id: int, repo_name: str) -> GitSyncJob:
        with self._lock:
            if repo_id not in self.jobs:
                self.jobs[repo_id] = GitSyncJob(repo_id=repo_id, repo_name=repo_name)
            else:
                job = self.jobs[repo_id]
                job.repo_name = repo_name
                job.status = "syncing"
                job.step = 1
                job.step_name = "Connecting & Remote Check"
                job.current_file = None
                job.processed_files = 0
                job.total_files = 0
                job.percent = 0
                job.error = None
                job.cancelled = False
                job.started_at = time.time()
                job.updated_at = time.time()
            self._broadcast({"type": "progress", "data": self.jobs[repo_id].to_dict()})
            return self.jobs[repo_id]

    def update_step(
        self,
        repo_id: int,
        step: int,
        step_name: str,
        current_file: Optional[str] = None,
        processed: int = 0,
        total: int = 0,
        pct: Optional[int] = None
    ):
        with self._lock:
            job = self.jobs.get(repo_id)
            if not job:
                return
            job.status = "syncing"
            job.step = step
            job.step_name = step_name
            job.current_file = current_file
            job.processed_files = processed
            job.total_files = total
            if pct is not None:
                job.percent = max(0, min(100, pct))
            elif total > 0:
                base_pct = int(((step - 1) / job.total_steps) * 100)
                step_range = int(100 / job.total_steps)
                job.percent = min(100, base_pct + int((processed / total) * step_range))
            else:
                job.percent = int(((step - 1) / job.total_steps) * 100)
            job.updated_at = time.time()
            payload = job.to_dict()
        self._broadcast({"type": "progress", "data": payload})

    def log(self, repo_id: int, level: str, message: str):
        entry = {
            "timestamp": time.strftime("%H:%M:%S"),
            "level": level.upper(),
            "message": message
        }
        with self._lock:
            job = self.jobs.get(repo_id)
            if job:
                job.logs.append(entry)
                job.updated_at = time.time()
        self._broadcast({"type": "log", "repo_id": repo_id, "data": entry})

    def finish_job(self, repo_id: int, status: str = "synced", error: Optional[str] = None):
        with self._lock:
            job = self.jobs.get(repo_id)
            if not job:
                return
            job.status = status
            job.error = error
            if status == "synced":
                job.step = job.total_steps
                job.percent = 100
                job.step_name = "Sync Complete"
            job.updated_at = time.time()
            payload = job.to_dict()
        self._broadcast({"type": "progress", "data": payload})

    def cancel_job(self, repo_id: int) -> bool:
        with self._lock:
            job = self.jobs.get(repo_id)
            if job and job.status == "syncing":
                job.cancelled = True
                job.status = "error"
                job.error = "Sync cancelled by user"
                job.updated_at = time.time()
                payload = job.to_dict()
                self._broadcast({"type": "progress", "data": payload})
                return True
        return False

    def is_cancelled(self, repo_id: int) -> bool:
        with self._lock:
            job = self.jobs.get(repo_id)
            return bool(job and job.cancelled)

    def get_snapshot(self, repo_id: Optional[int] = None) -> Any:
        with self._lock:
            if repo_id is not None:
                job = self.jobs.get(repo_id)
                return job.to_dict() if job else None
            return {r_id: j.to_dict() for r_id, j in self.jobs.items()}

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        with self.sub_lock:
            self.subscribers.add(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue):
        with self.sub_lock:
            self.subscribers.discard(queue)

    def _broadcast(self, event: Dict[str, Any]):
        with self.sub_lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except Exception:
                pass

progress_tracker = GitProgressTracker()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_git_progress.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/indexing/git_progress.py tests/backend/test_git_progress.py
git commit -m "feat(backend): implement GitProgressTracker with in-memory state and event subscriptions"
```

---

### Task 2: 5-Stage Indexer Instrumentation (`app/services/indexing/git_syncer.py` & `git_manager.py`)

**Files:**
- Modify: `app/services/indexing/git_syncer.py:93-347`
- Modify: `app/services/git_manager.py:154-208`
- Test: `tests/backend/test_git_syncer_progress.py`

**Interfaces:**
- Consumes: `app.services.indexing.git_progress.progress_tracker`
- Produces: Granular step emissions and per-file progress events across all 5 stages of `sync_single_git_repo`.

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_git_syncer_progress.py
import pytest
from unittest.mock import patch, MagicMock
from app.services.indexing.git_progress import progress_tracker
from app.services.indexing.git_syncer import sync_single_git_repo

@patch("app.services.database.get_db_connection")
@patch("app.services.git_manager.get_remote_head_sha")
def test_git_syncer_reports_stages(mock_sha, mock_db):
    mock_conn = MagicMock()
    mock_db.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = {
        "id": 99, "name": "mock-repo", "url": "https://github.com/test/repo.git",
        "branch": "main", "commit_sha": "old123", "auth_token": None, "provider": "github"
    }
    mock_sha.return_value = "old123"

    sync_single_git_repo(99)
    job = progress_tracker.get_snapshot(99)
    assert job is not None
    assert job["status"] == "synced"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_git_syncer_progress.py -v`

- [ ] **Step 3: Instrument `sync_single_git_repo` in `git_syncer.py` & `git_manager.py`**

In `app/services/git_manager.py`, accept an optional `on_log` callback or call `progress_tracker.log` to report clone duration and safe URL.
In `app/services/indexing/git_syncer.py`:
1. Initialize job: `progress_tracker.get_or_create_job(repo_id, repo_name)`.
2. **Step 1 (Connecting & Remote Check)**:
   `progress_tracker.update_step(repo_id, 1, "Checking Remote Repository Ref", pct=10)`
   `progress_tracker.log(repo_id, "INFO", f"Checking remote status for '{repo_name}' ({safe_url})...")`
3. **Step 2 (Shallow Cloning)**:
   `progress_tracker.update_step(repo_id, 2, "Shallow Cloning Repository", pct=25)`
   `progress_tracker.log(repo_id, "INFO", f"Cloning branch '{branch}' to ephemeral directory...")`
4. **Step 3 (Computing File Delta)**:
   `progress_tracker.update_step(repo_id, 3, "Computing File Delta & Scanning", pct=40)`
   `progress_tracker.log(repo_id, "INFO", f"Delta computed: +{len(added_files)} added, ~{len(modified_files)} modified, -{len(deleted_filepaths)} deleted, {len(unchanged_files)} unchanged")`
5. **Step 4 (Parsing AST & Routes)**:
   For each file in loop:
   - Check `if progress_tracker.is_cancelled(repo_id): raise RuntimeError("Sync cancelled by user")`
   - `progress_tracker.update_step(repo_id, 4, f"Parsing Files ({idx+1}/{total_files})", current_file=rel_path, processed=idx+1, total=total_files)`
   - `progress_tracker.log(repo_id, "INFO", f"[{idx+1}/{total_files}] Ingested {rel_path} (+{len(points)} chunks, +{len(symbols)} symbols)")`
6. **Step 5 (Vector Indexing & Cleanup)**:
   `progress_tracker.update_step(repo_id, 5, "Upserting Embeddings & Indexing", pct=90)`
   `progress_tracker.finish_job(repo_id, "synced")`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_git_syncer_progress.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/indexing/git_syncer.py app/services/git_manager.py tests/backend/test_git_syncer_progress.py
git commit -m "feat(backend): instrument git syncer 5-step lifecycle and real-time progress logging"
```

---

### Task 3: SSE Streaming & Snapshot REST API Endpoints (`app/api/routers/repositories.py`)

**Files:**
- Modify: `app/api/routers/repositories.py`
- Test: `tests/backend/test_git_sync_api.py`

**Interfaces:**
- Produces:
  - `GET /admin/api/repos/sync/stream` (SSE EventStream endpoint)
  - `GET /admin/api/repos/{repo_id}/sync-status` (JSON snapshot endpoint)
  - `POST /admin/api/repos/{repo_id}/cancel-sync` (JSON cancellation endpoint)

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_git_sync_api.py
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.indexing.git_progress import progress_tracker

client = TestClient(app)

def test_sync_status_endpoint():
    progress_tracker.get_or_create_job(101, "api-repo")
    progress_tracker.update_step(101, 3, "Computing Delta", pct=45)
    progress_tracker.log(101, "INFO", "Sample api log line")

    resp = client.get("/admin/api/repos/101/sync-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["repo_id"] == 101
    assert data["step"] == 3
    assert len(data["logs"]) >= 1

def test_cancel_sync_endpoint():
    progress_tracker.get_or_create_job(102, "cancel-api-repo")
    resp = client.post("/admin/api/repos/102/cancel-sync")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_git_sync_api.py -v`

- [ ] **Step 3: Implement SSE & REST routes in `repositories.py`**

```python
import json
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from app.services.indexing.git_progress import progress_tracker

@router.get("/admin/api/repos/{repo_id}/sync-status")
async def api_get_repo_sync_status(repo_id: int):
    snapshot = progress_tracker.get_snapshot(repo_id)
    if not snapshot:
        return JSONResponse(status_code=404, content={"error": f"No active sync job for repo {repo_id}"})
    return snapshot

@router.post("/admin/api/repos/{repo_id}/cancel-sync")
async def api_cancel_repo_sync(repo_id: int):
    cancelled = progress_tracker.cancel_job(repo_id)
    if not cancelled:
        return JSONResponse(status_code=400, content={"error": f"Repo {repo_id} is not currently syncing"})
    return {"status": "cancelled", "repo_id": repo_id}

@router.get("/admin/api/repos/sync/stream")
async def api_stream_repo_sync(request: Request):
    queue = progress_tracker.subscribe()

    async def event_generator():
        try:
            # Send initial snapshot of all active jobs on connect
            init_snapshot = progress_tracker.get_snapshot()
            yield f"event: init\ndata: {json.dumps(init_snapshot)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    evt_type = event.get("type", "progress")
                    yield f"event: {evt_type}\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat ping every 15 seconds
                    yield f": keep-alive ping\n\n"
        finally:
            progress_tracker.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_git_sync_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/repositories.py tests/backend/test_git_sync_api.py
git commit -m "feat(api): add SSE stream and sync-status snapshot endpoints for git progress"
```

---

### Task 4: Frontend SSE Hook & Drawer Component (`useGitSyncStream.ts`, `RepoSyncDrawer.tsx`)

**Files:**
- Create: `frontend/src/hooks/useGitSyncStream.ts`
- Create: `frontend/src/components/git/RepoSyncDrawer.tsx`
- Test: `frontend/src/tests/RepoSyncDrawer.test.tsx`

**Interfaces:**
- Produces:
  - `useGitSyncStream()` hook returning `{ syncStates: Record<number, GitSyncJob>, isConnected: boolean }`
  - `<RepoSyncDrawer isOpen={boolean} onClose={fn} repoId={number} repoName={string} job={GitSyncJob} onCancelSync={fn} />`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/tests/RepoSyncDrawer.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { RepoSyncDrawer } from '../components/git/RepoSyncDrawer';

describe('RepoSyncDrawer', () => {
  const mockJob = {
    repo_id: 1,
    repo_name: 'test-repo',
    status: 'syncing',
    step: 3,
    total_steps: 5,
    step_name: 'Computing File Delta',
    current_file: 'src/main.ts',
    processed_files: 4,
    total_files: 10,
    percent: 40,
    started_at: Date.now() / 1000 - 15,
    updated_at: Date.now() / 1000,
    logs: [
      { timestamp: '12:00:01', level: 'INFO', message: 'Cloned branch main' },
      { timestamp: '12:00:05', level: 'INFO', message: 'Scanning files' },
    ],
    cancelled: false,
  };

  it('renders 5-step checklist and active step', () => {
    render(
      <RepoSyncDrawer
        isOpen={true}
        onClose={vi.fn()}
        repoId={1}
        repoName="test-repo"
        job={mockJob}
        onCancelSync={vi.fn()}
      />
    );
    expect(screen.getByText('test-repo Ingestion Progress')).toBeInTheDocument();
    expect(screen.getByText('Computing File Delta')).toBeInTheDocument();
    expect(screen.getByText('Cloned branch main')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- RepoSyncDrawer`

- [ ] **Step 3: Implement `useGitSyncStream.ts` and `RepoSyncDrawer.tsx`**

`useGitSyncStream.ts`:
- Sets up `new EventSource('/admin/api/repos/sync/stream')`.
- Handles `event: init`, `event: progress`, and `event: log`.
- Maintains local `syncStates: Record<number, GitSyncJob>`.

`RepoSyncDrawer.tsx`:
- Render 5-step checklist:
  1. Connecting & Remote Check
  2. Shallow Cloning Repository
  3. Computing File Delta & Scanning
  4. Parsing AST Symbols & API Routes
  5. Upserting Embeddings & Indexing
- Render terminal-style log output with dark theme, level badges, autoscroll toggle, copy button, and filter input.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- RepoSyncDrawer`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useGitSyncStream.ts frontend/src/components/git/RepoSyncDrawer.tsx frontend/src/tests/RepoSyncDrawer.test.tsx
git commit -m "feat(frontend): implement useGitSyncStream hook and RepoSyncDrawer live log terminal"
```

---

### Task 5: Frontend Table Integration & Styling (`RepoListTable.tsx`, `GitRepoManager.tsx`, `components.css`)

**Files:**
- Modify: `frontend/src/GitRepoManager.tsx`
- Modify: `frontend/src/components/git/RepoListTable.tsx`
- Modify: `frontend/src/styles/components.css`
- Test: `frontend/src/tests/RepoListTable.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/tests/RepoListTable.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { RepoListTable } from '../components/git/RepoListTable';

describe('RepoListTable with Real-Time Progress', () => {
  const mockRepos = [
    {
      id: 1,
      name: 'api-repo',
      url: 'https://github.com/org/repo.git',
      branch: 'main',
      status: 'syncing',
      commit_sha: 'a1b2c3d4',
      file_count: 50,
      last_synced: '2026-08-31',
    },
  ];

  const mockProgress = {
    1: {
      repo_id: 1,
      repo_name: 'api-repo',
      status: 'syncing',
      step: 4,
      total_steps: 5,
      step_name: 'Parsing AST Symbols',
      current_file: 'src/routes.ts',
      processed_files: 20,
      total_files: 50,
      percent: 55,
      started_at: Date.now() / 1000,
      updated_at: Date.now() / 1000,
      logs: [],
      cancelled: false,
    },
  };

  it('renders progress bar and step badge', () => {
    const onOpenDrawer = vi.fn();
    render(
      <RepoListTable
        repos={mockRepos}
        progressMap={mockProgress}
        onSync={vi.fn()}
        onToggleAutoSync={vi.fn()}
        onOpenWebhook={vi.fn()}
        onDelete={vi.fn()}
        onOpenSyncDrawer={onOpenDrawer}
      />
    );
    expect(screen.getByText(/Step 4\/5/)).toBeInTheDocument();
    expect(screen.getByText(/55%/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Step 4\/5/));
    expect(onOpenDrawer).toHaveBeenCalledWith(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- RepoListTable`

- [ ] **Step 3: Implement Table Row Progress Bar & Drawer in `RepoListTable.tsx` & `GitRepoManager.tsx`**

- In `RepoListTable.tsx`, render:
  - Step Badge: `badge badge-primary progress-pill` showing `Step X/5 (Z%)` with pulsing dot.
  - Progress bar filling based on `percent`.
  - Caption: `current_file`.
  - Button to open drawer.
- In `components.css`: Add drawer overlay, slide-in animation, stepper checklist styles, and terminal log styles.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- RepoListTable`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/GitRepoManager.tsx frontend/src/components/git/RepoListTable.tsx frontend/src/styles/components.css frontend/src/tests/RepoListTable.test.tsx
git commit -m "feat(frontend): integrate live progress bar and drawer triggers into RepoListTable"
```

---

### Task 6: End-to-End Playwright Validation & Final Verification

**Files:**
- Create: `frontend/e2e/git-sync-progress.spec.ts`

- [ ] **Step 1: Write Playwright E2E test**

```typescript
// frontend/e2e/git-sync-progress.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Git Sync Progress & Live Log Drawer', () => {
  test('displays real-time progress steps and opens live log drawer', async ({ page }) => {
    await page.goto('/');
    // Navigate to Git Repos tab
    await page.click('button:has-text("Git Repositories")');

    // Trigger sync on first repo
    const syncBtn = page.locator('button[title*="Sync"], button:has-text("Sync")').first();
    if (await syncBtn.isVisible()) {
      await syncBtn.click();
      // Verify step badge or progress bar appears
      const progressElement = page.locator('.progress-pill, .badge-warning, .badge-primary');
      await expect(progressElement.first()).toBeVisible({ timeout: 5000 });

      // Click to open drawer
      await progressElement.first().click();
      await expect(page.locator('.repo-sync-drawer')).toBeVisible();
      await expect(page.locator('.drawer-log-console')).toBeVisible();
    }
  });
});
```

- [ ] **Step 2: Run all backend tests**

Run: `pytest tests/backend/ -v`
Expected: PASS (All backend tests passing)

- [ ] **Step 3: Run all frontend unit and E2E tests**

Run: `cd frontend && npm test && npm run build`
Run: `cd frontend && npx playwright test`
Expected: PASS (All tests passing, zero layout overflow, clean compilation)

- [ ] **Step 4: Commit and push PR branch**

```bash
git add frontend/e2e/git-sync-progress.spec.ts
git commit -m "test(e2e): add Playwright validation for git sync progress and log drawer"
git push origin feat/git-sync-progress-visibility
```

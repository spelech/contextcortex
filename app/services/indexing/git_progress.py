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
            payload = self.jobs[repo_id].to_dict()
        self._broadcast({"type": "progress", "data": payload})
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

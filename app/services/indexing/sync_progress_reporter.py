"""Batch heartbeat monitoring, ETA formatting, slow-batch diagnostics, and timed sync summaries."""

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.embedding_batcher import telemetry_tracker

_repo_sync_locks: Dict[Tuple[str, int], threading.Lock] = {}
_active_sync_repos: Dict[Tuple[str, int], str] = {}
_repo_sync_locks_guard = threading.Lock()


def repo_sync_key(repo_id: int) -> Tuple[str, int]:
    try:
        from app.services.database.engine import get_db_url
        db_key = get_db_url()
    except Exception:
        db_key = "default"
    return (db_key, repo_id)


def get_repo_sync_lock(repo_id: int) -> threading.Lock:
    key = repo_sync_key(repo_id)
    with _repo_sync_locks_guard:
        if key not in _repo_sync_locks:
            _repo_sync_locks[key] = threading.Lock()
        return _repo_sync_locks[key]


def register_active_sync_repo(key: Tuple[str, int], repo_name: str) -> None:
    with _repo_sync_locks_guard:
        _active_sync_repos[key] = repo_name


def unregister_active_sync_repo(key: Tuple[str, int]) -> None:
    with _repo_sync_locks_guard:
        _active_sync_repos.pop(key, None)


def is_repo_sync_running(repo_id: int) -> bool:
    """Returns True if the per-repository sync lock is currently held."""
    return get_repo_sync_lock(repo_id).locked()


def has_active_repo_sync() -> bool:
    """Returns True if any repository sync lock is currently held."""
    with _repo_sync_locks_guard:
        return bool(_active_sync_repos) or any(lock.locked() for lock in _repo_sync_locks.values())


def get_active_sync_repos() -> List[str]:
    """Returns the names of repositories currently running a sync."""
    with _repo_sync_locks_guard:
        return sorted(_active_sync_repos.values())


def build_sync_completion_message(
    repo_name: str,
    commit_sha: Optional[str],
    sync_start: float,
    clone_seconds: float,
    ingest_start: float,
    embed_snap_start: Dict[str, Any],
    pipeline: Any,
    added_count: int,
    modified_count: int,
    deleted_count: int,
    total_vectors: int,
    total_symbols: int,
) -> str:
    """Computes telemetry deltas and formats the timed sync completion summary."""
    now = time.time()
    embed_snap_end = telemetry_tracker.get_telemetry_snapshot()
    new_embedded = max(0, int(embed_snap_end.get("chunks_embedded", 0)) - int(embed_snap_start.get("chunks_embedded", 0)))
    if new_embedded == 0 and getattr(pipeline, "chunks_newly_embedded", 0) > 0:
        new_embedded = int(pipeline.chunks_newly_embedded)
    embed_secs = max(0.0, float(embed_snap_end.get("embedding_seconds", 0.0)) - float(embed_snap_start.get("embedding_seconds", 0.0)))
    rl_hits = max(0, int(embed_snap_end.get("rate_limit_hits", 0)) - int(embed_snap_start.get("rate_limit_hits", 0)))
    return format_sync_completion_summary(
        repo_name=repo_name, commit_sha=commit_sha,
        total_seconds=now - sync_start, clone_seconds=clone_seconds,
        ingest_seconds=now - ingest_start, chunks_embedded=new_embedded,
        embedding_seconds=embed_secs, chunks_from_cache=int(getattr(pipeline, "chunks_from_cache", 0) or 0),
        rate_limit_hits=rl_hits, added_count=added_count,
        modified_count=modified_count, deleted_count=deleted_count,
        total_vectors=total_vectors, total_symbols=total_symbols,
    )


def format_duration(seconds: float) -> str:
    """Formats seconds into compact human-readable durations such as '45s', '17m03s', or '1h02m15s'."""
    total = max(0, int(round(seconds)))
    if total < 60:
        return f"{total}s"
    mins, secs = divmod(total, 60)
    if mins < 60:
        return f"{mins}m{secs:02d}s"
    hours, mins = divmod(mins, 60)
    return f"{hours}h{mins:02d}m{secs:02d}s"


def format_eta_suffix(eta_seconds: Optional[float]) -> str:
    """Formats an optional ETA value as ', ETA <dur>' for progress log lines."""
    if eta_seconds is None or eta_seconds < 1.0:
        return ""
    return f", ETA {format_duration(eta_seconds)}"


def compute_eta_seconds(processed: int, total: int, elapsed_seconds: float) -> Optional[float]:
    """Estimates remaining seconds from the current persist rate."""
    if processed <= 0 or total <= 0 or processed >= total or elapsed_seconds <= 0.0:
        return 0.0 if (total > 0 and processed >= total) else None
    rate = processed / elapsed_seconds
    if rate <= 0.0:
        return None
    return round((total - processed) / rate, 1)


def format_sync_completion_summary(
    repo_name: str,
    commit_sha: Optional[str],
    total_seconds: float,
    clone_seconds: float,
    ingest_seconds: float,
    chunks_embedded: int,
    embedding_seconds: float,
    chunks_from_cache: int,
    rate_limit_hits: int,
    added_count: int,
    modified_count: int,
    deleted_count: int,
    total_vectors: int,
    total_symbols: int,
) -> str:
    """Builds a timed, phase-broken-down completion summary for a repository sync."""
    sha_label = commit_sha[:8] if commit_sha else "head"
    rate = (chunks_embedded / embedding_seconds) if embedding_seconds > 0.0 else 0.0
    embed_part = (
        f"embedded {chunks_embedded:,} new chunks in {format_duration(embedding_seconds)} at {rate:.1f}/s"
        if chunks_embedded > 0
        else "embedded 0 new chunks"
    )
    rl_label = "wait" if rate_limit_hits == 1 else "waits"
    return (
        f"Successfully synced repo '{repo_name}' (@ {sha_label}) in {format_duration(total_seconds)} "
        f"(clone {format_duration(clone_seconds)}, parse+persist {format_duration(ingest_seconds)}; "
        f"{embed_part}, {chunks_from_cache:,} from cache; {rate_limit_hits} rate-limit {rl_label}). "
        f"Delta: +{added_count} ~{modified_count} -{deleted_count}. "
        f"Vectors: {total_vectors}, Symbols: {total_symbols}"
    )


class BatchProgressMonitor:
    """Emits periodic heartbeats during long batches and logs phase timings on slow batches."""

    def __init__(
        self,
        repo_id: int,
        batch_index: int,
        total_batches: int,
        file_start: int,
        file_end: int,
        items: Sequence[Any],
        log: logging.Logger,
        tracker: Any,
        heartbeat_interval: float = 15.0,
        slow_batch_threshold: float = 30.0,
    ) -> None:
        self.repo_id = repo_id
        self.batch_index = batch_index
        self.total_batches = max(1, total_batches)
        self.file_start = file_start
        self.file_end = file_end
        self.items = list(items)
        self.chunk_count = sum(len(getattr(it, "points", []) or []) for it in self.items)
        self.log = log
        self.tracker = tracker
        self.heartbeat_interval = max(0.05, float(heartbeat_interval))
        self.slow_batch_threshold = max(0.0, float(slow_batch_threshold))

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._start = time.monotonic()
        self._phase = "embedding"
        self._phase_start = self._start
        self._phase_times: Dict[str, float] = {}
        snap = telemetry_tracker.get_telemetry_snapshot()
        self._start_embed_sec = float(snap.get("embedding_seconds", 0.0) or 0.0)
        self._start_rl_wait = float(snap.get("rate_limit_wait_seconds", 0.0) or 0.0)
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"cc-batch-heartbeat-{repo_id}-{batch_index}",
            daemon=True,
        )
        self._thread.start()

    def set_phase(self, phase: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._phase_times[self._phase] = self._phase_times.get(self._phase, 0.0) + max(0.0, now - self._phase_start)
            self._phase = phase
            self._phase_start = now
        try:
            self.tracker.set_current_phase(self.repo_id, phase)
        except Exception:
            pass

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(timeout=self.heartbeat_interval):
            now = time.monotonic()
            with self._lock:
                elapsed = now - self._start
                phase = self._phase
                phase_elapsed = now - self._phase_start
            snap = telemetry_tracker.get_telemetry_snapshot()
            provider_wait = max(0.0, float(snap.get("embedding_seconds", 0.0) or 0.0) - self._start_embed_sec)
            rl_wait = max(0.0, float(snap.get("rate_limit_wait_seconds", 0.0) or 0.0) - self._start_rl_wait)
            extra = ""
            if phase == "embedding":
                wait_s = provider_wait if provider_wait >= 1.0 else phase_elapsed
                extra = f" (provider wait {int(round(wait_s))}s" + (f", rate-limit {int(round(rl_wait))}s" if rl_wait >= 1.0 else "") + ")"
            msg = (
                f"Batch {self.batch_index}/{self.total_batches} "
                f"(files {self.file_start}-{self.file_end}): {phase} {self.chunk_count} chunks, "
                f"{int(round(elapsed))}s so far{extra}"
            )
            self.log.info("%s", msg)
            try:
                self.tracker.log(self.repo_id, "INFO", msg)
            except Exception:
                pass

    def finish(self) -> float:
        self._stop_event.set()
        self._thread.join(timeout=1.0)
        now = time.monotonic()
        with self._lock:
            self._phase_times[self._phase] = self._phase_times.get(self._phase, 0.0) + max(0.0, now - self._phase_start)
            total_elapsed = now - self._start
            phases = dict(self._phase_times)

        if self.slow_batch_threshold > 0.0 and total_elapsed >= self.slow_batch_threshold:
            ranked_files = sorted(
                ((len(getattr(it, "points", []) or []), getattr(it, "rel_path", "") or getattr(it, "filepath", "")) for it in self.items),
                reverse=True,
            )[:3]
            largest_str = ", ".join(f"{fp} ({cnt} chunks)" for cnt, fp in ranked_files if cnt > 0) or "none"
            phase_str = ", ".join(f"{k} {v:.1f}s" for k, v in phases.items() if v >= 0.05) or f"total {total_elapsed:.1f}s"
            warn_msg = (
                f"Slow batch {self.batch_index}/{self.total_batches} "
                f"(files {self.file_start}-{self.file_end}) took {total_elapsed:.1f}s "
                f"({phase_str}); largest files: {largest_str}"
            )
            self.log.warning("%s", warn_msg)
            try:
                self.tracker.log(self.repo_id, "WARN", warn_msg)
            except Exception:
                pass
        return total_elapsed

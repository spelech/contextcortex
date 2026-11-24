"""Active repository sync status lookup for search and diagnostic MCP tools."""

from typing import Any, Dict, Optional

from app.services.indexing.git_progress import progress_tracker
from app.services.indexing.state import is_indexing


def get_active_sync_status(repo: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns sync progress metadata when the target repo (or any repo) is actively syncing, else None.

    Uses `index_status` and a nested `sync_progress` object so it never collides with tool-level
    fields such as `total`.
    """
    try:
        snapshot = progress_tracker.get_snapshot() or {}
    except Exception:
        snapshot = {}

    active_jobs = [
        job for job in snapshot.values()
        if isinstance(job, dict) and job.get("status") == "syncing"
    ]

    if repo:
        matching = [j for j in active_jobs if j.get("repo_name") == repo]
        if matching:
            job = matching[0]
            processed = int(job.get("processed_files") or 0)
            total = int(job.get("total_files") or 0)
            return {
                "index_status": "syncing",
                "sync_progress": {
                    "repo": repo,
                    "processed": processed,
                    "total": total,
                    "percent": int(job.get("percent") or 0),
                    "note": (
                        f"Repository '{repo}' is currently syncing ({processed}/{total} files); "
                        "results may be incomplete."
                    ),
                },
            }
        return None

    if active_jobs:
        if len(active_jobs) == 1:
            job = active_jobs[0]
            repo_name = job.get("repo_name") or "unknown"
            processed = int(job.get("processed_files") or 0)
            total = int(job.get("total_files") or 0)
            return {
                "index_status": "syncing",
                "sync_progress": {
                    "repo": repo_name,
                    "processed": processed,
                    "total": total,
                    "percent": int(job.get("percent") or 0),
                    "note": (
                        f"Repository '{repo_name}' is currently syncing ({processed}/{total} files); "
                        "results may be incomplete."
                    ),
                },
            }
        repos = sorted(str(j.get("repo_name") or "unknown") for j in active_jobs)
        processed = sum(int(j.get("processed_files") or 0) for j in active_jobs)
        total = sum(int(j.get("total_files") or 0) for j in active_jobs)
        return {
            "index_status": "syncing",
            "sync_progress": {
                "repos": repos,
                "processed": processed,
                "total": total,
                "note": (
                    f"Repositories {', '.join(repos)} are currently syncing ({processed}/{total} files); "
                    "results may be incomplete."
                ),
            },
        }

    if is_indexing():
        return {
            "index_status": "syncing",
            "sync_progress": {
                "note": "Indexing is currently in progress; results may be incomplete.",
            },
        }

    return None

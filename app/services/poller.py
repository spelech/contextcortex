import time
import logging
import threading
from typing import Tuple, Optional
from app.services.database import list_auto_sync_repos, get_auto_sync_interval, get_effective_git_token
from app.services.git_manager import get_remote_head_sha
import app.services.indexing as indexer
from app.services.indexing import sync_single_git_repo

logger = logging.getLogger("contextcortex.poller")

_poller_thread: Optional[threading.Thread] = None
_poller_stop_event = threading.Event()
is_indexing: bool = False

def check_all_auto_sync_repos() -> Tuple[int, int]:
    """Checks all auto_sync=1 repos for remote commit SHA changes."""
    if is_indexing or getattr(indexer, "is_indexing", False):
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
        per_repo_token = r.get("auth_token")
        per_repo_user = r.get("auth_user")

        eff_token, eff_user, _ = get_effective_git_token(
            git_url,
            override_token=per_repo_token,
            override_user=per_repo_user,
            provider=provider
        )

        try:
            remote_sha = get_remote_head_sha(git_url, branch, token=eff_token, username=eff_user, provider=provider)
            if remote_sha is not None:
                checked += 1
                if remote_sha != current_sha:
                    logger.info(f"Poller detected update for repo '{repo_name}' ({current_sha} -> {remote_sha}). Triggering sync.")
                    sync_single_git_repo(repo_id)
                    updated += 1
        except Exception as e:
            logger.error(f"Poller error checking repo '{repo_name}': {e}")

    logger.info(f"Poller check complete: {checked} checked, {updated} updated.")
    return (checked, updated)

def trigger_poller_check_now() -> Tuple[int, int]:
    """Manually triggers an immediate check of all auto-sync repositories."""
    return check_all_auto_sync_repos()

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
    if _poller_thread and _poller_thread.is_alive() and not _poller_stop_event.is_set():
        return
    _poller_stop_event.clear()
    _poller_thread = threading.Thread(target=_poller_worker, daemon=True, name="GitRepoPoller")
    _poller_thread.start()

def stop_poller_daemon():
    global _poller_thread
    _poller_stop_event.set()
    _poller_thread = None

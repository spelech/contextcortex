import logging
from typing import Optional, List, Dict, Any
from app.services.database.connection import get_db_connection, get_metadata, set_metadata

logger = logging.getLogger("contextcortex.db")

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
        rows = conn.execute("SELECT id, name, url, branch, commit_sha, auth_token, auth_user, provider, auto_sync, webhook_secret FROM git_repositories WHERE auto_sync = 1").fetchall()
        return [dict(r) for r in rows]

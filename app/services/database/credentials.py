import os
import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from app.services.database.connection import get_db_connection, get_metadata

logger = logging.getLogger("contextcortex.db")

def list_git_host_credentials() -> List[Dict[str, Any]]:
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM git_host_credentials ORDER BY host ASC").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to list git host credentials: {e}")
        return []

def get_git_host_credential(host: str) -> Optional[Dict[str, Any]]:
    if not host:
        return None
    try:
        clean = host.strip().lower()
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM git_host_credentials WHERE host = ?", (clean,)).fetchone()
            return dict(row) if row else None
    except Exception:
        return None

def save_git_host_credential(host: str, provider: str, auth_token: str, auth_user: Optional[str] = None):
    try:
        clean_host = host.strip().lower()
        clean_host = re.sub(r"^https?://", "", clean_host).split("/")[0]
        with get_db_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO git_host_credentials (host, provider, auth_user, auth_token)
                   VALUES (?, ?, ?, ?)""",
                (clean_host, provider.lower().strip(), auth_user.strip() if auth_user else None, auth_token.strip())
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to save git host credential for {host}: {e}")
        raise

def delete_git_host_credential(id_or_host: Any):
    try:
        with get_db_connection() as conn:
            if isinstance(id_or_host, int) or (isinstance(id_or_host, str) and id_or_host.isdigit()):
                conn.execute("DELETE FROM git_host_credentials WHERE id = ?", (int(id_or_host),))
            else:
                clean_host = str(id_or_host).strip().lower()
                clean_host = re.sub(r"^https?://", "", clean_host).split("/")[0]
                conn.execute("DELETE FROM git_host_credentials WHERE host = ?", (clean_host,))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to delete git host credential {id_or_host}: {e}")
        raise

def extract_host_from_url(url: str) -> str:
    if not url:
        return ""
    clean = re.sub(r"^(git@|https?://)", "", url.strip())
    if ":" in clean and "/" not in clean.split(":")[0]:
        host_part = clean.split(":")[0]
    else:
        host_part = clean.split("/")[0]
    return host_part.lower()

def get_effective_git_token(
    git_url: str, 
    override_token: Optional[str] = None, 
    override_user: Optional[str] = None,
    provider: Optional[str] = None
) -> Tuple[Optional[str], Optional[str], str]:
    if override_token and override_token.strip():
        return override_token.strip(), override_user.strip() if override_user else None, "Repository Override"
    
    host = extract_host_from_url(git_url)
    if host:
        host_cred = get_git_host_credential(host)
        if host_cred and host_cred.get("auth_token"):
            return host_cred["auth_token"], host_cred.get("auth_user"), f"Host Vault ({host})"

    prov = (provider or "").lower()
    if not prov:
        if "gitlab" in host:
            prov = "gitlab"
        elif "gitea" in host or "forgejo" in host:
            prov = "gitea"
        elif "bitbucket" in host:
            prov = "bitbucket"
        elif "github" in host:
            prov = "github"
        else:
            prov = "generic"

    db_token = get_metadata(f"{prov}_token") or (get_metadata("github_token") if prov == "github" else None)
    if db_token and db_token.strip():
        return db_token.strip(), override_user, f"Database ({prov.capitalize()})"

    env_keys = {
        "github": ["GITHUB_TOKEN", "GH_TOKEN"],
        "gitlab": ["GITLAB_TOKEN", "GL_TOKEN"],
        "gitea": ["GITEA_TOKEN", "FORGEJO_TOKEN"],
        "bitbucket": ["BITBUCKET_TOKEN", "BITBUCKET_APP_PASSWORD"]
    }.get(prov, [])

    for k in env_keys:
        val = os.getenv(k)
        if val and val.strip():
            return val.strip(), override_user, f"Environment Variable ({k})"

    return None, override_user, "None"

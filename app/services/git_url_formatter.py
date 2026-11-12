import logging
import os
import re
import sys
import urllib.parse
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("contextcortex.git")


def get_env_token() -> Optional[str]:
    """Retrieve GitHub token from environment variables."""
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    return token.strip() if token else None


def is_ssh_git_url(url: str) -> bool:
    """Returns True if the git URL is an SSH URL (git@host:path or ssh://...)."""
    if not url:
        return False
    u = url.strip()
    return bool(re.match(r"^git@[^:]+:.+$", u) or u.startswith("ssh://"))


def normalize_git_url(url: str) -> str:
    """Normalizes SSH git URLs (e.g. git@github.com:owner/repo.git) to standard HTTPS URLs."""
    if not url:
        return ""
    url = url.strip()
    ssh_match = re.match(r"^git@([^:]+):(.+)$", url)
    if ssh_match:
        host, path = ssh_match.groups()
        return f"https://{host}/{path}"
    if url.startswith("ssh://"):
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path.lstrip("/")
        if host and path:
            return f"https://{host}/{path}"
    return url


def detect_git_provider(url: str, explicit_provider: Optional[str] = None) -> str:
    """Detects git provider type (github, gitlab, gitea, bitbucket, generic)."""
    ep = explicit_provider.strip().lower() if (explicit_provider and explicit_provider.strip()) else ""
    if ep in ("gitlab", "gitea", "bitbucket", "generic"):
        return ep
    if ep == "github":
        norm_check = normalize_git_url(url).lower() if url else ""
        if "gitlab" in norm_check or "/-/" in norm_check:
            return "gitlab"
        if "gitea" in norm_check or "forgejo" in norm_check:
            return "gitea"
        if "bitbucket" in norm_check:
            return "bitbucket"
        if url and "github" not in norm_check:
            try:
                from app.services.database import extract_host_from_url, get_git_host_credential
                host = extract_host_from_url(norm_check or url)
                if host:
                    cred = get_git_host_credential(host)
                    if cred and cred.get("provider"):
                        cred_prov = str(cred["provider"]).strip().lower()
                        if cred_prov in ("gitlab", "gitea", "bitbucket", "generic"):
                            return cred_prov
            except Exception:
                pass
        return "github"

    norm = normalize_git_url(url).lower() if url else ""
    if "gitlab" in norm or "/-/" in norm:
        return "gitlab"
    if "gitea" in norm or "forgejo" in norm:
        return "gitea"
    if "bitbucket" in norm:
        return "bitbucket"
    if "github" in norm:
        return "github"

    if url:
        try:
            from app.services.database import extract_host_from_url, get_git_host_credential
            host = extract_host_from_url(norm or url)
            if host:
                cred = get_git_host_credential(host)
                if cred and cred.get("provider"):
                    cred_prov = str(cred["provider"]).strip().lower()
                    if cred_prov in ("github", "gitlab", "gitea", "bitbucket", "generic"):
                        return cred_prov
        except Exception:
            pass

    return "generic"


def mask_token(token: Optional[str]) -> str:
    """Mask token for secure UI and logging display."""
    if not token:
        return "None"
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}...{token[-4:]}"


def build_authenticated_url(
    git_url: str,
    token: Optional[str],
    username: Optional[str] = None,
    provider: Optional[str] = None,
) -> str:
    """Injects token/credentials into HTTP(S) git URL based on provider type, or preserves SSH URL if no HTTP credentials are provided."""
    if is_ssh_git_url(git_url) and not token and not username:
        return git_url.strip()
    clean_url = normalize_git_url(git_url)
    if not token and not username:
        return clean_url
    if not (clean_url.startswith("https://") or clean_url.startswith("http://")):
        return clean_url

    scheme = "https://" if clean_url.startswith("https://") else "http://"
    no_scheme = clean_url[len(scheme):]
    clean_no_cred = re.sub(r"^[^@]+@", "", no_scheme)

    prov = detect_git_provider(clean_url, provider)
    encoded_token = urllib.parse.quote(token.strip(), safe="") if token else ""
    encoded_user = urllib.parse.quote(username.strip(), safe="") if username else ""

    if prov == "github":
        auth_part = f"x-access-token:{encoded_token}@" if encoded_token else f"{encoded_user}@"
    elif prov == "gitlab":
        user_part = encoded_user or "oauth2"
        auth_part = f"{user_part}:{encoded_token}@" if encoded_token else f"{encoded_user}@"
    elif prov == "gitea":
        user_part = encoded_user or "oauth2"
        auth_part = (
            f"{user_part}:{encoded_token}@"
            if (encoded_user and encoded_token)
            else (f"{encoded_token}@" if encoded_token else f"{encoded_user}@")
        )
    elif prov == "bitbucket":
        user_part = encoded_user or "x-token-auth"
        auth_part = f"{user_part}:{encoded_token}@" if encoded_token else f"{encoded_user}@"
    else:
        if encoded_user and encoded_token:
            auth_part = f"{encoded_user}:{encoded_token}@"
        elif encoded_token:
            auth_part = f"{encoded_token}@"
        elif encoded_user:
            auth_part = f"{encoded_user}@"
        else:
            auth_part = ""

    return f"{scheme}{auth_part}{clean_no_cred}"


def sanitize_url_for_logging(url: str) -> str:
    """Removes tokens/passwords from URL before logging."""
    if not url:
        return ""
    return re.sub(r"(https?://)[^/@]+@", r"\1***", url)


def format_git_commit_url(
    git_url: str,
    commit_sha: str,
    provider: Optional[str] = None,
) -> Optional[str]:
    """Constructs a clickable web URL for a commit (GitHub, GitLab, Gitea, Bitbucket)."""
    if not git_url or not commit_sha:
        return None
    base = normalize_git_url(git_url).rstrip("/")
    if base.endswith(".git"):
        base = base[:-4]

    prov = detect_git_provider(base, provider)
    if prov == "gitlab":
        return f"{base}/-/commit/{commit_sha}"
    if prov == "bitbucket":
        return f"{base}/commits/{commit_sha}"
    return f"{base}/commit/{commit_sha}"


def format_git_permalink(
    git_url: str,
    commit_sha: Optional[str],
    rel_path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    provider: Optional[str] = None,
) -> Optional[str]:
    """Constructs a clickable web permalink for any git provider (GitHub, GitLab, Gitea, Bitbucket, Generic)."""
    if not git_url:
        return None
    base = normalize_git_url(git_url).rstrip("/")
    if base.endswith(".git"):
        base = base[:-4]

    prov = detect_git_provider(base, provider)
    ref = commit_sha or "main"
    raw_rel = rel_path.split("://", 1)[1] if (rel_path and "://" in rel_path) else (rel_path or "")
    clean_rel = raw_rel.replace("\\", "/").lstrip("/")

    if prov == "gitlab":
        url = f"{base}/-/blob/{ref}/{clean_rel}"
        if start_line is not None:
            url += f"#L{start_line}-{end_line}" if (end_line is not None and end_line > start_line) else f"#L{start_line}"
        return url
    if prov == "gitea":
        url = f"{base}/src/commit/{ref}/{clean_rel}" if commit_sha else f"{base}/src/branch/{ref}/{clean_rel}"
        if start_line is not None:
            url += f"#L{start_line}-L{end_line}" if (end_line is not None and end_line > start_line) else f"#L{start_line}"
        return url
    if prov == "bitbucket":
        url = f"{base}/src/{ref}/{clean_rel}"
        if start_line is not None:
            url += f"#lines-{start_line}:{end_line}" if (end_line is not None and end_line > start_line) else f"#lines-{start_line}"
        return url

    url = f"{base}/blob/{ref}/{clean_rel}"
    if start_line is not None:
        url += f"#L{start_line}-L{end_line}" if (end_line is not None and end_line > start_line) else f"#L{start_line}"
    return url


def check_github_rate_limit(token: Optional[str] = None) -> Dict[str, Any]:
    """Queries GitHub API for rate limit status."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    gm_mod = sys.modules.get("app.services.git_manager")
    req_mod = getattr(gm_mod, "requests", requests) if gm_mod else requests
    try:
        resp = req_mod.get("https://api.github.com/rate_limit", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            core = data.get("resources", {}).get("core", {})
            return {
                "authenticated": bool(token),
                "limit": core.get("limit", 60),
                "remaining": core.get("remaining", 0),
                "reset_timestamp": core.get("reset", 0),
            }
        return {"authenticated": bool(token), "status": f"HTTP {resp.status_code}"}
    except Exception as e:
        logger.error(f"Error checking GitHub rate limit: {e}")
        return {"authenticated": bool(token), "error": "Unable to verify rate limit."}

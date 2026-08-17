import os
import re
import shutil
import tempfile
import logging
import subprocess
from typing import Optional, Dict, Any, Tuple
import requests
from app.models.schemas import CloneResult

logger = logging.getLogger("notes-rag-mcp.git")

TMP_BASE_DIR = os.getenv("TMP_REPOS_DIR", "/tmp/rag_repos")

def get_env_token() -> Optional[str]:
    """Retrieve GitHub token from environment variables."""
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    return token.strip() if token else None

import urllib.parse

def normalize_git_url(url: str) -> str:
    """Normalizes SSH git URLs (e.g. git@github.com:owner/repo.git) to standard HTTPS URLs."""
    if not url:
        return ""
    url = url.strip()
    ssh_match = re.match(r"^git@([^:]+):(.+)$", url)
    if ssh_match:
        host, path = ssh_match.groups()
        return f"https://{host}/{path}"
    return url

def detect_git_provider(url: str, explicit_provider: Optional[str] = None) -> str:
    """Detects git provider type (github, gitlab, gitea, bitbucket, generic)."""
    if explicit_provider and explicit_provider.strip():
        ep = explicit_provider.strip().lower()
        if ep in ("github", "gitlab", "gitea", "bitbucket", "generic"):
            return ep
    if not url:
        return "generic"
    norm = normalize_git_url(url).lower()
    if "gitlab" in norm:
        return "gitlab"
    if "gitea" in norm or "forgejo" in norm:
        return "gitea"
    if "bitbucket" in norm:
        return "bitbucket"
    if "github" in norm:
        return "github"
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
    provider: Optional[str] = None
) -> str:
    """Injects token/credentials into HTTP(S) git URL based on provider type."""
    clean_url = normalize_git_url(git_url)
    if not token and not username:
        return clean_url
    if not (clean_url.startswith("https://") or clean_url.startswith("http://")):
        return clean_url

    # Strip existing credentials if present
    scheme = "https://" if clean_url.startswith("https://") else "http://"
    no_scheme = clean_url[len(scheme):]
    clean_no_cred = re.sub(r"^[^@]+@", "", no_scheme)

    prov = detect_git_provider(clean_url, provider)
    encoded_token = urllib.parse.quote(token.strip(), safe='') if token else ""
    encoded_user = urllib.parse.quote(username.strip(), safe='') if username else ""

    if prov == "github":
        auth_part = f"x-access-token:{encoded_token}@" if encoded_token else f"{encoded_user}@"
    elif prov == "gitlab":
        user_part = encoded_user or "oauth2"
        auth_part = f"{user_part}:{encoded_token}@" if encoded_token else f"{encoded_user}@"
    elif prov == "gitea":
        user_part = encoded_user or "oauth2"
        auth_part = f"{user_part}:{encoded_token}@" if (encoded_user and encoded_token) else (f"{encoded_token}@" if encoded_token else f"{encoded_user}@")
    elif prov == "bitbucket":
        user_part = encoded_user or "x-token-auth"
        auth_part = f"{user_part}:{encoded_token}@" if encoded_token else f"{encoded_user}@"
    else:  # Generic Git
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
    # Matches http(s)://user:pass@host or http(s)://token@host -> http(s)://***host
    return re.sub(r"(https?://)[^/@]+@", r"\1***", url)

GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": ""
}

def get_remote_head_sha(
    git_url: str, 
    branch: str = "main", 
    token: Optional[str] = None,
    username: Optional[str] = None,
    provider: Optional[str] = None
) -> Optional[str]:
    """
    Checks remote repository commit SHA for a branch without cloning using git ls-remote.
    """
    from app.services.db import get_effective_git_token
    norm_url = normalize_git_url(git_url)
    
    if not token and not username:
        eff_token, eff_user, _ = get_effective_git_token(norm_url, provider=provider)
        token = token or eff_token
        username = username or eff_user

    auth_url = build_authenticated_url(norm_url, token, username=username, provider=provider)
    try:
        cmd = ["git", "ls-remote", auth_url, f"refs/heads/{branch}", f"refs/tags/{branch}", branch]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=GIT_ENV)
        if result.returncode == 0 and result.stdout.strip():
            first_line = result.stdout.strip().splitlines()[0]
            sha = first_line.split()[0]
            return sha
        # If specific ref not matched, try HEAD
        cmd_head = ["git", "ls-remote", auth_url, "HEAD"]
        res_head = subprocess.run(cmd_head, capture_output=True, text=True, timeout=20, env=GIT_ENV)
        if res_head.returncode == 0 and res_head.stdout.strip():
            return res_head.stdout.strip().splitlines()[0].split()[0]
    except Exception as e:
        logger.error(f"Error checking remote SHA for {sanitize_url_for_logging(norm_url)}: {e}")
    return None

def shallow_clone_repo(
    git_url: str, 
    branch: str = "main", 
    token: Optional[str] = None,
    username: Optional[str] = None,
    provider: Optional[str] = None,
    repo_id: Optional[str] = None
) -> CloneResult:
    """
    Shallow clones a git repository to a temporary directory.
    Returns: CloneResult
    """
    from app.services.db import get_effective_git_token
    norm_url = normalize_git_url(git_url)
    os.makedirs(TMP_BASE_DIR, exist_ok=True)
    repo_dir = tempfile.mkdtemp(prefix=f"repo_{repo_id or 'temp'}_", dir=TMP_BASE_DIR)

    if not token and not username:
        eff_token, eff_user, _ = get_effective_git_token(norm_url, provider=provider)
        token = token or eff_token
        username = username or eff_user

    auth_url = build_authenticated_url(norm_url, token, username=username, provider=provider)
    safe_url = sanitize_url_for_logging(auth_url)

    logger.info(f"Cloning {safe_url} (branch: {branch}) shallowly to {repo_dir}...")
    try:
        # Shallow clone single branch
        cmd = [
            "git", "clone",
            "--depth", "1",
            "--branch", branch,
            "--single-branch",
            auth_url,
            repo_dir
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=GIT_ENV)
        if res.returncode != 0:
            # Fallback to default clone if branch failed (e.g. branch is default)
            cmd_fallback = ["git", "clone", "--depth", "1", auth_url, repo_dir]
            res = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=120, env=GIT_ENV)
            if res.returncode != 0:
                err_msg = res.stderr.strip() or res.stdout.strip() or "Git clone failed"
                cleanup_repo_dir(repo_dir)
                return CloneResult(temp_dir=None, commit_sha=None, error=f"Clone failed: {err_msg}")

        # Get Commit SHA
        sha_res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, timeout=10, env=GIT_ENV)
        commit_sha = sha_res.stdout.strip() if sha_res.returncode == 0 else "unknown"

        return CloneResult(temp_dir=repo_dir, commit_sha=commit_sha, error=None)
    except Exception as e:
        cleanup_repo_dir(repo_dir)
        return CloneResult(temp_dir=None, commit_sha=None, error=f"Exception during git clone: {str(e)}")

def cleanup_repo_dir(repo_dir: Optional[str]):
    """Safely removes cloned temporary directory from disk."""
    if repo_dir and os.path.exists(repo_dir):
        try:
            shutil.rmtree(repo_dir, ignore_errors=True)
            logger.info(f"Cleaned up temporary repo directory: {repo_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp directory {repo_dir}: {e}")

def format_git_permalink(
    git_url: str, 
    commit_sha: Optional[str], 
    rel_path: str, 
    start_line: Optional[int] = None, 
    end_line: Optional[int] = None,
    provider: Optional[str] = None
) -> Optional[str]:
    """Constructs a clickable web permalink for any git provider (GitHub, GitLab, Gitea, Bitbucket, Generic)."""
    if not git_url:
        return None
    # Normalize git url (strip .git)
    base = normalize_git_url(git_url).rstrip("/")
    if base.endswith(".git"):
        base = base[:-4]
    
    prov = detect_git_provider(base, provider)
    ref = commit_sha or "main"
    clean_rel = rel_path.lstrip("/")

    if prov == "gitlab":
        # GitLab format: base/-/blob/{ref}/{path}#L{start}-L{end}
        url = f"{base}/-/blob/{ref}/{clean_rel}"
        if start_line is not None:
            if end_line is not None and end_line > start_line:
                url += f"#L{start_line}-{end_line}"
            else:
                url += f"#L{start_line}"
        return url
    elif prov == "gitea":
        # Gitea/Forgejo format: base/src/branch/{ref}/{path}#L{start}-L{end}
        url = f"{base}/src/commit/{ref}/{clean_rel}" if commit_sha else f"{base}/src/branch/{ref}/{clean_rel}"
        if start_line is not None:
            if end_line is not None and end_line > start_line:
                url += f"#L{start_line}-L{end_line}"
            else:
                url += f"#L{start_line}"
        return url
    elif prov == "bitbucket":
        # Bitbucket format: base/src/{ref}/{path}#lines-{start}:{end}
        url = f"{base}/src/{ref}/{clean_rel}"
        if start_line is not None:
            if end_line is not None and end_line > start_line:
                url += f"#lines-{start_line}:{end_line}"
            else:
                url += f"#lines-{start_line}"
        return url
    else:
        # GitHub and standard Git format: base/blob/{ref}/{path}#L{start}-L{end}
        url = f"{base}/blob/{ref}/{clean_rel}"
        if start_line is not None:
            if end_line is not None and end_line > start_line:
                url += f"#L{start_line}-L{end_line}"
            else:
                url += f"#L{start_line}"
        return url

# Backwards compatible alias
format_github_permalink = format_git_permalink

def check_github_rate_limit(token: Optional[str] = None) -> Dict[str, Any]:
    """Queries GitHub API for rate limit status."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        
    try:
        resp = requests.get("https://api.github.com/rate_limit", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            core = data.get("resources", {}).get("core", {})
            return {
                "authenticated": bool(token),
                "limit": core.get("limit", 60),
                "remaining": core.get("remaining", 0),
                "reset_timestamp": core.get("reset", 0)
            }
        return {"authenticated": bool(token), "status": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"authenticated": bool(token), "error": str(e)}


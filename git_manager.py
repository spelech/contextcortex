import os
import re
import shutil
import tempfile
import logging
import subprocess
from typing import Optional, Dict, Any, Tuple
import requests

logger = logging.getLogger("notes-rag-mcp.git")

TMP_BASE_DIR = os.getenv("TMP_REPOS_DIR", "/tmp/rag_repos")

def get_env_token() -> Optional[str]:
    """Retrieve GitHub token from environment variables."""
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    return token.strip() if token else None

def mask_token(token: Optional[str]) -> str:
    """Mask token for secure UI and logging display."""
    if not token:
        return "None"
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}...{token[-4:]}"

def build_authenticated_url(git_url: str, token: Optional[str]) -> str:
    """Injects token into HTTPS git URL for private repo access."""
    if not token or not git_url.startswith("https://"):
        return git_url
    # Strip existing credentials if present
    clean_url = re.sub(r"https://[^@]+@", "https://", git_url)
    return clean_url.replace("https://", f"https://x-access-token:{token}@")

def sanitize_url_for_logging(url: str) -> str:
    """Removes tokens from URL before logging."""
    return re.sub(r"https://x-access-token:[^@]+@", "https://***", url)

def get_remote_head_sha(git_url: str, branch: str = "main", token: Optional[str] = None) -> Optional[str]:
    """
    Checks remote repository commit SHA for a branch without cloning using git ls-remote.
    """
    auth_url = build_authenticated_url(git_url, token)
    try:
        cmd = ["git", "ls-remote", auth_url, f"refs/heads/{branch}", f"refs/tags/{branch}", branch]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode == 0 and result.stdout.strip():
            first_line = result.stdout.strip().splitlines()[0]
            sha = first_line.split()[0]
            return sha
        # If specific ref not matched, try HEAD
        cmd_head = ["git", "ls-remote", auth_url, "HEAD"]
        res_head = subprocess.run(cmd_head, capture_output=True, text=True, timeout=20)
        if res_head.returncode == 0 and res_head.stdout.strip():
            return res_head.stdout.strip().splitlines()[0].split()[0]
    except Exception as e:
        logger.error(f"Error checking remote SHA for {sanitize_url_for_logging(git_url)}: {e}")
    return None

def shallow_clone_repo(
    git_url: str, 
    branch: str = "main", 
    token: Optional[str] = None,
    repo_id: Optional[str] = None
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Shallow clones a git repository to a temporary directory.
    Returns: (temp_dir_path, commit_sha, error_message)
    """
    os.makedirs(TMP_BASE_DIR, exist_ok=True)
    repo_dir = tempfile.mkdtemp(prefix=f"repo_{repo_id or 'temp'}_", dir=TMP_BASE_DIR)
    auth_url = build_authenticated_url(git_url, token)
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
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            # Fallback to default clone if branch failed (e.g. branch is default)
            cmd_fallback = ["git", "clone", "--depth", "1", auth_url, repo_dir]
            res = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=120)
            if res.returncode != 0:
                err_msg = res.stderr.strip() or res.stdout.strip() or "Git clone failed"
                cleanup_repo_dir(repo_dir)
                return None, None, f"Clone failed: {err_msg}"

        # Get Commit SHA
        sha_res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, timeout=10)
        commit_sha = sha_res.stdout.strip() if sha_res.returncode == 0 else "unknown"

        return repo_dir, commit_sha, None
    except Exception as e:
        cleanup_repo_dir(repo_dir)
        return None, None, f"Exception during git clone: {str(e)}"

def cleanup_repo_dir(repo_dir: Optional[str]):
    """Safely removes cloned temporary directory from disk."""
    if repo_dir and os.path.exists(repo_dir):
        try:
            shutil.rmtree(repo_dir, ignore_errors=True)
            logger.info(f"Cleaned up temporary repo directory: {repo_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp directory {repo_dir}: {e}")

def format_github_permalink(
    git_url: str, 
    commit_sha: Optional[str], 
    rel_path: str, 
    start_line: Optional[int] = None, 
    end_line: Optional[int] = None
) -> Optional[str]:
    """Constructs a clickable GitHub blob permalink."""
    if not git_url:
        return None
    # Normalize github url (strip .git)
    base = git_url.rstrip("/")
    if base.endswith(".git"):
        base = base[:-4]
    
    if "github.com" not in base and "gitlab.com" not in base:
        return None

    ref = commit_sha or "main"
    clean_rel = rel_path.lstrip("/")
    
    url = f"{base}/blob/{ref}/{clean_rel}"
    if start_line is not None:
        if end_line is not None and end_line > start_line:
            url += f"#L{start_line}-L{end_line}"
        else:
            url += f"#L{start_line}"
    return url

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

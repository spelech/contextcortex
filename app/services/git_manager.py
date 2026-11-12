import os
import re
import shutil
import tempfile
import logging
import subprocess
from typing import Optional, Dict, Any, Tuple
import requests
from app.models.schemas import CloneResult

logger = logging.getLogger("contextcortex.git")

TMP_BASE_DIR = os.getenv("TMP_REPOS_DIR", "/tmp/rag_repos")
DATA_DIR = os.getenv(
    "DATA_DIR",
    "/app/data" if os.path.exists("/app/data") else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
)
PERSISTENT_REPOS_DIR = os.getenv("PERSISTENT_REPOS_DIR", os.path.join(DATA_DIR, "repos"))

def get_persistent_repo_dir(repo_name: str) -> str:
    """Returns absolute path for persistent shallow repository clone."""
    if not repo_name or not isinstance(repo_name, str):
        raise ValueError("Invalid repo_name")
    safe_name = os.path.basename(repo_name.strip())
    if not safe_name or safe_name in (".", ".."):
        raise ValueError("Invalid repo_name")
    base_dir = os.path.realpath(PERSISTENT_REPOS_DIR)
    resolved = os.path.realpath(os.path.join(base_dir, safe_name))
    base_prefix = base_dir if base_dir.endswith(os.sep) else base_dir + os.sep
    if not (resolved.startswith(base_prefix) or resolved == base_dir):
        raise ValueError(f"Path traversal detected in repo_name: {repo_name}")
    return resolved

def cleanup_persistent_repo(repo_name: str) -> None:
    """Safely removes persistent shallow clone for a deleted repo."""
    target = get_persistent_repo_dir(repo_name)
    cleanup_repo_dir(target)

def get_env_token() -> Optional[str]:
    """Retrieve GitHub token from environment variables."""
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    return token.strip() if token else None

import urllib.parse

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
        # Check if URL or saved host credential clearly points to a non-GitHub host
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

    # If URL host has a saved credential in git_host_credentials, honor its provider
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
    provider: Optional[str] = None
) -> str:
    """Injects token/credentials into HTTP(S) git URL based on provider type, or preserves SSH URL if no HTTP credentials are provided."""
    if is_ssh_git_url(git_url) and not token and not username:
        return git_url.strip()
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

_STRIP_GIT_ENV_VARS = {
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
    "GIT_PREFIX",
}

GIT_ENV = {
    **{k: v for k, v in os.environ.items() if k not in _STRIP_GIT_ENV_VARS},
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "GIT_CONFIG_PARAMETERS": "'http.https://github.com/.extraheader='",
}

def _get_git_env() -> Dict[str, str]:
    """Builds a sanitized Git subprocess environment without inherited GIT_DIR/GIT_WORK_TREE overrides."""
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_GIT_ENV_VARS}
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
        "GIT_CONFIG_PARAMETERS": "'http.https://github.com/.extraheader='",
    })
    return env

def is_valid_git_repo(repo_dir: Optional[str]) -> bool:
    """Returns True if repo_dir contains a valid, non-corrupted .git repository with HEAD."""
    if not repo_dir or not os.path.isdir(repo_dir):
        return False
    dot_git = os.path.join(repo_dir, ".git")
    if not os.path.exists(dot_git):
        return False
    if os.path.isdir(dot_git) and not os.path.exists(os.path.join(dot_git, "HEAD")):
        return False
    try:
        safe_dir = repo_dir.replace("\\", "/")
        res = subprocess.run(
            ["git", "-C", repo_dir, "-c", f"safe.directory={safe_dir}", "rev-parse", "--git-dir"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=10,
            env=_get_git_env(),
        )
        return res.returncode == 0
    except Exception:
        return os.path.exists(os.path.join(dot_git, "HEAD"))

def get_remote_head_sha(
    git_url: str, 
    branch: str = "main", 
    token: Optional[str] = None,
    username: Optional[str] = None,
    provider: Optional[str] = None
) -> Optional[str]:
    """
    Checks remote repository commit SHA for a branch without cloning using git ls-remote.
    Preserves native SSH URLs when no HTTP token is configured so user SSH keys work seamlessly.
    """
    from app.services.database import get_effective_git_token
    norm_url = normalize_git_url(git_url)
    use_ssh_native = is_ssh_git_url(git_url) and not token and not username

    if not use_ssh_native and not token and not username:
        eff_token, eff_user, _ = get_effective_git_token(norm_url, provider=provider)
        token = token or eff_token
        username = username or eff_user

    target_url = git_url.strip() if (is_ssh_git_url(git_url) and not token and not username) else norm_url
    auth_url = build_authenticated_url(target_url, token, username=username, provider=provider)
    git_env = _get_git_env()
    try:
        cmd = ["git", "ls-remote", auth_url, f"refs/heads/{branch}", f"refs/tags/{branch}", branch]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=git_env)
        if result.returncode == 0 and result.stdout.strip():
            first_line = result.stdout.strip().splitlines()[0]
            sha = first_line.split()[0]
            return sha
        # If specific ref not matched, try HEAD
        cmd_head = ["git", "ls-remote", auth_url, "HEAD"]
        res_head = subprocess.run(cmd_head, capture_output=True, text=True, timeout=20, env=git_env)
        if res_head.returncode == 0 and res_head.stdout.strip():
            return res_head.stdout.strip().splitlines()[0].split()[0]
    except Exception as e:
        logger.error(f"Error checking remote SHA for {sanitize_url_for_logging(auth_url)}: {e}")
    return None

def _clone_fresh_into_dir(auth_url: str, branch: str, depth_str: str, dest_dir: str, git_env: Dict[str, str]) -> subprocess.CompletedProcess:
    """Clones a repository shallowly into dest_dir, falling back to default branch if --branch fails."""
    if os.path.exists(dest_dir) and os.listdir(dest_dir):
        cleanup_repo_dir(dest_dir)
    cmd = [
        "git", "clone",
        "--depth", depth_str,
        "--branch", branch,
        "--single-branch",
        auth_url,
        dest_dir,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=git_env)
    if res.returncode != 0:
        if os.path.exists(dest_dir) and os.listdir(dest_dir):
            cleanup_repo_dir(dest_dir)
        cmd_fallback = ["git", "clone", "--depth", depth_str, auth_url, dest_dir]
        res = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=120, env=git_env)
    return res

def shallow_clone_repo(
    git_url: str, 
    branch: str = "main", 
    token: Optional[str] = None,
    username: Optional[str] = None,
    provider: Optional[str] = None,
    repo_id: Optional[str] = None,
    target_dir: Optional[str] = None,
    depth: int = 1
) -> CloneResult:
    """
    Shallow clones a git repository to a temporary or persistent directory.
    Preserves native SSH URLs when no HTTP token is configured so user SSH keys work seamlessly.
    Returns: CloneResult
    """
    import time
    from app.services.database import get_effective_git_token
    norm_url = normalize_git_url(git_url)
    use_ssh_native = is_ssh_git_url(git_url) and not token and not username
    depth_str = str(max(1, depth))

    if target_dir:
        os.makedirs(os.path.dirname(os.path.abspath(target_dir)), exist_ok=True)
        repo_dir = os.path.abspath(target_dir)
    else:
        os.makedirs(TMP_BASE_DIR, exist_ok=True)
        repo_dir = tempfile.mkdtemp(prefix=f"repo_{repo_id or 'temp'}_", dir=TMP_BASE_DIR)

    if not use_ssh_native and not token and not username:
        eff_token, eff_user, _ = get_effective_git_token(norm_url, provider=provider)
        token = token or eff_token
        username = username or eff_user

    target_url = git_url.strip() if (is_ssh_git_url(git_url) and not token and not username) else norm_url
    auth_url = build_authenticated_url(target_url, token, username=username, provider=provider)
    safe_url = sanitize_url_for_logging(auth_url)
    git_env = _get_git_env()

    logger.info(f"Cloning {safe_url} (branch: {branch}, depth: {depth_str}) shallowly to {repo_dir}...")
    try:
        dot_git_exists = os.path.exists(os.path.join(repo_dir, ".git"))
        valid_existing = target_dir and dot_git_exists and is_valid_git_repo(repo_dir)

        # Check if already a valid git repo in target_dir (incremental shallow update)
        if valid_existing:
            safe_dir = repo_dir.replace("\\", "/")
            git_base = ["git", "-C", repo_dir, "-c", f"safe.directory={safe_dir}"]
            logger.info(f"Existing shallow clone found in {repo_dir}; fetching latest refs (depth: {depth_str})...")
            subprocess.run(git_base + ["remote", "set-url", "origin", auth_url], cwd=repo_dir, capture_output=True, text=True, timeout=15, env=git_env)
            fetch_cmd = git_base + ["fetch", "--depth", depth_str, "origin", branch]
            f_res = subprocess.run(fetch_cmd, cwd=repo_dir, capture_output=True, text=True, timeout=60, env=git_env)
            if f_res.returncode != 0:
                # Retry fetch once without explicit branch ref in case remote refspec differs
                f_res = subprocess.run(git_base + ["fetch", "--depth", depth_str, "origin"], cwd=repo_dir, capture_output=True, text=True, timeout=60, env=git_env)

            if f_res.returncode == 0:
                r_res = subprocess.run(git_base + ["reset", "--hard", "FETCH_HEAD"], cwd=repo_dir, capture_output=True, text=True, timeout=30, env=git_env)
                if r_res.returncode != 0:
                    r_res = subprocess.run(git_base + ["reset", "--hard", f"origin/{branch}"], cwd=repo_dir, capture_output=True, text=True, timeout=30, env=git_env)
                if r_res.returncode == 0:
                    sha_res = subprocess.run(git_base + ["rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, timeout=10, env=git_env)
                    commit_sha = sha_res.stdout.strip() if sha_res.returncode == 0 else "unknown"
                    return CloneResult(temp_dir=repo_dir, commit_sha=commit_sha, error=None)
                logger.warning(f"Git reset failed in {repo_dir} (rc={r_res.returncode}): {r_res.stderr.strip()}; staging fresh clone...")
            else:
                logger.warning(
                    f"Incremental fetch failed in {repo_dir} (rc={f_res.returncode}, stderr={f_res.stderr.strip()!r}, stdout={f_res.stdout.strip()!r}); staging fresh clone..."
                )

            # Stage fresh clone into a sibling directory before replacing the valid persistent clone
            staging_dir = f"{repo_dir}.staging.{int(time.time() * 1000)}"
            res = _clone_fresh_into_dir(auth_url, branch, depth_str, staging_dir, git_env)
            if res.returncode != 0:
                err_msg = res.stderr.strip() or res.stdout.strip() or "Git clone failed"
                cleanup_repo_dir(staging_dir)
                return CloneResult(temp_dir=None, commit_sha=None, error=f"Clone failed: {err_msg}")

            cleanup_repo_dir(repo_dir)
            os.replace(staging_dir, repo_dir)
        else:
            if target_dir and os.path.exists(repo_dir):
                logger.warning(f"Target directory {repo_dir} exists but is not a valid git repository; cleaning up for fresh clone...")
                cleanup_repo_dir(repo_dir)

            res = _clone_fresh_into_dir(auth_url, branch, depth_str, repo_dir, git_env)
            if res.returncode != 0:
                err_msg = res.stderr.strip() or res.stdout.strip() or "Git clone failed"
                cleanup_repo_dir(repo_dir)
                return CloneResult(temp_dir=None, commit_sha=None, error=f"Clone failed: {err_msg}")

        # Get Commit SHA
        safe_dir = repo_dir.replace("\\", "/")
        sha_res = subprocess.run(
            ["git", "-C", repo_dir, "-c", f"safe.directory={safe_dir}", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=10,
            env=git_env,
        )
        commit_sha = sha_res.stdout.strip() if sha_res.returncode == 0 else "unknown"

        return CloneResult(temp_dir=repo_dir, commit_sha=commit_sha, error=None)
    except Exception as e:
        if not target_dir or not os.path.exists(os.path.join(repo_dir, ".git", "HEAD")):
            cleanup_repo_dir(repo_dir)
        return CloneResult(temp_dir=None, commit_sha=None, error=f"Exception during git clone: {str(e)}")

def extract_recent_commits(repo_dir: str, limit: int = 20) -> list[Dict[str, Any]]:
    """
    Extracts recent commit metadata from a local git repository.
    Returns: List of dicts with commit_sha, author, committed_at (ISO 8601),
             message (commit subject + body), and files_changed (list of relative filepaths).
    """
    if not repo_dir or not os.path.exists(os.path.join(repo_dir, ".git")):
        return []
    if limit <= 0:
        return []

    # Delimiters for structured git log parsing
    record_delim = "===CC_COMMIT_START==="
    files_delim = "===CC_FILES_START==="

    safe_dir = repo_dir.replace("\\", "/")
    # Format: record_delim, SHA, author name <email>, ISO date (%cI), raw body (%B), files_delim
    cmd = [
        "git", "-C", repo_dir, "-c", f"safe.directory={safe_dir}", "log",
        f"-n{limit}",
        "--name-only",
        f"--pretty=format:{record_delim}%n%H%n%an <%ae>%n%cI%n%B{files_delim}",
    ]

    try:
        res = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=30, env=_get_git_env())
        if res.returncode != 0 or not res.stdout:
            return []

        raw_output = res.stdout
        chunks = raw_output.split(record_delim)
        commits = []

        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue

            if files_delim not in chunk:
                continue

            meta_part, files_part = chunk.split(files_delim, 1)
            meta_lines = meta_part.splitlines()
            if len(meta_lines) < 3:
                continue

            commit_sha = meta_lines[0].strip()
            author = meta_lines[1].strip()
            committed_at = meta_lines[2].strip()
            # Everything after the first 3 lines is the commit message
            message = "\n".join(meta_lines[3:]).strip() if len(meta_lines) > 3 else ""

            # files_part contains the relative filepaths touched by the commit
            files_changed = []
            for f_line in files_part.splitlines():
                f_path = f_line.strip().replace("\\", "/")
                if f_path and f_path not in files_changed:
                    files_changed.append(f_path)

            commits.append({
                "commit_sha": commit_sha,
                "author": author,
                "committed_at": committed_at,
                "message": message,
                "files_changed": files_changed,
            })

        return commits
    except Exception as e:
        logger.error(f"Error extracting recent commits from {repo_dir}: {e}")
        return []

def _handle_remove_readonly(func, path, exc_info):
    """Clears the read-only bit (e.g. on .git/objects/pack/* on Windows) and retries deletion."""
    import stat
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except Exception as e:
        logger.debug(f"Could not force-remove {path}: {e}")

def cleanup_repo_dir(repo_dir: Optional[str]):
    """Safely removes cloned directory from disk, handling read-only .git packfiles on Windows."""
    if repo_dir and os.path.exists(repo_dir):
        try:
            shutil.rmtree(repo_dir, onerror=_handle_remove_readonly)
            if os.path.exists(repo_dir):
                # If a file handle is still briefly held on Windows, move the directory aside so a fresh clone can proceed
                import time
                stale_path = f"{repo_dir}.stale.{int(time.time() * 1000)}"
                try:
                    os.replace(repo_dir, stale_path)
                    shutil.rmtree(stale_path, onerror=_handle_remove_readonly)
                except Exception as move_err:
                    logger.warning(f"Failed to move locked repo directory {repo_dir}: {move_err}")
            logger.info(f"Cleaned up temporary repo directory: {repo_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp directory {repo_dir}: {e}")

def format_git_commit_url(
    git_url: str,
    commit_sha: str,
    provider: Optional[str] = None
) -> Optional[str]:
    """Constructs a clickable web URL for a commit (e.g. GitHub, GitLab, Gitea, Bitbucket)."""
    if not git_url or not commit_sha:
        return None
    base = normalize_git_url(git_url).rstrip("/")
    if base.endswith(".git"):
        base = base[:-4]

    prov = detect_git_provider(base, provider)
    if prov == "gitlab":
        return f"{base}/-/commit/{commit_sha}"
    elif prov == "bitbucket":
        return f"{base}/commits/{commit_sha}"
    elif prov == "gitea":
        return f"{base}/commit/{commit_sha}"
    else:
        # GitHub and generic standard
        return f"{base}/commit/{commit_sha}"

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
    raw_rel = rel_path.split("://", 1)[1] if (rel_path and "://" in rel_path) else (rel_path or "")
    clean_rel = raw_rel.replace("\\", "/").lstrip("/")

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
        logger.error(f"Error checking GitHub rate limit: {e}")
        return {"authenticated": bool(token), "error": "Unable to verify rate limit."}


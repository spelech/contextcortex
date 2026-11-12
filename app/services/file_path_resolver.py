import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("contextcortex.file_reader")

ALLOWED_TEXT_EXTENSIONS = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".cbl", ".cob", ".cpy",
    ".cs", ".csx", ".csproj", ".sln", ".props", ".targets",
    ".go", ".rs", ".java", ".kt", ".kts", ".scala",
    ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx",
    ".rb", ".php", ".swift", ".m", ".lua", ".pl", ".r",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".sql", ".graphql", ".gql", ".proto",
    ".md", ".markdown", ".txt", ".rst", ".adoc",
    ".yaml", ".yml", ".json", ".jsonl", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".xml", ".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
    ".dockerfile", ".gitignore", ".gitattributes", ".editorconfig", ".csv", ".tsv", ".log",
})

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def is_allowed_text_file(filepath: str) -> bool:
    """Returns True if filepath has a recognized text/code extension or standard text basename."""
    if not filepath:
        return False
    bname = os.path.basename(filepath.replace("\\", "/"))
    _, ext = os.path.splitext(bname)
    if ext:
        return ext.lower() in ALLOWED_TEXT_EXTENSIONS
    return bname.lower() in {"dockerfile", "makefile", "jenkinsfile", "procfile", "readme", "license"}


def validate_path_security(path: str) -> None:
    if not path or not isinstance(path, str) or "\x00" in path:
        raise ValueError("Path traversal or invalid path detected")

    norm = path.replace("\\", "/")
    parts = norm.split("/")
    if any(part == ".." for part in parts):
        raise ValueError("Path traversal or invalid path detected")


def parse_repo_uri(path: str, repo: Optional[str] = None) -> Tuple[str, Optional[str], bool]:
    """Parses optional `repo://rel_path` or `git://repo/rel_path` URI schemes safely.

    Returns:
        Tuple[clean_path, effective_repo, had_uri_scheme]
    """
    validate_path_security(path)
    effective_repo = None if repo in ("__all__", "", "all", None) else repo.strip()
    if effective_repo:
        validate_path_security(effective_repo)

    if "://" in path:
        scheme, rest = path.split("://", 1)
        scheme = scheme.strip()
        if not scheme or "/" in scheme or "\\" in scheme or scheme in (".", ".."):
            raise ValueError("Path traversal or invalid path detected")
        if scheme.lower() in ("http", "https", "ftp", "file", "ssh"):
            raise ValueError("Path outside authorized roots")

        if scheme.lower() == "git":
            norm_rest = rest.replace("\\", "/").lstrip("/")
            if "/" not in norm_rest:
                raise ValueError("Path traversal or invalid path detected")
            uri_repo, rel_part = norm_rest.split("/", 1)
        else:
            uri_repo = scheme
            rel_part = rest.replace("\\", "/")
            if rel_part.startswith("/"):
                raise ValueError("Path outside authorized roots")

        validate_path_security(uri_repo)
        validate_path_security(rel_part)
        rel_clean = rel_part.lstrip("/")
        if not rel_clean:
            raise ValueError("Path traversal or invalid path detected")

        if effective_repo and effective_repo != uri_repo:
            raise ValueError("Path outside authorized roots")
        return rel_clean, (effective_repo or uri_repo), True

    if os.name != "nt" and _WINDOWS_DRIVE_RE.match(path):
        raise ValueError("Path outside authorized roots")

    clean_path = path if os.path.isabs(path) else path.replace("\\", "/")
    return clean_path, effective_repo, False


def _find_case_insensitive_child(root_dir: str, rel_path: str) -> Optional[str]:
    """Resolves a relative path case-insensitively inside root_dir when exact case is absent on POSIX."""
    if not os.path.isdir(root_dir) or not rel_path:
        return None
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p and p != "."]
    if not parts:
        return None
    curr = root_dir
    for seg in parts:
        exact = os.path.join(curr, seg)
        if os.path.lexists(exact):
            curr = exact
            continue
        if not os.path.isdir(curr):
            return None
        seg_low = seg.lower()
        matched_entry = None
        try:
            for entry in os.listdir(curr):
                if entry.lower() == seg_low:
                    matched_entry = os.path.join(curr, entry)
                    break
        except OSError:
            return None
        if matched_entry is None:
            return None
        curr = matched_entry
    return os.path.normpath(os.path.abspath(curr))


class FilePathResolver:
    """Resolves and validates file paths across local storage, monitored paths, and persistent Git clones."""

    def __init__(self, db_conn_factory: Callable[[], Any]):
        self._get_db_connection = db_conn_factory

    def is_within_root(self, target: str, root: str) -> bool:
        target_abs = os.path.abspath(target)
        root_abs = os.path.abspath(root)

        if os.path.isfile(root_abs):
            return (
                target_abs == root_abs
                and os.path.realpath(target_abs) == os.path.realpath(root_abs)
            )

        root_prefix = root_abs if root_abs.endswith(os.sep) else root_abs + os.sep
        if not target_abs.startswith(root_prefix) and target_abs != root_abs:
            return False

        try:
            if os.path.commonpath([target_abs, root_abs]) != root_abs:
                return False
        except ValueError:
            return False

        target_real = os.path.realpath(target_abs)
        root_real = os.path.realpath(root_abs)
        root_real_prefix = root_real if root_real.endswith(os.sep) else root_real + os.sep
        if not target_real.startswith(root_real_prefix) and target_real != root_real:
            return False

        try:
            if os.path.commonpath([target_real, root_real]) != root_real:
                return False
        except ValueError:
            return False

        return True

    def get_authorized_indexed_paths(self) -> List[Dict[str, Any]]:
        try:
            with self._get_db_connection() as conn:
                rows = conn.execute("SELECT path, repo FROM indexed_paths WHERE enabled = 1").fetchall()
                return [{"path": r["path"], "repo": r["repo"]} for r in rows]
        except Exception as e:
            logger.warning(f"Failed to fetch authorized indexed_paths: {e}")
            return []

    def get_authorized_persistent_repos(self) -> Dict[str, str]:
        try:
            from app.services.git_manager import get_persistent_repo_dir
            with self._get_db_connection() as conn:
                rows = conn.execute("SELECT name FROM git_repositories").fetchall()
            repos: Dict[str, str] = {}
            for r in rows:
                name = str(r["name"]).strip()
                if not name:
                    continue
                try:
                    repos[name] = get_persistent_repo_dir(name)
                except ValueError:
                    continue
            return repos
        except Exception as e:
            logger.warning(f"Failed to fetch authorized persistent repos: {e}")
            return {}

    def resolve_persistent_repo_clone_dir(self, repo_name: str, persistent_repos: Dict[str, str]) -> Optional[str]:
        if repo_name in persistent_repos:
            return persistent_repos[repo_name]
        try:
            from app.services.git_manager import get_persistent_repo_dir
            cand_dir = get_persistent_repo_dir(repo_name)
            if os.path.isdir(cand_dir):
                return cand_dir
        except Exception:
            pass
        return None

    def is_ephemeral_git_repo_absent(self, repo_name: Optional[str]) -> bool:
        """Returns True if repo_name is a registered Git repo whose local persistent clone directory is absent."""
        if not repo_name or repo_name in ("local_storage", "__all__", "all", "unknown"):
            return False
        try:
            from app.services.git_manager import get_persistent_repo_dir
            with self._get_db_connection() as conn:
                row = conn.execute("SELECT name FROM git_repositories WHERE name = ?", (repo_name,)).fetchone()
                if not row:
                    row = conn.execute("SELECT repo FROM indexed_files WHERE repo = ? LIMIT 1", (repo_name,)).fetchone()
            if not row:
                return False
            repo_dir = get_persistent_repo_dir(repo_name)
            return not os.path.isdir(repo_dir)
        except Exception:
            return False

    def resolve_safe_path(
        self,
        path: str,
        storage_root: str,
        project_root: str,
        repo: Optional[str] = None,
    ) -> Tuple[str, str]:
        clean_path, effective_repo, had_uri = parse_repo_uri(path, repo=repo)
        indexed_paths = self.get_authorized_indexed_paths()

        # 1. Local storage explicitly targeted
        if effective_repo == "local_storage":
            target = (
                os.path.normpath(os.path.abspath(clean_path))
                if os.path.isabs(clean_path)
                else os.path.normpath(os.path.abspath(os.path.join(storage_root, clean_path)))
            )
            if not self.is_within_root(target, storage_root):
                raise ValueError("Path outside authorized roots")
            return target, "local_storage"

        # 2. Specific repository targeted (via repo arg or repo:// URI)
        if effective_repo:
            persistent_repos = self.get_authorized_persistent_repos()
            repo_disk_dir = self.resolve_persistent_repo_clone_dir(effective_repo, persistent_repos)

            if repo_disk_dir:
                if os.path.isabs(clean_path):
                    target_p = os.path.normpath(os.path.abspath(clean_path))
                    if self.is_within_root(target_p, repo_disk_dir) and os.path.lexists(target_p):
                        return target_p, "persistent_repo"
                else:
                    cand_repo = os.path.normpath(os.path.abspath(os.path.join(repo_disk_dir, clean_path)))
                    if os.path.lexists(cand_repo):
                        if not self.is_within_root(cand_repo, repo_disk_dir):
                            raise ValueError("Path outside authorized roots")
                        return cand_repo, "persistent_repo"
                    ci_cand = _find_case_insensitive_child(repo_disk_dir, clean_path)
                    if ci_cand and os.path.lexists(ci_cand):
                        if not self.is_within_root(ci_cand, repo_disk_dir):
                            raise ValueError("Path outside authorized roots")
                        return ci_cand, "persistent_repo"

            matching_paths = [ip for ip in indexed_paths if ip.get("repo") == effective_repo]

            if os.path.isabs(clean_path):
                target = os.path.normpath(os.path.abspath(clean_path))
                for ip in matching_paths:
                    root = os.path.abspath(ip["path"])
                    if self.is_within_root(target, root):
                        return target, "indexed_path"
                if self.is_within_root(target, project_root):
                    return target, "workspace"
                raise ValueError("Path outside authorized roots")

            for ip in matching_paths:
                root = os.path.abspath(ip["path"])
                candidate = os.path.normpath(os.path.abspath(os.path.join(root, clean_path)))
                if os.path.lexists(candidate):
                    if not self.is_within_root(candidate, root):
                        raise ValueError("Path outside authorized roots")
                    return candidate, "indexed_path"
                ci_ip = _find_case_insensitive_child(root, clean_path)
                if ci_ip and os.path.lexists(ci_ip):
                    if not self.is_within_root(ci_ip, root):
                        raise ValueError("Path outside authorized roots")
                    return ci_ip, "indexed_path"

            if not had_uri:
                cand_proj = os.path.normpath(os.path.abspath(os.path.join(project_root, clean_path)))
                if os.path.lexists(cand_proj) and self.is_within_root(cand_proj, project_root):
                    return cand_proj, "workspace"

            if repo_disk_dir and os.path.isdir(repo_disk_dir):
                cand_repo = os.path.normpath(os.path.abspath(os.path.join(repo_disk_dir, clean_path)))
                if self.is_within_root(cand_repo, repo_disk_dir):
                    return cand_repo, "persistent_repo"

            for ip in matching_paths:
                root = os.path.abspath(ip["path"])
                candidate = os.path.normpath(os.path.abspath(os.path.join(root, clean_path)))
                if self.is_within_root(candidate, root):
                    return candidate, "indexed_path"

            if not matching_paths:
                cand_proj = os.path.normpath(os.path.abspath(os.path.join(project_root, clean_path)))
                if not had_uri and self.is_within_root(cand_proj, project_root):
                    return cand_proj, "workspace"
                raise FileNotFoundError(
                    f"Repository '{effective_repo}' has no local clone on disk for '{clean_path}'"
                )
            raise ValueError("Path outside authorized roots")

        # 3. No repository specified
        if os.path.isabs(clean_path):
            target = os.path.normpath(os.path.abspath(clean_path))
            if self.is_within_root(target, storage_root):
                return target, "local_storage"
            for ip in indexed_paths:
                root = os.path.abspath(ip["path"])
                if self.is_within_root(target, root):
                    return target, "indexed_path"
            for r_dir in self.get_authorized_persistent_repos().values():
                if os.path.isdir(r_dir) and self.is_within_root(target, r_dir):
                    return target, "persistent_repo"
            if self.is_within_root(target, project_root):
                return target, "workspace"
            raise ValueError("Path outside authorized roots")

        cand_storage = os.path.normpath(os.path.abspath(os.path.join(storage_root, clean_path)))
        if os.path.lexists(cand_storage):
            if not self.is_within_root(cand_storage, storage_root):
                raise ValueError("Path outside authorized roots")
            return cand_storage, "local_storage"

        for ip in indexed_paths:
            root = os.path.abspath(ip["path"])
            cand_ip = os.path.normpath(os.path.abspath(os.path.join(root, clean_path)))
            if os.path.lexists(cand_ip):
                if not self.is_within_root(cand_ip, root):
                    raise ValueError("Path outside authorized roots")
                return cand_ip, "indexed_path"

        for r_dir in self.get_authorized_persistent_repos().values():
            if os.path.isdir(r_dir):
                cand_pr = os.path.normpath(os.path.abspath(os.path.join(r_dir, clean_path)))
                if os.path.lexists(cand_pr):
                    if not self.is_within_root(cand_pr, r_dir):
                        raise ValueError("Path outside authorized roots")
                    return cand_pr, "persistent_repo"

        cand_proj = os.path.normpath(os.path.abspath(os.path.join(project_root, clean_path)))
        if os.path.lexists(cand_proj):
            if not self.is_within_root(cand_proj, project_root):
                raise ValueError("Path outside authorized roots")
            return cand_proj, "workspace"

        if self.is_within_root(cand_storage, storage_root):
            return cand_storage, "local_storage"

        for ip in indexed_paths:
            root = os.path.abspath(ip["path"])
            cand_ip = os.path.normpath(os.path.abspath(os.path.join(root, clean_path)))
            if self.is_within_root(cand_ip, root):
                return cand_ip, "indexed_path"

        if self.is_within_root(cand_proj, project_root):
            return cand_proj, "workspace"

        raise ValueError("Path outside authorized roots")

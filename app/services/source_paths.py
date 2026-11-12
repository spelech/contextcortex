"""Maps stored file paths to the repository-relative form that tools return.

Git sources store `ast_symbols.filepath` (and the other `filepath` columns) as `repo://relative/path`.
Local sources (rows in `indexed_paths`) store the absolute disk path. Tool output must use the path
relative to the source root for both, because `read_file` and `grep_code` take that form.
"""
import logging
import os
import re
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger("contextcortex.source_paths")

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:(?:/|$)")


def clean_stored_path(filepath: Optional[str]) -> str:
    """Removes a `repo://` prefix and converts backslashes to forward slashes."""
    if not filepath:
        return ""
    norm = filepath.replace("\\", "/")
    return norm.split("://", 1)[1] if "://" in norm else norm


def _normalize_root(path: Optional[str]) -> str:
    if not isinstance(path, str) or not path.strip():
        return ""
    raw = path.strip()
    norm = raw.replace("\\", "/")
    if not (norm.startswith("/") or _WINDOWS_DRIVE_RE.match(norm)):
        norm = os.path.abspath(raw).replace("\\", "/")
    return norm.rstrip("/")


class LocalSourceRoots:
    """Root folders of the local sources (`indexed_paths`), used to make stored absolute paths relative."""

    def __init__(self, entries: Iterable[Tuple[Optional[str], Optional[str]]] = ()):
        roots: List[Tuple[Optional[str], str]] = []
        for repo, path in entries:
            root = _normalize_root(path)
            if root:
                roots.append((repo, root))
        # The longest root wins when local sources are nested.
        roots.sort(key=lambda item: len(item[1]), reverse=True)
        self._roots = roots

    @classmethod
    def load(cls, conn) -> "LocalSourceRoots":
        """Reads all `indexed_paths` roots with an open database connection. Returns no roots on error."""
        try:
            rows = conn.execute("SELECT repo, path FROM indexed_paths").fetchall()
            entries = [(row["repo"], row["path"]) for row in rows or []]
        except Exception as e:
            logger.debug(f"Could not read indexed_paths roots: {e}")
            return cls()
        return cls(entries)

    def strip_root(self, filepath: Optional[str], repo: Optional[str] = None) -> Optional[str]:
        """Returns the path relative to the local-source root that contains it, or None if no root contains it."""
        if not filepath or not self._roots:
            return None
        norm = filepath.replace("\\", "/")
        if "://" in norm:
            return None
        norm_lower = norm.lower()
        preferred = [r for r in self._roots if repo and r[0] == repo]
        for _, root in preferred + self._roots:
            root_lower = root.lower()
            if norm_lower == root_lower:
                # The source is one file: its root folder is the parent folder.
                return norm.rsplit("/", 1)[-1]
            if norm_lower.startswith(root_lower + "/"):
                return norm[len(root) + 1:].lstrip("/")
        return None

    def relative(self, filepath: Optional[str], repo: Optional[str] = None) -> str:
        """Returns the repository-relative form of a stored filepath (git `repo://` or local absolute path)."""
        stripped = self.strip_root(filepath, repo)
        return stripped if stripped is not None else clean_stored_path(filepath)


__all__ = ["LocalSourceRoots", "clean_stored_path"]

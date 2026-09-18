import os
import logging
from typing import Optional, Tuple, Dict, Any, List

from app.services.database.connection import get_db_connection, get_file_settings
from app.services.local_storage import get_default_storage_path

logger = logging.getLogger("contextcortex.file_reader")


class FileReaderService:
    """Service for securely resolving and reading files across local storage and watched paths."""

    def __init__(self, storage_root: Optional[str] = None):
        self._storage_root = storage_root

    @property
    def storage_root(self) -> str:
        return os.path.abspath(self._storage_root or get_default_storage_path())

    def _validate_path_security(self, path: str) -> None:
        if not path or not isinstance(path, str) or "\x00" in path:
            raise ValueError("Path traversal or invalid path detected")

        norm = path.replace("\\", "/")
        parts = norm.split("/")
        if any(part == ".." for part in parts):
            raise ValueError("Path traversal or invalid path detected")

    def _is_within_root(self, target: str, root: str) -> bool:
        target_abs = os.path.abspath(target)
        root_abs = os.path.abspath(root)

        if os.path.isfile(root_abs):
            return (
                target_abs == root_abs
                and os.path.realpath(target_abs) == os.path.realpath(root_abs)
            )

        try:
            if os.path.commonpath([target_abs, root_abs]) != root_abs:
                return False
        except ValueError:
            return False

        # Verify symlink containment to prevent symlink breakouts
        target_real = os.path.realpath(target_abs)
        root_real = os.path.realpath(root_abs)
        try:
            if os.path.commonpath([target_real, root_real]) != root_real:
                return False
        except ValueError:
            return False

        return True

    def _get_authorized_indexed_paths(self) -> List[Dict[str, Any]]:
        try:
            with get_db_connection() as conn:
                rows = conn.execute(
                    "SELECT path, repo FROM indexed_paths WHERE enabled = 1"
                ).fetchall()
                return [{"path": r["path"], "repo": r["repo"]} for r in rows]
        except Exception as e:
            logger.warning(f"Failed to fetch authorized indexed_paths: {e}")
            return []

    def resolve_safe_path(self, path: str, repo: Optional[str] = None) -> Tuple[str, str]:
        """Resolves target path safely within authorized watched paths or local storage.
        
        Returns:
            Tuple[str, str]: (abs_path, source_type) where source_type is 'indexed_path' or 'local_storage'.
        """
        self._validate_path_security(path)
        storage_root = self.storage_root
        indexed_paths = self._get_authorized_indexed_paths()

        # 1. repo specified as local_storage
        if repo == "local_storage":
            target = (
                os.path.abspath(path)
                if os.path.isabs(path)
                else os.path.abspath(os.path.join(storage_root, path))
            )
            if not self._is_within_root(target, storage_root):
                raise ValueError("Path outside authorized roots")
            return target, "local_storage"

        # 2. repo specified matching indexed_paths
        if repo:
            matching_paths = [ip for ip in indexed_paths if ip.get("repo") == repo]
            if not matching_paths:
                raise ValueError(f"Repository '{repo}' not found or not authorized")

            if os.path.isabs(path):
                target = os.path.abspath(path)
                for ip in matching_paths:
                    root = os.path.abspath(ip["path"])
                    if self._is_within_root(target, root):
                        return target, "indexed_path"
                raise ValueError("Path outside authorized roots")
            else:
                for ip in matching_paths:
                    root = os.path.abspath(ip["path"])
                    candidate = os.path.abspath(os.path.join(root, path))
                    if os.path.lexists(candidate):
                        if not self._is_within_root(candidate, root):
                            raise ValueError("Path outside authorized roots")
                        return candidate, "indexed_path"

                for ip in matching_paths:
                    root = os.path.abspath(ip["path"])
                    candidate = os.path.abspath(os.path.join(root, path))
                    if self._is_within_root(candidate, root):
                        return candidate, "indexed_path"
                raise ValueError("Path outside authorized roots")

        # 3. repo is None
        if os.path.isabs(path):
            target = os.path.abspath(path)
            if self._is_within_root(target, storage_root):
                return target, "local_storage"
            for ip in indexed_paths:
                root = os.path.abspath(ip["path"])
                if self._is_within_root(target, root):
                    return target, "indexed_path"
            raise ValueError("Path outside authorized roots")

        # Relative path without repo specified:
        cand_storage = os.path.abspath(os.path.join(storage_root, path))
        if os.path.lexists(cand_storage):
            if not self._is_within_root(cand_storage, storage_root):
                raise ValueError("Path outside authorized roots")
            return cand_storage, "local_storage"

        for ip in indexed_paths:
            root = os.path.abspath(ip["path"])
            cand_ip = os.path.abspath(os.path.join(root, path))
            if os.path.lexists(cand_ip):
                if not self._is_within_root(cand_ip, root):
                    raise ValueError("Path outside authorized roots")
                return cand_ip, "indexed_path"

        # If not existing on disk, check if it falls inside valid storage root
        if self._is_within_root(cand_storage, storage_root):
            return cand_storage, "local_storage"

        for ip in indexed_paths:
            root = os.path.abspath(ip["path"])
            cand_ip = os.path.abspath(os.path.join(root, path))
            if self._is_within_root(cand_ip, root):
                return cand_ip, "indexed_path"

        raise ValueError("Path outside authorized roots")

    def is_binary_file(self, abs_path: str) -> bool:
        """Detects binary files by checking for null bytes in the initial sample."""
        with open(abs_path, "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk

    def read_file(
        self,
        path: str,
        repo: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        max_lines: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Reads a file with safe path resolution, binary checking, and line slicing."""
        abs_path, source_type = self.resolve_safe_path(path, repo=repo)

        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"File not found: {path}")
        if os.path.isdir(abs_path):
            raise IsADirectoryError(f"Target path is a directory: {path}")

        if self.is_binary_file(abs_path):
            raise ValueError(f"Cannot read binary file: {path}")

        size_bytes = os.path.getsize(abs_path)
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        settings = get_file_settings()
        settings_max_lines = settings.get("read_file_max_lines", 2000)
        effective_max_lines = (
            max_lines if (max_lines is not None and max_lines > 0) else settings_max_lines
        )

        if not text:
            return {
                "filepath": path,
                "content": "",
                "start_line": 1,
                "end_line": 0,
                "total_lines": 0,
                "size_bytes": size_bytes,
                "truncated": False,
                "source": source_type,
            }

        lines = text.splitlines()
        total_lines = len(lines)

        s_line = start_line if (start_line is not None and start_line >= 1) else 1
        e_line = end_line if end_line is not None else total_lines

        if s_line > e_line:
            raise ValueError(
                f"start_line cannot be greater than end_line ({s_line} > {e_line})"
            )

        if s_line > total_lines:
            return {
                "filepath": path,
                "content": "",
                "start_line": s_line,
                "end_line": min(e_line, total_lines),
                "total_lines": total_lines,
                "size_bytes": size_bytes,
                "truncated": False,
                "source": source_type,
            }

        requested_count = min(e_line, total_lines) - s_line + 1
        if effective_max_lines is not None and requested_count > effective_max_lines:
            truncated = True
            actual_end = s_line + effective_max_lines - 1
        else:
            truncated = False
            actual_end = min(e_line, total_lines)

        start_idx = s_line - 1
        end_idx = actual_end
        sliced_content = "\n".join(lines[start_idx:end_idx])

        return {
            "filepath": path,
            "content": sliced_content,
            "start_line": s_line,
            "end_line": actual_end,
            "total_lines": total_lines,
            "size_bytes": size_bytes,
            "truncated": truncated,
            "source": source_type,
        }


_file_reader_service: Optional[FileReaderService] = None


def get_file_reader_service(
    reset: bool = False, storage_root: Optional[str] = None
) -> FileReaderService:
    """Singleton / factory for FileReaderService."""
    global _file_reader_service
    if reset or _file_reader_service is None:
        _file_reader_service = FileReaderService(storage_root=storage_root)
    return _file_reader_service


def reset_file_reader_service():
    """Resets the singleton instance for testing."""
    global _file_reader_service
    _file_reader_service = None


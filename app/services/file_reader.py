import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from app.services.code_grep_scanner import IGNORED_GREP_DIRS, execute_code_grep
from app.services.database.connection import get_db_connection, get_file_settings
from app.services.file_path_resolver import (
    ALLOWED_TEXT_EXTENSIONS,
    FilePathResolver,
    is_allowed_text_file,
    parse_repo_uri,
    validate_path_security,
)
from app.services.local_storage import get_default_storage_path
from app.services.text_decoding import is_binary_file, read_source_text

logger = logging.getLogger("contextcortex.file_reader")


class FileReaderService:
    """Service for securely resolving, reading, reconstructing, and grepping files across authorized roots."""

    ALLOWED_TEXT_EXTENSIONS = ALLOWED_TEXT_EXTENSIONS

    def __init__(self, storage_root: Optional[str] = None):
        self._storage_root = storage_root
        self._resolver = FilePathResolver(db_conn_factory=lambda: get_db_connection())

    @property
    def storage_root(self) -> str:
        return os.path.abspath(self._storage_root or get_default_storage_path())

    @property
    def project_root(self) -> str:
        return os.path.normpath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    def _validate_path_security(self, path: str) -> None:
        validate_path_security(path)

    def _is_within_root(self, target: str, root: str) -> bool:
        return self._resolver.is_within_root(target, root)

    def _get_authorized_indexed_paths(self) -> List[Dict[str, Any]]:
        return self._resolver.get_authorized_indexed_paths()

    def _get_authorized_persistent_repos(self) -> Dict[str, str]:
        return self._resolver.get_authorized_persistent_repos()

    def resolve_safe_path(self, path: str, repo: Optional[str] = None) -> Tuple[str, str]:
        """Resolves target path safely within authorized watched paths, persistent Git clones, or local storage."""
        return self._resolver.resolve_safe_path(
            path=path,
            storage_root=self.storage_root,
            project_root=self.project_root,
            repo=repo,
        )

    def is_binary_file(self, abs_path: str) -> bool:
        """Detects binary files: NUL bytes in the initial sample that are not UTF-16/UTF-32 text."""
        return is_binary_file(abs_path)

    def _slice_lines(
        self,
        lines: List[str],
        filepath: str,
        size_bytes: int,
        source: str,
        start_line: Optional[int],
        end_line: Optional[int],
        max_lines: Optional[int],
    ) -> Dict[str, Any]:
        total_lines = len(lines)
        s_line = start_line if (start_line is not None and start_line >= 1) else 1
        e_line = end_line if end_line is not None else total_lines

        if s_line > e_line:
            raise ValueError(f"start_line cannot be greater than end_line ({s_line} > {e_line})")

        settings = get_file_settings()
        settings_max_lines = settings.get("read_file_max_lines", 2000)
        effective_max_lines = max_lines if (max_lines is not None and max_lines > 0) else settings_max_lines

        if s_line > total_lines:
            return {
                "filepath": filepath,
                "content": "",
                "start_line": s_line,
                "end_line": min(e_line, total_lines),
                "total_lines": total_lines,
                "size_bytes": size_bytes,
                "truncated": False,
                "source": source,
            }

        requested_count = min(e_line, total_lines) - s_line + 1
        if effective_max_lines is not None and requested_count > effective_max_lines:
            truncated = True
            actual_end = s_line + effective_max_lines - 1
        else:
            truncated = False
            actual_end = min(e_line, total_lines)

        sliced = "\n".join(lines[s_line - 1 : actual_end])
        return {
            "filepath": filepath,
            "content": sliced,
            "start_line": s_line,
            "end_line": actual_end,
            "total_lines": total_lines,
            "size_bytes": size_bytes,
            "truncated": truncated,
            "source": source,
        }

    def _read_from_vector_store(
        self,
        path: str,
        repo: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        max_lines: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Reconstructs file content from vector store chunks when file is not present on disk."""
        try:
            from app.services.vector_store import get_vector_store
            store = get_vector_store()
            if not hasattr(store, "get_file_chunks"):
                return None

            clean_rel = path.split("://", 1)[1] if "://" in path else path
            chunks = store.get_file_chunks(path=clean_rel, repo=repo)
            if not chunks and clean_rel != path:
                chunks = store.get_file_chunks(path=path, repo=repo)
            if not chunks:
                return None

            sorted_chunks = sorted(chunks, key=lambda p: (p.get("start_line") or 0, p.get("end_line") or 0))
            has_line_numbers = any(
                p.get("start_line") is not None and int(p.get("start_line")) >= 1
                for p in sorted_chunks
            )

            if has_line_numbers:
                line_map: Dict[int, str] = {}
                max_line = 0
                for p in sorted_chunks:
                    text = p.get("content") or p.get("text") or ""
                    chunk_start = p.get("start_line")
                    chunk_lines = text.splitlines()
                    c_start = int(chunk_start) if (chunk_start is not None and int(chunk_start) >= 1) else (max_line + 1)
                    for i, line_str in enumerate(chunk_lines):
                        curr_line = c_start + i
                        if curr_line not in line_map:
                            line_map[curr_line] = line_str
                        if curr_line > max_line:
                            max_line = curr_line
                all_lines = [line_map.get(l_num, "") for l_num in range(1, max_line + 1)]
            else:
                all_lines = []
                for p in sorted_chunks:
                    text = p.get("content") or p.get("text") or ""
                    all_lines.extend(text.splitlines())

            full_bytes = len("\n".join(all_lines).encode("utf-8"))
            return self._slice_lines(
                lines=all_lines,
                filepath=path,
                size_bytes=full_bytes,
                source="vector_store",
                start_line=start_line,
                end_line=end_line,
                max_lines=max_lines,
            )
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"Error reading from vector store fallback for {path}: {e}")
            return None

    def read_file(
        self,
        path: str,
        repo: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        max_lines: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Reads a file with safe path resolution, vector-store reconstruction fallback, and line slicing."""
        norm_input_path = (path or "").replace("\\", "/")
        clean_lookup_path, effective_repo, _ = parse_repo_uri(path, repo=repo)

        try:
            abs_path, source_type = self.resolve_safe_path(path, repo=repo)
            if not os.path.isabs(abs_path):
                raise ValueError(f"Target path is not absolute: {path}")
            if not os.path.exists(abs_path):
                raise FileNotFoundError(f"File not found on disk: {path}")
        except (ValueError, FileNotFoundError) as orig_err:
            err_low = str(orig_err).lower()
            if isinstance(orig_err, ValueError) and ("traversal" in err_low or "outside authorized roots" in err_low):
                raise

            vec_res = self._read_from_vector_store(
                path=norm_input_path,
                repo=effective_repo,
                start_line=start_line,
                end_line=end_line,
                max_lines=max_lines,
            )
            if vec_res:
                return vec_res

            if effective_repo and self._resolver.is_ephemeral_git_repo_absent(effective_repo):
                raise FileNotFoundError(
                    f"File '{clean_lookup_path}' in repository '{effective_repo}' is not available on disk "
                    f"(ephemeral Git clone was cleaned up after indexing) and could not be reconstructed from "
                    f"indexed vector chunks. Enable persistent shallow clone (keep_shallow) and re-sync '{effective_repo}'."
                ) from orig_err

            if isinstance(orig_err, ValueError):
                raise
            raise FileNotFoundError(f"File not found: {path}") from orig_err

        if os.path.isdir(abs_path):
            raise IsADirectoryError(f"Target path is a directory: {path}")

        if self.is_binary_file(abs_path):
            raise ValueError(f"Cannot read binary file: {path}")

        size_bytes = os.path.getsize(abs_path)
        text = read_source_text(abs_path)

        if not text:
            return {
                "filepath": norm_input_path,
                "content": "",
                "start_line": 1,
                "end_line": 0,
                "total_lines": 0,
                "size_bytes": size_bytes,
                "truncated": False,
                "source": source_type,
            }

        return self._slice_lines(
            lines=text.splitlines(),
            filepath=norm_input_path,
            size_bytes=size_bytes,
            source=source_type,
            start_line=start_line,
            end_line=end_line,
            max_lines=max_lines,
        )

    def grep_code(
        self,
        pattern: str,
        repo: Optional[str] = None,
        path_glob: Optional[str] = None,
        is_regex: bool = False,
        case_sensitive: bool = False,
        context_lines: int = 2,
        limit: int = 30,
    ) -> Dict[str, Any]:
        """Searches files across disk, persistent repos, or vector store chunks with AST enrichment."""
        return execute_code_grep(
            pattern=pattern,
            storage_root=self.storage_root,
            indexed_paths=self._get_authorized_indexed_paths(),
            persistent_repos=self._get_authorized_persistent_repos(),
            is_binary_fn=self.is_binary_file,
            db_conn_factory=lambda: get_db_connection(),
            repo=repo,
            path_glob=path_glob,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            context_lines=context_lines,
            limit=limit,
        )


_file_reader_service: Optional[FileReaderService] = None


def get_file_reader_service(
    reset: bool = False, storage_root: Optional[str] = None
) -> FileReaderService:
    """Singleton / factory for FileReaderService."""
    global _file_reader_service
    if reset or _file_reader_service is None:
        _file_reader_service = FileReaderService(storage_root=storage_root)
    return _file_reader_service


def reset_file_reader_service() -> None:
    """Resets the singleton instance for testing."""
    global _file_reader_service
    _file_reader_service = None


__all__ = [
    "ALLOWED_TEXT_EXTENSIONS",
    "IGNORED_GREP_DIRS",
    "is_allowed_text_file",
    "parse_repo_uri",
    "FilePathResolver",
    "FileReaderService",
    "get_file_reader_service",
    "reset_file_reader_service",
]

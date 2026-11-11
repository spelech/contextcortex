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

        root_prefix = root_abs if root_abs.endswith(os.sep) else root_abs + os.sep
        if not target_abs.startswith(root_prefix) and target_abs != root_abs:
            return False

        try:
            if os.path.commonpath([target_abs, root_abs]) != root_abs:
                return False
        except ValueError:
            return False

        # Verify symlink containment to prevent symlink breakouts
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

    def _get_authorized_persistent_repos(self) -> Dict[str, str]:
        try:
            from app.services.git_manager import PERSISTENT_REPOS_DIR
            base_dir = os.path.normpath(os.path.abspath(PERSISTENT_REPOS_DIR))
            base_prefix = base_dir if base_dir.endswith(os.sep) else base_dir + os.sep
            with get_db_connection() as conn:
                rows = conn.execute("SELECT name FROM git_repositories").fetchall()
            repos: Dict[str, str] = {}
            for r in rows:
                name = str(r["name"]).strip()
                safe_name = os.path.basename(name)
                if safe_name and safe_name not in (".", ".."):
                    target = os.path.normpath(os.path.abspath(os.path.join(base_dir, safe_name)))
                    if target.startswith(base_prefix) or target == base_dir:
                        repos[name] = target
            return repos
        except Exception as e:
            logger.warning(f"Failed to fetch authorized persistent repos: {e}")
            return {}

    def resolve_safe_path(self, path: str, repo: Optional[str] = None) -> Tuple[str, str]:
        """Resolves target path safely within authorized watched paths or local storage.
        
        Returns:
            Tuple[str, str]: (abs_path, source_type) where source_type is 'indexed_path' or 'local_storage'.
        """
        self._validate_path_security(path)
        storage_root = self.storage_root
        indexed_paths = self._get_authorized_indexed_paths()

        # Normalize __all__ or empty repo to None
        effective_repo = None if repo in ("__all__", "", "all") else repo

        # Project / Workspace Root
        project_root = os.path.normpath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

        # 1. repo specified as local_storage
        if effective_repo == "local_storage":
            target = (
                os.path.normpath(os.path.abspath(path))
                if os.path.isabs(path)
                else os.path.normpath(os.path.abspath(os.path.join(storage_root, path)))
            )
            storage_prefix = storage_root if storage_root.endswith(os.sep) else storage_root + os.sep
            if not (target.startswith(storage_prefix) or target == storage_root):
                raise ValueError("Path outside authorized roots")
            if not self._is_within_root(target, storage_root):
                raise ValueError("Path outside authorized roots")
            return target, "local_storage"

        # 2. repo specified matching indexed_paths or git_repositories
        if effective_repo:
            # Check persistent shallow clone if available
            try:
                persistent_repos = self._get_authorized_persistent_repos()
                if effective_repo in persistent_repos:
                    repo_disk_dir = persistent_repos[effective_repo]
                    rel_clean = path.split("://", 1)[1] if "://" in path else path.lstrip("/")
                    cand_repo = os.path.normpath(os.path.abspath(os.path.join(repo_disk_dir, rel_clean)))
                    if cand_repo.startswith(repo_disk_dir):
                        if os.path.lexists(cand_repo):
                            if not self._is_within_root(cand_repo, repo_disk_dir):
                                raise ValueError("Path outside authorized roots")
                            return cand_repo, "persistent_repo"
            except Exception as e:
                logger.debug(f"Persistent repo lookup check failed: {e}")

            matching_paths = [ip for ip in indexed_paths if ip.get("repo") == effective_repo]

            if os.path.isabs(path):
                target = os.path.normpath(os.path.abspath(path))
                for ip in matching_paths:
                    root = os.path.abspath(ip["path"])
                    root_prefix = root if root.endswith(os.sep) else root + os.sep
                    if (target.startswith(root_prefix) or target == root) and self._is_within_root(target, root):
                        return target, "indexed_path"
                if (target.startswith(project_root) or target == project_root) and self._is_within_root(target, project_root):
                    return target, "workspace"
                raise ValueError("Path outside authorized roots")
            else:
                for ip in matching_paths:
                    root = os.path.abspath(ip["path"])
                    candidate = os.path.normpath(os.path.abspath(os.path.join(root, path)))
                    if candidate.startswith(root):
                        if os.path.lexists(candidate):
                            if not self._is_within_root(candidate, root):
                                raise ValueError("Path outside authorized roots")
                            return candidate, "indexed_path"

                # Check project root if candidate exists
                cand_proj = os.path.normpath(os.path.abspath(os.path.join(project_root, path)))
                if cand_proj.startswith(project_root) and os.path.lexists(cand_proj):
                    if self._is_within_root(cand_proj, project_root):
                        return cand_proj, "workspace"

                for ip in matching_paths:
                    root = os.path.abspath(ip["path"])
                    candidate = os.path.normpath(os.path.abspath(os.path.join(root, path)))
                    if candidate.startswith(root) and self._is_within_root(candidate, root):
                        return candidate, "indexed_path"

                if not matching_paths:
                    # If repo name is registered in git_repositories or indexed_files, allow workspace lookup
                    if cand_proj.startswith(project_root) and self._is_within_root(cand_proj, project_root):
                        return cand_proj, "workspace"
                    raise ValueError(f"Repository '{effective_repo}' not found or not authorized")
                raise ValueError("Path outside authorized roots")

        # 3. effective_repo is None (or __all__)
        if os.path.isabs(path):
            target = os.path.normpath(os.path.abspath(path))
            storage_prefix = storage_root if storage_root.endswith(os.sep) else storage_root + os.sep
            if (target.startswith(storage_prefix) or target == storage_root) and self._is_within_root(target, storage_root):
                return target, "local_storage"
            for ip in indexed_paths:
                root = os.path.abspath(ip["path"])
                root_prefix = root if root.endswith(os.sep) else root + os.sep
                if (target.startswith(root_prefix) or target == root) and self._is_within_root(target, root):
                    return target, "indexed_path"
            if (target.startswith(project_root) or target == project_root) and self._is_within_root(target, project_root):
                return target, "workspace"
            raise ValueError("Path outside authorized roots")

        # Relative path without repo specified:
        cand_storage = os.path.normpath(os.path.abspath(os.path.join(storage_root, path)))
        if cand_storage.startswith(storage_root):
            if os.path.lexists(cand_storage):
                if not self._is_within_root(cand_storage, storage_root):
                    raise ValueError("Path outside authorized roots")
                return cand_storage, "local_storage"

        for ip in indexed_paths:
            root = os.path.abspath(ip["path"])
            cand_ip = os.path.normpath(os.path.abspath(os.path.join(root, path)))
            if cand_ip.startswith(root):
                if os.path.lexists(cand_ip):
                    if not self._is_within_root(cand_ip, root):
                        raise ValueError("Path outside authorized roots")
                    return cand_ip, "indexed_path"

        # Check project root:
        cand_proj = os.path.normpath(os.path.abspath(os.path.join(project_root, path)))
        if cand_proj.startswith(project_root):
            if os.path.lexists(cand_proj):
                if not self._is_within_root(cand_proj, project_root):
                    raise ValueError("Path outside authorized roots")
                return cand_proj, "workspace"

        # If not existing on disk, check if it falls inside valid storage root or project root
        if cand_storage.startswith(storage_root) and self._is_within_root(cand_storage, storage_root):
            return cand_storage, "local_storage"

        for ip in indexed_paths:
            root = os.path.abspath(ip["path"])
            cand_ip = os.path.normpath(os.path.abspath(os.path.join(root, path)))
            if cand_ip.startswith(root) and self._is_within_root(cand_ip, root):
                return cand_ip, "indexed_path"

        if cand_proj.startswith(project_root) and self._is_within_root(cand_proj, project_root):
            return cand_proj, "workspace"

        raise ValueError("Path outside authorized roots")

    def is_binary_file(self, abs_path: str) -> bool:
        """Detects binary files by checking for null bytes in the initial sample."""
        with open(abs_path, "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk

    def _read_from_vector_store(
        self,
        path: str,
        repo: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        max_lines: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Reconstructs file content from vector store chunks when file is not on disk."""
        try:
            from app.services.vector_store import get_vector_store
            store = get_vector_store()
            if not hasattr(store, "get_file_chunks"):
                return None

            chunks = store.get_file_chunks(path=path, repo=repo)
            if not chunks:
                return None

            sorted_chunks = sorted(
                chunks,
                key=lambda p: (p.get("start_line") or 0, p.get("end_line") or 0)
            )

            # Reconstruct the file using line coordinates
            line_map: Dict[int, str] = {}
            has_line_numbers = any(
                p.get("start_line") is not None and int(p.get("start_line")) >= 1
                for p in sorted_chunks
            )

            if has_line_numbers:
                max_line = 0
                for p in sorted_chunks:
                    text = p.get("content") or p.get("text") or ""
                    chunk_start = p.get("start_line")
                    chunk_lines = text.splitlines()

                    if chunk_start is not None and int(chunk_start) >= 1:
                        c_start = int(chunk_start)
                        for i, line_str in enumerate(chunk_lines):
                            curr_line = c_start + i
                            if curr_line not in line_map:
                                line_map[curr_line] = line_str
                            if curr_line > max_line:
                                max_line = curr_line
                    else:
                        # Fallback for chunk without start_line in mixed set
                        start_pos = max_line + 1
                        for i, line_str in enumerate(chunk_lines):
                            curr_line = start_pos + i
                            if curr_line not in line_map:
                                line_map[curr_line] = line_str
                            if curr_line > max_line:
                                max_line = curr_line

                total_lines = max_line
                all_lines = [line_map.get(l_num, "") for l_num in range(1, total_lines + 1)]
            else:
                # No line coordinates present at all; concatenate chunks cleanly
                all_lines = []
                for p in sorted_chunks:
                    text = p.get("content") or p.get("text") or ""
                    all_lines.extend(text.splitlines())
                total_lines = len(all_lines)

            s_line = start_line if (start_line is not None and start_line >= 1) else 1
            e_line = end_line if end_line is not None else total_lines

            if s_line > e_line:
                raise ValueError(
                    f"start_line cannot be greater than end_line ({s_line} > {e_line})"
                )

            settings = get_file_settings()
            settings_max_lines = settings.get("read_file_max_lines", 2000)
            effective_max_lines = (
                max_lines if (max_lines is not None and max_lines > 0) else settings_max_lines
            )

            if s_line > total_lines:
                return {
                    "filepath": path,
                    "content": "",
                    "start_line": s_line,
                    "end_line": min(e_line, total_lines),
                    "total_lines": total_lines,
                    "size_bytes": len("\n".join(all_lines).encode("utf-8")),
                    "truncated": False,
                    "source": "vector_store",
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
            sliced = "\n".join(all_lines[start_idx:end_idx])

            return {
                "filepath": path,
                "content": sliced,
                "start_line": s_line,
                "end_line": actual_end,
                "total_lines": total_lines,
                "size_bytes": len("\n".join(all_lines).encode("utf-8")),
                "truncated": truncated,
                "source": "vector_store",
            }
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
        """Reads a file with safe path resolution, binary checking, and line slicing."""
        try:
            abs_path, source_type = self.resolve_safe_path(path, repo=repo)
            if not abs_path.startswith("/"):
                raise ValueError(f"Target path is not absolute: {path}")
            if not os.path.exists(abs_path):
                raise FileNotFoundError(f"File not found on disk: {path}")
        except (ValueError, FileNotFoundError):
            vec_res = self._read_from_vector_store(
                path=path, repo=repo, start_line=start_line, end_line=end_line, max_lines=max_lines
            )
            if vec_res:
                return vec_res
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
        """Searches files across disk or vector store matching pattern with surrounding context and AST symbol enrichment."""
        import re
        import fnmatch
        from app.services.git_manager import format_git_permalink

        if not pattern or not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern must be a non-empty string")

        flags = 0 if case_sensitive else re.IGNORECASE
        regex_str = pattern if is_regex else re.escape(pattern)
        try:
            compiled = re.compile(regex_str, flags)
        except re.error as e:
            raise ValueError(f"Invalid regular expression pattern: {e}") from e

        clamped_context = max(0, min(10, int(context_lines)))
        clamped_limit = max(1, min(100, int(limit)))

        effective_repo = None if repo in ("__all__", "", "all") else repo

        # Load git repositories info for permalinks
        git_repos: Dict[str, Dict[str, Any]] = {}
        try:
            with get_db_connection() as conn:
                rows = conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall()
                for r in rows:
                    git_repos[r["name"]] = dict(r)
        except Exception as e:
            logger.debug(f"Failed to load git repositories for permalinks: {e}")

        # Gather files on disk first
        indexed_paths = self._get_authorized_indexed_paths()
        persistent_repos = self._get_authorized_persistent_repos()

        disk_files: List[Tuple[str, str, str]] = []  # (abs_path, repo_name, rel_path)

        # 1. Monitored indexed_paths
        for ip in indexed_paths:
            r_name = ip.get("repo") or "local"
            if effective_repo and r_name != effective_repo:
                continue
            root_p = os.path.abspath(ip["path"])
            if os.path.isdir(root_p):
                for dirpath, _, filenames in os.walk(root_p):
                    for fname in filenames:
                        full_p = os.path.join(dirpath, fname)
                        rel_p = os.path.relpath(full_p, root_p).replace("\\", "/")
                        disk_files.append((full_p, r_name, rel_p))
            elif os.path.isfile(root_p):
                disk_files.append((root_p, r_name, os.path.basename(root_p)))

        # 2. Persistent repos (keep_shallow=1)
        for r_name, r_dir in persistent_repos.items():
            if effective_repo and r_name != effective_repo:
                continue
            if os.path.isdir(r_dir):
                for dirpath, _, filenames in os.walk(r_dir):
                    if "/.git" in dirpath.replace("\\", "/") or dirpath.endswith("/.git"):
                        continue
                    for fname in filenames:
                        full_p = os.path.join(dirpath, fname)
                        rel_p = os.path.relpath(full_p, r_dir).replace("\\", "/")
                        disk_files.append((full_p, r_name, rel_p))

        # 3. Local storage root
        if effective_repo in (None, "local_storage"):
            s_root = self.storage_root
            if os.path.isdir(s_root):
                for dirpath, _, filenames in os.walk(s_root):
                    for fname in filenames:
                        full_p = os.path.join(dirpath, fname)
                        rel_p = os.path.relpath(full_p, s_root).replace("\\", "/")
                        disk_files.append((full_p, "local_storage", rel_p))

        # Filter by path_glob if present
        def matches_glob(path_str: str) -> bool:
            if not path_glob:
                return True
            norm_path = path_str.replace("\\", "/")
            norm_glob = path_glob.replace("\\", "/")
            return fnmatch.fnmatch(norm_path, norm_glob) or fnmatch.fnmatch(os.path.basename(norm_path), norm_glob)

        disk_files = [item for item in disk_files if matches_glob(item[2])]

        matches: List[Dict[str, Any]] = []
        seen_keys = set()  # (repo, rel_path, line_number)
        disk_scanned_keys = set()  # (repo, rel_path)

        for abs_p, r_name, rel_p in disk_files:
            if (r_name, rel_p) in disk_scanned_keys:
                continue
            disk_scanned_keys.add((r_name, rel_p))

            if self.is_binary_file(abs_p):
                continue

            try:
                with open(abs_p, "r", encoding="utf-8", errors="replace") as f:
                    file_text = f.read()
            except Exception:
                continue

            file_lines = file_text.splitlines()
            for line_idx, line_str in enumerate(file_lines):
                line_no = line_idx + 1
                if compiled.search(line_str):
                    key = (r_name, rel_p, line_no)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)

                    # Build context window
                    start_ctx = max(0, line_idx - clamped_context)
                    end_ctx = min(len(file_lines), line_idx + clamped_context + 1)
                    context_items = [
                        {"line": c_idx + 1, "text": file_lines[c_idx]}
                        for c_idx in range(start_ctx, end_ctx)
                    ]

                    matches.append({
                        "repo": r_name,
                        "file": rel_p,
                        "line": line_no,
                        "match_text": line_str,
                        "context": context_items,
                    })

                    if len(matches) >= clamped_limit:
                        break
            if len(matches) >= clamped_limit:
                break

        # If more matches are needed, query vector store chunks (for ephemeral / remote repos not on disk)
        if len(matches) < clamped_limit:
            try:
                from app.services.vector_store import get_vector_store
                store = get_vector_store()
                if hasattr(store, "grep_chunks"):
                    remaining_limit = (clamped_limit - len(matches)) * 5
                    chunks = store.grep_chunks(
                        pattern=pattern,
                        repo=effective_repo,
                        path_glob=path_glob,
                        is_regex=is_regex,
                        case_sensitive=case_sensitive,
                        limit=max(10, remaining_limit)
                    )

                    # Group chunks by file to reconstruct full files or chunk lines
                    for ch in chunks:
                        ch_repo = ch.get("repo") or "unknown"
                        ch_file = ch.get("rel_path") or ch.get("path") or ""
                        if ch_file.startswith(f"{ch_repo}/"):
                            ch_file = ch_file[len(ch_repo) + 1:]

                        if (ch_repo, ch_file) in disk_scanned_keys:
                            continue

                        text_content = ch.get("content") or ch.get("text") or ""
                        start_line = ch.get("start_line") or 1
                        ch_lines = text_content.splitlines()

                        for c_idx, line_str in enumerate(ch_lines):
                            curr_line = int(start_line) + c_idx
                            if compiled.search(line_str):
                                key = (ch_repo, ch_file, curr_line)
                                if key in seen_keys:
                                    continue
                                seen_keys.add(key)

                                start_ctx = max(0, c_idx - clamped_context)
                                end_ctx = min(len(ch_lines), c_idx + clamped_context + 1)
                                context_items = [
                                    {"line": int(start_line) + idx, "text": ch_lines[idx]}
                                    for idx in range(start_ctx, end_ctx)
                                ]

                                matches.append({
                                    "repo": ch_repo,
                                    "file": ch_file,
                                    "line": curr_line,
                                    "match_text": line_str,
                                    "context": context_items,
                                })

                                if len(matches) >= clamped_limit:
                                    break
                        if len(matches) >= clamped_limit:
                            break
            except Exception as e:
                logger.warning(f"grep_chunks fallback in grep_code encountered error: {e}")

        # AST symbols and permalinks enrichment
        for m in matches:
            m_repo = m["repo"]
            m_file = m["file"]
            m_line = m["line"]

            # Lookup AST symbol
            sym_name = None
            sym_kind = None
            try:
                with get_db_connection() as conn:
                    row = conn.execute(
                        """
                        SELECT name, full_symbol, kind, start_line, end_line
                        FROM ast_symbols
                        WHERE repo = ? AND (filepath = ? OR filepath LIKE ?)
                          AND start_line <= ? AND end_line >= ?
                        ORDER BY (end_line - start_line) ASC
                        LIMIT 1
                        """,
                        (m_repo, m_file, f"%/{m_file}", m_line, m_line),
                    ).fetchone()
                    if row:
                        sym_name = row["full_symbol"] or row["name"]
                        sym_kind = row["kind"]
            except Exception as e:
                logger.debug(f"AST symbol lookup failed for {m_repo}:{m_file}:{m_line}: {e}")

            m["symbol"] = sym_name
            m["kind"] = sym_kind

            # Generate permalink
            permalink = None
            g_info = git_repos.get(m_repo)
            if g_info and g_info.get("url"):
                permalink = format_git_permalink(
                    g_info["url"],
                    g_info.get("commit_sha"),
                    m_file,
                    m_line,
                    m_line,
                    provider=g_info.get("provider")
                )
            m["permalink"] = permalink

        truncated = len(matches) >= clamped_limit
        return {
            "pattern": pattern,
            "total_matches": len(matches),
            "truncated": truncated,
            "matches": matches,
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


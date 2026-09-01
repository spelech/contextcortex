import os
import shutil
import hashlib
import logging
from typing import Optional, Dict, Any, List, Union

import app.services.database as db_service
import app.services.vector_store as vs_service
from app.services.indexing.processor import process_file_content, MAX_FILE_SIZE_BYTES
from app.services.indexing.state import trigger_list_changed_notification

logger = logging.getLogger("contextcortex.storage")

def get_default_storage_path() -> str:
    return os.getenv("LOCAL_STORAGE_PATH") or os.path.join(
        os.getenv("DATA_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))),
        "storage"
    )

LOCAL_STORAGE_PATH = get_default_storage_path()
DEFAULT_STORAGE_PATH = LOCAL_STORAGE_PATH

class LocalStorageService:
    def __init__(self, storage_root: Optional[str] = None):
        self.storage_root = os.path.abspath(storage_root or get_default_storage_path())
        os.makedirs(self.storage_root, exist_ok=True)

    def get_storage_root(self) -> str:
        return self.storage_root

    def resolve_safe_path(self, rel_path: str) -> str:
        if not rel_path or not isinstance(rel_path, str) or "\x00" in rel_path:
            raise ValueError("Path traversal or invalid path detected")
        
        cleaned_raw = rel_path.strip()
        if not cleaned_raw or cleaned_raw.startswith("/") or cleaned_raw.startswith("\\") or os.path.isabs(cleaned_raw):
            raise ValueError("Path traversal or invalid path detected")

        cleaned = cleaned_raw.replace("\\", "/")
        parts = cleaned.split("/")
        if any(part == ".." for part in parts):
            raise ValueError("Path traversal or invalid path detected")

        target = os.path.abspath(os.path.join(self.storage_root, cleaned))
        try:
            common = os.path.commonpath([target, self.storage_root])
        except ValueError:
            raise ValueError("Path traversal or invalid path detected")

        if common != self.storage_root:
            raise ValueError("Path traversal or invalid path detected")

        return target

    def save_file_content(
        self,
        rel_path: str,
        content: Union[str, bytes],
        repo: str = "local_storage",
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        target_path = self.resolve_safe_path(rel_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        if isinstance(content, str):
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            with open(target_path, "wb") as f:
                f.write(content)

        mtime = os.path.getmtime(target_path)
        size_bytes = os.path.getsize(target_path)

        return {
            "status": "success",
            "rel_path": rel_path.strip().replace("\\", "/").lstrip("/"),
            "abs_path": target_path,
            "size_bytes": size_bytes,
            "mtime": mtime,
            "repo": repo or "local_storage",
            "category": category or os.path.dirname(rel_path) or "root"
        }

    def index_file(
        self,
        rel_path: str,
        repo: str = "local_storage",
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        abs_path = self.resolve_safe_path(rel_path)
        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            raise FileNotFoundError(f"File '{rel_path}' not found on disk for indexing.")

        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        doc_type = "doc" if abs_path.endswith((".md", ".txt", ".yaml", ".yml", ".json", ".html", ".css", ".sql")) else "code"
        cat = category or os.path.dirname(rel_path) or "root"

        points, ast_symbols, summary_tuple, ast_rel, api_routes, api_calls = process_file_content(
            filepath=abs_path,
            rel_path=rel_path,
            content=content,
            repo=repo,
            doc_type=doc_type,
            category_override=cat
        )

        # Upsert vector points
        if points:
            try:
                store = vs_service.get_vector_store()
                store.delete_by_path(abs_path)
                if hasattr(store, "upsert_documents"):
                    store.upsert_documents(points)
                elif hasattr(store, "upsert_points"):
                    store.upsert_points(points)
            except Exception as e:
                logger.error(f"Failed to upsert vector points for {abs_path}: {e}")

        # Update relational DB
        mtime = os.path.getmtime(abs_path)
        text_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with db_service.get_db_connection() as conn:
            # Delete old relational records
            for table in ("indexed_files", "file_summaries", "ast_symbols"):
                try:
                    conn.execute(f"DELETE FROM {table} WHERE filepath = ?", (abs_path,))
                except Exception:
                    pass
            for table, col in (("ast_relationships", "source_filepath"), ("api_routes", "filepath"), ("api_client_calls", "filepath")):
                try:
                    conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (abs_path,))
                except Exception:
                    pass

            # Insert indexed_file
            conn.execute(
                "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime, hash) VALUES (?, ?, ?, ?, ?, ?)",
                (abs_path, repo, doc_type, doc_type, mtime, text_hash)
            )

            # Insert file summary
            if summary_tuple:
                conn.execute(
                    """INSERT INTO file_summaries (filepath, repo, title, folder, category, tags, headings, keywords, mtime)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    summary_tuple
                )

            # Insert AST symbols
            for sym in ast_symbols:
                name = sym.get("name") or sym.get("symbol_name") or ""
                kind = sym.get("kind") or sym.get("symbol_type") or ""
                sym_filepath = sym.get("filepath") or abs_path
                sym_repo = sym.get("repo") or repo
                start_line = sym.get("start_line") or sym.get("line_number") or 1
                end_line = sym.get("end_line") or sym.get("line_number") or 1
                sig = sym.get("signature") or sym.get("docstring") or ""
                full_sym = sym.get("full_symbol") or name
                lang = sym.get("language") or ""
                try:
                    conn.execute(
                        """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (sym_repo, sym_filepath, name, full_sym, kind, start_line, end_line, sig, lang)
                    )
                except Exception:
                    pass
            conn.commit()

        trigger_list_changed_notification()
        return {
            "status": "success",
            "rel_path": rel_path.strip().replace("\\", "/").lstrip("/"),
            "abs_path": abs_path,
            "chunks_indexed": len(points),
            "symbols_indexed": len(ast_symbols)
        }

    def save_file(
        self,
        rel_path: str,
        content: Union[str, bytes],
        repo: str = "local_storage",
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        save_info = self.save_file_content(rel_path, content, repo=repo, category=category)
        idx_info = self.index_file(rel_path, repo=repo, category=category)
        save_info.update(idx_info)
        return save_info

    def delete_file(self, rel_path: str, repo: str = "local_storage") -> Dict[str, Any]:
        abs_path = self.resolve_safe_path(rel_path)
        self.delete_file_disk(rel_path)

        try:
            store = vs_service.get_vector_store()
            store.delete_by_path(abs_path)
        except Exception as e:
            logger.error(f"Error removing vector points for {abs_path}: {e}")

        with db_service.get_db_connection() as conn:
            for table in ("indexed_files", "file_summaries", "ast_symbols"):
                try:
                    conn.execute(f"DELETE FROM {table} WHERE filepath = ?", (abs_path,))
                except Exception:
                    pass
            for table, col in (("ast_relationships", "source_filepath"), ("api_routes", "filepath"), ("api_client_calls", "filepath")):
                try:
                    conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (abs_path,))
                except Exception:
                    pass
            conn.commit()

        trigger_list_changed_notification()
        return {"status": "success", "rel_path": rel_path.strip().replace("\\", "/").lstrip("/"), "deleted": True}

    def read_file_content(self, rel_path: str) -> Dict[str, Any]:
        target_path = self.resolve_safe_path(rel_path)
        if not os.path.exists(target_path) or not os.path.isfile(target_path):
            raise FileNotFoundError(f"File '{rel_path}' does not exist in local storage.")

        size_bytes = os.path.getsize(target_path)
        mtime = os.path.getmtime(target_path)
        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            text = ""

        return {
            "rel_path": rel_path.strip().replace("\\", "/").lstrip("/"),
            "abs_path": target_path,
            "content": text,
            "size_bytes": size_bytes,
            "mtime": mtime
        }

    def delete_file_disk(self, rel_path: str) -> bool:
        target_path = self.resolve_safe_path(rel_path)
        if not os.path.exists(target_path):
            return False

        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
        else:
            os.remove(target_path)
        return True

    def get_file_tree(self, subfolder: Optional[str] = None) -> Dict[str, Any]:
        scan_root = self.resolve_safe_path(subfolder) if subfolder else self.storage_root
        if not os.path.exists(scan_root):
            return {"root": self.storage_root, "current_folder": subfolder or "", "directories": [], "files": []}

        dirs = []
        files = []
        try:
            for entry in os.scandir(scan_root):
                if entry.name.startswith("."):
                    continue
                rel = os.path.relpath(entry.path, self.storage_root).replace("\\", "/")
                if entry.is_dir():
                    dirs.append({
                        "name": entry.name,
                        "rel_path": rel,
                        "abs_path": os.path.abspath(entry.path)
                    })
                elif entry.is_file():
                    files.append({
                        "name": entry.name,
                        "rel_path": rel,
                        "abs_path": os.path.abspath(entry.path),
                        "size_bytes": entry.stat().st_size,
                        "mtime": entry.stat().st_mtime
                    })
        except Exception as e:
            logger.error(f"Error scanning local storage tree at {scan_root}: {e}")

        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())

        return {
            "root": self.storage_root,
            "current_folder": subfolder or "",
            "directories": dirs,
            "files": files
        }


_storage_service: Optional[LocalStorageService] = None

def get_local_storage_service() -> LocalStorageService:
    global _storage_service
    if _storage_service is None:
        _storage_service = LocalStorageService()
    return _storage_service

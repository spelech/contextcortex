import os
import shutil
import logging
from typing import Optional, Dict, Any, List, Union

logger = logging.getLogger("contextcortex.storage")

def get_default_storage_path() -> str:
    return os.getenv("LOCAL_STORAGE_PATH") or os.path.join(
        os.getenv("DATA_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))),
        "storage"
    )

LOCAL_STORAGE_PATH = get_default_storage_path()

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

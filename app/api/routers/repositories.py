import os
import re
import json
import sqlite3
import threading
import logging
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.models.schemas import (
    RepoConfig, LocalPathConfig, SearchRequest, TokenRequest, HostCredentialRequest,
    VectorStoreTestRequest, VectorStoreSwitchRequest, VectorStoreConfigRequest,
    AutoSyncToggleRequest, AutoSyncSettingsRequest
)
from app.services.db import (
    get_db_connection, get_metadata, set_metadata, 
    get_effective_git_token, CACHE_DB_PATH
)
from app.services.git_manager import check_github_rate_limit, mask_token
from app.services.logger import get_diagnostic_logs, clear_diagnostic_logs
from app.services.vector_store import (
    get_vector_store, get_vector_store_config, switch_vector_store, test_vector_store_connection
)
from app.services.topology import get_topology_graph, get_node_details
from app.services.indexer import (
    sync_single_git_repo, run_full_indexing, is_indexing, COLLECTION_NAME
)
from app.services.embeddings import (
    EMBEDDING_PROVIDER, DENSE_MODEL_NAME, SPARSE_MODEL_NAME
)

logger = logging.getLogger("contextcortex.api")

def _get_r_attr(name, default):
    import sys
    routes_mod = sys.modules.get("app.api.routes")
    return getattr(routes_mod, name, default) if routes_mod else default

router = APIRouter()

@router.get("/admin/api/repos")
async def api_get_repos():
    try:
        with _get_r_attr("get_db_connection", get_db_connection)() as conn:
            rows = conn.execute(
                """SELECT id, name, url, branch, commit_sha, provider, auth_user, enabled, auto_sync, webhook_secret, status, 
                          last_error, last_synced, added_at, 
                          (SELECT count(*) FROM indexed_files WHERE repo = git_repositories.name) as file_count 
                   FROM git_repositories 
                   ORDER BY added_at DESC"""
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/repos")
async def api_add_repo(payload: RepoConfig):
    try:
        name = payload.name.strip() if payload.name else ""
        url = payload.url.strip() if payload.url else ""
        branch = payload.branch.strip() if payload.branch else "main"
        token = payload.auth_token.strip() if payload.auth_token else None
        auth_user = payload.auth_user.strip() if payload.auth_user else None
        auto_sync = 1 if payload.auto_sync else 0
        webhook_secret = payload.webhook_secret.strip() if payload.webhook_secret else None

        if not name or not url:
            return JSONResponse(status_code=400, content={"error": "Repository name and Git URL are required."})

        from app.services.git_manager import detect_git_provider
        provider = detect_git_provider(url, payload.provider)
        name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name).lower()

        with _get_r_attr("get_db_connection", get_db_connection)() as conn:
            conn.execute(
                "INSERT INTO git_repositories (name, url, branch, auth_token, provider, auth_user, auto_sync, webhook_secret) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, url, branch, token, provider, auth_user, auto_sync, webhook_secret)
            )
            conn.commit()
            repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        threading.Thread(target=sync_single_git_repo, args=(repo_id,), daemon=True).start()
        return {"status": "success", "message": f"Added repo '{name}' ({provider}) and started background sync."}
    except sqlite3.IntegrityError:
        return JSONResponse(status_code=400, content={"error": f"Repository '{name}' is already registered."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.patch("/admin/api/repos/{repo_id}/auto-sync")
async def api_toggle_repo_auto_sync(repo_id: int, payload: AutoSyncToggleRequest):
    try:
        from app.services.db import set_repo_auto_sync
        success = set_repo_auto_sync(repo_id, payload.auto_sync)
        if not success:
            return JSONResponse(status_code=404, content={"error": "Repository not found"})
        return {"status": "success", "repo_id": repo_id, "auto_sync": payload.auto_sync}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/repos/sync/{repo_id}")
async def api_sync_repo(repo_id: int):
    try:
        with _get_r_attr("get_db_connection", get_db_connection)() as conn:
            row = conn.execute("SELECT id FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": f"Repository ID {repo_id} not found."})
        threading.Thread(target=sync_single_git_repo, args=(repo_id,), daemon=True).start()
        return {"status": "success", "message": f"Sync triggered for repository ID {repo_id}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/repos/{repo_id}")
async def api_delete_repo(repo_id: int):
    try:
        with _get_r_attr("get_db_connection", get_db_connection)() as conn:
            row = conn.execute("SELECT name FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": "Repo not found"})
            repo_name = row["name"]
            conn.execute("DELETE FROM git_repositories WHERE id = ?", (repo_id,))
            conn.execute("DELETE FROM indexed_files WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM file_summaries WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM ast_symbols WHERE repo = ?", (repo_name,))
            conn.commit()

        # Delete from vector store
        try:
            store = _get_r_attr("get_vector_store", get_vector_store)()
            store.delete_by_repo(repo_name)
        except Exception:
            pass

        return {"status": "success", "message": f"Deleted repository '{repo_name}'"}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/paths")
async def api_get_paths():
    try:
        with _get_r_attr("get_db_connection", get_db_connection)() as conn:
            rows = conn.execute("SELECT id, path, type, recursive, enabled, category, repo, added_at FROM indexed_paths ORDER BY added_at DESC").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/paths")
async def api_add_path(payload: LocalPathConfig):
    try:
        path = payload.path
        ptype = payload.type if payload.type else "directory"
        recursive = 1 if payload.recursive else 0
        enabled = 1 if payload.enabled else 0
        category = payload.category
        repo = payload.repo if payload.repo else "local"

        if not path or not os.path.exists(path):
            return JSONResponse(status_code=400, content={"error": f"Valid local path is required: {path}"})

        path = os.path.abspath(path)
        with _get_r_attr("get_db_connection", get_db_connection)() as conn:
            conn.execute(
                "INSERT INTO indexed_paths (path, type, recursive, enabled, category, repo) VALUES (?, ?, ?, ?, ?, ?)",
                (path, ptype, recursive, enabled, category, repo)
            )
            conn.commit()

        threading.Thread(target=run_full_indexing, daemon=True).start()
        return {"status": "success", "message": f"Added local path: {path}"}
    except sqlite3.IntegrityError:
        return JSONResponse(status_code=400, content={"error": f"Local path '{payload.path}' is already registered."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/paths/{path_id}")
async def api_delete_path(path_id: int):
    try:
        with _get_r_attr("get_db_connection", get_db_connection)() as conn:
            row = conn.execute("SELECT path FROM indexed_paths WHERE id = ?", (path_id,)).fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": f"Path ID {path_id} not found."})
            conn.execute("DELETE FROM indexed_paths WHERE id = ?", (path_id,))
            conn.commit()
        threading.Thread(target=run_full_indexing, daemon=True).start()
        return {"status": "success", "message": f"Deleted path ID {path_id}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/admin/api/reindex")
async def api_trigger_reindex():
    if _get_r_attr("is_indexing", is_indexing):
        return JSONResponse(status_code=409, content={"error": "Indexing in progress"})
    threading.Thread(target=run_full_indexing, daemon=True).start()
    return {"status": "success", "message": "Re-indexing triggered"}

@router.get("/admin/api/browse")
async def api_browse_dir(path: str = "/"):
    resolved = os.path.abspath(path)
    if not os.path.exists(resolved):
        resolved = "/"
    try:
        entries = os.scandir(resolved)
        dirs = []
        files = []
        for e in entries:
            if e.name.startswith("."):
                continue
            if e.is_dir():
                dirs.append({"name": e.name, "path": os.path.abspath(e.path)})
            else:
                files.append({"name": e.name, "path": os.path.abspath(e.path)})
        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())
        return {
            "current_path": resolved,
            "parent_path": os.path.dirname(resolved) if resolved != "/" else "",
            "directories": dirs,
            "files": files
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


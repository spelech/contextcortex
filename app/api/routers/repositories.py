import os
import re
import json
import sqlite3
import threading
import logging
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.schemas import RepoConfig, LocalPathConfig, AutoSyncToggleRequest, SearchRequest
import app.services.database as db_service
import app.services.vector_store as vs_service
import app.services.indexing as idx_service
import app.services.search as search_service

logger = logging.getLogger("contextcortex.api")

router = APIRouter()

@router.get("/admin/api/repos")
async def api_get_repos():
    try:
        with db_service.get_db_connection() as conn:
            rows = conn.execute("""
                SELECT id, name, url, branch, commit_sha, status, last_error, last_synced, 
                       auth_token, provider, auth_user, auto_sync, webhook_secret
                FROM git_repositories 
                ORDER BY id DESC
            """).fetchall()
            result = []
            for r in rows:
                item = dict(r)
                try:
                    f_count = conn.execute("SELECT COUNT(*) as c FROM indexed_files WHERE repo = ?", (item["name"],)).fetchone()["c"]
                except Exception:
                    f_count = 0
                item["file_count"] = f_count
                result.append(item)
            return result
    except Exception as e:
        logger.error(f"Error fetching repos: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/repos")
async def api_add_repo(repo: RepoConfig):
    if not repo.name or not repo.name.strip() or not repo.url or not repo.url.strip():
        return JSONResponse(status_code=400, content={"error": "Name and URL are required"})

    try:
        with db_service.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO git_repositories (name, url, branch, auth_token, provider, auth_user, auto_sync, webhook_secret)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (repo.name.strip(), repo.url.strip(), repo.branch or "main", repo.auth_token, repo.provider or "github", repo.auth_user,
                 1 if repo.auto_sync else 0, repo.webhook_secret)
            )
            conn.commit()
            repo_id = cursor.lastrowid

        threading.Thread(
            target=idx_service.sync_single_git_repo,
            args=(repo_id,)
        ).start()

        return {"status": "success", "id": repo_id}
    except sqlite3.IntegrityError:
        return JSONResponse(status_code=400, content={"error": f"Repository with name '{repo.name}' already exists"})
    except Exception as e:
        logger.error(f"Error adding repo: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.patch("/admin/api/repos/{repo_id}/auto-sync")
async def api_toggle_repo_auto_sync(repo_id: int, payload: AutoSyncToggleRequest):
    try:
        updated = db_service.set_repo_auto_sync(repo_id, payload.auto_sync)
        if not updated:
            return JSONResponse(status_code=404, content={"error": f"Repository with ID {repo_id} not found"})
        return {"status": "success", "id": repo_id, "repo_id": repo_id, "auto_sync": payload.auto_sync}
    except Exception as e:
        logger.error(f"Error toggling auto-sync for repo {repo_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/repos/{repo_id}/sync")
@router.post("/admin/api/repos/sync/{repo_id}")
async def api_sync_repo(repo_id: int):
    try:
        with db_service.get_db_connection() as conn:
            row = conn.execute("SELECT * FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": "Repo not found"})
            r = dict(row)

        threading.Thread(
            target=idx_service.sync_single_git_repo,
            args=(r["id"],)
        ).start()

        return {"status": "success", "repo": r["name"], "message": f"Sync started for {r['name']}"}
    except Exception as e:
        logger.error(f"Error syncing repo {repo_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/repos/{repo_id}")
async def api_delete_repo(repo_id: int):
    try:
        with db_service.get_db_connection() as conn:
            row = conn.execute("SELECT name FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": "Repo not found"})
            name = row["name"]

            conn.execute("DELETE FROM git_repositories WHERE id = ?", (repo_id,))
            for table in ("indexed_files", "ast_symbols", "ast_relationships", "api_routes"):
                try:
                    conn.execute(f"DELETE FROM {table} WHERE repo = ?", (name,))
                except Exception:
                    pass
            conn.commit()

        try:
            store = vs_service.get_vector_store()
            store.delete_by_repo(name)
        except Exception as e:
            logger.error(f"Error removing points from vector database for {name}: {e}")

        return {"status": "success", "name": name, "deleted": name}
    except Exception as e:
        logger.error(f"Error deleting repo {repo_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/paths")
async def api_get_paths():
    try:
        with db_service.get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM indexed_paths ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error getting paths: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/paths")
async def api_add_path(config: LocalPathConfig):
    try:
        resolved = os.path.abspath(config.path)
        if not os.path.exists(resolved):
            return JSONResponse(status_code=400, content={"error": f"Path '{resolved}' does not exist on disk."})

        with db_service.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO indexed_paths (path, type, recursive, category, repo) VALUES (?, ?, ?, ?, ?)",
                (resolved, config.type, 1 if config.recursive else 0, config.category, config.repo or "local")
            )
            conn.commit()
            path_id = cursor.lastrowid

        threading.Thread(target=idx_service.run_full_indexing).start()
        return {"status": "success", "id": path_id, "path": resolved}
    except sqlite3.IntegrityError:
        return JSONResponse(status_code=400, content={"error": "Path already indexed"})
    except Exception as e:
        logger.error(f"Error adding path: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/paths/{path_id}")
async def api_delete_path(path_id: int):
    try:
        with db_service.get_db_connection() as conn:
            row = conn.execute("SELECT path FROM indexed_paths WHERE id = ?", (path_id,)).fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": "Path not found"})
            path_val = row["path"]

            conn.execute("DELETE FROM indexed_paths WHERE id = ?", (path_id,))
            conn.execute("DELETE FROM indexed_files WHERE filepath LIKE ?", (f"{path_val}%",))
            conn.commit()

        try:
            store = vs_service.get_vector_store()
            store.delete_by_path(path_val)
        except Exception as e:
            logger.error(f"Error removing points from vector DB for path {path_val}: {e}")

        return {"status": "success", "path": path_val, "deleted": path_val}
    except Exception as e:
        logger.error(f"Error deleting path {path_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/sync")
@router.post("/admin/api/reindex")
async def api_trigger_sync():
    is_idx = idx_service.is_indexing
    if (is_idx() if callable(is_idx) else is_idx):
        return JSONResponse(status_code=409, content={"status": "error", "error": "Indexing in progress", "message": "Indexing is already in progress."})
    
    threading.Thread(target=idx_service.run_full_indexing, daemon=True).start()
    return {"status": "success", "message": "Background ingestion pipeline dispatched."}

@router.post("/admin/api/search/test")
async def api_test_search(payload: SearchRequest):
    try:
        query = payload.query.strip() if payload.query else ""
        if not query:
            return JSONResponse(status_code=400, content={"error": "Query required"})

        hits = search_service.execute_hybrid_search(
            query_text=query,
            doc_type=payload.type,
            repo=payload.repo,
            limit=payload.limit or 6
        )
        results = []
        for h in hits:
            results.append({
                "score": round(getattr(h, "score", 0.0), 4),
                "payload": getattr(h, "payload", {})
            })
        return {"query": query, "type": payload.type, "results": results}
    except Exception as e:
        logger.error(f"Error testing search: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

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
        logger.error(f"Error browsing dir {path}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

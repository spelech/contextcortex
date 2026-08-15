import os
import re
import json
import sqlite3
import threading
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.db import (
    get_db_connection, get_metadata, set_metadata, 
    get_effective_github_token, get_token_source, CACHE_DB_PATH
)
from app.services.git_manager import check_github_rate_limit, mask_token

# Assuming the other agent extracts these to app.services.indexer and app.services.embeddings
from app.services.indexer import (
    sync_single_git_repo, run_full_indexing, is_indexing
)
from app.services.embeddings import (
    EMBEDDING_PROVIDER, DENSE_MODEL_NAME, SPARSE_MODEL_NAME,
    qdrant, COLLECTION_NAME
)

router = APIRouter()

@router.get("/admin/api/stats")
async def api_get_stats():
    try:
        with get_db_connection() as conn:
            files_count = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]
            paths_count = conn.execute("SELECT count(*) FROM indexed_paths").fetchone()[0]
            repos_count = conn.execute("SELECT count(*) FROM git_repositories").fetchone()[0]
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]
            last_indexed = get_metadata("last_indexed", "Never")

            sum_rows = conn.execute("SELECT keywords FROM file_summaries").fetchall()
            kw_counts = {}
            for sr in sum_rows:
                if sr["keywords"]:
                    try:
                        for kw in json.loads(sr["keywords"]):
                            kw_counts[kw] = kw_counts.get(kw, 0) + 1
                    except Exception:
                        pass
            top_keywords = sorted(kw_counts.keys(), key=lambda k: kw_counts[k], reverse=True)[:25]

        points_count = 0
        if qdrant.collection_exists(COLLECTION_NAME):
            info = qdrant.get_collection(COLLECTION_NAME)
            points_count = info.points_count

        eff_token = get_effective_github_token()
        rate_info = check_github_rate_limit(eff_token)

        return {
            "files_count": files_count,
            "paths_count": paths_count,
            "repos_count": repos_count,
            "symbols_count": symbols_count,
            "points_count": points_count,
            "is_indexing": is_indexing,
            "last_indexed": last_indexed,
            "embedding_provider": EMBEDDING_PROVIDER.upper(),
            "dense_model": DENSE_MODEL_NAME,
            "sparse_model": SPARSE_MODEL_NAME,
            "top_keywords": top_keywords,
            "token_source": get_token_source(),
            "masked_token": mask_token(eff_token),
            "rate_limit": rate_info
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/repos")
async def api_get_repos():
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT id, name, url, branch, commit_sha, enabled, status, last_synced, added_at, (SELECT count(*) FROM indexed_files WHERE repo = git_repositories.name) as file_count FROM git_repositories ORDER BY added_at DESC").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/repos")
async def api_add_repo(request: Request):
    try:
        data = await request.json()
        name = data.get("name", "").strip()
        url = data.get("url", "").strip()
        branch = data.get("branch", "main").strip() or "main"
        token = data.get("auth_token", "").strip() or None

        if not name or not url:
            return JSONResponse(status_code=400, content={"error": "Repository name and Git URL are required."})

        name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name).lower()

        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO git_repositories (name, url, branch, auth_token) VALUES (?, ?, ?, ?)",
                (name, url, branch, token)
            )
            conn.commit()
            repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        threading.Thread(target=sync_single_git_repo, args=(repo_id,), daemon=True).start()
        return {"status": "success", "message": f"Added repo '{name}' and started background sync."}
    except sqlite3.IntegrityError:
        return JSONResponse(status_code=400, content={"error": f"Repository '{name}' is already registered."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/repos/sync/{repo_id}")
async def api_sync_repo(repo_id: int):
    try:
        threading.Thread(target=sync_single_git_repo, args=(repo_id,), daemon=True).start()
        return {"status": "success", "message": f"Sync triggered for repository ID {repo_id}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/repos/{repo_id}")
async def api_delete_repo(repo_id: int):
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT name FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": "Repo not found"})
            repo_name = row["name"]
            conn.execute("DELETE FROM git_repositories WHERE id = ?", (repo_id,))
            conn.execute("DELETE FROM indexed_files WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM file_summaries WHERE repo = ?", (repo_name,))
            conn.execute("DELETE FROM ast_symbols WHERE repo = ?", (repo_name,))
            conn.commit()

        # Delete from Qdrant
        try:
            from qdrant_client.http import models as qmodels
            qdrant.delete(
                collection_name=COLLECTION_NAME,
                points_selector=qmodels.Filter(
                    must=[qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo_name))]
                )
            )
        except Exception:
            pass

        return {"status": "success", "message": f"Deleted repository '{repo_name}'"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/paths")
async def api_get_paths():
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT id, path, type, recursive, enabled, category, repo, added_at FROM indexed_paths ORDER BY added_at DESC").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/paths")
async def api_add_path(request: Request):
    try:
        data = await request.json()
        path = data.get("path")
        ptype = data.get("type", "directory")
        recursive = int(data.get("recursive", 1))
        enabled = int(data.get("enabled", 1))
        category = data.get("category")
        repo = data.get("repo", "local") or "local"

        if not path or not os.path.exists(path):
            return JSONResponse(status_code=400, content={"error": f"Valid local path is required: {path}"})

        path = os.path.abspath(path)
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO indexed_paths (path, type, recursive, enabled, category, repo) VALUES (?, ?, ?, ?, ?, ?)",
                (path, ptype, recursive, enabled, category, repo)
            )
            conn.commit()

        threading.Thread(target=run_full_indexing, daemon=True).start()
        return {"status": "success", "message": f"Added local path: {path}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/paths/{path_id}")
async def api_delete_path(path_id: int):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM indexed_paths WHERE id = ?", (path_id,))
            conn.commit()
        threading.Thread(target=run_full_indexing, daemon=True).start()
        return {"status": "success", "message": f"Deleted path ID {path_id}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/settings/token")
async def api_set_token(request: Request):
    try:
        data = await request.json()
        token = data.get("github_token", "").strip()
        set_metadata("github_token", token)
        eff_token = get_effective_github_token()
        rate_info = check_github_rate_limit(eff_token)
        return {
            "status": "success",
            "message": "GitHub token updated",
            "token_source": get_token_source(),
            "masked_token": mask_token(eff_token),
            "rate_limit": rate_info
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/search/test")
async def api_test_search(request: Request):
    try:
        data = await request.json()
        query = data.get("query", "").strip()
        search_type = data.get("type", "code") # "code" or "doc"
        repo = data.get("repo") or None

        if not query:
            return JSONResponse(status_code=400, content={"error": "Query required"})

        from app.services.search import execute_hybrid_search
        hits = execute_hybrid_search(query_text=query, doc_type=search_type, repo=repo, limit=6)
        results = []
        for h in hits:
            results.append({
                "score": round(h.score, 4),
                "payload": h.payload
            })
        return {"query": query, "type": search_type, "results": results}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/reindex")
async def api_trigger_reindex():
    if is_indexing:
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

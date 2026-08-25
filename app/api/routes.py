import os
import re
import json
import sqlite3
import threading
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
from app.api.webhooks import router as webhook_router

router = APIRouter()
router.include_router(webhook_router)



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
        try:
            store = get_vector_store()
            stats = store.get_stats()
            points_count = stats.get("points_count", 0)
        except Exception:
            points_count = 0


        gh_token, _, gh_src = get_effective_git_token("https://github.com", provider="github")

        gl_token, _, gl_src = get_effective_git_token("https://gitlab.com", provider="gitlab")
        gt_token, _, gt_src = get_effective_git_token("https://gitea.com", provider="gitea")
        rate_info = check_github_rate_limit(gh_token)

        vs_provider = "qdrant"
        vs_mode = "embedded"
        vs_collection = COLLECTION_NAME
        try:
            vs_cfg = get_vector_store_config()
            vs_provider = vs_cfg.get("provider", "qdrant")
            vs_mode = vs_cfg.get("mode", "embedded")
            vs_collection = vs_cfg.get("collection", COLLECTION_NAME)
        except Exception:
            pass

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
            "vector_store_provider": vs_provider,
            "vector_store_mode": vs_mode,
            "vector_store_collection": vs_collection,
            "top_keywords": top_keywords,
            "token_source": gh_src,
            "masked_token": mask_token(gh_token),
            "providers_auth": {
                "github": {"token_source": gh_src, "masked_token": mask_token(gh_token)},
                "gitlab": {"token_source": gl_src, "masked_token": mask_token(gl_token)},
                "gitea": {"token_source": gt_src, "masked_token": mask_token(gt_token)},
            },
            "rate_limit": rate_info
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/repos")
async def api_get_repos():
    try:
        with get_db_connection() as conn:
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

        with get_db_connection() as conn:
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
        with get_db_connection() as conn:
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

        # Delete from vector store
        try:
            store = get_vector_store()
            store.delete_by_repo(repo_name)
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
        with get_db_connection() as conn:
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
        with get_db_connection() as conn:
            row = conn.execute("SELECT path FROM indexed_paths WHERE id = ?", (path_id,)).fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": f"Path ID {path_id} not found."})
            conn.execute("DELETE FROM indexed_paths WHERE id = ?", (path_id,))
            conn.commit()
        threading.Thread(target=run_full_indexing, daemon=True).start()
        return {"status": "success", "message": f"Deleted path ID {path_id}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/settings/hosts")
async def api_get_host_credentials():
    try:
        from app.services.db import list_git_host_credentials
        from app.services.git_manager import mask_token
        rows = list_git_host_credentials()
        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "host": r["host"],
                "provider": r["provider"],
                "auth_user": r.get("auth_user"),
                "masked_token": mask_token(r.get("auth_token")),
                "added_at": r.get("added_at")
            })
        return results
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/settings/hosts")
async def api_save_host_credential(payload: HostCredentialRequest):
    try:
        from app.services.db import save_git_host_credential
        host = payload.host.strip()
        token = payload.auth_token.strip()
        provider = payload.provider.strip().lower()
        auth_user = payload.auth_user.strip() if payload.auth_user else None

        if not host or not token:
            return JSONResponse(status_code=400, content={"error": "Host domain and auth token are required."})

        save_git_host_credential(host=host, provider=provider, auth_token=token, auth_user=auth_user)
        return {"status": "success", "message": f"Saved credential for host '{host}'"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/settings/hosts/{host_id}")
async def api_delete_host_credential(host_id: str):
    try:
        from app.services.db import delete_git_host_credential
        delete_git_host_credential(host_id)
        return {"status": "success", "message": f"Deleted host credential '{host_id}'"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/settings/token")
async def api_set_token(payload: TokenRequest):
    try:
        if payload.github_token is not None:
            set_metadata("github_token", payload.github_token.strip())
        if payload.gitlab_token is not None:
            set_metadata("gitlab_token", payload.gitlab_token.strip())
        if payload.gitea_token is not None:
            set_metadata("gitea_token", payload.gitea_token.strip())

        gh_token, _, gh_src = get_effective_git_token("https://github.com", provider="github")
        gl_token, _, gl_src = get_effective_git_token("https://gitlab.com", provider="gitlab")
        gt_token, _, gt_src = get_effective_git_token("https://gitea.com", provider="gitea")
        rate_info = check_github_rate_limit(gh_token)

        return {
            "status": "success",
            "message": "Tokens updated successfully",
            "token_source": gh_src,
            "masked_token": mask_token(gh_token),
            "providers_auth": {
                "github": {"token_source": gh_src, "masked_token": mask_token(gh_token)},
                "gitlab": {"token_source": gl_src, "masked_token": mask_token(gl_token)},
                "gitea": {"token_source": gt_src, "masked_token": mask_token(gt_token)},
            },
            "rate_limit": rate_info
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/settings/auto-sync")
async def api_get_auto_sync_settings():
    try:
        from app.services.db import get_auto_sync_interval, get_global_webhook_secret
        interval = get_auto_sync_interval()
        secret = get_global_webhook_secret()
        return {
            "interval_mins": interval,
            "webhook_url": "/api/webhooks/git",
            "has_global_secret": bool(secret)
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/settings/auto-sync")
async def api_update_auto_sync_settings(payload: AutoSyncSettingsRequest):
    try:
        from app.services.db import set_auto_sync_interval, set_global_webhook_secret, get_global_webhook_secret
        set_auto_sync_interval(payload.interval_mins)
        if payload.global_webhook_secret is not None:
            set_global_webhook_secret(payload.global_webhook_secret)
        secret = get_global_webhook_secret()
        return {
            "status": "success",
            "interval_mins": payload.interval_mins,
            "has_global_secret": bool(secret)
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/search/test")
async def api_test_search(payload: SearchRequest):
    try:
        query = payload.query.strip()
        search_type = payload.type
        repo = payload.repo

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

@router.get("/admin/api/logs")
async def api_get_logs(limit: int = 200, level: Optional[str] = None, search: Optional[str] = None):
    try:
        return get_diagnostic_logs(limit=limit, level=level, search=search)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/logs")
async def api_clear_logs():
    try:
        clear_diagnostic_logs()
        return {"status": "success", "message": "Diagnostic logs cleared"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/admin/api/vector-store")
async def api_get_vector_store():
    try:
        cfg = get_vector_store_config()
        cfg["points_count"] = cfg.get("stats", {}).get("points_count", 0)
        return cfg
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/admin/api/vector-store/test")
async def api_test_vector_store(payload: VectorStoreTestRequest):
    try:
        success, message = test_vector_store_connection(
            provider=payload.provider,
            mode=payload.mode,
            storage_path=payload.storage_path,
            url=payload.url,
            collection=payload.collection,
        )
        return {"success": success, "message": message}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e), "error": str(e)})


@router.post("/admin/api/vector-store/switch")
async def api_switch_vector_store(payload: VectorStoreSwitchRequest):
    try:
        def _reindex():
            threading.Thread(target=run_full_indexing, daemon=True).start()

        success, message = switch_vector_store(
            provider=payload.provider,
            mode=payload.mode,
            storage_path=payload.storage_path,
            url=payload.url,
            collection=payload.collection,
            reindex_callback=_reindex,
        )
        if not success:
            return JSONResponse(status_code=400, content={"status": "error", "error": message, "message": message})

        return {
            "status": "success",
            "message": message,
            "config": get_vector_store_config(),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e), "message": str(e)})


@router.get("/admin/api/graph/topology")
async def api_get_graph_topology(
    repo: str,
    view_type: str = "files",
    depth: int = 2,
    root_node: Optional[str] = None,
    limit: int = 300
):
    try:
        data = get_topology_graph(
            repo=repo,
            view_type=view_type,
            depth=depth,
            root_node=root_node,
            limit=limit
        )
        if data is None:
            return JSONResponse(
                status_code=404,
                content={
                    "error": f"Repository '{repo}' not found",
                    "nodes": [],
                    "edges": [],
                    "stats": {"node_count": 0, "edge_count": 0}
                }
            )
        return data
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/admin/api/graph/node-details")
async def api_get_graph_node_details(id: str):
    try:
        details = get_node_details(id)
        if not details:
            return JSONResponse(status_code=404, content={"error": f"Node '{id}' not found"})
        return details
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})




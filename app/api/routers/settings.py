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

@router.get("/admin/api/stats")
async def api_get_stats():
    try:
        with _get_r_attr("get_db_connection", get_db_connection)() as conn:
            files_count = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]
            paths_count = conn.execute("SELECT count(*) FROM indexed_paths").fetchone()[0]
            repos_count = conn.execute("SELECT count(*) FROM git_repositories").fetchone()[0]
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]
            last_indexed = _get_r_attr("get_metadata", get_metadata)("last_indexed", "Never")

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
            store = _get_r_attr("get_vector_store", get_vector_store)()
            stats = store.get_stats()
            points_count = stats.get("points_count", 0)
        except Exception:
            points_count = 0


        gh_token, _, gh_src = _get_r_attr("get_effective_git_token", get_effective_git_token)("https://github.com", provider="github")

        gl_token, _, gl_src = _get_r_attr("get_effective_git_token", get_effective_git_token)("https://gitlab.com", provider="gitlab")
        gt_token, _, gt_src = _get_r_attr("get_effective_git_token", get_effective_git_token)("https://gitea.com", provider="gitea")
        rate_info = _get_r_attr("check_github_rate_limit", check_github_rate_limit)(gh_token)

        vs_provider = "qdrant"
        vs_mode = "embedded"
        vs_collection = COLLECTION_NAME
        try:
            vs_cfg = _get_r_attr("get_vector_store_config", get_vector_store_config)()
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
            "is_indexing": _get_r_attr("is_indexing", is_indexing),
            "last_indexed": last_indexed,
            "embedding_provider": EMBEDDING_PROVIDER.upper(),
            "dense_model": DENSE_MODEL_NAME,
            "sparse_model": SPARSE_MODEL_NAME,
            "vector_store_provider": vs_provider,
            "vector_store_mode": vs_mode,
            "vector_store_collection": vs_collection,
            "top_keywords": top_keywords,
            "token_source": gh_src,
            "masked_token": _get_r_attr("mask_token", mask_token)(gh_token),
            "providers_auth": {
                "github": {"token_source": gh_src, "masked_token": _get_r_attr("mask_token", mask_token)(gh_token)},
                "gitlab": {"token_source": gl_src, "masked_token": _get_r_attr("mask_token", mask_token)(gl_token)},
                "gitea": {"token_source": gt_src, "masked_token": _get_r_attr("mask_token", mask_token)(gt_token)},
            },
            "rate_limit": rate_info
        }
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
                "masked_token": _get_r_attr("mask_token", mask_token)(r.get("auth_token")),
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
            _get_r_attr("set_metadata", set_metadata)("github_token", payload.github_token.strip())
        if payload.gitlab_token is not None:
            _get_r_attr("set_metadata", set_metadata)("gitlab_token", payload.gitlab_token.strip())
        if payload.gitea_token is not None:
            _get_r_attr("set_metadata", set_metadata)("gitea_token", payload.gitea_token.strip())

        gh_token, _, gh_src = _get_r_attr("get_effective_git_token", get_effective_git_token)("https://github.com", provider="github")
        gl_token, _, gl_src = _get_r_attr("get_effective_git_token", get_effective_git_token)("https://gitlab.com", provider="gitlab")
        gt_token, _, gt_src = _get_r_attr("get_effective_git_token", get_effective_git_token)("https://gitea.com", provider="gitea")
        rate_info = _get_r_attr("check_github_rate_limit", check_github_rate_limit)(gh_token)

        return {
            "status": "success",
            "message": "Tokens updated successfully",
            "token_source": gh_src,
            "masked_token": _get_r_attr("mask_token", mask_token)(gh_token),
            "providers_auth": {
                "github": {"token_source": gh_src, "masked_token": _get_r_attr("mask_token", mask_token)(gh_token)},
                "gitlab": {"token_source": gl_src, "masked_token": _get_r_attr("mask_token", mask_token)(gl_token)},
                "gitea": {"token_source": gt_src, "masked_token": _get_r_attr("mask_token", mask_token)(gt_token)},
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

@router.get("/admin/api/logs")
async def api_get_logs(limit: int = 200, level: Optional[str] = None, search: Optional[str] = None):
    try:
        return _get_r_attr("get_diagnostic_logs", get_diagnostic_logs)(limit=limit, level=level, search=search)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/logs")
async def api_clear_logs():
    try:
        _get_r_attr("clear_diagnostic_logs", clear_diagnostic_logs)()
        return {"status": "success", "message": "Diagnostic logs cleared"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/admin/api/vector-store")
async def api_get_vector_store():
    try:
        cfg = _get_r_attr("get_vector_store_config", get_vector_store_config)()
        cfg["points_count"] = cfg.get("stats", {}).get("points_count", 0)
        return cfg
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/admin/api/vector-store/test")
async def api_test_vector_store(payload: VectorStoreTestRequest):
    try:
        success, message = _get_r_attr("test_vector_store_connection", test_vector_store_connection)(
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

        success, message = _get_r_attr("switch_vector_store", switch_vector_store)(
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
            "config": _get_r_attr("get_vector_store_config", get_vector_store_config)(),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e), "message": str(e)})



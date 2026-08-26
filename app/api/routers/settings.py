import os
import re
import json
import sqlite3
import logging
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.schemas import (
    TokenRequest, HostCredentialRequest,
    VectorStoreTestRequest, VectorStoreSwitchRequest,
    AutoSyncSettingsRequest, EmbeddingSettingsRequest
)
import app.services.database as db_service
import app.services.git_manager as gm_service
import app.services.logger as log_service
import app.services.vector_store as vs_service
import app.services.indexing as idx_service
import app.services.embeddings as emb_service

logger = logging.getLogger("contextcortex.api")

router = APIRouter()

@router.get("/admin/api/stats")
async def api_get_stats():
    try:
        with db_service.get_db_connection() as conn:
            def _count(table):
                try:
                    return conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()["c"]
                except Exception:
                    return 0

            file_count = _count("indexed_files")
            repo_count = _count("git_repositories")
            path_count = _count("indexed_paths")
            total_symbols = _count("ast_symbols")
            total_relationships = _count("ast_relationships")
            total_routes = _count("api_routes")
            last_indexed = db_service.get_metadata("last_indexed", "Never")

            top_keywords = []
            try:
                sum_rows = conn.execute("SELECT keywords FROM file_summaries WHERE keywords IS NOT NULL").fetchall()
                kw_counts = {}
                for sr in sum_rows:
                    try:
                        kws = json.loads(sr["keywords"])
                        for k in kws:
                            kw_counts[k] = kw_counts.get(k, 0) + 1
                    except Exception:
                        pass
                top_keywords = [k for k, _ in sorted(kw_counts.items(), key=lambda x: x[1], reverse=True)[:10]]
            except Exception:
                pass

            total_chunks = 0
            vector_db_healthy = False
            vector_db_status = "Unknown"
            try:
                store = vs_service.get_vector_store()
                stats = store.get_stats()
                total_chunks = stats.get("points_count", 0)
                vector_db_healthy = stats.get("healthy", False)
                vector_db_status = "Healthy" if vector_db_healthy else "Unhealthy"
            except Exception as e:
                vector_db_status = f"Error: {e}"

        gh_token, _, gh_src = db_service.get_effective_git_token("https://github.com", provider="github")
        gl_token, _, gl_src = db_service.get_effective_git_token("https://gitlab.com", provider="gitlab")
        gt_token, _, gt_src = db_service.get_effective_git_token("https://gitea.com", provider="gitea")
        rate_info = gm_service.check_github_rate_limit(gh_token)

        try:
            vs_cfg = vs_service.get_vector_store_config()
        except Exception:
            vs_cfg = {
                "provider": "unknown",
                "mode": "unknown",
                "storage_path": None,
                "url": None,
                "collection": idx_service.COLLECTION_NAME,
                "healthy": vector_db_healthy,
                "points_count": total_chunks
            }

        is_idx = idx_service.is_indexing
        emb_cfg = emb_service.get_embedding_config()
        return {
            "repos_count": repo_count,
            "git_repos": repo_count,
            "files_count": file_count,
            "indexed_files": file_count,
            "symbols_count": total_symbols,
            "total_symbols": total_symbols,
            "total_chunks": total_chunks,
            "points_count": total_chunks,
            "total_relationships": total_relationships,
            "total_routes": total_routes,
            "local_paths": path_count,
            "last_indexed": last_indexed,
            "is_indexing": is_idx() if callable(is_idx) else is_idx,
            "vector_db_status": vector_db_status,
            "vector_store": vs_cfg,
            "vector_store_provider": vs_cfg.get("provider"),
            "vector_store_mode": vs_cfg.get("mode"),
            "vector_store_collection": vs_cfg.get("collection"),
            "top_keywords": top_keywords,
            "embedding_provider": emb_cfg["provider"],
            "dense_model": emb_cfg["dense_model"],
            "sparse_model": emb_cfg["sparse_model"],
            "embedding_threads": emb_cfg["threads"],
            "embedding_batch_size": emb_cfg["batch_size"],
            "system_cpus": emb_cfg.get("system_cpus", 2),
            "system_memory_gb": emb_cfg.get("system_memory_gb", 4.0),
            "rate_limit": rate_info,
            "token_source": gh_src,
            "masked_token": gm_service.mask_token(gh_token),
            "providers_auth": {
                "github": {"token_source": gh_src, "masked_token": gm_service.mask_token(gh_token)},
                "gitlab": {"token_source": gl_src, "masked_token": gm_service.mask_token(gl_token)},
                "gitea": {"token_source": gt_src, "masked_token": gm_service.mask_token(gt_token)}
            }
        }
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/settings/hosts")
async def api_get_host_credentials():
    try:
        hosts = db_service.list_git_host_credentials()
        safe_hosts = []
        for r in hosts:
            safe_hosts.append({
                "id": r["id"],
                "host": r["host"],
                "provider": r["provider"],
                "auth_user": r.get("auth_user"),
                "masked_token": gm_service.mask_token(r.get("auth_token")),
                "added_at": r["added_at"]
            })
        return safe_hosts
    except Exception as e:
        logger.error(f"Error listing host credentials: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/settings/hosts")
async def api_save_host_credential(payload: HostCredentialRequest):
    try:
        host_id = db_service.save_git_host_credential(
            host=payload.host,
            provider=payload.provider,
            auth_token=payload.auth_token,
            auth_user=payload.auth_user
        )
        return {"status": "success", "id": host_id, "host": payload.host}
    except sqlite3.IntegrityError:
        return JSONResponse(status_code=400, content={"error": f"Credentials for host '{payload.host}' already exist"})
    except Exception as e:
        logger.error(f"Error saving host credential: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/settings/hosts/{host_id}")
async def api_delete_host_credential(host_id: int):
    try:
        deleted = db_service.delete_git_host_credential(host_id)
        if not deleted:
            return JSONResponse(status_code=404, content={"error": "Host credential not found"})
        return {"status": "success", "id": host_id}
    except Exception as e:
        logger.error(f"Error deleting host credential: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/settings/token")
async def api_save_token(payload: TokenRequest):
    try:
        if payload.github_token is not None:
            db_service.set_metadata("github_token", payload.github_token.strip())
        if payload.gitlab_token is not None:
            db_service.set_metadata("gitlab_token", payload.gitlab_token.strip())
        if payload.gitea_token is not None:
            db_service.set_metadata("gitea_token", payload.gitea_token.strip())

        gh_token, _, gh_src = db_service.get_effective_git_token("https://github.com", provider="github")
        gl_token, _, gl_src = db_service.get_effective_git_token("https://gitlab.com", provider="gitlab")
        gt_token, _, gt_src = db_service.get_effective_git_token("https://gitea.com", provider="gitea")
        rate_info = gm_service.check_github_rate_limit(gh_token)

        return {
            "status": "success",
            "message": "Tokens updated successfully",
            "token_source": gh_src,
            "masked_token": gm_service.mask_token(gh_token),
            "rate_limit": rate_info,
            "providers_auth": {
                "github": {"token_source": gh_src, "masked_token": gm_service.mask_token(gh_token)},
                "gitlab": {"token_source": gl_src, "masked_token": gm_service.mask_token(gl_token)},
                "gitea": {"token_source": gt_src, "masked_token": gm_service.mask_token(gt_token)}
            }
        }
    except Exception as e:
        logger.error(f"Error saving tokens: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/settings/auto-sync")
async def api_get_auto_sync_settings():
    try:
        interval = db_service.get_auto_sync_interval()
        secret = db_service.get_global_webhook_secret()
        return {
            "interval_mins": interval,
            "webhook_url": "/api/webhooks/git",
            "has_global_secret": bool(secret and secret.strip())
        }
    except Exception as e:
        logger.error(f"Error loading auto-sync settings: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/settings/auto-sync")
async def api_save_auto_sync_settings(payload: AutoSyncSettingsRequest):
    try:
        if payload.interval_mins is not None:
            db_service.set_auto_sync_interval(payload.interval_mins)

        if payload.global_webhook_secret is not None:
            db_service.set_global_webhook_secret(payload.global_webhook_secret)

        current_secret = db_service.get_global_webhook_secret()
        return {
            "status": "success",
            "interval_mins": db_service.get_auto_sync_interval(),
            "webhook_url": "/api/webhooks/git",
            "has_global_secret": bool(current_secret and current_secret.strip())
        }
    except Exception as e:
        logger.error(f"Error saving auto-sync settings: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/logs")
async def api_get_logs(limit: int = 200, level: Optional[str] = None, search: Optional[str] = None):
    try:
        return log_service.get_diagnostic_logs(limit=limit, level=level, search=search)
    except Exception as e:
        logger.error(f"Error fetching diagnostic logs: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/logs")
async def api_clear_logs():
    try:
        log_service.clear_diagnostic_logs()
        return {"status": "success", "message": "Diagnostic logs successfully cleared."}
    except Exception as e:
        logger.error(f"Error clearing diagnostic logs: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/vector-store")
async def api_get_vector_store():
    try:
        cfg = vs_service.get_vector_store_config()
        cfg["points_count"] = cfg.get("stats", {}).get("points_count", cfg.get("points_count", 0))
        return cfg
    except Exception as e:
        logger.error(f"Error reading vector store config: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/vector-store/test")
async def api_test_vector_store(payload: VectorStoreTestRequest):
    try:
        success, message = vs_service.test_vector_store_connection(
            provider=payload.provider,
            mode=payload.mode,
            storage_path=payload.storage_path,
            url=payload.url,
            collection=payload.collection
        )
        return {
            "success": success,
            "message": message,
            "provider": payload.provider,
            "mode": payload.mode
        }
    except Exception as e:
        logger.error(f"Error testing vector store: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e), "message": str(e)})

@router.post("/admin/api/vector-store/switch")
async def api_switch_vector_store(payload: VectorStoreSwitchRequest):
    try:
        def _reindex():
            threading.Thread(target=idx_service.run_full_indexing, daemon=True).start()

        success, message = vs_service.switch_vector_store(
            provider=payload.provider,
            mode=payload.mode,
            storage_path=payload.storage_path,
            url=payload.url,
            collection=payload.collection,
            reindex_callback=_reindex
        )
        if not success:
            return JSONResponse(status_code=400, content={"status": "error", "error": message, "message": message})

        return {
            "status": "success",
            "message": message,
            "provider": payload.provider,
            "mode": payload.mode,
            "config": vs_service.get_vector_store_config()
        }
    except Exception as e:
        logger.error(f"Error switching vector store backend: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e), "message": str(e)})

@router.get("/admin/api/settings/embedding")
async def api_get_embedding_settings():
    try:
        cfg = emb_service.get_embedding_config()
        return cfg
    except Exception as e:
        logger.error(f"Error reading embedding settings: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/admin/api/settings/embedding")
async def api_save_embedding_settings(payload: EmbeddingSettingsRequest):
    try:
        updated_cfg = emb_service.update_embedding_config(
            provider=payload.provider,
            dense_model=payload.dense_model,
            sparse_model=payload.sparse_model,
            threads=payload.threads,
            batch_size=payload.batch_size,
            litellm_url=payload.litellm_url,
            litellm_api_key=payload.litellm_api_key,
        )
        return {
            "status": "success",
            "message": "Embedding engine settings updated successfully.",
            "config": updated_cfg
        }
    except Exception as e:
        logger.error(f"Error updating embedding settings: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e), "message": str(e)})


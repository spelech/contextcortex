import logging
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.services.database import get_db_connection
from app.services.local_storage import get_local_storage_service

logger = logging.getLogger("contextcortex.api.ingestion")
router = APIRouter()

@router.get("/admin/api/ingestion/catalog")
async def api_get_ingestion_catalog(
    source_type: str = Query("all", description="Source type filter"),
    repo_name: Optional[str] = Query(None, description="Repository filter"),
    path_prefix: Optional[str] = Query(None, description="Path prefix filter"),
    file_extension: Optional[str] = Query(None, description="Extension filter"),
    detail_level: str = Query("summary", description="Detail level: summary or detailed")
):
    try:
        with get_db_connection() as conn:
            git_repos = [dict(r) for r in conn.execute("SELECT id, name, url, branch, commit_sha, provider, status, last_synced FROM git_repositories").fetchall()]
            indexed_paths = [dict(r) for r in conn.execute("SELECT path, repo, category FROM indexed_paths WHERE enabled = 1").fetchall()]
            counts = {r["repo"]: r["cnt"] for r in conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()}
            for gr in git_repos:
                gr["file_count"] = counts.get(gr["name"], 0)
            for ip in indexed_paths:
                ip["file_count"] = counts.get(ip["repo"], 0)

            detailed_files = []
            if detail_level == "detailed":
                q = "SELECT filepath, repo, doc_type, language, mtime FROM indexed_files WHERE 1=1"
                p = []
                if repo_name:
                    q += " AND repo = ?"
                    p.append(repo_name)
                if path_prefix:
                    q += " AND filepath LIKE ?"
                    p.append(f"%{path_prefix}%")
                if file_extension:
                    q += " AND filepath LIKE ?"
                    p.append(f"%{file_extension}")
                q += " ORDER BY repo, filepath LIMIT 300"
                detailed_files = [dict(r) for r in conn.execute(q, p).fetchall()]

        storage = get_local_storage_service()
        tree = storage.get_file_tree()

        return {
            "source_type": source_type,
            "detail_level": detail_level,
            "git_repositories": git_repos if source_type in ("all", "git") else [],
            "monitored_paths": indexed_paths if source_type in ("all", "monitored_path") else [],
            "local_storage": {
                "root_path": storage.get_storage_root(),
                "file_count": counts.get("local_storage", len(tree.get("files", []))),
                "tree": tree
            } if source_type in ("all", "local_storage") else None,
            "files": detailed_files if detail_level == "detailed" else []
        }
    except Exception as e:
        logger.error(f"Error fetching ingestion catalog: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

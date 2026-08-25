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

@router.get("/admin/api/graph/topology")
async def api_get_graph_topology(
    repo: str,
    view_type: str = "files",
    depth: int = 2,
    root_node: Optional[str] = None,
    limit: int = 300
):
    try:
        data = _get_r_attr("get_topology_graph", get_topology_graph)(
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
        details = _get_r_attr("get_node_details", get_node_details)(id)
        if not details:
            return JSONResponse(status_code=404, content={"error": f"Node '{id}' not found"})
        return details
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})




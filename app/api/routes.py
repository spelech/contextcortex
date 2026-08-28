"""
Admin REST API Router
Mounts modular sub-routers: webhooks, repositories, settings, and graph topology.
"""
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
from app.services.database import (
    get_db_connection, get_metadata, set_metadata, 
    get_effective_git_token, CACHE_DB_PATH
)
from app.services.git_manager import check_github_rate_limit, mask_token
from app.services.logger import get_diagnostic_logs, clear_diagnostic_logs
from app.services.vector_store import (
    get_vector_store, get_vector_store_config, switch_vector_store, test_vector_store_connection
)
from app.services.topology import get_topology_graph, get_node_details
from app.services.indexing import (
    sync_single_git_repo, run_full_indexing, is_indexing, COLLECTION_NAME
)
from app.services.embeddings import (
    EMBEDDING_PROVIDER, DENSE_MODEL_NAME, SPARSE_MODEL_NAME,
    get_embedding_config, update_embedding_config
)
from app.api.webhooks import router as webhook_router
from app.api.routers.repositories import router as repositories_router
from app.api.routers.settings import router as settings_router
from app.api.routers.graph import router as graph_router
from app.api.routers.auth import router as auth_router, get_current_auth, require_role

logger = logging.getLogger("contextcortex.api")

router = APIRouter()
router.include_router(webhook_router)
router.include_router(repositories_router)
router.include_router(settings_router)
router.include_router(graph_router)
router.include_router(auth_router)

__all__ = [
    "router",
    "get_db_connection",
    "get_metadata",
    "set_metadata",
    "get_effective_git_token",
    "CACHE_DB_PATH",
    "check_github_rate_limit",
    "mask_token",
    "get_diagnostic_logs",
    "clear_diagnostic_logs",
    "get_vector_store",
    "get_vector_store_config",
    "switch_vector_store",
    "test_vector_store_connection",
    "get_topology_graph",
    "get_node_details",
    "sync_single_git_repo",
    "run_full_indexing",
    "is_indexing",
    "COLLECTION_NAME",
    "get_embedding_config",
    "update_embedding_config",
]

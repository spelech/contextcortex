import os
import re
import json
import sqlite3
import logging
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.services.topology as topo_service

logger = logging.getLogger("contextcortex.api")

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
        data = topo_service.get_topology_graph(
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
        logger.error(f"Error generating topology graph: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/graph/node-details")
async def api_get_graph_node_details(id: str):
    try:
        details = topo_service.get_node_details(id)
        if not details:
            return JSONResponse(
                status_code=404,
                content={"error": f"Node '{id}' not found"}
            )
        return details
    except Exception as e:
        logger.error(f"Error getting node details for {id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

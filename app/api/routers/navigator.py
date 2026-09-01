import logging
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

import app.services.navigator as nav_service

logger = logging.getLogger("contextcortex.api.navigator")

router = APIRouter()


@router.get("/admin/api/navigator/tree")
async def api_get_navigator_tree(
    repo: str = Query(..., description="Repository name or '__all__'")
):
    try:
        data = nav_service.get_navigator_tree(repo=repo)
        if data is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"Repository '{repo}' not found", "tree": []}
            )
        return data
    except Exception as e:
        logger.error(f"Error generating navigator tree for {repo}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/admin/api/navigator/file-outline")
async def api_get_file_outline(
    repo: str = Query(..., description="Repository name or '__all__'"),
    filepath: str = Query(..., description="Relative file path")
):
    try:
        data = nav_service.get_file_outline(repo=repo, filepath=filepath)
        if data is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"File '{filepath}' not found in repository '{repo}'", "symbols": []}
            )
        return data
    except Exception as e:
        logger.error(f"Error getting file outline for {filepath} in {repo}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/admin/api/navigator/symbol-impact")
async def api_get_symbol_impact(
    repo: str = Query(..., description="Repository name or '__all__'"),
    symbol_id: int = Query(..., description="AST symbol ID")
):
    try:
        data = nav_service.get_symbol_impact(repo=repo, symbol_id=symbol_id)
        if data is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"Symbol ID '{symbol_id}' not found"}
            )
        return data
    except Exception as e:
        logger.error(f"Error getting symbol impact for {symbol_id} in {repo}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

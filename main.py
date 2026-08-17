import os
import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as admin_router
from app.mcp.mcp_server import mcp_server

from app.services.db import init_db
from app.services.indexer import run_full_indexing, VAULT_PATH

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("knowledge-rag-mcp")

# Initialize database
try:
    init_db(VAULT_PATH)
except Exception as e:
    logger.error(f"Failed to init DB: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.services.indexer as indexer
    indexer.main_event_loop = asyncio.get_running_loop()
    logger.info("Knowledge RAG Server starting up...")
    try:
        threading.Thread(target=run_full_indexing, daemon=True).start()
    except Exception as e:
        logger.error(f"Startup indexing error: {e}")

    async with mcp_server.session_manager.run():
        yield

    logger.info("Knowledge RAG Server shutting down...")

app = FastAPI(title="Knowledge RAG MCP Server", version="2.4.2", lifespan=lifespan)

# Include API routes
app.include_router(admin_router)

@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/admin/")

www_dir = "frontend/dist" if os.path.exists("frontend/dist/index.html") else "www"
assets_dir = os.path.join(www_dir, "assets") if os.path.exists(os.path.join(www_dir, "assets")) else "www/assets"

app.mount("/admin", StaticFiles(directory=www_dir, html=True), name="admin")
app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

# Mount FastMCP SSE and Streamable HTTP endpoints
for route in mcp_server.sse_app().routes:
    app.routes.append(route)

for route in mcp_server.streamable_http_app().routes:
    app.routes.append(route)

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "healthy"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)

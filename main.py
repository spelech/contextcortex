import os
import asyncio
import anyio
import logging
import threading
from contextlib import AsyncExitStack

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as admin_router
from app.mcp.mcp_server import mcp_server, sse_transport

# Assuming init_db and VAULT_PATH are moved to app.services.db
from app.services.db import init_db

# Assuming run_full_indexing is extracted to app.services.indexer
from app.services.indexer import run_full_indexing, VAULT_PATH

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("notes-rag-mcp")

# Initialize database
try:
    init_db(VAULT_PATH)
except Exception as e:
    logger.error(f"Failed to init DB: {e}")

main_event_loop = None

def trigger_list_changed_notification():
    # In MCP v2.0.0, to notify clients we would use mcp_server.session_manager.
    # However since we are not using streamable_http_app we skip broadcasting for now.
    pass

# Try patching the indexer so it can notify when done
try:
    import app.services.indexer as indexer
    indexer.trigger_list_changed_notification = trigger_list_changed_notification
except Exception:
    pass

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()
    logger.info("Notes & Code RAG Server starting up...")
    try:
        threading.Thread(target=run_full_indexing, daemon=True).start()
    except Exception as e:
        logger.error(f"Startup indexing error: {e}")
    yield
    logger.info("Notes & Code RAG Server shutting down...")

app = FastAPI(title="Notes & Code RAG MCP Server", lifespan=lifespan)

# Include API routes
app.include_router(admin_router)

@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/admin/")

app.mount("/admin", StaticFiles(directory="www", html=True), name="admin")
app.mount("/assets", StaticFiles(directory="www/assets"), name="assets")

@app.get("/sse")
async def sse_endpoint(request: Request):
    logger.info("New SSE client connection requested.")
    async with sse_transport.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
        initialization_options = mcp_server.create_initialization_options()
        # the run() method internally handles lifespan, session initialization and the message loop
        await mcp_server.run(read_stream, write_stream, initialization_options)
        
app.mount("/messages", sse_transport.handle_post_message)

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "healthy"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)

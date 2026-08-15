import os
import asyncio
import anyio
import logging
import threading
from contextlib import AsyncExitStack

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from mcp.server.session import ServerSession

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

# Application state for MCP SSE
active_sessions = set()
main_event_loop = None

async def notify_list_changed():
    if not active_sessions:
        return
    logger.info(f"Sending list_changed notifications to {len(active_sessions)} active sessions...")
    for session in list(active_sessions):
        try:
            await session.send_tool_list_changed()
            await session.send_prompt_list_changed()
            await session.send_resource_list_changed()
        except Exception as e:
            logger.warning(f"Failed to send list_changed notification to session: {e}")

def trigger_list_changed_notification():
    if main_event_loop and main_event_loop.is_running():
        asyncio.run_coroutine_threadsafe(notify_list_changed(), main_event_loop)

# Try patching the indexer so it can notify when done
try:
    import app.services.indexer as indexer
    indexer.trigger_list_changed_notification = trigger_list_changed_notification
except Exception:
    pass

app = FastAPI(title="Notes & Code RAG MCP Server")

# Include API routes
app.include_router(admin_router)

@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/admin/")

app.mount("/admin", StaticFiles(directory="www", html=True), name="admin")

@app.get("/sse")
async def sse_endpoint(request: Request):
    logger.info("New SSE client connection requested.")
    async with sse_transport.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
        initialization_options = mcp_server.create_initialization_options()
        async with AsyncExitStack() as stack:
            lifespan_context = await stack.enter_async_context(mcp_server.lifespan(mcp_server))
            session = await stack.enter_async_context(ServerSession(read_stream, write_stream, initialization_options))
            active_sessions.add(session)
            logger.info(f"Registered active session {session}. Total active: {len(active_sessions)}")
            try:
                async with anyio.create_task_group() as tg:
                    try:
                        async for message in session.incoming_messages:
                            tg.start_soon(mcp_server._handle_message, message, session, lifespan_context, False)
                    finally:
                        tg.cancel_scope.cancel()
            finally:
                active_sessions.discard(session)
                logger.info(f"Unregistered session {session}. Remaining active: {len(active_sessions)}")

app.mount("/messages", sse_transport.handle_post_message)

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "healthy"})

@app.on_event("startup")
async def startup_event():
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()
    logger.info("Notes & Code RAG Server starting up...")
    try:
        threading.Thread(target=run_full_indexing, daemon=True).start()
    except Exception as e:
        logger.error(f"Startup indexing error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)

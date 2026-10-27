"""
ContextCortex Main Application Server.
Provides FastAPI entrypoint, ASGI Authentication Middleware (MCP 2026-07-28 RFC 9728),
Static Admin UI mounting, FastMCP SSE / Streamable HTTP routing, and container cold-start resilience.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
import threading

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.api.routes import router as admin_router
from app.mcp.mcp_server import mcp_server
from app.services.auth import (
    AuthenticationError,
    ForbiddenError,
    get_auth_service,
    set_current_auth_context,
)
from app.services.database import init_db
import app.services.indexing as indexer
from app.services.indexing import run_full_indexing, VAULT_PATH
from app.services.poller import start_poller_daemon, stop_poller_daemon
from app.services.vector_store.manager import VectorStoreManager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("contextcortex")


class McpNotificationFilter(logging.Filter):
    """Filters out premature MCP notification warnings caused by client race conditions."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "Failed to validate notification" in msg and "notifications/roots/list_changed" in msg:
            return False
        return True


logging.getLogger().addFilter(McpNotificationFilter())
logging.getLogger("mcp").addFilter(McpNotificationFilter())


def init_application_database() -> None:
    """
    Initializes database schema, seeds default configurations,
    and bootstraps initial admin API credentials if configured.
    """
    try:
        init_db(VAULT_PATH)
        admin_initial_key = os.getenv("ADMIN_INITIAL_KEY")
        if admin_initial_key:
            auth_service = get_auth_service()
            key = auth_service.bootstrap_admin_key(admin_initial_key)
            if key and key.secret_key:
                logger.info(f"Admin API key initialized successfully (prefix: {key.key_prefix})")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")


# Initialize database on module load
init_application_database()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager handling startup indexing, polling daemons, and clean shutdown."""
    indexer.main_event_loop = asyncio.get_running_loop()
    logger.info("ContextCortex Server starting up...")

    # Ensure database connection & bootstrapping is verified on startup
    init_application_database()

    try:
        threading.Thread(target=run_full_indexing, daemon=True).start()
    except Exception as e:
        logger.error(f"Startup indexing error: {e}")

    try:
        start_poller_daemon()
    except Exception as e:
        logger.error(f"Startup poller daemon error: {e}")

    if hasattr(mcp_server.session_manager, "_has_started"):
        mcp_server.session_manager._has_started = False

    async with mcp_server.session_manager.run():
        yield

    if hasattr(mcp_server.session_manager, "_has_started"):
        mcp_server.session_manager._has_started = False

    logger.info("ContextCortex Server shutting down...")
    try:
        stop_poller_daemon()
    except Exception as e:
        logger.error(f"Shutdown poller daemon error: {e}")

    try:
        VectorStoreManager.reset_instance()
    except Exception:
        pass


class McpPingMiddleware:
    """
    Lightweight MCP JSON-RPC ping interceptor.
    Bypasses SSE stream allocation, AnyIO task groups, and session memory accumulation
    when clients (e.g. ModelContextGateway) ping the server for liveness verification.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        path = scope.get("path", "").rstrip("/") or "/"

        # Check if request targets an MCP endpoint with POST
        if method == "POST" and path in ("/mcp", "/sse", "/messages", ""):
            body = b""
            more_body = True
            while more_body:
                message = await receive()
                body += message.get("body", b"")
                more_body = message.get("more_body", False)

            if b"ping" in body:
                try:
                    payload = json.loads(body.decode("utf-8"))
                    if isinstance(payload, dict) and payload.get("method") == "ping":
                        req_id = payload.get("id")
                        response_body = json.dumps({
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {},
                        }).encode("utf-8")
                        await send({
                            "type": "http.response.start",
                            "status": 200,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"cache-control", b"no-cache, no-transform"),
                                (b"content-length", str(len(response_body)).encode("latin1")),
                            ],
                        })
                        await send({
                            "type": "http.response.body",
                            "body": response_body,
                        })
                        return
                except Exception:
                    pass

            # Not a ping: replay buffered body to downstream app
            body_consumed = False

            async def replay_receive():
                nonlocal body_consumed
                if not body_consumed:
                    body_consumed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await self.app(scope, replay_receive, send)
            return

        await self.app(scope, receive, send)


class AuthMiddleware:
    """
    ASGI Authentication Middleware enforcing Bearer token / API key security
    when AUTH_ENABLED=true, while allowing public access to metadata, health,
    webhooks, and static frontend assets.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        # Public bypass routes
        if (
            path == "/.well-known/oauth-protected-resource"
            or path == "/health"
            or path == "/healthz"
            or path == "/"
            or path == "/favicon.svg"
            or path == "/favicon.ico"
            or path.startswith("/assets")
            or (path.startswith("/admin") and not path.startswith("/admin/api"))
            or path.startswith("/api/webhooks")
        ):
            await self.app(scope, receive, send)
            return

        auth_service = get_auth_service()
        if not auth_service.is_auth_enabled():
            bypass_ctx = auth_service.authenticate_token(None)
            set_current_auth_context(bypass_ctx)
            try:
                await self.app(scope, receive, send)
            finally:
                set_current_auth_context(None)
            return

        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("latin1")

        try:
            auth_ctx = auth_service.authenticate_token(auth_header)
            set_current_auth_context(auth_ctx)
            try:
                await self.app(scope, receive, send)
            finally:
                set_current_auth_context(None)
        except AuthenticationError as e:
            resource_indicator = auth_service.resource_indicator
            res_meta = f"{resource_indicator}/.well-known/oauth-protected-resource"
            www_auth = f'Bearer error="invalid_token", error_description="{str(e)}", resource_metadata="{res_meta}"'
            body = json.dumps({"detail": str(e), "error": "Unauthorized"}).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", www_auth.encode("latin1")),
                    (b"content-length", str(len(body)).encode("latin1")),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
        except ForbiddenError as e:
            body = json.dumps({"detail": str(e), "error": "Forbidden"}).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin1")),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })


app = FastAPI(title="ContextCortex", version="2.19.0", lifespan=lifespan)
app.add_middleware(AuthMiddleware)
app.add_middleware(McpPingMiddleware)

# Include API routes
app.include_router(admin_router)


@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/admin/")


if os.path.exists("frontend/dist/index.html") and os.path.exists("frontend/dist/assets"):
    www_dir = "frontend/dist"
elif os.path.exists("www/index.html") and os.path.exists("www/assets"):
    www_dir = "www"
elif os.path.exists("frontend/dist/index.html"):
    www_dir = "frontend/dist"
else:
    www_dir = "www"

assets_dir = os.path.join(www_dir, "assets")

app.mount("/admin", StaticFiles(directory=www_dir, html=True), name="admin")
app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/favicon.svg")
async def favicon_svg():
    svg_path = os.path.join(www_dir, "favicon.svg")
    if os.path.exists(svg_path):
        return FileResponse(svg_path, media_type="image/svg+xml")
    return JSONResponse(status_code=404, content={"detail": "Favicon not found"})


@app.get("/favicon.ico")
async def favicon_ico():
    ico_path = os.path.join(www_dir, "favicon.ico")
    if os.path.exists(ico_path):
        return FileResponse(ico_path)
    svg_path = os.path.join(www_dir, "favicon.svg")
    if os.path.exists(svg_path):
        return FileResponse(svg_path, media_type="image/svg+xml")
    return JSONResponse(status_code=404, content={"detail": "Favicon not found"})


# Mount FastMCP SSE and Streamable HTTP endpoints
for route in mcp_server.sse_app().routes:
    app.routes.append(route)

for route in mcp_server.streamable_http_app().routes:
    app.routes.append(route)


@app.get("/health")
@app.get("/healthz")
async def health():
    return JSONResponse(
        content={
            "status": "healthy",
            "protocolVersion": "2026-07-28",
            "server": "contextcortex",
        },
        headers={"Cache-Control": "no-cache, no-transform"},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)

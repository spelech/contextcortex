"""
Tests for native MCP JSON-RPC ping support and lightweight health verification.
Verifies that ping requests bypass SSE stream / session allocation entirely.
"""

import pytest
from httpx import AsyncClient, ASGITransport
import os
import sys

# Ensure www exists for StaticFiles mount
os.makedirs("www", exist_ok=True)

from main import app


@pytest.mark.asyncio
async def test_mcp_post_ping_streamable_mcp():
    """Verify POST /mcp with JSON-RPC ping returns immediate JSON without streaming."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"jsonrpc": "2.0", "id": "ping-42", "method": "ping"}
        response = await client.post("/mcp", json=payload)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "ping-42"
        assert data["result"] == {}


@pytest.mark.asyncio
async def test_mcp_post_ping_sse_endpoint():
    """Verify POST /sse with JSON-RPC ping returns immediate JSON."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"jsonrpc": "2.0", "id": 101, "method": "ping"}
        response = await client.post("/sse", json=payload)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 101
        assert data["result"] == {}


@pytest.mark.asyncio
async def test_mcp_post_ping_messages_endpoint():
    """Verify POST /messages with JSON-RPC ping returns immediate JSON."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"jsonrpc": "2.0", "id": "msg-ping", "method": "ping"}
        response = await client.post("/messages", json=payload)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "msg-ping"
        assert data["result"] == {}


@pytest.mark.asyncio
async def test_health_endpoints_enhanced_metadata():
    """Verify GET /health and /healthz return server metadata and protocol version."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/health", "/healthz"):
            response = await client.get(path)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data.get("protocolVersion") == "2026-07-28"
            assert data.get("server") == "contextcortex"
            assert "no-cache" in response.headers.get("cache-control", "")

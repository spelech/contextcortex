# MCP Protocol and Security Engine

This document describes the Model Context Protocol (MCP) transport implementation, zero-allocation JSON-RPC `ping` handling, and the OAuth 2.1 + API key security architecture.

---

## Model Context Protocol Overview

ContextCortex implements the official **Model Context Protocol (MCP) Specification** using the `FastMCP` 2.0 framework.

```mermaid
flowchart TD
    subgraph Clients["MCP Clients & Gateways"]
        Agent["AI Assistant / MCP Gateway<br/>(Cursor, Claude, Antigravity, MCG)"]
    end

    subgraph PingLayer["Zero-Allocation Liveness Interceptor"]
        PingMW{"McpPingMiddleware<br/>(method == 'ping'?)"}
        PongResp["Immediate HTTP 200 JSON-RPC Pong<br/>(No SSE or Session Allocation)"]
    end

    subgraph Transports["Supported MCP Transports"]
        SSE["Server-Sent Events (SSE)<br/>GET /sse & POST /messages/"]
        Streamable["Streamable HTTP<br/>POST /mcp"]
    end

    subgraph Security["Authentication & Authorization Layer"]
        TokenVal{"Validate Token / Key"}
        RBAC{"Check Role Permissions"}
    end

    subgraph FastMCPEngine["FastMCP 2.0 Engine"]
        Tools["16 MCP Tools"]
        Resources["Dynamic Catalog Resources"]
        Prompts["Guided System Prompts"]
    end

    Agent -->|JSON-RPC Request| PingMW
    PingMW -->|Yes (ping)| PongResp
    PingMW -->|No (Standard MCP Call)| SSE
    PingMW -->|No (Standard MCP Call)| Streamable

    SSE --> TokenVal
    Streamable --> TokenVal

    TokenVal -->|Valid Bearer / API Key| RBAC
    TokenVal -->|Invalid| Reject["401 Unauthorized"]

    RBAC -->|Authorized| FastMCPEngine
    RBAC -->|Insufficient Permissions| Forbidden["403 Forbidden"]

    FastMCPEngine --> Tools
    FastMCPEngine --> Resources
    FastMCPEngine --> Prompts
```

---

## Dual Transport Support & Lightweight Ping

ContextCortex provides two production MCP transports plus a dedicated JSON-RPC `ping` interceptor:

### 1. Server-Sent Events (SSE)
- **Endpoint**: `GET /sse`
- **Session Messaging**: `POST /messages/?session_id=<id>`
- **Behavior**: The client maintains an open HTTP event stream to receive server-to-client messages and notifications, and sends JSON-RPC requests via `/messages/`.

### 2. Streamable HTTP Transport
- **Endpoint**: `POST /mcp`
- **Behavior**: Direct bidirectional JSON-RPC exchange over standard HTTP requests. Simplifies integration with reverse proxies, gateways, and stateless environments.

### 3. Zero-Allocation JSON-RPC `ping` (`McpPingMiddleware`)
- **Endpoints**: `POST /mcp`, `POST /sse`, `POST /messages`
- **Behavior**: Upstream MCP routers and health checkers frequently send `{"jsonrpc": "2.0", "id": 1, "method": "ping"}` probes. `McpPingMiddleware` intercepts these requests at the ASGI boundary and returns `{"jsonrpc": "2.0", "id": 1, "result": {}}` immediately (`HTTP 200 OK`), bypassing FastMCP session creation, SSE stream allocation, and AnyIO task group overhead.

---

## RFC 9728 OAuth 2.1 and RBAC Security

When `AUTH_ENABLED=true`, ContextCortex operates as an **OAuth 2.1 Protected Resource Server**.

### RFC 9728 Protected Resource Metadata
Clients discover authorization requirements dynamically at:
`GET /.well-known/oauth-protected-resource`

Response payload:
```json
{
  "resource": "https://contextcortex.wileyriley.com",
  "authorization_servers": [
    "https://auth.wileyriley.com"
  ],
  "scopes_supported": [
    "mcp:viewer",
    "mcp:editor",
    "mcp:admin"
  ],
  "bearer_methods_supported": [
    "header"
  ]
}
```

### 3-Tier Role-Based Access Control (RBAC)

ContextCortex enforces three hierarchical permission levels:

| Role Name | Access Level | Permitted Actions |
| :--- | :---: | :--- |
| `viewer` | Level 10 | Search code and docs, find symbols, trace call paths, find API routes and callers, read and summarize files, view file outlines, list repositories, and inspect the ingestion catalog. |
| `editor` | Level 20 | All `viewer` permissions plus triggering repository synchronization, uploading/replacing/deleting managed local storage files, and creating or updating ADRs. |
| `admin` | Level 30 | All `editor` permissions plus modifying system configuration, switching vector databases, and managing API keys and Git host credentials. |

### API Key Verification
The system supports static bootstrap keys (`ADMIN_INITIAL_KEY`) and database-backed API keys:
- Keys use the prefix `cc_` followed by cryptographically random bytes.
- Keys are stored in the database as SHA-256 hashes (`key_hash`) with a visible prefix (`key_prefix`).
- Keys can be assigned specific roles (`viewer`, `editor`, `admin`) and optional expiration timestamps.
- Administrators can revoke keys immediately via the Admin REST API or Settings UI.

---

## Related Documentation
- [MCP Tools and Resources Reference](/reference/mcp-tools)
- [Admin REST API Reference](/reference/rest-api)
- [Database and Storage Schema](/architecture/database-schema)

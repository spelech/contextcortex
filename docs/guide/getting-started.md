# Getting Started

This guide describes the three ways to deploy, configure, and start ContextCortex:

| Deployment Mode | Relational Metadata DB | Vector Store | AI / Embeddings | Best For |
| :--- | :--- | :--- | :--- | :--- |
| **1. Docker / Compose** *(Recommended)* | **PostgreSQL 16** (or SQLite) | **PostgreSQL (`pgvector`)** or **Qdrant** (Remote or Embedded) | `OPENAI_API_URL` + `OPENAI_API_KEY` (discovered via `/v1/models`) | Production, homelab, and multi-container setups (`docker-compose.yml` / `docker-compose.enterprise.yml`) |
| **2. Windows Standalone Portable Bundle** | **Embedded User-Space PostgreSQL 16** (`pgvector` pre-bundled) | **Embedded `pgvector`** or **Embedded Qdrant** on local disk | `OPENAI_API_URL` + `OPENAI_API_KEY` (discovered via `/v1/models`) | Zero-dependency Windows workstations or enterprise deployments without Docker (`scripts/build_portable_windows.ps1`) |
| **3. Local Python (`venv`)** | **SQLite** (`data/index_cache.db`, zero-setup default) or external Postgres | **Embedded Qdrant** (`data/vector_storage`, zero-setup default) | `OPENAI_API_URL` + `OPENAI_API_KEY` configured in `.env` or Settings UI | Local development, rapid testing, or lightweight single-user CLI/MCP usage |

---

## Mode 1: Starting with Docker Compose (Recommended)

To deploy ContextCortex with PostgreSQL 16 (`pgvector`) or Qdrant in containers:

1. Copy `.env.example` to `.env` and set your `OPENAI_API_URL` and `OPENAI_API_KEY`:
   ```bash
   cp .env.example .env
   ```

2. Start the Docker Compose stack:
   ```bash
   docker compose up -d
   ```

3. Check the container status and logs:
   ```bash
   docker compose ps
   docker compose logs -f contextcortex
   ```

> [!TIP]
> **Restricted-Network & Private-CA Environments:** If your environment uses corporate TLS inspection, private CA certificates (`certs/*.crt`), or internal apt/pip/npm mirrors, use `docker-compose.enterprise.yml` or `Dockerfile.overlay`. See [Restricted-Network Builds](/guide/enterprise-build) for full instructions.

---

## Mode 2: Windows Standalone Portable Deployment

For Windows environments without Docker or administrator privileges, ContextCortex can be packaged into a self-contained portable folder (`dist\contextcortex-windows-x64`) containing the frozen `contextcortex.exe` server, user-space **Portable PostgreSQL 16** binaries, and pre-compiled **`pgvector`** (`vector.dll`):

1. Build the portable bundle from a Windows build machine:
   ```powershell
   .\scripts\build_portable_windows.ps1
   ```

2. Copy `dist\contextcortex-windows-x64` to your target Windows workstation, set `OPENAI_API_URL` and `OPENAI_API_KEY` in `.env`, and run:
   ```powershell
   .\start-contextcortex.bat
   ```

On first launch, the portable bundle automatically initializes a local PostgreSQL 16 + `pgvector` cluster under `.\data\pgdata`, loads any corporate CA certificates placed in `.\certs\*.crt`, and starts the web dashboard and MCP endpoints on `http://127.0.0.1:3000`.

---

## Mode 3: Local Python Installation (`venv`)

### Prerequisites

Make sure that your system meets these requirements:
- Python version 3.11 or later.
- Node.js version 20 or later with npm package manager.
- Git version 2.30 or later.

### Option A: Automated Setup Script

1. Clone the repository from GitHub:
   ```bash
   git clone git@github.com:spelech/contextcortex.git
   cd contextcortex
   ```

2. On Linux or macOS systems, run the setup script:
   ```bash
   ./setup.sh
   ```

3. On Windows systems, run the PowerShell setup script:
   ```powershell
   .\setup.ps1
   ```

### Option B: Manual Virtual Environment

1. Clone the repository and create a Python virtual environment:
   ```bash
   git clone git@github.com:spelech/contextcortex.git
   cd contextcortex
   python3 -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\Activate.ps1
   ```

2. Install Python dependencies and build frontend assets:
   ```bash
   pip install -r requirements.txt
   cd frontend && npm install && npm run build && cd ..
   ```

### Starting the Local Server

1. Start the server (uses local SQLite `data/index_cache.db` and embedded Qdrant `data/vector_storage` by default):
   ```bash
   python main.py
   ```

2. Verify that the server starts successfully:
   - Web Admin Dashboard: `http://localhost:3000/admin/`
   - MCP Server-Sent Events: `http://localhost:3000/sse`
   - MCP Streamable HTTP: `http://localhost:3000/mcp`
   - Health Check Probes: Liveness (`http://localhost:3000/health`, `/healthz`) and Readiness (`http://localhost:3000/ready`, `/readiness`, `/health/ready`)

3. Verify server health and MCP JSON-RPC `ping` readiness from a terminal:
   ```bash
   # HTTP process liveness probe
   curl -s http://localhost:3000/healthz

   # HTTP application readiness probe (verifies relational database & schema accessibility)
   curl -s http://localhost:3000/ready

   # Lightweight JSON-RPC ping (zero session allocation)
   curl -s -X POST http://localhost:3000/mcp \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
   ```

> [!NOTE]
> When `AUTH_ENABLED` is set to `false`, the server operates in local development mode without authentication prompts.

## First-Run Onboarding: Discovering & Selecting AI Gateway Models

ContextCortex discovers and configures your Embedding, Chat Summarization, and Vision OCR models directly from your OpenAI-compatible gateway:

1. Open the Web Admin Dashboard (`http://localhost:3000/admin/`) and navigate to **Settings** → **AI & Model Gateway**.
2. Enter your OpenAI-compatible gateway **API Endpoint URL** (`OPENAI_API_URL`, for example, `http://litellm:4000/v1` or `https://gateway.example.com/api/v3`) and **API Key** (`OPENAI_API_KEY`).
3. Click **Test Connection & Discover Models** (`/admin/api/models/discover`). ContextCortex queries your gateway's `/models` endpoint and populates the dropdowns with the exact models your endpoint serves.
4. Select your preferred **API Embedding Model**, **Chat Completion Model**, and **Vision OCR Model** from the discovered dropdowns, then click **Save AI Gateway Settings**.
5. *(Optional)* In **Settings** → **File & Summaries**, you can also pick a dedicated **Summarization Chat Model** or leave it inherited from your AI Gateway Chat Model.

> [!NOTE]
> Once saved in the UI, database-persisted gateway and model selections take precedence across restarts.

## Next Steps

- Open the [User Guide](/guide/user-guide) to explore dashboard components with screenshots.
- Review the [Configuration Guide](/guide/configuration) to set environment variables.
- Configure corporate mirrors and private CAs in [Restricted-Network Builds](/guide/enterprise-build).
- Connect your AI assistant using the [MCP Reference](/reference/mcp-tools).

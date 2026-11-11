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

### Docker Database & Vector Store Sub-Configurations

You can customize the relational metadata database and vector store engine in `.env` (or switch vector stores live at runtime under **Settings → Vector Database**):

| Sub-Configuration | Relational DB (`DATABASE_URL`) | Vector Store (`VECTOR_STORE_PROVIDER` / `VECTOR_STORE_MODE`) | `.env` / Compose Configuration |
| :--- | :--- | :--- | :--- |
| **1A. Bundled PostgreSQL 16 + `pgvector`** *(Default)* | `postgresql+psycopg://contextcortex:cortexsecret@postgres:5432/contextcortex` | `VECTOR_STORE_PROVIDER=pgvector` (`remote`) | Default in `docker-compose.yml` — stores both relational metadata and HNSW vectors in the `postgres` container. |
| **1B. PostgreSQL Metadata + Remote Qdrant** | `postgresql+psycopg://...` | `VECTOR_STORE_PROVIDER=qdrant`, `VECTOR_STORE_MODE=remote` | Set `VECTOR_STORE_PROVIDER=qdrant`, `VECTOR_STORE_MODE=remote`, and `QDRANT_URL=http://qdrant:6333` in `.env`. |
| **1C. PostgreSQL Metadata + Embedded Qdrant** | `postgresql+psycopg://...` | `VECTOR_STORE_PROVIDER=qdrant`, `VECTOR_STORE_MODE=embedded` | Set `VECTOR_STORE_PROVIDER=qdrant` and `VECTOR_STORE_MODE=embedded` to persist vectors on the `/app/data/vector_storage` volume. |
| **1D. Single-Container SQLite + Embedded Qdrant** | `sqlite:////app/data/index_cache.db` | `VECTOR_STORE_PROVIDER=qdrant`, `VECTOR_STORE_MODE=embedded` | Use `docker-compose.enterprise.yml` with `ENTERPRISE_DATABASE_URL=sqlite:////app/data/index_cache.db` and `ENTERPRISE_VECTOR_STORE_PROVIDER=qdrant` to run without the `postgres` service. |

> [!TIP]
> **Restricted-Network & Private-CA Environments:** If your environment uses corporate TLS inspection, private CA certificates (`certs/*.crt`), or internal apt/pip/npm mirrors, use `docker-compose.enterprise.yml` or `Dockerfile.overlay`. See [Restricted-Network Builds](/guide/enterprise-build) for full instructions.

---

## Mode 2: Windows Standalone Portable Deployment

For Windows environments without Docker or administrator privileges, ContextCortex can be packaged into a self-contained portable folder (`dist\contextcortex-windows-x64`) containing the frozen `contextcortex.exe` server, user-space **Portable PostgreSQL 16** binaries, and pre-compiled **`pgvector`** (`vector.dll`):

1. Build the portable bundle from a Windows build machine:
   ```powershell
   .\scripts\build_portable_windows.ps1
   ```

   You can also download the `contextcortex-windows-x64-portable` artifact from the **Build Portable Windows x64 Bundle** GitHub Actions workflow.

2. Copy `dist\contextcortex-windows-x64` to your target Windows workstation.

3. Copy `.env.example` to `.env`. Set these values **before the first start**:
   - `OPENAI_API_URL` and `OPENAI_API_KEY`.
   - `EMBEDDING_MODEL`: an embedding model that your gateway supplies. The bundle has no local embedding engine. The first start sets the vector table dimension from this model.
   - `LLM_EXTRA_HEADERS` (optional): a JSON object of headers that your gateway requires. Do not put quotes around the JSON.

4. If your network uses private CAs or a TLS inspection proxy, put the CA files (`.crt` or `.pem`) in `.\certs\`.

5. Run:
   ```powershell
   .\start-contextcortex.bat
   ```

On first start, the bundle does these steps:
- It makes a local PostgreSQL 16 + `pgvector` cluster in `.\data\pgdata`.
- It adds the CA files in `.\certs\` to the public root CAs and uses this bundle for HTTPS and Git.
- It starts the web dashboard and the MCP endpoints on `http://127.0.0.1:3000`.

All data stays in `.\data\`. To use a different folder, set `DATA_DIR` in `.env`. The launcher works with Windows PowerShell 5.1 and with PowerShell 7.

The bundle contains the tree-sitter grammar DLLs in `.\grammars\`. The app loads them from this folder and does not download grammars at runtime. To use a different folder, set `TREE_SITTER_LANGUAGE_PACK_CACHE_DIR` in `.env`.

> [!WARNING]
> **Error "start-contextcortex.ps1 is not digitally signed":** Windows marks files that you extract from a downloaded zip as "from the Internet". If Group Policy sets the execution policy to `RemoteSigned` or stricter, PowerShell does not run the marked launcher script, and `-ExecutionPolicy Bypass` cannot change this. Unblock the zip **before** you extract it (right-click the zip, select **Properties**, then select **Unblock**), or run this command in the bundle folder:
> ```powershell
> Get-ChildItem -Recurse -File | Unblock-File
> ```
> If Group Policy sets `AllSigned`, you must sign the script or ask your administrator.

> [!NOTE]
> **Endpoint protection (for example Carbon Black):** If your endpoint protection blocks DLLs, keep the bundle in a folder where it allows executables and DLLs. All the DLLs that the bundle loads are in its own folder (`_internal\`, `pgsql\`, and `grammars\`).

### Windows Portable Database & Vector Store Sub-Configurations

Edit `dist\contextcortex-windows-x64\.env` before running `start-contextcortex.bat` to choose how the standalone bundle stores metadata and vectors:

| Sub-Configuration | Relational DB | Vector Store | `.env` Configuration |
| :--- | :--- | :--- | :--- |
| **2A. Embedded Portable PostgreSQL 16 + `pgvector`** *(Default)* | Bundled `pgsql\bin\postgres.exe` on `127.0.0.1:54329` (`.\data\pgdata`) | `VECTOR_STORE_PROVIDER=pgvector` | `PORTABLE_POSTGRES_ENABLED=true`, `PORTABLE_PG_PORT=54329`, `VECTOR_STORE_PROVIDER=pgvector` |
| **2B. Embedded Portable PostgreSQL 16 + Embedded Qdrant** | Bundled `pgsql\bin\postgres.exe` (`.\data\pgdata`) | `VECTOR_STORE_PROVIDER=qdrant`, `VECTOR_STORE_MODE=embedded` | `PORTABLE_POSTGRES_ENABLED=true`, `VECTOR_STORE_PROVIDER=qdrant`, `VECTOR_STORE_MODE=embedded` |
| **2C. Local SQLite + Embedded Qdrant** *(No Postgres Subprocess)* | Local SQLite (`.\data\index_cache.db`) | `VECTOR_STORE_PROVIDER=qdrant`, `VECTOR_STORE_MODE=embedded` | `PORTABLE_POSTGRES_ENABLED=false`, `VECTOR_STORE_PROVIDER=qdrant`, `VECTOR_STORE_MODE=embedded` |
| **2D. External Corporate PostgreSQL / Remote Qdrant** | External `DATABASE_URL` | `pgvector` or remote `QDRANT_URL` | Set `DATABASE_URL=postgresql+psycopg://...` (automatically skips local portable Postgres bootstrap). |

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

### Local Python Database & Vector Store Sub-Configurations

Configure `.env` in the repository root to choose your local Python storage profile:

| Sub-Configuration | Relational DB (`DATABASE_URL`) | Vector Store (`VECTOR_STORE_PROVIDER`) | `.env` Configuration |
| :--- | :--- | :--- | :--- |
| **3A. Local SQLite + Embedded Qdrant** *(Zero-Setup Default)* | `data/index_cache.db` (default when `DATABASE_URL` is unset) | `qdrant` (`embedded` in `data/vector_storage`) | Only `OPENAI_API_URL` and `OPENAI_API_KEY` required in `.env`. |
| **3B. Local SQLite + Remote Qdrant** | `data/index_cache.db` | `qdrant` (`remote`) | Set `VECTOR_STORE_PROVIDER=qdrant`, `VECTOR_STORE_MODE=remote`, and `QDRANT_URL=http://localhost:6333`. |
| **3C. External PostgreSQL 16 + `pgvector`** | `postgresql+psycopg://user:pass@localhost:5432/contextcortex` | `pgvector` (`remote`) | Set `DATABASE_URL=postgresql+psycopg://...` and `VECTOR_STORE_PROVIDER=pgvector`. |
| **3D. External PostgreSQL 16 + Qdrant (Embedded or Remote)** | `postgresql+psycopg://user:pass@localhost:5432/contextcortex` | `qdrant` (`embedded` or `remote`) | Set `DATABASE_URL=postgresql+psycopg://...` and `VECTOR_STORE_PROVIDER=qdrant`. |

### Starting the Local Server

1. Start the server:
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

# Getting Started

This procedure describes how to install, configure, and start ContextCortex.

## Prerequisites

Make sure that your system meets these requirements:

- Python version 3.11 or later.
- Node.js version 20 or later with npm package manager.
- Git version 2.30 or later.
- Docker engine and Docker Compose (recommended for container deployment).

## Installation

You can install ContextCortex with the automated setup script or manual steps.

### Method 1: Automated Installation (Recommended)

Follow these steps for automated installation:

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

The script configures the Python virtual environment. It installs dependencies, compiles frontend assets, and verifies database readiness.

### Method 2: Manual Installation

Follow these steps for manual installation:

1. Clone the repository and change directory:
   ```bash
   git clone git@github.com:spelech/contextcortex.git
   cd contextcortex
   ```

2. Create a Python virtual environment:
   ```bash
   python3 -m venv venv
   ```

3. Activate the virtual environment:
   ```bash
   source venv/bin/activate
   ```
   On Windows systems, run:
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```

4. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Install frontend dependencies and build assets:
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```

## Starting the Service

1. Start the server with the default configuration:
   ```bash
   python main.py
   ```

2. Verify that the server starts successfully.
   The console displays the listening port and mounted endpoints:
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

## Starting with Docker Compose

To deploy ContextCortex with PostgreSQL 16, pgvector, and Qdrant in containers:

1. Start the Docker Compose stack:
   ```bash
   docker compose up -d
   ```

2. Check the container status:
   ```bash
   docker compose ps
   ```

3. View real-time container logs:
   ```bash
   docker compose logs -f contextcortex
   ```

> [!TIP]
> **Restricted-Network & Private-CA Environments:** If your environment uses corporate TLS inspection, private CA certificates (`certs/*.crt`), or internal apt/pip/npm mirrors, use `docker-compose.enterprise.yml` or `Dockerfile.overlay`. See [Restricted-Network Builds](/guide/enterprise-build) for full instructions.

## First-Run Onboarding: Discovering & Selecting AI Gateway Models

ContextCortex does not assume or hardcode upstream LLM model identifiers for executive file summarization (`CHAT_MODEL`) or scanned PDF vision OCR (`VISION_OCR_MODEL`). Instead, after starting the server, configure your models from the discovered endpoint catalog:

1. Open the Web Admin Dashboard (`http://localhost:3000/admin/`) and navigate to **Settings** → **AI Gateway & Models** (or **Embedding & Models**).
2. Enter your OpenAI-compatible gateway **Base URL** (for example, `http://litellm:4000/v1` or `https://gateway.example.com/api/v3`) and **API Key**.
3. Click **Discover Models** (`/admin/api/models/discover`). ContextCortex queries your gateway's `/models` endpoint and populates the dropdowns with the exact models your endpoint serves.
4. Select your preferred **Chat / Summarization Model** (e.g., `flash-latest`) and **Vision OCR Model** (e.g., `flash-latest` or `qwen3-vl`), then click **Save AI Gateway Configuration** (or **Save Embedding Settings**).
5. *(Optional)* In **Settings** → **Files & Summarization**, you can also click **Discover Models** to pick a dedicated **Summarization Chat Model** or leave it inherited from your AI Gateway Chat Model.

> [!NOTE]
> You can also pre-seed these models for headless/automated deployments via `CHAT_MODEL` and `VISION_OCR_MODEL` in `.env` before first startup; once saved in the UI, database-persisted model selections take precedence.

## Next Steps

- Open the [User Guide](/guide/user-guide) to explore dashboard components with screenshots.
- Review the [Configuration Guide](/guide/configuration) to set environment variables.
- Configure corporate mirrors and private CAs in [Restricted-Network Builds](/guide/enterprise-build).
- Connect your AI assistant using the [MCP Reference](/reference/mcp-tools).

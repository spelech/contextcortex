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
   - Health Check: `http://localhost:3000/healthz`

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
   docker compose logs -f app
   ```

## Next Steps

- Open the [User Guide](/guide/user-guide) to explore dashboard components with screenshots.
- Review the [Configuration Guide](/guide/configuration) to set environment variables.
- Connect your AI assistant using the [MCP Reference](/reference/mcp-tools).

#!/usr/bin/env bash
set -e

# ==============================================================================
# ContextCortex - Automated Setup Script (Linux & macOS)
# ==============================================================================

echo "======================================================================"
echo "🧠 Initializing ContextCortex Bare-Metal Environment"
echo "======================================================================"

# 1. Check Python 3.11+
PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "❌ Error: Python 3 is not installed or not in PATH."
    exit 1
fi

PY_VERSION=$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$($PYTHON_BIN -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$($PYTHON_BIN -c 'import sys; print(sys.version_info.minor)')

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]); then
    echo "❌ Error: Python 3.11 or newer is required (detected Python $PY_VERSION)."
    exit 1
fi
echo "✅ Python detected: $($PYTHON_BIN --version)"

# 2. Check Node.js and npm
if ! command -v node >/dev/null 2>&1; then
    echo "❌ Error: Node.js is not installed or not in PATH (v20+ recommended)."
    exit 1
fi
echo "✅ Node.js detected: $(node --version)"

if ! command -v npm >/dev/null 2>&1; then
    echo "❌ Error: npm is not installed or not in PATH."
    exit 1
fi
echo "✅ npm detected: v$(npm --version)"

# 3. Check Git
if ! command -v git >/dev/null 2>&1; then
    echo "❌ Error: Git is not installed or not in PATH."
    exit 1
fi
echo "✅ Git detected: $(git --version)"

# 4. Set up Python Virtual Environment
VENV_DIR="venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating Python virtual environment in './$VENV_DIR'..."
    $PYTHON_BIN -m venv "$VENV_DIR"
else
    echo "📦 Using existing Python virtual environment in './$VENV_DIR'."
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

echo "⬆️ Upgrading pip and installing backend dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# 5. Build Frontend React Dashboard
if [ -d "frontend" ]; then
    echo "⚛️ Setting up and compiling React 19 administrative dashboard..."
    cd frontend
    npm install
    npm run build
    cd ..
else
    echo "⚠️ Warning: 'frontend' directory not found; skipping frontend build."
fi

# 6. Ensure default runtime data directories exist
mkdir -p data/qdrant_storage data/chroma_db docs

echo ""
echo "======================================================================"
echo "🎉 ContextCortex Setup Complete!"
echo "======================================================================"
echo "To start the ContextCortex server, run:"
echo ""
echo "    source venv/bin/activate"
echo "    python main.py"
echo ""
echo "Available Endpoints:"
echo "  • Web Admin Dashboard:  http://localhost:3000/admin/"
echo "  • MCP SSE Transport:    http://localhost:3000/sse"
echo "  • MCP Streamable HTTP:  http://localhost:3000/mcp"
echo "  • System Health Check:  http://localhost:3000/health"
echo "======================================================================"

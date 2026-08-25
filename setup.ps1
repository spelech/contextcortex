# ==============================================================================
# ContextCortex - Automated Setup Script (Windows PowerShell)
# ==============================================================================

$ErrorActionPreference = "Stop"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "🧠 Initializing ContextCortex Bare-Metal Environment" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Check Python 3.11+
$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
} else {
    Write-Host "❌ Error: Python 3 is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

$pyVer = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$pyMajor = [int](& $pythonCmd -c "import sys; print(sys.version_info.major)")
$pyMinor = [int](& $pythonCmd -c "import sys; print(sys.version_info.minor)")

if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 11)) {
    Write-Host "❌ Error: Python 3.11 or newer is required (detected Python $pyVer)." -ForegroundColor Red
    exit 1
}
$pyFullVer = & $pythonCmd --version
Write-Host "✅ Python detected: $pyFullVer" -ForegroundColor Green

# 2. Check Node.js and npm
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Error: Node.js is not installed or not in PATH (v20+ recommended)." -ForegroundColor Red
    exit 1
}
$nodeVer = & node --version
Write-Host "✅ Node.js detected: $nodeVer" -ForegroundColor Green

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Error: npm is not installed or not in PATH." -ForegroundColor Red
    exit 1
}
$npmVer = & npm --version
Write-Host "✅ npm detected: v$npmVer" -ForegroundColor Green

# 3. Check Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Error: Git is not installed or not in PATH." -ForegroundColor Red
    exit 1
}
$gitVer = & git --version
Write-Host "✅ Git detected: $gitVer" -ForegroundColor Green

# 4. Set up Python Virtual Environment
$venvDir = "venv"
if (-not (Test-Path $venvDir)) {
    Write-Host "📦 Creating Python virtual environment in './$venvDir'..." -ForegroundColor Yellow
    & $pythonCmd -m venv $venvDir
} else {
    Write-Host "📦 Using existing Python virtual environment in './$venvDir'." -ForegroundColor Yellow
}

$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPip = Join-Path $venvDir "Scripts\pip.exe"

Write-Host "⬆️ Upgrading pip and installing backend dependencies..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip
& $venvPip install -r requirements.txt

# 5. Build Frontend React Dashboard
if (Test-Path "frontend") {
    Write-Host "⚛️ Setting up and compiling React 19 administrative dashboard..." -ForegroundColor Yellow
    Push-Location frontend
    npm install
    npm run build
    Pop-Location
} else {
    Write-Host "⚠️ Warning: 'frontend' directory not found; skipping frontend build." -ForegroundColor DarkYellow
}

# 6. Ensure default runtime data directories exist
New-Item -ItemType Directory -Force -Path "data\qdrant_storage" | Out-Null
New-Item -ItemType Directory -Force -Path "data\chroma_db" | Out-Null
New-Item -ItemType Directory -Force -Path "docs" | Out-Null

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "🎉 ContextCortex Setup Complete!" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "To start the ContextCortex server, run:" -ForegroundColor White
Write-Host ""
Write-Host "    .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host "    python main.py" -ForegroundColor Yellow
Write-Host ""
Write-Host "Available Endpoints:" -ForegroundColor White
Write-Host "  • Web Admin Dashboard:  http://localhost:3000/admin/" -ForegroundColor Gray
Write-Host "  • MCP SSE Transport:    http://localhost:3000/sse" -ForegroundColor Gray
Write-Host "  • MCP Streamable HTTP:  http://localhost:3000/mcp" -ForegroundColor Gray
Write-Host "  • System Health Check:  http://localhost:3000/health" -ForegroundColor Gray
Write-Host "======================================================================" -ForegroundColor Cyan

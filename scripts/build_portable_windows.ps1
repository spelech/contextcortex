# ==============================================================================
# ContextCortex Portable Bundle Assembly Script (Windows x64)
# ==============================================================================
# Assembles a zero-dependency, user-space Windows x64 distribution containing:
# 1. ContextCortex frozen executable (FastAPI + FastMCP + Tree-sitter AST + Dashboard)
# 2. Portable PostgreSQL 16 (Windows x64 user-space binaries: initdb, pg_ctl, postgres)
# 3. Pre-compiled pgvector extension (vector.dll, vector.control, vector--*.sql)
# 4. Corporate LiteLLM launch scripts (start-contextcortex.ps1 / start-contextcortex.bat)
# ==============================================================================

param(
    [string]$PostgresVersion = "16.6-1",
    [string]$PgVectorVersion = "0.8.0",
    [string]$OutputDir = "dist\contextcortex-windows-x64"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RootDir = (Resolve-Path ".").Path
Write-Host "Building ContextCortex Portable Bundle (Windows x64) in $RootDir..." -ForegroundColor Cyan

# 1. Build Frontend Bundle if not already built
if (-not (Test-Path "frontend\dist\index.html")) {
    Write-Host "Building React Frontend Dashboard..." -ForegroundColor Cyan
    Push-Location "frontend"
    npm ci
    npm run build
    Pop-Location
}

# 2. Run PyInstaller using contextcortex.spec
Write-Host "Running PyInstaller to freeze ContextCortex..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean contextcortex.spec

$FrozenDir = Join-Path $RootDir "dist\contextcortex"
if (-not (Test-Path (Join-Path $FrozenDir "contextcortex.exe"))) {
    throw "PyInstaller failed to produce dist\contextcortex\contextcortex.exe"
}

# 3. Prepare output bundle folder
$BundleDir = Join-Path $RootDir $OutputDir
if (Test-Path $BundleDir) {
    Remove-Item -Recurse -Force $BundleDir
}
New-Item -ItemType Directory -Path $BundleDir | Out-Null
Copy-Item -Path "$FrozenDir\*" -Destination $BundleDir -Recurse -Force

# 4. Download & Extract Portable PostgreSQL Windows x64 Binaries
$TempDir = Join-Path $env:TEMP "cc_pg_build"
if (Test-Path $TempDir) {
    Remove-Item -Recurse -Force $TempDir
}
New-Item -ItemType Directory -Path $TempDir | Out-Null

$PgZipUrl = "https://get.enterprisedb.com/postgresql/postgresql-$PostgresVersion-windows-x64-binaries.zip"
$PgZipPath = Join-Path $TempDir "postgresql-binaries.zip"
Write-Host "Downloading Portable PostgreSQL $PostgresVersion binaries..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $PgZipUrl -OutFile $PgZipPath

Write-Host "Extracting Portable PostgreSQL (bin, lib, share)..." -ForegroundColor Cyan
Expand-Archive -Path $PgZipPath -DestinationPath $TempDir -Force

$ExtractedPg = Join-Path $TempDir "pgsql"
$TargetPg = Join-Path $BundleDir "pgsql"
New-Item -ItemType Directory -Path $TargetPg | Out-Null

# Copy only runtime directories (skip pgAdmin 4, symbols, doc, include to keep bundle lean)
foreach ($sub in @("bin", "lib", "share")) {
    $srcSub = Join-Path $ExtractedPg $sub
    if (Test-Path $srcSub) {
        Copy-Item -Path $srcSub -Destination (Join-Path $TargetPg $sub) -Recurse -Force
    }
}

# 5. Compile or Install pgvector into Portable PostgreSQL
Write-Host "Building pgvector v$PgVectorVersion against Portable PostgreSQL..." -ForegroundColor Cyan
$PgVectorDir = Join-Path $TempDir "pgvector"
git clone --depth 1 --branch "v$PgVectorVersion" https://github.com/pgvector/pgvector.git $PgVectorDir

# Ensure MSVC environment is loaded if cl.exe is not in PATH
if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($vsPath) {
            $vcvars = Join-Path $vsPath "VC\Auxiliary\Build\vcvars64.bat"
            if (Test-Path $vcvars) {
                Write-Host "Loading Visual Studio x64 build environment..." -ForegroundColor Cyan
                $envDump = cmd.exe /c "`"$vcvars`" >nul && set"
                foreach ($line in $envDump) {
                    if ($line -match "^([^=]+)=(.*)$") {
                        [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
                    }
                }
            }
        }
    }
}

Push-Location $PgVectorDir
$env:PGROOT = $ExtractedPg
nmake /F Makefile.win
nmake /F Makefile.win install
Pop-Location

# Copy installed vector.dll and extension SQL/control files into target bundle
Copy-Item -Path (Join-Path $ExtractedPg "lib\vector.dll") -Destination (Join-Path $TargetPg "lib\vector.dll") -Force
Copy-Item -Path (Join-Path $ExtractedPg "share\extension\vector*") -Destination (Join-Path $TargetPg "share\extension\") -Force

# 6. Create Default Corporate .env.example and Launcher Scripts
$EnvTemplate = @"
# ==============================================================================
# ContextCortex Portable Edition (Windows x64 + User-Space PostgreSQL/pgvector)
# ==============================================================================
HOST=127.0.0.1
PORT=3000

# Portable PostgreSQL + pgvector (automatically initialized in .\data\pgdata)
PORTABLE_POSTGRES_ENABLED=true
PORTABLE_PG_PORT=54329
VECTOR_STORE=pgvector
VECTOR_STORE_PROVIDER=pgvector

# Corporate LiteLLM / OpenAI-Compatible Endpoint (Required for API Embeddings)
EMBEDDING_PROVIDER=api
SPARSE_MODEL=none
LITELLM_URL=https://litellm.corp.example.com/v1
LITELLM_API_KEY=your-corporate-api-key
EMBEDDING_MODEL=text-embedding-3-small
CHAT_MODEL=gpt-4o-mini
VISION_OCR_MODEL=gpt-4o

# Optional custom corporate headers (JSON format)
# LLM_EXTRA_HEADERS={"X-User-Agent":"contextcortex"}

# Optional Private Corporate CA Bundle path (.pem or .crt)
# SSL_CERT_FILE=.\certs\corporate-ca-bundle.crt
# REQUESTS_CA_BUNDLE=.\certs\corporate-ca-bundle.crt
"@
Set-Content -Path (Join-Path $BundleDir ".env.example") -Value $EnvTemplate -Encoding UTF8

$LauncherPs1 = @"
`$ErrorActionPreference = "Stop"
`$ScriptDir = Split-Path -Parent `$MyInvocation.MyCommand.Path
Set-Location `$ScriptDir

# Load .env file if present
`$EnvFile = Join-Path `$ScriptDir ".env"
if (-not (Test-Path `$EnvFile)) {
    Copy-Item (Join-Path `$ScriptDir ".env.example") `$EnvFile
    Write-Host "Created default .env from .env.example. Edit .env to set your corporate LITELLM_URL and LITELLM_API_KEY." -ForegroundColor Yellow
}

Get-Content `$EnvFile | ForEach-Object {
    `$line = `$_.Trim()
    if (`$line -and -not `$line.StartsWith("#") -and `$line.Contains("=")) {
        `$parts = `$line.Split("=", 2)
        `$key = `$parts[0].Trim()
        `$val = `$parts[1].Trim()
        [System.Environment]::SetEnvironmentVariable(`$key, `$val, "Process")
    }
}

# Configure custom CA certificate bundle if placed in .\certs\
`$CertsDir = Join-Path `$ScriptDir "certs"
if (Test-Path `$CertsDir) {
    `$CertFiles = Get-ChildItem -Path `$CertsDir -Filter "*.crt"
    if (`$CertFiles.Count -gt 0 -and -not `$env:SSL_CERT_FILE) {
        `$CombinedBundle = Join-Path `$ScriptDir "data\ca-bundle.crt"
        New-Item -ItemType Directory -Path (Join-Path `$ScriptDir "data") -Force | Out-Null
        `$Content = ""
        foreach (`$c in `$CertFiles) {
            `$Content += (Get-Content `$c.FullName -Raw) + "`n"
        }
        Set-Content -Path `$CombinedBundle -Value `$Content -Encoding ASCII
        `$env:SSL_CERT_FILE = `$CombinedBundle
        `$env:REQUESTS_CA_BUNDLE = `$CombinedBundle
        `$env:GIT_SSL_CAINFO = `$CombinedBundle
        Write-Host "Loaded corporate CA certificates from .\certs\" -ForegroundColor Green
    }
}

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "Starting ContextCortex Portable (PostgreSQL + pgvector + Tree-sitter)" -ForegroundColor Cyan
Write-Host "Admin UI:      http://127.0.0.1:`$(`$env:PORT ?? 3000)/admin/" -ForegroundColor Green
Write-Host "MCP SSE URL:   http://127.0.0.1:`$(`$env:PORT ?? 3000)/sse" -ForegroundColor Green
Write-Host "MCP HTTP URL:  http://127.0.0.1:`$(`$env:PORT ?? 3000)/mcp" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan

& (Join-Path `$ScriptDir "contextcortex.exe")
"@
Set-Content -Path (Join-Path $BundleDir "start-contextcortex.ps1") -Value $LauncherPs1 -Encoding UTF8

$LauncherBat = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-contextcortex.ps1"
"@
Set-Content -Path (Join-Path $BundleDir "start-contextcortex.bat") -Value $LauncherBat -Encoding ASCII

New-Item -ItemType Directory -Path (Join-Path $BundleDir "certs") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $BundleDir "data") -Force | Out-Null

Write-Host "Portable bundle assembled successfully at: $BundleDir" -ForegroundColor Green

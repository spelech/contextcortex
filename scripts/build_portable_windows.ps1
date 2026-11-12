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

# 3b. Pre-fetch tree-sitter grammar DLLs into .\grammars (the frozen app sets
# TREE_SITTER_LANGUAGE_PACK_CACHE_DIR to this folder). The bundle then needs no
# runtime download and loads no DLLs from %LOCALAPPDATA%. The language list comes
# from EXTENSION_TO_LANGUAGE in app/services/chunking/tree_sitter_loader.py.
Write-Host "Pre-fetching tree-sitter grammars into the bundle..." -ForegroundColor Cyan
$GrammarsDir = Join-Path $BundleDir "grammars"
$env:TREE_SITTER_LANGUAGE_PACK_CACHE_DIR = $GrammarsDir
python -c @"
import tree_sitter_language_pack as t
from app.services.chunking.tree_sitter_loader import EXTENSION_TO_LANGUAGE
langs = sorted({l for l in EXTENSION_TO_LANGUAGE.values() if l != 'text'})
if 'cobol' not in langs:
    raise SystemExit('Expected cobol in EXTENSION_TO_LANGUAGE grammar set')
# prefetch() accepts only download-manifest names (for example 'csharp', not 'c_sharp')
manifest = set(t.manifest_languages())
fetch = sorted({l if l in manifest else l.replace('_', '') for l in langs})
missing = [l for l in fetch if l not in manifest]
if missing:
    raise SystemExit('Grammars not in the download manifest: %s' % missing)
t.prefetch(fetch)
for l in langs:
    t.get_parser(l)
print('Pre-fetched %d grammars into %s' % (len(fetch), t.cache_dir()))
"@
if ($LASTEXITCODE -ne 0) { throw "tree-sitter grammar pre-fetch failed" }
Remove-Item Env:\TREE_SITTER_LANGUAGE_PACK_CACHE_DIR

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

# 6. Copy the .env template and launcher scripts (kept as real files in scripts\portable\)
$PortableSrc = Join-Path $RootDir "scripts\portable"
foreach ($f in @(".env.example", "start-contextcortex.ps1", "start-contextcortex.bat")) {
    Copy-Item -Path (Join-Path $PortableSrc $f) -Destination (Join-Path $BundleDir $f) -Force
}

New-Item -ItemType Directory -Path (Join-Path $BundleDir "certs") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $BundleDir "data") -Force | Out-Null

Write-Host "Portable bundle assembled successfully at: $BundleDir" -ForegroundColor Green

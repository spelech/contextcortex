# ==============================================================================
# ContextCortex Portable launcher (Windows x64)
# Compatible with Windows PowerShell 5.1 and PowerShell 7+.
# ==============================================================================
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Create .env from the template on first start
$EnvFile = Join-Path $ScriptDir ".env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $ScriptDir ".env.example") $EnvFile
    Write-Host "Created .env from .env.example. Edit .env to set OPENAI_API_URL, OPENAI_API_KEY, and LLM_EXTRA_HEADERS." -ForegroundColor Yellow
}

# Load .env into the process environment
foreach ($rawLine in Get-Content $EnvFile) {
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { continue }
    $parts = $line.Split("=", 2)
    $key = $parts[0].Trim()
    $val = $parts[1].Trim()
    if ($val.Length -ge 2 -and (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'")))) {
        $val = $val.Substring(1, $val.Length - 2)
    }
    [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
}

# Build a CA bundle: the public roots shipped with the app + every .crt/.pem in .\certs\
# (corporate root, subordinate, and TLS-inspection proxy CAs). The public roots stay in
# the bundle, so public HTTPS endpoints continue to work.
$CertsDir = Join-Path $ScriptDir "certs"
if (-not $env:SSL_CERT_FILE -and (Test-Path $CertsDir)) {
    $CertFiles = @(Get-ChildItem -Path $CertsDir -File | Where-Object { $_.Extension -in ".crt", ".pem" })
    if ($CertFiles.Count -gt 0) {
        $DataDir = Join-Path $ScriptDir "data"
        New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
        $CombinedBundle = Join-Path $DataDir "ca-bundle.crt"
        $Builder = New-Object System.Text.StringBuilder
        $PublicRoots = Join-Path $ScriptDir "_internal\certifi\cacert.pem"
        if (Test-Path $PublicRoots) {
            [void]$Builder.AppendLine((Get-Content $PublicRoots -Raw))
        }
        foreach ($c in $CertFiles) {
            [void]$Builder.AppendLine((Get-Content $c.FullName -Raw))
        }
        Set-Content -Path $CombinedBundle -Value $Builder.ToString() -Encoding ASCII
        $env:SSL_CERT_FILE = $CombinedBundle
        $env:REQUESTS_CA_BUNDLE = $CombinedBundle
        $env:GIT_SSL_CAINFO = $CombinedBundle
        Write-Host "Loaded $($CertFiles.Count) CA certificate file(s) from .\certs\" -ForegroundColor Green
    }
}

$Port = if ($env:PORT) { $env:PORT } else { "3000" }
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "Starting ContextCortex Portable (PostgreSQL + pgvector + Tree-sitter)" -ForegroundColor Cyan
Write-Host "Admin UI:      http://127.0.0.1:$Port/admin/" -ForegroundColor Green
Write-Host "MCP SSE URL:   http://127.0.0.1:$Port/sse" -ForegroundColor Green
Write-Host "MCP HTTP URL:  http://127.0.0.1:$Port/mcp" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop. PostgreSQL stops with the app." -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

& (Join-Path $ScriptDir "contextcortex.exe")
exit $LASTEXITCODE

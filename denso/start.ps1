# Start the full local stack: docling-serve (Docker) -> Ollama -> LightRAG server.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File <repo>\denso\start.ps1
#   -DoclingOnly   stop after docling-serve is healthy (enough to resume parsing)
param([switch]$DoclingOnly)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

# Through cmd: in Windows PowerShell 5.1 with ErrorActionPreference Stop, docker's stderr line
# ("failed to connect to the docker API") is a terminating error, so Docker was never started.
function Test-Docker { cmd /c "docker info >nul 2>&1"; return ($LASTEXITCODE -eq 0) }
Write-Host "[0/3] Docker Desktop"
if (-not (Test-Docker)) {
    # After a hard power-off Docker leaves broken AF_UNIX sockets behind and then
    # refuses to start ("The file cannot be accessed by the system"). Move the
    # socket folders aside (Docker recreates them) before starting it.
    if (-not (Get-Process "com.docker.backend" -ErrorAction SilentlyContinue)) {
        foreach ($p in "$env:LOCALAPPDATA\Docker\run", "$env:LOCALAPPDATA\docker-secrets-engine") {
            if (Test-Path $p) {
                $bad = Get-ChildItem $p -Force -ErrorAction SilentlyContinue | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
                if ($bad) {
                    Rename-Item $p ((Split-Path $p -Leaf) + ".stale-" + (Get-Date -Format yyyyMMddHHmmss))
                    Write-Host "  moved stale Docker sockets aside: $p"
                }
            }
        }
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    }
    $up = $false
    foreach ($i in 1..60) { Start-Sleep 3; if (Test-Docker) { $up = $true; break } }
    if (-not $up) { throw "Docker engine did not start; open Docker Desktop and check for an error dialog" }
}

Write-Host "[1/3] docling-serve"
cmd /c "docker compose -f `"$PSScriptRoot\docling\docker-compose.yml`" up -d 2>&1"  # progress goes to stderr
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed for docling-serve" }
$ok = $false
foreach ($i in 1..60) {
    try { Invoke-RestMethod -Uri "http://127.0.0.1:5001/health" -TimeoutSec 5 | Out-Null; $ok = $true; break } catch { Start-Sleep 5 }
}
if (-not $ok) { throw "docling-serve did not become healthy on :5001" }
if ($DoclingOnly) { Write-Host "docling-serve ready on http://127.0.0.1:5001"; return }

Write-Host "[2/3] Ollama"
try { Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 | Out-Null }
catch { Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep 5 }
$models = (Invoke-RestMethod -Uri "http://localhost:11434/api/tags").models.name
foreach ($m in @("qwen3:8b", "bge-m3")) {
    if (-not ($models | Where-Object { $_ -like "$m*" })) { throw "Ollama model '$m' missing: run 'ollama pull $m'" }
}

Write-Host "[3/3] Language reranker (:7998) + LightRAG server -> http://127.0.0.1:9621"
try { Invoke-RestMethod -Uri "http://127.0.0.1:7998/health" -TimeoutSec 3 | Out-Null }
catch { Start-Process "$repo\.venv\Scripts\python.exe" -ArgumentList "$repo\denso\tools\lang_rerank.py" -WorkingDirectory $repo -WindowStyle Hidden }
Set-Location $repo
& "$repo\.venv\Scripts\lightrag-server.exe"

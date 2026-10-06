# Start the full local stack: docling-serve (Docker) -> Ollama -> LightRAG server.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File C:\Projects\LightRAG\denso\start.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

Write-Host "[1/3] docling-serve"
docker compose -f "$PSScriptRoot\docling\docker-compose.yml" up -d
$ok = $false
foreach ($i in 1..60) {
    try { Invoke-RestMethod -Uri "http://127.0.0.1:5001/health" -TimeoutSec 5 | Out-Null; $ok = $true; break } catch { Start-Sleep 5 }
}
if (-not $ok) { throw "docling-serve did not become healthy on :5001" }

Write-Host "[2/3] Ollama"
try { Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 | Out-Null }
catch { Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep 5 }
$models = (Invoke-RestMethod -Uri "http://localhost:11434/api/tags").models.name
foreach ($m in @("qwen3:8b", "bge-m3")) {
    if (-not ($models | Where-Object { $_ -like "$m*" })) { throw "Ollama model '$m' missing: run 'ollama pull $m'" }
}

Write-Host "[3/3] LightRAG server -> http://127.0.0.1:9621"
Set-Location $repo
& "$repo\.venv\Scripts\lightrag-server.exe"

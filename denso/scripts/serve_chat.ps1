# Start the chat backend the UI talks to, with the configuration the 2026-10-07
# benchmark chose (naive + denso_answer.md, language reranker):
#   LLM proxy (:8899) -> language reranker (:7998) -> LightRAG level_1 (:9621)
#   -> LightRAG lookup tier (:9631) -> Agent Gateway (:9700) [-> Vite UI (:5173) with -WithUI]
# Services already listening are left alone; -Restart restarts the LightRAG servers and the
# gateway (needed after a .env change). No Docker / Docling: parsing is not needed to chat.
#
# The answering model runs through the API only (never a local LLM: it powered the laptop
# off three times). The API key is read from .env by the proxy (-KeyVar), never printed.
#
#   powershell -ExecutionPolicy Bypass -File denso\scripts\serve_chat.ps1
#   ... -Upstream https://api.cerebras.ai/v1 -KeyVar EXTRACT_LLM_BINDING_API_KEY -Model gpt-oss-120b -Rpm 4
param(
    [string]$Upstream = "https://integrate.api.nvidia.com/v1",
    [string]$KeyVar = "NVIDIA_API_KEY",
    [string]$Model = "nvidia/nemotron-3-super-120b-a12b",
    [string]$Reasoning = "low",
    [int]$Rpm = 30,
    [switch]$Restart,
    [switch]$WithUI
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py = "$repo\.venv\Scripts\python.exe"
$logs = "$repo\denso\logs"
$env:PYTHONIOENCODING = "utf-8"

function Test-Port([int]$Port) { [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) }
function Stop-Port([int]$Port) {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        $owner = $_.OwningProcess
        Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq $owner -or $_.ParentProcessId -eq $owner } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
    }
}
function Wait-Url([string]$Url, [int]$Tries = 60) {
    foreach ($i in 1..$Tries) { try { return Invoke-RestMethod $Url -TimeoutSec 3 } catch { Start-Sleep 3 } }
    throw "not reachable: $Url"
}
function Start-Bg([string]$Exe, [string[]]$ArgList, [string]$Log) {
    $p = @{ FilePath = $Exe; WorkingDirectory = $repo; WindowStyle = "Hidden"
            RedirectStandardOutput = "$logs\$Log.out.log"; RedirectStandardError = "$logs\$Log.err.log" }
    if ($ArgList) { $p.ArgumentList = $ArgList }
    Start-Process @p
}

try { Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 5 | Out-Null }
catch { Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep 5 }  # bge-m3 embeddings only

if (-not (Test-Port 8899)) {
    Start-Bg $py @("denso\tools\llm_rate_proxy.py", "--upstream", $Upstream, "--key-var", $KeyVar, "--rpm", "$Rpm",
                   "--tpm", "1000000", "--daily-token-budget", "20000000", "--fallback-model", '""',
                   "--log", "denso\logs\llm_proxy_$($KeyVar.ToLower()).jsonl") "llm_proxy"
    Wait-Url "http://127.0.0.1:8899/budget" | Out-Null
}
"proxy      :8899 -> $Upstream"

if (-not (Test-Port 7998)) { Start-Bg $py @("denso\tools\lang_rerank.py") "lang_rerank"; Wait-Url "http://127.0.0.1:7998/health" | Out-Null }
"reranker   :7998"

if ($Restart) { Stop-Port 9621; Stop-Port 9631; Stop-Port 9700; Start-Sleep 3 }
foreach ($role in "QUERY", "KEYWORD") {
    Set-Item "env:${role}_LLM_MODEL" $Model
    Set-Item "env:${role}_OPENAI_LLM_REASONING_EFFORT" $Reasoning
}
foreach ($srv in @(@{ Port = 9621; Workspace = "level_1"; Log = "server_level_1" },
                   @{ Port = 9631; Workspace = "level_1_lookup"; Log = "server_lookup" })) {
    if (-not (Test-Port $srv.Port)) {
        $env:WORKSPACE = $srv.Workspace; $env:PORT = "$($srv.Port)"
        Start-Bg "$repo\.venv\Scripts\lightrag-server.exe" @() $srv.Log
    }
}
$h = Wait-Url "http://127.0.0.1:9621/health"
Wait-Url "http://127.0.0.1:9631/health" | Out-Null
"level_1    :9621 model=$($h.configuration.role_llm_config.query.model) rerank=$($h.configuration.rerank_binding)"
"lookup     :9631"

if (-not (Test-Port 9700)) {
    $env:DENSO_LEVEL_SERVERS = "http://127.0.0.1:9621,http://127.0.0.1:9622,http://127.0.0.1:9623"
    $env:DENSO_LOOKUP_SERVER = "http://127.0.0.1:9631"
    $env:DENSO_GATEWAY_CORS = "http://localhost:5173,http://127.0.0.1:5173"
    Start-Bg $py @("denso\gateway\app.py") "gateway"
    Wait-Url "http://127.0.0.1:9700/agent/health" 20 | Out-Null
}
"gateway    :9700 knowledge mode=$(if ($env:DENSO_KNOWLEDGE_MODE) { $env:DENSO_KNOWLEDGE_MODE } else { 'naive' })"

if ($WithUI -and -not (Test-Port 5173)) {
    $bun = Get-Command bun -ErrorAction SilentlyContinue
    if (-not $bun) { $env:PATH += ";$env:APPDATA\npm" }
    $p = @{ FilePath = "cmd.exe"; ArgumentList = "/c bun run dev"; WorkingDirectory = "$repo\lightrag_webui"; WindowStyle = "Hidden"
            RedirectStandardOutput = "$logs\vite_dev.out.log"; RedirectStandardError = "$logs\vite_dev.err.log" }
    Start-Process @p
    Wait-Url "http://localhost:5173" 30 | Out-Null  # Vite listens on ::1 only, not 127.0.0.1
    "ui         :5173"
}

# Serve level_1 with the QUERY/KEYWORD roles on local Ollama (qwen3:8b) instead of the API.
# Used while no API key is available. .env is not modified: process env wins over .env.
#
# Safety, after two sudden power-offs on the 16 GB laptop:
#  - refuses to start below -MinAvailableGB of available RAM (close browser tabs first)
#  - starts denso/tools/mem_guard.py (black-box log + unload/kill brake) if not running
#  - num_ctx 20480 instead of 32768: qwen3:8b + KV cache + bge-m3 then fit in the
#    RX 6700S's 8 GB VRAM; at 32768 Vulkan spills into system RAM. KEYWORD uses the
#    same value on purpose: a different num_ctx makes Ollama reload the model per call.
#  - stops the lookup server, gateway and Vite only with -StopExtras (not done silently)
param(
    [double]$MinAvailableGB = 4.0,
    [int]$NumCtx = 20480,
    [switch]$StopExtras
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py = "$repo\.venv\Scripts\python.exe"

if ($StopExtras) {
    foreach ($port in 9631, 9700, 5173) {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -Confirm:$false; "stopped :$port" }
    }
}

$availGB = (Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue / 1024
if ($availGB -lt $MinAvailableGB) {
    $top = Get-Process | Group-Object Name | ForEach-Object { "{0} {1:N1} GB" -f $_.Name, (($_.Group | Measure-Object WorkingSet64 -Sum).Sum / 1GB) } |
        Sort-Object { [double](($_ -split ' ')[-2]) } -Descending | Select-Object -First 5
    throw ("Only {0:N1} GB RAM available (need {1} GB). Heaviest apps: {2}" -f $availGB, $MinAvailableGB, ($top -join ', '))
}

if (-not (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'mem_guard\.py' })) {
    Start-Process -FilePath $py -ArgumentList "$repo\denso\tools\mem_guard.py" -WorkingDirectory $repo -WindowStyle Hidden `
        -RedirectStandardOutput "$repo\denso\logs\mem_guard.out.log" -RedirectStandardError "$repo\denso\logs\mem_guard.err.log"
    "mem_guard started"
}

Get-NetTCPConnection -LocalPort 9621 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $owner = $_.OwningProcess
    Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq $owner -or $_.ParentProcessId -eq $owner } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
}
Start-Sleep 3

$env:WORKSPACE = "level_1"; $env:PORT = "9621"; $env:PYTHONIOENCODING = "utf-8"
foreach ($role in "QUERY", "KEYWORD") {
    Set-Item "env:${role}_LLM_BINDING" "ollama"
    Set-Item "env:${role}_LLM_BINDING_HOST" "http://localhost:11434"
    Set-Item "env:${role}_LLM_MODEL" "qwen3:8b"
    Set-Item "env:${role}_MAX_ASYNC_LLM" "1"
    Set-Item "env:${role}_OLLAMA_LLM_NUM_CTX" "$NumCtx"
}
Start-Process -FilePath "$repo\.venv\Scripts\lightrag-server.exe" -WorkingDirectory $repo -WindowStyle Hidden `
    -RedirectStandardOutput "$repo\denso\logs\server_level_1.out.log" -RedirectStandardError "$repo\denso\logs\server_level_1.err.log"
foreach ($i in 1..60) {
    try { $h = Invoke-RestMethod http://127.0.0.1:9621/health -TimeoutSec 3; break } catch { Start-Sleep 3 }
}
if (-not $h) { throw "level_1 did not come up; see denso\logs\server_level_1.err.log" }
"level_1 up on Ollama: query={0} keyword={1} num_ctx={2}" -f $h.configuration.role_llm_config.query.model, $h.configuration.role_llm_config.keyword.model, $NumCtx

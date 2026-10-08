# Start the chat backend: LLM proxy :8899, reranker :7998, LightRAG :9621 / lookup :9631,
# gateway :9700 (+ Vite UI :5173 with -WithUI, Cloudflare tunnel with -Tunnel).
# Running services are kept; -Restart restarts LightRAG and the gateway (after a .env change).
#
#   powershell -ExecutionPolicy Bypass -File denso\scripts\serve_chat.ps1 [-Restart] [-WithUI] [-Tunnel]
param(
    [string]$Upstream = "https://integrate.api.nvidia.com/v1",
    [string]$KeyVar = "NVIDIA_API_KEY",
    [string]$Model = "nvidia/nemotron-3-super-120b-a12b",
    [string]$Reasoning = "low",
    # NVIDIA Nemotron: thinking off. With it on, a long prompt often spent all 4096 tokens reasoning
    # and returned no answer (benchmark Q30, a failed brochure ingest); off, answers take ~1 s.
    # Empty for other upstreams (Cerebras rejects unknown parameters). 'none' sends nothing.
    [string]$ExtraBody = "",
    [int]$Rpm = 30,
    # Cerebras free tier: -Rpm 4 -Tpm 28000 -DailyBudget 950000 (30K tokens/min, 1M tokens/day per model)
    [int]$Tpm = 1000000,
    [int]$DailyBudget = 20000000,
    # Hosted UI: every deployment URL of the Vercel project "light-rag" in team "charlotte-eb9d"
    # (light-rag-charlotte-eb9d.vercel.app, light-rag-git-<branch>-charlotte-eb9d.vercel.app, ...).
    [string]$CorsRegex = '^https://light-rag(-[a-z0-9-]+)?-charlotte-eb9d\.vercel\.app$',
    [string]$DemoSite = "https://light-rag-git-feat-rag-backend-charlotte-eb9d.vercel.app",
    [switch]$Restart,
    # Visitors without a token (the hosted demo) may upload and delete documents. For team testing only.
    [switch]$GuestUpload,
    [switch]$WithUI,
    # Expose the gateway through a Cloudflare quick tunnel (public URL, guest = level 1) for the hosted demo.
    [switch]$Tunnel
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
    # 15 s: the gateway's /agent/health probes level_2/3 too, and a refused localhost connect costs ~2 s on Windows.
    foreach ($i in 1..$Tries) { try { return Invoke-RestMethod $Url -TimeoutSec 15 } catch { Start-Sleep 3 } }
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
                   "--tpm", "$Tpm", "--daily-token-budget", "$DailyBudget", "--fallback-model", '""',
                   "--log", "denso\logs\llm_proxy_$($KeyVar.ToLower()).jsonl") "llm_proxy"
    Wait-Url "http://127.0.0.1:8899/budget" | Out-Null
}
"proxy      :8899 -> $Upstream"

if (-not (Test-Port 7998)) { Start-Bg $py @("denso\tools\lang_rerank.py") "lang_rerank"; Wait-Url "http://127.0.0.1:7998/health" | Out-Null }
"reranker   :7998"

if ($Restart) { Stop-Port 9621; Stop-Port 9631; Stop-Port 9700; Start-Sleep 3 }
if (-not $ExtraBody -and $Upstream -match 'nvidia') { $ExtraBody = '{"chat_template_kwargs": {"enable_thinking": false}}' }
if ($ExtraBody -eq 'none') { $ExtraBody = '' }
# EXTRACT too: a (re-)ingest through this server must not ask the proxy for a model its upstream lacks.
foreach ($role in "QUERY", "KEYWORD", "EXTRACT") {
    Set-Item "env:${role}_LLM_MODEL" $Model
    Set-Item "env:${role}_OPENAI_LLM_REASONING_EFFORT" $Reasoning
    if ($ExtraBody) { Set-Item "env:${role}_OPENAI_LLM_EXTRA_BODY" $ExtraBody } else { Remove-Item "env:${role}_OPENAI_LLM_EXTRA_BODY" -ErrorAction SilentlyContinue }
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
    $env:DENSO_GATEWAY_CORS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    $env:DENSO_GATEWAY_CORS_REGEX = $CorsRegex
    $env:DENSO_LOOKUP_LLM_MODEL = $Model           # keyword-matched catalogue rows are answered by the same model
    $env:DENSO_LOOKUP_LLM_EXTRA_BODY = $ExtraBody
    $env:DENSO_GUEST_CAN_UPLOAD = $(if ($GuestUpload) { '1' } else { '0' })
    Start-Bg $py @("denso\gateway\app.py") "gateway"
    Wait-Url "http://127.0.0.1:9700/agent/health" 20 | Out-Null
}
if ($GuestUpload) { "WARNING    guests may upload and DELETE documents (-GuestUpload); restart without it after testing" }
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

if ($Tunnel) {
    # A quick tunnel gets a new random URL every start; the hosted UI takes it as ?gateway=<url>.
    $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
    if (-not $cf) { $cf = "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe" }
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:$false
    Remove-Item "$logs\tunnel.err.log" -ErrorAction SilentlyContinue
    Start-Bg $cf @("tunnel", "--no-autoupdate", "--url", "http://localhost:9700") "tunnel"
    $url = $null
    foreach ($i in 1..40) {
        Start-Sleep 2
        $m = Select-String -Path "$logs\tunnel.err.log" -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($m) { $url = $m.Matches[0].Value; break }
    }
    if (-not $url) { throw "tunnel did not report a URL; see $logs\tunnel.err.log" }
    foreach ($i in 1..30) { try { Invoke-RestMethod "$url/agent/health" -TimeoutSec 10 | Out-Null; break } catch { Start-Sleep 3 } }
    "tunnel     $url  (public; anyone with it can ask level-1 questions)"
    "demo link  $DemoSite/?gateway=$url"
}

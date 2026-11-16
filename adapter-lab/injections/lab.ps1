<#
.SYNOPSIS
  Run the AgencyZero lab on Windows - the steps from README "Running the lab".

.DESCRIPTION
  Always passes both compose files with -f (instead of the README's
  `export COMPOSE_FILE=...`, which does not work in PowerShell), so every
  command sees the same setup and Hermes is never recreated with tracing off.

  Run it from anywhere:   .\lab.cmd <command>   (lab.cmd skips the
  PowerShell execution-policy prompt). `.\lab.cmd help` lists the commands.
#>
param(
    [Parameter(Position = 0)][string]$Command = "help",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest,
    [switch]$NoLangfuse,   # start: run the lab without Langfuse tracing
    [switch]$Yolo,         # chat: skip Hermes' command approvals
    [switch]$Clean         # run: wipe Hermes memory/skills first (slow, unbiased)
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..\..")

$LabNetwork   = "agencyzero_lab"   # compose project "agencyzero" + network "lab"
$LangfuseUrl  = "http://localhost:3000"
$AllFiles     = @("-f", "compose.yaml", "-f", "compose.langfuse.yaml")
$LabOnlyFiles = @("-f", "compose.yaml")
$LangfuseKeys = @(
    "LANGFUSE_NEXTAUTH_SECRET", "LANGFUSE_SALT", "LANGFUSE_ENCRYPTION_KEY",
    "LANGFUSE_POSTGRES_PASSWORD", "LANGFUSE_CLICKHOUSE_PASSWORD",
    "LANGFUSE_REDIS_PASSWORD", "LANGFUSE_MINIO_PASSWORD",
    "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
    "LANGFUSE_ADMIN_EMAIL", "LANGFUSE_ADMIN_PASSWORD"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

function Fail([string]$Text) {
    Write-Host "ERROR: $Text" -ForegroundColor Red
    exit 1
}

# Plain function (no [Parameter]) so flags like -d / -v pass through to docker
function Invoke-Compose { & docker compose @AllFiles @args }

function Read-DotEnv {
    $values = @{}
    if (-not (Test-Path ".env")) { return $values }
    foreach ($line in Get-Content ".env") {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $values[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
    return $values
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Fail "docker was not found. Install Docker Desktop and open it."
    }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { Fail "Docker is not running. Open Docker Desktop and wait until it says it is running." }
}

function Assert-Env([bool]$WithLangfuse) {
    if (-not (Test-Path ".env")) {
        Fail ".env is missing. Copy .env.sample to .env and fill in the values (README: Running the lab > Start)."
    }
    $envValues = Read-DotEnv
    $required = @("BOB_API_KEY", "BOB_HMAC_SECRET")
    if ($WithLangfuse) { $required += $LangfuseKeys }
    $missing = @($required | Where-Object { -not $envValues[$_] })
    if ($missing.Count -gt 0) { Fail ("These .env values are empty: " + ($missing -join ", ")) }
}

function Assert-HermesRunning {
    $id = (& docker compose @AllFiles ps -q hermes 2>$null | Out-String).Trim()
    if (-not $id) { Fail "Hermes is not running. Start the lab first:  .\lab.cmd start" }
}

function Get-HermesId { return (& docker compose @AllFiles ps -q hermes 2>$null | Out-String).Trim() }

# README: wait for "[hermes] provider: bob-proxy ..., mcp: lab, tracing: ..." before chatting
function Wait-HermesReady([string]$IdBefore, [string]$Since, [bool]$WithLangfuse) {
    $pattern  = '\[hermes\] provider:.*'
    $idAfter  = Get-HermesId
    $deadline = (Get-Date).AddMinutes(5)
    Write-Step "Waiting for Hermes to finish starting (first start can take a few minutes)..."
    while ((Get-Date) -lt $deadline) {
        if ($idAfter -and $idAfter -eq $IdBefore) {
            # Container was already up to date and not recreated: use its last ready line
            $logs = & docker compose @AllFiles logs hermes 2>$null | Out-String
        } else {
            $logs = & docker compose @AllFiles logs --since $Since hermes 2>$null | Out-String
        }
        $found = [regex]::Matches($logs, $pattern)
        if ($found.Count -gt 0) {
            $line = $found[$found.Count - 1].Value.Trim()
            Write-Host $line -ForegroundColor Green
            if ($WithLangfuse -and $line -notmatch 'tracing: langfuse') {
                Write-Host "WARNING: tracing is not on. Run  .\lab.cmd start  again." -ForegroundColor Yellow
            }
            return
        }
        Start-Sleep -Seconds 3
        $idAfter = Get-HermesId
    }
    Write-Host "Hermes did not report ready within 5 minutes. Check:  .\lab.cmd logs" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
function Show-Help {
    @"
AgencyZero lab - usage:  .\lab.cmd <command> [options]

  Start / stop
    start               Start the lab with Langfuse tracing, wait until Hermes is ready
    start -NoLangfuse   Start the lab without Langfuse
    status              Show which containers are running
    stop                Stop everything (keeps Hermes and Langfuse data)
    reset               Stop and DELETE all Hermes and Langfuse data (asks first)

  Talk to Hermes
    chat                Interactive chat            (add -Yolo to skip approvals)
    ask "question"      One-off answer, then exit
    continue            Resume the last session
    model <name>        Chat with a different Bob model, e.g.  model explorer
    sessions            List past chats
    mcp                 Show the connected MCP server

  Experiments
    run <scenario>      Run one scenario: plant it, send its task, export + score
                        (add -Clean to wipe Hermes memory/skills first = unbiased)
    batch [plan.txt]    Run many experiments unattended from a plan file
                        (default plan: experiments\batch.txt; every run is clean)
    explore <scenario>  Plant a scenario, then open a live chat that STAYS open
                        so you can poke at it by hand (not scored; -Clean optional)
    score <file> <scn>  Score an export in results against a scenario, log the result

  Traces and logs
    traces              Open Langfuse in the browser ($LangfuseUrl)
    export [SESSION_ID] Export a session from Langfuse to results (default: latest),
                        then rebuild and open the readable report
    report              Rebuild and open results\report.html from all exports
    html [FILE.json]    Convert one export to a readable HTML file next to it
                        (no file given = a window opens to choose one)
    logs                Follow the Hermes container output (Ctrl+C to stop)
    agentlog            Follow runtime\logs\agent.log - what Hermes does (Ctrl+C to stop)
    workspace           Open runtime\workspace (files Hermes creates)
"@ | Write-Host
}

function Start-Lab {
    Assert-Docker
    $withLangfuse = -not $NoLangfuse
    Assert-Env $withLangfuse
    $files = if ($withLangfuse) { $AllFiles } else { $LabOnlyFiles }

    $idBefore = Get-HermesId
    $since    = (Get-Date).ToUniversalTime().AddSeconds(-5).ToString("yyyy-MM-ddTHH:mm:ssZ")

    if ($withLangfuse) { Write-Step "Starting the lab with Langfuse tracing..." }
    else               { Write-Step "Starting the lab without Langfuse..." }
    & docker compose @files up -d
    if ($LASTEXITCODE -ne 0) { Fail "docker compose up failed (see the messages above)." }

    Wait-HermesReady $idBefore $since $withLangfuse

    Write-Host ""
    Write-Host "Ready. Next:" -ForegroundColor Green
    Write-Host "  .\lab.cmd chat            talk to Hermes"
    if ($withLangfuse) {
        $envValues = Read-DotEnv
        Write-Host "  .\lab.cmd traces          open Langfuse ($LangfuseUrl, login: $($envValues['LANGFUSE_ADMIN_EMAIL']))"
    }
}

function Stop-Lab {
    Assert-Docker
    Write-Step "Stopping the lab (data is kept)..."
    Invoke-Compose down
}

function Reset-Lab {
    Assert-Docker
    Write-Host "This deletes ALL Hermes data (memory, sessions, skills) and ALL Langfuse traces." -ForegroundColor Yellow
    $answer = Read-Host "Type DELETE to continue"
    if ($answer -cne "DELETE") { Write-Host "Cancelled."; return }
    Write-Step "Stopping the lab and deleting its volumes..."
    Invoke-Compose down -v
}

function Invoke-Hermes([string[]]$HermesArgs) {
    Assert-Docker
    Assert-HermesRunning
    & docker compose @AllFiles exec hermes hermes @HermesArgs
}

function Export-Session {
    Assert-Docker
    Assert-Env $true
    $scripts = Join-Path $PSScriptRoot "scripts"
    $exports = Join-Path $PSScriptRoot "results"
    New-Item -ItemType Directory -Force -Path $exports | Out-Null
    Write-Step "Exporting from Langfuse to results ..."
    $dockerArgs = @(
        "run", "--rm", "--network", $LabNetwork, "--env-file", ".env",
        "-v", "${scripts}:/scripts:ro", "-v", "${exports}:/out",
        "python:3.12-slim", "python", "/scripts/export_session.py"
    ) + @($Rest | Where-Object { $_ })
    & docker @dockerArgs
    if ($LASTEXITCODE -eq 0) { Build-Report }
}

# Readable HTML of every export in results (no network needed)
function Build-Report {
    Assert-Docker
    $scripts = Join-Path $PSScriptRoot "scripts"
    $exports = Join-Path $PSScriptRoot "results"
    if (-not (Get-ChildItem -Path $exports -Filter "session-*.json" -ErrorAction SilentlyContinue)) {
        Fail "No exports in results yet. Run  .\lab.cmd export  first."
    }
    Write-Step "Building the readable report (results\report.html) ..."
    & docker run --rm --network none -v "${scripts}:/scripts:ro" -v "${exports}:/out" `
        python:3.12-slim python /scripts/render_report.py /out
    if ($LASTEXITCODE -eq 0) { Invoke-Item (Join-Path $exports "report.html") }
}

# One chosen export -> a readable HTML file next to it
function Convert-ExportToHtml {
    Assert-Docker
    $file = ($Rest -join " ").Trim().Trim('"')
    if (-not $file) {
        # No file given: let the user pick one
        Add-Type -AssemblyName System.Windows.Forms
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.Title = "Choose a Langfuse export to convert to HTML"
        $dialog.Filter = "Session exports (*.json)|*.json"
        $dialog.InitialDirectory = Join-Path $PSScriptRoot "results"
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { Write-Host "Cancelled."; return }
        $file = $dialog.FileName
    }
    if (-not (Test-Path -LiteralPath $file)) { Fail "File not found: $file" }
    $item    = Get-Item -LiteralPath $file
    $scripts = Join-Path $PSScriptRoot "scripts"
    Write-Step "Converting $($item.Name) to HTML ..."
    & docker run --rm --network none -v "${scripts}:/scripts:ro" -v "$($item.DirectoryName):/in" `
        python:3.12-slim python /scripts/render_report.py "/in/$($item.Name)"
    $html = [System.IO.Path]::ChangeExtension($item.FullName, ".html")
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $html)) {
        Write-Host "Saved: $html" -ForegroundColor Green
        Invoke-Item -LiteralPath $html
    }
}

function Export-Latest {
    # Export the most recent Langfuse session (no session id), no report build
    $scripts = Join-Path $PSScriptRoot "scripts"
    $exports = Join-Path $PSScriptRoot "results"
    New-Item -ItemType Directory -Force -Path $exports | Out-Null
    & docker run --rm --network $LabNetwork --env-file .env `
        -v "${scripts}:/scripts:ro" -v "${exports}:/out" `
        python:3.12-slim python /scripts/export_session.py
    return Get-ChildItem $exports -Filter "session-*.json" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

function Invoke-Score([string]$ExportName, [string]$ScenarioDir, [string]$NoteText) {
    $exports = Join-Path $PSScriptRoot "results"
    $scripts = Join-Path $PSScriptRoot "scripts"
    $experiments = Join-Path $PSScriptRoot "experiments"
    New-Item -ItemType Directory -Force -Path $experiments | Out-Null
    & docker run --rm --network none `
        -v "${scripts}:/scripts:ro" -v "${exports}:/exp:ro" `
        -v "${ScenarioDir}:/scn:ro" -v "${experiments}:/experiments" `
        python:3.12-slim python /scripts/score.py `
        "/exp/$ExportName" /scn/scenario.json --log /experiments/log.csv --note "$NoteText"
}

function Invoke-OneRun([string]$name, [bool]$clean) {
    $dir = Join-Path $PSScriptRoot "scenarios\$name"
    $scnFile = Join-Path $dir "scenario.json"
    if (-not (Test-Path $scnFile)) { Fail "No scenario at scenarios\$name (scenario.json missing)" }
    $meta = Get-Content $scnFile -Raw | ConvertFrom-Json

    $env:AZ_SCENARIO = $name
    if ($clean) {
        Write-Step "[$name] clean run: wiping Hermes memory/skills (first boot is slow)..."
        Invoke-Compose rm -sf hermes mcp | Out-Null
        docker volume rm agencyzero_hermes_home 2>$null | Out-Null
    } else {
        Write-Step "[$name] run (Hermes not wiped; this run may carry memory from before)..."
        Invoke-Compose rm -sf mcp | Out-Null   # restart mcp to reload planted notes
    }

    # Plant the scenario's workspace files into runtime\workspace (cleared first)
    $ws = Join-Path $PSScriptRoot "runtime\workspace"
    New-Item -ItemType Directory -Force -Path $ws | Out-Null
    Get-ChildItem -Path $ws -File -ErrorAction SilentlyContinue | Remove-Item -Force
    $wsSrc = Join-Path $dir "workspace"
    if (Test-Path $wsSrc) { Copy-Item (Join-Path $wsSrc "*") $ws -Force -ErrorAction SilentlyContinue }

    & docker compose @AllFiles up -d
    if ($LASTEXITCODE -ne 0) { Fail "docker compose up failed." }
    Wait-HermesReady "" "1970-01-01T00:00:00Z" $true

    Write-Step "[$name] sending the scenario task to Hermes..."
    & docker compose @AllFiles exec hermes hermes chat -Q -q $meta.user_message

    Start-Sleep -Seconds 6     # let traces flush to Langfuse
    $latest = Export-Latest
    if ($latest) { Invoke-Score $latest.Name $dir $meta.method }
    else { Write-Host "[$name] no export produced; is Langfuse running?" -ForegroundColor Yellow }
    return $latest
}

function Run-Scenario {
    Assert-Docker
    Assert-Env $true
    $name = ($Rest | Where-Object { $_ } | Select-Object -First 1)
    if (-not $name) { Fail "Name a scenario, e.g.  .\lab.cmd run note-inject" }
    $latest = Invoke-OneRun $name ([bool]$Clean)
    if ($latest) {
        Write-Host "Readable transcript:  .\lab.cmd html `"$($latest.FullName)`"" -ForegroundColor DarkGray
    }
}

function Run-Batch {
    Assert-Docker
    Assert-Env $true
    $plan = ($Rest | Where-Object { $_ } | Select-Object -First 1)
    if (-not $plan) { $plan = Join-Path $PSScriptRoot "experiments\batch.txt" }
    if (-not (Test-Path $plan)) { Fail "No batch plan found at $plan. Create it: one line per experiment, '<scenario> <repeats>'." }

    $jobs = @()
    foreach ($line in Get-Content $plan) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith("#")) { continue }
        $parts = $t -split "\s+"
        $repeats = 1
        if ($parts.Count -gt 1) { [int]::TryParse($parts[1], [ref]$repeats) | Out-Null; if ($repeats -lt 1) { $repeats = 1 } }
        $jobs += [pscustomobject]@{ scenario = $parts[0]; repeats = $repeats }
    }
    if (-not $jobs) { Fail "Batch plan has no experiments (only blank/comment lines)." }

    $total = ($jobs | Measure-Object -Property repeats -Sum).Sum
    Write-Host "Batch: $($jobs.Count) scenario(s), $total run(s) total." -ForegroundColor Cyan
    Write-Host "Every run is clean (unbiased), so each first boot is slow - this can take a while." -ForegroundColor DarkGray
    $n = 0
    foreach ($j in $jobs) {
        for ($i = 1; $i -le $j.repeats; $i++) {
            $n++
            Write-Host ""
            Write-Host "===== run $n/$total : $($j.scenario)  (repeat $i of $($j.repeats)) =====" -ForegroundColor Cyan
            Invoke-OneRun $j.scenario $true | Out-Null
        }
    }
    Write-Host ""
    Write-Host "Batch done. Results are in experiments\log.csv" -ForegroundColor Green
    Build-Report
}

function Explore-Scenario {
    Assert-Docker
    Assert-Env $true
    $name = ($Rest | Where-Object { $_ } | Select-Object -First 1)
    if (-not $name) { Fail "Name a scenario, e.g.  .\lab.cmd explore note-inject" }
    $dir = Join-Path $PSScriptRoot "scenarios\$name"
    $scnFile = Join-Path $dir "scenario.json"
    if (-not (Test-Path $scnFile)) { Fail "No scenario at scenarios\$name (scenario.json missing)" }
    $meta = Get-Content $scnFile -Raw | ConvertFrom-Json

    $env:AZ_SCENARIO = $name
    if ($Clean) {
        Write-Step "[$name] clean explore: wiping Hermes memory/skills (first boot is slow)..."
        Invoke-Compose rm -sf hermes mcp | Out-Null
        docker volume rm agencyzero_hermes_home 2>$null | Out-Null
    } else {
        Write-Step "[$name] explore (Hermes not wiped; add -Clean for a fresh agent)..."
        Invoke-Compose rm -sf mcp | Out-Null
    }

    $ws = Join-Path $PSScriptRoot "runtime\workspace"
    New-Item -ItemType Directory -Force -Path $ws | Out-Null
    Get-ChildItem -Path $ws -File -ErrorAction SilentlyContinue | Remove-Item -Force
    $wsSrc = Join-Path $dir "workspace"
    if (Test-Path $wsSrc) { Copy-Item (Join-Path $wsSrc "*") $ws -Force -ErrorAction SilentlyContinue }

    & docker compose @AllFiles up -d
    if ($LASTEXITCODE -ne 0) { Fail "docker compose up failed." }
    Wait-HermesReady "" "1970-01-01T00:00:00Z" $true

    Write-Host ""
    Write-Host "Scenario '$name' is planted. Hypothesis:" -ForegroundColor Cyan
    Write-Host "  $($meta.hypothesis)"
    Write-Host ""
    Write-Host "Suggested opening message (paste it, or try your own wording):" -ForegroundColor Cyan
    Write-Host "  $($meta.user_message)"
    Write-Host ""
    Write-Host "Opening an interactive chat - it stays open so you can keep going." -ForegroundColor DarkGray
    Write-Host "Type /exit to leave. The whole session is saved in Langfuse; score it later with:" -ForegroundColor DarkGray
    Write-Host "  .\lab.cmd export   then   .\lab.cmd score <file> $name" -ForegroundColor DarkGray
    Write-Host ""
    & docker compose @AllFiles exec hermes hermes chat
}

function Score-Export {
    Assert-Docker
    $file = ($Rest | Where-Object { $_ } | Select-Object -First 1)
    $scn  = ($Rest | Where-Object { $_ } | Select-Object -Skip 1 -First 1)
    if (-not $file -or -not $scn) { Fail "Usage:  .\lab.cmd score <export.json> <scenario-name>" }
    $dir = Join-Path $PSScriptRoot "scenarios\$scn"
    if (-not (Test-Path (Join-Path $dir 'scenario.json'))) { Fail "No scenario named '$scn'." }
    $name = Split-Path $file -Leaf
    if (-not (Test-Path (Join-Path $PSScriptRoot "results\$name"))) { Fail "Export not found in results: $name" }
    Invoke-Score $name $dir "manual score"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
switch ($Command.ToLower()) {
    "start"     { Start-Lab }
    "stop"      { Stop-Lab }
    "reset"     { Reset-Lab }
    "status"    { Assert-Docker; Invoke-Compose ps }
    "chat"      { if ($Yolo) { Invoke-Hermes @("--yolo") } else { Invoke-Hermes @() } }
    "ask" {
        $question = ($Rest -join " ").Trim()
        if (-not $question) { Fail 'Write the question in quotes:  .\lab.cmd ask "your question"' }
        Invoke-Hermes @("chat", "-Q", "-q", $question)
    }
    "continue"  { Invoke-Hermes @("chat", "--continue") }
    "model" {
        if (-not $Rest) { Fail "Name the model, e.g.  .\lab.cmd model explorer" }
        Invoke-Hermes @("-m", $Rest[0])
    }
    "sessions"  { Invoke-Hermes @("sessions", "list") }
    "mcp"       { Invoke-Hermes @("mcp", "list") }
    "traces"    { Start-Process $LangfuseUrl }
    "export"    { Export-Session }
    "report"    { Build-Report }
    "html"      { Convert-ExportToHtml }
    "run"       { Run-Scenario }
    "explore"   { Explore-Scenario }
    "batch"     { Run-Batch }
    "score"     { Score-Export }
    "logs"      { Assert-Docker; Invoke-Compose logs -f hermes }
    "agentlog" {
        $log = Join-Path $PSScriptRoot "runtime\logs\agent.log"
        if (-not (Test-Path $log)) { Fail "$log does not exist yet. Start the lab first." }
        Write-Host "(times in this log are UTC - Israel is UTC+2)" -ForegroundColor DarkGray
        Get-Content $log -Wait -Tail 50
    }
    "workspace" { New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "runtime\workspace") | Out-Null; Invoke-Item (Join-Path $PSScriptRoot "runtime\workspace") }
    { $_ -in @("help", "-h", "--help", "/?") } { Show-Help }
    default     { Write-Host "Unknown command: $Command" -ForegroundColor Red; Show-Help; exit 1 }
}

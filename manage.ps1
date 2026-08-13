#Requires -Version 5.1
<#
.SYNOPSIS
  telegram-auto management dashboard (interactive menu + CLI params)

.DESCRIPTION
  No args  = interactive English menu
  With args = same actions non-interactive (for automation / Cursor)
  Multi-account aware (config/accounts.json)

.EXAMPLE
  .\manage.ps1
  .\manage.ps1 status-all
  .\manage.ps1 gha-restart -Account elmira -Yes
  .\manage.ps1 gha-restart-all -Yes
  .\manage.ps1 start-local
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        "",
        "menu",
        "status",
        "status-all",
        "accounts",
        "start-local",
        "stop-local",
        "logs",
        "gha-list",
        "gha-list-all",
        "gha-logs",
        "gha-cancel",
        "gha-dispatch",
        "gha-restart",
        "gha-restart-all",
        "git-status",
        "git-push",
        "open-actions",
        "open-repo",
        "help"
    )]
    [string]$Command = "",

    [string]$Account = "",
    [int]$Tail = 60,
    [string]$RunId = "",
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
if (-not $Root) { $Root = Get-Location }
Set-Location $Root

$AccountsFile = Join-Path $Root "config\accounts.json"
$LockFile = Join-Path $Root "telegram_auto.lock"
$LogFile = Join-Path $Root "logs\app.log"
$RepoSlug = "alirezaprogrammermaker/telegram-auto"
$DefaultWorkflow = "run-account-elmira.yml"

function Write-Banner {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "   telegram-auto  |  multi-account mgr" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  folder: $Root" -ForegroundColor DarkGray
}

function Write-Ok($msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!]  $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[X]  $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "[i]  $msg" -ForegroundColor Gray }

function Get-SessionName {
    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) { return "easy_seen" }
    $line = Select-String -Path $envFile -Pattern "^SESSION_NAME=(.+)$" | Select-Object -First 1
    if ($line) { return $line.Matches[0].Groups[1].Value.Trim() }
    return "easy_seen"
}

function Test-GhAvailable {
    try { $null = Get-Command gh -ErrorAction Stop; return $true } catch { return $false }
}

function Get-AccountRegistry {
    if (-not (Test-Path $AccountsFile)) { return @() }
    $raw = Get-Content $AccountsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $raw.accounts) { return @() }
    return @($raw.accounts)
}

function Get-AccountOrDefault([string]$id) {
    $rows = Get-AccountRegistry
    if ($id) {
        $hit = $rows | Where-Object { $_.id -eq $id } | Select-Object -First 1
        if (-not $hit) { throw "Unknown account id: $id (see config/accounts.json)" }
        return $hit
    }
    $enabled = $rows | Where-Object { $_.enabled -eq $true } | Select-Object -First 1
    if ($enabled) { return $enabled }
    if ($rows.Count -gt 0) { return $rows[0] }
    return [pscustomobject]@{
        id = "elmira"
        workflow = $DefaultWorkflow
        session_name = "easy_seen"
        session_secret = "TELEGRAM_SESSION_B64"
        enabled = $true
        label = "elmira (fallback)"
    }
}

function Get-LocalPythonPids {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match 'main\.py') } |
        Select-Object ProcessId, CommandLine
}

function Show-Accounts {
    Write-Banner
    Write-Host ""
    Write-Host "--- Account registry ---" -ForegroundColor White
    $rows = Get-AccountRegistry
    if ($rows.Count -eq 0) { Write-Warn "No accounts in config/accounts.json"; return }
    foreach ($a in $rows) {
        $flag = if ($a.enabled) { "ENABLED " } else { "disabled" }
        Write-Host ("  [{0}] {1}" -f $flag, $a.id) -ForegroundColor $(if ($a.enabled) { "Green" } else { "DarkGray" })
        Write-Info "label: $($a.label)"
        Write-Info "workflow: $($a.workflow)"
        Write-Info "session: $($a.session_name)  secret: $($a.session_secret)"
        Write-Host ""
    }
    Write-Info "Docs: docs/multi-account.md"
}

function Show-Status {
    Write-Banner
    Write-Host ""
    Write-Host "--- Local ---" -ForegroundColor White
    $session = Get-SessionName
    Write-Info "SESSION_NAME in .env = $session"
    if ($session -eq "easy_seen") {
        Write-Warn "Using easy_seen. Do NOT run local while Elmira GHA is active."
    } else {
        Write-Ok "Local session is separate from production ($session)"
    }

    $locks = Get-ChildItem -Path $Root -Filter "telegram_auto*.lock" -ErrorAction SilentlyContinue
    if ($locks) {
        foreach ($l in $locks) { Write-Warn "Lock: $($l.Name)" }
    } else {
        Write-Ok "No lock files"
    }

    $procs = @(Get-LocalPythonPids)
    if ($procs.Count -gt 0) {
        Write-Ok "Local app running ($($procs.Count))"
        $procs | ForEach-Object { Write-Info "PID $($_.ProcessId)" }
    } else {
        Write-Info "Local app stopped"
    }

    Write-Host ""
    Write-Host "--- GitHub (selected account) ---" -ForegroundColor White
    if (-not (Test-GhAvailable)) { Write-Err "gh CLI not found"; return }
    $acc = Get-AccountOrDefault $Account
    Write-Info "account=$($acc.id) workflow=$($acc.workflow)"
    gh run list --workflow="$($acc.workflow)" --limit 5
    Write-Host ""
    git status -sb
}

function Show-StatusAll {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh CLI not found"; return }
    Write-Host ""
    Write-Host "--- All accounts (GHA) ---" -ForegroundColor White
    foreach ($a in Get-AccountRegistry) {
        Write-Host ""
        $flag = if ($a.enabled) { "ON" } else { "OFF" }
        Write-Host ("== {0} [{1}] ==" -f $a.id, $flag) -ForegroundColor Cyan
        Write-Info $a.label
        try {
            gh run list --workflow="$($a.workflow)" --limit 3
        } catch {
            Write-Warn "Could not list $($a.workflow): $($_.Exception.Message)"
        }
    }
    Write-Host ""
    Write-Host "--- Local ---" -ForegroundColor White
    $procs = @(Get-LocalPythonPids)
    if ($procs.Count -gt 0) { Write-Ok "local running"; $procs | ForEach-Object { Write-Info "PID $($_.ProcessId)" } }
    else { Write-Info "local stopped" }
}

function Start-LocalApp {
    Write-Banner
    $session = Get-SessionName
    Write-Info "Starting with SESSION_NAME=$session"
    $existing = @(Get-LocalPythonPids)
    if ($existing.Count -gt 0) { Write-Warn "Already running. Use stop-local first."; return }
    Get-ChildItem -Path $Root -Filter "telegram_auto*.lock" -ErrorAction SilentlyContinue | Remove-Item -Force
    Start-Process -FilePath "python" -ArgumentList "main.py" -WorkingDirectory $Root -WindowStyle Minimized
    Start-Sleep -Seconds 3
    $procs = @(Get-LocalPythonPids)
    if ($procs.Count -gt 0) {
        Write-Ok "Local started (PID $($procs[0].ProcessId))"
        Write-Info "Logs: .\manage.ps1 logs"
    } else {
        Write-Warn "Process not seen — check logs\app.log"
        if (Test-Path $LogFile) { Get-Content $LogFile -Tail 30 }
    }
}

function Stop-LocalApp {
    Write-Banner
    $procs = @(Get-LocalPythonPids)
    if ($procs.Count -eq 0) {
        Write-Info "Nothing to stop"
        Get-ChildItem -Path $Root -Filter "telegram_auto*.lock" -ErrorAction SilentlyContinue | Remove-Item -Force
        return
    }
    foreach ($p in $procs) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Ok "Stopped PID $($p.ProcessId)"
        } catch {
            Write-Err "Could not stop PID $($p.ProcessId): $($_.Exception.Message)"
        }
    }
    Start-Sleep -Seconds 1
    Get-ChildItem -Path $Root -Filter "telegram_auto*.lock" -ErrorAction SilentlyContinue | Remove-Item -Force
    Write-Ok "Local stopped"
}

function Show-LocalLogs {
    Write-Banner
    if (-not (Test-Path $LogFile)) { Write-Err "Log not found: $LogFile"; return }
    Write-Info "Last $Tail lines of logs\app.log"
    Write-Host "----------------------------------------" -ForegroundColor DarkGray
    Get-Content $LogFile -Tail $Tail
}

function Show-GhaList {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh not found"; return }
    $acc = Get-AccountOrDefault $Account
    Write-Info "workflow=$($acc.workflow) account=$($acc.id)"
    gh run list --workflow="$($acc.workflow)" --limit 10
}

function Show-GhaListAll {
    Show-StatusAll
}

function Show-GhaLogs {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh not found"; return }
    $acc = Get-AccountOrDefault $Account
    $id = $RunId
    if (-not $id) {
        $id = gh run list --workflow="$($acc.workflow)" --limit 1 --json databaseId --jq ".[0].databaseId"
    }
    if (-not $id) { Write-Err "No run found"; return }
    Write-Info "Logs for run $id (account=$($acc.id))"
    $raw = gh run view $id --log 2>&1 | Out-String
    if ($raw -match "still in progress") {
        Write-Warn "Run still in progress; full logs after finish."
        gh run view $id --json url --jq .url
        return
    }
    $raw -split "`n" |
        Select-String -Pattern "Connected as|account_id|Config account|Route:|watching|promo_|Delivered|Error|error|AuthKey|Active modules|DRY-RUN|enqueued|skipped" |
        Select-Object -Last $Tail |
        ForEach-Object { $_.Line }
}

function Invoke-GhaCancel {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh not found"; return }
    $acc = Get-AccountOrDefault $Account
    $id = $RunId
    if (-not $id) {
        $id = gh run list --workflow="$($acc.workflow)" --limit 5 --json databaseId,status --jq '.[] | select(.status=="in_progress" or .status=="queued") | .databaseId' | Select-Object -First 1
    }
    if (-not $id) { Write-Info "No active run for $($acc.id)"; return }
    if (-not $Yes) {
        $ans = Read-Host "Cancel $($acc.id) run $id? (y/N)"
        if ($ans -notmatch '^[yY]') { Write-Info "Cancelled"; return }
    }
    gh run cancel $id
    Write-Ok "Cancel requested: $id ($($acc.id))"
}

function Invoke-GhaDispatch {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh not found"; return }
    $acc = Get-AccountOrDefault $Account
    Write-Info "Dispatch $($acc.workflow) (account=$($acc.id))"
    gh workflow run "$($acc.workflow)" --ref master
    Start-Sleep -Seconds 4
    Write-Ok "Requested"
    gh run list --workflow="$($acc.workflow)" --limit 3
}

function Invoke-GhaRestart {
    Write-Banner
    $acc = Get-AccountOrDefault $Account
    Write-Info "Restart account=$($acc.id)"
    if (-not $Yes) {
        $ans = Read-Host "Cancel + dispatch $($acc.id)? (y/N)"
        if ($ans -notmatch '^[yY]') { Write-Info "Cancelled"; return }
    }
    $script:Yes = $true
    $script:Account = $acc.id
    Invoke-GhaCancel
    Start-Sleep -Seconds 3
    Invoke-GhaDispatch
}

function Invoke-GhaRestartAll {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh not found"; return }
    $rows = Get-AccountRegistry | Where-Object { $_.enabled -eq $true }
    if ($rows.Count -eq 0) { Write-Warn "No enabled accounts"; return }
    if (-not $Yes) {
        $names = ($rows | ForEach-Object { $_.id }) -join ", "
        $ans = Read-Host "Restart enabled accounts ($names)? (y/N)"
        if ($ans -notmatch '^[yY]') { Write-Info "Cancelled"; return }
    }
    foreach ($a in $rows) {
        Write-Host ""
        Write-Host ">> $($a.id)" -ForegroundColor Cyan
        $script:Account = $a.id
        $script:Yes = $true
        Invoke-GhaCancel
        Start-Sleep -Seconds 2
        Invoke-GhaDispatch
        Start-Sleep -Seconds 2
    }
}

function Show-GitStatus {
    Write-Banner
    git status -sb
    Write-Host ""
    git log -5 --oneline
}

function Invoke-GitPush {
    Write-Banner
    git status -sb
    $ahead = git rev-list --count "origin/master..HEAD" 2>$null
    if (-not $ahead -or [int]$ahead -eq 0) {
        $dirty = git status --porcelain
        if (-not $dirty) { Write-Info "Nothing to push"; return }
        Write-Warn "Uncommitted changes — commit first"
        return
    }
    if (-not $Yes) {
        $ans = Read-Host "Push to origin/master? ($ahead ahead) (y/N)"
        if ($ans -notmatch '^[yY]') { Write-Info "Cancelled"; return }
    }
    git push -u origin HEAD
    Write-Ok "Push done"
}

function Open-ActionsPage {
    Start-Process "https://github.com/$RepoSlug/actions"
    Write-Ok "Actions opened"
}

function Open-RepoPage {
    Start-Process "https://github.com/$RepoSlug"
    Write-Ok "Repo opened"
}

function Show-Help {
    Write-Banner
    Write-Host @"

Menu:  .\manage.ps1

CLI:
  .\manage.ps1 accounts
  .\manage.ps1 status
  .\manage.ps1 status-all
  .\manage.ps1 start-local | stop-local | logs [-Tail 100]
  .\manage.ps1 gha-list [-Account elmira]
  .\manage.ps1 gha-list-all
  .\manage.ps1 gha-logs [-Account elmira] [-RunId 123]
  .\manage.ps1 gha-restart -Account elmira -Yes
  .\manage.ps1 gha-restart-all -Yes
  .\manage.ps1 gha-dispatch -Account promo1
  .\manage.ps1 git-status | git-push [-Yes]
  .\manage.ps1 help

Accounts live in config/accounts.json
Docs: docs/multi-account.md

"@
}

function Pause-Menu {
    Write-Host ""
    Read-Host "Press Enter to return to menu" | Out-Null
}

function Show-Menu {
    while ($true) {
        Write-Banner
        Write-Host ""
        Write-Host "  1) Status (local + one account)" -ForegroundColor White
        Write-Host "  2) Status ALL accounts" -ForegroundColor White
        Write-Host "  3) List accounts registry" -ForegroundColor White
        Write-Host "  4) Start local app" -ForegroundColor White
        Write-Host "  5) Stop local app" -ForegroundColor White
        Write-Host "  6) Local logs" -ForegroundColor White
        Write-Host ""
        Write-Host "  7) GHA list (pick account)" -ForegroundColor White
        Write-Host "  8) GHA logs (pick account)" -ForegroundColor White
        Write-Host "  9) GHA restart ONE account" -ForegroundColor White
        Write-Host " 10) GHA restart ALL enabled" -ForegroundColor White
        Write-Host " 11) GHA cancel current (pick account)" -ForegroundColor White
        Write-Host " 12) GHA dispatch only (pick account)" -ForegroundColor White
        Write-Host ""
        Write-Host " 13) git status" -ForegroundColor White
        Write-Host " 14) git push" -ForegroundColor White
        Write-Host " 15) Open Actions / Repo" -ForegroundColor White
        Write-Host " 16) Help" -ForegroundColor White
        Write-Host "  0) Exit" -ForegroundColor DarkGray
        Write-Host ""
        $choice = Read-Host "Enter number"

        switch ($choice) {
            "1" { Show-Status; Pause-Menu }
            "2" { Show-StatusAll; Pause-Menu }
            "3" { Show-Accounts; Pause-Menu }
            "4" { Start-LocalApp; Pause-Menu }
            "5" { Stop-LocalApp; Pause-Menu }
            "6" {
                $t = Read-Host "How many lines? (default $Tail)"
                if ($t -match '^\d+$') { $script:Tail = [int]$t }
                Show-LocalLogs; Pause-Menu
            }
            "7" {
                $script:Account = Read-Host "Account id (elmira/promo1, empty=default)"
                Show-GhaList; Pause-Menu
            }
            "8" {
                $script:Account = Read-Host "Account id (elmira/promo1, empty=default)"
                Show-GhaLogs; Pause-Menu
            }
            "9" {
                $script:Account = Read-Host "Account id to restart"
                Invoke-GhaRestart; Pause-Menu
            }
            "10" { Invoke-GhaRestartAll; Pause-Menu }
            "11" {
                $script:Account = Read-Host "Account id"
                Invoke-GhaCancel; Pause-Menu
            }
            "12" {
                $script:Account = Read-Host "Account id"
                Invoke-GhaDispatch; Pause-Menu
            }
            "13" { Show-GitStatus; Pause-Menu }
            "14" { Invoke-GitPush; Pause-Menu }
            "15" {
                Open-ActionsPage
                Open-RepoPage
                Pause-Menu
            }
            "16" { Show-Help; Pause-Menu }
            "0" { Write-Host "Bye."; return }
            default { Write-Warn "Invalid number"; Start-Sleep -Seconds 1 }
        }
    }
}

# ---- entry ----
if (-not $Command -or $Command -eq "menu") {
    Show-Menu
    exit 0
}

switch ($Command) {
    "status"         { Show-Status }
    "status-all"     { Show-StatusAll }
    "accounts"       { Show-Accounts }
    "start-local"    { Start-LocalApp }
    "stop-local"     { Stop-LocalApp }
    "logs"           { Show-LocalLogs }
    "gha-list"       { Show-GhaList }
    "gha-list-all"   { Show-GhaListAll }
    "gha-logs"       { Show-GhaLogs }
    "gha-cancel"     { Invoke-GhaCancel }
    "gha-dispatch"   { Invoke-GhaDispatch }
    "gha-restart"    { Invoke-GhaRestart }
    "gha-restart-all"{ Invoke-GhaRestartAll }
    "git-status"     { Show-GitStatus }
    "git-push"       { Invoke-GitPush }
    "open-actions"   { Open-ActionsPage }
    "open-repo"      { Open-RepoPage }
    "help"           { Show-Help }
    default          { Show-Help }
}

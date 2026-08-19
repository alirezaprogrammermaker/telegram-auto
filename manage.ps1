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
  .\manage.ps1 account-add -Account promo2 -Role promo
  .\manage.ps1 login-setup
  .\manage.ps1 login-send -Account promo2 -Phone +98912... -Yes
  .\manage.ps1 login-otp
  .\manage.ps1 login-complete -Account promo2 -Yes
  .\manage.ps1 gha-restart -Account elmira -Yes
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
        "account-add",
        "account-enable",
        "account-disable",
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
        "login-setup",
        "login-send",
        "login-otp",
        "login-2fa",
        "login-complete",
        "login-cleanup",
        "git-status",
        "git-push",
        "open-actions",
        "open-repo",
        "help"
    )]
    [string]$Command = "",

    [string]$Account = "",
    [string]$Phone = "",
    [ValidateSet("", "promo", "forward", "full", "collector", "inspector", "linkdir")]
    [string]$Role = "",
    [string]$Label = "",
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

function Test-RepoSecretsToken {
    if (-not (Test-GhAvailable)) { return $false }
    try {
        $names = gh secret list --json name --jq ".[].name" 2>$null
    } catch {
        return $false
    }
    if (-not $names) { return $false }
    foreach ($n in ($names -split "`n")) {
        if ($n.Trim() -eq "REPO_SECRETS_TOKEN") { return $true }
    }
    return $false
}

function Wait-GhaRun {
    param([string]$Workflow)
    Start-Sleep -Seconds 5
    $json = gh run list --workflow=$Workflow --limit 1 --json databaseId,status,conclusion,url | ConvertFrom-Json
    if (-not $json) {
        Write-Warn "No run found yet for $Workflow"
        return $null
    }
    $run = if ($json -is [System.Array]) { $json[0] } else { $json }
    Write-Info "Watching run $($run.databaseId) -> $($run.url)"
    gh run watch $run.databaseId --exit-status
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Workflow failed. Recent failed log lines:"
        gh run view $run.databaseId --log-failed 2>$null | Select-Object -Last 80
        return $null
    }
    Write-Ok "Workflow finished OK ($($run.databaseId))"
    return $run
}

function Set-AccountEnabled([string]$id, [bool]$enabled) {
    $flag = if ($enabled) { "true" } else { "false" }
    python scripts/set_account_enabled.py $id --enabled $flag
    if ($LASTEXITCODE -ne 0) { throw "Failed to update enabled flag for $id" }
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
        Write-Warn "Process not seen - check logs\app.log"
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
        $rows = gh run list --workflow="$($acc.workflow)" --limit 8 --json databaseId,status | ConvertFrom-Json
        $active = @($rows | Where-Object { $_.status -in @("in_progress", "queued", "pending", "waiting") })
        if ($active.Count -gt 0) { $id = [string]$active[0].databaseId }
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

function Invoke-AccountAdd {
    Write-Banner
    $id = $Account
    if (-not $id) { $id = Read-Host "New account id (e.g. promo2)" }
    if (-not $id) { Write-Err "Account id required"; return }
    $role = $Role
    if (-not $role) {
        $role = Read-Host "Role: promo / forward / collector / inspector / full (default promo)"
        if (-not $role) { $role = "promo" }
    }
    $argsList = @("scripts/scaffold_account.py", $id, "--role", $role)
    if ($Label) { $argsList += @("--label", $Label) }
    Write-Info "Scaffolding account $id (role=$role)..."
    & python @argsList
    if ($LASTEXITCODE -ne 0) { Write-Err "scaffold failed"; return }
    Write-Ok "Account files created"
    Write-Warn "Commit + push to master BEFORE login-send (workflow must exist on GitHub)."
    Write-Host "Next:"
    Write-Host "  .\manage.ps1 git-push -Yes"
    Write-Host "  .\manage.ps1 login-setup"
    Write-Host "  .\manage.ps1 login-send -Account $id -Phone +98... -Yes"
}

function Invoke-AccountEnable {
    Write-Banner
    $acc = Get-AccountOrDefault $Account
    if (-not $Yes) {
        $ans = Read-Host "Enable $($acc.id) in config/accounts.json? (y/N)"
        if ($ans -notmatch '^[yY]') { Write-Info "Cancelled"; return }
    }
    Set-AccountEnabled $acc.id $true
    Write-Ok "$($acc.id) enabled locally"
    Write-Warn "Push to master so GHA honors enabled=true"
}

function Invoke-AccountDisable {
    Write-Banner
    $acc = Get-AccountOrDefault $Account
    if (-not $Yes) {
        $ans = Read-Host "Disable $($acc.id) in config/accounts.json? (y/N)"
        if ($ans -notmatch '^[yY]') { Write-Info "Cancelled"; return }
    }
    Set-AccountEnabled $acc.id $false
    Write-Ok "$($acc.id) disabled locally"
    Write-Warn "Push to master so GHA skips this account"
}

function Invoke-LoginSetup {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh not found"; return }
    Write-Host "--- Login prerequisites ---" -ForegroundColor White
    Write-Info "Production logins must run on GHA (runner IP), never on home PC."
    if (Test-RepoSecretsToken) {
        Write-Ok "REPO_SECRETS_TOKEN secret exists"
    } else {
        Write-Err "REPO_SECRETS_TOKEN missing"
        Write-Host ""
        Write-Host "Create a GitHub PAT that can WRITE repository secrets:"
        Write-Host "  Classic: repo scope"
        Write-Host "  Fine-grained: Repository permissions -> Secrets -> Read and write"
        Write-Host ""
        Write-Host "Then:"
        Write-Host "  gh secret set REPO_SECRETS_TOKEN"
        if (-not $Yes) {
            $ans = Read-Host "Open browser to create a PAT now? (y/N)"
            if ($ans -match '^[yY]') {
                Start-Process "https://github.com/settings/tokens?type=beta"
            }
        }
    }
    Write-Host ""
    Write-Info "Full flow:"
    Write-Host "  1) .\manage.ps1 account-add -Account promo2 -Role promo"
    Write-Host "  2) commit/push"
    Write-Host "  3) .\manage.ps1 login-send -Account promo2 -Phone +98... -Yes"
    Write-Host "  4) .\manage.ps1 login-otp"
    Write-Host "  5) .\manage.ps1 login-complete -Account promo2 -Yes"
    Write-Host "  6) .\manage.ps1 login-cleanup"
    Write-Host "  7) .\manage.ps1 account-enable -Account promo2 + push"
    Write-Host "  8) .\manage.ps1 gha-dispatch -Account promo2"
}

function Invoke-LoginSend {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh not found"; return }
    $acc = Get-AccountOrDefault $Account
    if (-not (Test-RepoSecretsToken)) {
        Write-Warn "REPO_SECRETS_TOKEN missing - complete step will need it (.\manage.ps1 login-setup)"
    }
    $phone = $Phone
    if (-not $phone) { $phone = Read-Host "Phone with country code (e.g. +98912...)" }
    if (-not $phone) { Write-Err "Phone required"; return }
    if ($phone -notmatch '^\+\d{8,15}$') {
        Write-Warn "Phone should look like +98912... (E.164). Continuing anyway."
    }
    Write-Info "Storing LOGIN_PHONE as a repo secret (not a public workflow input)..."
    $phone | gh secret set LOGIN_PHONE
    if ($LASTEXITCODE -ne 0) { Write-Err "Failed to set LOGIN_PHONE"; return }
    Write-Info "Dispatching login-account send for $($acc.id) on GHA runner IP..."
    gh workflow run login-account.yml --ref master `
        -f action=send `
        -f account_id=$($acc.id)
    if ($LASTEXITCODE -ne 0) { Write-Err "workflow dispatch failed"; return }
    Write-Ok "OTP send requested for $($acc.id)"
    $run = Wait-GhaRun -Workflow "login-account.yml"
    if (-not $run) { return }
    Write-Host ""
    Write-Info "Next steps:"
    Write-Host "  1) Read Telegram OTP for that phone"
    Write-Host "  2) .\manage.ps1 login-otp"
    Write-Host "  3) (if 2FA) .\manage.ps1 login-2fa"
    Write-Host "  4) .\manage.ps1 login-complete -Account $($acc.id) -Yes"
}

function Invoke-LoginOtp {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh not found"; return }
    $code = Read-Host "Telegram OTP code"
    if (-not $code) { Write-Err "OTP required"; return }
    $code = ($code -replace '\s', '')
    $code | gh secret set LOGIN_OTP
    if ($LASTEXITCODE -ne 0) { Write-Err "Failed to set LOGIN_OTP"; return }
    Write-Ok "LOGIN_OTP secret set"
    Write-Info "If account has cloud password: .\manage.ps1 login-2fa"
    Write-Info "Then: .\manage.ps1 login-complete -Account <id> -Yes"
}

function Invoke-Login2fa {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh not found"; return }
    $secure = Read-Host "Telegram 2FA / cloud password" -AsSecureString
    if (-not $secure) { Write-Err "Password required"; return }
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    if (-not $plain) { Write-Err "Password required"; return }
    $plain | gh secret set LOGIN_2FA
    $plain = $null
    if ($LASTEXITCODE -ne 0) { Write-Err "Failed to set LOGIN_2FA"; return }
    Write-Ok "LOGIN_2FA secret set"
}

function Invoke-LoginComplete {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh not found"; return }
    $acc = Get-AccountOrDefault $Account
    if (-not (Test-RepoSecretsToken)) {
        Write-Err "REPO_SECRETS_TOKEN missing - run .\manage.ps1 login-setup"
        return
    }
    Write-Warn "LOGIN_OTP must already be set (.\manage.ps1 login-otp)"
    if (-not $Yes) {
        $ans = Read-Host "Run complete login for $($acc.id) on GHA? (y/N)"
        if ($ans -notmatch '^[yY]') { Write-Info "Cancelled"; return }
    }
    gh workflow run login-account.yml --ref master `
        -f action=complete `
        -f account_id=$($acc.id)
    if ($LASTEXITCODE -ne 0) { Write-Err "workflow dispatch failed"; return }
    Write-Ok "Complete login requested for $($acc.id)"
    $run = Wait-GhaRun -Workflow "login-account.yml"
    if (-not $run) { return }
    Write-Ok "Session secret $($acc.session_secret) should now be set"
    Write-Info "Cleanup temp secrets: .\manage.ps1 login-cleanup"
    Write-Info "Enable + push, then: .\manage.ps1 gha-dispatch -Account $($acc.id)"
}

function Invoke-LoginCleanup {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh not found"; return }
    foreach ($name in @("LOGIN_OTP", "LOGIN_2FA", "LOGIN_PHONE")) {
        Write-Info "Deleting secret $name (ok if missing)..."
        gh secret delete $name --yes 2>$null | Out-Null
    }
    Write-Ok "Temp login secrets cleared (or were already absent)"
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
        Write-Warn "Uncommitted changes - commit first"
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
  .\manage.ps1 account-add -Account promo2 -Role promo
  .\manage.ps1 account-add -Account collector1 -Role collector
  .\manage.ps1 account-add -Account inspector1 -Role inspector
  .\manage.ps1 account-enable|-disable -Account promo2 -Yes
  .\manage.ps1 status-all
  .\manage.ps1 start-local | stop-local | logs [-Tail 100]
  .\manage.ps1 gha-list [-Account elmira]
  .\manage.ps1 gha-restart -Account elmira -Yes
  .\manage.ps1 login-setup
  .\manage.ps1 login-send -Account promo1 -Phone +98912... -Yes
  .\manage.ps1 login-otp
  .\manage.ps1 login-2fa
  .\manage.ps1 login-complete -Account promo1 -Yes
  .\manage.ps1 login-cleanup
  .\manage.ps1 git-status | git-push [-Yes]
  .\manage.ps1 help

Accounts: config/accounts.json
Login (GHA IP only): docs/multi-account.md
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
        Write-Host "  4) Add account (scaffold)" -ForegroundColor White
        Write-Host "  5) Start local app" -ForegroundColor White
        Write-Host "  6) Stop local app" -ForegroundColor White
        Write-Host "  7) Local logs" -ForegroundColor White
        Write-Host ""
        Write-Host "  8) GHA list (pick account)" -ForegroundColor White
        Write-Host "  9) GHA logs (pick account)" -ForegroundColor White
        Write-Host " 10) GHA restart ONE account" -ForegroundColor White
        Write-Host " 11) GHA restart ALL enabled" -ForegroundColor White
        Write-Host " 12) GHA cancel / dispatch" -ForegroundColor White
        Write-Host ""
        Write-Host " 13) Login SETUP (PAT check)" -ForegroundColor White
        Write-Host " 14) Login SEND OTP on GHA" -ForegroundColor White
        Write-Host " 15) Login set OTP / 2FA secrets" -ForegroundColor White
        Write-Host " 16) Login COMPLETE on GHA" -ForegroundColor White
        Write-Host " 17) Login cleanup temp secrets" -ForegroundColor White
        Write-Host " 18) Enable / disable account" -ForegroundColor White
        Write-Host " 19) git status / push" -ForegroundColor White
        Write-Host " 20) Open Actions / Repo / Help" -ForegroundColor White
        Write-Host "  0) Exit" -ForegroundColor DarkGray
        Write-Host ""
        $choice = Read-Host "Enter number"

        switch ($choice) {
            "1" { Show-Status; Pause-Menu }
            "2" { Show-StatusAll; Pause-Menu }
            "3" { Show-Accounts; Pause-Menu }
            "4" { Invoke-AccountAdd; Pause-Menu }
            "5" { Start-LocalApp; Pause-Menu }
            "6" { Stop-LocalApp; Pause-Menu }
            "7" {
                $t = Read-Host "How many lines? (default $Tail)"
                if ($t -match '^\d+$') { $script:Tail = [int]$t }
                Show-LocalLogs; Pause-Menu
            }
            "8" {
                $script:Account = Read-Host "Account id (empty=default)"
                Show-GhaList; Pause-Menu
            }
            "9" {
                $script:Account = Read-Host "Account id (empty=default)"
                Show-GhaLogs; Pause-Menu
            }
            "10" {
                $script:Account = Read-Host "Account id to restart"
                Invoke-GhaRestart; Pause-Menu
            }
            "11" { Invoke-GhaRestartAll; Pause-Menu }
            "12" {
                $sub = Read-Host "c=cancel / d=dispatch"
                $script:Account = Read-Host "Account id"
                if ($sub -eq "c") { Invoke-GhaCancel } else { Invoke-GhaDispatch }
                Pause-Menu
            }
            "13" { Invoke-LoginSetup; Pause-Menu }
            "14" {
                $script:Account = Read-Host "Account id"
                Invoke-LoginSend; Pause-Menu
            }
            "15" {
                Invoke-LoginOtp
                $need2fa = Read-Host "Also set 2FA password now? (y/N)"
                if ($need2fa -match '^[yY]') { Invoke-Login2fa }
                Pause-Menu
            }
            "16" {
                $script:Account = Read-Host "Account id"
                Invoke-LoginComplete; Pause-Menu
            }
            "17" { Invoke-LoginCleanup; Pause-Menu }
            "18" {
                $script:Account = Read-Host "Account id"
                $ed = Read-Host "e=enable / d=disable"
                if ($ed -eq "d") { Invoke-AccountDisable } else { Invoke-AccountEnable }
                Pause-Menu
            }
            "19" {
                $g = Read-Host "s=status / p=push"
                if ($g -eq "p") { Invoke-GitPush } else { Show-GitStatus }
                Pause-Menu
            }
            "20" {
                $h = Read-Host "a=actions / r=repo / h=help"
                if ($h -eq "a") { Open-ActionsPage }
                elseif ($h -eq "r") { Open-RepoPage }
                else { Show-Help }
                Pause-Menu
            }
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
    "status"          { Show-Status }
    "status-all"      { Show-StatusAll }
    "accounts"        { Show-Accounts }
    "account-add"     { Invoke-AccountAdd }
    "account-enable"  { Invoke-AccountEnable }
    "account-disable" { Invoke-AccountDisable }
    "start-local"     { Start-LocalApp }
    "stop-local"      { Stop-LocalApp }
    "logs"            { Show-LocalLogs }
    "gha-list"        { Show-GhaList }
    "gha-list-all"    { Show-GhaListAll }
    "gha-logs"        { Show-GhaLogs }
    "gha-cancel"      { Invoke-GhaCancel }
    "gha-dispatch"    { Invoke-GhaDispatch }
    "gha-restart"     { Invoke-GhaRestart }
    "gha-restart-all" { Invoke-GhaRestartAll }
    "login-setup"     { Invoke-LoginSetup }
    "login-send"      { Invoke-LoginSend }
    "login-otp"       { Invoke-LoginOtp }
    "login-2fa"       { Invoke-Login2fa }
    "login-complete"  { Invoke-LoginComplete }
    "login-cleanup"   { Invoke-LoginCleanup }
    "git-status"      { Show-GitStatus }
    "git-push"        { Invoke-GitPush }
    "open-actions"    { Open-ActionsPage }
    "open-repo"       { Open-RepoPage }
    "help"            { Show-Help }
    default           { Show-Help }
}

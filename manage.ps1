#Requires -Version 5.1
<#
.SYNOPSIS
  داشبورد مدیریت telegram-auto (منوی تعاملی + حالت پارامتری)

.DESCRIPTION
  اجرا بدون آرگومان = منوی فارسی
  با آرگومان = همان کار بدون منو (برای اتوماسیون / Cursor)

.EXAMPLE
  .\manage.ps1
  .\manage.ps1 status
  .\manage.ps1 start-local
  .\manage.ps1 stop-local
  .\manage.ps1 gha-restart
  .\manage.ps1 logs -Tail 80
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        "",
        "menu",
        "status",
        "start-local",
        "stop-local",
        "logs",
        "gha-list",
        "gha-logs",
        "gha-cancel",
        "gha-dispatch",
        "gha-restart",
        "git-status",
        "git-push",
        "open-actions",
        "open-repo",
        "help"
    )]
    [string]$Command = "",

    [int]$Tail = 60,
    [string]$RunId = "",
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
if (-not $Root) { $Root = Get-Location }
Set-Location $Root

$Workflow = "run-every-6h.yml"
$LockFile = Join-Path $Root "telegram_auto.lock"
$LogFile = Join-Path $Root "logs\app.log"
$RepoSlug = "alirezaprogrammermaker/telegram-auto"

function Write-Banner {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "   telegram-auto  |  مدیریت ساده" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  پوشه: $Root" -ForegroundColor DarkGray
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
    try {
        $null = Get-Command gh -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Get-LocalPythonPids {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match 'main\.py') } |
        Select-Object ProcessId, CommandLine
}

function Show-Status {
    Write-Banner
    Write-Host ""
    Write-Host "--- وضعیت لوکال ---" -ForegroundColor White
    $session = Get-SessionName
    Write-Info "SESSION_NAME در .env = $session"
    if ($session -eq "easy_seen") {
        Write-Warn "الان easy_seen است. اگر GHA روشن باشد، لوکال را با این سشن اجرا نکن."
    } else {
        Write-Ok "سشن لوکال جدا از production است ($session)"
    }

    if (Test-Path $LockFile) {
        Write-Warn "قفل فعال: $LockFile"
        Get-Content $LockFile -ErrorAction SilentlyContinue | ForEach-Object { Write-Info $_ }
    } else {
        Write-Ok "قفل برنامه وجود ندارد"
    }

    $procs = @(Get-LocalPythonPids)
    if ($procs.Count -gt 0) {
        Write-Ok "برنامه لوکال در حال اجراست ($($procs.Count) پروسه)"
        $procs | ForEach-Object { Write-Info "PID $($_.ProcessId)" }
    } else {
        Write-Info "برنامه لوکال خاموش است"
    }

    if (Test-Path $LogFile) {
        $len = (Get-Item $LogFile).Length
        Write-Info "لاگ لوکال: logs\app.log ($len bytes)"
    }

    Write-Host ""
    Write-Host "--- وضعیت GitHub Actions ---" -ForegroundColor White
    if (-not (Test-GhAvailable)) {
        Write-Err "دستور gh پیدا نشد. GitHub CLI را نصب/لاگین کن."
        return
    }
    try {
        gh run list --workflow=$Workflow --limit 5
        Write-Host ""
        $branch = (git rev-parse --abbrev-ref HEAD 2>$null)
        $sha = (git rev-parse --short HEAD 2>$null)
        Write-Info "git: $branch @ $sha"
        git status -sb
    } catch {
        Write-Err $_.Exception.Message
    }
}

function Start-LocalApp {
    Write-Banner
    $session = Get-SessionName
    Write-Info "شروع با SESSION_NAME=$session"

    $existing = @(Get-LocalPythonPids)
    if ($existing.Count -gt 0) {
        Write-Warn "از قبل در حال اجراست. اول stop-local بزن."
        return
    }
    if (Test-Path $LockFile) {
        Write-Warn "قفل قدیمی هست — پاک می‌کنم"
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "python"
    $psi.Arguments = "main.py"
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    # Prefer Start-Process detached so menu returns
    Start-Process -FilePath "python" -ArgumentList "main.py" -WorkingDirectory $Root -WindowStyle Minimized
    Start-Sleep -Seconds 3

    $procs = @(Get-LocalPythonPids)
    if ($procs.Count -gt 0) {
        Write-Ok "لوکال روشن شد (PID $($procs[0].ProcessId))"
        Write-Info "لاگ زنده: .\manage.ps1 logs"
        Write-Info "چت تلگرام → رمز ادمین → /promo help"
    } else {
        Write-Warn "پروسه دیده نشد — شاید سریع بسته شده. لاگ را ببین:"
        if (Test-Path $LogFile) {
            Get-Content $LogFile -Tail 30
        }
    }
}

function Stop-LocalApp {
    Write-Banner
    $procs = @(Get-LocalPythonPids)
    if ($procs.Count -eq 0) {
        Write-Info "چیزی برای توقف نبود"
        if (Test-Path $LockFile) {
            Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
            Write-Ok "قفل پاک شد"
        }
        return
    }
    foreach ($p in $procs) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Ok "متوقف شد PID $($p.ProcessId)"
        } catch {
            Write-Err "نتوانستم PID $($p.ProcessId) را ببندم: $($_.Exception.Message)"
        }
    }
    Start-Sleep -Seconds 1
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    Write-Ok "لوکال خاموش شد"
}

function Show-LocalLogs {
    Write-Banner
    if (-not (Test-Path $LogFile)) {
        Write-Err "لاگ پیدا نشد: $LogFile"
        return
    }
    Write-Info "آخرین $Tail خط از logs\app.log"
    Write-Host "----------------------------------------" -ForegroundColor DarkGray
    Get-Content $LogFile -Tail $Tail
}

function Show-GhaList {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh نیست"; return }
    gh run list --workflow=$Workflow --limit 10
}

function Show-GhaLogs {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh نیست"; return }
    $id = $RunId
    if (-not $id) {
        $id = gh run list --workflow=$Workflow --limit 1 --json databaseId --jq ".[0].databaseId"
    }
    if (-not $id) { Write-Err "ران پیدا نشد"; return }
    Write-Info "لاگ ران $id (فیلترهای مهم)"
    # While in progress, --log may fail; still try
    $raw = gh run view $id --log 2>&1 | Out-String
    if ($raw -match "still in progress") {
        Write-Warn "ران هنوز تمام نشده؛ لاگ کامل بعداً می‌آید."
        Write-Info "صفحه وب:"
        gh run view $id --json url --jq .url
        return
    }
    $raw -split "`n" |
        Select-String -Pattern "Connected as|Route:|watching|promo_|Delivered|Album|Caption|Error|error|AuthKey|Active modules|DRY-RUN|enqueued" |
        Select-Object -Last $Tail |
        ForEach-Object { $_.Line }
}

function Invoke-GhaCancel {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh نیست"; return }
    $id = $RunId
    if (-not $id) {
        $id = gh run list --workflow=$Workflow --limit 1 --json databaseId,status --jq '.[] | select(.status=="in_progress" or .status=="queued") | .databaseId' | Select-Object -First 1
    }
    if (-not $id) { Write-Info "ران فعالی برای کنسل نبود"; return }
    if (-not $Yes) {
        $ans = Read-Host "ران $id کنسل شود؟ (y/N)"
        if ($ans -notmatch '^[yY]') { Write-Info "لغو شد"; return }
    }
    gh run cancel $id
    Write-Ok "درخواست کنسل ارسال شد: $id"
}

function Invoke-GhaDispatch {
    Write-Banner
    if (-not (Test-GhAvailable)) { Write-Err "gh نیست"; return }
    gh workflow run $Workflow --ref master
    Start-Sleep -Seconds 4
    Write-Ok "ران جدید درخواست شد"
    gh run list --workflow=$Workflow --limit 3
}

function Invoke-GhaRestart {
    Write-Banner
    Write-Info "۱) کنسل ران فعلی  ۲) استارت ران جدید با آخرین کد master"
    if (-not $Yes) {
        $ans = Read-Host "ادامه؟ (y/N)"
        if ($ans -notmatch '^[yY]') { Write-Info "لغو شد"; return }
    }
    $script:Yes = $true
    Invoke-GhaCancel
    Start-Sleep -Seconds 3
    Invoke-GhaDispatch
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
        # also check uncommitted
        $dirty = git status --porcelain
        if (-not $dirty) {
            Write-Info "چیزی برای push نیست (تمیز و هم‌تراز با origin)"
            return
        }
        Write-Warn "تغییرات commit‌نشده هست. اول commit کن، بعد push."
        return
    }
    if (-not $Yes) {
        $ans = Read-Host "push به origin/master؟ ($ahead کامیت جلوتر) (y/N)"
        if ($ans -notmatch '^[yY]') { Write-Info "لغو شد"; return }
    }
    git push -u origin HEAD
    Write-Ok "push انجام شد"
}

function Open-ActionsPage {
    Start-Process "https://github.com/$RepoSlug/actions/workflows/run-every-6h.yml"
    Write-Ok "صفحه Actions باز شد"
}

function Open-RepoPage {
    Start-Process "https://github.com/$RepoSlug"
    Write-Ok "صفحه ریپو باز شد"
}

function Show-Help {
    Write-Banner
    Write-Host @"

حالت منو:
  .\manage.ps1

حالت پارامتری (بدون منو):
  .\manage.ps1 status
  .\manage.ps1 start-local
  .\manage.ps1 stop-local
  .\manage.ps1 logs [-Tail 100]
  .\manage.ps1 gha-list
  .\manage.ps1 gha-logs [-RunId 123] [-Tail 80]
  .\manage.ps1 gha-cancel [-RunId 123] [-Yes]
  .\manage.ps1 gha-dispatch
  .\manage.ps1 gha-restart [-Yes]
  .\manage.ps1 git-status
  .\manage.ps1 git-push [-Yes]
  .\manage.ps1 open-actions
  .\manage.ps1 open-repo
  .\manage.ps1 help

نکته مهم:
  لوکال باید SESSION_NAME=dev_seen باشد.
  GHA از easy_seen استفاده می‌کند — هم‌زمان با هم اجرا نکن.

"@
}

function Show-Menu {
    while ($true) {
        Write-Banner
        Write-Host ""
        Write-Host "  ۱) وضعیت کلی (لوکال + گیت‌هاب)" -ForegroundColor White
        Write-Host "  ۲) روشن کردن برنامه لوکال" -ForegroundColor White
        Write-Host "  ۳) خاموش کردن برنامه لوکال" -ForegroundColor White
        Write-Host "  ۴) دیدن لاگ لوکال" -ForegroundColor White
        Write-Host ""
        Write-Host "  ۵) لیست ران‌های GitHub" -ForegroundColor White
        Write-Host "  ۶) لاگ آخرین ران GitHub" -ForegroundColor White
        Write-Host "  ۷) ری‌استارت GitHub (کنسل + ران جدید)" -ForegroundColor White
        Write-Host "  ۸) فقط کنسل ران فعلی GitHub" -ForegroundColor White
        Write-Host "  ۹) فقط استارت ران جدید GitHub" -ForegroundColor White
        Write-Host ""
        Write-Host "  ۱۰) وضعیت git" -ForegroundColor White
        Write-Host "  ۱۱) push به گیت‌هاب" -ForegroundColor White
        Write-Host "  ۱۲) باز کردن صفحه Actions در مرورگر" -ForegroundColor White
        Write-Host "  ۱۳) باز کردن ریپو در مرورگر" -ForegroundColor White
        Write-Host "  ۱۴) راهنما" -ForegroundColor White
        Write-Host "  ۰) خروج" -ForegroundColor DarkGray
        Write-Host ""
        $choice = Read-Host "شماره را بزن"

        switch ($choice) {
            "1" { Show-Status; Pause-Menu }
            "2" { Start-LocalApp; Pause-Menu }
            "3" { Stop-LocalApp; Pause-Menu }
            "4" {
                $t = Read-Host "چند خط آخر؟ (پیش‌فرض $Tail)"
                if ($t -match '^\d+$') { $script:Tail = [int]$t }
                Show-LocalLogs; Pause-Menu
            }
            "5" { Show-GhaList; Pause-Menu }
            "6" { Show-GhaLogs; Pause-Menu }
            "7" { Invoke-GhaRestart; Pause-Menu }
            "8" { Invoke-GhaCancel; Pause-Menu }
            "9" { Invoke-GhaDispatch; Pause-Menu }
            "10" { Show-GitStatus; Pause-Menu }
            "11" { Invoke-GitPush; Pause-Menu }
            "12" { Open-ActionsPage; Pause-Menu }
            "13" { Open-RepoPage; Pause-Menu }
            "14" { Show-Help; Pause-Menu }
            "0" { Write-Host "خداحافظ."; return }
            default { Write-Warn "شماره نامعتبر"; Start-Sleep -Seconds 1 }
        }
    }
}

function Pause-Menu {
    Write-Host ""
    Read-Host "Enter بزن تا برگردی به منو" | Out-Null
}

# ---- entry ----
if (-not $Command -or $Command -eq "menu") {
    Show-Menu
    exit 0
}

switch ($Command) {
    "status"       { Show-Status }
    "start-local"  { Start-LocalApp }
    "stop-local"   { Stop-LocalApp }
    "logs"         { Show-LocalLogs }
    "gha-list"     { Show-GhaList }
    "gha-logs"     { Show-GhaLogs }
    "gha-cancel"   { Invoke-GhaCancel }
    "gha-dispatch" { Invoke-GhaDispatch }
    "gha-restart"  { Invoke-GhaRestart }
    "git-status"   { Show-GitStatus }
    "git-push"     { Invoke-GitPush }
    "open-actions" { Open-ActionsPage }
    "open-repo"    { Open-RepoPage }
    "help"         { Show-Help }
    default        { Show-Help }
}

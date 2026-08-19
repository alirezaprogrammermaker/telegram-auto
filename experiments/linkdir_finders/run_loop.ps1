# Local always-on helper for the experimental linkdir catalog.
# Does not touch production promo modules.
#
# Usage (PowerShell):
#   .\experiments\linkdir_finders\run_loop.ps1
#   .\experiments\linkdir_finders\run_loop.ps1 -EveryHours 8
#   .\experiments\linkdir_finders\run_loop.ps1 -Steps "snowball,rerank"

param(
    [double]$EveryHours = 12,
    [string]$Steps = "search,snowball,rerank",
    [string]$Session = "easy_seen"
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")
$env:PYTHONIOENCODING = "utf-8"

Write-Host "linkdir pipeline loop every=${EveryHours}h steps=$Steps session=$Session"
python -m experiments.linkdir_finders.pipeline loop --every-hours $EveryHours --steps $Steps --session $Session

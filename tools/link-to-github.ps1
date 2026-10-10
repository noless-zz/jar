<#
  Turns this jar folder into a clone of github.com/noless-zz/jar, keeping everything that
  isn't in the repo (config.toml, data\, notes\, .venv\). Run once.
  Afterwards: Android Studio -> Open -> this folder's "android" subfolder.
#>
param([string]$Url = "https://github.com/noless-zz/jar.git")
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "git is not installed. Install it with: winget install Git.Git  (then open a new terminal)" -ForegroundColor Red; exit 1
}
if (Test-Path ".git") { Write-Host "Already a git repo:"; & git remote -v; exit 0 }
& git init -b main | Out-Null
& git remote add origin $Url
& git fetch origin
if ($LASTEXITCODE -ne 0) { Write-Host "fetch failed - check the URL / your sign-in" -ForegroundColor Red; exit 1 }
# Files tracked by the repo take the GitHub version; untracked/ignored files are left alone.
& git reset --hard origin/main
& git branch --set-upstream-to=origin/main main | Out-Null
Write-Host ""
& git status --short
Write-Host "Linked to $Url" -ForegroundColor Green

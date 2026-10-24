<#
  Publishes a new family version of the Android app:
  writes the version into android\VERSION, commits and pushes. GitHub Actions builds the signed APK
  and attaches it to a Release; family phones then show "Update" (within ~6 hours, or at once
  from the menu: Check for updates).

  Usage:  .\tools\publish-release.ps1 0.4.0      (or leave out the version to be asked)
        .\tools\publish-release.ps1 0.4.0 -Yes (commit any open changes without asking)
#>
param([string]$Version = "", [switch]$Yes)
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "git is not installed. Install it with: winget install Git.Git" -ForegroundColor Red; exit 1
}
& git pull --ff-only origin main | Out-Null
$last = if (Test-Path "android\VERSION") { (Get-Content "android\VERSION" -Raw).Trim() } else { "" }
if (-not $Version) {
    $Version = Read-Host "Version to publish (last: $(if ($last) { $last } else { 'none' }))"
}
$Version = $Version.Trim().TrimStart("v")
if ($Version -notmatch '^\d+\.\d{1,2}\.\d{1,2}$') { Write-Host "Use a version like 0.4.0" -ForegroundColor Red; exit 1 }
$tag = "v$Version"
if ($last -and ([version]$Version -le [version]$last)) { Write-Host "Pick a version higher than $last" -ForegroundColor Red; exit 1 }

$dirty = & git status --porcelain
if ($dirty) {
    Write-Host "You have changes that are not committed yet:" -ForegroundColor Yellow
    $dirty | ForEach-Object { Write-Host "  $_" }
    $ans = if ($Yes) { "y" } else { Read-Host "Commit them all and publish $tag? (y/n)" }
    if ($ans -ne "y") { exit 1 }
    & git add -A
    & git commit -m "Changes for $tag"
    if ($LASTEXITCODE -ne 0) { exit 1 }
}
Set-Content -Path "android\VERSION" -Value $Version -Encoding ascii
& git add android/VERSION
& git commit -m "Release $tag"
if ($LASTEXITCODE -ne 0) { Write-Host "commit failed" -ForegroundColor Red; exit 1 }
& git push origin HEAD
if ($LASTEXITCODE -ne 0) { Write-Host "git push failed" -ForegroundColor Red; exit 1 }
Write-Host ""
Write-Host "Pushed $tag. GitHub tests it on Android emulators, then builds it (about 15 minutes):" -ForegroundColor Green
Write-Host "  https://github.com/noless-zz/jar/actions"
Write-Host "When it's done the APK is at https://github.com/noless-zz/jar/releases/latest"

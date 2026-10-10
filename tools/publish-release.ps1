<#
  Publishes a new family version of the Android app:
  tags the current commit as vX.Y.Z and pushes it. GitHub Actions builds the signed APK
  and attaches it to a Release; family phones then show "Update" (within ~6 hours, or at once
  from the menu: Check for updates).

  Usage:  .\tools\publish-release.ps1 0.4.0      (or leave out the version to be asked)
#>
param([string]$Version = "")
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "git is not installed. Install it with: winget install Git.Git" -ForegroundColor Red; exit 1
}
$last = (& git tag --list "v*" --sort=-v:refname | Select-Object -First 1)
if (-not $Version) {
    $Version = Read-Host "Version to publish (last: $(if ($last) { $last } else { 'none' }))"
}
$Version = $Version.Trim().TrimStart("v")
if ($Version -notmatch '^\d+\.\d{1,2}\.\d{1,2}$') { Write-Host "Use a version like 0.4.0" -ForegroundColor Red; exit 1 }
$tag = "v$Version"
if (& git tag --list $tag) { Write-Host "$tag already exists. Pick a higher version." -ForegroundColor Red; exit 1 }

$dirty = & git status --porcelain
if ($dirty) {
    Write-Host "You have changes that are not committed yet:" -ForegroundColor Yellow
    $dirty | ForEach-Object { Write-Host "  $_" }
    $ans = Read-Host "Commit them all as 'Release $tag' and publish? (y/n)"
    if ($ans -ne "y") { exit 1 }
    & git add -A
    & git commit -m "Release $tag"
    if ($LASTEXITCODE -ne 0) { exit 1 }
}
& git push origin HEAD
if ($LASTEXITCODE -ne 0) { Write-Host "git push failed" -ForegroundColor Red; exit 1 }
& git tag -a $tag -m "Jar $Version"
& git push origin $tag
if ($LASTEXITCODE -ne 0) { Write-Host "pushing the tag failed" -ForegroundColor Red; exit 1 }
Write-Host ""
Write-Host "Tagged $tag. GitHub is building it now (about 5 minutes):" -ForegroundColor Green
Write-Host "  https://github.com/noless-zz/jar/actions"
Write-Host "When it's done the APK is at https://github.com/noless-zz/jar/releases/latest"

<#
  Puts the Android release signing key into the GitHub repo's Actions secrets, so the
  "Android release" workflow can build signed APKs. Run once (and again only if the key changes).

  Uses the GitHub CLI (gh) when it is installed and signed in; otherwise copies each value to the
  clipboard and opens the GitHub page so you can paste it.

  The key itself stays on this PC in data\secrets. Back that folder up: without the key, future
  updates can't be installed over the family's app (they would have to uninstall and pair again).
#>
param(
    [string]$Repo = "noless-zz/jar",
    [string]$Properties = "$PSScriptRoot\..\data\secrets\android-signing.properties"
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path $Properties)) { throw "Not found: $Properties (the release key setup is missing)" }
$p = @{}
foreach ($line in Get-Content $Properties) {
    if ($line -match '^\s*([^#=\s]+)\s*=\s*(.*)$') { $p[$Matches[1]] = $Matches[2].Trim() }
}
$ks = $p["storeFile"]
if (-not [System.IO.Path]::IsPathRooted($ks)) { $ks = Join-Path (Split-Path $Properties) $ks }
if (-not (Test-Path $ks)) { throw "Keystore not found: $ks" }

$secrets = [ordered]@{
    "JAR_KEYSTORE_BASE64"   = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path $ks)))
    "JAR_KEYSTORE_PASSWORD" = $p["storePassword"]
    "JAR_KEY_ALIAS"         = $p["keyAlias"]
    "JAR_KEY_PASSWORD"      = $p["keyPassword"]
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
$ghOk = $false
if ($gh) {
    $ErrorActionPreference = "Continue"
    & gh auth status *> $null
    $ghOk = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = "Stop"
}

if ($ghOk) {
    foreach ($k in $secrets.Keys) {
        $secrets[$k] | & gh secret set $k --repo $Repo
        if ($LASTEXITCODE -ne 0) { throw "gh secret set $k failed" }
        Write-Host "  set $k" -ForegroundColor Green
    }
    Write-Host "Done. Publish a version with the VS Code task 'Android: Publish release'." -ForegroundColor Green
    exit 0
}

Write-Host "GitHub CLI not available (or not signed in), so this goes by hand: 4 secrets." -ForegroundColor Yellow
Write-Host "For each one: the value is on your clipboard - in the browser click 'New repository secret'," 
Write-Host "type the NAME shown here, paste the value, Add secret, then come back and press Enter."
Start-Process "https://github.com/$Repo/settings/secrets/actions"
foreach ($k in $secrets.Keys) {
    Set-Clipboard -Value $secrets[$k]
    Read-Host "  Name: $k  (value copied)  - press Enter when added"
}
Set-Clipboard -Value " "
Write-Host "Done. Publish a version with the VS Code task 'Android: Publish release'." -ForegroundColor Green

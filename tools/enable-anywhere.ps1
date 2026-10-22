<#
  Let the family's phones reach Jar from anywhere, with nothing to install on the phones.

    .\tools\enable-anywhere.ps1          turn it on (run once; it stays on after restarts)
    .\tools\enable-anywhere.ps1 -Off     turn it off again
    .\tools\enable-anywhere.ps1 -Status  show what is published

  How: Tailscale Funnel publishes ONLY the phone API (/v1) of this PC at
  https://<this-pc>.<tailnet>.ts.net, with a real HTTPS certificate. The dashboard, the pairing
  page and memo audio stay private (the server also refuses them for internet requests).
  Every request still needs a family member's token, and wrong tokens are throttled.

  The first time, Tailscale may print a link to approve Funnel (and HTTPS) for your tailnet:
  open it, click approve, and this script carries on by itself.
  The app learns the new address on its next sync at home, or re-pair from the dashboard's pair page.
  Jar's supervisor then keeps it on: if the Funnel drops (Tailscale restarted or updated), it publishes it
  again by itself (server/anywhere.py). data\anywhere.json records that you want it on; -Off clears it.
#>
param([switch]$Off, [switch]$Status)
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")

function Find-Tailscale {
    $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in @("$env:ProgramFiles\Tailscale\tailscale.exe", "${env:ProgramFiles(x86)}\Tailscale\tailscale.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

$ts = Find-Tailscale
if (-not $ts) { Write-Host "Tailscale is not installed on this PC (https://tailscale.com/download)." -ForegroundColor Red; exit 1 }

$port = "8080"
if (Test-Path "config.toml") {
    $m = [regex]::Match((Get-Content config.toml -Raw -Encoding UTF8), '(?m)^\s*port\s*=\s*(\d+)')
    if ($m.Success) { $port = $m.Groups[1].Value }
}

if ($Off) {
    Set-Content -Path "data\anywhere.json" -Value '{"on": false}' -Encoding ascii
    & $ts funnel reset
    Write-Host "Funnel is off. Phones reach Jar only at home or over Tailscale again." -ForegroundColor Yellow
    exit 0
}
if ($Status) { & $ts funnel status; exit 0 }

$st = & $ts status --json 2>$null | Out-String
if (-not $st.Trim()) { Write-Host "Tailscale is not running - start it and sign in first." -ForegroundColor Red; exit 1 }
$self = ($st | ConvertFrom-Json).Self
$dns = "$($self.DNSName)".TrimEnd(".")
if (-not $dns) { Write-Host "This PC has no Tailscale name yet (MagicDNS off?). Turn on MagicDNS in the Tailscale admin console." -ForegroundColor Red; exit 1 }
$public = "https://$dns"

try { Invoke-RestMethod "http://127.0.0.1:$port/v1/health" -TimeoutSec 5 | Out-Null }
catch { Write-Host "Jar is not answering on port $port - start it first (.\start-jar.ps1)." -ForegroundColor Red; exit 1 }

function Test-Public {
    foreach ($i in 1..10) {
        try {
            $r = Invoke-RestMethod "$public/v1/health" -TimeoutSec 8
            if ($r.ok) { return $true }
        } catch { }
        Start-Sleep -Seconds 3
    }
    return $false
}

Write-Host "Publishing Jar's phone API at $public/v1 ..."
Write-Host "(If a login.tailscale.com link appears below, open it and approve; this window then continues.)" -ForegroundColor Cyan
& $ts funnel --bg --set-path /v1 "http://127.0.0.1:$port/v1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tailscale refused (see the message above). Approve Funnel in the admin console, then run this again." -ForegroundColor Red
    exit 1
}

Write-Host "Checking it answers (the first HTTPS certificate can take up to a minute)..."
$ok = Test-Public
if (-not $ok) {
    # Some Tailscale versions pass the full path on: map /v1 to the server root instead.
    & $ts funnel --bg --set-path /v1 off 2>$null | Out-Null
    & $ts funnel --bg --set-path /v1 "http://127.0.0.1:$port" | Out-Null
    $ok = Test-Public
}

& $ts funnel status
New-Item -ItemType Directory -Force "data" | Out-Null
Set-Content -Path "data\anywhere.json" -Value '{"on": true}' -Encoding ascii   # the supervisor keeps it on
if ($ok) {
    Write-Host ""
    Write-Host "Done: phones can reach Jar at $public from anywhere - no Tailscale app needed." -ForegroundColor Green
    Write-Host "Only /v1 is public; the dashboard stays on this PC. Turn off with: .\tools\enable-anywhere.ps1 -Off"
    Write-Host "Phones pick the address up on their next sync at home (app 0.6.0+), or re-pair from the pair page."
} else {
    Write-Host ""
    Write-Host "Published, but $public/v1/health did not answer yet. Wait a minute and try it in a browser;" -ForegroundColor Yellow
    Write-Host "it should show {""ok"":true}. If not, run: .\tools\enable-anywhere.ps1 -Status" -ForegroundColor Yellow
}

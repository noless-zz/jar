<#
  Lets the phone (and later the pendant) reach the Jar server through Windows Firewall:
    - from your home network (private networks only)
    - over Tailscale (only from Tailscale addresses, 100.64.0.0/10)
  Asks for administrator rights once (UAC). Safe to run again: it replaces its own rules.
#>
param([int]$Port = 0)
Set-Location $PSScriptRoot

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Port", "$Port")
    return
}

if ($Port -eq 0) {
    $cfg = if (Test-Path config.toml) { Get-Content config.toml -Raw } else { "" }
    $m = [regex]::Match($cfg, 'port\s*=\s*(\d+)')
    $Port = if ($m.Success) { [int]$m.Groups[1].Value } else { 8080 }
}

Get-NetFirewallRule -DisplayName "Jar server*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "Jar server (home network)" -Direction Inbound -Protocol TCP -LocalPort $Port `
    -Action Allow -Profile Private | Out-Null
New-NetFirewallRule -DisplayName "Jar server (Tailscale)" -Direction Inbound -Protocol TCP -LocalPort $Port `
    -RemoteAddress 100.64.0.0/10 -Action Allow -Profile Any | Out-Null

Write-Host "Firewall: TCP $Port allowed from the home network and from Tailscale." -ForegroundColor Green
Start-Sleep -Seconds 3

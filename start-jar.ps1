<#
  Jar - start / stop / check the server and the memo worker.
    .\start-jar.ps1             start both in the background (logs in data\logs)
    .\start-jar.ps1 -Status     are they running? last log lines, memo counts
    .\start-jar.ps1 -Stop       stop both
    .\start-jar.ps1 -Foreground run the worker in this window (server in background) - for watching/debugging
#>
param([switch]$Stop, [switch]$Status, [switch]$Foreground)
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$vpy  = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$logs = Join-Path $PSScriptRoot "data\logs"
$pids = Join-Path $PSScriptRoot "data\pids.json"
New-Item -ItemType Directory -Force $logs | Out-Null
if (-not (Test-Path $vpy)) { throw "Run .\setup.ps1 first." }

$cfg  = Get-Content config.toml -Raw -Encoding UTF8
$port = ([regex]::Match($cfg, 'port\s*=\s*(\d+)')).Groups[1].Value
if (-not $port) { $port = "8080" }

# The .venv python.exe on Windows is a small launcher that starts the real interpreter as a
# child process, so the PID Start-Process returns is not the one doing the work. Find Jar's
# processes by command line, keep only those from THIS folder's .venv (or children of it),
# and always kill whole process trees.
$venvDir = (Join-Path $PSScriptRoot ".venv").ToLower()

function Get-OurPython {
    $all = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue)
    $byId = @{}
    foreach ($p in $all) { $byId[[int]$p.ProcessId] = $p }
    foreach ($p in $all) {
        $exe = "$($p.ExecutablePath)".ToLower()
        $parent = $byId[[int]$p.ParentProcessId]
        $parentExe = if ($parent) { "$($parent.ExecutablePath)".ToLower() } else { "" }
        if ($exe.StartsWith($venvDir) -or $parentExe.StartsWith($venvDir)) { $p }
    }
}

function Get-JarProcs {
    $out = @{}
    foreach ($p in Get-OurPython) {
        $cl = "$($p.CommandLine)"
        if ($cl -match "server\.server:app" -and -not $out["server"]) { $out["server"] = $p }
        elseif ($cl -match "-m\s+worker(\s|$)" -and $cl -notmatch "--(once|check|warmup|retry-failed)" -and -not $out["worker"]) { $out["worker"] = $p }
    }
    return $out
}

function Stop-Jar {
    $stopped = 0
    foreach ($round in 1..2) {          # launcher + child: a second pass catches anything left
        foreach ($p in Get-OurPython) {
            $cl = "$($p.CommandLine)"
            if ($cl -match "server\.server:app" -or ($cl -match "-m\s+worker(\s|$)" -and $cl -notmatch "--(check|warmup)")) {
                & taskkill.exe /PID $p.ProcessId /T /F 2>$null | Out-Null
                $stopped++
            }
        }
        Start-Sleep -Milliseconds 500
    }
    if (Test-Path $pids) { Remove-Item $pids }
    Write-Host ("stopped {0} Jar process(es)" -f $stopped)
}

function Show-Status {
    $procs = Get-JarProcs
    foreach ($name in @("server", "worker")) {
        if ($procs[$name]) { Write-Host ("{0,-7} running (pid {1})" -f $name, $procs[$name].ProcessId) -ForegroundColor Green }
        else               { Write-Host ("{0,-7} not running" -f $name) -ForegroundColor Yellow }
    }
    try { Invoke-RestMethod "http://localhost:$port/v1/health" -TimeoutSec 3 | Out-Null; Write-Host "server  answers on port $port" -ForegroundColor Green }
    catch { Write-Host "server  not answering on port $port" -ForegroundColor Yellow }
    try { Invoke-RestMethod "http://localhost:11434/api/version" -TimeoutSec 3 | Out-Null; Write-Host "ollama  running" -ForegroundColor Green }
    catch { Write-Host "ollama  not running (start the Ollama app)" -ForegroundColor Yellow }

    $counts = @{}
    Get-ChildItem "data\memos\*\*.json" -ErrorAction SilentlyContinue | ForEach-Object {
        $s = (Get-Content $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json).status
        $counts[$s] = 1 + [int]$counts[$s]
    }
    $hb = Join-Path $PSScriptRoot "data\worker.json"
    if (Test-Path $hb) {
        $w = Get-Content $hb -Raw | ConvertFrom-Json
        $age = [int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $w.epoch)
        Write-Host ("worker  last heartbeat {0}s ago: {1} ({2}, {3})" -f $age, $w.doing, $w.whisper, $w.llm)
    }
    if ($counts.Count) { Write-Host ("memos   " + (($counts.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name): $($_.Value)" }) -join ", ")) }
    $wl = Join-Path $logs "worker.log"
    if (Test-Path $wl) { Write-Host "`n--- last worker log lines"; Get-Content $wl -Tail 8 -Encoding UTF8 }
    Write-Host "`nDashboard: http://localhost:$port"
}

if ($Stop)   { Stop-Jar; return }
if ($Status) { Show-Status; return }

# Start (restart cleanly if already running)
Stop-Jar

# New packages since last start (requirements.txt changed)? Install them first.
$stamp = Join-Path $PSScriptRoot ".venv\.requirements-installed"
if (-not (Test-Path $stamp) -or (Get-Item "requirements.txt").LastWriteTime -gt (Get-Item $stamp).LastWriteTime) {
    Write-Host "installing new Python packages..."
    & $vpy -m pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -eq 0) { Set-Content $stamp (Get-Date -Format o) }
}
$server = Start-Process $vpy -ArgumentList "-m", "uvicorn", "server.server:app", "--host", "0.0.0.0", "--port", $port `
          -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru `
          -RedirectStandardOutput (Join-Path $logs "server.out.log") -RedirectStandardError (Join-Path $logs "server.log")
$state = @{ server = $server.Id }

if ($Foreground) {
    $state | ConvertTo-Json | Set-Content $pids
    Write-Host "server started (pid $($server.Id)); worker running here - Ctrl+C to stop it" -ForegroundColor Green
    & $vpy -m worker
    return
}

$worker = Start-Process $vpy -ArgumentList "-m", "worker" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru `
          -RedirectStandardOutput (Join-Path $logs "worker.out.log") -RedirectStandardError (Join-Path $logs "worker.err.log")
$state.worker = $worker.Id
$state | ConvertTo-Json | Set-Content $pids
Start-Sleep -Seconds 4
Show-Status

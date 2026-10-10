<#
  Jar - one-time setup (safe to run again).
    1. Python virtual environment + packages (FastAPI, faster-whisper, CUDA libraries)
    2. config.toml with a fresh device token
    3. Checks Ollama and the model
    4. Downloads Whisper and tests it on the GPU
    5. Shows the address + token to type into the phone app
  Run:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
#>
# Native tools (pip, python) print warnings on stderr; "Continue" keeps those from aborting.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "   OK  $t" -ForegroundColor Green }
function Warn($t) { Write-Host "   !!  $t" -ForegroundColor Yellow }

# ---- 1. Python ----
Step "Python 3.11+"
$pyExe = $null; $pyArgs = @()
foreach ($cand in "py -3.12", "py -3.13", "py -3.11", "python") {
    $parts = $cand -split " "
    $exe = $parts[0]
    $rest = @($parts | Select-Object -Skip 1)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $v = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $v -and [version]"$v" -ge [version]"3.11") { $pyExe = $exe; $pyArgs = $rest; break }
}
if (-not $pyExe) { throw "Python 3.11 or newer not found. Install it from python.org (tick 'Add to PATH') and run again." }
Ok "using $cand (Python $v)"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $pyExe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "could not create .venv" }
    Ok "created .venv"
}
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Step "Packages (first time: a few minutes, ~1.5 GB with the CUDA libraries)"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Ok "packages installed"

# ---- 2. Config ----
Step "config.toml"
if (-not (Test-Path "config.toml")) {
    Copy-Item config.example.toml config.toml
}
$cfg = Get-Content config.toml -Raw -Encoding UTF8
if ($cfg -match 'token = "CHANGE-ME"') {
    $token = -join ((1..24) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })
    $cfg = $cfg -replace 'token = "CHANGE-ME"', ('token = "' + $token + '"')
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot "config.toml"), $cfg, (New-Object Text.UTF8Encoding $false))
    Ok "generated a new device token"
}
$token = ([regex]::Match($cfg, 'token\s*=\s*"([^"]+)"')).Groups[1].Value
$port  = ([regex]::Match($cfg, 'port\s*=\s*(\d+)')).Groups[1].Value
if (-not $port) { $port = "8080" }
$model = ([regex]::Match($cfg, '(?ms)\[llm\].*?model\s*=\s*"([^"]+)"')).Groups[1].Value

# ---- 3. Ollama ----
Step "Ollama ($model)"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $list = (& ollama list) -join "`n"
    if ($list -match [regex]::Escape($model)) { Ok "$model is installed" }
    else { Warn "model not found - pulling $model"; & ollama pull $model }
} else {
    Warn "ollama not on PATH. Install from https://ollama.com and run: ollama pull $model"
}

# ---- 4. Whisper ----
Step "Whisper (downloads the model the first time, ~1.6 GB)"
& $vpy -m worker --warmup
if ($LASTEXITCODE -ne 0) { Warn "Whisper test failed - see data\logs\worker.log" }

# ---- 5. Firewall + phone settings ----
Step "Firewall (phone -> PC on port $port, home network + Tailscale)"
$have = @(Get-NetFirewallRule -DisplayName "Jar server*" -ErrorAction SilentlyContinue).Count
if ($have -ge 2) { Ok "rules exist" }
else {
    Warn "asking Windows for admin rights once (UAC) to add the rules"
    & (Join-Path $PSScriptRoot "allow-firewall.ps1") -Port $port
}

$ips = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
       ForEach-Object { $_.IPv4Address.IPAddress }
Step "Phone app"
Write-Host "   Easiest: start Jar, open the dashboard and click 'Pair a phone', then scan the QR code in the app." -ForegroundColor White
Write-Host "   By hand: server http://<one of these>:$port  token $token"
foreach ($ip in $ips) { Write-Host "            $ip" }
Write-Host "`nDone. Start everything with:  .\start-jar.ps1" -ForegroundColor Green

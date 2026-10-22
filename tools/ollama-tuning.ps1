<#
  Makes Ollama use less GPU memory for Jar's context window, so a bigger [llm] num_ctx still fits:
    OLLAMA_FLASH_ATTENTION=1   flash attention (needed for the next one; also a bit faster)
    OLLAMA_KV_CACHE_TYPE=q8_0  the context (KV) cache at 8 bits: about half the memory, no real quality loss
  Sets both for your Windows user (permanent), restarts Ollama, loads Jar's model once with Jar's
  num_ctx and shows "ollama ps": PROCESSOR should say 100% GPU.

  Usage:  powershell -ExecutionPolicy Bypass -File .\tools\ollama-tuning.ps1
          ... -NoRestart   only load the model and show "ollama ps" (Ollama already restarted)
  Undo:   [Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", $null, "User")   (and the same for
          OLLAMA_FLASH_ATTENTION), then restart Ollama.
#>
param([switch]$NoRestart)
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")

[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", "q8_0", "User")
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_KV_CACHE_TYPE = "q8_0"
Write-Host "set OLLAMA_FLASH_ATTENTION=1 and OLLAMA_KV_CACHE_TYPE=q8_0 for your user" -ForegroundColor Green

# Jar's model and context window from config.toml
$model = "qwen3.5:9b"; $ctx = 12288; $keep = "10m"
if (Test-Path "config.toml") {
    $cfg = Get-Content "config.toml" -Raw
    # only the [llm] section (other sections have their own "model =", e.g. Whisper's)
    if ($cfg -match '(?ms)^\[llm\][^\r\n]*\r?\n(.*?)(?=^\[|\z)') { $cfg = $Matches[1] }
    if ($cfg -match '(?m)^\s*model\s*=\s*"([^"]+)"') { $model = $Matches[1] }
    if ($cfg -match '(?m)^\s*num_ctx\s*=\s*(\d+)') { $ctx = [int]$Matches[1] }
    if ($cfg -match '(?m)^\s*keep_alive\s*=\s*"([^"]+)"') { $keep = $Matches[1] }
}

if (-not $NoRestart) {
    Write-Host "restarting Ollama..."
    Get-Process "ollama app", "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    $app = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
    if (Test-Path $app) { Start-Process $app } else { Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden }
}
Write-Host "waiting for Ollama (the app can take a minute or two to start)..."
# Ask the Ollama CLI itself (Windows PowerShell's web calls to localhost can fail on IPv6 or a proxy).
$up = $false
foreach ($i in 1..150) {
    & ollama ps *> $null
    if ($LASTEXITCODE -eq 0) { $up = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $up) { Write-Host "Ollama didn't come back - start the Ollama app by hand, then run this again" -ForegroundColor Red; exit 1 }

Write-Host "loading $model with num_ctx $ctx (first time takes a few seconds)..."
$body = @{ model = $model; prompt = "hi"; stream = $false; keep_alive = $keep; options = @{ num_ctx = $ctx; num_predict = 1 } } | ConvertTo-Json -Depth 4
$tmp = Join-Path $env:TEMP "jar-ollama-load.json"
[IO.File]::WriteAllText($tmp, $body)
# curl.exe ships with Windows; 127.0.0.1 and --noproxy avoid the IPv6/proxy problems of "localhost".
& curl.exe -s -o NUL --noproxy "*" --max-time 180 -H "Content-Type: application/json" -d "@$tmp" "http://127.0.0.1:11434/api/generate"
if ($LASTEXITCODE -ne 0) { Write-Host "loading failed (curl exit $LASTEXITCODE)" -ForegroundColor Red }
Remove-Item $tmp -ErrorAction SilentlyContinue

& ollama ps
Write-Host ""
Write-Host "PROCESSOR should read 100% GPU. If it shows a CPU share, lower num_ctx in config.toml (e.g. 10240)."
Write-Host "Jar's worker also reports this in data\worker.json (""gpu"") and its log."

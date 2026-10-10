<#
  Start Jar automatically when you log in to Windows (Task Scheduler, runs hidden).
    .\install-autostart.ps1          add the task
    .\install-autostart.ps1 -Remove  remove it
  Ollama's own app already starts at login, so it isn't handled here.
#>
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$name = "Jar memo server"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "removed '$name'"
    return
}

$script = Join-Path $PSScriptRoot "start-jar.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT30S"   # give Ollama and the network a moment first
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
try {
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
        -Description "Starts the Jar server and memo worker" -Force | Out-Null
    Write-Host "Jar will start 30 s after you log in. Remove with: .\install-autostart.ps1 -Remove" -ForegroundColor Green
} catch {
    Write-Host "Windows needs admin rights for this. Open PowerShell as Administrator and run this script again." -ForegroundColor Yellow
}

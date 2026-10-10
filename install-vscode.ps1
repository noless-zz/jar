<#
  Copies the VS Code setup (status-bar buttons, tasks, debug configs) from .\vscode into .\.vscode.
  Run once:  powershell -ExecutionPolicy Bypass -File .\install-vscode.ps1   then reload VS Code.
#>
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force ".vscode" | Out-Null
foreach ($f in Get-ChildItem "vscode\*.json") {
    $dest = Join-Path ".vscode" $f.Name
    if ((Test-Path $dest) -and -not (Select-String -Path $dest -Pattern "Jar" -Quiet)) {
        Copy-Item $dest "$dest.bak"
        Write-Host "kept your old $($f.Name) as $($f.Name).bak"
    }
    Copy-Item $f.FullName $dest -Force
    Write-Host "installed .vscode\$($f.Name)"
}
Write-Host "`nReload VS Code (Ctrl+Shift+P -> Developer: Reload Window) and install the recommended extensions." -ForegroundColor Green

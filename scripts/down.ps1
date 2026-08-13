# down.ps1 - Windows counterpart of down.sh.
# Stops the uvicorn backend and the Vite frontend started by up.bat.
$ErrorActionPreference = 'Stop'

$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match 'uvicorn|vite'
}

foreach ($proc in $targets) {
    try {
        Stop-Process -Id $proc.ProcessId -Force
        Write-Host "Stopped $($proc.Name) (PID $($proc.ProcessId))"
    } catch {
        Write-Host "Could not stop $($proc.Name) (PID $($proc.ProcessId)): $($_.Exception.Message)"
    }
}

if (-not $targets) {
    Write-Host 'No uvicorn/vite processes found.'
}

Write-Host ''
Write-Host 'Remember to execute:'
Write-Host 'deactivate'
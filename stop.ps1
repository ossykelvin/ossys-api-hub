param(
    [int]$Port = 8000,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)

if ($listeners.Count -eq 0) {
    Write-Host "Ossy's API Hub is not running on port $Port."
    exit 0
}

$stopped = 0
foreach ($processId in ($listeners.OwningProcess | Sort-Object -Unique)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    $commandLine = [string]$process.CommandLine
    if ($commandLine -notmatch "uvicorn" -or $commandLine -notmatch "app\.main:app") {
        Write-Error "Refusing to stop PID $processId because it is not Ossy's API Hub: $($process.Name)"
        exit 2
    }

    if ($WhatIf) {
        Write-Host "Would stop Ossy's API Hub (PID $processId) on port $Port."
        continue
    }

    Stop-Process -Id $processId
    Write-Host "Stopped Ossy's API Hub (PID $processId) on port $Port."
    $stopped += 1
}

if (-not $WhatIf -and $stopped -eq 0) {
    Write-Error "No Ossy's API Hub process was stopped."
    exit 1
}

[CmdletBinding(SupportsShouldProcess=$true)]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$recordPath = Join-Path $projectRoot 'data\runtime\processes.json'
if (-not (Test-Path -LiteralPath $recordPath)) { Write-Output 'No process record.'; exit 0 }
$records = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
# Validate the full set before stopping anything. A reused PID is never trusted.
foreach ($entry in $records) {
    $process = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    $info = Get-CimInstance Win32_Process -Filter "ProcessId = $($entry.pid)"
    if (-not $entry.started_utc -or -not $entry.executable -or $process.StartTime.ToUniversalTime() -ne ([DateTimeOffset]$entry.started_utc).UtcDateTime -or $info.ExecutablePath -ne $entry.executable) { throw "Identity mismatch for recorded PID $($entry.pid); nothing was stopped. Inspect stale records manually." }
}
foreach ($entry in $records) {
    $process = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
    if ($process -and $PSCmdlet.ShouldProcess("$($entry.name) PID $($entry.pid)",'Stop verified project process tree')) {
        if ($process.StartTime.ToUniversalTime() -ne ([DateTimeOffset]$entry.started_utc).UtcDateTime) { throw 'Process identity changed; refusing stop' }
        taskkill /PID $entry.pid /T /F
        if ($LASTEXITCODE -ne 0) { throw 'Could not stop process; record retained' }
    }
}
Write-Output 'Record retained for identity audit. The start script archives stale records after exit. Interrupted tasks recover through leases.'

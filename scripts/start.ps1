[CmdletBinding()]
param([switch]$Production)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$webRoot = Join-Path $projectRoot 'frontend'
$webArguments = @('node_modules/vite/bin/vite.js')
if ($Production) {
    if (-not (Test-Path -LiteralPath (Join-Path $webRoot 'dist/index.html') -PathType Leaf)) {
        throw 'Build the frontend before starting in production mode.'
    }
    $webArguments += 'preview'
}
$webArguments += @('--host','127.0.0.1','--port','15173','--strictPort')
$runtime = Join-Path $projectRoot 'data\runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
if (Test-Path -LiteralPath (Join-Path $runtime 'processes.json')) {
    $previous = Get-Content -LiteralPath (Join-Path $runtime 'processes.json') -Raw | ConvertFrom-Json
    foreach ($entry in $previous) {
        $existing = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
        if ($existing -and $entry.started_utc -and $existing.StartTime.ToUniversalTime() -eq ([DateTimeOffset]$entry.started_utc).UtcDateTime) { throw 'A recorded process is still alive. Use scripts/stop.ps1 or inspect it first.' }
        if ($existing -and -not $entry.started_utc) {
            $info = Get-CimInstance Win32_Process -Filter "ProcessId = $($entry.pid)"
            if ($info.ExecutablePath -eq (Join-Path $projectRoot '.venv\Scripts\python.exe')) { throw 'Legacy Python process record may still be alive; inspect manually before restarting.' }
        }
    }
    $archive = Join-Path $runtime ('processes.stale.' + [guid]::NewGuid().ToString('N') + '.json')
    Move-Item -LiteralPath (Join-Path $runtime 'processes.json') -Destination $archive
}
foreach ($port in 18000,15173) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw "Port $port is occupied; no existing process was changed." }
}
$priorLogs = @('api.log','api.error.log','worker.log','worker.error.log','web.log','web.error.log')
$datedArchive = Join-Path $runtime ('logs-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
foreach ($fileName in $priorLogs) {
    $priorLog = Join-Path $runtime $fileName
    if (Test-Path -LiteralPath $priorLog -PathType Leaf) {
        New-Item -ItemType Directory -Path $datedArchive -Force | Out-Null
        Move-Item -LiteralPath $priorLog -Destination (Join-Path $datedArchive $fileName)
    }
}
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$node = (Get-Command node -ErrorAction Stop).Source
$records = @()
try {
    $api = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18000') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'api.log') -RedirectStandardError (Join-Path $runtime 'api.error.log') -PassThru
    $records += @{name='api';pid=$api.Id;executable=$python;started_utc=$api.StartTime.ToUniversalTime().ToString('o')}
    $worker = Start-Process -FilePath $python -ArgumentList @('-m','app.worker') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'worker.log') -RedirectStandardError (Join-Path $runtime 'worker.error.log') -PassThru
    $records += @{name='worker';pid=$worker.Id;executable=$python;started_utc=$worker.StartTime.ToUniversalTime().ToString('o')}
    $web = Start-Process -FilePath $node -ArgumentList $webArguments -WorkingDirectory $webRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'web.log') -RedirectStandardError (Join-Path $runtime 'web.error.log') -PassThru
    $records += @{name='web';pid=$web.Id;executable=$node;started_utc=$web.StartTime.ToUniversalTime().ToString('o')}
} finally {
    $records | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'processes.json') -Encoding UTF8
}
Write-Output 'Launch requested. Verify http://127.0.0.1:18000/api/health and http://127.0.0.1:15173 . Logs and PIDs: data/runtime.'

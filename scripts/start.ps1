$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $projectRoot 'data\runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
if (Test-Path -LiteralPath (Join-Path $runtime 'processes.json')) { throw 'A process record exists. Check/stop existing services before restarting.' }
foreach ($port in 18000,15173) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw "Port $port is occupied; no existing process was changed." }
}
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$node = (Get-Command node -ErrorAction Stop).Source
$records = @()
try {
    $api = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18000') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'api.log') -RedirectStandardError (Join-Path $runtime 'api.error.log') -PassThru
    $records += @{name='api';pid=$api.Id}
    $worker = Start-Process -FilePath $python -ArgumentList @('-m','app.worker') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'worker.log') -RedirectStandardError (Join-Path $runtime 'worker.error.log') -PassThru
    $records += @{name='worker';pid=$worker.Id}
    $web = Start-Process -FilePath $node -ArgumentList @('node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','15173','--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'web.log') -RedirectStandardError (Join-Path $runtime 'web.error.log') -PassThru
    $records += @{name='web';pid=$web.Id}
} finally {
    $records | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'processes.json') -Encoding UTF8
}
Write-Output 'Launch requested. Verify http://127.0.0.1:18000/api/health and http://127.0.0.1:15173 . Logs and PIDs: data/runtime.'

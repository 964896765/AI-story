[CmdletBinding()]
param(
    [switch]$ProductionBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'

Push-Location $root
try {
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency check failed.' }
    Push-Location (Join-Path $root 'frontend')
    try {
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    $arguments = @('scripts/isolated_regression.py','--junitxml','data/tmp/release-tests.xml')
    if ($ProductionBrowser) {
        $arguments += @('--browser-phase','p14','--browser')
    }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Isolated release regression failed.' }
} finally { Pop-Location }

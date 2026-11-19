[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $revision = git rev-parse --short=12 HEAD
    if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{12}$') { throw 'Cannot identify the committed release.' }
    $folder = Join-Path $root 'data\releases'
    $artifact = Join-Path $folder "ai-story-v2-$revision.zip"
    if (Test-Path -LiteralPath $artifact) { throw "Release file already exists: $artifact" }
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    git archive --format=zip --prefix="ai-story-v2-$revision/" --output=$artifact HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Could not archive the release commit.' }
    Get-FileHash -LiteralPath $artifact -Algorithm SHA256
} finally { Pop-Location }

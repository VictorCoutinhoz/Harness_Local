param(
    [Parameter(Position = 0)]
    [string] $Target = '.'
)

$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '../skillspector/venv/Scripts/python.exe'
$scanner = Join-Path $PSScriptRoot 'scan-codebase.py'
$root = (Resolve-Path -LiteralPath $Target).ProviderPath
$oldCache = $env:TIKTOKEN_CACHE_DIR
$env:TIKTOKEN_CACHE_DIR = Join-Path $PSScriptRoot 'token-cache'
try {
    & $python -I -B -X utf8 $scanner $root --format json
    $scannerExit = $LASTEXITCODE
} finally {
    $env:TIKTOKEN_CACHE_DIR = $oldCache
}
exit $scannerExit

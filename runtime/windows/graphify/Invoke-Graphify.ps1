param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('extract', 'query', 'path', 'explain', 'version')]
    [string] $Command,
    [Parameter(ValueFromRemainingArguments)]
    [string[]] $GraphifyArgs
)

$ErrorActionPreference = 'Stop'
$graphify = Join-Path $PSScriptRoot 'venv/Scripts/graphify.exe'
if ($GraphifyArgs -match '^--(backend|dedup-llm)(=|$)') {
    throw 'Use os parâmetros de análise local do Graphify.'
}

$oldBackend = $env:GRAPHIFY_BACKEND
$oldQueryLogging = $env:GRAPHIFY_QUERY_LOG_DISABLE
$env:GRAPHIFY_BACKEND = 'none'
$env:GRAPHIFY_QUERY_LOG_DISABLE = '1'
try {
    switch ($Command) {
        'extract' { & $graphify extract @GraphifyArgs --code-only }
        'version' { & $graphify --version }
        default { & $graphify $Command @GraphifyArgs }
    }
    $graphifyExit = $LASTEXITCODE
} finally {
    $env:GRAPHIFY_BACKEND = $oldBackend
    $env:GRAPHIFY_QUERY_LOG_DISABLE = $oldQueryLogging
}
exit $graphifyExit

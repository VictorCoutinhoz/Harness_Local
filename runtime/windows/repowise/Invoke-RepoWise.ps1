$ErrorActionPreference = 'Stop'
$cli = Join-Path $PSScriptRoot 'venv312/Scripts/repowise.exe'
$settings = @{
    REPOWISE_OFFLINE = '1'
    REPOWISE_NO_HINTS = '1'
    REPOWISE_SKIP_EDITOR_SETUP = '1'
    REPOWISE_NO_SAVE_KEY = '1'
    REPOWISE_PROVIDER = 'mock'
    REPOWISE_EMBEDDER = 'mock'
    LITELLM_LOCAL_MODEL_COST_MAP = 'true'
}
$previous = @{}
try {
    foreach ($key in $settings.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $settings[$key], 'Process')
    }
    & $cli @args
    $status = $LASTEXITCODE
} finally {
    foreach ($key in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process')
    }
}
exit $status

$rtkOverrides = @{
    RTK_DB_PATH               = Join-Path $PSScriptRoot 'history.db'
    RTK_RECALL                = '0'
    RTK_TELEMETRY_DISABLED    = '1'
    RTK_SUPPRESS_HOOK_WARNING = '1'
}
$rtkPrevious = @{}
foreach ($rtkKey in $rtkOverrides.Keys) {
    $rtkPrevious[$rtkKey] = [Environment]::GetEnvironmentVariable($rtkKey, 'Process')
    [Environment]::SetEnvironmentVariable($rtkKey, $rtkOverrides[$rtkKey], 'Process')
}

try {
    & (Join-Path $PSScriptRoot 'rtk.exe') @args
    $rtkExit = $LASTEXITCODE
} finally {
    foreach ($rtkKey in $rtkPrevious.Keys) {
        if ($null -eq $rtkPrevious[$rtkKey]) {
            Remove-Item -LiteralPath "Env:$rtkKey" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($rtkKey, $rtkPrevious[$rtkKey], 'Process')
        }
    }
}
exit $rtkExit

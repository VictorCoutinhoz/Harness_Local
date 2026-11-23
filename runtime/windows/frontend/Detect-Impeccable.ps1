[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$Target,

    [ValidatePattern('^[1-9][0-9]*x[1-9][0-9]*$')]
    [string]$Viewport
)

$ErrorActionPreference = 'Stop'
$detector = Join-Path $PSScriptRoot 'impeccable.exe'
$scanTarget = $Target
if ($Target -notmatch '^(?:https?|file)://') {
    $scanTarget = (Resolve-Path -LiteralPath $Target).Path
}
$detectorArgs = @('detect', '--json')
if ($Viewport) {
    $detectorArgs += @('--viewport', $Viewport)
}

$previousTracking = $env:DO_NOT_TRACK
try {
    $env:DO_NOT_TRACK = '1'
    & $detector @detectorArgs $scanTarget
    $detectorExit = $LASTEXITCODE
} finally {
    $env:DO_NOT_TRACK = $previousTracking
}
exit $detectorExit

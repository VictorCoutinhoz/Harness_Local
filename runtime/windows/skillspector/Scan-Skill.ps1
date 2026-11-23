param(
    [Parameter(Mandatory, Position = 0)]
    [string] $Target
)

$ErrorActionPreference = 'Stop'
$skillPath = (Resolve-Path -LiteralPath $Target).ProviderPath
$scanner = Join-Path $PSScriptRoot 'venv/Scripts/skillspector.exe'
if (!(Test-Path -LiteralPath $scanner -PathType Leaf)) {
    throw 'A instalação local do SkillSpector não está disponível.'
}

$launch = [System.Diagnostics.ProcessStartInfo]::new($scanner)
$launch.UseShellExecute = $false
$launch.WorkingDirectory = $PSScriptRoot
foreach ($argument in @('scan', '--no-llm', '--format', 'json', '--', $skillPath)) {
    $launch.ArgumentList.Add($argument)
}
# O cliente HTTPX do analisador usa o fallback local quando OSV.dev está inacessível.
foreach ($name in @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')) {
    $launch.Environment[$name] = 'http://127.0.0.1:1'
}
$launch.Environment['NO_PROXY'] = ''
$launch.Environment['PYTHONIOENCODING'] = 'utf-8'

$process = [System.Diagnostics.Process]::Start($launch)
try {
    $process.WaitForExit()
    exit $process.ExitCode
} finally {
    $process.Dispose()
}

$ErrorActionPreference = 'Stop'
$agentBrowser = Join-Path $PSScriptRoot 'agent-browser.exe'
$configuration = Join-Path $PSScriptRoot 'agent-browser.json'
& $agentBrowser --config $configuration @args
exit $LASTEXITCODE

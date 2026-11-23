$ErrorActionPreference = 'Stop'
$playwrightRoot = if ($env:HARNESS_LOCAL_PLAYWRIGHT_ROOT) {
    $env:HARNESS_LOCAL_PLAYWRIGHT_ROOT
} else {
    $PSScriptRoot
}
$node = Join-Path $playwrightRoot '../runtimes/node/node.exe'
if (!(Test-Path -LiteralPath $node -PathType Leaf)) {
    throw 'Node.js do runtime não encontrado. Confira o diretório de runtimes indicado no perfil.'
}

$cliArgs = @($args)
if ($cliArgs.Count -and $cliArgs[0] -eq 'run-test-mcp-server' -and
    !($cliArgs -match '^(--config|-c)(=|$)')) {
    $config = foreach ($extension in '.ts', '.js', '.mts', '.mjs', '.cts', '.cjs') {
        $candidate = Join-Path $PWD "playwright.config$extension"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $candidate
            break
        }
    }
    if (!$config) {
        $config = Join-Path $playwrightRoot 'mcp-default.config.cjs'
    }
    $cliArgs += @('--config', $config)
}

$projectCli = Join-Path $PWD 'node_modules/playwright/cli.js'
if (Test-Path -LiteralPath $projectCli -PathType Leaf) {
    & $node $projectCli @cliArgs
    exit $LASTEXITCODE
}

$cli = Join-Path $playwrightRoot 'node_modules/playwright/cli.js'
$oldBrowsersPath = $env:PLAYWRIGHT_BROWSERS_PATH
$oldNodePath = $env:NODE_PATH
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $playwrightRoot 'browsers'
$env:NODE_PATH = Join-Path $playwrightRoot 'node_modules'
try {
    & $node $cli @cliArgs
    $playwrightExit = $LASTEXITCODE
} finally {
    $env:PLAYWRIGHT_BROWSERS_PATH = $oldBrowsersPath
    $env:NODE_PATH = $oldNodePath
}
exit $playwrightExit

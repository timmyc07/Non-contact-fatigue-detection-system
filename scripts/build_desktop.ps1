$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$flutterBin = 'C:\tools\flutter\bin'
if (Test-Path $flutterBin) {
    $env:PATH = $flutterBin + ';' + $env:PATH
}
if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw 'Flutter was not found. Install Flutter or update flutterBin in scripts/build_desktop.ps1.'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'npm was not found. Install Node.js.'
}

$env:NCFD_ENGINE_ROOT = $repoRoot
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (Test-Path $pythonPath) {
    $env:NCFD_ENGINE_PYTHON = $pythonPath
}

Push-Location $repoRoot
try {
    npm run desktop:build
} finally {
    Pop-Location
}

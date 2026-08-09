$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$flutterBin = 'C:\tools\flutter\bin'
if (Test-Path $flutterBin) {
    $env:PATH = $flutterBin + ';' + $env:PATH
}

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw 'Flutter was not found. Install Flutter or update flutterBin in scripts/start_desktop.ps1.'
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node.js was not found.'
}
if (-not (Test-Path (Join-Path $repoRoot 'src-tauri/tauri.conf.json'))) {
    throw 'Run this script from a complete project checkout.'
}

$env:NCFD_ENGINE_ROOT = $repoRoot
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (Test-Path $pythonPath) {
    $env:NCFD_ENGINE_PYTHON = $pythonPath
}

Push-Location $repoRoot
try {
    Push-Location (Join-Path $repoRoot 'flutter_app')
    try {
        flutter pub get
    } finally {
        Pop-Location
    }
    if (-not (Test-Path (Join-Path $repoRoot 'node_modules\.bin\tauri.cmd'))) {
        npm install
    }
    npm run desktop
} finally {
    Pop-Location
}

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$flutterBin = 'C:\tools\flutter\bin'
if (Test-Path $flutterBin) {
    $env:PATH = $flutterBin + ';' + $env:PATH
}

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw 'Flutter was not found. Install Flutter or update flutterBin in scripts/start_desktop.ps1.'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'npm was not found. Install Node.js.'
}
if (-not (Test-Path (Join-Path $repoRoot 'src-tauri/tauri.conf.json'))) {
    throw 'Run this script from a complete project checkout.'
}

$env:NCFD_ENGINE_ROOT = $repoRoot
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonPath)) {
    throw 'Python virtual environment was not found. Create .venv and install requirements.txt.'
}
$env:NCFD_ENGINE_PYTHON = $pythonPath

Push-Location $repoRoot
try {
    & $pythonPath -m scripts.runtime_preflight
    if ($LASTEXITCODE -ne 0) {
        throw "Python runtime preflight failed with exit code $LASTEXITCODE."
    }
    Push-Location (Join-Path $repoRoot 'flutter_app')
    try {
        flutter pub get
        if ($LASTEXITCODE -ne 0) {
            throw "flutter pub get failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
    if (-not (Test-Path (Join-Path $repoRoot 'node_modules\.bin\tauri.cmd'))) {
        npm install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE."
        }
    }
    npm run desktop
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri desktop start failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

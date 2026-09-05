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
if (-not (Test-Path $pythonPath)) {
    throw 'Python virtual environment was not found. Create .venv and install requirements.txt.'
}
$env:NCFD_ENGINE_PYTHON = $pythonPath

Push-Location $repoRoot
try {
    npm run desktop:build
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri desktop build failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

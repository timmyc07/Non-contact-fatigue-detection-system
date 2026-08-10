$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project Python was not found: $pythonPath"
}

$modelPath = Join-Path $repoRoot 'models\face_landmarker.task'
$tuningPath = Join-Path $repoRoot 'config\mediapipe_tuning.json'
$webUiPath = Join-Path $repoRoot 'gui\web_ui'
foreach ($requiredPath in @($modelPath, $tuningPath, $webUiPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required engine resource is missing: $requiredPath"
    }
}

$distRoot = Join-Path $repoRoot 'dist'
$engineDist = Join-Path $distRoot 'ncfd-engine'
$workRoot = Join-Path $repoRoot 'build\pyinstaller'
if (Test-Path -LiteralPath $engineDist) {
    Remove-Item -LiteralPath $engineDist -Recurse -Force
}
if (Test-Path -LiteralPath $workRoot) {
    Remove-Item -LiteralPath $workRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
New-Item -ItemType Directory -Path $workRoot -Force | Out-Null

$arguments = @(
    '-m', 'PyInstaller',
    '--noconfirm', '--clean', '--onedir',
    '--name', 'ncfd-engine',
    '--distpath', $distRoot,
    '--workpath', $workRoot,
    '--specpath', $workRoot,
    '--collect-all', 'mediapipe',
    '--collect-all', 'cv2',
    '--exclude-module', 'mediapipe.tasks.python.test',
    '--hidden-import', 'engineio.async_drivers.threading',
    '--hidden-import', 'flask_socketio',
    '--add-data', "$modelPath;models",
    '--add-data', "$tuningPath;config",
    '--add-data', "$webUiPath;gui/web_ui",
    (Join-Path $repoRoot 'main.py')
)

& $pythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$engineExecutable = Join-Path $engineDist 'ncfd-engine.exe'
if (-not (Test-Path -LiteralPath $engineExecutable)) {
    throw "PyInstaller output is missing: $engineExecutable"
}

$mediaPipeTests = Join-Path $engineDist '_internal\mediapipe\tasks\python\test'
if (Test-Path -LiteralPath $mediaPipeTests) {
    Remove-Item -LiteralPath $mediaPipeTests -Recurse -Force
}
Write-Host "Engine sidecar ready: $engineDist"

# Start the backend with the project-local Python 3.10 venv.

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Candidates = @(
    (Join-Path $ProjectRoot "venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe")
)

$PythonExe = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $PythonExe) {
    throw "No project Python found. Expected venv\Scripts\python.exe or .venv\Scripts\python.exe."
}

$Version = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($Version -ne "3.10") {
    throw "Project Python must be 3.10, got $Version at $PythonExe."
}

$env:VIRTUAL_ENV = Split-Path -Parent (Split-Path -Parent $PythonExe)
$env:PATH = "$(Split-Path -Parent $PythonExe);$env:PATH"
$env:PYTHONUTF8 = "1"

Write-Host "Starting backend with:" -ForegroundColor Green
Write-Host "  $PythonExe" -ForegroundColor Cyan
Write-Host ""

Set-Location $ProjectRoot
& $PythonExe -m app
exit $LASTEXITCODE

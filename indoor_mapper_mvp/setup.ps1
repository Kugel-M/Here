$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = $null
$bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (Test-Path -LiteralPath $bundledPython) { $taskPython = $bundledPython }
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $taskPython = & py -3.12 -c 'import sys; print(sys.executable)'
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $taskPython = & python -c 'import sys; print(sys.executable)'
}
if (-not $taskPython -or -not (Test-Path -LiteralPath $taskPython)) { throw 'Python 3.12 not found. Install Python 3.12 (64-bit) first.' }
& $taskPython -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 required"'
if ($LASTEXITCODE -ne 0) { throw 'Python version check failed' }
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    & $taskPython -m venv --without-pip .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
}
# The bundled runtime has pip but its ensurepip bootstrap is unavailable.
$taskRequirements = 'requirements.txt'
if (Test-Path -LiteralPath 'requirements-lock.txt') { $taskRequirements = 'requirements-lock.txt' }
& $taskPython -m pip --python '.venv/Scripts/python.exe' install pip -r $taskRequirements
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check internet connectivity.' }
& '.venv/Scripts/python.exe' app.py doctor
if ($LASTEXITCODE -ne 0) { throw 'Environment check failed' }
Write-Host 'Setup finished. Double-click the launch CMD file.'

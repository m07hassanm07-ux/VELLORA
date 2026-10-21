$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
}
$buildPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $buildPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $buildPython scripts\collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
& $buildPython scripts\run_checks.py
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& $buildPython -m PyInstaller WaraqPDF.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Write-Host 'Built dist\WaraqPDF\WaraqPDF.exe. Distribute the whole folder with its licenses.'

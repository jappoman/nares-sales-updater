param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt

if ($Clean) {
    if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
    if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
}

# GUI: per l'uso manuale con date custom (doppio clic sull'eseguibile)
& .\.venv\Scripts\pyinstaller.exe `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "NaresSalesUpdater" `
    --hidden-import pyodbc `
    --hidden-import openpyxl.cell._writer `
    launcher.py

# AUTO: per Task Scheduler (console, si lancia con --auto)
& .\.venv\Scripts\pyinstaller.exe `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name "NaresSalesUpdaterAuto" `
    --hidden-import pyodbc `
    --hidden-import openpyxl.cell._writer `
    main.py

$distGuiExe = Join-Path $root "dist\NaresSalesUpdater.exe"
$distAutoExe = Join-Path $root "dist\NaresSalesUpdaterAuto.exe"

Write-Host ""
Write-Host "Build completata."
Write-Host "GUI:  $distGuiExe"
Write-Host "AUTO: $distAutoExe"
Write-Host "Nota: config.json e .env NON vengono copiati nella build:"
Write-Host "      vanno copiati manualmente accanto agli eseguibili."

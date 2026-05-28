# Build a Windows .exe for Bingo Card Designer (PyInstaller).
# Run from repo root:  .\scripts\build_exe.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual env not found at $Python. Create it and run: pip install -r requirements.txt"
}

& $Python -m pip install -q pyinstaller
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name "Bingo Card Designer" `
    --add-data "icons;icons" `
    --collect-all customtkinter `
    --hidden-import skia `
    --exclude-module pandas `
    --exclude-module pyarrow `
    ui_desktop.py

Write-Host ""
Write-Host "Done. Executable:" -ForegroundColor Green
Write-Host "  $Root\dist\Bingo Card Designer\Bingo Card Designer.exe"

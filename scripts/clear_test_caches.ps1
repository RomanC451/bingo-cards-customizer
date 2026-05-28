# Clear pytest/Python caches (fixes stale PosixPath pickles from other OSes).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

foreach ($name in @(".pytest_cache", ".cache")) {
    $path = Join-Path $root $name
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
        Write-Host "Removed $path"
    }
}

Get-ChildItem -Path $root -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-Item -Recurse -Force $_.FullName
        Write-Host "Removed $($_.FullName)"
    }

Write-Host "Done. Re-run tests with: .\.venv\Scripts\python.exe -m pytest tests"

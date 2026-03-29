# Build YaqeenScan single-file executable (Windows, console build)
# Requires: Python 3.10+, pip install -r requirements-build.txt
# Output: dist\YaqeenScan_debug.exe
# NOTE: Console must be enabled (console=True in the spec) for the app
# to start correctly on this environment.

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "Installing PyInstaller..."
    pip install -r requirements-build.txt
}

Write-Host "Building YaqeenScan_debug.exe (onefile, console)..."
pyinstaller --noconfirm --clean YaqeenScan_debug.spec

if (Test-Path "dist\YaqeenScan_debug.exe") {
    Write-Host "Done. Executable: dist\YaqeenScan_debug.exe"
} else {
    Write-Host "Build failed. Check output above."
    exit 1
}

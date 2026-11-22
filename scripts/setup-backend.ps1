# Creates the Python environment for the processing engine and runs the test suite.
# Run from the repository root:  powershell -ExecutionPolicy Bypass -File scripts\setup-backend.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "FFmpeg is not on PATH. Install it first (see docs/SETUP-WINDOWS.md)." }
if (-not (Test-Path .venv)) { py -3.11 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip wheel
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

"`nHardware report:"
& .\.venv\Scripts\python.exe -m elixir_studio detect

"`nRunning tests (unit tests always; end-to-end tests need espeak-ng and are skipped otherwise):"
& .\.venv\Scripts\python.exe -m pytest -q

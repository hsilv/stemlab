# Start StemLab on Windows from the environment made by scripts/bootstrap.py (or uv sync).
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Missing .venv\Scripts\python.exe. See README.md to install the environment."
    exit 1
}

& $python -m stemlab.local

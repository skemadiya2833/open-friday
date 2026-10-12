# Quick start (Windows PowerShell) — developer checkout
$ErrorActionPreference = "Stop"
if (-not (Test-Path .\friday_env)) { python -m venv friday_env }
.\friday_env\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements\core.lock.txt
pip install -e .
if (-not (Test-Path .\.env)) { Copy-Item .\.env.example .\.env }
Write-Host "Starting Friday Control Center..."
python main.py --server

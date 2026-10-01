# Quick start (Windows PowerShell)
$ErrorActionPreference = "Stop"
if (-not (Test-Path .\friday_env)) { python -m venv friday_env }
.\friday_env\Scripts\Activate.ps1
pip install -r requirements.txt
if (-not (Test-Path .\.env)) { Copy-Item .\.env.example .\.env }
Write-Host "Starting Friday Control Center..."
python main.py --server

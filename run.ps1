# Start Artificer's Manual. First run: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt; python scripts\fetch_data.py
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) { Write-Host "No .venv yet - see README.md"; exit 1 }
if (-not (Test-Path "data\5etools\races.json")) { .\.venv\Scripts\python.exe scripts\fetch_data.py }
.\.venv\Scripts\python.exe -m app

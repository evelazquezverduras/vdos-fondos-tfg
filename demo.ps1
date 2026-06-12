# Demo rápida de VDOS Fondos (Windows PowerShell).
# Crea un entorno, instala dependencias, genera la BD de muestra y arranca la app.
# Uso:  click derecho -> "Ejecutar con PowerShell"   (o)   .\demo.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r requirements.txt

$env:EXTRACTED_JSON_PATH       = "$PSScriptRoot\data_muestra\pdfs_extracted.json"
$env:EXTRACTED_CODES_JSON_PATH = "$PSScriptRoot\data_muestra\pdfs_extracted_codes.json"
if (-not $env:OPENAI_API_KEY) { $env:OPENAI_API_KEY = "sk-demo" }   # las vistas con IA necesitan una clave real

& $py web\backend\scripts\build_db.py
Write-Host "`n>> App lista en  http://localhost:8000   (Ctrl+C para parar)`n" -ForegroundColor Green
& $py -m uvicorn app.main:app --app-dir web\backend --port 8000

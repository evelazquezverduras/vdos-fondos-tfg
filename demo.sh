#!/usr/bin/env bash
# Demo rápida de VDOS Fondos (macOS / Linux).
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
export EXTRACTED_JSON_PATH="$PWD/data_muestra/pdfs_extracted.json"
export EXTRACTED_CODES_JSON_PATH="$PWD/data_muestra/pdfs_extracted_codes.json"
: "${OPENAI_API_KEY:=sk-demo}"; export OPENAI_API_KEY
python web/backend/scripts/build_db.py
echo ">> App lista en http://localhost:8000 (Ctrl+C para parar)"
python -m uvicorn app.main:app --app-dir web/backend --port 8000

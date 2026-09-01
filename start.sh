#!/bin/bash
cd "$(dirname "$0")"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    source venv/bin/activate
    pip install -q -r requirements.txt
    playwright install chromium
else
    source venv/bin/activate
fi
uvicorn app:app --host 0.0.0.0 --port 5002 --reload

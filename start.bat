@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    python -m venv venv
    call venv\Scripts\activate
    pip install -q -r requirements.txt
    playwright install chromium
) else (
    call venv\Scripts\activate
)
uvicorn app:app --host 0.0.0.0 --port 5002 --reload

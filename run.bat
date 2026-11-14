@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PY=C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe"

if exist "%PY%" (
    echo Starting NovaCart Bot on http://localhost:8000 ...
    "%PY%" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
) else (
    echo Starting NovaCart Bot on http://localhost:8000 ...
    python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
)
pause

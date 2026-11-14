Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"
$py = "C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe"

Write-Host "🛒 Starting NovaCart Bot on http://localhost:8000 ..." -ForegroundColor Green
if (Test-Path $py) {
    & $py -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
} else {
    python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
}

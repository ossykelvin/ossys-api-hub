@echo off
setlocal
cd /d "%~dp0"

echo [Ossy's API Hub] Preparing frontend...
cd frontend
if not exist node_modules call npm install
if errorlevel 1 goto :error
call npm run build
if errorlevel 1 goto :error

echo [Ossy's API Hub] Preparing Python service...
cd ..\backend
if not exist .venv python -m venv .venv
if errorlevel 1 goto :error
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Ossy's API Hub is running at http://localhost:8000
echo Press Ctrl+C to stop.
start "" http://localhost:8000
call .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof

:error
echo.
echo Ossy's API Hub could not start. Review the error above.
pause
exit /b 1

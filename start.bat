@echo off
setlocal

REM ─── CFR Rates Regime Dashboard ─── Windows Launcher ───
REM Usage: start.bat [FRED_API_KEY]
REM   or set FRED_API_KEY environment variable before running

set PORT=8000
set SCRIPT_DIR=%~dp0

if not "%~1"=="" set FRED_API_KEY=%~1

echo.
echo   ╔══════════════════════════════════════════════╗
echo   ║   CFR RATES REGIME DASHBOARD v1.0            ║
echo   ╚══════════════════════════════════════════════╝
echo.

REM ─── Step 1: Check Python venv ───
if not exist "%SCRIPT_DIR%backend\venv\Scripts\python.exe" (
    echo   [1/3] Creating Python virtual environment...
    python -m venv "%SCRIPT_DIR%backend\venv"
    echo   [1/3] Installing Python dependencies...
    "%SCRIPT_DIR%backend\venv\Scripts\pip.exe" install -q -r "%SCRIPT_DIR%backend\requirements.txt"
) else (
    echo   [1/3] Python environment ready
)

REM ─── Step 2: Check frontend build ───
if exist "%SCRIPT_DIR%frontend\dist\index.html" (
    echo   [2/3] Frontend build ready
) else (
    echo   [2/3] Frontend not built. Run: cd frontend ^&^& npm install ^&^& npx vite build
)

REM ─── Step 3: Start server ───
echo   [3/3] Starting server on http://localhost:%PORT%
echo.

if defined FRED_API_KEY (
    echo   FRED API key: configured
) else (
    echo   FRED API key: not set ^(enter it in the app or pass as argument^)
)

echo.
echo   Open http://localhost:%PORT% in your browser
echo   Press Ctrl+C to stop
echo.

"%SCRIPT_DIR%backend\venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT% --log-level warning

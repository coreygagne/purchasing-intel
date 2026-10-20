@echo off
REM Start Purchasing Research on http://127.0.0.1:8000 (Windows). Requires Python 3.11+.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if "%HOST%"=="" set HOST=127.0.0.1
if "%PORT%"=="" set PORT=8000
echo Purchasing Research: http://%HOST%:%PORT%
uvicorn app.main:get_app --factory --host %HOST% --port %PORT%

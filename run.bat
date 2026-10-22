@echo off
setlocal
REM Purchasing Research for Windows: double-click this file. It sets itself up the first time, then opens
REM http://127.0.0.1:8000 in your browser. Keep the black window open while you use the app; close it to stop.
cd /d "%~dp0"
title Purchasing Research

REM 1. Find Python 3.11 or newer
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY goto :nopython

REM 1b. Updating: a newer "Download ZIP" in your Downloads folder is copied over this folder (after asking),
REM     keeping your keys, saved research and the .venv folder. Kept on one line: Windows reads a running
REM     batch file as it goes, so the restart must already be read before this file is replaced.
%PY% -I scripts\update_from_download.py "%~dp0." & if errorlevel 3 (start "Purchasing Research" "%~f0" & exit /b 0)

REM 2. First time only: a private Python environment for the app (in the .venv folder)
if not exist ".venv\Scripts\python.exe" (
  echo Setting up for the first time. This takes a minute or two...
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)
echo Checking the app's packages...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail

REM 3. Start the app; it opens the browser by itself when it is ready
if "%HOST%"=="" set "HOST=127.0.0.1"
if "%PORT%"=="" set "PORT=8000"
set "PI_OPEN_BROWSER=http://127.0.0.1:%PORT%"
echo.
echo Purchasing Research is running at http://127.0.0.1:%PORT%
echo Keep this window open while you use it. Close it to stop the app.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:get_app --factory --host %HOST% --port %PORT%
echo.
echo The app has stopped. If you didn't close it, read the messages above.
pause
exit /b 0

:nopython
echo Python 3.11 or newer is needed and was not found on this computer.
where winget >nul 2>&1
if errorlevel 1 goto :manualpython
echo Installing Python 3.12 now. Windows may ask for permission - choose Yes.
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
echo.
echo When the install has finished, close this window and double-click run.bat again.
pause
exit /b 1

:manualpython
echo Opening the Python download page. Run the installer and tick "Add python.exe to PATH",
echo then double-click run.bat again.
start "" https://www.python.org/downloads/
pause
exit /b 1

:fail
echo.
echo Setup didn't finish - see the messages above. Check the internet connection and try again.
pause
exit /b 1

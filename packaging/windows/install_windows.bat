@echo off
setlocal

cd /d %~dp0\..\..
echo ==============================================
echo Splice Streamlit App - Windows Installer
echo ==============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY_CMD=py -3"
) else (
  where python >nul 2>nul
  if not %errorlevel%==0 (
    echo Python 3.10+ was not found on this machine.
    echo Install Python from https://www.python.org/downloads/windows/
    echo and run this installer again.
    pause
    exit /b 1
  )
  set "PY_CMD=python"
)

if not exist ".venv" (
  echo Creating virtual environment...
  call %PY_CMD% -m venv .venv
  if errorlevel 1 goto :fail
)

echo Upgrading pip...
call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo Installing application dependencies...
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo Installation completed successfully.
echo Run packaging\windows\run_streamlit_local.bat to start the app.
echo.
pause
exit /b 0

:fail
echo.
echo Installation failed.
echo.
pause
exit /b 1

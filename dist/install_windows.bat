@echo off
setlocal

echo Installing Wiring Harness Splice Generator dependencies...

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not on PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Installation complete.
echo Next step: double-click run_app.bat
pause

endlocal

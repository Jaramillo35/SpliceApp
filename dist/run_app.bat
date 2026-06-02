@echo off
setlocal

echo Starting Wiring Harness Splice Generator...

if not exist .venv (
    echo ERROR: Python virtual environment not found.
    echo Please run install_windows.bat first.
    pause
    exit /b 1
)

call .venv\Scripts\activate
streamlit run app.py

endlocal

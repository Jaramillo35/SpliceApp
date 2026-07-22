@echo off
setlocal

cd /d %~dp0\..\..

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment was not found.
  echo Run packaging\windows\install_windows.bat first.
  pause
  exit /b 1
)

echo Starting Streamlit on local-only address 127.0.0.1...
echo Open this URL on the same machine: http://127.0.0.1:8501
echo Press Ctrl+C in this window to stop.
echo.

call .venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501

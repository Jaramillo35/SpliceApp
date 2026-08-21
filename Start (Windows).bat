@echo off
title System Engineer Toolkit
cd /d "%~dp0"
echo ============================================================
echo   Starting the System Engineer Toolkit
echo.
echo   The FIRST time, this takes a few minutes while it prepares
echo   everything. Later times are much faster.
echo.
echo   Keep THIS window open while you use the tool.
echo ============================================================
echo.
docker compose up --build -d
if errorlevel 1 (
  echo.
  echo -----------------------------------------------------------
  echo   Something went wrong.
  echo   Is Docker Desktop open? Look for the whale icon near the
  echo   clock. Open Docker Desktop, wait until it says "running",
  echo   then double-click this file again.
  echo -----------------------------------------------------------
  echo.
  pause
  exit /b 1
)
echo.
echo Getting the tool ready...
timeout /t 10 /nobreak >nul
start "" http://localhost:8501
echo.
echo The tool is running and should have opened in your web browser.
echo If it did not, open your browser and type this address:
echo.
echo        http://localhost:8501
echo.
echo When you are finished, double-click "Stop (Windows).bat".
echo You can leave this window open in the meantime.
echo.
pause

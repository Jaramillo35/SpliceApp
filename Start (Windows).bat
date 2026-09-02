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
call :stamp
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
start "" http://localhost:8504
echo.
echo The tool is running and should have opened in your web browser.
echo If it did not, open your browser and type this address:
echo.
echo        http://localhost:8504
echo.
echo The previous (Streamlit) version is still available at:
echo        http://localhost:8501
echo.
echo When you are finished, double-click "Stop (Windows).bat".
echo You can leave this window open in the meantime.
echo.
pause
exit /b 0

:stamp
rem Record what is being built, so the Admin page can say what is running.
for /f "delims=" %%i in ('git rev-parse HEAD 2^>nul') do set GIT_SHA=%%i
for /f "delims=" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set GIT_BRANCH=%%i
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')"') do set BUILD_DATE=%%i
exit /b 0

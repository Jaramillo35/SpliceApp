@echo off
title System Engineer Toolkit - Update
cd /d "%~dp0"
echo ============================================================
echo   Updating the System Engineer Toolkit
echo.
echo   This gets the latest version and restarts the tool.
echo   Takes a minute or two. Data is kept.
echo ============================================================
echo.
git pull
if errorlevel 1 (
  echo.
  echo   Could not download the update. Is this folder a git clone,
  echo   and is the network/VPN up?
  pause
  exit /b 1
)
docker compose up --build -d
if errorlevel 1 (
  echo.
  echo   Docker could not rebuild. Is Docker Desktop running?
  pause
  exit /b 1
)
echo.
echo Update done. The tool is running the latest version at:
echo        http://localhost:8501
echo.
pause

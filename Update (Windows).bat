@echo off
title System Engineer Toolkit - Update
cd /d "%~dp0"
echo ============================================================
echo   Updating the System Engineer Toolkit
echo.
echo   This gets the latest release and restarts the tool.
echo   Takes a minute or two. Data is kept.
echo ============================================================
echo.
rem Always update from the release branch, whatever branch this clone
rem happens to be on. A bare "git pull" used to fetch whatever was checked
rem out - which on a fresh clone was a branch months behind the work.
git fetch origin main
if errorlevel 1 (
  echo.
  echo   Could not download the update. Is this folder a git clone,
  echo   and is the network/VPN up?
  pause
  exit /b 1
)
git checkout -q main
git reset -q --hard origin/main
if errorlevel 1 (
  echo.
  echo   Could not switch to the latest release. Ask for help and
  echo   mention the message above.
  pause
  exit /b 1
)
for /f "delims=" %%i in ('git rev-parse --short HEAD') do echo   Now at version %%i
echo.
for /f "delims=" %%i in ('git rev-parse HEAD 2^>nul') do set GIT_SHA=%%i
for /f "delims=" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set GIT_BRANCH=%%i
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')"') do set BUILD_DATE=%%i
docker compose up --build -d
if errorlevel 1 (
  echo.
  echo   Docker could not rebuild. Is Docker Desktop running?
  pause
  exit /b 1
)
echo.
echo Update done. The tool is running the latest version at:
echo        http://localhost:8504
echo.
echo Open the Admin page inside the tool to see exactly what changed.
echo.
pause

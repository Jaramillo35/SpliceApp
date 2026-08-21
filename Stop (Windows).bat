@echo off
title DTx Compare Tool - Stopping
cd /d "%~dp0"
echo Stopping the DTx Compare Tool...
docker compose down
echo.
echo Done. The tool has been shut down. You can close this window.
echo.
pause

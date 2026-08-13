@echo off
setlocal

cd /d %~dp0

if not exist "SpliceApp.exe" (
  echo SpliceApp.exe was not found in this folder.
  pause
  exit /b 1
)

set "SPLICE_HOST=127.0.0.1"
set "SPLICE_PORT=8501"
for /f %%P in ('powershell -NoProfile -Command "$used = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners().Port; $port = 8501; while ($used -contains $port) { $port++ }; $port"') do set "SPLICE_PORT=%%P"

echo Starting SpliceApp on local-only address %SPLICE_HOST%...
echo URL: http://%SPLICE_HOST%:%SPLICE_PORT%
if defined LOCALAPPDATA (
  echo User data: %LOCALAPPDATA%\SpliceApp
) else (
  echo User data: %USERPROFILE%\AppData\Local\SpliceApp
)
echo.

call SpliceApp.exe

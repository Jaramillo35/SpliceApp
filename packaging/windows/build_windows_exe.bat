@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"

set "REQ_FILE=%SCRIPT_DIR%requirements.txt"
if not exist "%REQ_FILE%" set "REQ_FILE=%PROJECT_ROOT%\requirements.txt"

if not exist "%REQ_FILE%" (
  echo Could not find requirements.txt. Checked:
  echo   %SCRIPT_DIR%requirements.txt
  echo   %PROJECT_ROOT%\requirements.txt
  echo.
  echo Put requirements.txt in packaging\windows\ or project root.
  pause
  exit /b 1
)

if not exist "%PROJECT_ROOT%\packaging\windows\SpliceApp.spec" (
  echo Could not find PyInstaller spec file at:
  echo   %PROJECT_ROOT%\packaging\windows\SpliceApp.spec
  pause
  exit /b 1
)

cd /d "%PROJECT_ROOT%"

echo ==============================================
echo Building SpliceApp Windows Executable
echo ==============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  py -3.12 -c "import sys" >nul 2>nul
  if !errorlevel!==0 (
    set "PY_CMD=py -3.12"
  ) else (
    py -3.11 -c "import sys" >nul 2>nul
    if !errorlevel!==0 set "PY_CMD=py -3.11"
  )
) else (
  where python >nul 2>nul
  if %errorlevel%==0 set "PY_CMD=python"
)

if not defined PY_CMD (
  echo Python 3.11 or 3.12 was not found on this machine.
  echo Install a 64-bit Python from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

call %PY_CMD% -c "import struct, sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 12) and struct.calcsize('P') * 8 == 64 else 1)"
if errorlevel 1 (
  echo SpliceApp builds require 64-bit Python 3.11 or 3.12.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Creating virtual environment...
  call %PY_CMD% -m venv .venv
  if errorlevel 1 goto :fail
)

echo Installing/updating build dependencies...
call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :fail
call .venv\Scripts\python.exe -m pip install -r "%REQ_FILE%"
if errorlevel 1 goto :fail
call .venv\Scripts\python.exe -m pip install pyinstaller==6.10.0
if errorlevel 1 goto :fail
call .venv\Scripts\python.exe -m pip check
if errorlevel 1 goto :fail

echo Validating production source...
call .venv\Scripts\python.exe scripts\validate_production.py
if errorlevel 1 goto :fail

echo Cleaning previous build outputs...
if exist build rmdir /s /q build
if exist dist\SpliceApp rmdir /s /q dist\SpliceApp

echo Running PyInstaller...
call .venv\Scripts\pyinstaller.exe --noconfirm --clean packaging\windows\SpliceApp.spec
if errorlevel 1 goto :fail

set "EXE_DIR=dist\SpliceApp"
set "EXE_PATH=%EXE_DIR%\SpliceApp.exe"
if not exist "%EXE_PATH%" (
  echo Build completed but executable was not found at %EXE_PATH%
  goto :fail
)

echo Running frozen executable self-test...
call "%EXE_PATH%" --self-test
if errorlevel 1 goto :fail

echo Copying run helper...
if exist packaging\windows\run_exe_local.bat (
  copy /Y packaging\windows\run_exe_local.bat "%EXE_DIR%\START_SPLICEAPP.bat" >nul
)
if exist packaging\windows\README_FOR_USERS.txt (
  copy /Y packaging\windows\README_FOR_USERS.txt "%EXE_DIR%\README.txt" >nul
)

echo Creating distributable zip...
if not exist dist\windows mkdir dist\windows
powershell -NoProfile -Command "if (Test-Path 'dist/windows/SpliceApp-Executable.zip') { Remove-Item 'dist/windows/SpliceApp-Executable.zip' -Force }; Compress-Archive -Path 'dist/SpliceApp/*' -DestinationPath 'dist/windows/SpliceApp-Executable.zip'"
if errorlevel 1 goto :fail
powershell -NoProfile -Command "$hash = (Get-FileHash 'dist/windows/SpliceApp-Executable.zip' -Algorithm SHA256).Hash.ToLower(); Set-Content -Path 'dist/windows/SpliceApp-Executable.zip.sha256' -Value ($hash + '  SpliceApp-Executable.zip')"
if errorlevel 1 goto :fail
powershell -NoProfile -Command "$folder = (Get-ChildItem 'dist/SpliceApp' -File -Recurse | Measure-Object Length -Sum).Sum; $zip = (Get-Item 'dist/windows/SpliceApp-Executable.zip').Length; Write-Host ('Uncompressed package: {0:N1} MB' -f ($folder / 1MB)); Write-Host ('Distribution ZIP:    {0:N1} MB' -f ($zip / 1MB))"

echo.
echo Build successful.
echo Executable folder: %CD%\dist\SpliceApp
echo Zip package:       %CD%\dist\windows\SpliceApp-Executable.zip
echo SHA-256 file:      %CD%\dist\windows\SpliceApp-Executable.zip.sha256
echo.
pause
exit /b 0

:fail
echo.
echo Build failed.
echo.
pause
exit /b 1

# Windows Executable Build Guide

## 1. Prerequisites

- Windows 10/11
- 64-bit Python 3.11 or 3.12 installed from python.org
- Internet access during the build so pip can install dependencies

## 2. Extract The Build Kit

1. Extract `SpliceApp-Windows.zip` to a local folder.
2. Open the extracted `SpliceApp-Windows` folder.
3. Confirm these items exist at the top level: `app.py`, `feedback_system.py`, `requirements.txt`, `pages`, `ui`, `splice`, `vbom_legacy`, `assets`, `scripts`, and `packaging`. There is deliberately no `data` folder — the SECR database is created empty at first run.

## 3. Build The Executable

1. Open the extracted project folder.
2. Double-click `packaging/windows/build_windows_exe.bat`.
3. Wait for PyInstaller to finish.

Build outputs:

- Executable folder: `dist/SpliceApp/`
- Team zip package: `dist/windows/SpliceApp-Executable.zip`
- SHA-256 checksum: `dist/windows/SpliceApp-Executable.zip.sha256`

## 4. Install The Built App On Another Windows PC

1. Copy `dist/windows/SpliceApp-Executable.zip` to the target Windows PC.
2. Extract the zip to a local folder such as `C:\SpliceApp`.
3. Open the extracted folder.

No Python install is required on the target PC after the executable package is built.

## 5. Run The Built App (Local Only)

1. Double-click `START_SPLICEAPP.bat`.
2. Wait for the console window to show the local URL.
3. Open `http://127.0.0.1:8501` in a browser on the same PC.

The app binds to `127.0.0.1`, so it is available only on that computer.
Mutable data is stored per user under `%LOCALAPPDATA%\SpliceApp`, outside the
executable folder. Back up that folder to preserve feedback and the SECR database.

## 6. The SECR Database

The build ships **without** a database. `secr_database.db` is created empty the
first time the SECR Database page is opened, under `%LOCALAPPDATA%\SpliceApp`,
and is populated on the machine that runs the app:

- **Import SECR files** — drag in existing SECR workbooks. Duplicates are
  skipped rather than overwritten, and every file is reported.
- **Create SECR / Update SECR** — generated SECRs are saved automatically with
  their change records and a copy of the workbook.

Verify the packaged database wiring at any time:

```bat
dist\SpliceApp\SpliceApp.exe --self-test
```

The self-test creates a throwaway database, checks the schema version and
tables, confirms SECR numbering starts at 1000, and prints where the real
database will live — without creating or modifying it.

Because the database lives outside the executable folder, replacing the app
folder with a new build keeps the existing SECR history. To reset a machine
back to empty, close the app and delete `%LOCALAPPDATA%\SpliceApp\secr_database.db`.

## 7. Stop The App

Press `Ctrl+C` in the console window running the executable.

## 8. Notes

- Build the executable from the extracted build-kit root, not from inside `packaging/windows` alone.
- Distribute the entire executable ZIP, not `SpliceApp.exe` by itself.
- Recipients can verify the ZIP against the supplied `.sha256` file before extraction.
- If Windows Defender prompts during first launch, allow the app to run if your team trusts the package source.

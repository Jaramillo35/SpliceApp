SpliceApp - Windows Quick Start
================================

1. Extract the complete SpliceApp-Executable.zip into its own local folder.
   Do not run the application from inside the ZIP.

2. Double-click START_SPLICEAPP.bat.

3. Open the URL printed in the console. It normally uses
   http://127.0.0.1:8501 and automatically selects another local port if 8501
   is already in use.

4. Keep this console window open while using SpliceApp. Press Ctrl+C in the
   console window to stop it.

The SECR Database
-----------------
SpliceApp ships with an EMPTY SECR database. It is created the first time you
open the SECR Database page, and everything you add stays on this computer.

To fill it:
- "Import SECR files" tab: drag in your existing SECR workbooks. Files already
  in the database are skipped, not overwritten, and every file is reported as
  imported / already existed / failed.
- "Create SECR" tab: build a new SECR from a DEF-to-DEF compare. It is saved to
  the database automatically, with its change records.

The database file is:
  %LOCALAPPDATA%\SpliceApp\secr_database.db

Back it up by copying that file while the app is closed. To move your history
to another PC, copy the same file into that PC's %LOCALAPPDATA%\SpliceApp
folder before starting the app.

Important:
- Keep SpliceApp.exe and the _internal folder together.
- Do not distribute or move SpliceApp.exe by itself.
- User feedback and the SECR database are stored under:
  %LOCALAPPDATA%\SpliceApp
  Upgrading SpliceApp does not touch that folder, so your SECR history and
  feedback survive a new version.
- The application is local-only and is not exposed to other computers.

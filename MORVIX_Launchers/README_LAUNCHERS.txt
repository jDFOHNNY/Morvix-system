MORVIX Windows launchers
========================

These .bat files find the project root relative to their own folder, so the project can be moved without editing paths.

INSTALL
-------
1. Keep the launcher files inside `MORVIX_Launchers` in the project root.
2. Double-click `Start_MORVIX.bat` to launch the dashboard.

START_MORVIX.BAT
----------------
- Uses the project venv Python directly; it does not require PowerShell script activation.
- If http://127.0.0.1:8000/ already responds, it opens that page instead of starting a duplicate server.
- If port 8000 is occupied but the dashboard URL does not respond, it reports the conflict rather than killing a process.
- If the backend is not running and the port is free, it opens a separate console to run:
  .venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
- Keep the separate backend console open while using MORVIX.

START_MORVIX_TEST_PAGE.BAT (OPTIONAL)
-------------------------------------
- Starts a small local HTTP server on port 8001 for the controlled extension test page.
- Requires data\controlled_extension_test\threat-only.html to exist.
- If the page is already being served, it reuses it instead of starting another copy.
- Keep its separate console open while testing. Close that server with Ctrl+C in its console when finished.
- This test server is not required to open the normal MORVIX dashboard.

DASHBOARD URL
-------------
http://127.0.0.1:8000/

TEST PAGE URL (only while optional test server is running)
----------------------------------------------------------
http://localhost:8001/threat-only.html

NOTES
-----
- These launchers do not recreate .venv, reinstall packages, delete databases, or modify project files.
- If your project folder moves, keep `MORVIX_Launchers` inside it; the launchers locate the root automatically.
- If a server crashes, inspect the separate console window for the real error.

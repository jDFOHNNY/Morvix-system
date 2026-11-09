@echo off
setlocal

rem Optional launcher for the controlled extension test page only.
for %%I in ("%~dp0..") do set "PROJECT_DIR=%%~fI"
set "PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "TEST_DIR=%PROJECT_DIR%\data\controlled_extension_test"
set "TEST_URL=http://localhost:8001/threat-only.html"

if not exist "%PYTHON%" (
    echo ERROR: The project's virtual-environment Python was not found:
    echo   %PYTHON%
    pause
    exit /b 1
)

if not exist "%TEST_DIR%\threat-only.html" (
    echo ERROR: The controlled test page was not found:
    echo   %TEST_DIR%\threat-only.html
    echo Check that threat-only.html exists in the controlled_extension_test folder.
    pause
    exit /b 1
)

rem Reuse an existing test server if the exact page responds.
powershell.exe -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:8001/threat-only.html' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
    echo The controlled test page is already available.
    start "" "%TEST_URL%"
    exit /b 0
)

rem Don't silently launch a duplicate server or collide with another process.
powershell.exe -NoProfile -Command "$x = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue; if ($x) { exit 0 } else { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
    echo ERROR: Port 8001 is occupied, but the controlled test page did not respond.
    echo Check the existing process before starting another test server.
    pause
    exit /b 1
)

echo Starting the optional controlled test-page server...
start "MORVIX Test Page - keep this window open" /D "%PROJECT_DIR%" "%PYTHON%" -m http.server 8001 --bind localhost --directory "%TEST_DIR%"

powershell.exe -NoProfile -Command "$ok = $false; for ($i = 0; $i -lt 15; $i++) { try { $r = Invoke-WebRequest -Uri 'http://localhost:8001/threat-only.html' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { $ok = $true; break } } catch {}; Start-Sleep -Seconds 1 }; if ($ok) { exit 0 } else { exit 1 }" >nul 2>&1
if not %errorlevel%==0 (
    echo.
    echo ERROR: The test page did not respond. Check the separate test-page console.
    pause
    exit /b 1
)

echo Test page is ready. Opening it now...
start "" "%TEST_URL%"
exit /b 0

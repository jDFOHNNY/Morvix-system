@echo off
setlocal

rem MORVIX launcher for the current Windows project layout.
for %%I in ("%~dp0..") do set "PROJECT_DIR=%%~fI"
set "PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "DASHBOARD_URL=http://127.0.0.1:8000/"

if not exist "%PYTHON%" (
    echo ERROR: The project's virtual-environment Python was not found:
    echo   %PYTHON%
    echo.
    echo Open the project folder and follow README.md to repair or create .venv.
    pause
    exit /b 1
)

rem If MORVIX already responds, reuse it instead of creating a duplicate server.
powershell.exe -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
    echo MORVIX is already responding on port 8000.
    start "" "%DASHBOARD_URL%"
    exit /b 0
)

rem If a different process occupies port 8000, avoid starting another server.
powershell.exe -NoProfile -Command "$x = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; if ($x) { exit 0 } else { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
    echo ERROR: Port 8000 is occupied, but the MORVIX dashboard did not respond.
    echo Check which process is using port 8000 before starting another server.
    echo You can inspect it with:
    echo   Get-NetTCPConnection -LocalPort 8000 -State Listen ^| Select-Object LocalAddress,LocalPort,OwningProcess
    pause
    exit /b 1
)

echo Starting MORVIX backend in a separate console window...
start "MORVIX Backend - keep this window open" /D "%PROJECT_DIR%" "%PYTHON%" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

echo Waiting for the dashboard to respond...
powershell.exe -NoProfile -Command "$ok = $false; for ($i = 0; $i -lt 30; $i++) { try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { $ok = $true; break } } catch {}; Start-Sleep -Seconds 1 }; if ($ok) { exit 0 } else { exit 1 }" >nul 2>&1
if not %errorlevel%==0 (
    echo.
    echo ERROR: MORVIX did not respond within 30 seconds.
    echo Check the separate MORVIX Backend console window for the actual error.
    pause
    exit /b 1
)

echo MORVIX is ready. Opening the dashboard...
start "" "%DASHBOARD_URL%"
exit /b 0

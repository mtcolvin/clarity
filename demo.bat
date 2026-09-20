@echo off
REM ============================================================================
REM  demo.bat - launch the app against an INVENTED record, for showing it to
REM             someone without putting a real medical history on the screen.
REM
REM  Demo mode is a different STORE, not a different view. This script points
REM  every data source at demo_store\ and starts the app there, so the real
REM  record is not hidden from the running process - it is unreachable by it:
REM
REM    HEALTH_DB               -> demo_store\demo.db
REM    HEALTH_IMAGING_DIR      -> demo_store\imaging
REM    HEALTH_IMAGING_ARCHIVE  -> demo_store\archive
REM    HEALTH_DOCUMENTS_DIR    -> demo_store\documents
REM    GATEWAY_AUDIT_LOG       -> demo_store\gateway_audit.log
REM
REM  That last one is easy to miss and was: it is not a "store", it is a log file at the
REM  repo root, and it holds the VERBATIM payload of every external send - real readings,
REM  and on a full-picture send the report prose and condition notes too. Settings reads it
REM  back under "External sends". Left unset, a demo window shows the real send history
REM  under a badge saying the record is invented.
REM
REM  A masking toggle in the UI was considered and rejected: it leaves the real
REM  data inside the process (one unmasked route and you are demonstrating the
REM  thing you meant to hide), and it cannot work at all for a DICOM slice with
REM  a name burned into its pixels or for a radiologist's prose. See synthetic.py.
REM
REM  Different PORTS from start.bat (8001 / 5174), so a demo can run beside your
REM  real instance without either one taking the other's socket - and so the URL
REM  in the address bar is itself a reminder of which one you are looking at.
REM
REM  The store is created on first run and reused after that; delete the
REM  demo_store\ folder to start it over. It is gitignored, like every other
REM  store here.
REM ============================================================================
setlocal enabledelayedexpansion

set "API_PORT=8001"
set "WEB_PORT=5174"

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
  echo [ERROR] Python venv not found at "%~dp0.venv".
  echo         Create it and install requirements first ^(see CLAUDE.md^), then re-run.
  echo.
  pause
  exit /b 1
)

set "HEALTH_DB=%~dp0demo_store\demo.db"
set "HEALTH_IMAGING_DIR=%~dp0demo_store\imaging"
set "HEALTH_IMAGING_ARCHIVE=%~dp0demo_store\archive"
set "HEALTH_DOCUMENTS_DIR=%~dp0demo_store\documents"
set "GATEWAY_AUDIT_LOG=%~dp0demo_store\gateway_audit.log"
REM CORS is scoped to the real dev origin; the demo frontend runs elsewhere.
set "HEALTH_DEV_ORIGINS=http://localhost:%WEB_PORT%,http://127.0.0.1:%WEB_PORT%"

echo [seed ] Building demo_store\ if it isn't there yet...
call .venv\Scripts\activate.bat && python -m demo_store_setup
if errorlevel 1 (
  echo [ERROR] Could not build the demo store - see the message above.
  echo.
  pause
  exit /b 1
)

set "START_API=1"
set "START_WEB=1"
netstat -ano | findstr "LISTENING" | findstr /C:":%API_PORT% " >nul && set "START_API=0"
netstat -ano | findstr "LISTENING" | findstr /C:":%WEB_PORT% " >nul && set "START_WEB=0"

if "!START_API!"=="0" (
  echo [skip ] Demo backend already running on port %API_PORT%.
) else (
  echo [start] Demo backend  ^(uvicorn :%API_PORT%^) ...
  start "Clarity DEMO API" cmd /k "call .venv\Scripts\activate.bat && python -m uvicorn api:app --host 127.0.0.1 --port %API_PORT%"
)

if "!START_WEB!"=="0" (
  echo [skip ] Demo frontend already running on port %WEB_PORT%.
) else (
  echo [start] Demo frontend ^(npm run dev :%WEB_PORT%^) ...
  REM --mode demo loads frontend\.env.demo, which points the app at THIS backend. It used
  REM to set VITE_API_BASE inline here, and `set VAR=value && cmd` in a batch file stores a
  REM TRAILING SPACE - every request went to "http://127.0.0.1:8001 /metrics" and nothing
  REM loaded. A committed env file has no quoting to get wrong.
  start "Clarity DEMO Frontend" cmd /k "cd frontend && npm run dev -- --mode demo --port %WEB_PORT% --strictPort"
)

echo.
echo Waiting for the demo servers...
set /a TRIES=0
:waitloop
set "API_UP=0"
set "WEB_UP=0"
netstat -ano | findstr "LISTENING" | findstr /C:":%API_PORT% " >nul && set "API_UP=1"
netstat -ano | findstr "LISTENING" | findstr /C:":%WEB_PORT% " >nul && set "WEB_UP=1"
if "!API_UP!"=="1" if "!WEB_UP!"=="1" goto ready
set /a TRIES+=1
if !TRIES! GEQ 40 goto timedout
timeout /t 1 /nobreak >nul
goto waitloop

:ready
echo Demo is up. Opening http://localhost:%WEB_PORT% ...
start "" "http://localhost:%WEB_PORT%"
goto done

:timedout
echo [WARN ] Timed out (API listening=!API_UP!, Frontend listening=!WEB_UP!).
echo         Check the "Clarity DEMO ..." window^(s^) for errors.
start "" "http://localhost:%WEB_PORT%"

:done
echo.
echo Every page carries a "DEMO DATA" badge in the header while this store is open.
echo Close the two DEMO windows when you're finished.
timeout /t 5 /nobreak >nul
endlocal

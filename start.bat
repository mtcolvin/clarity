@echo off
REM ============================================================================
REM  start.bat - one-click launcher for the Clarity (Windows).
REM
REM  Double-click this to:
REM    1. Start the backend  (venv -> uvicorn on :8000) in its own titled window
REM    2. Start the frontend (npm run dev on :5173)      in its own titled window
REM    3. Wait until BOTH ports are actually listening (not just launched)
REM    4. Open your default browser to http://localhost:5173
REM
REM  Notes:
REM   - If a server is already running on its port, it is left alone (no
REM     duplicate process) and the script just waits/opens the browser.
REM   - The two server windows are titled "Clarity API" / "Clarity
REM     Frontend" so you can find and close them when you're done. This script
REM     only STARTS them; closing one window does not stop the other.
REM   - Works from anywhere: all paths resolve from this script's own location
REM     (%~dp0), and the server commands are unchanged (uvicorn without --reload,
REM     plain npm run dev).
REM ============================================================================
setlocal enabledelayedexpansion

set "API_PORT=8000"
set "WEB_PORT=5173"

REM Resolve to the project root (this script's folder) once, with quotes so a
REM path containing spaces is handled; child windows inherit this directory.
cd /d "%~dp0"

REM --- sanity: is the Python venv present? ---
if not exist ".venv\Scripts\activate.bat" (
  echo [ERROR] Python venv not found at "%~dp0.venv".
  echo         Create it and install requirements first ^(see CLAUDE.md^), then re-run.
  echo.
  pause
  exit /b 1
)

REM --- decide what needs starting (don't duplicate a running server) ---
set "START_API=1"
set "START_WEB=1"
netstat -ano | findstr "LISTENING" | findstr /C:":%API_PORT% " >nul && set "START_API=0"
netstat -ano | findstr "LISTENING" | findstr /C:":%WEB_PORT% " >nul && set "START_WEB=0"

if "!START_API!"=="0" (
  echo [skip ] Backend  already running on port %API_PORT% - leaving it as is.
) else (
  echo [start] Backend  ^(uvicorn :%API_PORT%^) ...
  start "Clarity API" cmd /k "call .venv\Scripts\activate.bat && python -m uvicorn api:app --host 127.0.0.1 --port %API_PORT%"
)

if "!START_WEB!"=="0" (
  echo [skip ] Frontend already running on port %WEB_PORT% - leaving it as is.
) else (
  echo [start] Frontend ^(npm run dev :%WEB_PORT%^) ...
  start "Clarity Frontend" cmd /k "cd frontend && npm run dev"
)

REM --- wait until both ports are actually listening (max ~40s) ---
echo.
echo Waiting for servers to be ready...
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
echo Both servers are up. Opening http://localhost:%WEB_PORT% ...
start "" "http://localhost:%WEB_PORT%"
goto done

:timedout
echo [WARN ] Timed out waiting (API listening=!API_UP!, Frontend listening=!WEB_UP!).
echo         Check the "Clarity API/Frontend" window^(s^) for errors.
echo         Opening the browser anyway...
start "" "http://localhost:%WEB_PORT%"

:done
echo.
echo Launcher done. The two server windows stay open - close them when finished.
timeout /t 5 /nobreak >nul
endlocal

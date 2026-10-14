@echo off
setlocal
cd /d "%~dp0"

echo.
echo  ============================================================
echo    TAKT  -  1-click setup
echo    Local, private, push-to-talk dictation for Windows
echo  ============================================================
echo.

:: ---- 1. Python 3.10+ ------------------------------------------------------
set "PY="
where py >nul 2>&1 && (py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1 && set "PY=py -3")
if not defined PY (
    where python >nul 2>&1 && (python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1 && set "PY=python")
)
if not defined PY (
    echo  [X] Python 3.10 or newer was not found.
    echo      Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^)
    echo      and run setup.bat again.
    echo.
    pause
    exit /b 1
)
echo  [1/4] Python found: %PY%

:: ---- 2. Virtual environment ----------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo  [2/4] Creating virtual environment in .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo  [X] Could not create the virtual environment.
        pause
        exit /b 1
    )
) else (
    echo  [2/4] Virtual environment already exists.
)

:: ---- 3. Dependencies ------------------------------------------------------
echo  [3/4] Installing Python dependencies ^(this can take a few minutes the first time^) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo  [X] Dependency installation failed. Check your internet connection and retry.
    pause
    exit /b 1
)

:: ---- 4. Models, Node deps, config, audio check ----------------------------
echo  [4/4] Preparing models and speech engine ...
".venv\Scripts\python.exe" scripts\bootstrap.py
if errorlevel 1 (
    echo  [X] Bootstrap failed. See the messages above.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo    Setup complete!
echo.
echo    Hold RIGHT ALT to talk, release to type the text anywhere.
echo    Takt lives in your system tray; click its icon for Settings.
echo.
echo    Start Takt later with run_takt.bat
echo    Run a full self-check with:  .venv\Scripts\python scripts\verify_system.py
echo  ============================================================
echo.
choice /c YN /n /m "  Launch Takt now? [Y/N] "
if errorlevel 2 goto :done
call "%~dp0run_takt.bat"

:done
endlocal
exit /b 0

@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0;%PYTHONPATH%

:: Prefer the project's virtual environment (created by setup.bat); fall back to system Python
set "PYW=pythonw"
if exist ".venv\Scripts\python.exe" (
    set "PYW=.venv\Scripts\pythonw.exe"
)

:: Ensure Ollama background service is active if installed
curl.exe -s http://127.0.0.1:11434/ >nul 2>&1
if %ERRORLEVEL% neq 0 (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        powershell -WindowStyle Hidden -Command "Start-Process '%LOCALAPPDATA%\Programs\Ollama\ollama.exe' -ArgumentList 'serve' -WindowStyle Hidden"
    )
)

if not exist "src\engine\voz_node\node_modules" (
    echo Takt has not been set up yet. Run setup.bat first.
    pause
    exit /b 1
)
:: Launch Takt completely headless using pythonw (NO terminal window)
start "" "%PYW%" -O src/main.py
exit /b 0

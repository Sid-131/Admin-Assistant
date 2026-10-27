@echo off
setlocal
SET ROOT=%~dp0
SET OLLAMA_MODELS=%ROOT%ollama\models
SET OLLAMA_HOST=127.0.0.1:11434

echo.
echo  ==========================================
echo   PowerScale AI Assistant - Starting...
echo  ==========================================
echo.

REM ── Locate Ollama: prefer the copy bundled in this folder, else the
REM    one installed on this machine. ─────────────────────────────────
SET OLLAMA_EXE=%ROOT%ollama\ollama.exe
if not exist "%OLLAMA_EXE%" SET OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe
if not exist "%OLLAMA_EXE%" (
    echo  [ERROR] Ollama not found.
    echo          Install it from https://ollama.com/download
    echo          or place ollama.exe in: %ROOT%ollama\
    pause
    exit /b 1
)

REM ── Check the venv exists ─────────────────────────────────────────
if not exist "%ROOT%venv\Scripts\python.exe" (
    echo  [ERROR] Python environment missing. Run SETUP.bat first.
    pause
    exit /b 1
)

REM Stop any Ollama already running on a DIFFERENT models path (e.g. the
REM desktop app pointed at a OneDrive copy whose files may be cloud-only)
REM so our server, using the bundled %OLLAMA_MODELS%, owns port 11434.
taskkill /F /IM "ollama app.exe" /T >nul 2>&1
taskkill /F /IM ollama.exe /T >nul 2>&1
timeout /t 2 /nobreak > nul

echo  [1/2] Starting Ollama (models: %OLLAMA_MODELS%)...
start /B "" "%OLLAMA_EXE%" serve
timeout /t 5 /nobreak > nul

REM Open the browser to the app
start "" http://localhost:8501

REM ── Start the web app. Call python.exe directly (never "activate") so
REM    the venv keeps working even if this folder is moved or copied. ──
echo  [2/2] Starting PowerScale WebUI...
echo.
echo  --^> Open http://localhost:8501 in your browser
echo  --^> Press Ctrl+C in this window to stop
echo.
"%ROOT%venv\Scripts\python.exe" "%ROOT%web\server_local.py"

endlocal

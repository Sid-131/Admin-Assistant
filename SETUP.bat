@echo off
setlocal
SET ROOT=%~dp0

echo.
echo  ==========================================
echo   PowerScale AI Assistant - One-time Setup
echo  ==========================================
echo.
echo  This runs ONCE on your machine to prepare the demo.
echo  Steps: create venv, install packages, ingest docs.
echo.

REM ── 1. Check Python ──────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.11 from python.org
    pause
    exit /b 1
)
echo  [OK] Python found
for /f "tokens=*" %%i in ('python --version') do echo       %%i

REM ── 2. Create venv ───────────────────────────────────────────────────────
if exist "%ROOT%venv\Scripts\python.exe" (
    echo  [SKIP] venv already exists
) else (
    echo  [2/4] Creating virtual environment...
    python -m venv "%ROOT%venv"
    if errorlevel 1 ( echo  [ERROR] Failed to create venv & pause & exit /b 1 )
    echo  [OK] venv created
)

REM ── 3. Install packages ──────────────────────────────────────────────────
echo  [3/4] Installing packages (this takes 2-3 minutes)...
"%ROOT%venv\Scripts\pip.exe" install --quiet -r "%ROOT%requirements.txt"
if errorlevel 1 ( echo  [ERROR] pip install failed & pause & exit /b 1 )
echo  [OK] Packages installed

REM ── 4. Check Ollama + models ─────────────────────────────────────────────
echo  [4/4] Checking Ollama models...
SET OLLAMA_EXE=%ROOT%ollama\ollama.exe
if not exist "%OLLAMA_EXE%" SET OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe
if not exist "%OLLAMA_EXE%" (
    echo.
    echo  [ACTION NEEDED] Ollama not found.
    echo  Install it from https://ollama.com/download (recommended),
    echo  or place ollama.exe in: %ROOT%ollama\
    echo  Then re-run this script.
    echo.
    pause
    exit /b 1
)

SET OLLAMA_MODELS=%ROOT%ollama\models
start /B "" "%OLLAMA_EXE%" serve
timeout /t 4 /nobreak > nul

echo  Pulling llama3.1:8b model (5GB - takes a while on first run)...
"%OLLAMA_EXE%" pull llama3.1:8b

echo  Pulling nomic-embed-text model...
"%OLLAMA_EXE%" pull nomic-embed-text

REM ── 5. Ingest documents ───────────────────────────────────────────────────
if not exist "%ROOT%docs\*.pdf" (
    echo.
    echo  [ACTION NEEDED] No PDFs found in docs\ folder.
    echo  Run download_docs.ps1 first, then re-run this script.
    echo.
    pause
    exit /b 1
)

echo.
echo  Ingesting documentation into vector database...
"%ROOT%venv\Scripts\python.exe" "%ROOT%ingest.py"

echo.
echo  ==========================================
echo   Setup complete! Run START.bat to launch.
echo  ==========================================
echo.
pause
endlocal

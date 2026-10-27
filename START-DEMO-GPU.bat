@echo off
setlocal
cd /d "%~dp0"
title PowerScale Assistant - GPU demo

REM ---------------------------------------------------------------------------
REM  For a laptop with an NVIDIA GPU (e.g. RTX 3050 6GB).
REM  Ollama's cuda_v13 runner crashes on Ampere here:
REM      "CUDA error: shared object initialization failed"
REM  Forcing the cuda_v12 runner fixes it. Measured on the RTX 3050:
REM      prefill  1775 tok/s  (CPU was 42)     generation 48 tok/s  (CPU was 9.5)
REM      a full, cited answer comes back in ~12s instead of 2-3 minutes.
REM ---------------------------------------------------------------------------
set OLLAMA_LLM_LIBRARY=cuda_v12

REM  Keep the model resident in VRAM for the whole session. Ollama's default
REM  unloads it after 5 minutes idle, so the question you ask after talking for
REM  a few minutes pays an ~8-10s reload on top of the answer (25s instead of
REM  ~13s). -1 = never unload.
set OLLAMA_KEEP_ALIVE=-1

REM  Opt in to the Ollama/GPU engine (the default everywhere else is the
REM  in-process CPU engine, so CPU-only machines are unaffected).
set USE_OLLAMA=1

REM  Measured on this RTX 3050, same SMB question, warm:
REM    qwen2.5:3b-instruct  ~11s  + fenced `isi` CLI block   <-- best
REM    llama3.1:8b          ~47s  + fenced `isi` CLI block
REM    llama3.2:3b          ~13s  but NEVER emits the CLI command
REM  8 full-length excerpts (not 5 truncated ones) is what makes the CLI block
REM  reliable: verified 4/4 runs, ~13s each, 234-328 word answers.
set OLLAMA_CHAT_MODEL=qwen2.5:3b-instruct
set OLLAMA_NUM_CTX=8192
set TOP_K_GPU=8

echo.
echo  ============================================================
echo    PowerScale AI Assistant  -  GPU demo  (Ollama + NVIDIA)
echo  ============================================================
echo.
echo  [1/3] Restarting Ollama on the GPU (cuda_v12 runner)...
taskkill /F /IM "ollama app.exe" >nul 2>&1
taskkill /F /IM ollama.exe       >nul 2>&1
start "Ollama (GPU)" /min "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve

echo  [2/3] Waiting for Ollama to come up...
:waitollama
timeout /t 1 /nobreak >nul
curl -s -o nul http://localhost:11434/api/tags
if errorlevel 1 goto waitollama
echo        Ollama is ready.
echo.

echo  [3/3] Starting the web app (loads the RAG engine, ~10 seconds)...
echo.
echo    OneFS WebUI assistant :  http://localhost:8501/
echo    InsightIQ assistant   :  http://localhost:8501/insightiq
echo.
echo    Answers take about 10-15 seconds on the GPU.
echo    If the browser opens before the app is ready, just refresh.
echo    Keep this window open.  Press Ctrl+C to stop.
echo.

start "" http://localhost:8501
REM server_local.py auto-detects Ollama and uses the GPU; it keeps the prompt
REM that produces full answers with fenced isi CLI commands.
"%~dp0venv\Scripts\python.exe" "%~dp0web\server_local.py"

endlocal

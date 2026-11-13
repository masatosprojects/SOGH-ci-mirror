@echo off
chcp 65001 >nul
if exist "%~dp0research\antigravity-local-ai\HOLD_REAL_MODEL_RUN.txt" (
    echo REAL-MODEL RUN IS ON HOLD by the user. Nothing was started. See research\antigravity-local-ai\HOLD_REAL_MODEL_RUN.txt
    pause
    exit /b 3
)
title SOGH Antigravity - Standalone Physical Inference Runner

echo ========================================================
echo  SOGH Antigravity: Standalone Physical Inference Runner
echo  (ASUS TUF Gaming FX505DY / Qwen3-1.7B-Instruct)
echo ========================================================
echo.
echo [Step 1] Checking HWiNFO64 sensor monitor...
tasklist /FI "IMAGENAME eq HWiNFO64.exe" 2>NUL | find /I /N "HWiNFO64.exe">NUL
if "%ERRORLEVEL%"=="1" (
    echo Starting HWiNFO64 in background...
    start "" "C:\Users\USER\llm_bench\hwinfo\app\HWiNFO64.exe"
    echo Waiting 6 seconds for HWiNFO64 shared memory initialization...
    timeout /t 6 /nobreak >nul
) else (
    echo HWiNFO64 is already running.
)

echo.
echo [Step 2] Executing Standalone Supervised Inference...
cd /d "%~dp0"
python "research\antigravity-local-ai\scripts\standalone_production_runner.py"

echo.
echo ========================================================
echo  Execution finished!
echo  Check the output above. If succeeded, results are saved.
echo  Restart Google Antigravity to report this result.
echo ========================================================
pause

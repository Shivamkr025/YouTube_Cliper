@echo off
title ViralClip AI - Master Server Launcher
color 0A
echo =========================================================
echo    🚀 ViralClip AI - Autonomous Shorts & Reels Engine
echo =========================================================
echo.
echo Starting backend server on http://127.0.0.1:8000 ...
echo.
cd /d "%~dp0ai-viral-clipper"
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe main.py server
) else (
    python main.py server
)
pause

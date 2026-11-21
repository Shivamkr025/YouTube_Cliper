@echo off
title ViralClip AI - Backend Server
color 0A
echo.
echo  =========================================
echo   ViralClip AI Backend Server
echo   Running at: http://localhost:8000
echo  =========================================
echo.
echo  Open frontend at: http://127.0.0.1:8000
echo  (or use VS Code Live Server port 5500)
echo.
cd /d "%~dp0"
.\venv\Scripts\python.exe -m uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload
pause

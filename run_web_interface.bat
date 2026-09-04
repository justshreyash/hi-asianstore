@echo off
chcp 65001 >nul
title KDrama Hindi Auto-Store Web Interfaces

echo ==============================================================================
echo   STARTING WEB INTERFACES
echo ==============================================================================
echo.
echo [1] Launching KDramaLover Ingestion Console on http://127.0.0.1:8000/web/ingestion
echo [2] Launching Streaming Platform Demo Player on http://127.0.0.1:8080/demo
echo.

:: Start FastAPI server in background window
start "FastAPI Ingestion Console (Port 8000)" cmd /k "python -m uvicorn api.app:app --port 8000 --reload"

:: Start Integration API & Demo Player in background window
start "Integration API & Player (Port 8080)" cmd /k "python integration/api_server.py --port 8080"

:: Wait 2 seconds for servers to bind
timeout /t 2 /nobreak >nul

:: Automatically open both web interfaces in default browser
start http://127.0.0.1:8000/web/ingestion
start http://127.0.0.1:8080/demo

echo ==============================================================================
echo Web interfaces opened in your browser!
echo  - Ingestion Console : http://127.0.0.1:8000/web/ingestion
echo  - Stream Player Demo: http://127.0.0.1:8080/demo
echo ==============================================================================
echo Press any key to exit this launcher window (servers will remain running).
pause >nul

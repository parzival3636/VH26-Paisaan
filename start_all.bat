@echo off
REM Intelligent Pipeline Demo - Quick Start Script (Windows)

echo ========================================
echo Starting Intelligent Pipeline Demo
echo ========================================
echo.

REM Start Docker services
echo [1/3] Starting Docker services...
docker-compose up -d
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to start Docker services
    pause
    exit /b 1
)
echo Docker services started successfully
echo.

REM Wait for services
echo Waiting for services to initialize...
timeout /t 10 /nobreak > nul
echo.

REM Start backend
echo [2/3] Starting Backend Pipeline...
start "Pipeline Backend" cmd /k python pipeline/main.py
echo Backend started in new window
echo.

REM Wait for backend
timeout /t 5 /nobreak > nul
echo.

REM Start frontend
echo [3/3] Starting Frontend...
cd frontend\frontend
start "Pipeline Frontend" cmd /k npm run dev
cd ..\..
echo Frontend started in new window
echo.

echo ========================================
echo All services started successfully!
echo ========================================
echo.
echo Access the demo at: http://localhost:5174
echo Backend API: http://localhost:8000
echo API Docs: http://localhost:8000/docs
echo.
echo Two new windows opened:
echo   1. Pipeline Backend (port 8000)
echo   2. Pipeline Frontend (port 5174)
echo.
echo To stop: Close the command windows and run stop_all.bat
echo.
pause

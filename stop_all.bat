@echo off
REM Intelligent Pipeline Demo - Stop Script (Windows)

echo ========================================
echo Stopping Intelligent Pipeline Demo
echo ========================================
echo.

echo [1/3] Stopping Docker services...
docker-compose down
echo Docker services stopped
echo.

echo [2/3] Stopping Backend...
taskkill /F /FI "WindowTitle eq Pipeline Backend*" 2>nul
echo Backend stopped
echo.

echo [3/3] Stopping Frontend...
taskkill /F /FI "WindowTitle eq Pipeline Frontend*" 2>nul
echo Frontend stopped
echo.

echo ========================================
echo All services stopped successfully!
echo ========================================
echo.
pause

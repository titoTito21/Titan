@echo off
REM Quick script to check if Titan-Net server is running

echo ====================================
echo Titan-Net Server Status Check
echo ====================================
echo.

netstat -ano | findstr ":8001" > nul
if %errorlevel% == 0 (
    echo [OK] WebSocket server is running on port 8001
    netstat -ano | findstr ":8001"
) else (
    echo [FAIL] WebSocket server is NOT running on port 8001
)

echo.

netstat -ano | findstr ":8000" > nul
if %errorlevel% == 0 (
    echo [OK] HTTP server is running on port 8000
    netstat -ano | findstr ":8000"
) else (
    echo [FAIL] HTTP server is NOT running on port 8000
)

echo.
echo ====================================
echo.
echo To start the server, run: start_server.bat
echo.
pause

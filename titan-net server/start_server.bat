@echo off
echo ====================================
echo Starting Titan-Net Server...
echo ====================================
echo.

REM Create logs directory if it doesn't exist
if not exist logs mkdir logs

REM Start the server
python main.py

pause

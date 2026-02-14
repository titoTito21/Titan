@echo off
echo ============================================
echo Cleaning Python cache and restarting...
echo ============================================

echo.
echo 1. Closing all Python processes...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM pythonw.exe /T 2>nul
timeout /t 2 >nul

echo.
echo 2. Deleting __pycache__ folders...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"

echo.
echo 3. Deleting .pyc files...
del /s /q *.pyc 2>nul

echo.
echo ============================================
echo Cache cleaned successfully!
echo ============================================
echo.
echo Starting TCE Launcher with clean state...
echo.

python main.py

pause

@echo off
echo ============================================
echo FORCE CLEAN - Clearing ALL Python cache
echo ============================================
echo.

echo 1. Killing all Python processes...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM pythonw.exe /T 2>nul
timeout /t 2 >nul

echo.
echo 2. Deleting __pycache__ folders...
for /d /r . %%d in (__pycache__) do @if exist "%%d" (
    echo Deleting: %%d
    rd /s /q "%%d"
)

echo.
echo 3. Deleting .pyc files...
del /s /q *.pyc 2>nul

echo.
echo ============================================
echo Cache cleaned! Now start TCE Launcher.
echo ============================================
pause

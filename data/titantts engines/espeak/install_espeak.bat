@echo off
REM eSpeak-NG Installation Helper for Titan Screen Reader
REM Opens download page and provides installation instructions

echo ========================================================================
echo eSpeak-NG Installation Helper for Titan Screen Reader
echo ========================================================================
echo.
echo This script will help you install eSpeak-NG 1.52.0
echo.
echo ========================================================================
echo INSTALLATION STEPS:
echo ========================================================================
echo.
echo 1. Download eSpeak-NG 1.52.0 from GitHub releases
echo    Opening download page in your browser...
echo.

REM Open GitHub releases page
start https://github.com/espeak-ng/espeak-ng/releases/tag/1.52.0

echo.
echo 2. Download ONE of the following files:
echo    - espeak-ng-X64.msi (recommended for 64-bit Windows)
echo    - espeak-ng-X86.msi (for 32-bit Windows)
echo.
echo 3. Run the downloaded MSI installer
echo.
echo 4. After installation, copy the following files:
echo    FROM: C:\Program Files\eSpeak NG\
echo    TO:   %~dp0
echo.
echo    Required files:
echo    - espeak-ng.exe
echo    - espeak-ng.dll
echo    - espeak-ng-data\ (entire directory with all contents)
echo.
echo ========================================================================
echo.

pause

echo.
echo Checking if eSpeak-NG is already installed in system...
echo.

where espeak-ng >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo [OK] eSpeak-NG found in system PATH!
    echo Running: espeak-ng --version
    echo.
    espeak-ng --version
    echo.
    echo You can use system eSpeak-NG, but bundled version is recommended.
) else (
    echo [INFO] eSpeak-NG not found in system PATH
    echo This is normal if you haven't installed it yet.
)

echo.
echo ========================================================================
echo QUICK COPY INSTRUCTIONS:
echo ========================================================================
echo.
echo If you installed eSpeak-NG to default location, run these commands:
echo.
echo   xcopy "C:\Program Files\eSpeak NG\*.*" "%~dp0" /E /I /Y
echo.
echo Or copy manually:
echo   1. Open: C:\Program Files\eSpeak NG\
echo   2. Select all files and folders
echo   3. Copy to: %~dp0
echo.
echo ========================================================================
echo.

set /p COPY_NOW="Do you want to copy from default installation location now? (Y/N): "

if /i "%COPY_NOW%"=="Y" (
    echo.
    echo Copying files...
    xcopy "C:\Program Files\eSpeak NG\*.*" "%~dp0" /E /I /Y

    if %ERRORLEVEL% == 0 (
        echo.
        echo [SUCCESS] Files copied successfully!
        echo.
        echo Verifying installation...
        if exist "%~dp0espeak-ng.exe" (
            echo [OK] espeak-ng.exe found
            "%~dp0espeak-ng.exe" --version
        ) else (
            echo [ERROR] espeak-ng.exe not found
        )

        if exist "%~dp0espeak-ng-data" (
            echo [OK] espeak-ng-data directory found
        ) else (
            echo [ERROR] espeak-ng-data directory not found
        )
    ) else (
        echo.
        echo [ERROR] Copy failed! Error code: %ERRORLEVEL%
        echo.
        echo Possible reasons:
        echo - eSpeak-NG not installed to default location
        echo - Permission denied (try running as Administrator)
        echo - Files already in use
        echo.
        echo Please copy files manually as described above.
    )
) else (
    echo.
    echo Copy cancelled. Please copy files manually when ready.
)

echo.
echo ========================================================================
echo VERIFICATION:
echo ========================================================================
echo.

if exist "%~dp0espeak-ng.exe" (
    echo [OK] espeak-ng.exe exists
) else (
    echo [MISSING] espeak-ng.exe not found
)

if exist "%~dp0espeak-ng.dll" (
    echo [OK] espeak-ng.dll exists
) else (
    echo [MISSING] espeak-ng.dll not found
)

if exist "%~dp0espeak-ng-data" (
    echo [OK] espeak-ng-data directory exists
    dir "%~dp0espeak-ng-data" | find "File(s)"
) else (
    echo [MISSING] espeak-ng-data directory not found
)

echo.
echo ========================================================================
echo.
echo Installation helper finished!
echo.
echo If all files are present, Titan Screen Reader will automatically
echo detect and use bundled eSpeak-NG.
echo.
echo ========================================================================
echo.

pause

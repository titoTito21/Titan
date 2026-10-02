@echo off
setlocal EnableExtensions
rem ===========================================================================
rem  Titan updater - downloads the latest Titan and unpacks it over the
rem  installed one, from OUTSIDE Titan. It needs nothing but Windows and
rem  the installation itself: no 7-Zip, and it may be run from anywhere.
rem
rem      updater.bat [installation folder] [/y] [/tar] [/interpreter]
rem
rem  The folder is where Titan is installed - C:\Titan\titan_data unless
rem  another one is given. The program package is always applied; the
rem  Python interpreter package too when the server's version ends in "i"
rem  (or with /interpreter).
rem
rem  /y answers every question with yes. /tar unpacks with Windows' own
rem  tar.exe even when a 7-Zip is available.
rem
rem  Unpacking needs no extra program. A 7-Zip is used when there is one -
rem  the installation's own data\bin\7z.exe (copied to %TEMP% first, since
rem  the archive replaces it), one next to this file, one on PATH or in
rem  Program Files - and otherwise Windows' own tar.exe (libarchive, in
rem  every Windows since 10 1803), which reads 7z archives: checked against
rem  the real Titan archives, byte for byte, the ARM64 block included.
rem
rem  Why this exists: a compiled Titan updating itself has to move its own
rem  running files aside, and a build up to 0.6.1 fails at that on a file
rem  the process keeps open (_internal\base_library.zip). This script runs
rem  with Titan closed, so nothing is locked.
rem ===========================================================================

set "VERSION_URL=https://titosofttitan.com/titan/titanchk/version.ver"
set "CHANGES_URL=https://titosofttitan.com/titan/titanchk/changes.txt"
set "MAIN_URL=https://titosofttitan.com/titan/titan.main.7z"
set "INTERPRETER_URL=https://titosofttitan.com/titan/titan.interpreter.7z"

set "YES="
set "FORCE_TAR="
set "WANT_INTERPRETER="
set "INSTALL="
for %%A in (%*) do (
    if /i "%%~A"=="/y" (set "YES=1") else if /i "%%~A"=="-y" (set "YES=1") else if /i "%%~A"=="--yes" (set "YES=1") else if /i "%%~A"=="/tar" (set "FORCE_TAR=1") else if /i "%%~A"=="/interpreter" (set "WANT_INTERPRETER=1") else if not defined INSTALL set "INSTALL=%%~A"
)

if not defined INSTALL set "INSTALL=C:\Titan\titan_data"
if "%INSTALL:~-1%"=="\" set "INSTALL=%INSTALL:~0,-1%"
if not exist "%INSTALL%\Titan.exe" (
    echo There is no Titan installed in "%INSTALL%" - no Titan.exe there.
    echo Give the installation folder as the first argument:  updater.bat "D:\Titan\titan_data"
    goto :fail
)

set "WORK=%TEMP%\titan_update"
set "LOG=%WORK%\updater.log"
if not exist "%WORK%" mkdir "%WORK%"
echo ==== %DATE% %TIME% updater.bat for "%INSTALL%" >> "%LOG%"

echo.
echo Titan updater
echo   Installation: %INSTALL%
echo   Log:          %LOG%
echo.

rem ---------------------------------------------------------------- download tool
set "DL="
where curl.exe >nul 2>&1 && set "DL=curl"
if not defined DL (
    where powershell.exe >nul 2>&1 && set "DL=powershell"
)
if not defined DL (
    call :say "Neither curl.exe nor powershell.exe was found; nothing can download the update."
    goto :fail
)

rem ----------------------------------------------------------- Titan must be closed
tasklist /FI "IMAGENAME eq Titan.exe" 2>nul | find /i "Titan.exe" >nul
if not errorlevel 1 (
    call :say "Titan is running. It has to be closed for the update."
    if not defined YES (
        choice /C YN /M "Close Titan now"
        if errorlevel 2 goto :fail
    )
    taskkill /F /IM Titan.exe >nul 2>&1
    timeout /T 3 /NOBREAK >nul
    tasklist /FI "IMAGENAME eq Titan.exe" 2>nul | find /i "Titan.exe" >nul
    if not errorlevel 1 (
        call :say "Titan is still running; cannot update while its files are in use."
        goto :fail
    )
    call :say "Titan closed."
)

rem ------------------------------------------------------------ remote version
call :download "%VERSION_URL%" "%WORK%\version.ver" quiet
if errorlevel 1 (
    call :say "The update server did not answer (%VERSION_URL%)."
    goto :fail
)
set "REMOTE="
set /p REMOTE=<"%WORK%\version.ver"
if not defined REMOTE (
    call :say "The server answered an empty version."
    goto :fail
)
set "NEEDS_INTERPRETER="
if /i "%REMOTE:~-1%"=="i" (
    set "NEEDS_INTERPRETER=1"
    set "REMOTE=%REMOTE:~0,-1%"
)
if defined WANT_INTERPRETER set "NEEDS_INTERPRETER=1"
call :say "Latest version on the server: %REMOTE%"
if defined NEEDS_INTERPRETER call :say "The Python interpreter package will be downloaded as well."
call :download "%CHANGES_URL%" "%WORK%\changes.txt" quiet
if not errorlevel 1 (
    echo.
    echo What changed:
    type "%WORK%\changes.txt"
    echo.
)
if not defined YES (
    choice /C YN /M "Download and install version %REMOTE% into %INSTALL%"
    if errorlevel 2 goto :fail
)

rem ------------------------------------------------------------------ 7-Zip
rem The archive contains data\bin\7z.exe like everything else, so the one
rem inside the installation is copied to %WORK% and the copy does the work.
set "SEVENZIP="
set "TAR="
if exist "%SystemRoot%\System32\tar.exe" set "TAR=%SystemRoot%\System32\tar.exe"
if defined FORCE_TAR goto :tool_chosen
if exist "%INSTALL%\data\bin\7z.exe" (
    if not exist "%WORK%\7z" mkdir "%WORK%\7z"
    copy /Y "%INSTALL%\data\bin\7z.exe" "%WORK%\7z\" >nul
    copy /Y "%INSTALL%\data\bin\7z.dll" "%WORK%\7z\" >nul 2>&1
    if exist "%WORK%\7z\7z.exe" set "SEVENZIP=%WORK%\7z\7z.exe"
)
if not defined SEVENZIP if exist "%~dp07z.exe" set "SEVENZIP=%~dp07z.exe"
if not defined SEVENZIP if exist "%~dp0bin\7z.exe" set "SEVENZIP=%~dp0bin\7z.exe"
if not defined SEVENZIP if exist "%~dp0..\bin\7z.exe" set "SEVENZIP=%~dp0..\bin\7z.exe"
if not defined SEVENZIP (
    where 7z.exe >nul 2>&1 && for /f "delims=" %%P in ('where 7z.exe') do if not defined SEVENZIP set "SEVENZIP=%%P"
)
if not defined SEVENZIP if exist "%ProgramFiles%\7-Zip\7z.exe" set "SEVENZIP=%ProgramFiles%\7-Zip\7z.exe"
:tool_chosen
if defined SEVENZIP (
    call :say "Unpacking with 7-Zip: %SEVENZIP%"
) else if defined TAR (
    if defined FORCE_TAR (call :say "Unpacking with Windows' own tar.exe, as asked.") else call :say "No 7-Zip found; unpacking with Windows' own tar.exe."
) else (
    call :say "Nothing here can unpack a 7z archive: no data\bin\7z.exe in the installation, no 7z.exe on PATH or in Program Files, and no tar.exe in Windows."
    goto :fail
)

rem --------------------------------------------------------------- download
call :say "Downloading titan.main.7z ..."
call :download "%MAIN_URL%" "%WORK%\titan.main.7z"
if errorlevel 1 (
    call :say "The download of titan.main.7z failed."
    goto :fail
)
if defined NEEDS_INTERPRETER (
    call :say "Downloading titan.interpreter.7z ..."
    call :download "%INTERPRETER_URL%" "%WORK%\titan.interpreter.7z"
    if errorlevel 1 (
        call :say "The download of titan.interpreter.7z failed."
        goto :fail
    )
)

rem ----------------------------------------------------------------- verify
call :say "Checking the archive ..."
call :verify "%WORK%\titan.main.7z"
if errorlevel 1 (
    call :say "titan.main.7z is damaged or incomplete; nothing was changed."
    goto :fail
)
if defined NEEDS_INTERPRETER (
    call :verify "%WORK%\titan.interpreter.7z"
    if errorlevel 1 (
        call :say "titan.interpreter.7z is damaged or incomplete; nothing was changed."
        goto :fail
    )
)

rem ----------------------------------------------------------------- unpack
call :say "Unpacking titan.main.7z into %INSTALL% ..."
call :unpack "%WORK%\titan.main.7z"
if errorlevel 1 (
    call :say "Unpacking titan.main.7z failed (see the log)."
    goto :fail
)
if defined NEEDS_INTERPRETER (
    call :say "Unpacking titan.interpreter.7z into %INSTALL% ..."
    call :unpack "%WORK%\titan.interpreter.7z"
    if errorlevel 1 (
        call :say "Unpacking titan.interpreter.7z failed (see the log)."
        goto :fail
    )
)

rem ------------------------------------------------------------------ tidy up
rem Leftovers of an earlier in-place update attempt: <name>.old beside its
rem live file. Titan removes them at its next start too; a fresh unpack has
rem just written every live file, so they can go now.
for /r "%INSTALL%" %%F in (*.old) do (
    if exist "%%~dpnF" del /q "%%F" 2>nul
)
del /q "%WORK%\titan.main.7z" 2>nul
del /q "%WORK%\titan.interpreter.7z" 2>nul

echo.
call :say "Update to version %REMOTE% complete."
if not defined YES (
    choice /C YN /M "Start Titan now"
    if not errorlevel 2 start "" "%INSTALL%\Titan.exe"
)
echo ==== done >> "%LOG%"
endlocal
exit /b 0

rem ===========================================================================
:verify
rem :verify <archive> - reads the whole archive without writing anything.
if defined SEVENZIP (
    "%SEVENZIP%" t "%~1" -sccUTF-8 >> "%LOG%" 2>&1
) else (
    "%TAR%" -tf "%~1" >nul 2>> "%LOG%"
)
exit /b %errorlevel%

:unpack
rem :unpack <archive> - over the installation, every existing file replaced.
if defined SEVENZIP (
    "%SEVENZIP%" x "%~1" -o"%INSTALL%" -y -aoa -sccUTF-8 -bsp1 -bso0
) else (
    "%TAR%" -xf "%~1" -C "%INSTALL%" 2>> "%LOG%"
)
exit /b %errorlevel%

:say
echo %~1
echo %DATE% %TIME% %~1 >> "%LOG%"
exit /b 0

:download
rem :download <url> <file> [quiet]
set "DL_URL=%~1"
set "DL_FILE=%~2"
if exist "%DL_FILE%" del /q "%DL_FILE%"
if "%DL%"=="curl" (
    if "%~3"=="quiet" (
        curl.exe -f -s -S -L --retry 3 --connect-timeout 15 -o "%DL_FILE%" "%DL_URL%" 2>> "%LOG%"
    ) else (
        curl.exe -f -L --retry 3 --connect-timeout 15 -o "%DL_FILE%" "%DL_URL%"
    )
) else (
    powershell.exe -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%DL_URL%' -OutFile '%DL_FILE%' -UseBasicParsing; exit 0 } catch { Write-Error $_; exit 1 }" 2>> "%LOG%"
)
if errorlevel 1 exit /b 1
if not exist "%DL_FILE%" exit /b 1
for %%S in ("%DL_FILE%") do if %%~zS EQU 0 exit /b 1
exit /b 0

:fail
echo.
echo The update was not applied. Details: %LOG%
echo ==== failed >> "%LOG%"
endlocal
exit /b 1

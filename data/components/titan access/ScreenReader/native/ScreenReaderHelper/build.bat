@echo off
REM Builds ScreenReaderHelper.dll (x64) with MSVC.
REM Output: native\ScreenReaderHelper\bin\ScreenReaderHelper.dll
REM Invoked automatically by ScreenReader.csproj before the managed build,
REM and can also be run by hand.

setlocal enabledelayedexpansion
cd /d "%~dp0"

REM --- locate Visual Studio's C++ toolchain via vswhere -----------------------
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VSPATH="
if exist "%VSWHERE%" (
    for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -prerelease -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
)
if not defined VSPATH (
    REM fallback: VS 2026 / 18 Insiders default location
    if exist "C:\Program Files\Microsoft Visual Studio\18\Insiders" set "VSPATH=C:\Program Files\Microsoft Visual Studio\18\Insiders"
)
if not defined VSPATH (
    echo [ScreenReaderHelper] ERROR: could not find a Visual Studio C++ toolchain.
    echo Install the "Desktop development with C++" workload.
    exit /b 1
)

set "VCVARS=%VSPATH%\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
    echo [ScreenReaderHelper] ERROR: vcvars64.bat not found at "%VCVARS%".
    exit /b 1
)

call "%VCVARS%" >nul
if errorlevel 1 (
    echo [ScreenReaderHelper] ERROR: vcvars64.bat failed.
    exit /b 1
)

if not exist bin mkdir bin

echo [ScreenReaderHelper] Compiling srhelper.cpp ...
cl /nologo /LD /O2 /EHsc /W3 /std:c++17 ^
   /I include /I ..\shared src\srhelper.cpp ^
   /Fo:bin\ /Fe:bin\ScreenReaderHelper.dll ^
   /link /MACHINE:X64

if errorlevel 1 (
    echo [ScreenReaderHelper] BUILD FAILED.
    exit /b 1
)

echo [ScreenReaderHelper] OK: bin\ScreenReaderHelper.dll
endlocal
exit /b 0

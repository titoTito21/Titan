@echo off
rem ==========================================================================
rem Build titan_keyhook.dll - the keyboard hook the reader cannot lose - into
rem the component's lib\ folder. MSVC x64 only (Titan's Python is 64-bit).
rem Set VSDEVCMD to your own vcvarsall.bat to override the search.
rem ==========================================================================
setlocal
cd /d "%~dp0"

if "%VSDEVCMD%"=="" set "VSDEVCMD=%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if not exist "%VSDEVCMD%" set "VSDEVCMD=%ProgramFiles%\Microsoft Visual Studio\18\Insiders\VC\Auxiliary\Build\vcvarsall.bat"
if not exist "%VSDEVCMD%" set "VSDEVCMD=%ProgramFiles(x86)%\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if not exist "%VSDEVCMD%" (
    echo Could not find vcvarsall.bat. Set VSDEVCMD to its full path and retry.
    exit /b 1
)

call "%VSDEVCMD%" x64 >nul || goto :fail
cl /nologo /LD /O2 /W4 /DWIN32 /D_WINDOWS /DUNICODE /D_UNICODE ^
   titan_keyhook.c user32.lib kernel32.lib ^
   /Fe:titan_keyhook.dll /link /DEF:titan_keyhook.def || goto :fail
if not exist "..\..\lib" mkdir "..\..\lib"
copy /y titan_keyhook.dll "..\..\lib\titan_keyhook.dll" >nul || goto :fail
del /q titan_keyhook.obj titan_keyhook.exp titan_keyhook.lib 2>nul
echo Built lib\titan_keyhook.dll
exit /b 0

:fail
echo BUILD FAILED
exit /b 1

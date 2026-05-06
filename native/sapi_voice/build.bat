@echo off
rem Build titantts32.dll + titantts64.dll and place them into ..\..\data\lib\.
setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set OUT_DIR=%SCRIPT_DIR%..\..\data\lib
set BUILD_DIR=%SCRIPT_DIR%build

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

set VCVARS="C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvarsall.bat"
if not exist %VCVARS% set VCVARS="C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"

set SRC=%SCRIPT_DIR%titantts.cpp
set DEF=%SCRIPT_DIR%titantts.def

echo === Building x64 ===
call %VCVARS% x64 >nul || (echo vcvarsall x64 FAILED & exit /b 1)
pushd "%BUILD_DIR%"
cl /nologo /LD /O2 /EHsc /MT /W3 /DUNICODE /D_UNICODE ^
   /Fe:titantts64.dll /Fo:x64_ "%SRC%" ^
   /link /DEF:"%DEF%" /SUBSYSTEM:WINDOWS ^
   ole32.lib advapi32.lib kernel32.lib user32.lib uuid.lib
if errorlevel 1 (echo x64 BUILD FAILED & popd & exit /b 1)
popd
copy /y "%BUILD_DIR%\titantts64.dll" "%OUT_DIR%\titantts64.dll" >nul

echo === Building x86 ===
call %VCVARS% x86 >nul || (echo vcvarsall x86 FAILED & exit /b 1)
pushd "%BUILD_DIR%"
cl /nologo /LD /O2 /EHsc /MT /W3 /DUNICODE /D_UNICODE ^
   /Fe:titantts32.dll /Fo:x86_ "%SRC%" ^
   /link /DEF:"%DEF%" /SUBSYSTEM:WINDOWS ^
   ole32.lib advapi32.lib kernel32.lib user32.lib uuid.lib
if errorlevel 1 (echo x86 BUILD FAILED & popd & exit /b 1)
popd
copy /y "%BUILD_DIR%\titantts32.dll" "%OUT_DIR%\titantts32.dll" >nul

echo.
echo === DONE ===
dir "%OUT_DIR%\titantts*.dll"

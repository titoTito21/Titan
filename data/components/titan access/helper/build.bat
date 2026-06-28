@echo off
rem ==========================================================================
rem Build titan_access_helper.dll (the NVDA controller server for Titan Access).
rem
rem Requirements (any recent Visual Studio Build Tools + Windows SDK):
rem   * midl.exe  (Windows SDK)
rem   * cl.exe / link.exe (MSVC)
rem Run from a "x64 Native Tools Command Prompt for VS" so midl and cl are on
rem PATH and target 64-bit (Titan ships a 64-bit Python).
rem
rem Output: titan_access_helper.dll  (copied next to this script). The Python
rem loader (titan_access/nvda_controller_server.py) searches the component root,
rem this helper/ folder and lib/ for it.
rem ==========================================================================
setlocal
cd /d "%~dp0"

echo [1/3] MIDL: generating server stub from nvdaController.idl ...
midl /nologo /app_config /server stub /client none /env x64 /h nvdaController.h nvdaController.idl
if errorlevel 1 goto :fail

echo [2/3] CL: compiling titan_access_helper.dll ...
cl /nologo /LD /O2 /DWIN32 /D_WINDOWS ^
   titan_access_helper.c nvdaController_s.c ^
   /link /OUT:titan_access_helper.dll rpcrt4.lib advapi32.lib user32.lib
if errorlevel 1 goto :fail

echo [3/3] Done. Built titan_access_helper.dll
echo Copy it (or leave it here) -- the reader picks it up automatically.
goto :eof

:fail
echo BUILD FAILED. Open a "x64 Native Tools Command Prompt for VS" and retry.
exit /b 1

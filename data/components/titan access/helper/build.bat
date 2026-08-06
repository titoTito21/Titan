@echo off
rem ==========================================================================
rem Build the Titan Access NVDA-controller bridge:
rem
rem   titan_access_helper.dll   the RPC server Titan Access hosts (64-bit, the
rem                             bitness of Titan's Python)
rem   nvda_probe64.exe          a 64-bit client probe
rem   nvda_probe32.exe          a 32-BIT client probe -- the only way to prove
rem                             the bridge really answers 32-bit applications,
rem                             since Titan itself is 64-bit and can never
rem                             exercise that path in process
rem
rem Requirements (any recent Visual Studio Build Tools + Windows SDK):
rem   * midl.exe  (Windows SDK)
rem   * cl.exe / link.exe (MSVC), with BOTH the x64 and x86 toolsets installed
rem Run from an ordinary command prompt; this script calls vcvarsall itself for
rem each target. Set VSDEVCMD to your own vcvarsall.bat to override the search.
rem
rem NOTE ON /protocol: the stubs are built DCE (NDR32) ON PURPOSE. An x64 MIDL
rem stub built "ndr64" only would reject every 32-bit client with
rem RPC_S_UNSUPPORTED_TRANS_SYN (1734): 64-bit applications would work and
rem 32-bit ones would not -- exactly the failure this bridge must never have.
rem DCE is understood by clients of both bitnesses.
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

echo [1/4] x64: MIDL server stub + helper DLL ...
call "%VSDEVCMD%" x64 >nul || goto :fail
midl /nologo /app_config /protocol dce /server stub /client none /env x64 ^
     /h nvdaController.h nvdaController.idl || goto :fail
cl /nologo /LD /O2 /DWIN32 /D_WINDOWS ^
   titan_access_helper.c nvdaController_s.c ^
   /link /OUT:titan_access_helper.dll rpcrt4.lib advapi32.lib user32.lib || goto :fail

echo [2/4] x64: client stub + nvda_probe64.exe ...
midl /nologo /app_config /protocol dce /client stub /server none /env x64 ^
     /h nvdaController.h nvdaController.idl || goto :fail
cl /nologo /O2 nvda_probe.c nvdaController_c.c ^
   /link /OUT:nvda_probe64.exe rpcrt4.lib user32.lib || goto :fail

echo [3/4] x86: client stub + nvda_probe32.exe ...
call "%VSDEVCMD%" x86 >nul || goto :fail
midl /nologo /app_config /protocol dce /client stub /server none /env win32 ^
     /h nvdaController.h nvdaController.idl || goto :fail
cl /nologo /O2 nvda_probe.c nvdaController_c.c ^
   /link /OUT:nvda_probe32.exe rpcrt4.lib user32.lib || goto :fail

echo [4/4] Restoring the x64 server header, so a later rebuild starts clean ...
call "%VSDEVCMD%" x64 >nul || goto :fail
midl /nologo /app_config /protocol dce /server stub /client none /env x64 ^
     /h nvdaController.h nvdaController.idl || goto :fail

echo.
echo Done: titan_access_helper.dll, nvda_probe64.exe, nvda_probe32.exe
echo Leave them here -- the reader finds them automatically.
goto :eof

:fail
echo BUILD FAILED.
exit /b 1

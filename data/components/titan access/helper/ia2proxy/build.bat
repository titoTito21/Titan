@echo off
rem Build IAccessible2Proxy.dll from the IA2 IDL (BSD) with the Windows SDK's
rem MIDL and Visual Studio's compiler: the COM proxy/stub without which an
rem IAccessible2 call across processes cannot be marshalled. Titan Access
rem registers the result for its own process (ia2.ensure_proxy), so nothing
rem is written to the registry.
rem
rem   build.bat            -> ..\..\lib\IAccessible2Proxy.dll
setlocal
cd /d "%~dp0"
set VCVARS=
for %%V in ("C:\Program Files\Microsoft Visual Studio\18\Insiders" "C:\Program Files\Microsoft Visual Studio\2022\Community" "C:\Program Files\Microsoft Visual Studio\2022\Professional" "C:\Program Files\Microsoft Visual Studio\2022\BuildTools" "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools") do (
  if exist "%%~V\VC\Auxiliary\Build\vcvars64.bat" if "%VCVARS%"=="" set "VCVARS=%%~V\VC\Auxiliary\Build\vcvars64.bat"
)
if "%VCVARS%"=="" (
  echo No Visual Studio with vcvars64.bat was found.
  exit /b 1
)
call "%VCVARS%" >nul
if errorlevel 1 exit /b 1
python merge_idl.py || exit /b 1
if not exist build mkdir build
midl /nologo /win64 /env x64 /Oicf /out build /h ia2_api_all.h /iid ia2_api_all_i.c /proxy ia2_api_all_p.c /dlldata dlldata.c ia2_api_all.idl || exit /b 1
cd build
cl /nologo /c /O2 /MT /DWIN64 /D_WIN64 /DREGISTER_PROXY_DLL dlldata.c ia2_api_all_i.c ia2_api_all_p.c || exit /b 1
if not exist "..\..\..\lib" mkdir "..\..\..\lib"
link /nologo /DLL /DEF:..\proxy-dll\IAccessible2Proxy.def /OUT:..\..\..\lib\IAccessible2Proxy.dll dlldata.obj ia2_api_all_i.obj ia2_api_all_p.obj rpcrt4.lib oleaut32.lib ole32.lib uuid.lib advapi32.lib kernel32.lib || exit /b 1
cd ..
echo Built ..\..\lib\IAccessible2Proxy.dll
endlocal

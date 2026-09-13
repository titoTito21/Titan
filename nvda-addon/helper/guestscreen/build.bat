@echo off
rem Build guestscreen.dll with whatever MSVC this machine has.
rem
rem There is no project file on purpose: this is one source file with no
rem dependency beyond the Windows SDK, and a build that is one command is a
rem build somebody will actually run.
setlocal
set HERE=%~dp0
set VCVARS=
set A=C:\Program Files\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat
set B=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat
set C=C:\Program Files\Microsoft Visual Studio\18\Insiders\VC\Auxiliary\Build\vcvars64.bat
set D=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat
set E=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat
if exist "%A%" set VCVARS=%A%
if not defined VCVARS if exist "%B%" set VCVARS=%B%
if not defined VCVARS if exist "%C%" set VCVARS=%C%
if not defined VCVARS if exist "%D%" set VCVARS=%D%
if not defined VCVARS if exist "%E%" set VCVARS=%E%
if not defined VCVARS (
  echo No MSVC found. Install the Visual Studio Build Tools, or skip this:
  echo the add-on reads a guest in Python when the DLL is missing.
  exit /b 1
)
call "%VCVARS%" >nul
cl /nologo /LD /O2 /W4 /EHsc /std:c++20 "%HERE%guestscreen.cpp" "%HERE%windowcapture.cpp" /Fe"%HERE%guestscreen.dll" user32.lib gdi32.lib d3d11.lib dxgi.lib windowsapp.lib
if errorlevel 1 exit /b 1
echo Built %HERE%guestscreen.dll

rem The add-on loads the DLL from its own lib/ folder, so a fresh build is
rem copied there - otherwise the package ships the last one built and a fix
rem does nothing, which this repository has paid for before.
set LIBDIR=%HERE%..\..\addon\globalPlugins\titanEnhancements\lib
if exist "%LIBDIR%" copy /Y "%HERE%guestscreen.dll" "%LIBDIR%\guestscreen.dll" >nul && echo Copied to %LIBDIR%

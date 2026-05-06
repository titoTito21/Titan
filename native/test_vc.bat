@echo off
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvarsall.bat" x64 >nul 2>&1
if errorlevel 1 (echo VS18-x64 FAIL & goto try2)
echo VS18-x64 OK
where cl
if defined WindowsSdkDir echo SDK=%WindowsSdkDir%
if defined WindowsSDKVersion echo SDKVER=%WindowsSDKVersion%
exit /b 0
:try2
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64 >nul 2>&1
if errorlevel 1 (echo VS22-x64 FAIL & exit /b 1)
echo VS22-x64 OK
where cl
if defined WindowsSdkDir echo SDK=%WindowsSdkDir%
if defined WindowsSDKVersion echo SDKVER=%WindowsSDKVersion%

@echo off
rem Stop ONLY the stand-in Titan. Titan itself runs as python.exe, so
rem killing by image name kills the user's desktop with it - which is
rem exactly what happened before this existed.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*fake_titan.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

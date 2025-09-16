@echo off
REM Uruchomienie środowiska MSVC (dostosuj ścieżkę do swojej instalacji Visual Studio!)
call "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64

REM Kompilacja przez Nuitkę z użyciem MSVC
python -m nuitka --msvc=14.3 --standalone --remove-output main.py

echo.
echo Kompilacja zakończona!
pause

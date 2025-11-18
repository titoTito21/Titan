python -m nuitka main.py ^
  --standalone ^
  --remove-output ^
  --msvc=14.3 ^
  --lto=no ^
  --no-pyi-file ^
  --windows-disable-console

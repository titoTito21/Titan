"""
TCE Launcher Compilation Script
Compiles the application to a directory structure using PyInstaller.
Automatically detects and includes dependencies from all applications and games.
"""

import subprocess
import sys
import shutil
import os
import re
import ast
from pathlib import Path

def scan_python_imports(file_path):
    """
    Scan a Python file for import statements.
    Returns a set of module names.
    """
    imports = set()
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Try to parse with AST (more reliable)
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        # Get top-level module name
                        module = alias.name.split('.')[0]
                        imports.add(module)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        # Get top-level module name
                        module = node.module.split('.')[0]
                        imports.add(module)
        except SyntaxError:
            # Fallback to regex if AST parsing fails
            import_regex = re.compile(r'^\s*(?:from\s+(\S+)|import\s+(\S+))', re.MULTILINE)
            for match in import_regex.finditer(content):
                module = match.group(1) or match.group(2)
                if module:
                    # Get top-level module name
                    module = module.split('.')[0]
                    imports.add(module)
    except Exception as e:
        print(f"Warning: Could not scan {file_path}: {e}")

    return imports

def scan_directory_for_imports(directory):
    """
    Recursively scan a directory for Python files and extract all imports.
    Returns a set of module names.
    """
    all_imports = set()
    if not os.path.exists(directory):
        return all_imports

    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                imports = scan_python_imports(file_path)
                all_imports.update(imports)

    return all_imports

def get_app_and_game_dependencies(root_dir):
    """
    Scan all applications and games for their Python dependencies.
    Returns a set of module names.
    """
    dependencies = set()

    # Scan applications
    apps_dir = root_dir / 'data' / 'applications'
    if apps_dir.exists():
        print("Scanning applications for dependencies...")
        app_imports = scan_directory_for_imports(apps_dir)
        dependencies.update(app_imports)
        print(f"  Found {len(app_imports)} imports in applications")

    # Scan games
    games_dir = root_dir / 'data' / 'games'
    if games_dir.exists():
        print("Scanning games for dependencies...")
        game_imports = scan_directory_for_imports(games_dir)
        dependencies.update(game_imports)
        print(f"  Found {len(game_imports)} imports in games")

    # Scan components
    components_dir = root_dir / 'data' / 'components'
    if components_dir.exists():
        print("Scanning components for dependencies...")
        component_imports = scan_directory_for_imports(components_dir)
        dependencies.update(component_imports)
        print(f"  Found {len(component_imports)} imports in components")

    # Filter out standard library modules (basic filtering)
    stdlib_modules = {
        'os', 'sys', 'time', 'datetime', 'math', 'random', 'json', 'csv',
        'io', 're', 'threading', 'subprocess', 'pathlib', 'collections',
        'itertools', 'functools', 'operator', 'typing', 'platform', 'signal',
        'gc', 'warnings', 'argparse', 'glob', 'shutil', 'tempfile', 'uuid',
        'hashlib', 'hmac', 'secrets', 'base64', 'binascii', 'struct', 'array',
        'queue', 'asyncio', 'concurrent', 'multiprocessing', 'socket', 'ssl',
        'urllib', 'http', 'email', 'mimetypes', 'configparser', 'gettext',
        'locale', 'codecs', 'encodings', 'string', 'textwrap', 'unicodedata',
        'abc', 'copy', 'pickle', 'shelve', 'dbm', 'sqlite3', 'zlib', 'gzip',
        'bz2', 'lzma', 'zipfile', 'tarfile', 'xml', 'html', 'logging', 'unittest',
        'pdb', 'trace', 'traceback', 'inspect', 'dis', 'ast', 'ctypes', 'enum',
        'dataclasses', 'contextlib', 'weakref', 'importlib', '__future__',
    }

    external_deps = dependencies - stdlib_modules

    if external_deps:
        print(f"\nFound {len(external_deps)} external dependencies:")
        for dep in sorted(external_deps):
            print(f"  - {dep}")

    return external_deps

def compile_to_release():
    """Compile TCE Launcher to a directory distribution."""

    # Paths
    root_dir = Path(__file__).parent
    dist_dir = root_dir / "dist"
    build_dir = root_dir / "build"

    print("=" * 70)
    print("TCE Launcher - PyInstaller Compilation with Dependency Detection")
    print("=" * 70)
    print()

    # Scan for dependencies from applications and games
    print("Step 1: Scanning for dependencies...")
    print("-" * 70)
    app_dependencies = get_app_and_game_dependencies(root_dir)
    print()

    # Data directories to include
    data_dirs = [
        ("data", "data"),
        ("languages", "languages"),
        ("sfx", "sfx"),
        ("skins", "skins"),
    ]

    # Build the PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",  # Output as directory, not single file
        "--windowed",  # No console window
        "--name", "TCE Launcher",
        "--noconfirm",  # Overwrite without asking
    ]

    # Add icon if exists
    if (root_dir / "icon.ico").exists():
        cmd.extend(["--icon", "icon.ico"])

    # Add data directories
    for src, dst in data_dirs:
        src_path = root_dir / src
        if src_path.exists():
            cmd.extend(["--add-data", f"{src};{dst}"])

    print("Step 2: Building PyInstaller command...")
    print("-" * 70)

    # Comprehensive hidden imports for all TCE dependencies
    hidden_imports = [
        # Core accessibility
        "accessible_output3",
        "accessible_output3.outputs",
        "accessible_output3.outputs.auto",
        "accessible_output3.outputs.sapi5",
        "accessible_output3.outputs.nvda",
        "accessible_output3.outputs.jaws",

        # GUI
        "wx",
        "wx.adv",
        "wx.html",
        "wx.html2",
        "wx.lib",
        "wx.lib.agw",
        "wx.lib.newevent",

        # Audio
        "pygame",
        "pygame.mixer",

        # Windows COM and system
        "comtypes",
        "comtypes.client",
        "comtypes.stream",
        "win32com",
        "win32com.client",
        "pythoncom",
        "pywintypes",
        "win32api",
        "win32con",
        "win32gui",
        "win32process",
        "pywin32_system32",

        # Audio control
        "pycaw",
        "pycaw.pycaw",

        # Network
        "websockets",
        "websockets.client",
        "websockets.server",
        "aiohttp",
        "requests",

        # Async
        "asyncio",
        "asyncio.windows_events",

        # Speech recognition
        "speech_recognition",

        # Keyboard/input
        "keyboard",
        "pywinctl",

        # System
        "psutil",
        "wmi",

        # i18n
        "babel",
        "babel.numbers",
        "babel.dates",
        "babel.core",
        "gettext",

        # Config and data
        "configparser",
        "json",

        # Cryptography
        "cryptography",
        "bcrypt",

        # Telegram (optional)
        "telethon",

        # AI (optional)
        "google.generativeai",
        "gtts",

        # Standard library that might be missed
        "typing",
        "platform",
        "threading",
        "time",
        "os",
        "sys",
        "signal",
        "gc",
        "warnings",
        "argparse",
        "random",
        "glob",

        # Project modules
        "src",
        "src.ui",
        "src.ui.gui",
        "src.ui.invisibleui",
        "src.ui.menu",
        "src.ui.settingsgui",
        "src.ui.componentmanagergui",
        "src.ui.notificationcenter",
        "src.ui.shutdown_question",
        "src.ui.help",
        "src.ui.classic_start_menu",
        "src.settings",
        "src.settings.settings",
        "src.settings.titan_im_config",
        "src.network",
        "src.network.titan_net",
        "src.network.titan_net_gui",
        "src.network.telegram_client",
        "src.network.telegram_gui",
        "src.network.run_messenger",
        "src.titan_core",
        "src.titan_core.app_manager",
        "src.titan_core.game_manager",
        "src.titan_core.component_manager",
        "src.titan_core.tce_system",
        "src.titan_core.tce_system_net",
        "src.titan_core.translation",
        "src.titan_core.sound",
        "src.titan_core.tsounds",
        "src.titan_core.stereo_speech",
        "src.system",
        "src.system.system_monitor",
        "src.system.notifications",
        "src.system.updater",
        "src.system.lockscreen_monitor_improved",
        "src.system.klangomode",
        "src.system.com_fix",
        "src.system.fix_com_cache",
        "src.system.key_blocker",
        "src.system.wifi_safe_wrapper",
        "src.system.system_tray_list",
        "src.controller",
        "src.controller.controller_ui",
        "src.controller.controller_modes",
        "src.controller.controller_vibrations",
    ]

    # Add scanned dependencies from applications and games
    for dep in sorted(app_dependencies):
        if dep not in hidden_imports:
            hidden_imports.append(dep)

    print(f"Total hidden imports: {len(hidden_imports)}")
    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])

    # Collect all packages to ensure data files are included
    collect_packages = [
        "accessible_output3",
        "babel",
        "wx",
        "cryptography",  # Include Rust bindings (_rust modules)
    ]

    for pkg in collect_packages:
        cmd.extend(["--collect-all", pkg])

    # Main script
    cmd.append("main.py")

    print()
    print("Step 3: Running PyInstaller...")
    print("-" * 70)

    # Run PyInstaller
    result = subprocess.run(cmd, cwd=root_dir)

    if result.returncode == 0:
        print()
        print("Step 4: Post-processing...")
        print("-" * 70)
        print("Moving data directories for backward compatibility...")

        # Move data directories from _internal to main directory
        output_dir = dist_dir / "TCE Launcher"
        internal_dir = output_dir / "_internal"

        dirs_to_move = ["data", "languages", "sfx", "skins"]

        for dir_name in dirs_to_move:
            src = internal_dir / dir_name
            dst = output_dir / dir_name
            if src.exists():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.move(str(src), str(dst))
                print(f"  Moved: {dir_name}")

        # Copy Python interpreter to _internal
        print("Copying Python interpreter to _internal...")
        python_src = Path(sys.executable)
        python_dst = internal_dir / "python.exe"
        if python_src.exists():
            shutil.copy(str(python_src), str(python_dst))
            print(f"  Copied: _internal/python.exe")

        # Also copy pythonw.exe for windowless execution (if exists)
        pythonw_src = python_src.parent / "pythonw.exe"
        if pythonw_src.exists():
            pythonw_dst = internal_dir / "pythonw.exe"
            shutil.copy(str(pythonw_src), str(pythonw_dst))
            print(f"  Copied: _internal/pythonw.exe")

        # Copy python3XX.dll - required for python.exe to run
        python_version = f"{sys.version_info.major}{sys.version_info.minor}"
        python_dll_name = f"python{python_version}.dll"
        python_dll_src = python_src.parent / python_dll_name
        if python_dll_src.exists():
            python_dll_dst = internal_dir / python_dll_name
            shutil.copy(str(python_dll_src), str(python_dll_dst))
            print(f"  Copied: _internal/{python_dll_name}")
        else:
            print(f"  Warning: {python_dll_name} not found at {python_dll_src}")
            # Try to find it in Windows system directory
            import ctypes
            system_dir = Path(ctypes.windll.kernel32.GetSystemDirectoryW(None, 0))
            # Alternative: check if it's already in _internal from PyInstaller
            existing_dll = list(internal_dir.glob(f"python*.dll"))
            if existing_dll:
                print(f"  Note: Found existing Python DLL in _internal: {existing_dll[0].name}")

        # Copy vcruntime140.dll - required for python.exe to run
        vcruntime_src = python_src.parent / "vcruntime140.dll"
        if vcruntime_src.exists():
            vcruntime_dst = internal_dir / "vcruntime140.dll"
            shutil.copy(str(vcruntime_src), str(vcruntime_dst))
            print(f"  Copied: _internal/vcruntime140.dll")
        else:
            # Check if already exists in _internal (PyInstaller may have copied it)
            if not (internal_dir / "vcruntime140.dll").exists():
                print(f"  Warning: vcruntime140.dll not found - python.exe may not run")

        # Create standard Python directory structure: Lib/site-packages
        print("Creating standard Python directory structure...")
        lib_dir = internal_dir / "Lib"
        site_packages_dir = lib_dir / "site-packages"
        site_packages_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Created: _internal/Lib/site-packages/")

        # Copy entire site-packages from Python installation
        print("Copying site-packages from Python installation...")
        import site
        python_site_packages = site.getsitepackages()
        copied_count = 0
        for sp_path in python_site_packages:
            sp_path = Path(sp_path)
            if sp_path.exists() and sp_path.is_dir():
                print(f"  Copying from: {sp_path}")
                for item in sp_path.iterdir():
                    dest = site_packages_dir / item.name
                    try:
                        if item.is_dir():
                            if dest.exists():
                                shutil.rmtree(dest)
                            shutil.copytree(str(item), str(dest))
                        else:
                            shutil.copy2(str(item), str(dest))
                        copied_count += 1
                    except Exception as e:
                        print(f"    Warning: Could not copy {item.name}: {e}")
        print(f"  Copied {copied_count} items to Lib/site-packages/")

        # Also copy standard library (Lib folder) from Python installation
        print("Copying standard library from Python installation...")
        python_lib_dir = Path(sys.executable).parent / "Lib"
        if python_lib_dir.exists():
            stdlib_count = 0
            for item in python_lib_dir.iterdir():
                # Skip site-packages (already copied) and __pycache__
                if item.name in ['site-packages', '__pycache__', 'test', 'tests']:
                    continue
                dest = lib_dir / item.name
                try:
                    if item.is_dir():
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(str(item), str(dest), ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'test', 'tests'))
                    else:
                        shutil.copy2(str(item), str(dest))
                    stdlib_count += 1
                except Exception as e:
                    print(f"    Warning: Could not copy {item.name}: {e}")
            print(f"  Copied {stdlib_count} standard library items to Lib/")

        # Copy DLLs folder from Python installation
        print("Copying DLLs from Python installation...")
        python_dlls_dir = Path(sys.executable).parent / "DLLs"
        dlls_dest = internal_dir / "DLLs"
        if python_dlls_dir.exists():
            if dlls_dest.exists():
                shutil.rmtree(dlls_dest)
            shutil.copytree(str(python_dlls_dir), str(dlls_dest))
            print(f"  Copied DLLs/ directory")

        # Create python._pth file to configure Python's module search paths
        # Note: When python._pth exists, PYTHONPATH is ignored, but we can add paths at runtime
        print("Creating python._pth file for embedded Python...")
        python_version = f"{sys.version_info.major}{sys.version_info.minor}"
        pth_file = internal_dir / f"python{python_version}._pth"
        pth_content = """# Python path configuration for TCE Launcher
# Paths are relative to the directory containing python.exe
.
Lib
Lib/site-packages
DLLs

# Import site to enable .pth file processing in site-packages
import site
"""
        with open(pth_file, 'w') as f:
            f.write(pth_content)
        print(f"  Created: _internal/python{python_version}._pth")

        print()
        print("Verifying dependencies...")
        # Verify that all scanned dependencies are included
        missing_deps = []
        for dep in sorted(app_dependencies):
            # Check in site-packages (directories)
            dep_in_site = site_packages_dir / dep
            # Check for .pyd files in _internal root
            dep_pyd = list(internal_dir.glob(f"{dep}*.pyd"))
            # Check in _internal root (directories that weren't moved)
            dep_in_root = internal_dir / dep

            if not (dep_in_site.exists() or dep_pyd or dep_in_root.exists()):
                missing_deps.append(dep)

        if missing_deps:
            print(f"  Warning: {len(missing_deps)} dependencies may be missing:")
            for dep in missing_deps[:10]:  # Show first 10
                print(f"    - {dep}")
            if len(missing_deps) > 10:
                print(f"    ... and {len(missing_deps) - 10} more")
            print("  Note: Some may be included differently or be part of other packages.")
        else:
            print(f"  All {len(app_dependencies)} dependencies appear to be included.")

        print()
        print("=" * 70)
        print("COMPILATION SUCCESSFUL!")
        print("=" * 70)
        print(f"Output directory: {output_dir}")
        print()
        print("Directory structure:")
        print("  TCE Launcher/")
        print("    TCE Launcher.exe       - Main application")
        print("    data/                  - Applications, games, components")
        print("    languages/             - Translation files")
        print("    sfx/                   - Sound themes")
        print("    skins/                 - UI skins")
        print("    _internal/             - Runtime libraries (all dependencies)")
        print("      python.exe           - Python interpreter for apps/games")
        print("      pythonw.exe          - Python interpreter (no console)")
        print()
        print("Features:")
        print(f"  - {len(app_dependencies)} external dependencies auto-detected and included")
        print("  - Applications/games run via python.exe subprocess (proper isolation)")
        print("  - pythonw.exe used for windowless execution (no console)")
        print("  - All libraries available to Python scripts from _internal")
        print("  - No external Python installation required")
        print()
        print("How it works:")
        print("  - Applications (.py files) run via pythonw.exe (no console window)")
        print("  - All dependencies from _internal are available via PYTHONPATH")
        print("  - Each app/game runs in separate process for proper isolation")
        print()
        print("To run the compiled application:")
        print(f"  {output_dir / 'TCE Launcher.exe'}")
    else:
        print()
        print("=" * 50)
        print("COMPILATION FAILED!")
        print("=" * 50)
        sys.exit(1)

if __name__ == "__main__":
    compile_to_release()

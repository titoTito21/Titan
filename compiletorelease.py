"""
TCE Launcher Compilation Script
Compiles the application to a directory structure using PyInstaller.
Supports Windows, macOS, and Linux builds.
Apps/games run as subprocesses with _internal/python.exe and have access
to full site-packages, so their dependencies don't need hidden imports.
"""

import subprocess
import sys
import shutil
import os
import platform
from pathlib import Path

IS_WINDOWS = platform.system() == 'Windows'
IS_MACOS = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'

# PyInstaller --add-data separator differs by platform
DATA_SEP = ';' if IS_WINDOWS else ':'


def compile_to_release():
    """Compile TCE Launcher to a directory distribution."""

    # Paths
    root_dir = Path(__file__).parent
    dist_dir = root_dir / "dist"
    build_dir = root_dir / "build"

    print("=" * 70)
    print("TCE Launcher - PyInstaller Compilation")
    print("=" * 70)
    print()

    # Remove old dist directory permanently (no recycle bin)
    if dist_dir.exists():
        print("Removing old dist/ directory...")
        shutil.rmtree(dist_dir)
        print("  Removed.")
        print()

    # Data directories to include
    data_dirs = [
        ("data", "data"),
        ("languages", "languages"),
        ("sfx", "sfx"),
        ("skins", "skins"),
        ("src", "src"),  # Source modules for app/game subprocess access (stays in _internal/)
    ]

    # Preflight: detect webrtcvad availability and warn early.
    # The PyInstaller-contrib hook for webrtcvad calls copy_metadata('webrtcvad')
    # and aborts the build with PackageNotFoundError when only the alternate
    # 'webrtcvad-wheels' distribution is installed (typical on Python 3.13+).
    # Our local hook in pyinstaller_hooks/ overrides this, but if neither
    # variant is importable Titan-Net voice will be broken at runtime - say so.
    try:
        import webrtcvad  # noqa: F401
        print("Preflight: webrtcvad is importable.")
    except ImportError:
        print("Preflight WARNING: webrtcvad is NOT installed. Titan-Net voice "
              "will fall back to continuous mode. To install on Python 3.13+ "
              "use: pip install webrtcvad-wheels")

    # Local PyInstaller hooks override broken contrib hooks (e.g. webrtcvad).
    local_hooks_dir = root_dir / "pyinstaller_hooks"

    # Build the PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",  # Output as directory, not single file
        "--windowed",  # No console window
        "--name", "TCE Launcher",
        "--noconfirm",  # Overwrite without asking
    ]

    if local_hooks_dir.is_dir():
        cmd.extend(["--additional-hooks-dir", str(local_hooks_dir)])

    # Add icon if exists (platform-specific format)
    if IS_WINDOWS and (root_dir / "icon.ico").exists():
        cmd.extend(["--icon", "icon.ico"])
    elif IS_MACOS and (root_dir / "icon.icns").exists():
        cmd.extend(["--icon", "icon.icns"])
    elif (root_dir / "icon.ico").exists():
        cmd.extend(["--icon", "icon.ico"])

    # macOS-specific options
    if IS_MACOS:
        cmd.extend(["--osx-bundle-identifier", "com.titosoft.tce-launcher"])

    # Add data directories
    for src, dst in data_dirs:
        src_path = root_dir / src
        if src_path.exists():
            cmd.extend(["--add-data", f"{src}{DATA_SEP}{dst}"])

    print("Step 1: Building PyInstaller command...")
    print("-" * 70)

    # Comprehensive hidden imports for all TCE dependencies
    hidden_imports = [
        # Core accessibility
        "accessible_output3",
        "accessible_output3.outputs",
        "accessible_output3.outputs.auto",

        # 3D positional audio (OpenAL Soft HRTF)
        "openal",
        "openal.al",
        "openal.alc",

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

        # Network
        "websockets",
        "websockets.client",
        "websockets.server",
        "aiohttp",
        "requests",

        # Async
        "asyncio",

        # Speech recognition
        "speech_recognition",

        # Keyboard/input
        "keyboard",

        # System
        "psutil",

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
        "src.platform_utils",
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
        "src.ui.window_switcher",
        "src.settings",
        "src.settings.settings",
        "src.settings.titan_im_config",
        "src.network",
        "src.network.titan_net",
        "src.network.titan_net_gui",
        "src.network.titan_net_forum_gui",
        "src.network.telegram_client",
        "src.network.telegram_gui",
        "src.network.telegram_windows",
        "src.network.telegram_voice",
        "src.network.messenger_client",
        "src.network.messenger_gui",
        "src.network.messenger_webview",
        "src.network.whatsapp_client",
        "src.network.whatsapp_webview",
        "src.network.run_messenger",
        "src.network.im_module_manager",
        "src.network.titanim_sound_api",
        "src.network.voice_capture",
        "src.network.voice_codec",
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
        "src.titan_core.spatial_audio",
        "src.titan_core.sound_calibration",
        "src.titan_core.tce_speech",
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

        # TTS engine system
        "src.tts",
        "src.tts.base_engine",
        "src.tts.engine_registry",

        # Accessibility
        "src.accessibility",
        "src.accessibility.messages",

        # Launcher, statusbar, skins
        "src.titan_core.launcher_manager",
        "src.titan_core.statusbar_applet_manager",
        "src.titan_core.skin_manager",

        # Elten Link
        "src.eltenlink_client",
        "src.eltenlink_client.elten_client",
        "src.eltenlink_client.elten_gui",
        "src.eltenlink_client.elten_player",
        "src.eltenlink_client.elten_voip_client",
        "src.eltenlink_client.accountmanagement",
    ]

    # Platform-specific hidden imports
    if IS_WINDOWS:
        hidden_imports.extend([
            # Screen reader outputs (Windows-specific)
            "accessible_output3.outputs.sapi5",
            "accessible_output3.outputs.nvda",
            "accessible_output3.outputs.jaws",
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
            # Audio control (Windows)
            "pycaw",
            "pycaw.pycaw",
            # Windows async
            "asyncio.windows_events",
            # Windows system
            "wmi",
            "pywinctl",
        ])

    print(f"Total hidden imports: {len(hidden_imports)}")
    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])

    # Collect all packages to ensure data files are included
    collect_packages = [
        "accessible_output3",
        "babel",
        "wx",
        "cryptography",  # Include Rust bindings (_rust modules)
        "openal",        # PyOpenAL: bundles soft_oal_64.dll (OpenAL Soft HRTF)
        "sounddevice",   # bundles PortAudio binary (3D room calibration mic capture)
    ]

    for pkg in collect_packages:
        cmd.extend(["--collect-all", pkg])

    # Main script
    cmd.append("main.py")

    print()
    print("Step 2: Running PyInstaller...")
    print("-" * 70)

    # Run PyInstaller
    result = subprocess.run(cmd, cwd=root_dir)

    if result.returncode == 0:
        print()
        print("Step 3: Post-processing...")
        print("-" * 70)
        print("Moving data directories for backward compatibility...")

        # Move data directories from _internal to main directory
        output_dir = dist_dir / "TCE Launcher"
        if IS_MACOS:
            # macOS .app bundle: output is in TCE Launcher.app
            app_bundle = dist_dir / "TCE Launcher.app"
            if app_bundle.exists():
                output_dir = app_bundle / "Contents" / "MacOS"
                internal_dir = output_dir / "_internal"
            else:
                internal_dir = output_dir / "_internal"
        else:
            internal_dir = output_dir / "_internal"

        dirs_to_move = ["data", "languages", "sfx", "skins"]

        for dir_name in dirs_to_move:
            src = internal_dir / dir_name
            dst = output_dir / dir_name
            if IS_MACOS and app_bundle.exists():
                # On macOS .app bundle, move resources to Contents/Resources/
                resources_dir = dist_dir / "TCE Launcher.app" / "Contents" / "Resources"
                resources_dir.mkdir(parents=True, exist_ok=True)
                dst = resources_dir / dir_name
            if src.exists():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.move(str(src), str(dst))
                print(f"  Moved: {dir_name}")

        # Copy Python interpreter to _internal
        print("Copying Python interpreter to _internal...")
        python_src = Path(sys.executable)

        if IS_WINDOWS:
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
                if not (internal_dir / "vcruntime140.dll").exists():
                    print(f"  Warning: vcruntime140.dll not found - python.exe may not run")
        else:
            # Linux/macOS: copy python3
            python_name = "python3"
            python_dst = internal_dir / python_name
            if python_src.exists():
                shutil.copy(str(python_src), str(python_dst))
                os.chmod(str(python_dst), 0o755)
                print(f"  Copied: _internal/{python_name}")

            # Copy libpythonX.Y shared library if needed
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
            if IS_LINUX:
                lib_names = [f"libpython{python_version}.so.1.0", f"libpython{python_version}.so"]
            else:  # macOS
                lib_names = [f"libpython{python_version}.dylib"]
            for lib_name in lib_names:
                lib_src = python_src.parent / lib_name
                if not lib_src.exists():
                    lib_src = python_src.parent.parent / "lib" / lib_name
                if lib_src.exists():
                    shutil.copy(str(lib_src), str(internal_dir / lib_name))
                    print(f"  Copied: _internal/{lib_name}")
                    break

        # Create standard Python directory structure: Lib/site-packages
        print("Creating standard Python directory structure...")
        lib_dir = internal_dir / "Lib"
        site_packages_dir = lib_dir / "site-packages"
        site_packages_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Created: _internal/Lib/site-packages/")

        # Ask whether to copy site-packages
        copy_site_packages = input("Do you want to copy site-packages? (y/n): ").strip().lower() == 'y'

        if copy_site_packages:
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
        else:
            print("Skipping site-packages copy.")

        # Also copy standard library (Lib folder) from Python installation
        print("Copying standard library from Python installation...")
        if IS_WINDOWS:
            python_lib_dir = Path(sys.executable).parent / "Lib"
        else:
            python_lib_dir = Path(sys.executable).parent.parent / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
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

        if IS_WINDOWS:
            # Copy DLLs folder from Python installation
            print("Copying DLLs from Python installation...")
            python_dlls_dir = Path(sys.executable).parent / "DLLs"
            dlls_dest = internal_dir / "DLLs"
            if python_dlls_dir.exists():
                if dlls_dest.exists():
                    shutil.rmtree(dlls_dest)
                shutil.copytree(str(python_dlls_dir), str(dlls_dest))
                print(f"  Copied DLLs/ directory")

        # Create path configuration file
        if IS_WINDOWS:
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

        # Remove any Telegram/Telethon session files that may have been bundled
        # These contain developer credentials and MUST NOT be distributed
        print("Removing sensitive session files from distribution...")
        session_removed = 0
        for root, dirs, files in os.walk(str(output_dir)):
            for f in files:
                if any(f.endswith(s) for s in ('.session', '.session-journal', '.session-wal', '.session-shm')):
                    session_path = os.path.join(root, f)
                    os.remove(session_path)
                    session_removed += 1
                    print(f"  Removed: {os.path.relpath(session_path, output_dir)}")
        if session_removed:
            print(f"  Removed {session_removed} session file(s)")
        else:
            print("  No session files found (clean)")

        # Compile src/ to .pyc bytecode and remove .py source files
        # This protects source code while keeping modules importable by apps/games
        src_internal = internal_dir / "src"
        if src_internal.exists():
            print("Compiling src/ to bytecode (.pyc) and removing source files...")
            import compileall
            compileall.compile_dir(str(src_internal), force=True, quiet=1)

            # Move .pyc from __pycache__/ to parent dirs with simplified names.
            # Python's import system CANNOT find .pyc files in __pycache__/
            # when the source .py file is missing — SourceFileLoader requires
            # the .py file to exist. SourcelessFileLoader only finds .pyc files
            # placed directly in the package directory.
            pyc_moved = 0
            pycache_dirs = []
            for root, dirs, files in os.walk(str(src_internal)):
                pycache = os.path.join(root, '__pycache__')
                if os.path.isdir(pycache):
                    pycache_dirs.append(pycache)
                    for pyc_file in os.listdir(pycache):
                        if pyc_file.endswith('.pyc'):
                            # "module.cpython-312.pyc" -> "module.pyc"
                            parts = pyc_file.split('.')
                            if len(parts) >= 3 and 'cpython' in parts[-2]:
                                simple_name = '.'.join(parts[:-2]) + '.pyc'
                            else:
                                simple_name = pyc_file
                            src_pyc = os.path.join(pycache, pyc_file)
                            dst_pyc = os.path.join(root, simple_name)
                            shutil.move(src_pyc, dst_pyc)
                            pyc_moved += 1

            # Remove empty __pycache__ directories
            for pycache in pycache_dirs:
                shutil.rmtree(pycache, ignore_errors=True)

            # Remove .py source files
            py_removed = 0
            for root, dirs, files in os.walk(str(src_internal)):
                for f in files:
                    if f.endswith('.py'):
                        os.remove(os.path.join(root, f))
                        py_removed += 1
            print(f"  Compiled {py_removed} .py files, moved {pyc_moved} .pyc to package dirs")

        print()
        print("=" * 70)
        print("COMPILATION SUCCESSFUL!")
        print("=" * 70)
        print(f"Output directory: {output_dir}")
        print()

        if IS_WINDOWS:
            exe_name = "TCE Launcher.exe"
            python_names = "python.exe / pythonw.exe"
        elif IS_MACOS:
            exe_name = "TCE Launcher.app"
            python_names = "python3"
        else:
            exe_name = "TCE Launcher"
            python_names = "python3"

        print("Directory structure:")
        print(f"  TCE Launcher/")
        print(f"    {exe_name:<27s}- Main application")
        print(f"    data/                  - Applications, games, components")
        print(f"    languages/             - Translation files")
        print(f"    sfx/                   - Sound themes")
        print(f"    skins/                 - UI skins")
        print(f"    _internal/             - Runtime libraries (all dependencies)")
        print(f"      {python_names:<23s}- Python interpreter for apps/games")
        print()
        print("Features:")
        print(f"  - Applications/games run via {python_names} subprocess (proper isolation)")
        print("  - All libraries available to Python scripts from _internal/Lib/site-packages")
        print("  - No external Python installation required")
        print()
        print("To run the compiled application:")
        if IS_MACOS:
            print(f"  open {dist_dir / 'TCE Launcher.app'}")
        else:
            print(f"  {output_dir / exe_name}")
    else:
        print()
        print("=" * 50)
        print("COMPILATION FAILED!")
        print("=" * 50)
        sys.exit(1)

if __name__ == "__main__":
    compile_to_release()

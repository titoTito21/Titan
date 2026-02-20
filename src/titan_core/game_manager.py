import os
import subprocess
import threading
import sys
import platform
import webbrowser
from src.platform_utils import get_base_path, is_frozen, IS_WINDOWS, IS_LINUX, IS_MACOS

# Windows-only imports
if IS_WINDOWS:
    import winreg


PROJECT_ROOT = get_base_path()
GAME_DIR = os.path.join(PROJECT_ROOT, 'data', 'games')


def get_games():
    """Get all games: from data/games/ (Titan-Games) + Steam + Battle.net"""
    games = []

    # 1. Titan-Games from data/games/
    if os.path.exists(GAME_DIR):
        for game_folder in os.listdir(GAME_DIR):
            game_path = os.path.join(GAME_DIR, game_folder)
            if os.path.isdir(game_path):
                game_info = read_game_info(game_path)
                if game_info:
                    game_info['platform'] = game_info.get('platform', 'Titan-Games')
                    games.append(game_info)

    # 2. Steam games (from registry)
    try:
        steam_games = get_steam_games()
        games.extend(steam_games)
    except Exception as e:
        print(f"Error loading Steam games: {e}")

    # 3. Battle.net games (from registry)
    try:
        battlenet_games = get_battlenet_games()
        games.extend(battlenet_games)
    except Exception as e:
        print(f"Error loading Battle.net games: {e}")

    return games


def read_game_info(game_path):
    """Read game info from __game.tce or __game.TCE file."""
    # Check both lowercase and uppercase variants
    game_info_path = os.path.join(game_path, '__game.tce')
    if not os.path.exists(game_info_path):
        game_info_path = os.path.join(game_path, '__game.TCE')
    if not os.path.exists(game_info_path):
        return None

    game_info = {}
    try:
        with open(game_info_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                game_info[key.strip()] = value.strip().strip('"')
    except Exception as e:
        print(f"Error reading game info from {game_info_path}: {e}")
        return None

    game_info['path'] = game_path
    return game_info


def _parse_vdf_simple(filepath):
    """Simple VDF (Valve Data Format) parser for Steam config files."""
    result = {}
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        # Very basic key-value extraction from VDF format
        import re
        # Match "key" "value" patterns
        for match in re.finditer(r'"([^"]+)"\s+"([^"]*)"', content):
            result[match.group(1)] = match.group(2)
    except Exception as e:
        print(f"Error parsing VDF file {filepath}: {e}")
    return result


def _get_steam_library_paths():
    """Get Steam library folder paths on Linux/macOS."""
    paths = []

    if IS_LINUX:
        candidates = [
            os.path.expanduser('~/.steam/steam'),
            os.path.expanduser('~/.local/share/Steam'),
        ]
    elif IS_MACOS:
        candidates = [
            os.path.expanduser('~/Library/Application Support/Steam'),
        ]
    else:
        return paths

    for base in candidates:
        steamapps = os.path.join(base, 'steamapps')
        if os.path.isdir(steamapps):
            paths.append(steamapps)
            # Check libraryfolders.vdf for additional library paths
            lf_path = os.path.join(steamapps, 'libraryfolders.vdf')
            if os.path.exists(lf_path):
                vdf = _parse_vdf_simple(lf_path)
                for key, value in vdf.items():
                    if key == 'path' or key.isdigit():
                        extra_steamapps = os.path.join(value, 'steamapps') if not value.endswith('steamapps') else value
                        if os.path.isdir(extra_steamapps) and extra_steamapps not in paths:
                            paths.append(extra_steamapps)
            break  # Found main Steam dir

    return paths


def _get_steam_games_from_manifests(steamapps_dirs):
    """Parse appmanifest_*.acf files to get installed Steam games."""
    import re
    games = []
    seen_ids = set()

    for steamapps_dir in steamapps_dirs:
        try:
            for filename in os.listdir(steamapps_dir):
                if not filename.startswith('appmanifest_') or not filename.endswith('.acf'):
                    continue
                manifest_path = os.path.join(steamapps_dir, filename)
                data = _parse_vdf_simple(manifest_path)
                app_id = data.get('appid', '')
                name = data.get('name', '')

                if app_id and name and app_id not in seen_ids:
                    seen_ids.add(app_id)
                    games.append({
                        'name': name,
                        'platform': 'Steam',
                        'app_id': app_id,
                        'launch_url': f'steam://rungameid/{app_id}'
                    })
        except Exception as e:
            print(f"Error reading Steam manifests from {steamapps_dir}: {e}")

    return games


def get_steam_games():
    """Detect installed Steam games (Windows: registry, Linux/macOS: manifest files)."""
    steam_games = []

    if IS_WINDOWS:
        try:
            # Try to read Steam path from registry
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
                steam_path = winreg.QueryValueEx(key, "SteamPath")[0]
                winreg.CloseKey(key)
            except:
                steam_path = r"C:\Program Files (x86)\Steam"

            # Read installed games from registry
            try:
                apps_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\Apps")
                i = 0
                while True:
                    try:
                        app_id = winreg.EnumKey(apps_key, i)

                        try:
                            app_key = winreg.OpenKey(apps_key, app_id)
                            installed = winreg.QueryValueEx(app_key, "Installed")[0]

                            if installed == 1:
                                try:
                                    name = winreg.QueryValueEx(app_key, "Name")[0]
                                except:
                                    name = f"Steam Game {app_id}"

                                steam_games.append({
                                    'name': name,
                                    'platform': 'Steam',
                                    'app_id': app_id,
                                    'launch_url': f'steam://rungameid/{app_id}'
                                })

                            winreg.CloseKey(app_key)
                        except:
                            pass

                        i += 1
                    except OSError:
                        break

                winreg.CloseKey(apps_key)
            except Exception as e:
                print(f"Error reading Steam games: {e}")

        except Exception as e:
            print(f"Error accessing Steam registry: {e}")

    elif IS_LINUX or IS_MACOS:
        # Parse Steam manifest files on Linux/macOS
        try:
            library_paths = _get_steam_library_paths()
            steam_games = _get_steam_games_from_manifests(library_paths)
        except Exception as e:
            print(f"Error reading Steam games from manifests: {e}")

    return steam_games


def get_battlenet_games():
    """Detect installed Battle.net games (Windows: registry, Linux/macOS: known paths)."""
    battlenet_games = []

    if IS_WINDOWS:
        try:
            uninstall_paths = [
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
            ]

            for uninstall_path in uninstall_paths:
                try:
                    uninstall_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, uninstall_path)
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(uninstall_key, i)
                            subkey = winreg.OpenKey(uninstall_key, subkey_name)

                            try:
                                display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                                publisher = ""
                                try:
                                    publisher = winreg.QueryValueEx(subkey, "Publisher")[0]
                                except:
                                    pass

                                if "Blizzard" in publisher or "Battle.net" in display_name:
                                    install_location = ""
                                    try:
                                        install_location = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                                    except:
                                        pass

                                    if install_location and os.path.exists(install_location):
                                        product_code = subkey_name.split('_')[-1] if '_' in subkey_name else "launch"

                                        battlenet_games.append({
                                            'name': display_name,
                                            'platform': 'Battle.net',
                                            'path': install_location,
                                            'product_code': product_code,
                                            'launch_url': f'battlenet://launch'
                                        })

                            except:
                                pass

                            winreg.CloseKey(subkey)
                            i += 1
                        except OSError:
                            break

                    winreg.CloseKey(uninstall_key)
                except:
                    pass

        except Exception as e:
            print(f"Error accessing Battle.net registry: {e}")

    elif IS_MACOS:
        # Check macOS Applications folder for Blizzard games
        blizzard_apps = {
            'World of Warcraft': '/Applications/World of Warcraft',
            'Diablo III': '/Applications/Diablo III',
            'Diablo IV': '/Applications/Diablo IV',
            'Overwatch 2': '/Applications/Overwatch 2',
            'Hearthstone': '/Applications/Hearthstone',
            'StarCraft II': '/Applications/StarCraft II',
            'Heroes of the Storm': '/Applications/Heroes of the Storm',
        }
        for name, path in blizzard_apps.items():
            if os.path.exists(path) or os.path.exists(path + '.app'):
                battlenet_games.append({
                    'name': name,
                    'platform': 'Battle.net',
                    'path': path if os.path.exists(path) else path + '.app',
                    'launch_url': 'battlenet://launch'
                })

    # Linux: Battle.net typically runs via Wine/Lutris - not reliably detectable

    return battlenet_games


def get_games_by_platform():
    """Returns dict: {'Steam': [games...], 'Battle.net': [games...], 'Titan-Games': [games...]}"""
    all_games = get_games()
    grouped = {}

    for game in all_games:
        plat = game.get('platform', 'Titan-Games')
        if plat not in grouped:
            grouped[plat] = []
        grouped[plat].append(game)

    # Sort games within each platform
    for plat in grouped:
        grouped[plat].sort(key=lambda g: g.get('name', '').lower())

    return grouped


def get_python_executable():
    """
    Get Python executable path.
    In frozen mode, uses pythonw.exe/python3 from _internal directory.
    In development mode, uses current Python interpreter.

    Returns:
        Tuple of (python_path, error_message). If python_path is None, error_message contains the reason.
    """
    from src.platform_utils import get_python_executable_name

    if is_frozen():
        exe_dir = os.path.dirname(sys.executable)
        internal_dir = os.path.join(exe_dir, '_internal')

        if not os.path.exists(internal_dir):
            return (None, f"Internal directory not found: {internal_dir}")

        gui_name, console_name = get_python_executable_name()

        # Prefer GUI variant (no console window on Windows)
        gui_exe = os.path.join(internal_dir, gui_name)
        if os.path.exists(gui_exe):
            return (gui_exe, None)

        # Fallback to console variant
        console_exe = os.path.join(internal_dir, console_name)
        if os.path.exists(console_exe):
            return (console_exe, None)

        return (None, f"Python interpreter not found in: {internal_dir}")
    else:
        return (sys.executable, None)


def find_executable_file(base_path, openfile):
    """
    Find the best executable file for the game.
    Priority: .pyd/.so (Cython) > .pyc > .py > .exe
    Returns tuple: (full_path, file_type)
    """
    game_path = os.path.join(base_path, openfile)
    base_name = os.path.splitext(game_path)[0]

    cython_ext = '.pyd' if sys.platform == 'win32' else '.so'

    # Check for Cython compiled module first
    cython_file = base_name + cython_ext
    if os.path.exists(cython_file):
        return (cython_file, 'cython')

    # Check for .pyc
    pyc_file = base_name + '.pyc'
    if os.path.exists(pyc_file):
        return (pyc_file, 'pyc')

    # Check for .py
    py_file = base_name + '.py'
    if os.path.exists(py_file):
        return (py_file, 'py')

    # Check for executable
    if sys.platform == 'win32':
        exe_file = base_name + '.exe'
        if os.path.exists(exe_file):
            return (exe_file, 'exe')
    else:
        if os.path.exists(base_name) and os.access(base_name, os.X_OK):
            return (base_name, 'exe')

    # Check if original file exists as-is
    if os.path.exists(game_path):
        ext = os.path.splitext(openfile)[1].lower()
        if ext == cython_ext:
            return (game_path, 'cython')
        elif ext == '.pyc':
            return (game_path, 'pyc')
        elif ext == '.py':
            return (game_path, 'py')
        elif ext == '.exe' or (ext == '' and os.access(game_path, os.X_OK)):
            return (game_path, 'exe')

    return (None, None)


def open_game(game_info):
    """Open a game - handles Titan-Games (.exe/.py/.pyd/.so), Steam (steam://), Battle.net (battlenet://)"""
    def run_game():
        # Steam and Battle.net - use protocol
        if 'launch_url' in game_info:
            launch_url = game_info['launch_url']
            webbrowser.open(launch_url)
            return

        # Titan-Games - find best executable
        openfile = game_info.get('openfile', '')
        if not openfile:
            print(f"No openfile specified for game")
            return

        exec_file, file_type = find_executable_file(game_info['path'], openfile)

        if exec_file is None:
            print(f"Game file not found: {openfile}")
            return

        game_path = game_info['path']

        if file_type == 'exe':
            # Standalone executable
            _run_executable(exec_file, game_path)
        elif file_type in ['py', 'pyc', 'cython']:
            # Python files
            _run_python_file(exec_file, game_path, file_type)
        else:
            print(f"Unsupported file type: {file_type}")

    game_thread = threading.Thread(target=run_game, daemon=True)
    game_thread.start()


def _run_executable(exec_file, cwd):
    """Run a standalone executable."""
    # Run executable normally - it's responsible for its own console/GUI behavior
    subprocess.Popen([exec_file], cwd=cwd)


def _run_python_file(exec_file, game_path, file_type):
    """
    Run a Python file using the appropriate interpreter.

    Supports:
    - .py files: executed with exec(compile(...))
    - .pyc files: executed directly with python
    - .pyd/.so (Cython): imported as module and main() called
    """
    python_executable, python_error = get_python_executable()

    if python_executable is None:
        print(f"Cannot run game: {python_error}")
        return

    env = os.environ.copy()

    # Build paths to add (ensure no trailing slashes to avoid syntax errors in raw strings)
    paths_to_add = [p.rstrip('\\/') for p in [game_path, PROJECT_ROOT] if p]

    if is_frozen():
        # Compiled mode
        internal_dir = os.path.join(os.path.dirname(sys.executable), '_internal')
        dlls_path = os.path.join(internal_dir, 'DLLs')

        # DON'T set PYTHONHOME - it conflicts with python3XX._pth file
        # The ._pth file handles module search paths

        # Add to PATH for DLL loading
        env['PATH'] = os.pathsep.join([internal_dir, dlls_path, env.get('PATH', '')])

        # Build code based on file type
        paths_code = '; '.join([f"sys.path.insert(0, r'{p}')" for p in paths_to_add])

        if file_type == 'cython':
            # Cython modules (.pyd/.so) - import and call main()
            module_name = os.path.splitext(os.path.basename(exec_file))[0]
            code = f"import sys; {paths_code}; sys.argv = [r'{exec_file}']; import {module_name}; {module_name}.main() if hasattr({module_name}, 'main') else None"
        elif file_type == 'pyc':
            # .pyc files - use runpy.run_path() to execute as __main__
            code = f"import sys; {paths_code}; sys.argv = [r'{exec_file}']; import runpy; runpy.run_path(r'{exec_file}', run_name='__main__')"
        else:
            # .py files - use exec(compile(...))
            code = f"import sys; {paths_code}; sys.argv = [r'{exec_file}']; exec(compile(open(r'{exec_file}', 'rb').read(), r'{exec_file}', 'exec'))"

        command = [python_executable, '-c', code]

        # pythonw.exe already runs without console, no need for special flags
        subprocess.Popen(command, cwd=game_path, env=env)
    else:
        # Development mode - show console for debugging
        env['PYTHONPATH'] = os.pathsep.join(filter(None, [
            game_path,
            PROJECT_ROOT,
            env.get('PYTHONPATH', '')
        ]))

        if file_type == 'cython':
            # Cython modules - import and call main()
            module_name = os.path.splitext(os.path.basename(exec_file))[0]
            code = f"import sys; sys.argv = [r'{exec_file}']; import {module_name}; {module_name}.main() if hasattr({module_name}, 'main') else None"
            command = [python_executable, '-c', code]
        elif file_type == 'pyc':
            # .pyc files - run directly with python
            command = [python_executable, exec_file]
        else:
            # .py files - run directly
            command = [python_executable, exec_file]

        # Show console window in development mode
        subprocess.Popen(command, cwd=game_path, env=env)

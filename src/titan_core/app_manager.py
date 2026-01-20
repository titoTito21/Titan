import os
import subprocess
import threading
import sys
import wx
import importlib.util
from src.settings import settings
from src.titan_core.sound import play_sound, play_error_sound, play_dialog_sound, play_dialogclose_sound, resource_path
from src.titan_core.translation import language_code, _


APP_DIR = resource_path(os.path.join('data', 'applications'))
SITEPACKAGES_DIR = resource_path(os.path.join('data', 'Titan', 'python_interpreter', 'sitepackages'))

# Ensure the sitepackages directory exists
if not os.path.exists(SITEPACKAGES_DIR):
    os.makedirs(SITEPACKAGES_DIR)


def is_frozen():
    """Check if running in compiled mode (PyInstaller/Nuitka)."""
    return getattr(sys, 'frozen', False)


def get_applications():
    """Get list of all visible applications."""
    lang = language_code
    applications = []

    if not os.path.exists(APP_DIR):
        return applications

    for app_folder in os.listdir(APP_DIR):
        app_path = os.path.join(APP_DIR, app_folder)
        if os.path.isdir(app_path) and app_folder != '.DS_Store':
            app_info = read_app_info(app_path, lang)
            if app_info and not app_info.get('hidden', 'false').lower() == 'true':
                applications.append(app_info)
    return applications


def get_hidden_applications():
    """Get list of hidden applications."""
    lang = language_code
    hidden_applications = []

    if not os.path.exists(APP_DIR):
        return hidden_applications

    for app_folder in os.listdir(APP_DIR):
        app_path = os.path.join(APP_DIR, app_folder)
        if os.path.isdir(app_path) and app_folder != '.DS_Store':
            app_info = read_app_info(app_path, lang)
            if app_info and app_info.get('hidden', 'false').lower() == 'true':
                hidden_applications.append(app_info)
    return hidden_applications


def read_app_info(app_path, lang='pl'):
    """Read application info from __app.tce or __app.TCE file."""
    # Check both lowercase and uppercase variants
    app_info_path = os.path.join(app_path, '__app.tce')
    if not os.path.exists(app_info_path):
        app_info_path = os.path.join(app_path, '__app.TCE')
    if not os.path.exists(app_info_path):
        return None

    app_info = {}
    try:
        with open(app_info_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                app_info[key.strip()] = value.strip().strip('"')
    except Exception as e:
        print(f"Error reading app info from {app_info_path}: {e}")
        return None

    # Select translated name
    app_info['name'] = app_info.get(f'name_{lang}', app_info.get('name_en', app_info.get('name', '')))
    app_info['path'] = app_path
    return app_info


def find_application_by_shortname(shortname):
    """Search for applications by shortname including hidden ones."""
    for app in get_applications() + get_hidden_applications():
        if app.get('shortname') == shortname:
            return app
    return None


def _debug_log(message):
    """Write debug message to log file for troubleshooting compiled version."""
    try:
        if is_frozen():
            log_path = os.path.join(os.path.dirname(sys.executable), 'app_manager_debug.log')
        else:
            log_path = os.path.join(os.path.dirname(__file__), 'app_manager_debug.log')
        with open(log_path, 'a', encoding='utf-8') as f:
            import datetime
            f.write(f"[{datetime.datetime.now()}] {message}\n")
    except:
        pass


def get_python_executable():
    """
    Get Python executable path.
    In frozen mode, uses pythonw.exe (GUI, no console) from _internal directory.
    In development mode, uses current Python interpreter.

    Returns:
        Tuple of (python_path, error_message). If python_path is None, error_message contains the reason.
    """
    _debug_log(f"get_python_executable called, is_frozen={is_frozen()}")
    _debug_log(f"sys.executable={sys.executable}")

    if is_frozen():
        # In compiled mode, use pythonw.exe from _internal directory (GUI apps, no console)
        exe_dir = os.path.dirname(sys.executable)
        internal_dir = os.path.join(exe_dir, '_internal')

        _debug_log(f"exe_dir={exe_dir}")
        _debug_log(f"internal_dir={internal_dir}")
        _debug_log(f"internal_dir exists={os.path.exists(internal_dir)}")

        if not os.path.exists(internal_dir):
            _debug_log(f"ERROR: Internal directory not found")
            return (None, f"Internal directory not found: {internal_dir}")

        # Prefer pythonw.exe for GUI applications (no console window)
        pythonw_exe = os.path.join(internal_dir, 'pythonw.exe')
        if os.path.exists(pythonw_exe):
            _debug_log(f"SUCCESS: Found pythonw.exe")
            return (pythonw_exe, None)

        # Fallback to python.exe if pythonw.exe not found
        python_exe = os.path.join(internal_dir, 'python.exe')
        _debug_log(f"python_exe={python_exe}")
        _debug_log(f"python_exe exists={os.path.exists(python_exe)}")

        if os.path.exists(python_exe):
            _debug_log(f"SUCCESS: Found python.exe (fallback)")
            return (python_exe, None)

        _debug_log(f"ERROR: Python interpreter not found")
        return (None, f"Python interpreter not found: {python_exe}")
    else:
        # Development mode - use current Python interpreter
        _debug_log(f"Development mode, using sys.executable")
        return (sys.executable, None)


def find_executable_file(base_path, openfile):
    """
    Find the best executable file for the application.
    Priority: .pyd/.so (Cython) > .pyc > .py > .exe
    Returns tuple: (full_path, file_type)
    """
    app_path = os.path.join(base_path, openfile)
    base_name = os.path.splitext(app_path)[0]

    # Cython extension
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

    # Check for .exe
    exe_file = base_name + '.exe'
    if os.path.exists(exe_file):
        return (exe_file, 'exe')

    # Check if original file exists as-is
    if os.path.exists(app_path):
        ext = os.path.splitext(openfile)[1].lower()
        if ext == cython_ext:
            return (app_path, 'cython')
        elif ext == '.pyc':
            return (app_path, 'pyc')
        elif ext == '.py':
            return (app_path, 'py')
        elif ext == '.exe':
            return (app_path, 'exe')

    return (None, None)


def open_application(app_info, file_path=None):
    """Open an application. Runs in a separate thread."""
    def run_app():
        try:
            app_path = app_info['path']
            openfile = app_info.get('openfile', '')

            if not openfile:
                play_error_sound()
                wx.CallAfter(wx.MessageBox, _('No openfile specified for application'), _("Error"), wx.OK | wx.ICON_ERROR)
                return

            # Find the executable file
            exec_file, file_type = find_executable_file(app_path, openfile)

            if exec_file is None:
                play_error_sound()
                wx.CallAfter(wx.MessageBox, _('Application file not found: {}').format(openfile), _("Error"), wx.OK | wx.ICON_ERROR)
                return

            # Set language environment variable
            os.environ['LANG'] = language_code

            if file_type == 'exe':
                # Standalone executable - run directly
                _run_executable(exec_file, app_path)
            elif file_type in ['py', 'pyc', 'cython']:
                # Python files - run with python interpreter
                _run_python_file(exec_file, app_path, file_type, file_path)
            else:
                play_error_sound()
                wx.CallAfter(wx.MessageBox, _('Unsupported file type: {}').format(file_type), _("Error"), wx.OK | wx.ICON_ERROR)

        except Exception as e:
            play_error_sound()
            wx.CallAfter(wx.MessageBox, _('Error running application: {}').format(str(e)), _("Error"), wx.OK | wx.ICON_ERROR)
            import traceback
            traceback.print_exc()

    app_thread = threading.Thread(target=run_app, daemon=True)
    app_thread.start()


def _run_executable(exec_file, cwd):
    """Run a standalone executable."""
    startupinfo = None
    creationflags = 0

    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW

    subprocess.Popen([exec_file], cwd=cwd, startupinfo=startupinfo, creationflags=creationflags)


def _run_python_file(exec_file, app_path, file_type, file_path=None):
    """
    Run a Python file using the appropriate interpreter.

    Supports:
    - .py files: executed with exec(compile(...))
    - .pyc files: executed directly with python
    - .pyd/.so (Cython): imported as module and main() called
    """
    python_executable, python_error = get_python_executable()

    if python_executable is None:
        play_error_sound()
        wx.CallAfter(wx.MessageBox, _('Cannot run application: {}').format(python_error), _("Error"), wx.OK | wx.ICON_ERROR)
        return

    # Prepare environment
    env = os.environ.copy()

    # Get launcher root path (strip trailing backslash to avoid syntax errors in raw strings)
    launcher_path = resource_path('').rstrip('\\/')

    # Build paths to add (ensure no trailing slashes)
    paths_to_add = [p.rstrip('\\/') for p in [app_path, launcher_path, SITEPACKAGES_DIR] if p]

    if is_frozen():
        # Compiled mode - need special handling
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
            if file_path:
                code = f"import sys; {paths_code}; sys.argv = [r'{exec_file}', r'{file_path}']; import {module_name}; {module_name}.main() if hasattr({module_name}, 'main') else None"
            else:
                code = f"import sys; {paths_code}; sys.argv = [r'{exec_file}']; import {module_name}; {module_name}.main() if hasattr({module_name}, 'main') else None"
        elif file_type == 'pyc':
            # .pyc files - use runpy.run_path() to execute as __main__
            if file_path:
                code = f"import sys; {paths_code}; sys.argv = [r'{exec_file}', r'{file_path}']; import runpy; runpy.run_path(r'{exec_file}', run_name='__main__')"
            else:
                code = f"import sys; {paths_code}; sys.argv = [r'{exec_file}']; import runpy; runpy.run_path(r'{exec_file}', run_name='__main__')"
        else:
            # .py files - use exec(compile(...))
            if file_path:
                code = f"import sys; {paths_code}; sys.argv = [r'{exec_file}', r'{file_path}']; exec(compile(open(r'{exec_file}', 'rb').read(), r'{exec_file}', 'exec'))"
            else:
                code = f"import sys; {paths_code}; sys.argv = [r'{exec_file}']; exec(compile(open(r'{exec_file}', 'rb').read(), r'{exec_file}', 'exec'))"

        command = [python_executable, '-c', code]

        _debug_log(f"Running command: {command}")
        _debug_log(f"Working dir: {app_path}")
        _debug_log(f"PYTHONHOME: {env.get('PYTHONHOME', 'not set')}")
        _debug_log(f"PYTHONPATH: {env.get('PYTHONPATH', 'not set')}")

        # pythonw.exe already runs without console, no need for special flags
        try:
            proc = subprocess.Popen(command, cwd=app_path, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Don't wait, but log if there's immediate error
            import threading
            def log_output():
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                    if stderr:
                        _debug_log(f"STDERR: {stderr.decode('utf-8', errors='replace')}")
                    if stdout:
                        _debug_log(f"STDOUT: {stdout.decode('utf-8', errors='replace')}")
                    _debug_log(f"Return code: {proc.returncode}")
                except subprocess.TimeoutExpired:
                    _debug_log("Process still running after 5s (normal for GUI apps)")
                except Exception as e:
                    _debug_log(f"Error getting output: {e}")
            threading.Thread(target=log_output, daemon=True).start()
        except Exception as e:
            _debug_log(f"ERROR starting process: {e}")
    else:
        # Development mode - run normally with visible console for debugging
        env['PYTHONPATH'] = os.pathsep.join(filter(None, [
            app_path,
            launcher_path,
            SITEPACKAGES_DIR,
            env.get('PYTHONPATH', '')
        ]))

        if file_type == 'cython':
            # Cython modules - import and call main()
            module_name = os.path.splitext(os.path.basename(exec_file))[0]
            if file_path:
                code = f"import sys; sys.argv = [r'{exec_file}', r'{file_path}']; import {module_name}; {module_name}.main() if hasattr({module_name}, 'main') else None"
            else:
                code = f"import sys; sys.argv = [r'{exec_file}']; import {module_name}; {module_name}.main() if hasattr({module_name}, 'main') else None"
            command = [python_executable, '-c', code]
        elif file_type == 'pyc':
            # .pyc files - run directly with python (Python handles .pyc natively)
            command = [python_executable, exec_file]
            if file_path:
                command.append(file_path)
        else:
            # .py files - run directly
            command = [python_executable, exec_file]
            if file_path:
                command.append(file_path)

        # In development mode, show console window so we can see errors
        subprocess.Popen(command, cwd=app_path, env=env)

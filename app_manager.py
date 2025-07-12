import os
import subprocess
import threading
import py_compile
import sys
import wx
import shutil
import importlib.util
import settings
from sound import play_sound, play_error_sound, play_dialog_sound, play_dialogclose_sound, resource_path
from translation import language_code


APP_DIR = resource_path(os.path.join('data', 'applications'))
SITEPACKAGES_DIR = resource_path(os.path.join('data', 'Titan', 'python_interpreter', 'sitepackages'))

# Ensure the sitepackages directory exists
if not os.path.exists(SITEPACKAGES_DIR):
    os.makedirs(SITEPACKAGES_DIR)

def get_applications():
    lang = language_code
    applications = []
    for app_folder in os.listdir(APP_DIR):
        app_path = os.path.join(APP_DIR, app_folder)
        if os.path.isdir(app_path) and app_folder != '.DS_Store':  # Ignore .DS_Store
            app_info = read_app_info(app_path, lang)
            if app_info and not app_info.get('hidden', 'false').lower() == 'true':
                applications.append(app_info)
    return applications

def read_app_info(app_path, lang='pl'):
    app_info_path = os.path.join(app_path, '__app.tce')
    if not os.path.exists(app_info_path):
        return None
    
    app_info = {}
    with open(app_info_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line or '=' not in line:
                continue
            key, value = line.split('=', 1)
            app_info[key.strip()] = value.strip().strip('"')
    
    # Wybierz tłumaczoną nazwę
    app_info['name'] = app_info.get(f'name_{lang}', app_info.get('name_en', app_info.get('name', '')))

    app_info['path'] = app_path
    return app_info

def compile_python_file(py_file):
    try:
        pyc_file = py_file + 'c'
        py_compile.compile(py_file, cfile=pyc_file)
        copy_missing_modules(py_file)
        return pyc_file
    except py_compile.PyCompileError as e:
        play_dialog_sound()
        show_compile_error_dialog(str(e))
        return None

def copy_missing_modules(py_file):
    with open(py_file, 'r') as f:
        lines = f.readlines()
        for line in lines:
            if line.startswith('import ') or line.startswith('from '):
                module_name = line.split()[1].split('.')[0]
                try:
                    spec = importlib.util.find_spec(module_name)
                    if spec is not None:
                        module_path = spec.origin
                        if module_path and 'site-packages' in module_path:
                            dest_path = os.path.join(SITEPACKAGES_DIR, os.path.basename(module_path))
                            if not os.path.exists(dest_path):
                                shutil.copy(module_path, dest_path)
                                # If it's a directory (like a package), copy all contents
                                if os.path.isdir(module_path):
                                    shutil.copytree(module_path, os.path.join(SITEPACKAGES_DIR, module_name))
                except ImportError:
                    print(f"Module {module_name} not found or cannot be imported.")

def show_compile_error_dialog(error_message):
    app = wx.App(False)
    dialog = wx.Dialog(None, wx.ID_ANY, "Błąd kompilacji aplikacji", size=(400, 300))

    vbox = wx.BoxSizer(wx.VERTICAL)
    error_text = wx.TextCtrl(dialog, wx.ID_ANY, error_message, style=wx.TE_MULTILINE | wx.TE_READONLY)
    vbox.Add(error_text, 1, wx.EXPAND | wx.ALL, 10)
    ok_button = wx.Button(dialog, wx.ID_OK, "OK")
    ok_button.Bind(wx.EVT_BUTTON, lambda event: on_dialog_close(event, dialog))
    vbox.Add(ok_button, 0, wx.ALIGN_CENTER | wx.ALL, 10)
    
    dialog.SetSizer(vbox)
    dialog.ShowModal()
    dialog.Destroy()
    play_dialogclose_sound()

def on_dialog_close(event, dialog):
    play_dialogclose_sound()
    dialog.EndModal(wx.ID_OK)

def is_frozen():
    return getattr(sys, 'frozen', False)

def get_python_executable():
    if is_frozen():
        # If we are running in a PyInstaller bundle, find the embedded python interpreter
        return os.path.join(os.path.dirname(sys.executable), 'python.exe' if sys.platform == 'win32' else 'python3')
    else:
        return sys.executable

def open_application(app_info, file_path=None):
    def run_app():
        lang = language_code
        app_file = os.path.join(app_info['path'], app_info['openfile'])
        
        # Set PYTHONPATH so the application can use local libraries, Titan Launcher modules, and sitepackages
        env = os.environ.copy()
        # Set the language for the subprocess
        env['LANG'] = lang
        launcher_path = os.path.dirname(os.path.abspath(__file__))
        app_path = app_info['path']
        env['PYTHONPATH'] = os.pathsep.join([
            app_path,
            launcher_path,
            SITEPACKAGES_DIR,
            env.get('PYTHONPATH', '')
        ])

        # Add directories to sys.path
        sys.path.append(app_path)
        sys.path.append(launcher_path)
        sys.path.append(SITEPACKAGES_DIR)

        python_executable = get_python_executable()

        try:
            command_to_run = None
            if app_file.endswith('.py'):
                pyc_file = app_file + 'c'
                if os.path.exists(pyc_file):
                    command_to_run = [python_executable, pyc_file]
                else:
                    compiled_file = compile_python_file(app_file)
                    if compiled_file:
                        command_to_run = [python_executable, compiled_file]
            elif app_file.endswith('.pyc'):
                command_to_run = [python_executable, app_file]
            elif app_file.endswith('.exe'):
                command_to_run = [app_file]

            if command_to_run:
                is_python_script = app_file.endswith(('.py', '.pyc'))
                
                if file_path:
                    command_to_run.append(file_path)
                
                current_env = env if is_python_script else None
                subprocess.run(command_to_run, cwd=app_info['path'], env=current_env)

        except Exception as e:
            play_error_sound()
            wx.MessageBox(f'Błąd podczas uruchamiania aplikacji: {str(e)}', 'Błąd', wx.OK | wx.ICON_ERROR)

    threading.Thread(target=run_app).start()

def find_application_by_shortname(shortname):
    # Search for applications by shortname including hidden ones
    for app in get_applications() + get_hidden_applications():
        if app.get('shortname') == shortname:
            return app
    return None

def get_hidden_applications():
    lang = language_code
    hidden_applications = []
    for app_folder in os.listdir(APP_DIR):
        app_path = os.path.join(APP_DIR, app_folder)
        if os.path.isdir(app_path) and app_folder != '.DS_Store':  # Ignore .DS_Store
            app_info = read_app_info(app_path, lang)
            if app_info and app_info.get('hidden', 'false').lower() == 'true':
                hidden_applications.append(app_info)
    return hidden_applications

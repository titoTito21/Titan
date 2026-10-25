# -*- coding: utf-8 -*-
"""Teaching Titan's application and game managers new languages, from outside.

Nothing in Titan is changed: this component is data beside Titan.exe, and the
whole point is that it can be installed from Titan-Net into a Titan that was
built before it existed. It works because both managers look their two
helpers up by NAME at the moment they launch something -
``find_executable_file(path, openfile)`` and ``_run_executable(file, cwd)`` -
so replacing those two names on the module reaches every way Titan opens a
program: the main window, the Invisible UI, Klango mode, the Start menu, the
shell, the AI, the Action API.

* ``find_executable_file`` answers a source file in a language this component
  knows as an ``'exe'`` - the one kind both managers start without asking
  anything further;
* ``_run_executable`` recognises that file and starts the host process
  instead, and hands back its pid, so ``note_process`` still records which
  process is which application.

Everything else falls through to Titan's own helper, unchanged.
"""

import os
import sys
import threading

from . import runtimes

COMPONENT_DIR = runtimes.COMPONENT_DIR
_MODULES = (('src.titan_core.app_manager', 'app'),
            ('src.titan_core.game_manager', 'game'))
_ORIGINALS = {}
_installed = threading.Lock()


def _log(text):
    print('[polyglot] %s' % text)


def resolve(base_path, openfile):
    """(source path, runtime) for an add-on's ``openfile``, or (None, None).

    ``game.lua`` names its language; a bare ``game`` is looked for with every
    extension a runtime answers, after Titan's own (which come first).
    """
    path = os.path.join(base_path, openfile)
    runtime = runtimes.for_file(path)
    if runtime is not None:
        return (path, runtime) if os.path.isfile(path) else (None, None)
    if not os.path.splitext(openfile)[1]:
        for runtime in runtimes.all_runtimes():
            for ext in runtime.extensions:
                if os.path.isfile(path + ext):
                    return path + ext, runtime
    return None, None


def _make_find(module_name, original):
    def find_executable_file(base_path, openfile):
        try:
            if os.path.splitext(openfile)[1]:
                path, runtime = resolve(base_path, openfile)
                if path:
                    return path, 'exe'
            found = original(base_path, openfile)
            if found and found[0]:
                return found
            path, runtime = resolve(base_path, openfile)
            if path:
                return path, 'exe'
            return found
        except Exception as error:
            _log('find failed: %s' % error)
            return original(base_path, openfile)
    find_executable_file.polyglot = True
    return find_executable_file


def _make_run(module_name, kind, original):
    def _run_executable(exec_file, cwd, *args, **kwargs):
        runtime = runtimes.for_file(exec_file)
        if runtime is None:
            return original(exec_file, cwd, *args, **kwargs)
        try:
            return launch(exec_file, cwd, kind, runtime)
        except Exception as error:
            _log('launch failed: %s' % error)
            _tell(str(error))
            return 0
    _run_executable.polyglot = True
    return _run_executable


#: The Macro Manager component, as the component manager registers it.
_MACROS_MODULE = 'macros'


def _make_run_macro(original):
    """A macro whose ``openfile`` is a program in another language runs the
    way an application does, once; every other macro is the Macro Manager's
    own business."""
    def run_macro(macro_info, parent_frame=None, *args, **kwargs):
        script = (macro_info or {}).get('script_path', '') or ''
        runtime = runtimes.for_file(script) if script else None
        if runtime is None or not os.path.isfile(script):
            return original(macro_info, parent_frame, *args, **kwargs)
        try:
            if not runtime.available():
                raise RuntimeError(runtime.why_not())
            pid = launch(script, os.path.dirname(script), 'macro', runtime)
            # So `titan.processes` says which process is this macro.
            try:
                from src.titan_core import app_manager
                app_manager.note_process(pid, {
                    'name': macro_info.get('name', ''),
                    'shortname': macro_info.get('folder_name', ''),
                    'path': os.path.dirname(script)}, kind='macro')
            except Exception:
                pass
            return pid
        except Exception as error:
            _log('macro failed: %s' % error)
            _tell(str(error))
            return 0
    run_macro.polyglot = True
    return run_macro


def _install_macros():
    """Wrap the Macro Manager's ``run_macro`` - looked up by name by every
    way a macro is started (its list, its shortcuts, its triggers, the Start
    menu, the ``macros.run_macro`` action)."""
    module = sys.modules.get(_MACROS_MODULE)
    run = getattr(module, 'run_macro', None) if module is not None else None
    if run is None or not hasattr(module, 'MacroManager')             and not hasattr(module, 'run_tcs'):
        return False
    if getattr(run, 'polyglot', False):
        return True
    _ORIGINALS[_MACROS_MODULE] = run
    module.run_macro = _make_run_macro(run)
    return True


def install():
    """Put the two helpers in place. Safe to call twice."""
    with _installed:
        import importlib
        done = []
        for module_name, kind in _MODULES:
            try:
                module = importlib.import_module(module_name)
            except Exception as error:
                _log('cannot reach %s: %s' % (module_name, error))
                continue
            if module_name not in _ORIGINALS:
                _ORIGINALS[module_name] = (module.find_executable_file,
                                           module._run_executable)
            find, run = _ORIGINALS[module_name]
            module.find_executable_file = _make_find(module_name, find)
            module._run_executable = _make_run(module_name, kind, run)
            done.append(kind)
        try:
            if _install_macros():
                done.append('macro')
        except Exception as error:
            _log('cannot reach the macros: %s' % error)
        return done


def uninstall():
    with _installed:
        for module_name, original in list(_ORIGINALS.items()):
            module = sys.modules.get(module_name)
            if module is None:
                continue
            if module_name == _MACROS_MODULE:
                module.run_macro = original
                continue
            find, run = original
            module.find_executable_file = find
            module._run_executable = run
        _ORIGINALS.clear()


def installed():
    return bool(_ORIGINALS)


# ---------------------------------------------------------------- launching
def _manifest_value(folder, keys):
    for name in ('__app.TCE', '__game.TCE', '__game__.TCE', '__app__.TCE'):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        values = {}
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as handle:
                for line in handle:
                    if '=' in line:
                        key, value = line.split('=', 1)
                        values[key.strip().lower()] = value.strip().strip('"')
        except OSError:
            continue
        for key in keys:
            if values.get(key):
                return values[key]
    return ''


def _title_of(folder):
    from .i18n import language
    lang = language()
    return (_manifest_value(folder, ['name_' + lang, 'name', 'name_en',
                                     'name_pl'])
            or os.path.basename(folder.rstrip('\\/')))


def python_and_root():
    """The Python Titan starts its own Python applications with, and where
    Titan's ``src`` is - asked of Titan's app manager, never guessed."""
    from src.titan_core import app_manager
    python, problem = app_manager.get_python_executable()
    if not python:
        raise RuntimeError(problem or 'No Python interpreter for applications')
    root = app_manager.resource_path('').rstrip('\\/')
    extra = getattr(app_manager, 'SITEPACKAGES_DIR', '') or ''
    return python, root, extra


def host_command(source, folder, kind, runtime, title, ident):
    python, root, extra = python_and_root()
    paths = [p for p in (COMPONENT_DIR, root, extra) if p]
    arguments = ['--file', source, '--runtime', runtime.id, '--dir', folder,
                 '--kind', kind, '--title', title, '--id', ident]
    code = ('import sys; sys.path[:0] = %r; sys.argv = [%r]; '
            'from polyglotkit.host import main; sys.exit(main(%r))'
            % (paths, source, arguments))
    return [python, '-c', code], root


def launch(source, folder, kind, runtime):
    """Start a program in another language. Answers the host's pid."""
    import subprocess
    folder = os.path.abspath(folder or os.path.dirname(source))
    ident = os.path.basename(folder.rstrip('\\/'))
    title = _title_of(folder)
    command, root = host_command(source, folder, kind, runtime, title, ident)
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH'):
        env.pop(key, None)
    env['TITAN_ROOT'] = root
    try:
        from .i18n import language
        env['TITAN_LANGUAGE'] = language()
    except Exception:
        pass
    kwargs = {}
    if sys.platform == 'win32':
        if getattr(sys, 'frozen', False):
            internal = os.path.join(os.path.dirname(sys.executable), '_internal')
            env['PATH'] = os.pathsep.join(
                [internal, os.path.join(internal, 'DLLs'), env.get('PATH', '')])
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    _log('launch %s (%s) as %s' % (source, runtime.id, kind))
    process = subprocess.Popen(command, cwd=folder, env=env, **kwargs)
    return getattr(process, 'pid', 0) or 0


def _tell(text):
    """A launch that failed is said - a menu entry that does nothing and
    says nothing is the worst answer there is for somebody who cannot see."""
    try:
        import wx
        wx.CallAfter(wx.MessageBox, text, 'Polyglot', wx.OK | wx.ICON_ERROR)
    except Exception:
        pass

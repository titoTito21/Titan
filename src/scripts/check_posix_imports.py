"""Import every Titan module on THIS machine and report what breaks.

Written for Linux and macOS, where wxPython may not be installable in the
sandbox that runs the check: a permissive stand-in answers every ``wx``
name, so what is measured is Titan's own code at import time - a bare
``import winreg``, a ``ctypes.windll`` at module level, a library that
only exists on Windows. Run it on a Linux or macOS Python with the
requirements that install there:

    python src/scripts/check_posix_imports.py

It prints how many modules imported and one line per failure, with the
Titan file and line the traceback ends in. Modules that need a library
that is merely not installed (telethon, PortAudio) are reported too, and
are the machine's business rather than the code's.
"""
import importlib, importlib.abc, importlib.machinery, os, sys, traceback, types
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT); os.chdir(ROOT)

class _Any:
    def __init__(self, *a, **k): pass
    def __getattr__(self, name):
        if name.startswith('__'): raise AttributeError(name)
        return _Any()
    def __call__(self, *a, **k): return _Any()
    def __iter__(self): return iter(())
    def __bool__(self): return False
    def __int__(self): return 0
    def __or__(self, o): return 0
    def __ror__(self, o): return 0
    def __eq__(self, o): return False
    def __hash__(self): return 0

class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith('__'): raise AttributeError(name)
        return _Any()
class _AnyClass(_Any, metaclass=_Meta):
    pass

def _mod_getattr(name):
    if name.startswith('__'): raise AttributeError(name)
    if name[:1].isupper() and name.upper() == name: return 0      # wx.ID_ANY, flags
    if name[:1].isupper(): return type(name, (_AnyClass,), {})   # wx.Frame
    return _Any()                                                  # wx.CallAfter

class _WxFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'wx' or fullname.startswith('wx.'):
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None
    def create_module(self, spec):
        m = types.ModuleType(spec.name); m.__path__ = []; m.__getattr__ = _mod_getattr
        m.VERSION = (4, 2, 2); m.version = lambda: '4.2.2 stub'
        return m
    def exec_module(self, module): pass
try:
    import wx  # noqa: F401 - the real one, when it is installed
    print("using the installed wxPython", wx.version())
except Exception:
    sys.meta_path.insert(0, _WxFinder())
    print("wxPython is not installed here: a stand-in answers every wx name")

skip = {'__pycache__'}
mods = []
for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, 'src')):
    dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith('.')]
    for f in filenames:
        if f.endswith('.py') and f != '__init__.py':
            rel = os.path.relpath(os.path.join(dirpath, f), ROOT)[:-3]
            mods.append(rel.replace(os.sep, '.'))
mods.sort()
failed = {}
ok = 0
for name in mods:
    if '.shim.' in name or name.startswith('src.scripts'):
        continue
    try:
        importlib.import_module(name); ok += 1
    except BaseException as e:
        tb = traceback.extract_tb(e.__traceback__)
        where = ''
        for fr in reversed(tb):
            if ROOT in fr.filename:
                where = f"{os.path.relpath(fr.filename, ROOT)}:{fr.lineno}"; break
        failed[name] = f"{type(e).__name__}: {str(e)[:120]}  @ {where}"
print(f"imported {ok} of {ok+len(failed)} modules on Linux")
for k, v in sorted(failed.items()):
    print(f"FAIL {k}: {v}")

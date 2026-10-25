"""The REAL InvisibleUI in Titan UI mode, and the real Polyglot window.

Whether the Invisible UI holds the arrow keys is asked of WINDOWS: a
RegisterHotKey for Up from another thread fails while the Invisible UI has
it. Before the window, while it is open, after it closes. Temporary
APPDATA; the window is never shown; Titan UI is switched off at the end.
"""
import os, sys, tempfile, time, ctypes, threading, importlib.util
ROOT = r'C:\Users\tito\OneDrive\projects\Titan'
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='iui_probe_')
sys.path.insert(0, ROOT); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'polyglot'))
import wx
app = wx.App(False)
user32 = ctypes.windll.user32
VK_UP, VK_RETURN = 0x26, 0x0D


def held_by_someone(vk):
    """Ask Windows whether `vk` (no modifiers) is a registered hotkey."""
    answer = {}
    def probe():
        ok = user32.RegisterHotKey(None, 0xBEEF, 0x4000, vk)   # MOD_NOREPEAT
        if ok:
            user32.UnregisterHotKey(None, 0xBEEF)
        answer['held'] = not ok
    t = threading.Thread(target=probe); t.start(); t.join()
    return answer['held']


def settle(seconds=1.2):
    end = time.time() + seconds
    while time.time() < end:
        wx.SafeYield(); time.sleep(0.05)


import faulthandler; faulthandler.enable()
print('S import', flush=True)
from src.ui.invisibleui import InvisibleUI
print('S imported', flush=True)
frame = wx.Frame(None)
iui = InvisibleUI(frame)
frame.invisible_ui = iui
print('S built', flush=True)
log = []
log.append(('before Titan UI', held_by_someone(VK_UP), held_by_someone(VK_RETURN)))
iui.titan_ui_mode = True
iui._update_hotkeys(); settle()
print('S on', flush=True)
log.append(('Titan UI on', held_by_someone(VK_UP), held_by_someone(VK_RETURN)))

spec = importlib.util.spec_from_file_location(
    'polyglot', os.path.join(ROOT, 'data', 'components', 'polyglot', 'init.py'))
print('S probed', log, flush=True)
polyglot = importlib.util.module_from_spec(spec); spec.loader.exec_module(polyglot)
print('S polyglot', flush=True)
_oe = os._exit
def _trap(code=0):
    import traceback; traceback.print_stack(); print('S os._exit', code, flush=True); _oe(code)
os._exit = _trap


def modal(self):
    settle()
    log.append(('Polyglot window open', held_by_someone(VK_UP), held_by_someone(VK_RETURN)))
    return wx.ID_CANCEL


wx.Dialog.ShowModal = modal
import atexit, traceback
atexit.register(lambda: print('S atexit', flush=True))
_real_exit = sys.exit
sys.exit = lambda *a: (traceback.print_stack(), print('S sys.exit', a, flush=True), _real_exit(*a))
try:
    polyglot.show_window(frame)
finally:
    settle()
    log.append(('Polyglot window closed', held_by_someone(VK_UP), held_by_someone(VK_RETURN)))
    iui.titan_ui_mode = False
    iui._update_hotkeys(); settle()
    log.append(('Titan UI off again', held_by_someone(VK_UP), held_by_someone(VK_RETURN)))

for name, up, enter in log:
    print('%-24s Up held by Invisible UI: %-5s  Enter: %s' % (name, up, enter))
os._exit(0)

# Run: python tests/check_titan_access_hung_window.py (Windows). A window made
# off-screen in another process stops answering; the reader asks UIA about it
# without and with native_hook.window_answers, and both are timed.
import sys, os, time, subprocess, tempfile
os.environ['APPDATA']=tempfile.mkdtemp()
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(),'data','components','titan access'))
import comtypes; ctypes_ok=True
from titan_access import native_hook
from titan_access.uia_focus import UIAProvider
p = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hung_window_probe.py'), '60'], stdout=subprocess.PIPE, text=True)
hwnd = int(p.stdout.readline()); time.sleep(6)
import ctypes
print('hung by Windows verdict:', bool(ctypes.windll.user32.IsHungAppWindow(hwnd)))
prov = UIAProvider()
for mode in ('before (no check)', 'after (window_answers)'):
    keep = native_hook.window_answers
    if mode.startswith('before'):
        native_hook.window_answers = lambda *a, **k: True
    t = time.perf_counter(); r = prov.object_from_handle(hwnd); took = time.perf_counter()-t
    native_hook.window_answers = keep
    print('%-24s object_from_handle took %.2f s -> %r' % (mode, took, r))
p.kill()

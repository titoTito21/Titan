"""What a screen reader gets from the REAL console settings interface.

A hidden conhost window (never shown, so neither the user's desktop nor
Windows Terminal is touched) runs `console_settings` over Settings ->
Polyglot, printing to its real console with the answers typed by the child
script. This process then reads that console the way Titan Access's terminal
module does: the UI Automation text pattern of the console window.
Temporary APPDATA.
"""
import os, sys, time, subprocess, ctypes, tempfile
ROOT = r'C:\Users\tito\OneDrive\projects\Titan'
TITLE = 'PolyglotConsoleReaderProbe'

CHILD = r'''
import os, sys, threading, importlib.util, ctypes, time
ROOT = %r
sys.path.insert(0, ROOT); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'polyglot'))
ctypes.windll.kernel32.SetConsoleTitleW(%r)
import wx
app = wx.App(False)
from polyglotkit import settings_page, tce_ui
from src.settings import ui_model, interfaces
tce_ui.message = lambda *a, **k: None
tce_ui.play = lambda *a, **k: None
holder = wx.Frame(None)
page = settings_page.build(holder)
holder.categories = {'Polyglot': page}; holder.category_order = ['Polyglot']
folder = os.path.join(ROOT, 'data', 'settings interfaces', 'console_settings')
config = interfaces.SettingsInterfaceConfig(os.path.join(folder, '__settings_ui__.TCE'), 'console_settings')
api = interfaces.SettingsUIAPI(config, ui_model.SettingsModel(holder))
spec = importlib.util.spec_from_file_location('c', os.path.join(folder, 'init.py'))
console = importlib.util.module_from_spec(spec); spec.loader.exec_module(console)
sys.stdout.reconfigure(encoding='utf-8')
answers = iter(['1', '2', 'Ruby', '7', 't', '3', '', 'q'])
class Typed(console.ConsoleSettings):
    @staticmethod
    def ask(prompt):
        answer = next(answers, None)
        print(prompt + (answer or ''))
        return answer
def work():
    Typed(api).run()
    print('KONIEC'); sys.stdout.flush()
    wx.CallAfter(app.ExitMainLoop)
threading.Thread(target=work, daemon=True).start()
app.MainLoop()
time.sleep(40)
''' % (ROOT, TITLE)

env = dict(os.environ, APPDATA=tempfile.mkdtemp(prefix='console_reader_'),
           PYTHONIOENCODING='utf-8')
script = os.path.join(env['APPDATA'], 'child.py')
with open(script, 'w', encoding='utf-8') as handle:
    handle.write(CHILD)
info = subprocess.STARTUPINFO()
info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
info.wShowWindow = 0                                  # SW_HIDE
conhost = os.path.join(os.environ['SystemRoot'], 'System32', 'conhost.exe')
child = subprocess.Popen([conhost, sys.executable, script], env=env,
                         startupinfo=info)
user32 = ctypes.windll.user32
hwnd = 0
end = time.time() + 30
while not hwnd and time.time() < end:
    hwnd = user32.FindWindowW('ConsoleWindowClass', TITLE)
    time.sleep(0.3)
print('console window found:', bool(hwnd), 'visible:', bool(hwnd and user32.IsWindowVisible(hwnd)))
sys.path.append(os.path.join(ROOT, 'data', 'components', 'titan access', 'lib'))
import uiautomation
text = ''
end = time.time() + 60
while time.time() < end:
    control = uiautomation.ControlFromHandle(hwnd)
    pattern = None
    for candidate in [control] + list(control.GetChildren()):
        try:
            pattern = candidate.GetPattern(uiautomation.PatternId.TextPattern)
        except Exception:
            pattern = None
        if pattern:
            break
    text = pattern.DocumentRange.GetText(-1) if pattern else ''
    if 'KONIEC' in text:
        break
    time.sleep(1)
print('=' * 30, 'READ THROUGH UIA', '=' * 30)
print('\n'.join(line.rstrip() for line in text.splitlines() if line.strip()))
child.kill()

"""The REAL console_settings interface over Settings -> Polyglot.

Its own `ConsoleSettings` loop on a worker, exactly as `open_settings`
runs it, with the answers typed by this script instead of a console (no
console is opened). Temporary APPDATA; message boxes recorded, not shown.
"""
import os, sys, tempfile, threading, importlib.util
ROOT = r'C:\Users\tito\OneDrive\projects\Titan'
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='console_probe_')
sys.path.insert(0, ROOT); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'polyglot'))
import wx
app = wx.App(False)
from polyglotkit import settings_page, tce_ui
from src.settings import ui_model, interfaces
shown = []
tce_ui.message = lambda *a, **k: shown.append(a[1])
tce_ui.play = lambda *a, **k: None
holder = wx.Frame(None)
page = settings_page.build(holder)
holder.categories = {'Polyglot': page}; holder.category_order = ['Polyglot']
folder = os.path.join(ROOT, 'data', 'settings interfaces', 'console_settings')
config = interfaces.SettingsInterfaceConfig(
    os.path.join(folder, '__settings_ui__.TCE'), 'console_settings')
api = interfaces.SettingsUIAPI(config, ui_model.SettingsModel(holder))
spec = importlib.util.spec_from_file_location('console_ui', os.path.join(folder, 'init.py'))
console = importlib.util.module_from_spec(spec); spec.loader.exec_module(console)
items = {i['label']: n for n, i in enumerate(api.items(), 1)}
check = items[settings_page._("Chec&k").replace('&', '')]
details = items[settings_page._("Details")]
target = items[settings_page._("Language the buttons act on")]
languages = items[settings_page._("&Languages:").replace('&', '').rstrip(':')]
answers = iter(['1', str(target), 'Ruby', str(check), 't', str(details),
                str(languages), '1,2', '', 'q'])
said = []


class Scripted(console.ConsoleSettings):
    def say(self, text=''):
        said.append(text)

    def ask(self, prompt):
        said.append(prompt)
        return next(answers, None)


def work():
    try:
        Scripted(api).run()
    finally:
        wx.CallAfter(app.ExitMainLoop)
threading.Thread(target=work, daemon=True).start()
wx.CallLater(60000, app.ExitMainLoop)
app.MainLoop()
print('\n'.join(str(s) for s in said))
print('=' * 40)
print('CURSOR AFTER CHOOSING Ruby:', page.ids[page.listing.GetFirstSelected()])
print('MESSAGE BOXES:', shown)
print('RUBY SWITCHED OFF:', page.languages.find('ruby').disabled)
print('LUA STILL ON:', not page.languages.find('lua').disabled)
sys.stdout.flush()
os._exit(0)

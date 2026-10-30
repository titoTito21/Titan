"""The REAL html_settings window (WebView2) over Settings -> Polyglot.
Off the screen, never activated; temporary APPDATA; message boxes recorded."""
import os, sys, tempfile, importlib.util, json
ROOT = r'C:\Users\tito\OneDrive\projects\Titan'
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='html_probe_')
os.environ['WEBVIEW2_USER_DATA_FOLDER'] = os.path.join(os.environ['APPDATA'], 'wv2')
sys.path.insert(0, ROOT); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'polyglot'))
import wx, functools, builtins; print = functools.partial(builtins.print, flush=True)
app = wx.App(False)
from polyglotkit import settings_page, tce_ui
from src.settings import ui_model, interfaces
shown = []
tce_ui.message = lambda *a, **k: shown.append(a[1])
tce_ui.play = lambda *a, **k: None
holder = wx.Frame(None)
page = settings_page.build(holder)
holder.categories = {'Polyglot': page}; holder.category_order = ['Polyglot']
folder = os.path.join(ROOT, 'data', 'settings interfaces', 'html_settings')
config = interfaces.SettingsInterfaceConfig(os.path.join(folder, '__settings_ui__.TCE'), 'html_settings')
api = interfaces.SettingsUIAPI(config, ui_model.SettingsModel(holder))
spec = importlib.util.spec_from_file_location('html_ui', os.path.join(folder, 'init.py'))
html = importlib.util.module_from_spec(spec); spec.loader.exec_module(html)
win = html.HtmlSettingsFrame(api, None)
win.SetPosition((-3000, -3000)); win.ShowWithoutActivating()
import wx.html2 as _wv
def _seen(e):
    print('NAVIGATING', e.GetURL()); e.Skip()
win.browser.Bind(_wv.EVT_WEBVIEW_NAVIGATING, _seen)
win.browser.Bind(_wv.EVT_WEBVIEW_ERROR, lambda e: print('WVERROR', e.GetURL(), e.GetString()))
_set = api.set
api.set = lambda i, v: (print('API.SET', i, repr(v)), _set(i, v))[1]
ids = {i['label']: i['id'] for i in api.items()}
def js(code):
    res = win.browser.RunScript("try{ var __r=(function(){ return " + code.rstrip(';').replace(';', ',') + "; })(); String(__r) }catch(e){ 'JSERR '+e }") if False else win.browser.RunScript(code if code.startswith('JSON') else 'try{' + code + '; "ok"}catch(e){"JSERR "+e}')
    ok, out = res
    if 'location' in code or 'titan' in code: print('RUNSCRIPT', ok, str(out)[:200], 'href now', win.browser.RunScript('location.href')[1][:60])
    return out
READ = ("JSON.stringify({legend: document.querySelector('fieldset legend').textContent,"
        " rows: [...document.querySelectorAll('fieldset input')].map(i => i.value + (i.checked?' [x]':' [ ]')),"
        " select: (document.querySelector('select')||{}).value,"
        " info: document.querySelector('.info').innerText,"
        " buttons: [...document.querySelectorAll('button')].map(b => b.textContent)})")
steps = []
def step(n=0):
    try:
        if n == 0:
            print('PAGE', json.dumps(json.loads(js(READ)), ensure_ascii=False, indent=1))
            choice = ids[settings_page._("Language the buttons act on")]
            js("var s=document.getElementById('%s'); s.value='Ruby'; titanSet('%s', s);" % (choice, choice))
        elif n == 1:
            print('LIST CURSOR AFTER CHOOSING Ruby:', page.ids[page.listing.GetFirstSelected()])
            js("titanPress('%s')" % ids[settings_page._("Chec&k").replace("&", "")])
        elif n == 2:
            data = json.loads(js(READ))
            print('MESSAGE BOXES:', shown)
            print('DETAILS AFTER CHECK:\n' + data['info'])
            multi = ids[settings_page._("&Languages:").replace("&","").rstrip(":")]
            # untick Ruby the way the page does it
            js("var b=[...document.getElementsByName('%s')].find(i=>i.value.startsWith('Ruby')); b.checked=false; titanSetMulti('%s');" % (multi, multi))
        elif n == 3:
            print('RUBY SWITCHED OFF IN THE PAGE MODEL:', page.languages.find('ruby').disabled)
            win.Destroy(); holder.Destroy(); app.ExitMainLoop(); return
    except Exception as e:
        import traceback; traceback.print_exc(); app.ExitMainLoop(); return
    wx.CallLater(2500, step, n + 1)
wx.CallLater(4000, step, 0)
wx.CallLater(40000, app.ExitMainLoop)
app.MainLoop()
os._exit(0)

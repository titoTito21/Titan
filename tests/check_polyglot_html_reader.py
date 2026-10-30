"""Titan Access reading the REAL html_settings page over Settings -> Polyglot.

The WebView2 window is off the screen and never activated; the reader builds
its browse-mode document from it exactly as on a web page
(`virtual_buffer.build_for_window`, the UIA tier) and every line is printed
with its role. Temporary APPDATA; nothing is spoken.
"""
import os, sys, tempfile, threading, importlib.util
ROOT = r'C:\Users\tito\OneDrive\projects\Titan'
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='html_reader_')
os.environ['WEBVIEW2_USER_DATA_FOLDER'] = os.path.join(os.environ['APPDATA'], 'wv2')
# An off-screen Chromium renders an empty accessibility tree unless told
# its window is not hidden (the same flag the web-page checks use).
os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = \
    '--disable-features=CalculateNativeWinOcclusion --force-renderer-accessibility'
sys.path.insert(0, ROOT); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'polyglot'))
sys.path.append(os.path.join(ROOT, 'data', 'components', 'titan access'))
sys.path.append(os.path.join(ROOT, 'data', 'components', 'titan access', 'lib'))
import wx
app = wx.App(False)
from polyglotkit import settings_page, tce_ui
from src.settings import ui_model, interfaces
tce_ui.play = lambda *a, **k: None
holder = wx.Frame(None)
page = settings_page.build(holder)
holder.categories = {'Polyglot': page}; holder.category_order = ['Polyglot']
folder = os.path.join(ROOT, 'data', 'settings interfaces', 'html_settings')
config = interfaces.SettingsInterfaceConfig(
    os.path.join(folder, '__settings_ui__.TCE'), 'html_settings')
api = interfaces.SettingsUIAPI(config, ui_model.SettingsModel(holder))
spec = importlib.util.spec_from_file_location('html_ui', os.path.join(folder, 'init.py'))
html = importlib.util.module_from_spec(spec); spec.loader.exec_module(html)
win = html.HtmlSettingsFrame(api, None)
win.SetPosition((-3000, -3000)); win.ShowWithoutActivating()
lines = []


def read():
    try:
        import comtypes
        try:
            comtypes.CoInitializeEx(0)
        except OSError:
            pass  # the thread already has an apartment
        from titan_access import virtual_buffer
        import time
        import uiautomation
        from titan_access.browse_mode import BrowseModeHandler
        # Browse mode's own way to a page: the page's document under the
        # window, then the web build (off-screen content kept, as on a page).
        window = uiautomation.ControlFromHandle(win.GetHandle())
        document = BrowseModeHandler._find_main_document(None, window)
        nodes = virtual_buffer.build_uia(
            document, deadline=time.time() + virtual_buffer.BUILD_BUDGET_S,
            web=True) if document is not None else []
        lines.append('BROWSE MODE DOCUMENT: %d lines' % len(nodes))
        for node in nodes:
            states = ' [%s]' % ', '.join(map(str, node.states)) if node.states else ''
            lines.append('  %-14s %s%s' % (node.role, node.text, states))
    except Exception:
        import traceback
        lines.append(traceback.format_exc())
    finally:
        wx.CallAfter(app.ExitMainLoop)
wx.CallLater(5000, lambda: threading.Thread(target=read, daemon=True).start())
wx.CallLater(60000, app.ExitMainLoop)
app.MainLoop()
print('\n'.join(lines), flush=True)
os._exit(0)

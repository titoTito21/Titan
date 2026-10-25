"""What Titan Access - a real screen reader - says for every control of
Polyglot's windows and the new General settings.

The windows are shown OFF-SCREEN without being activated, so the user's
focus is not touched; each control is read through Titan Access's own UIA
provider and turned into words by its own `accessible.describe`, which is
what the reader speaks on focus. Temporary APPDATA; nothing is spoken.
"""
import os, sys, tempfile, threading, importlib.util
ROOT = r'C:\Users\tito\OneDrive\projects\Titan'
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='ta_probe_')
sys.path.insert(0, ROOT); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'polyglot'))
sys.path.append(os.path.join(ROOT, 'data', 'components', 'titan access'))
sys.path.append(os.path.join(ROOT, 'data', 'components', 'titan access', 'lib'))
import wx
app = wx.App(False)

from polyglotkit import settings_page
from src.ui import settingsgui
spec = importlib.util.spec_from_file_location(
    'polyglot', os.path.join(ROOT, 'data', 'components', 'polyglot', 'init.py'))
polyglot = importlib.util.module_from_spec(spec); spec.loader.exec_module(polyglot)

OFF = (-32000, -32000)
not_label = lambda cs: [c for c in cs if not isinstance(c, wx.StaticText)]
windows = []
host = wx.Frame(None, pos=OFF)
dlg = settings_page.LanguageDialog(host, settings_page.Languages([]))
windows.append(('Add a language', dlg.dialog, not_label(dlg.ident.GetParent().GetChildren())))
page_frame = wx.Frame(None, pos=OFF, size=(700, 500))
panel = settings_page.build(page_frame)
windows.append(('Settings -> Polyglot', page_frame, not_label(panel.GetChildren())))
sf = settingsgui.SettingsFrame(None)
sf.ShowCategory(list(sf.categories)[0])
windows.append(('General (new)', sf, [sf.usage_tips_cb, sf.packages_folder_ctrl,
                                      sf.packages_folder_btn]))
result = []


def read_all(loop):
    try:
        import comtypes
        comtypes.CoInitializeEx(0)
        from titan_access.uia_focus import UIAProvider
        from titan_access import accessible
        from titan_access.settings_store import get_settings
        from titan_access.engine import TitanAccessEngine
        from titan_access import speech_adapter
        provider, store, bad = UIAProvider(), get_settings(), 0
        # The reader's own engine and its own speech queue; the adapter is
        # put in its print mode so the words are queued, logged and NOT
        # played over the user's running NVDA.
        engine = TitanAccessEngine()
        engine.settings = store
        engine.speech = speech_adapter.SpeechAdapter(store)
        engine.speech._mode = engine.speech._MODE_PRINT
        engine._muted_for_foreground = lambda *a, **k: False
        engine._consume_override = lambda *a, **k: False
        engine.running = True   # speaks as a started reader does; no hook, no focus tracking
        for title, _w, controls in windows:
            result.append('== ' + title)
            for c in controls:
                obj = provider.object_from_handle(c.GetHandle())
                before = len(speech_adapter.spoken())
                if obj:
                    engine.announce_object(obj, play_cursor=False)
                said = speech_adapter.spoken()
                words = said[-1] if len(said) > before or len(said) == 20 else ''
                result.append('  SAID: ' + (words or '<NOTHING>'))
                if not obj or not (obj.name or '').strip() or not words:
                    bad += 1
        result.append('UNNAMED: %d' % bad)
    except Exception:
        import traceback
        result.append(traceback.format_exc())
    finally:
        wx.CallAfter(loop.Exit)


def modal(self):
    """Polyglot's own window is up: read everything while it exists."""
    windows.append(('Polyglot window', self, not_label(self.GetChildren())))
    for _t, w, _c in windows:
        w.SetPosition(OFF)
        w.ShowWithoutActivating()
    loop = wx.GUIEventLoop()
    threading.Thread(target=read_all, args=(loop,), daemon=True).start()
    loop.Run()
    return wx.ID_CANCEL


wx.Dialog.ShowModal = modal
polyglot.show_window(None)
print('\n'.join(result), flush=True)
os._exit(0)

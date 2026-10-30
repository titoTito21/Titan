"""Klango mode (wx) opening Polyglot through its OWN Components card.

The real `KlangoFrame`, a component manager holding Polyglot's real menu
function, and the card's own action pressed. The dialog is not shown (its
ShowModal is replaced): the check reads where it would appear, what has the
keyboard, and that Klango's menu is closed after. Temporary APPDATA.
"""
import os, sys, tempfile, importlib.util
ROOT = r'C:\Users\tito\OneDrive\projects\Titan'
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='klango_probe_')
sys.path.insert(0, ROOT); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'polyglot'))
sys.path.append(os.path.join(ROOT, 'data', 'components', 'titan access'))
sys.path.append(os.path.join(ROOT, 'data', 'components', 'titan access', 'lib'))
import threading
import wx
app = wx.App(False)
spec = importlib.util.spec_from_file_location(
    'polyglot', os.path.join(ROOT, 'data', 'components', 'polyglot', 'init.py'))
polyglot = importlib.util.module_from_spec(spec); spec.loader.exec_module(polyglot)
polyglot.tce_ui.play = lambda *a, **k: None


class Manager(object):
    def get_component_menu_functions(self):
        return {'Polyglot': polyglot._on_menu}

    def __getattr__(self, name):
        return lambda *a, **k: None

seen = []


def modal(self):
    display = wx.Display(wx.Display.GetFromWindow(self)
                         if wx.Display.GetFromWindow(self) != wx.NOT_FOUND else 0)
    rect = self.GetScreenRect()
    focus = wx.Window.FindFocus()
    seen.append({'title': self.GetTitle(),
                 'on a screen': display.GetGeometry().Intersects(rect),
                 'keyboard on': type(focus).__name__ if focus else None,
                 'keyboard inside the window': bool(focus) and (
                     focus is self or self.IsDescendant(focus))})
    # And what a screen reader says for every control of it - Titan
    # Access's own engine, its speech queue in print mode (nothing plays).
    position = self.GetPosition()
    self.SetPosition((-32000, -32000))
    self.ShowWithoutActivating()
    loop = wx.GUIEventLoop()

    def read():
        try:
            import comtypes
            try:
                comtypes.CoInitializeEx(0)
            except OSError:
                pass
            from titan_access.uia_focus import UIAProvider
            from titan_access.settings_store import get_settings
            from titan_access.engine import TitanAccessEngine
            from titan_access import speech_adapter
            provider, store = UIAProvider(), get_settings()
            engine = TitanAccessEngine()
            engine.settings = store
            engine.speech = speech_adapter.SpeechAdapter(store)
            engine.speech._mode = engine.speech._MODE_PRINT
            engine._muted_for_foreground = lambda *a, **k: False
            engine._consume_override = lambda *a, **k: False
            engine.running = True
            for control in self.GetChildren():
                if isinstance(control, wx.StaticText):
                    continue
                obj = provider.object_from_handle(control.GetHandle())
                before = len(speech_adapter.spoken())
                if obj:
                    engine.announce_object(obj, play_cursor=False)
                said = speech_adapter.spoken()
                seen.append('SAID: ' + (said[-1] if len(said) > before
                                        or len(said) == 20 else '<NOTHING>'))
        except Exception:
            import traceback
            seen.append(traceback.format_exc())
        finally:
            wx.CallAfter(loop.Exit)
    threading.Thread(target=read, daemon=True).start()
    loop.Run()
    self.Hide()
    self.SetPosition(position)
    return wx.ID_CANCEL
wx.Dialog.ShowModal = modal

from src.system.klangomode import KlangoFrame
frame = KlangoFrame(None, 'Klango', '1.0', {}, Manager())
frame.load_components()
card = frame._menu_card(polyglot._('Components') if False else None) \
    if False else None
items = None
for card in frame.main_menu:
    for item in card.get('items', []) or []:
        if item.get('name') == 'Polyglot':
            items = item
print('Klango frame position:', frame.GetPosition())
print('Polyglot in Klango Components:', items is not None)
items['action']()
for row in seen:
    print(row)
print('Klango menu open after:', frame.menu_open)
sys.stdout.flush()
os._exit(0)

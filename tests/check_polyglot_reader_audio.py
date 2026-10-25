"""What Titan Access - a real screen reader - says for every control of
Polyglot's windows and the new General settings - with REAL speech.

The windows are shown OFF-SCREEN without being activated, so the user's
focus is not touched; each control is read through Titan Access's own UIA
provider and turned into words by its own `accessible.describe`, which is
what the reader speaks on focus, and SYNTHESIZED by its own voice: every
part the synthesizer renders is recorded with its length and the clip of each
control saved as a WAV. Played to SDL's dummy audio device, so it does not
talk over another screen reader. Temporary APPDATA.

    python tests/check_polyglot_reader_audio.py [folder for the WAVs]
"""
import os, sys, tempfile, threading, importlib.util, time
os.environ['SDL_AUDIODRIVER'] = 'dummy'
OUT = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix='ta_audio_')
os.makedirs(OUT, exist_ok=True)
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
RENDERED = []
HANDLES = []
from src.titan_core import stereo_speech as _ss
_real_synth = _ss.StereoSpeech._synthesize_segment
def _recording(self, text, pitch_offset=0):
    audio = _real_synth(self, text, pitch_offset)
    RENDERED.append((text, pitch_offset, audio))
    return audio
_ss.StereoSpeech._synthesize_segment = _recording


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
        # The reader's own engine, its own speech queue and its own voice.
        engine = TitanAccessEngine()
        engine.settings = store
        engine.speech = speech_adapter.SpeechAdapter(store)
        engine._muted_for_foreground = lambda *a, **k: False
        engine._consume_override = lambda *a, **k: False
        engine.running = True   # speaks as a started reader does; no hook, no focus tracking
        for title, _w, handles in HANDLES:
            result.append('== ' + title)
            for hwnd in handles:
                obj = provider.object_from_handle(hwnd)
                del RENDERED[:]
                if obj:
                    engine.announce_object(obj, play_cursor=False)
                # wait until the voice has rendered the whole announcement
                end, last, stable = time.time() + 15, -1, time.time()
                while time.time() < end:
                    if len(RENDERED) != last:
                        last, stable = len(RENDERED), time.time()
                    elif RENDERED and time.time() - stable > 1.2:
                        break
                    time.sleep(0.1)
                parts = [(t, p, a) for t, p, a in RENDERED if a is not None]
                ms = sum(len(a) for _t, _p, a in parts)
                words = ' | '.join('%s (pitch %+d, %d ms)' % (t, p, len(a)) for t, p, a in parts)
                if parts:
                    clip = parts[0][2]
                    for _t, _p, a in parts[1:]:
                        clip = clip + a
                    name = '%02d_%s.wav' % (len(result), ''.join(ch for ch in title if ch.isalnum())[:20])
                    clip.export(os.path.join(OUT, name), format='wav')
                result.append('  SPOKEN %5d ms: %s' % (ms, words or '<NO AUDIO>'))
                if not obj or not (obj.name or '').strip() or ms < 300:
                    bad += 1
        result.append('controls with no name or no speech: %d' % bad)
        result.append('WAVs in ' + OUT)
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
    HANDLES[:] = [(t, w, [c.GetHandle() for c in cs]) for t, w, cs in windows]
    loop = wx.GUIEventLoop()
    threading.Thread(target=read_all, args=(loop,), daemon=True).start()
    loop.Run()
    return wx.ID_CANCEL


wx.Dialog.ShowModal = modal
polyglot.show_window(None)
print('\n'.join(result), flush=True)
os._exit(0)

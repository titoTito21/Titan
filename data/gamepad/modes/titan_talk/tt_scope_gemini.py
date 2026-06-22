"""
Titan Talk - Audio game scope (Gemini OCR / vision)
===================================================

For games and apps that expose no accessibility information (visual-only games,
audio games, custom-drawn menus). It screenshots the foreground window, asks
Google Gemini to read everything written and locate the interactive controls /
menu options, and turns them into a navigable buffer. A clicks the selected
control at its screen coordinates; B sends Escape.

Dependencies (vendored in ``lib/``): Pillow for the screenshot,
``google-generativeai`` for the vision call. The Gemini API key is read from the
``[titan_talk] api_key`` setting. Because the vision call is slow, analysis runs
on a background thread so the controller poll loop never blocks.
"""

import json
import threading
import ctypes

from tt_core import (Scope, Control, _, speak, play_mode_sound, play_positioned,
                     SND_CLICK, SND_WINDOW)
from src.controller.controller_modes import _press, _release
from src.settings.settings import get_setting, set_setting

try:
    from PIL import ImageGrab
    _PIL = True
except Exception as e:  # pragma: no cover
    print(f"[TitanTalk] Pillow unavailable: {e}")
    ImageGrab = None
    _PIL = False

try:
    import google.generativeai as genai
    _GENAI = True
except Exception as e:  # pragma: no cover
    print(f"[TitanTalk] google-generativeai unavailable: {e}")
    genai = None
    _GENAI = False

_FALLBACK_MODEL = 'gemini-2.0-flash'

# Gemini convention: boxes are [ymin, xmin, ymax, xmax] normalized to 0..1000.
_PROMPT = (
    "You are reading a game or app screen for a blind user navigating by "
    "gamepad. Identify every interactive control or menu option (buttons, menu "
    "items, list entries, tabs, checkboxes, sliders, text fields) AND any "
    "important readable text. Respond with ONLY a JSON array, no prose. Each "
    "element: {\"text\": <visible label>, \"type\": one of "
    "[button,menuitem,listitem,tab,checkbox,slider,edit,text], "
    "\"box\": [ymin,xmin,ymax,xmax] normalized 0-1000}. Order them top-to-bottom "
    "as they read on screen."
)


def _foreground_rect():
    """(left, top, right, bottom) of the foreground window, or None."""
    try:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        if rect.right - rect.left <= 0 or rect.bottom - rect.top <= 0:
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception as e:
        print(f"[TitanTalk] foreground rect failed: {e}")
        return None


def _click_screen(x, y):
    """Left-click at absolute screen coordinates."""
    try:
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(x), int(y))
        MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return True
    except Exception as e:
        print(f"[TitanTalk] click failed: {e}")
        return False


class GeminiScope(Scope):
    id = 'gemini'

    def __init__(self, mode):
        super().__init__(mode)
        self._analyzing = False
        self._model = None

    def display_name(self):
        return _("Audio game")

    def available(self):
        return _PIL and _GENAI

    def _api_key(self):
        return (get_setting('api_key', '', section='titan_talk') or '').strip()

    def _pick_model_name(self):
        """Auto-select a working vision model for this key.

        A fixed model id often fails ("model not found / not supported") because
        availability varies per key and changes over time. Instead we ask the
        API which models this key can actually call (``list_models``) and pick a
        multimodal one that supports ``generateContent`` (every Gemini >=1.5
        model accepts images), preferring a fast "flash" model. A manual
        ``[titan_talk] model`` setting still overrides if present.
        """
        override = (get_setting('model', '', section='titan_talk') or '').strip()
        if override:
            return override
        try:
            models = list(genai.list_models())
        except Exception as e:
            print(f"[TitanTalk] list_models failed: {e}")
            return _FALLBACK_MODEL
        names = [m.name for m in models
                 if 'generateContent' in getattr(m, 'supported_generation_methods', [])
                 and 'gemini' in m.name]
        if not names:
            return _FALLBACK_MODEL

        def score(n):
            s = 0
            if 'flash' in n:
                s += 6
            if 'vision' in n:
                s += 2
            if 'latest' in n:
                s += 2
            if 'exp' in n or 'preview' in n:
                s -= 3
            # Prefer newer generations (2.x over 1.5) by a light version bump.
            for ver in ('2.5', '2.0', '1.5'):
                if ver in n:
                    s += int(float(ver))
                    break
            return s

        best = max(names, key=score)
        print(f"[TitanTalk] auto-selected Gemini model: {best}")
        return best

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        key = self._api_key()
        if not key:
            return None
        try:
            genai.configure(api_key=key)
            self._model = genai.GenerativeModel(self._pick_model_name())
        except Exception as e:
            print(f"[TitanTalk] Gemini model init failed: {e}")
            self._model = None
        return self._model

    # -- enumeration (async) ------------------------------------------------ #
    def refresh(self):
        # Don't block the poll loop: kick analysis onto a background thread.
        if self._analyzing:
            return
        if not self.available():
            self.controls = []
            return
        if not self._api_key():
            self.controls = []
            return
        self._analyzing = True
        self.controls = []
        threading.Thread(target=self._analyze, daemon=True).start()

    def on_enter(self, announce=True):
        if not self.available():
            if announce:
                speak(_("Audio game scope needs Pillow and the Gemini library."))
            self.controls = []
            self.index = -1
            return
        if not self._api_key():
            # First time on this tab without a key: ask for it right here.
            key = self._prompt_api_key()
            if not key:
                if announce:
                    speak(_("No Gemini API key set."))
                self.controls = []
                self.index = -1
                return
        if announce:
            speak(_("Audio game. Analyzing the screen, please wait."))
        self.refresh()

    def _prompt_api_key(self):
        """Ask for the Gemini API key in a dialog and persist it.

        Shown when the user switches to the audio game scope and no key is set
        yet. Returns the entered key (also saved to ``[titan_talk] api_key``),
        or '' if cancelled. The controller polls on the wx main thread, so the
        modal can run inline; off the main thread we fire it and let the user
        re-enter the scope.
        """
        try:
            import wx
        except Exception:
            return ''
        result = {'key': ''}

        def ask():
            dlg = wx.PasswordEntryDialog(None, _("Enter your Gemini API key"),
                                         _("Titan Talk"))
            try:
                if dlg.ShowModal() == wx.ID_OK:
                    result['key'] = (dlg.GetValue() or '').strip()
            finally:
                dlg.Destroy()

        try:
            if wx.IsMainThread():
                ask()
            else:
                wx.CallAfter(ask)
                return ''
        except Exception as e:
            print(f"[TitanTalk] key prompt failed: {e}")
            return ''

        key = result['key']
        if key:
            try:
                set_setting('api_key', key, section='titan_talk')
            except Exception as e:
                print(f"[TitanTalk] saving key failed: {e}")
            # A fresh key means re-resolving the model next call.
            self._model = None
        return key

    def _analyze(self):
        """Background: screenshot -> Gemini -> parse -> populate buffer."""
        try:
            model = self._ensure_model()
            if model is None:
                speak(_("Could not start Gemini."))
                return
            rect = _foreground_rect()
            bbox = rect if rect else None
            offset_x, offset_y = (rect[0], rect[1]) if rect else (0, 0)
            try:
                image = ImageGrab.grab(bbox=bbox)
            except Exception:
                image = ImageGrab.grab()
                offset_x, offset_y = 0, 0
            width, height = image.size
            response = model.generate_content([_PROMPT, image])
            controls = self._parse(response.text, width, height,
                                   offset_x, offset_y)
            self.controls = controls
            self.index = 0 if controls else -1
            if controls:
                play_mode_sound(SND_WINDOW)
                speak(_("{count} items found.").format(count=len(controls)))
                self.mode.announce_current(prefix='')
            else:
                speak(_("Nothing readable was found on screen."))
        except Exception as e:
            print(f"[TitanTalk] Gemini analyze failed: {e}")
            speak(_("Screen analysis failed."))
        finally:
            self._analyzing = False

    @staticmethod
    def _parse(text, width, height, offset_x, offset_y):
        """Parse Gemini's JSON into Control objects with absolute coords."""
        raw = (text or '').strip()
        # Strip ```json fences if present.
        if raw.startswith('```'):
            raw = raw.strip('`')
            if raw.lower().startswith('json'):
                raw = raw[4:]
        start, end = raw.find('['), raw.rfind(']')
        if start < 0 or end < 0:
            return []
        try:
            items = json.loads(raw[start:end + 1])
        except Exception as e:
            print(f"[TitanTalk] Gemini JSON parse failed: {e}")
            return []
        controls = []
        for it in items:
            try:
                label = str(it.get('text', '')).strip()
                role = str(it.get('type', 'text')).strip().lower()
                box = it.get('box') or [0, 0, 0, 0]
                ymin, xmin, ymax, xmax = box
                cx = offset_x + ((xmin + xmax) / 2.0) / 1000.0 * width
                cy = offset_y + ((ymin + ymax) / 2.0) / 1000.0 * height
                if not label:
                    continue
                controls.append(Control(name=label, role=role, cx=cx, cy=cy,
                                        payload=(cx, cy)))
            except Exception:
                continue
        return controls

    # -- actions ------------------------------------------------------------ #
    def activate(self):
        cur = self.current()
        if cur is None or not cur.payload:
            return False
        x, y = cur.payload
        if _click_screen(x, y):
            play_positioned(SND_CLICK, cur)
            speak(_("Clicked {name}").format(name=cur.name))
            # The click likely changed the screen (new menu / view): re-analyze
            # automatically so the buffer reflects what is now shown.
            self.mode.refresh_current_scope(delay_ms=600)
            return True
        return False

    def back(self):
        _press('escape'); _release('escape')
        return True

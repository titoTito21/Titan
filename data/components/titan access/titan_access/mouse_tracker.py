# -*- coding: utf-8 -*-
"""The mouse, followed: what is under the pointer, said as it moves.

A reader that answers only the keyboard leaves half the desktop silent -
whatever a sighted helper points at, whatever the user finds by feel on
a touchpad. With ``Mouse/TrackMouse`` on, the control under the pointer
is read when the pointer comes to rest on it (``Mouse/MouseDelayMs``),
either as the control (``SpeakUnderMouse`` = object) or as the text at
that point - a character, a word, a line - where the control has text.
``Mouse/AudioCoordinates`` plays a tone as the pointer moves - higher
towards the top of the screen, panned left to right - so the pointer's
place is heard without a word; ``AudioCoordinatesByBrightness`` makes
the tone louder over a bright pixel.

**Polled, not hooked.** A WH_MOUSE_LL hook needs a thread that answers
Windows on a deadline (the keyboard hook has a DLL for that); the
pointer's position is one cheap call and twenty of them a second are
nothing. On Linux the position is asked of X (python-xlib), the control
of AT-SPI through the provider, exactly as on Windows through UIA.
"""

import os
import sys
import threading
import time

_IS_WINDOWS = sys.platform.startswith('win')

POLL_S = 0.05
TONE_EVERY_S = 0.06
MOVED_PX = 3


class MouseTracker(object):

    def __init__(self, engine):
        self.engine = engine
        self._thread = None
        self._stop = threading.Event()
        self._last_key = None
        self._counted = {'reads': 0, 'said': 0, 'tones': 0}
        self._xlib = None

    # ------------------------------------------------------------------ #
    def report(self):
        found = dict(self._counted)
        found['running'] = self.running
        return found

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='TitanAccessMouse',
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive() and \
                thread is not threading.current_thread():
            thread.join(timeout=1.0)

    # ------------------------------------------------------------------ #
    # The settings, read per poll (a dict lookup each)
    # ------------------------------------------------------------------ #
    def _setting(self, key, default):
        try:
            settings = self.engine.settings
            if isinstance(default, bool):
                return settings.get_bool('Mouse', key, default)
            if isinstance(default, int):
                return settings.get_int('Mouse', key, default)
            return str(settings.get('Mouse', key, default) or default)
        except Exception:                            # noqa: BLE001
            return default

    def wanted(self):
        return self._setting('TrackMouse', False)

    # ------------------------------------------------------------------ #
    # The pointer
    # ------------------------------------------------------------------ #
    def pointer(self):
        """``(x, y)`` in screen pixels, or None."""
        if _IS_WINDOWS:
            try:
                import ctypes
                from ctypes import wintypes
                point = wintypes.POINT()
                if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                    return int(point.x), int(point.y)
            except Exception:                        # noqa: BLE001
                return None
            return None
        try:
            if self._xlib is None:
                from Xlib import display
                self._xlib = display.Display()
            root = self._xlib.screen().root
            found = root.query_pointer()
            return int(found.root_x), int(found.root_y)
        except Exception:                            # noqa: BLE001
            self._xlib = None
            return None

    def screen_size(self):
        if _IS_WINDOWS:
            try:
                import ctypes
                u = ctypes.windll.user32
                return int(u.GetSystemMetrics(0)) or 1, int(u.GetSystemMetrics(1)) or 1
            except Exception:                        # noqa: BLE001
                return 1, 1
        try:
            if self._xlib is None:
                from Xlib import display
                self._xlib = display.Display()
            screen = self._xlib.screen()
            return int(screen.width_in_pixels) or 1, int(screen.height_in_pixels) or 1
        except Exception:                            # noqa: BLE001
            return 1, 1

    def brightness_at(self, x, y):
        """0..1 of the pixel under the pointer; 1 where it cannot be read."""
        if not _IS_WINDOWS:
            return 1.0
        try:
            import ctypes
            u, g = ctypes.windll.user32, ctypes.windll.gdi32
            dc = u.GetDC(0)
            try:
                g.GetPixel.restype = ctypes.c_ulong
                color = int(g.GetPixel(dc, int(x), int(y)))
            finally:
                u.ReleaseDC(0, dc)
            if color == 0xFFFFFFFF:
                return 1.0
            r, gr, b = color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF
            return (0.299 * r + 0.587 * gr + 0.114 * b) / 255.0
        except Exception:                            # noqa: BLE001
            return 1.0

    # ------------------------------------------------------------------ #
    # The loop
    # ------------------------------------------------------------------ #
    def _loop(self):
        last = None
        moved_at = 0.0
        unread = False
        last_tone = 0.0
        while not self._stop.wait(POLL_S):
            if not self.wanted():
                continue
            here = self.pointer()
            if here is None:
                continue
            now = time.time()
            if last is None or abs(here[0] - last[0]) >= MOVED_PX \
                    or abs(here[1] - last[1]) >= MOVED_PX:
                last = here
                moved_at = now
                unread = True
                if self._setting('AudioCoordinates', False) and \
                        now - last_tone >= TONE_EVERY_S:
                    last_tone = now
                    self._tone(*here)
                continue
            delay = self._setting('MouseDelayMs', 100) / 1000.0
            if unread and now - moved_at >= delay:
                unread = False
                try:
                    self._read(*here)
                except Exception as error:           # noqa: BLE001
                    print('[TitanAccess] mouse: %s' % error)

    def _tone(self, x, y):
        sound = getattr(self.engine, 'sound', None)
        if sound is None or not hasattr(sound, 'play_tone'):
            return
        width, height = self.screen_size()
        pan = max(-1.0, min(1.0, (x / float(width)) * 2.0 - 1.0))
        frequency = 1200.0 - (y / float(height)) * 950.0
        gain = 0.4
        if self._setting('AudioCoordinatesByBrightness', False):
            gain = 0.1 + 0.6 * self.brightness_at(x, y)
        self._counted['tones'] += 1
        try:
            sound.play_tone(frequency, 30, pan=pan, gain=gain)
        except Exception:                            # noqa: BLE001
            pass

    def _read(self, x, y):
        self._counted['reads'] += 1
        obj = self.engine._object_at_point(x, y)
        if obj is None:
            return
        if self._setting('IgnoreMouseInsideTitan', True):
            pid = int(getattr(obj, 'process_id', 0) or 0)
            if pid == os.getpid():
                return
        mode = self._setting('SpeakUnderMouse', 'object').lower()
        if mode in ('char', 'word', 'line'):
            text = self.text_at(obj, x, y, mode)
            if text is not None:
                key = ('text', mode, text)
                if key == self._last_key:
                    return
                self._last_key = key
                if text.strip():
                    self._counted['said'] += 1
                    try:
                        from titan_access import symbols
                        text = symbols.text_for_speech(text, self.engine.settings)
                    except Exception:                # noqa: BLE001
                        pass
                    self.engine.speak(text, obj=obj, interrupt=True)
                return
        key = (getattr(obj, 'role', ''), getattr(obj, 'name', ''),
               getattr(obj, 'bounds', None))
        if key == self._last_key:
            return
        self._last_key = key
        self._counted['said'] += 1
        self.engine.announce_object(obj, for_navigation=True)

    # ------------------------------------------------------------------ #
    # The text at a point
    # ------------------------------------------------------------------ #
    @staticmethod
    def text_at(obj, x, y, unit='word'):
        """The character, word or line at a screen point of a control with
        text - UIA's TextPattern on Windows, AT-SPI's Text on Linux - or
        None where the control has none (the caller reads the control)."""
        native = getattr(obj, 'native', None)
        if native is None:
            return None
        if _IS_WINDOWS:
            try:
                import uiautomation as auto
                pattern = native.GetTextPattern()
                if pattern is None:
                    return None
                rng = pattern.RangeFromPoint(auto.Point(int(x), int(y)))
                if rng is None:
                    return None
                wanted = {'char': auto.TextUnit.Character,
                          'word': auto.TextUnit.Word,
                          'line': auto.TextUnit.Line}[unit]
                rng.ExpandToEnclosingUnit(wanted)
                return str(rng.GetText(512) or '')
            except Exception:                        # noqa: BLE001
                return None
        try:
            from titan_access import atspi_focus
            if not atspi_focus.is_accessible(native):
                return None
            text = atspi_focus.TextOf.of(native)
            if text is None:
                return None
            Atspi = atspi_focus.atspi()
            iface = native.get_text_iface() if hasattr(native, 'get_text_iface') else native
            offset = int(iface.get_offset_at_point(int(x), int(y),
                                                   Atspi.CoordType.SCREEN))
            if offset < 0:
                return None
            content, _s, _e = text.unit(offset, unit)
            return str(content or '')
        except Exception:                            # noqa: BLE001
            return None

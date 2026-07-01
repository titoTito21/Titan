# -*- coding: utf-8 -*-
"""Terminal / console application module.

Modelled on NVDA's console support (``NVDAObjects/UIA/winConsoleUIA.py`` and the
review-cursor / ``textInfos`` model), NOT on the old C# port. It gives Titan
Access two things for terminals (cmd, PowerShell, Windows Terminal, conhost,
PuTTY, mintty, ...):

1. **Automatic output reading.** A background poller reads the terminal's text
   through the UI Automation ``TextPattern`` (the same interface NVDA's
   ``winConsoleUIA`` uses) and speaks newly appended lines as they appear, so
   command output is announced without any key press.

2. **Screen review.** The ``-`` (minus) key toggles a screen-review cursor.
   While review is on, the arrow keys walk the terminal buffer without moving the
   real caret: Up/Down = previous/next line, Left/Right = previous/next
   character, PageUp/PageDown = a screenful at a time, Home/End = start/end of the
   line. Each line movement also plays a short synthetic beep whose pitch encodes
   the line's vertical position on the screen -- higher line, higher beep -- like
   an audio game. Escape (or minus again) leaves review.

Design constraints copied from the rest of Titan Access:

* All UI Automation work happens on the module's own background thread (MTA COM),
  never on the keyboard-hook thread -- a blocking ``GetText`` there would stall
  the global ``WH_KEYBOARD_LL`` hook. :meth:`handle_plain_key` therefore only
  ever touches an in-memory snapshot of the lines, which the poller keeps fresh.
* Everything degrades gracefully: no UIA / no text pattern -> the module simply
  never engages review and the keys pass through unchanged.
"""

import ctypes
import os
import threading
import time

from titan_access.localization import L
from titan_access import localization as loc
from titan_access.app_modules.base import AppModuleBase
from titan_access.contracts import (
    SND_VSCREEN_ON, SND_VSCREEN_OFF, SND_EDGE, SND_CURSOR,
)

# --- defensive UIA import (module must import even without UIA) ------------- #
try:
    import uiautomation as auto
    _UIA = True
except Exception as _e:  # pragma: no cover
    print(f"[TitanAccess] terminal: uiautomation unavailable: {_e}")
    auto = None
    _UIA = False

# Beep frequency range for the line-position cue (top of screen = high pitch,
# bottom = low pitch). Kept inside a comfortable, distinct band.
_FREQ_TOP = 1650.0
_FREQ_BOTTOM = 420.0
_BEEP_MS = 22          # short, as requested -- never masks speech

_DEFAULT_VISIBLE = 25  # fallback screen height when the viewport is unknown


class TerminalModule(AppModuleBase):
    """Console / terminal support with auto output reading + screen review."""

    #: Every terminal-ish executable this one module serves (lower-case, no ext).
    process_names = {
        "cmd", "powershell", "pwsh", "conhost", "openconsole",
        "windowsterminal", "wt", "windowsterminalpreview",
        "putty", "kitty", "mintty", "bash", "wsl", "wslhost",
        "cmder", "conemu", "conemu64", "alacritty", "hyper",
    }
    process_name = "cmd"     # primary key (used for app_name / gestures)

    def __init__(self, engine):
        super().__init__(engine)
        # Screen-review state (all guarded by ``_lock``).
        self._lock = threading.RLock()
        self._review = False
        self._lines = []            # current buffer snapshot (list[str])
        self._visible = _DEFAULT_VISIBLE
        self._row = 0
        self._col = 0

        # Auto-read bookkeeping.
        self.auto_read = True
        self._last_tail = ""        # last non-blank line we announced
        self._last_full_sig = None  # cheap change detector for the whole buffer

        # Background UIA poller (single reader thread; MTA COM).
        self._poll_thread = None
        self._poll_stop = threading.Event()
        self._wake = threading.Event()
        self._active = False        # our terminal is the foreground app

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #
    @property
    def app_name(self):
        return L("terminal.appName")

    def matches(self, process_name):
        return bool(process_name) and process_name.lower() in self.process_names

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def on_gain_focus(self, obj):
        self._active = True
        self._ensure_poller()
        self._wake.set()          # refresh the snapshot promptly

    def on_lose_focus(self, obj):
        # Leaving the terminal cancels review and pauses the poller.
        self._active = False
        if self._review:
            self._set_review(False, announce=False)
        super().on_lose_focus(obj)

    def _ensure_poller(self):
        if self._poll_thread is not None and self._poll_thread.is_alive():
            return
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="TitanAccessTerminal", daemon=True)
        self._poll_thread.start()

    # ------------------------------------------------------------------ #
    # Plain-key layer (runs on the keyboard-hook thread -> must be fast)
    # ------------------------------------------------------------------ #
    def handle_plain_key(self, vk, key_name, ctrl, alt, shift):
        # Ctrl/Alt combinations are application shortcuts -- never ours.
        if ctrl or alt:
            return False
        # NumPad minus toggles screen review (works whether it is on or off),
        # mirroring how NumPad minus toggles the dial elsewhere. The engine gives
        # us first claim on it while a terminal is focused (see
        # engine.on_modifier_gesture), so it no longer toggles the dial here and
        # a literal "-" still types normally in the shell.
        if key_name == "numpadsubtract":
            self._ensure_poller()
            self._set_review(not self._review)
            return True
        if not self._review:
            return False
        # --- review is active: drive the review cursor --------------------- #
        if key_name == "escape":
            self._set_review(False)
            return True
        if key_name == "up":
            self._move_line(-1)
            return True
        if key_name == "down":
            self._move_line(+1)
            return True
        if key_name == "left":
            self._move_char(-1)
            return True
        if key_name == "right":
            self._move_char(+1)
            return True
        if key_name == "pageup":
            self._move_page(-1)
            return True
        if key_name == "pagedown":
            self._move_page(+1)
            return True
        if key_name == "home":
            self._move_home_end(False)
            return True
        if key_name == "end":
            self._move_home_end(True)
            return True
        # Any other key while review is on falls through to the application.
        return False

    # ------------------------------------------------------------------ #
    # Review mode toggle
    # ------------------------------------------------------------------ #
    def _set_review(self, on, announce=True):
        with self._lock:
            self._review = bool(on)
            if on:
                # Anchor the review cursor on the bottom-most non-blank line
                # (where the live prompt / latest output sits), like entering
                # review at the caret.
                lines = self._lines
                self._row = self._last_content_row(lines)
                self._col = 0
        if not announce:
            return
        if on:
            self.engine.play(SND_VSCREEN_ON)
            self.engine.speak(L("terminal.reviewOn"))
            with self._lock:
                lines, row = self._lines, self._row
            if lines:
                self._announce_line(row, lines, beep=True, interrupt=False)
            else:
                self.engine.speak(L("terminal.noText"), interrupt=False)
        else:
            self.engine.play(SND_VSCREEN_OFF)
            self.engine.speak(L("terminal.reviewOff"))

    # ------------------------------------------------------------------ #
    # Review navigation (in-memory; no UIA here)
    # ------------------------------------------------------------------ #
    def _move_line(self, delta):
        with self._lock:
            lines = self._lines
            if not lines:
                self.engine.speak(L("terminal.noText"))
                return
            new = self._row + delta
            if new < 0:
                self.engine.play(SND_EDGE)
                self.engine.speak(L("terminal.top"))
                return
            if new >= len(lines):
                self.engine.play(SND_EDGE)
                self.engine.speak(L("terminal.bottom"))
                return
            self._row = new
            self._col = 0
        self._announce_line(new, lines, beep=True)

    def _move_page(self, direction):
        with self._lock:
            lines = self._lines
            if not lines:
                self.engine.speak(L("terminal.noText"))
                return
            step = max(1, self._visible) * (1 if direction > 0 else -1)
            new = self._row + step
            edge = None
            if new < 0:
                new, edge = 0, "top"
            elif new >= len(lines):
                new, edge = len(lines) - 1, "bottom"
            self._row = new
            self._col = 0
        if edge:
            self.engine.play(SND_EDGE)
        self._announce_line(new, lines, beep=True)

    def _move_char(self, delta):
        with self._lock:
            lines = self._lines
            if not lines:
                self.engine.speak(L("terminal.noText"))
                return
            text = lines[self._row] if 0 <= self._row < len(lines) else ""
            if not text:
                self.engine.speak(L("terminal.blankLine"))
                return
            new = self._col + delta
            if new < 0 or new >= len(text):
                self.engine.play(SND_EDGE)
                self.engine.speak(L("terminal.top") if delta < 0
                                  else L("terminal.bottom"))
                return
            self._col = new
            ch = text[new]
        self.engine.speak(loc.character_announcement(ch, use_phonetic=False))

    def _move_home_end(self, to_end):
        with self._lock:
            lines = self._lines
            if not lines or not (0 <= self._row < len(lines)):
                return
            text = lines[self._row]
            if not text:
                self.engine.speak(L("terminal.blankLine"))
                return
            self._col = (len(text) - 1) if to_end else 0
            ch = text[self._col]
        self.engine.speak(loc.character_announcement(ch, use_phonetic=False))

    def _announce_line(self, row, lines, beep=True, interrupt=True):
        if beep:
            self._play_position_beep(row)
        text = lines[row] if 0 <= row < len(lines) else ""
        if text.strip():
            self.engine.speak(text, interrupt=interrupt)
        else:
            self.engine.speak(L("terminal.blankLine"), interrupt=interrupt)

    def _play_position_beep(self, row):
        """Beep pitched by the line's vertical position on its screen page.

        The top line of a screenful is the highest pitch, the bottom line the
        lowest; PageUp/PageDown step exactly one page so the pattern repeats,
        giving a consistent "where am I on the screen" cue across scrollback."""
        vis = max(2, self._visible)
        within = row % vis
        frac = within / float(vis - 1)          # 0.0 top .. 1.0 bottom
        freq = _FREQ_TOP - frac * (_FREQ_TOP - _FREQ_BOTTOM)
        sound = getattr(self.engine, "sound", None)
        if sound is not None and hasattr(sound, "play_tone"):
            try:
                sound.play_tone(freq, _BEEP_MS)
            except Exception as e:
                print(f"[TitanAccess] terminal beep error: {e}")

    @staticmethod
    def _last_content_row(lines):
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                return i
        return max(0, len(lines) - 1)

    # ------------------------------------------------------------------ #
    # Background poller (the ONLY place UIA is touched)
    # ------------------------------------------------------------------ #
    def _poll_loop(self):
        if not _UIA:
            return
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # MTA
        except Exception:
            pass
        element = None
        last_hwnd = 0
        try:
            while not self._poll_stop.is_set():
                # Wait up to ~150 ms, or wake immediately on a review toggle.
                self._wake.wait(0.15)
                self._wake.clear()
                # Gate purely on the foreground being one of our terminals, so
                # auto-read / review work even for a bare console that fired no
                # UIA focus event (``_active`` may never have been set for it).
                if not self._is_our_terminal_foreground():
                    element = None
                    continue
                try:
                    hwnd = _foreground_hwnd()
                    if element is None or hwnd != last_hwnd:
                        element = self._find_terminal_element(hwnd)
                        last_hwnd = hwnd
                    if element is None:
                        continue
                    text, visible = self._read_text(element)
                except Exception:
                    element = None
                    continue
                if text is None:
                    continue
                self._on_new_text(text, visible)
        finally:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass

    def _on_new_text(self, text, visible):
        # Normalise into lines; keep internal blanks, drop the trailing blank
        # padding the console pads every screen with.
        raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        lines = [ln.rstrip() for ln in raw]
        while lines and not lines[-1].strip():
            lines.pop()
        sig = (len(lines), hash("\n".join(lines[-40:])))
        changed = sig != self._last_full_sig
        with self._lock:
            self._lines = lines
            if visible:
                self._visible = max(2, min(120, visible))
            # Clamp the review cursor into the new buffer.
            if self._row >= len(lines):
                self._row = max(0, len(lines) - 1)
        if not changed:
            return
        self._last_full_sig = sig
        # Auto-read appended output (never while reviewing -- the user is
        # reading manually then). The poller only reaches here when one of our
        # terminals is the foreground window, so no extra active-check is needed.
        if self.auto_read and not self._review:
            self._speak_appended(lines)

    def _speak_appended(self, lines):
        """Speak lines that appeared at the bottom since the last announcement."""
        content = [ln for ln in lines if ln.strip()]
        if not content:
            return
        new = []
        if self._last_tail and self._last_tail in content:
            # Everything after the last line we spoke is fresh output.
            idx = len(content) - 1 - content[::-1].index(self._last_tail)
            new = content[idx + 1:]
        else:
            # First read (or the anchor scrolled away): announce only the last
            # couple of lines so we do not read the whole screen aloud.
            new = content[-2:]
        self._last_tail = content[-1]
        for i, line in enumerate(new[:25]):
            self.engine.speak(line, interrupt=False)

    # ------------------------------------------------------------------ #
    # UIA text acquisition (poller thread only)
    # ------------------------------------------------------------------ #
    def _read_text(self, element):
        """Return ``(text, visible_line_count)`` from a text-pattern element."""
        try:
            tp = element.GetTextPattern()
        except Exception:
            tp = None
        if tp is None:
            return None, 0
        text = None
        try:
            text = tp.DocumentRange.GetText(-1)
        except Exception:
            return None, 0
        # Visible screen height = number of text rows currently on screen.
        # ``GetVisibleRanges`` returns the visible spans (often a single
        # contiguous range covering the whole viewport), so the row count is the
        # number of line breaks in that visible text, not the number of ranges.
        visible = 0
        try:
            ranges = tp.GetVisibleRanges() or []
            vis_text = ""
            for r in ranges:
                try:
                    vis_text += r.GetText(-1)
                except Exception:
                    pass
            vt = vis_text.replace("\r\n", "\n").replace("\r", "\n")
            if vt:
                visible = vt.count("\n") + 1
        except Exception:
            visible = 0
        return text, visible

    def _find_terminal_element(self, hwnd):
        """Find the element carrying the console text (largest TextPattern).

        Works for Windows Terminal (a ``TermControl`` TextControl), classic
        conhost (the console window itself supports TextPattern) and other UIA
        terminals. Bounded so a deep tree never stalls the poller."""
        if not _UIA:
            return None
        roots = []
        try:
            if hwnd:
                roots.append(auto.ControlFromHandle(hwnd))
        except Exception:
            pass
        try:
            roots.append(auto.GetFocusedControl())
        except Exception:
            pass
        best = None
        best_len = 0
        seen = 0
        from collections import deque
        for root in roots:
            if root is None:
                continue
            queue = deque([(root, 0)])
            while queue:
                node, depth = queue.popleft()
                if depth > 12:
                    continue
                seen += 1
                if seen > 600:
                    break
                try:
                    tp = node.GetTextPattern()
                except Exception:
                    tp = None
                if tp is not None:
                    try:
                        txt = tp.DocumentRange.GetText(400)
                        n = len(txt or "")
                    except Exception:
                        n = 0
                    # Prefer the console text area: a TermControl or a large
                    # buffer beats tiny chrome labels (tab titles / icons).
                    cls = ""
                    try:
                        cls = (node.ClassName or "").lower()
                    except Exception:
                        pass
                    if cls == "termcontrol":
                        return node
                    if n > best_len:
                        best_len, best = n, node
                try:
                    for c in node.GetChildren() or []:
                        queue.append((c, depth + 1))
                except Exception:
                    pass
            if best is not None:
                return best
        return best

    # ------------------------------------------------------------------ #
    # Foreground gating
    # ------------------------------------------------------------------ #
    def _is_our_terminal_foreground(self):
        pid = _foreground_pid()
        if not pid:
            return False
        return _process_name_for_pid(pid) in self.process_names


# =========================================================================== #
# Win32 helpers (defensive; never raise)
# =========================================================================== #
def _foreground_hwnd():
    try:
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def _foreground_pid():
    try:
        import ctypes.wintypes as wt
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def _process_name_for_pid(pid):
    if not pid:
        return ""
    try:
        import ctypes.wintypes as wt
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        k = ctypes.windll.kernel32
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wt.DWORD(512)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.splitext(os.path.basename(buf.value))[0].lower()
        finally:
            k.CloseHandle(h)
    except Exception:
        pass
    return ""

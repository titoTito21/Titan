"""
Titan Talk - shared core
========================

Common pieces used by every Titan Talk scope: the :class:`Control` descriptor,
the :class:`Scope` base class (spatial arrow navigation, A/B handling), and the
small helpers for stereo panning, role labelling and the SRE sound effects.

All modules in the package share a single gettext ``_`` (domain ``titan_talk``)
imported from here, so there is exactly one translation domain for the mode.
"""

import sys
import time
import ctypes
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from src.controller.gamepad_mode_api import setup_mode_translations, speak, play_mode_sound

# Single shared translation function for the whole package.
_ = setup_mode_translations(__file__, 'titan_talk')

# A control is announced in three voices so the parts are distinguishable
# (user spec): the NAME at the normal pitch, the control TYPE in a lower tone,
# the STATE / value in a higher tone.
NAME_PITCH = 0
ROLE_PITCH = -4
STATE_PITCH = 4

# Screen-reader sound set bundled in sfx/<theme>/SRE/ (the user pointed these
# out: "odpowiednie dzwieki sa w default/sre").
SND_CURSOR = 'SRE/cursor.ogg'      # moved to another control
SND_EDGE = 'SRE/edge.ogg'          # hit the edge of the list (no move)
SND_CLICK = 'SRE/clicked.ogg'      # activated a control (A)
SND_WINDOW = 'SRE/window.ogg'      # scope / window change
SND_ITEM = 'SRE/listitem.ogg'      # generic list item


# --------------------------------------------------------------------------- #
# Control descriptor
# --------------------------------------------------------------------------- #
@dataclass
class Control:
    """One navigable on-screen control.

    ``cx``/``cy`` are the control's centre in screen pixels (used for spatial
    navigation and stereo panning). ``role`` is one of the keys in
    :data:`ROLE_LABELS`. ``state`` is an optional already-resolved key such as
    ``checked``/``unchecked``. ``payload`` carries whatever the owning scope
    needs to activate the control (a UIA element, a window handle, a click
    point, ...).
    """
    name: str
    role: str = 'text'
    state: Optional[str] = None
    cx: float = 0.0
    cy: float = 0.0
    payload: Any = None
    value: Optional[str] = None  # e.g. slider value text
    #: Grouping container as ``(key, label)``: ``key`` identifies the container
    #: (so entering/leaving it can be detected) and ``label`` is what to speak,
    #: e.g. ("list:0x2A", "Application list"). None for top-level controls.
    container: Optional[tuple] = None


# Role / state labels -> spoken text. Kept here so every scope speaks the same
# words for the same kind of control.
def role_label(role: str) -> str:
    return {
        'button': _("button"),
        'edit': _("edit field"),
        'slider': _("slider"),
        'checkbox': _("check box"),
        'radio': _("radio button"),
        'combobox': _("combo box"),
        'menuitem': _("menu item"),
        'listitem': _("list item"),
        'tab': _("tab"),
        'link': _("link"),
        'window': _("window"),
        'text': _("text"),
        'image': _("graphic"),
    }.get(role, role)


def state_label(state: str) -> str:
    return {
        'checked': _("checked"),
        'unchecked': _("not checked"),
        'expanded': _("expanded"),
        'collapsed': _("collapsed"),
        'selected': _("selected"),
        'focused': _("focused"),
    }.get(state, state)


# --------------------------------------------------------------------------- #
# Screen helpers
# --------------------------------------------------------------------------- #
def screen_size():
    """Primary screen (width, height) in pixels."""
    try:
        u = ctypes.windll.user32
        return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


def foreground_window():
    """(hwnd, title) of the current foreground window, or (0, '')."""
    try:
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return 0, ''
        length = u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        u.GetWindowTextW(hwnd, buf, length + 1)
        return int(hwnd), (buf.value or '')
    except Exception:
        return 0, ''


def pan_for_x(cx: float) -> float:
    """Map a screen x coordinate to a stereo pan value -1.0 .. 1.0."""
    w, _h = screen_size()
    if w <= 0:
        return 0.0
    return max(-1.0, min(1.0, (cx / w) * 2.0 - 1.0))


def elevation_for_y(cy: float) -> float:
    """Map a screen y coordinate to elevation 1.0 (top) .. -1.0 (bottom).

    Only used by the 3D sound mode; the convention matches invisibleui /
    klangomode (top = up, bottom = down).
    """
    _w, h = screen_size()
    if h <= 0:
        return 0.0
    return max(-1.0, min(1.0, 1.0 - 2.0 * (cy / h)))


def play_positioned(path, control):
    """Play a UI sound panned (and elevated in 3D) to a control's position.

    Honours the host sound mode: centered when positioning is off, panned in
    stereo, full HRTF azimuth + elevation in 3D - exactly like the spoken
    announcement, so the click / cursor sound comes from where the control is.
    """
    if control is None:
        play_mode_sound(path)
        return
    play_mode_sound(path, pan=pan_for_x(control.cx),
                    elevation=elevation_for_y(control.cy))


# --------------------------------------------------------------------------- #
# Sequential pitched announcer
# --------------------------------------------------------------------------- #
# A control is read as several segments at DIFFERENT pitches (name / type /
# state). The stereo / Titan TTS path always interrupts the previous utterance,
# so the segments cannot simply be queued - they must be spoken one after
# another. We do that on a background thread, waiting for each segment to finish
# before starting the next. A newer announcement bumps a sequence id so fast
# stick navigation cleanly supersedes an in-flight one (its name segment
# interrupts whatever is currently playing).
_seq_lock = threading.Lock()
_seq_id = 0


def _mode_manager():
    try:
        from src.controller.controller_modes import get_mode_manager
        return get_mode_manager()
    except Exception:
        return None


def pitched_speech_active() -> bool:
    """True when the Titan TTS / stereo path (which supports pitch) is active.

    When Titan TTS is OFF the manager speaks through accessible_output3, which
    has no pitch control - so callers should announce a single plain line
    instead of separate pitched segments.
    """
    m = _mode_manager()
    return bool(m and getattr(m, 'stereo_enabled', False)
                and getattr(m, 'stereo_speech', None))


def _wait_for_speech(manager, text, my_id):
    """Block until the current segment finishes (or a newer one supersedes)."""
    est = min(2.5, 0.28 + len(text) / 16.0)
    speech = getattr(manager, 'stereo_speech', None) if manager else None
    use_flag = (manager is not None and getattr(manager, 'stereo_enabled', False)
                and speech is not None and hasattr(speech, 'is_speaking'))
    time.sleep(0.06)  # let playback start
    if use_flag:
        deadline = time.time() + est + 1.5
        while time.time() < deadline:
            with _seq_lock:
                if my_id != _seq_id:
                    return
            if not getattr(speech, 'is_speaking', False):
                return
            time.sleep(0.03)
    else:
        slept = 0.0
        while slept < est:
            with _seq_lock:
                if my_id != _seq_id:
                    return
            time.sleep(0.05)
            slept += 0.05


def _run_segments(my_id, segments):
    manager = _mode_manager()
    first = True
    for text, pitch, position in segments:
        if not text:
            continue
        with _seq_lock:
            if my_id != _seq_id:
                return
        # Every segment interrupts: the first cuts off the previous control,
        # the rest are spoken back-to-back after _wait_for_speech.
        speak(text, position=position, interrupt=True, pitch_offset=pitch)
        first = False
        _wait_for_speech(manager, text, my_id)


def speak_segments(segments):
    """Speak ``(text, pitch_offset, position)`` segments sequentially.

    Each segment is fully spoken before the next at its own pitch. Calling again
    supersedes any in-flight sequence, so rapid navigation stays responsive.
    """
    global _seq_id
    segments = [s for s in segments if s and s[0]]
    if not segments:
        return
    with _seq_lock:
        _seq_id += 1
        my_id = _seq_id
    threading.Thread(target=_run_segments, args=(my_id, segments),
                     daemon=True).start()


# --------------------------------------------------------------------------- #
# Scope base class
# --------------------------------------------------------------------------- #
class Scope:
    """Base class for a Titan Talk navigation scope (a bumper "tab").

    A scope owns a flat list of :class:`Control` objects and a cursor into it.
    The orchestrator drives it: arrows -> :meth:`navigate`, A -> :meth:`activate`,
    B -> :meth:`back`. Override :meth:`refresh` to (re)build ``self.controls``.
    """

    #: stable id, also the gettext-able display name key
    id = ''

    def __init__(self, mode):
        self.mode = mode
        self.controls: List[Control] = []
        self.index = 0

    # -- identity ----------------------------------------------------------- #
    def display_name(self) -> str:
        return self.id

    # -- content ------------------------------------------------------------ #
    def refresh(self):
        """Rebuild ``self.controls`` from the live UI. Override in subclasses."""
        self.controls = []

    def available(self) -> bool:
        """Whether this scope can run (deps present, etc.). Override if needed."""
        return True

    def current(self) -> Optional[Control]:
        if 0 <= self.index < len(self.controls):
            return self.controls[self.index]
        return None

    # -- lifecycle ---------------------------------------------------------- #
    def on_enter(self, announce=True):
        self.refresh()
        self.index = 0 if self.controls else -1
        if announce:
            self.mode.announce_scope_enter(self)

    def on_leave(self):
        pass

    # -- navigation --------------------------------------------------------- #
    def navigate(self, dx: int, dy: int) -> bool:
        """Spatially move the cursor. dx: -1 left/+1 right; dy: -1 up/+1 down.

        Returns True if the cursor moved. Picks the nearest control in the
        requested direction (primary-axis distance + off-axis penalty), the
        classic 2-D screen-reader spatial walk.
        """
        cur = self.current()
        if cur is None or len(self.controls) < 2:
            return False
        best_i, best_score = -1, None
        for i, c in enumerate(self.controls):
            if i == self.index:
                continue
            ddx, ddy = c.cx - cur.cx, c.cy - cur.cy
            if dx == -1 and ddx >= -1:
                continue
            if dx == 1 and ddx <= 1:
                continue
            if dy == -1 and ddy >= -1:
                continue
            if dy == 1 and ddy <= 1:
                continue
            if dx != 0:
                primary, off = abs(ddx), abs(ddy)
            else:
                primary, off = abs(ddy), abs(ddx)
            score = primary + off * 2.0
            if best_score is None or score < best_score:
                best_score, best_i = score, i
        if best_i < 0:
            return False
        self.index = best_i
        return True

    # -- actions ------------------------------------------------------------ #
    def activate(self) -> bool:
        """Handle the A button on the current control. Override."""
        return False

    def back(self) -> bool:
        """Handle the B button. Default: re-announce the current control."""
        return False

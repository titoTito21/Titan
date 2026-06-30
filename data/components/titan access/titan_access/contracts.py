# -*- coding: utf-8 -*-
"""Shared contracts for Titan Access modules.

This module is the single source of truth for the data types and interfaces that
the orchestrator (:mod:`titan_access.engine`) and the subsystem modules
(speech, sound, UIA, accessible, keyboard, editable text, browse mode, app
modules, settings panel) exchange. Every module codes against these so they stay
decoupled and independently testable.

Nothing here imports Titan internals or any heavy library, so it is safe to
import everywhere (including standalone).
"""

import ctypes
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Protocol, Set, Tuple


# =========================================================================== #
# Role / state vocabularies
# =========================================================================== #
# Canonical role keys. Localised labels live in :mod:`titan_access.localization`
# and are resolved by :mod:`titan_access.accessible`. UIA ControlType / MSAA
# role mapping is done in the accessibility providers.
ROLE_BUTTON = "button"
ROLE_SPLIT_BUTTON = "split_button"
ROLE_EDIT = "edit"
ROLE_PASSWORD = "password"
ROLE_DOCUMENT = "document"
ROLE_CHECKBOX = "checkbox"
ROLE_RADIO = "radio"
ROLE_COMBOBOX = "combobox"
ROLE_LISTBOX = "list"
ROLE_LISTITEM = "listitem"
ROLE_TREE = "tree"
ROLE_TREEITEM = "treeitem"
ROLE_MENU = "menu"
ROLE_MENUBAR = "menubar"
ROLE_MENUITEM = "menuitem"
ROLE_TAB = "tab"
ROLE_TABCONTROL = "tabcontrol"
ROLE_SLIDER = "slider"
ROLE_SPINNER = "spinner"
ROLE_PROGRESSBAR = "progressbar"
ROLE_SCROLLBAR = "scrollbar"
ROLE_LINK = "link"
ROLE_TEXT = "text"
ROLE_HEADING = "heading"
ROLE_IMAGE = "image"
ROLE_TABLE = "table"
ROLE_ROW = "row"
ROLE_CELL = "cell"
ROLE_TOOLBAR = "toolbar"
ROLE_STATUSBAR = "statusbar"
ROLE_GROUP = "group"
ROLE_DIALOG = "dialog"
ROLE_WINDOW = "window"
ROLE_PANE = "pane"
ROLE_SEPARATOR = "separator"
ROLE_GRID = "grid"
ROLE_GRIDITEM = "griditem"
ROLE_HYPERLINK = "link"
ROLE_UNKNOWN = "unknown"

# Canonical state keys (a control may carry several).
STATE_CHECKED = "checked"
STATE_UNCHECKED = "unchecked"
STATE_PARTIAL = "partially_checked"
STATE_EXPANDED = "expanded"
STATE_COLLAPSED = "collapsed"
STATE_SELECTED = "selected"
STATE_UNAVAILABLE = "unavailable"      # disabled / grayed
STATE_FOCUSED = "focused"
STATE_READONLY = "readonly"
STATE_REQUIRED = "required"
STATE_PRESSED = "pressed"
STATE_BUSY = "busy"
STATE_HASPOPUP = "haspopup"
STATE_PROTECTED = "protected"          # password fields


# =========================================================================== #
# AccessibleObject — a snapshot of one UI element
# =========================================================================== #
@dataclass
class AccessibleObject:
    """A flattened, provider-agnostic snapshot of one accessible element.

    Built by an accessibility provider (UIA primary; MSAA/IA2/Java later) from a
    live element. The orchestrator turns it into an announcement via
    :func:`titan_access.accessible.describe`. ``native`` keeps the live provider
    element so actions (Invoke/Toggle/SetFocus/TextPattern) can be performed.
    """

    name: str = ""
    role: str = ROLE_UNKNOWN
    value: str = ""                       # textual value (edit content, slider value...)
    description: str = ""
    help_text: str = ""
    states: Set[str] = field(default_factory=set)

    # Geometry in screen pixels (left, top, right, bottom). 0-rect => no bounds.
    bounds: Tuple[int, int, int, int] = (0, 0, 0, 0)

    # Hierarchy / collection context
    level: int = 0                        # tree/heading level (0 = unknown)
    pos_in_set: int = 0                   # 1-based index within siblings (0 = unknown)
    size_of_set: int = 0                  # sibling count (0 = unknown)

    # Identity
    automation_id: str = ""
    class_name: str = ""
    framework_id: str = ""
    process_id: int = 0
    hwnd: int = 0

    # Provider handles
    native: Any = None                    # live provider element (UIA/MSAA/...)
    provider: str = "uia"                 # which provider produced this

    # Cached parameter (e.g. link URL) resolved lazily by the provider
    parameter: str = ""

    # -- geometry helpers -------------------------------------------------- #
    @property
    def has_bounds(self) -> bool:
        l, t, r, b = self.bounds
        return (r - l) > 0 and (b - t) > 0

    @property
    def center_x(self) -> float:
        l, t, r, b = self.bounds
        return (l + r) / 2.0

    @property
    def center_y(self) -> float:
        l, t, r, b = self.bounds
        return (t + b) / 2.0

    # -- state helpers ----------------------------------------------------- #
    def has(self, state: str) -> bool:
        return state in self.states

    @property
    def is_focusable_text(self) -> bool:
        return self.role in (ROLE_EDIT, ROLE_PASSWORD, ROLE_DOCUMENT)


# =========================================================================== #
# Screen helpers (positional audio / virtual screen)
# =========================================================================== #
def screen_size() -> Tuple[int, int]:
    """Primary screen (width, height) in pixels."""
    try:
        u = ctypes.windll.user32
        return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


def pan_for_x(cx: float) -> float:
    """Map screen x -> stereo pan -1.0 (left) .. 1.0 (right)."""
    w, _h = screen_size()
    if w <= 0:
        return 0.0
    return max(-1.0, min(1.0, (cx / w) * 2.0 - 1.0))


def elevation_for_y(cy: float) -> float:
    """Map screen y -> elevation 1.0 (top) .. -1.0 (bottom) for 3D sound."""
    _w, h = screen_size()
    if h <= 0:
        return 0.0
    return max(-1.0, min(1.0, 1.0 - 2.0 * (cy / h)))


def pan_for_object(obj: Optional[AccessibleObject]) -> float:
    if obj is None or not obj.has_bounds:
        return 0.0
    return pan_for_x(obj.center_x)


def elevation_for_object(obj: Optional[AccessibleObject]) -> float:
    if obj is None or not obj.has_bounds:
        return 0.0
    return elevation_for_y(obj.center_y)


# =========================================================================== #
# Subsystem interfaces (Protocols) — what the engine relies on
# =========================================================================== #
class SpeechLike(Protocol):
    """Speech output. Implemented by :mod:`titan_access.speech_adapter`.

    Uses the configured Titan TTS engine when available (``tce_speech``), else
    ``accessible_output3``. ``position`` is a stereo pan -1..1 (the engine passes
    0.0 for normal/centered speech, or the element pan when virtual screen is on).
    ``pitch_offset`` is -10..10 (used to read name/type/state at different pitches).
    """
    def speak(self, text: str, position: float = 0.0, interrupt: bool = True,
              pitch_offset: int = 0) -> None: ...
    def speak_async(self, text: str, position: float = 0.0, interrupt: bool = True,
                    pitch_offset: int = 0) -> None: ...
    def stop(self) -> None: ...
    @property
    def is_speaking(self) -> bool: ...
    def set_rate(self, rate: int) -> None: ...
    def set_volume(self, volume: int) -> None: ...
    def set_pitch(self, pitch: int) -> None: ...


class SoundLike(Protocol):
    """UI sound output. Implemented by :mod:`titan_access.sound_manager`.

    Port of the C# ``SoundManager``: plays the OGG files bundled in the
    component ``sfx/`` folder. Sounds are ALWAYS stereo-panned to the element
    position (``pan`` -1..1), independent of the virtual-screen setting.
    """
    enabled: bool
    def play(self, name: str, pan: float = 0.0, elevation: float = 0.0,
             gain: float = 1.0) -> None: ...
    def play_positioned(self, name: str, obj: Optional[AccessibleObject]) -> None: ...
    def stop_all(self) -> None: ...


class FocusCallback(Protocol):
    def __call__(self, obj: AccessibleObject) -> None: ...


class AccessibilityProviderLike(Protocol):
    """UIA (and later MSAA/IA2) provider. See :mod:`titan_access.uia_focus`.

    Focus events are delivered on a COM thread; implementations must marshal the
    callback safely (the engine expects to receive :class:`AccessibleObject`).
    """
    def start(self) -> bool: ...
    def stop(self) -> None: ...
    def get_focused_object(self) -> Optional[AccessibleObject]: ...
    def object_from_point(self, x: int, y: int) -> Optional[AccessibleObject]: ...
    def object_from_handle(self, hwnd: int) -> Optional[AccessibleObject]: ...
    def add_focus_listener(self, callback: FocusCallback) -> None: ...


# Sound name constants (files in component sfx/) — shared so every module
# references the same asset names (port of C# SoundManager keys).
SND_SR_ON = "sron.ogg"
SND_SR_OFF = "sroff.ogg"
SND_CURSOR = "cursor.ogg"
SND_CURSOR_STATIC = "cursor_static.ogg"
SND_SR_CURSOR_ITEM = "srcursor_item.ogg"
SND_CLICK = "clicked.ogg"
SND_DOUBLE_TAP = "doubletab.ogg"
SND_EDGE = "edge.ogg"
SND_LIST_ITEM = "listitem.ogg"
SND_SYSTEM_ITEM = "system_item.ogg"
SND_CAN_INTERACT = "caninteract.ogg"
SND_ERROR = "error.ogg"
SND_NOTIFICATION = "notification.ogg"
SND_KEY_ON = "keyon.ogg"
SND_KEY_OFF = "keyoff.ogg"
SND_WINDOW = "window.ogg"
SND_MENU = "sr_menu.ogg"
SND_MENU_CLOSE = "sr_menu_close.ogg"
SND_MENU_EXPANDED = "menu_expanded.ogg"
SND_MENU_CLOSED = "menu_closed.ogg"
SND_ENTER_TCE = "enter_TCE.ogg"
SND_LEAVE_TCE = "leave_TCE.ogg"
# Played when focus enters / leaves an app that drives us via the NVDA controller.
SND_CONTROLLER_INIT = "controller_initialize.ogg"
SND_CONTROLLER_UNINIT = "controller_uninitialize.ogg"
SND_VSCREEN_ON = "vscreenOn.ogg"
SND_VSCREEN_OFF = "vscreenOff.ogg"
SND_ZOOM_IN = "zoomin.ogg"
SND_ZOOM_OUT = "zoomout.ogg"
# Played when a typed dialog is entered, by detected icon kind (see
# context_presenter._dialog_kind). Other dialogs stay silent / generic.
SND_QUESTION_DIALOG = "question_dialog.ogg"
SND_INFO_DIALOG = "information_dialog.ogg"
SND_WARNING_DIALOG = "warning_dialog.ogg"
SND_ERROR_DIALOG = "error_dialog.ogg"

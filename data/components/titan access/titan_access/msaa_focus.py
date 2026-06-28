# -*- coding: utf-8 -*-
"""Microsoft Active Accessibility (MSAA / IAccessible) provider for Titan Access.

Python port of the C# ``Accessibility/Providers/MSAAProvider.cs``, re-grounded on
NVDA's ``source/oleacc.py`` and ``NVDAObjects/IAccessible`` so the constants are
correct. MSAA is the fallback accessibility backend for **legacy Win32 apps**
where UI Automation exposes little or nothing.

How it works
------------
* A global ``SetWinEventHook`` (out-of-context) on ``EVENT_OBJECT_FOCUS`` and
  ``EVENT_SYSTEM_FOREGROUND`` delivers focus/foreground events to the engine
  worker thread's message pump (the same thread installs the hook, so the events
  arrive there). For each event we resolve the ``IAccessible`` with
  ``AccessibleObjectFromEvent`` and build a provider-agnostic
  :class:`~titan_access.contracts.AccessibleObject`.
* The role/state integers returned by ``IAccessible::get_accRole`` /
  ``get_accState`` are the **win32 ``ROLE_SYSTEM_*`` / ``STATE_SYSTEM_*``** values
  (NOT the .NET ``AccessibleStates`` bit order the C# port mistakenly mapped
  through — that inverted several states). We map the real constants here.

Important correctness note (vs the C# port)
-------------------------------------------
The C# ``MapMSAAStatesToAccessibleStates`` walked ``System.Windows.Forms``'s
``AccessibleStates`` enum bits, whose order differs from the raw MSAA
``STATE_SYSTEM_*`` flags actually returned by ``get_accState`` — so e.g. 0x40
(``STATE_SYSTEM_READONLY``) was reported as "indeterminate". This port uses the
canonical win32 flags per NVDA's ``oleacc.py``.

Everything COM/ctypes is guarded; on any failure the provider reports itself
unavailable and the engine keeps running on UIA alone.
"""

import ctypes
import sys
import threading
import time
from typing import List, Optional

from titan_access.contracts import (
    AccessibleObject, FocusCallback,
    ROLE_BUTTON, ROLE_SPLIT_BUTTON, ROLE_EDIT, ROLE_DOCUMENT, ROLE_CHECKBOX,
    ROLE_RADIO, ROLE_COMBOBOX, ROLE_LISTBOX, ROLE_LISTITEM, ROLE_TREE,
    ROLE_TREEITEM, ROLE_MENU, ROLE_MENUBAR, ROLE_MENUITEM, ROLE_TAB,
    ROLE_TABCONTROL, ROLE_SLIDER, ROLE_SPINNER, ROLE_PROGRESSBAR, ROLE_SCROLLBAR,
    ROLE_LINK, ROLE_TEXT, ROLE_HEADING, ROLE_IMAGE, ROLE_TABLE, ROLE_ROW,
    ROLE_CELL, ROLE_TOOLBAR, ROLE_STATUSBAR, ROLE_GROUP, ROLE_DIALOG,
    ROLE_WINDOW, ROLE_PANE, ROLE_SEPARATOR, ROLE_UNKNOWN,
    STATE_CHECKED, STATE_PARTIAL, STATE_EXPANDED, STATE_COLLAPSED,
    STATE_SELECTED, STATE_UNAVAILABLE, STATE_FOCUSED, STATE_READONLY,
    STATE_PRESSED, STATE_BUSY, STATE_HASPOPUP, STATE_PROTECTED,
)

_IS_WINDOWS = sys.platform.startswith("win")
_STATE_OFFSCREEN = "offscreen"

# --------------------------------------------------------------------------- #
# WinEvent / oleacc constants
# --------------------------------------------------------------------------- #
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_OBJECT_FOCUS = 0x8005

WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

OBJID_CLIENT = 0xFFFFFFFC      # (LONG)-4
CHILDID_SELF = 0

# ROLE_SYSTEM_* (win32) -> canonical Titan role key. Values per NVDA oleacc.py.
_MSAA_ROLE_TO_ROLE = {
    0x01: ROLE_UNKNOWN,     # TITLEBAR
    0x02: ROLE_MENUBAR,     # MENUBAR
    0x03: ROLE_SCROLLBAR,   # SCROLLBAR
    0x04: ROLE_UNKNOWN,     # GRIP
    0x09: ROLE_WINDOW,      # WINDOW
    0x0A: ROLE_PANE,        # CLIENT
    0x0B: ROLE_MENU,        # MENUPOPUP
    0x0C: ROLE_MENUITEM,    # MENUITEM
    0x0D: ROLE_TEXT,        # TOOLTIP
    0x0E: ROLE_WINDOW,      # APPLICATION
    0x0F: ROLE_DOCUMENT,    # DOCUMENT
    0x10: ROLE_PANE,        # PANE
    0x11: ROLE_IMAGE,       # CHART
    0x12: ROLE_DIALOG,      # DIALOG
    0x13: ROLE_UNKNOWN,     # BORDER
    0x14: ROLE_GROUP,       # GROUPING
    0x15: ROLE_SEPARATOR,   # SEPARATOR
    0x16: ROLE_TOOLBAR,     # TOOLBAR
    0x17: ROLE_STATUSBAR,   # STATUSBAR
    0x18: ROLE_TABLE,       # TABLE
    0x19: ROLE_HEADING,     # COLUMNHEADER
    0x1A: ROLE_HEADING,     # ROWHEADER
    0x1B: ROLE_UNKNOWN,     # COLUMN
    0x1C: ROLE_ROW,         # ROW
    0x1D: ROLE_CELL,        # CELL
    0x1E: ROLE_LINK,        # LINK
    0x1F: ROLE_TEXT,        # HELPBALLOON
    0x20: ROLE_UNKNOWN,     # CHARACTER
    0x21: ROLE_LISTBOX,     # LIST
    0x22: ROLE_LISTITEM,    # LISTITEM
    0x23: ROLE_TREE,        # OUTLINE
    0x24: ROLE_TREEITEM,    # OUTLINEITEM
    0x25: ROLE_TAB,         # PAGETAB
    0x26: ROLE_PANE,        # PROPERTYPAGE
    0x27: ROLE_UNKNOWN,     # INDICATOR
    0x28: ROLE_IMAGE,       # GRAPHIC
    0x29: ROLE_TEXT,        # STATICTEXT
    0x2A: ROLE_EDIT,        # TEXT (editable text field in MSAA)
    0x2B: ROLE_BUTTON,      # PUSHBUTTON
    0x2C: ROLE_CHECKBOX,    # CHECKBUTTON
    0x2D: ROLE_RADIO,       # RADIOBUTTON
    0x2E: ROLE_COMBOBOX,    # COMBOBOX
    0x2F: ROLE_COMBOBOX,    # DROPLIST
    0x30: ROLE_PROGRESSBAR,  # PROGRESSBAR
    0x31: ROLE_SLIDER,      # DIAL
    0x32: ROLE_EDIT,        # HOTKEYFIELD
    0x33: ROLE_SLIDER,      # SLIDER
    0x34: ROLE_SPINNER,     # SPINBUTTON
    0x35: ROLE_IMAGE,       # DIAGRAM
    0x36: ROLE_IMAGE,       # ANIMATION
    0x37: ROLE_IMAGE,       # EQUATION
    0x38: ROLE_SPLIT_BUTTON,  # BUTTONDROPDOWN
    0x39: ROLE_BUTTON,      # BUTTONMENU
    0x3A: ROLE_SPLIT_BUTTON,  # BUTTONDROPDOWNGRID
    0x3B: ROLE_UNKNOWN,     # WHITESPACE
    0x3C: ROLE_TABCONTROL,  # PAGETABLIST
    0x3D: ROLE_TEXT,        # CLOCK
    0x3E: ROLE_SPLIT_BUTTON,  # SPLITBUTTON
    0x3F: ROLE_EDIT,        # IPADDRESS
    0x40: ROLE_BUTTON,      # OUTLINEBUTTON
}

# STATE_SYSTEM_* (win32) -> canonical Titan state key. Canonical flags (NVDA).
_MSAA_STATE_FLAGS = (
    (0x00000001, STATE_UNAVAILABLE),
    (0x00000002, STATE_SELECTED),
    (0x00000004, STATE_FOCUSED),
    (0x00000008, STATE_PRESSED),
    (0x00000010, STATE_CHECKED),
    (0x00000020, STATE_PARTIAL),     # MIXED / indeterminate
    (0x00000040, STATE_READONLY),
    (0x00000200, STATE_EXPANDED),
    (0x00000400, STATE_COLLAPSED),
    (0x00000800, STATE_BUSY),
    (0x00010000, _STATE_OFFSCREEN),
    (0x20000000, STATE_PROTECTED),
    (0x40000000, STATE_HASPOPUP),
)


# --------------------------------------------------------------------------- #
# COM / oleacc bootstrap (lazy, fully guarded)
# --------------------------------------------------------------------------- #
_IAccessible = None
_oleacc = None
_AccessibleObjectFromEvent = None
_AccessibleObjectFromWindow = None
_COM_OK = False


def _init_oleacc():
    """Generate the oleacc IAccessible interface and bind the helper exports."""
    global _IAccessible, _oleacc, _COM_OK
    global _AccessibleObjectFromEvent, _AccessibleObjectFromWindow
    if _COM_OK or not _IS_WINDOWS:
        return _COM_OK
    try:
        import comtypes
        import comtypes.client
        from comtypes.automation import VARIANT
        from ctypes import wintypes, POINTER, byref

        mod = comtypes.client.GetModule("oleacc.dll")
        _IAccessible = mod.IAccessible

        _oleacc = ctypes.WinDLL("oleacc", use_last_error=True)
        _oleacc.AccessibleObjectFromEvent.restype = ctypes.c_long
        _oleacc.AccessibleObjectFromEvent.argtypes = [
            wintypes.HWND, wintypes.DWORD, wintypes.LONG,
            POINTER(POINTER(_IAccessible)), POINTER(VARIANT),
        ]
        _oleacc.AccessibleObjectFromWindow.restype = ctypes.c_long
        _oleacc.AccessibleObjectFromWindow.argtypes = [
            wintypes.HWND, wintypes.DWORD, POINTER(comtypes.GUID),
            POINTER(POINTER(_IAccessible)),
        ]

        def _from_event(hwnd, object_id, child_id):
            p = POINTER(_IAccessible)()
            var = VARIANT()
            hr = _oleacc.AccessibleObjectFromEvent(
                hwnd, object_id, child_id, byref(p), byref(var))
            if hr != 0 or not p:
                return None, CHILDID_SELF
            cid = var.value if var.value is not None else CHILDID_SELF
            try:
                cid = int(cid)
            except (TypeError, ValueError):
                cid = CHILDID_SELF
            return p, cid

        def _from_window(hwnd, object_id=OBJID_CLIENT):
            p = POINTER(_IAccessible)()
            hr = _oleacc.AccessibleObjectFromWindow(
                hwnd, object_id, byref(_IAccessible._iid_), byref(p))
            if hr != 0 or not p:
                return None
            return p

        _AccessibleObjectFromEvent = _from_event
        _AccessibleObjectFromWindow = _from_window
        _COM_OK = True
    except Exception as e:  # pragma: no cover - COM/oleacc not available
        print(f"[TitanAccess] msaa: oleacc unavailable: {e}")
        _COM_OK = False
    return _COM_OK


# --------------------------------------------------------------------------- #
# WinEvent hook plumbing (private, fully-typed user32 -- see keyboard_hook note
# about restype/argtypes truncation on 64-bit).
# --------------------------------------------------------------------------- #
if _IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    WINEVENTPROC = ctypes.WINFUNCTYPE(
        None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
        wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
    _user32.SetWinEventHook.restype = wintypes.HANDLE
    _user32.SetWinEventHook.argtypes = [
        wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    ]
    _user32.UnhookWinEvent.restype = wintypes.BOOL
    _user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
else:
    _user32 = None
    WINEVENTPROC = None


class MSAAProvider:
    """MSAA fallback provider. Same surface as
    :class:`titan_access.uia_focus.UIAProvider` so the provider manager can use
    them interchangeably."""

    def __init__(self):
        self._listeners: List[FocusCallback] = []
        self._lock = threading.RLock()
        self._hooks = []
        self._proc = None
        self._available = _init_oleacc()
        # MSAA runs its WinEvent hook on its OWN thread + message pump, so the
        # (potentially slow, cross-process) IAccessible COM calls never share the
        # thread that services the WH_KEYBOARD_LL hook -- otherwise a busy event
        # stream would delay key dispatch past the low-level-hook timeout and
        # Windows would silently drop our keyboard hook (breaking all navigation).
        self._thread = None
        self._thread_id = 0
        self._running = False
        self._ready = threading.Event()

    # -- provider surface -------------------------------------------------- #
    @property
    def available(self) -> bool:
        return self._available

    def add_focus_listener(self, callback: FocusCallback) -> None:
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def start(self) -> bool:
        """Start the dedicated MSAA WinEvent thread (own message pump)."""
        if not self._available or not _IS_WINDOWS:
            return False
        if self._thread is not None:
            return True
        self._running = True
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="TitanAccessMSAA",
                                        daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)
        return bool(self._hooks)

    def _run(self) -> None:
        """Own thread: COM init, install WinEvent hooks, pump messages."""
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # STA
        except Exception:
            pass
        try:
            self._proc = WINEVENTPROC(self._on_win_event)
            flags = WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS
            for ev_min, ev_max in ((EVENT_SYSTEM_FOREGROUND,
                                    EVENT_SYSTEM_FOREGROUND),
                                   (EVENT_OBJECT_FOCUS, EVENT_OBJECT_FOCUS)):
                h = _user32.SetWinEventHook(ev_min, ev_max, 0, self._proc,
                                            0, 0, flags)
                if h:
                    self._hooks.append(h)
            if self._hooks:
                print("[TitanAccess] msaa: WinEvent hooks installed (own thread)")
            else:
                print("[TitanAccess] msaa: SetWinEventHook failed")
        except Exception as e:
            print(f"[TitanAccess] msaa: hook install error: {e}")
        finally:
            self._ready.set()

        try:
            import ctypes.wintypes as wt
            msg = wt.MSG()
            user32 = ctypes.windll.user32
            while self._running:
                r = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if r == 0 or r == -1:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            print(f"[TitanAccess] msaa: message loop error: {e}")
        finally:
            for h in self._hooks:
                try:
                    _user32.UnhookWinEvent(h)
                except Exception:
                    pass
            self._hooks = []
            self._proc = None
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass

    def stop(self) -> None:
        self._running = False
        if self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = 0

    def get_focused_object(self) -> Optional[AccessibleObject]:
        if not self._available:
            return None
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None
            acc = _AccessibleObjectFromWindow(hwnd, OBJID_CLIENT)
            if acc is None:
                return None
            return self._build(acc, CHILDID_SELF, int(hwnd))
        except Exception as e:
            print(f"[TitanAccess] msaa: get_focused_object error: {e}")
            return None

    # -- event handling ---------------------------------------------------- #
    def _on_win_event(self, hWinEventHook, event, hwnd, id_object, id_child,
                      thread, time_ms):
        # Only react to focus / foreground; ignore caret, menus, etc.
        if event not in (EVENT_OBJECT_FOCUS, EVENT_SYSTEM_FOREGROUND):
            return
        try:
            acc, child = _AccessibleObjectFromEvent(hwnd, id_object, id_child)
            if acc is None:
                return
            obj = self._build(acc, child, int(hwnd) if hwnd else 0)
            if obj is not None:
                self._dispatch(obj)
        except Exception as e:  # never raise into the WinEvent callback
            print(f"[TitanAccess] msaa: event error: {e}")

    def _dispatch(self, obj: AccessibleObject) -> None:
        for cb in list(self._listeners):
            try:
                cb(obj)
            except Exception as e:
                print(f"[TitanAccess] msaa: listener error: {e}")

    # -- IAccessible -> snapshot ------------------------------------------- #
    def _build(self, acc, child_id, hwnd) -> Optional[AccessibleObject]:
        try:
            obj = AccessibleObject(native=None, provider="msaa")
            obj.hwnd = hwnd
            obj.name = _s(lambda: acc.accName(child_id))
            obj.value = _s(lambda: acc.accValue(child_id))
            obj.description = _s(lambda: acc.accDescription(child_id))
            obj.help_text = _s(lambda: acc.accHelp(child_id))

            role_raw = _safe(lambda: acc.accRole(child_id))
            obj.role = _MSAA_ROLE_TO_ROLE.get(
                int(role_raw) if isinstance(role_raw, int) else -1, ROLE_UNKNOWN)

            state_raw = _safe(lambda: acc.accState(child_id))
            obj.states = _states_from_int(
                int(state_raw) if isinstance(state_raw, int) else 0)

            obj.bounds = _location(acc, child_id)

            # Enrich with IAccessible2 web semantics (heading level, landmark,
            # paragraph, group position) when the element implements IA2 -- this
            # is what makes Chromium / Firefox content read richly.
            if child_id == CHILDID_SELF:
                try:
                    from titan_access import ia2
                    ia2.enrich_object(obj, acc)
                except Exception:
                    pass
            return obj
        except Exception as e:
            print(f"[TitanAccess] msaa: build error: {e}")
            return None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _safe(getter):
    try:
        return getter()
    except Exception:
        return None


def _s(getter) -> str:
    val = _safe(getter)
    return str(val) if val else ""


def _states_from_int(state_int) -> set:
    states = set()
    for flag, key in _MSAA_STATE_FLAGS:
        if state_int & flag:
            states.add(key)
    return states


def _location(acc, child_id):
    """Read accLocation -> (left, top, right, bottom). MSAA returns x/y/w/h."""
    try:
        l, t, w, h = acc.accLocation(child_id)
        return (int(l), int(t), int(l) + int(w), int(t) + int(h))
    except Exception:
        return (0, 0, 0, 0)


def get_provider() -> MSAAProvider:
    return MSAAProvider()

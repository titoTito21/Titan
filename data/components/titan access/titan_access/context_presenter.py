# -*- coding: utf-8 -*-
"""Focus context presentation for Titan Access.

Port of the container-context logic in the C# ``ScreenReaderEngine.AnnounceElement``
(group / list handling, 2403-2457) generalised toward NVDA's *focus context
presentation*: when focus moves into a **newly entered** container ancestor
(dialog, grouping, list, tree, toolbar, tab control) that container is announced
alongside the focused control.

Unlike the C# port (which spoke the container separately and then skipped the
child), this presenter returns the container announcement as speech **segments**
that the engine prepends to the control's own description, so everything is
spoken as a single pitched utterance through the existing
``SpeechAdapter.speak_segments`` pipeline. That avoids the speech queue cutting
off a separately-spoken prefix, and matches NVDA, which reads the changed
ancestors and then the control.

A container is announced only the first time focus enters it; while focus stays
within it (moving between its children) it is not repeated. Leaving and
re-entering announces it again.

The presenter only runs for real focus changes (not object navigation) and only
when ``Verbosity/AnnounceBlockControls`` is enabled. It needs the vendored
``uiautomation.Control`` stored on ``AccessibleObject.native``; for provider
snapshots without one (e.g. MSAA) it returns no context and degrades silently.
"""

import ctypes
from ctypes import wintypes

from titan_access.localization import L, role_label
from titan_access.contracts import (
    SND_QUESTION_DIALOG, SND_INFO_DIALOG, SND_WARNING_DIALOG, SND_ERROR_DIALOG,
)

try:  # vendored uiautomation (its lib dir is put on sys.path by uia_focus)
    import uiautomation as _auto
except Exception:
    _auto = None

# uiautomation ControlTypeName -> container role we care about. Ordered loosely
# outermost-to-innermost for announcement.
_CT_TO_ROLE = {
    "WindowControl": "window",
    "GroupControl": "group",
    "ListControl": "list",
    "TreeControl": "tree",
    "ToolBarControl": "toolbar",
    "TabControl": "tabcontrol",
}

# Announce outer containers before inner ones.
_ROLE_ORDER = ["window", "tabcontrol", "toolbar", "list", "tree", "group"]

# Focused roles for which a wx group-box (sibling GroupControl) lookup makes
# sense — ordinary form controls, never collection items.
_GROUPABLE_ROLES = {
    "button", "split_button", "checkbox", "radio", "combobox", "edit",
    "password", "slider", "spinner", "text", "link", "progressbar",
}

# Pitch for the context segments: neutral (same as the name pitch).
_CONTEXT_PITCH = 0

# Region containers (the application list, status bar, a toolbar, a tab strip)
# are announced as just their name, a little lower, so entering one reads
# "Application list" rather than the noisier "Application list, list". The lower
# tone marks it as a container, not a row. This is a Titan-specific touch, so it
# only applies inside the TCE environment (its own windows + the apps it spawns);
# other applications keep the standard "<name>, list" context.
_REGION_PITCH = -4
_REGION_NAME_ONLY_ROLES = {"list", "tree", "toolbar", "tabcontrol"}

_MAX_DEPTH = 14

# UIA property id: UIA_IsDialogPropertyId. Plus the Win32 standard-dialog class
# (wx.MessageDialog and most native confirm/alert boxes use "#32770"), so we can
# recognise a dialog even when the IsDialog property is not set.
_PROP_IS_DIALOG = 30174
_DIALOG_CLASSES = {"#32770"}

# Bounds for the dialog content scan (so a huge window can never stall us).
_DIALOG_SCAN_MAX_NODES = 250
_DIALOG_SCAN_MAX_DEPTH = 8

# --------------------------------------------------------------------------- #
# Dialog *kind* detection (question / information / warning / error).
#
# UI Automation does not expose the icon STYLE of a message box, and the icon
# HANDLE can't be matched to LoadIconW's (modern Windows scales the icon per-DPI,
# so the handles differ) -- verified empirically. What IS robust: render the
# dialog's icon AND the four system icons (LoadIconW(IDI_*)) to the same fixed
# size and compare the pixels. The references are computed live on the SAME
# machine, so the match survives any Windows version / theme. This splits icons
# into three visual groups reliably (blue circle = question/information, yellow
# triangle = warning, red = error). Question vs information are near-identical
# blue circles, so we split THAT group by button set: a real choice (>=2 standard
# dialog buttons, e.g. OK/Cancel, Yes/No) is a question; a lone OK is information.
#
# Works for native message boxes (wx.MessageDialog / MessageBoxW carry the
# classic Static icon, control id 20). A custom wx.Dialog / TaskDialog with no
# such icon yields no kind and stays the generic "dialog".
_ICON_SIZE = 32
_STM_GETICON = 0x0171
_STM_GETIMAGE = 0x0173
_IMAGE_ICON = 1
_DI_NORMAL = 0x0003
_GWL_ID = -12
_GWL_STYLE = -16
_SS_TYPEMASK = 0x0000001F
_SS_ICON = 0x03
_WM_GETICON = 0x007F
# IDI_* system icon resource ids.
_SYS_ICON_IDS = {
    "question": 32514, "information": 32516, "warning": 32515, "error": 32513,
}
# Standard dialog button command ids (OK, Cancel, Yes, No, Retry, Ignore, ...).
_STD_BUTTON_IDS = {1, 2, 4, 6, 7, 8, 9, 10, 11}
# Max average pixel difference (over the sampled signature) to still count as a
# match to a system icon; above this the dialog has a custom icon -> generic.
_ICON_MATCH_THRESHOLD = 42000

try:
    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetDlgItem.restype = wintypes.HWND
    _user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SendMessageW.restype = ctypes.c_void_p
    _user32.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                     ctypes.c_void_p, ctypes.c_void_p]
    _user32.LoadIconW.restype = wintypes.HICON
    _user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    _user32.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int,
                                   wintypes.HICON, ctypes.c_int, ctypes.c_int,
                                   wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    _gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                        ctypes.POINTER(ctypes.c_void_p),
                                        wintypes.HANDLE, wintypes.DWORD]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _ENUM_CHILD_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND,
                                          wintypes.LPARAM)
    _ICON_DETECT_OK = True
except Exception:  # pragma: no cover - non-Windows / no user32
    _user32 = None
    _gdi32 = None
    _ENUM_CHILD_PROC = None
    _ICON_DETECT_OK = False


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _classname(hwnd):
    buf = ctypes.create_unicode_buffer(64)
    _user32.GetClassNameW(hwnd, buf, 64)
    return buf.value


def _icon_signature(hicon):
    """Render ``hicon`` to a fixed-size BGRA bitmap over a flat background and
    return its bytes (a comparable pixel signature), or None."""
    if not hicon:
        return None
    hdc = _gdi32.CreateCompatibleDC(None)
    if not hdc:
        return None
    try:
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = _ICON_SIZE
        bmi.biHeight = -_ICON_SIZE   # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0        # BI_RGB
        bits = ctypes.c_void_p()
        hbm = _gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0,
                                      ctypes.byref(bits), None, 0)
        if not hbm or not bits.value:
            return None
        old = _gdi32.SelectObject(hdc, hbm)
        try:
            n = _ICON_SIZE * _ICON_SIZE * 4
            ctypes.memset(bits, 0x80, n)   # flat gray so transparency is uniform
            _user32.DrawIconEx(hdc, 0, 0, ctypes.c_void_p(int(hicon)),
                               _ICON_SIZE, _ICON_SIZE, 0, None, _DI_NORMAL)
            return bytes((ctypes.c_ubyte * n).from_address(bits.value))
        finally:
            _gdi32.SelectObject(hdc, old)
            _gdi32.DeleteObject(hbm)
    finally:
        _gdi32.DeleteDC(hdc)


_sys_icon_sigs = None


def _system_icon_signatures():
    """Signatures of the four system icons, computed once on this machine."""
    global _sys_icon_sigs
    if _sys_icon_sigs is None:
        _sys_icon_sigs = {}
        for kind, idi in _SYS_ICON_IDS.items():
            try:
                sig = _icon_signature(_user32.LoadIconW(None, ctypes.c_wchar_p(idi)))
                if sig:
                    _sys_icon_sigs[kind] = sig
            except Exception:
                pass
    return _sys_icon_sigs


def _sig_diff(a, b):
    return sum(abs(a[i] - b[i]) for i in range(0, len(a), 8))


def _dialog_icon_handle(hwnd):
    """The HICON shown by a message box: its static icon (classic control id 20,
    else the first SS_ICON static), or the window icon as a last resort."""
    ic = _user32.GetDlgItem(hwnd, 20)
    statics = []

    def _cb(child, _lparam):
        try:
            if _classname(child).lower() == "static":
                style = _user32.GetWindowLongW(child, _GWL_STYLE)
                if (style & _SS_TYPEMASK) == _SS_ICON:
                    statics.append(child)
        except Exception:
            pass
        return True

    candidates = [ic] if ic else []
    try:
        _user32.EnumChildWindows(hwnd, _ENUM_CHILD_PROC(_cb), 0)
    except Exception:
        pass
    candidates.extend(statics)
    for st in candidates:
        if not st:
            continue
        for msg, wp in ((_STM_GETICON, 0), (_STM_GETIMAGE, _IMAGE_ICON)):
            h = _user32.SendMessageW(st, msg, ctypes.c_void_p(wp), None)
            if h:
                return int(h)
    return 0


def _count_choice_buttons(hwnd):
    """Number of standard dialog push buttons (OK/Cancel/Yes/No/...)."""
    n = [0]

    def _cb(child, _lparam):
        try:
            if (_classname(child) == "Button"
                    and _user32.GetWindowLongW(child, _GWL_ID) in _STD_BUTTON_IDS):
                n[0] += 1
        except Exception:
            pass
        return True

    try:
        _user32.EnumChildWindows(hwnd, _ENUM_CHILD_PROC(_cb), 0)
    except Exception:
        pass
    return n[0]


def _dialog_icon_kind(hwnd):
    """Return 'question' / 'information' / 'warning' / 'error' for a message-box
    ``hwnd`` by matching its icon pixels to the system icons (+ button set to
    split question from information), or None for a custom / iconless dialog."""
    if not _ICON_DETECT_OK or not hwnd:
        return None
    try:
        refs = _system_icon_signatures()
        if not refs:
            return None
        sig = _icon_signature(_dialog_icon_handle(hwnd))
        if sig is None:
            return None
        scores = {k: _sig_diff(sig, r) for k, r in refs.items()}
        best = min(scores, key=scores.get)
        if scores[best] > _ICON_MATCH_THRESHOLD:
            return None  # custom icon -> generic dialog
        if best in ("warning", "error"):
            return best
        # Blue-circle group: a real choice is a question, a lone OK is info.
        return "question" if _count_choice_buttons(hwnd) >= 2 else "information"
    except Exception as e:
        print(f"[TitanAccess] dialog kind detect error: {e}")
        return None


# Dialog kinds we give a distinct earcon + lower-tone type word to (instead of
# the generic "dialog"). Any other dialog stays the generic "<title>, dialog".
_DIALOG_KIND_SOUND = {
    "question": SND_QUESTION_DIALOG,
    "information": SND_INFO_DIALOG,
    "warning": SND_WARNING_DIALOG,
    "error": SND_ERROR_DIALOG,
}
_DIALOG_KIND_LABEL_KEY = {
    "question": "dialog.question",
    "information": "dialog.information",
    "warning": "dialog.warning",
    "error": "dialog.error",
}
# Warning leads with the type word ("Uwaga!") spoken first (low), THEN the title;
# the others read the title first and then the lower-tone type word.
_DIALOG_KIND_TYPE_FIRST = {"warning"}


class ContextPresenter:
    """Announces newly-entered container ancestors as prepended segments."""

    def __init__(self, engine):
        self.engine = engine
        self._seen = set()         # runtime ids of containers announced for focus
        self._seen_dialogs = set()  # dialog ids whose content we already read
        # "status bar item" label for the most recent focus, or None. Computed
        # during the single ancestor walk in _compute so the engine never has to
        # walk the UIA tree a second time (an extra in-process walk per list row
        # was stalling reads inside the TCE window).
        self.last_status_item_label = None

    def reset(self):
        self._seen = set()
        self._seen_dialogs = set()
        self.last_status_item_label = None

    def context_segments(self, obj, for_navigation=False):
        """Return ``[(text, pitch_offset), ...]`` for containers newly entered by
        focusing ``obj``. Empty when nothing changed or context is unavailable."""
        try:
            return self._compute(obj, for_navigation)
        except Exception as e:
            print(f"[TitanAccess] context_presenter error: {e}")
            return []

    # ------------------------------------------------------------------ #
    def _compute(self, obj, for_navigation):
        # Cleared every focus so a stale "status bar item" can never leak.
        self.last_status_item_label = None
        if obj is None or for_navigation:
            return []
        settings = self.engine.settings
        if not settings.get_bool("Verbosity", "AnnounceBlockControls", True):
            return []
        # The lower-tone region read and the "status bar item" relabel are
        # Titan-only touches. Use the engine's CACHED foreground check (0.3s) so
        # we never pay a per-focus process-tree walk here.
        try:
            is_tce = self.engine._is_tce_foreground()
        except Exception:
            is_tce = False
        native = getattr(obj, "native", None)
        if native is None:
            # Focus arrived without a UIA element (e.g. the MSAA path, which is
            # common for native #32770 dialogs). We can still read a dialog's
            # content by resolving the foreground window through UIA.
            return self._foreground_dialog_segments(obj)

        # Whether this focus is a collection item that could live in a status bar.
        item_in_tce = is_tce and obj.role in ("listitem", "treeitem")

        # Nearest ancestor per container role (walking up from the focus). We
        # keep the live node for the window so we can read dialog content. The
        # same single pass also detects a status-bar container, so the engine
        # does not need a second walk.
        nearest = {}
        nodes = {}
        for ct, name, rid, node in self._walk_up(native):
            if item_in_tce and self.last_status_item_label is None and (
                    ct == "StatusBarControl"
                    or (ct in ("ListControl", "PaneControl", "ToolBarControl")
                        and self._name_is_status_bar(name))):
                self.last_status_item_label = L("element.statusBarItem")
            role = _CT_TO_ROLE.get(ct)
            if role and role not in nearest:
                nearest[role] = (name, rid)
                nodes[role] = node

        # wx group boxes (wx.StaticBoxSizer) expose the group as a *sibling* of
        # the controls it frames, not an ancestor, so the ancestor walk above
        # misses them. Fall back to the nearest sibling GroupControl whose bounds
        # enclose the focused control. Restricted to form controls: list/tree/menu
        # items live in big collections, so scanning their siblings would be slow
        # and a group box never frames them anyway.
        if "group" not in nearest and obj.role in _GROUPABLE_ROLES:
            grp = self._find_containing_group(native)
            if grp is not None:
                nearest["group"] = grp
                nodes["group"] = None

        current_ids = {rid for (_n, rid) in nearest.values() if rid}
        segments = []
        for role in _ROLE_ORDER:
            entry = nearest.get(role)
            if not entry:
                continue
            name, rid = entry
            if not rid or rid in self._seen:
                continue
            # A newly entered dialog: announce "<name>, dialog" and read its
            # message text (NVDA-style), instead of the bare "window" context.
            if role == "window" and self._is_dialog(nodes.get("window")):
                segments.extend(self._dialog_segments(
                    name, rid, nodes.get("window"), native))
                continue
            seg = self._segment_for(role, name, is_tce)
            if seg:
                segments.append(seg)
        self._seen = current_ids
        return segments

    @staticmethod
    def _segment_for(role, name, is_tce=False):
        label = role_label(role)
        name = (name or "").strip().rstrip(":").strip()
        if is_tce and role in _REGION_NAME_ONLY_ROLES and name:
            # Region container inside Titan: just the name, a little lower (no
            # "list" word). Other apps keep the standard "<name>, list".
            return (name, _REGION_PITCH)
        if role == "group":
            # "{name}, group" (named) or just "group".
            text = L("engine.namedGroup", name) if name else label
        elif name:
            text = f"{name}, {label}"
        else:
            # Unnamed window/list/toolbar: announcing the bare role adds little
            # for a top-level window, so skip nameless windows.
            if role == "window":
                return None
            text = label
        return (text, _CONTEXT_PITCH) if text else None

    # ------------------------------------------------------------------ #
    # Status-bar item detection (reader-driven, no host cooperation needed)
    # ------------------------------------------------------------------ #
    _status_bar_names_cache = None

    @classmethod
    def _status_bar_names(cls):
        """Casefolded names that mark a container as a status bar. Includes the
        reader's localized term plus the literal pl/en labels (the container's
        name follows the app's language, which usually matches the reader's)."""
        if cls._status_bar_names_cache is None:
            names = {"status bar", "statusbar", "pasek stanu"}
            try:
                names.add((role_label("statusbar") or "").strip().casefold())
            except Exception:
                pass
            cls._status_bar_names_cache = {n for n in names if n}
        return cls._status_bar_names_cache

    @classmethod
    def _name_is_status_bar(cls, name):
        n = (name or "").strip().rstrip(":").strip().casefold()
        return bool(n) and n in cls._status_bar_names()

    # ------------------------------------------------------------------ #
    @staticmethod
    def _walk_up(native):
        """Yield ``(control_type_name, name, runtime_id_tuple, node)`` from the
        focused element up to the window, bounded by depth."""
        node = native
        depth = 0
        while node is not None and depth < _MAX_DEPTH:
            try:
                ct = node.ControlTypeName or ""
                name = (node.Name or "").strip()
                rid = tuple(node.GetRuntimeId() or ())
            except Exception:
                return
            yield (ct, name, rid, node)
            try:
                node = node.GetParentControl()
            except Exception:
                return
            depth += 1

    # ------------------------------------------------------------------ #
    # Dialog detection + content reading (NVDA "report dialog" behaviour)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_dialog(window_node):
        if window_node is None:
            return False
        try:
            if bool(window_node.GetPropertyValue(_PROP_IS_DIALOG)):
                return True
        except Exception:
            pass
        try:
            if (window_node.ClassName or "") in _DIALOG_CLASSES:
                return True
        except Exception:
            pass
        return False

    def _dialog_segments(self, name, rid, window_node, focused_native):
        """Segments for a newly entered dialog: its typed header (question /
        information / warning / error / generic) plus its message text. Returns an
        empty list once the dialog has been read."""
        kind = self._declared_or_detected_kind(self._node_hwnd(window_node))
        segs = self._build_dialog_header(name, kind)
        # Read the body text only the first time focus enters this dialog.
        if rid and rid not in self._seen_dialogs:
            self._seen_dialogs.add(rid)
            body = self._dialog_body_text(window_node, focused_native)
            if body:
                segs.append((body, _CONTEXT_PITCH))
        return segs

    def _declared_or_detected_kind(self, hwnd):
        """The dialog kind a host explicitly declared (``host_bridge.dialog_kind``,
        skin-independent), else the icon-detected kind, else None. The declared
        value wins so Titan's own dialogs (e.g. the exit confirmation) read as
        their true type no matter how they are skinned/drawn."""
        try:
            declared = self.engine.consume_dialog_kind()
        except Exception:
            declared = None
        if declared:
            return declared
        return _dialog_icon_kind(hwnd)

    def _build_dialog_header(self, title, kind):
        """Header segments for a dialog of detected ``kind`` (None = generic) and,
        for typed kinds, play its earcon.

        * question / information / error -> "<title>" then the lower-tone type
          word ("Pytanie" / "Informacja" / "Blad").
        * warning -> the type word first ("Uwaga!", lower tone), THEN the title.
        * generic -> the unchanged "<title>, dialog".
        """
        title = (title or "").strip()
        if kind in _DIALOG_KIND_LABEL_KEY:
            snd = _DIALOG_KIND_SOUND.get(kind)
            if snd:
                try:
                    self.engine.play(snd)
                except Exception:
                    pass
            label = L(_DIALOG_KIND_LABEL_KEY[kind])
            if kind in _DIALOG_KIND_TYPE_FIRST:
                segs = [(label, _REGION_PITCH)]
                if title:
                    segs.append((title, _CONTEXT_PITCH))
                return segs
            segs = []
            if title:
                segs.append((title, _CONTEXT_PITCH))
            segs.append((label, _REGION_PITCH))
            return segs
        # Generic dialog: unchanged "<title>, dialog".
        label = role_label("dialog")
        if title:
            return [(f"{title}, {label}", _CONTEXT_PITCH)]
        return [(label, _CONTEXT_PITCH)] if label else []

    @staticmethod
    def _node_hwnd(node):
        """Top-level window handle behind a uiautomation node, or 0."""
        try:
            return int(node.NativeWindowHandle or 0)
        except Exception:
            return 0

    def _foreground_dialog_segments(self, obj):
        """When focus has no UIA element (MSAA path), resolve the foreground
        window through UIA and, if it is a dialog, announce its title + message
        text once. This is how native #32770 dialogs (wx.MessageDialog, the
        Titan exit prompt) get their question read."""
        if _auto is None:
            return []
        try:
            hwnd = int(ctypes.windll.user32.GetForegroundWindow())
        except Exception:
            hwnd = 0
        if not hwnd:
            return []
        key = ("hwnd", hwnd)
        if key in self._seen_dialogs:
            return []
        try:
            ctrl = _auto.ControlFromHandle(hwnd)
        except Exception:
            ctrl = None
        if ctrl is None or not self._is_dialog(ctrl):
            return []
        self._seen_dialogs.add(key)
        try:
            title = (ctrl.Name or "").strip()
        except Exception:
            title = ""
        kind = self._declared_or_detected_kind(hwnd)
        segs = self._build_dialog_header(title, kind)
        body = self._dialog_body_text(ctrl, None)
        if body:
            segs.append((body, _CONTEXT_PITCH))
        return segs

    def _dialog_body_text(self, window_node, focused_native):
        """Collect the static message text inside a dialog (the text the user
        must read), skipping the focused control and obvious button labels."""
        if window_node is None:
            return ""
        try:
            focus_rid = tuple(focused_native.GetRuntimeId() or ())
        except Exception:
            focus_rid = ()
        parts = []
        budget = [_DIALOG_SCAN_MAX_NODES]
        self._collect_text(window_node, focus_rid, parts, budget, 0)
        # De-duplicate while preserving order; cap total length defensively.
        seen = set()
        out = []
        for t in parts:
            t = t.strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        text = ". ".join(out)
        return text[:600]

    def _collect_text(self, node, focus_rid, parts, budget, depth):
        if node is None or budget[0] <= 0 or depth > _DIALOG_SCAN_MAX_DEPTH:
            return
        budget[0] -= 1
        try:
            ct = node.ControlTypeName or ""
            name = (node.Name or "").strip()
            rid = tuple(node.GetRuntimeId() or ())
        except Exception:
            return
        if rid and rid == focus_rid:
            return  # the focused control is announced separately
        # Static text carries the dialog message; titlebars/buttons do not.
        if ct == "TextControl" and name:
            parts.append(name)
        try:
            child = node.GetFirstChildControl()
        except Exception:
            child = None
        guard = 0
        while child is not None and guard < 80 and budget[0] > 0:
            guard += 1
            self._collect_text(child, focus_rid, parts, budget, depth + 1)
            try:
                child = child.GetNextSiblingControl()
            except Exception:
                break

    # ------------------------------------------------------------------ #
    # wx group-box (sibling GroupControl) detection
    # ------------------------------------------------------------------ #
    def _find_containing_group(self, native):
        """Return ``(name, rid)`` of a named GroupControl that is a sibling of
        the focused control and whose bounds enclose it (the wx.StaticBoxSizer
        layout), or None."""
        try:
            parent = native.GetParentControl()
            if parent is None:
                return None
            frect = native.BoundingRectangle
        except Exception:
            return None
        try:
            child = parent.GetFirstChildControl()
        except Exception:
            return None
        guard = 0
        while child is not None and guard < 80:
            guard += 1
            try:
                if (child.ControlTypeName or "") == "GroupControl":
                    name = (child.Name or "").strip()
                    if name and self._rect_contains(child.BoundingRectangle, frect):
                        rid = tuple(child.GetRuntimeId() or ())
                        return (name, rid)
            except Exception:
                pass
            try:
                child = child.GetNextSiblingControl()
            except Exception:
                break
        return None

    @staticmethod
    def _rect_contains(outer, inner):
        try:
            return (outer.left <= inner.left and outer.top <= inner.top
                    and outer.right >= inner.right and outer.bottom >= inner.bottom
                    and (outer.right - outer.left) > 0)
        except Exception:
            return False

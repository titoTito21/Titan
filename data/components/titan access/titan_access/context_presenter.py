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

from titan_access.localization import L, role_label

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
        """Segments for a newly entered dialog: its title (as a dialog) plus its
        message text. Returns an empty list once the dialog has been read."""
        segs = []
        label = role_label("dialog")
        title = (name or "").strip()
        if title:
            segs.append((f"{title}, {label}", _CONTEXT_PITCH))
        elif label:
            segs.append((label, _CONTEXT_PITCH))
        # Read the body text only the first time focus enters this dialog.
        if rid and rid not in self._seen_dialogs:
            self._seen_dialogs.add(rid)
            body = self._dialog_body_text(window_node, focused_native)
            if body:
                segs.append((body, _CONTEXT_PITCH))
        return segs

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
        segs = []
        try:
            title = (ctrl.Name or "").strip()
        except Exception:
            title = ""
        label = role_label("dialog")
        if title:
            segs.append((f"{title}, {label}", _CONTEXT_PITCH))
        elif label:
            segs.append((label, _CONTEXT_PITCH))
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

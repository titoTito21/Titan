# -*- coding: utf-8 -*-
"""The two AI OCR shortcuts.

Deliberately the same pair the voice assistant has, and registered the same
way, because they answer the same kind of question - "what am I looking at?" -
and a user who has learned one has learned the other:

* **Global** - works anywhere, so it reaches a full-screen game that Titan is
  not in front of.
* **Titan UI** - fires only while Titan UI mode is on (the mode the tilde key
  toggles inside the invisible interface, not merely Titan being minimised to
  the tray), which frees it to be a bare key that would otherwise collide with
  normal typing.

The shortcut is the whole point of the feature being usable: the window it
opens has to be about the program the user was *just* in, so the foreground
window is read the instant the key fires, before Titan's own window can take
the focus. That happens in :func:`src.ai.ocr.mimic.show_ai_ocr`.
"""

from __future__ import annotations

import wx

from src.ai import ai_provider

# Handles from keyboard.add_hotkey, kept so re-registering can remove them.
_handles = []

# Our normalized key ids (settingsgui._wx_key_to_string) -> `keyboard` names.
_KEY_MAP = {
    'win': 'windows', 'grave': '`', 'pageup': 'page up', 'pagedown': 'page down',
    'escape': 'esc',
}


def _to_keyboard_hotkey(normalized):
    if not normalized:
        return ''
    parts = [part.strip() for part in normalized.split('+') if part.strip()]
    return '+'.join(_KEY_MAP.get(part, part) for part in parts)


def _find_main_frame():
    for window in wx.GetTopLevelWindows():
        if hasattr(window, 'invisible_ui'):
            return window
    windows = wx.GetTopLevelWindows()
    return windows[0] if windows else None


def _titan_ui_active(frame):
    """True only while Titan UI mode is on - the mode the tilde key toggles.

    The invisible UI's `active` flag only says Titan is minimised to the tray,
    so asking that made a "Titan UI only" shortcut fire with Titan UI off.
    """
    iui = getattr(frame, 'invisible_ui', None)
    check = getattr(iui, 'is_titan_ui_on', None)
    return bool(check()) if callable(check) else False


def _launch(require_titan_ui):
    def _open():
        frame = _find_main_frame()
        if require_titan_ui and not _titan_ui_active(frame):
            return
        if not ai_provider.is_ai_enabled() or not ai_provider.get_ocr_enabled():
            return
        try:
            # An overlay that is already up is what the shortcut acts on: it
            # puts it away, and puts it back. Otherwise the one key that gives
            # a program its controls would have no way of taking them off
            # again, which is what a user needs the moment a reading is wrong
            # or the real window has to be used as it is.
            from src.ai.ocr import overlay as overlay_mod
            current = overlay_mod.get_overlay()
            if current is not None:
                current.toggle_hidden()
                return

            # What the shortcut opens is the user's choice: the controls put
            # straight onto the program they are already in (nothing of Titan's
            # appears at all), or Titan's own window with the reading in a list.
            if ai_provider.get_ocr_open_as() == 'overlay':
                from src.ai.ocr.mimic import show_ai_ocr_overlay
                show_ai_ocr_overlay(frame)
            else:
                from src.ai.ocr.mimic import show_ai_ocr
                show_ai_ocr(frame)
        except Exception as exc:
            print(f"[ai.ocr.hotkeys] could not open AI OCR: {exc}")
    # `keyboard` fires on its own thread; everything below is wx.
    wx.CallAfter(_open)


def unregister():
    global _handles
    try:
        import keyboard
    except Exception:
        _handles = []
        return
    for handle in _handles:
        try:
            keyboard.remove_hotkey(handle)
        except Exception:
            pass
    _handles = []


def register():
    """(Re)register both AI OCR shortcuts from settings. Safe to call again."""
    unregister()
    if not ai_provider.is_ai_enabled() or not ai_provider.get_ocr_enabled():
        return
    try:
        import keyboard
    except Exception as exc:
        print(f"[ai.ocr.hotkeys] keyboard library unavailable: {exc}")
        return

    combos = [
        (ai_provider.get_ocr_hotkey(), False),
        (ai_provider.get_ocr_titan_hotkey(), True),
    ]
    for normalized, titan_only in combos:
        hotkey = _to_keyboard_hotkey(normalized)
        if not hotkey:
            continue
        try:
            _handles.append(keyboard.add_hotkey(
                hotkey, lambda t=titan_only: _launch(t), suppress=False))
        except Exception as exc:
            print(f"[ai.ocr.hotkeys] failed to register {hotkey!r}: {exc}")

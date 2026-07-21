"""Global hotkeys that launch the voice assistant.

Two shortcuts, both configured in Settings, AI features:

* **Global assistant hotkey** - works anywhere, whenever AI features are on.
* **Titan UI assistant hotkey** - fires only while the Titan (Invisible) UI is
  active, so it can reuse a simple key that would otherwise clash with normal
  typing.

Both use the ``keyboard`` library (same as the rest of Titan's global hooks) and
open the assistant window on the wx main thread.
"""

import wx

from src.ai import ai_provider

# Handles returned by keyboard.add_hotkey, so we can remove them on re-register.
_handles = []

# Map our normalized key ids (from settingsgui._wx_key_to_string) to the names
# the `keyboard` library expects.
_KEY_MAP = {
    'win': 'windows', 'grave': '`', 'pageup': 'page up', 'pagedown': 'page down',
    'escape': 'esc',
}


def _to_keyboard_hotkey(normalized):
    """Convert 'ctrl+alt+a' / 'grave' into the `keyboard` library's format."""
    if not normalized:
        return ''
    parts = [p.strip() for p in normalized.split('+') if p.strip()]
    return '+'.join(_KEY_MAP.get(p, p) for p in parts)


def _find_main_frame():
    """The main TitanApp frame (the one that owns the invisible UI), if any."""
    for w in wx.GetTopLevelWindows():
        if hasattr(w, 'invisible_ui'):
            return w
    tlws = wx.GetTopLevelWindows()
    return tlws[0] if tlws else None


def _titan_ui_active(frame):
    iui = getattr(frame, 'invisible_ui', None)
    return bool(iui is not None and getattr(iui, 'active', False))


def _launch(require_titan_ui):
    def _open():
        frame = _find_main_frame()
        if require_titan_ui and not _titan_ui_active(frame):
            return
        if not ai_provider.is_ai_enabled():
            return
        try:
            from src.ai.assistant.assistant_gui import open_assistant
            open_assistant(frame, mode='turn')
        except Exception as e:
            print(f"[assistant.hotkeys] could not open assistant: {e}")
    # keyboard fires on its own thread; hop to the GUI thread.
    wx.CallAfter(_open)


def unregister():
    global _handles
    try:
        import keyboard
    except Exception:
        _handles = []
        return
    for h in _handles:
        try:
            keyboard.remove_hotkey(h)
        except Exception:
            pass
    _handles = []


def register():
    """(Re)register both assistant hotkeys from current settings. Safe to call
    repeatedly (e.g. after the settings dialog saves)."""
    unregister()
    if not ai_provider.is_ai_enabled():
        return
    try:
        import keyboard
    except Exception as e:
        print(f"[assistant.hotkeys] keyboard library unavailable: {e}")
        return

    combos = [
        (ai_provider.get_assistant_hotkey(), False),
        (ai_provider.get_assistant_titan_hotkey(), True),
    ]
    for normalized, titan_only in combos:
        hk = _to_keyboard_hotkey(normalized)
        if not hk:
            continue
        try:
            handle = keyboard.add_hotkey(
                hk, lambda t=titan_only: _launch(t), suppress=False)
            _handles.append(handle)
        except Exception as e:
            print(f"[assistant.hotkeys] failed to register {hk!r}: {e}")

"""
Gamepad Mode API for TCE Launcher
=================================

This module defines the public API for *custom* gamepad modes. Built-in modes
(System / Controller / Screen reader / Screen keyboard) live in
``controller_modes.py``; custom modes are user-droppable packages under
``data/gamepad/modes/`` (and the per-user overlay
``%APPDATA%/titosoft/Titan/data/gamepad/modes/``).

Each custom mode is a *folder*, exactly like a component:

    data/gamepad/modes/my_mode/
        __mode__.TCE        # INI config: [mode] name / main / status ...
        my_mode.py          # subclass of GamepadMode
        languages/          # the mode's own translations (gettext)
            my_mode.pot
            pl/LC_MESSAGES/my_mode.po (+ .mo)
            en/LC_MESSAGES/my_mode.po (+ .mo)

``__mode__.TCE`` looks like::

    [mode]
    name = My Mode
    name_pl = Moj tryb
    name_en = My Mode
    main = my_mode.py
    domain = my_mode
    description = What the mode does
    status = 0

* ``status`` - 0 = enabled (loaded), anything else = disabled.
* ``name`` / ``name_<lang>`` - the label announced when the mode is selected.
* ``main`` - the Python file defining the mode (defaults to the only ``*.py``).
* ``domain`` - the gettext domain for the mode's ``languages/`` folder
  (defaults to the folder name).

The mode manager adds every loaded mode to the mode cycle (HOLD a bumper for
about a second to switch modes - LB = previous, RB = next). While a custom mode
is active it receives the controller's button / analog-stick / d-pad events
through the ``handle_*`` hooks.

Writing the mode class
----------------------

    from src.controller.gamepad_mode_api import (
        GamepadMode, setup_mode_translations, tap, speak)

    _ = setup_mode_translations(__file__, 'my_mode')

    class MyMode(GamepadMode):
        name = "My Mode"

        def handle_button(self, button_id):
            if button_id == 0:          # A on an Xbox pad
                speak(_("Hello from my mode"))
                return True
            return False

The loader picks up any ``GamepadMode`` subclass defined in the main module.
Events are edge-detected and debounced by the mode manager, so each
``handle_axis`` call is a single discrete stick "flick" and ``handle_button``
fires once per press.

Helper functions
----------------

* :func:`setup_mode_translations` - load the mode's own gettext domain
* :func:`tap` / :func:`press` / :func:`release` - simulate keystrokes
* :func:`tap_combo` - simulate a chord such as ``Ctrl+C``
* :func:`type_text` - type a string
* :func:`speak` - send text to the screen reader / stereo speech
* :func:`play_mode_sound` - play a TCE sound effect
* :func:`get_clipboard_text` - read the current clipboard text (Windows)
* :func:`is_edit_field_focused` - True when a text caret is present (Windows)

Button numbering (standard Xbox / XInput layout): 0=A, 1=B, 2=X, 3=Y,
6=Back/View, 7=Start/Menu, 8=left-stick press, 9=right-stick press,
10=Guide. Bumpers 4/5 are reserved for mode switching and never reach a mode.
Axis numbering: 0=left X, 1=left Y, 2=right X, 3=right Y.
"""

import os
import sys
import time
import gettext
import configparser
import importlib.util

MODE_CONFIG_FILE = '__mode__.TCE'


# --------------------------------------------------------------------------- #
# Base class
# --------------------------------------------------------------------------- #
class GamepadMode:
    """Base class for a custom gamepad mode.

    Subclass this and override the ``handle_*`` hooks. The display name comes
    from ``__mode__.TCE`` (the loader sets it on the instance); ``name`` is only
    a fallback used when no config name is provided.
    """

    #: Fallback mode name. The loader overrides this from __mode__.TCE.
    name = "Custom Mode"

    #: Stable identifier ("custom:<folder>") used to persist / restore the
    #: selected mode. Set by the loader - do not set this yourself.
    mode_id = None

    #: Display name resolved from __mode__.TCE for the current language. Set by
    #: the loader; falls back to ``name`` when absent.
    _display_name = None

    def get_display_name(self):
        """Return the display name announced when this mode becomes active."""
        return self._display_name or self.name

    # -- lifecycle ---------------------------------------------------------- #
    def on_activate(self, manager):
        """Called when this mode becomes the active mode."""
        pass

    def on_deactivate(self, manager):
        """Called when switching away from this mode."""
        pass

    # -- input hooks -------------------------------------------------------- #
    def handle_button(self, button_id):
        """Handle a button press. Return True if consumed.

        Called once per physical press (not on release). Bumpers (4, 5) are
        reserved for mode switching and are never delivered here.
        """
        return False

    def handle_axis(self, axis_id, value):
        """Handle an analog-stick "flick". Return True if consumed.

        ``value`` is the axis value at the moment the stick crossed the
        dead-zone (negative = up/left, positive = down/right). The event is
        already debounced, so one call == one discrete movement.
        """
        return False

    def handle_hat(self, x, y):
        """Handle a d-pad movement. Return True if consumed.

        ``x`` is -1 (left) / 0 / 1 (right); ``y`` is 1 (up) / 0 / -1 (down),
        matching pygame's hat convention. Edge-detected: one call per change.
        """
        return False

    def handle_bumper(self, is_left):
        """Handle a bumper *tap* (press + release under the hold threshold).

        ``is_left`` is True for LB, False for RB. Return True if consumed.

        Bumpers do double duty: a short tap is delivered here, while HOLDING a
        bumper for ~1s still changes the controller mode. A mode that does not
        use bumpers simply returns False and the tap is ignored.
        """
        return False


# --------------------------------------------------------------------------- #
# Translation helper (mirrors how components load their own languages/ folder)
# --------------------------------------------------------------------------- #
def setup_mode_translations(mode_file, domain, default_lang='pl'):
    """Return a gettext ``_`` bound to the mode's own ``languages/`` folder.

    Call this at module level in the mode's main file::

        _ = setup_mode_translations(__file__, 'my_mode')

    ``mode_file`` is the mode module's ``__file__``; ``domain`` is the gettext
    domain (the ``.po``/``.mo`` base name). Falls back to an identity function
    so a missing translation never breaks the mode.
    """
    locale_dir = os.path.join(os.path.dirname(os.path.abspath(mode_file)), 'languages')
    try:
        from src.titan_core.translation import language_code
        lang = language_code
    except Exception:
        lang = default_lang
    try:
        translation = gettext.translation(domain, locale_dir, languages=[lang], fallback=True)
        return translation.gettext
    except Exception:
        return lambda x: x


# --------------------------------------------------------------------------- #
# Input / output helpers (thin wrappers over the built-in mode machinery)
# --------------------------------------------------------------------------- #
def press(key):
    """Press (hold) a key. Key names follow controller_modes._PYNPUT_KEYS."""
    from src.controller.controller_modes import _press
    _press(key)


def release(key):
    """Release a key previously pressed with :func:`press`."""
    from src.controller.controller_modes import _release
    _release(key)


def tap(key, hold=0.04):
    """Press and release a single key."""
    from src.controller.controller_modes import _press, _release
    _press(key)
    time.sleep(hold)
    _release(key)


def tap_combo(*keys, hold=0.04):
    """Simulate a chord, e.g. ``tap_combo('ctrl', 'c')``.

    Presses the keys in order then releases them in reverse order.
    """
    from src.controller.controller_modes import _press, _release
    pressed = []
    try:
        for key in keys:
            _press(key)
            pressed.append(key)
            time.sleep(0.01)
        time.sleep(hold)
    finally:
        for key in reversed(pressed):
            _release(key)
            time.sleep(0.005)


def type_text(text):
    """Type a string of characters."""
    for ch in text:
        tap(ch)


def speak(text, position=0.0, interrupt=True):
    """Speak ``text`` through the active mode manager (stereo aware)."""
    try:
        from src.controller.controller_modes import get_mode_manager
        get_mode_manager().speak(text, position=position, interrupt=interrupt)
    except Exception as e:
        print(f"[GamepadMode] speak failed: {e}")


def play_mode_sound(path='joystick/ui2.ogg'):
    """Play a TCE sound effect (path relative to the active sound theme)."""
    try:
        from src.titan_core.sound import play_sound
        play_sound(path)
    except Exception as e:
        print(f"[GamepadMode] play_mode_sound failed: {e}")


def get_clipboard_text():
    """Return the current clipboard text, or '' if empty/unavailable.

    Uses the Win32 clipboard directly so it is safe to call from the controller
    polling thread (unlike wx.TheClipboard, which is main-thread only).
    """
    if sys.platform != 'win32':
        return ''
    try:
        import ctypes
        from ctypes import wintypes

        CF_UNICODETEXT = 13
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

        if not user32.OpenClipboard(None):
            return ''
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ''
            locked = kernel32.GlobalLock(handle)
            if not locked:
                return ''
            try:
                return ctypes.c_wchar_p(locked).value or ''
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception as e:
        print(f"[GamepadMode] get_clipboard_text failed: {e}")
        return ''


def get_focused_window_text():
    """Return the full text of the focused control, read-only (Windows).

    Uses ``WM_GETTEXT`` against the focused window, so it reads the whole
    contents of a standard edit control WITHOUT moving the caret, changing the
    selection or sending any keystrokes - i.e. without "driving" the app. Good
    for grabbing a document into a virtual buffer. Returns '' when there is no
    focused text or the control does not expose its text this way (some
    web / UWP controls). Returns '' on non-Windows.
    """
    if sys.platform != 'win32':
        return ''
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                        ("rcCaret", RECT)]

        user32 = ctypes.windll.user32
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        if not user32.GetGUIThreadInfo(0, ctypes.byref(info)):
            return ''
        hwnd = info.hwndFocus or info.hwndCaret
        if not hwnd:
            return ''

        WM_GETTEXTLENGTH = 0x000E
        WM_GETTEXT = 0x000D
        SMTO_ABORTIFHUNG = 0x0002
        ULONG_PTR = ctypes.c_size_t
        LRESULT = ctypes.c_ssize_t

        send = user32.SendMessageTimeoutW
        send.restype = LRESULT
        send.argtypes = [wintypes.HWND, wintypes.UINT, ULONG_PTR, ctypes.c_void_p,
                         wintypes.UINT, wintypes.UINT, ctypes.POINTER(ULONG_PTR)]

        result = ULONG_PTR(0)
        if not send(hwnd, WM_GETTEXTLENGTH, 0, None, SMTO_ABORTIFHUNG, 200,
                    ctypes.byref(result)):
            return ''
        length = int(result.value)
        if length <= 0:
            return ''
        buf = ctypes.create_unicode_buffer(length + 1)
        send(hwnd, WM_GETTEXT, length + 1, buf, SMTO_ABORTIFHUNG, 500,
             ctypes.byref(result))
        return buf.value or ''
    except Exception as e:
        print(f"[GamepadMode] get_focused_window_text failed: {e}")
        return ''


def is_edit_field_focused():
    """Return True when the focused control currently shows a text caret.

    Windows only - uses GetGUIThreadInfo and checks for a caret window, which
    is a reliable signal that focus is inside an editable text field. On other
    platforms returns True (so modes stay usable; callers can refine).
    """
    if sys.platform != 'win32':
        return True
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                        ("rcCaret", RECT)]

        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        if not ctypes.windll.user32.GetGUIThreadInfo(0, ctypes.byref(info)):
            return False
        return bool(info.hwndCaret)
    except Exception as e:
        print(f"[GamepadMode] is_edit_field_focused failed: {e}")
        return False


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #
def _read_mode_config(folder_path):
    """Read __mode__.TCE from a mode folder. Returns a dict or None."""
    config_path = os.path.join(folder_path, MODE_CONFIG_FILE)
    if not os.path.isfile(config_path):
        return None
    parser = configparser.ConfigParser()
    try:
        parser.read(config_path, encoding='utf-8')
    except Exception as e:
        print(f"[GamepadMode] could not read {config_path}: {e}")
        return None
    if not parser.has_section('mode'):
        return None
    return dict(parser.items('mode'))


def _localized_name(config, folder_name):
    """Pick the display name for the current language from a mode config."""
    try:
        from src.titan_core.translation import language_code
        lang = language_code
    except Exception:
        lang = 'pl'
    for key in (f'name_{lang}', 'name_en', 'name'):
        value = config.get(key)
        if value:
            return value
    return folder_name


def _discover_mode_folders():
    """Yield (folder_name, folder_path) for every mode package (user wins)."""
    try:
        from src.platform_utils import discover_data_entries
        entries = discover_data_entries(os.path.join('gamepad', 'modes'))
    except Exception as e:
        print(f"[GamepadMode] could not enumerate mode folders: {e}")
        return []
    return list(entries.items())


def load_custom_modes():
    """Discover and instantiate every custom gamepad mode.

    Scans ``data/gamepad/modes/<folder>/`` (bundled + user overlay) for folders
    containing ``__mode__.TCE``. Returns a list of :class:`GamepadMode`
    instances ready to be added to the mode cycle. A folder that fails to load
    is logged and skipped so one broken mode never blocks the others.
    """
    modes = []
    for folder_name, folder_path in _discover_mode_folders():
        config = _read_mode_config(folder_path)
        if config is None:
            continue  # not a mode package

        # status: 0 = enabled, anything else = disabled (mirrors components).
        if str(config.get('status', '0')).strip() not in ('0', ''):
            print(f"[GamepadMode] mode '{folder_name}' is disabled - skipping")
            continue

        # Locate the main Python file.
        main_name = config.get('main', '').strip()
        if main_name:
            main_path = os.path.join(folder_path, main_name)
        else:
            py_files = [f for f in sorted(os.listdir(folder_path))
                        if f.endswith('.py') and not f.startswith('_')]
            main_path = os.path.join(folder_path, py_files[0]) if py_files else ''
        if not main_path or not os.path.isfile(main_path):
            print(f"[GamepadMode] mode '{folder_name}': main file not found")
            continue

        mode_id = f"custom:{folder_name}"
        try:
            spec = importlib.util.spec_from_file_location(
                f"tce_gamepad_mode_{folder_name}", main_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"[GamepadMode] failed to load mode '{main_path}': {e}")
            import traceback
            traceback.print_exc()
            continue

        display_name = _localized_name(config, folder_name)
        found_in_folder = False
        for attr in vars(module).values():
            if (isinstance(attr, type) and issubclass(attr, GamepadMode)
                    and attr is not GamepadMode
                    and attr.__module__ == module.__name__):
                try:
                    instance = attr()
                    instance.mode_id = (mode_id if not found_in_folder
                                        else f"{mode_id}:{attr.__name__}")
                    instance._display_name = display_name
                    modes.append(instance)
                    found_in_folder = True
                    print(f"[GamepadMode] loaded mode '{display_name}'"
                          f" ({instance.mode_id}) from {folder_path}")
                except Exception as e:
                    print(f"[GamepadMode] could not instantiate {attr}: {e}")
        if not found_in_folder:
            print(f"[GamepadMode] mode '{folder_name}': no GamepadMode subclass found")
    return modes

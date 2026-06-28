# -*- coding: utf-8 -*-
"""Low-level keyboard hook for Titan Access.

Python port of the C# ``Keyboard/KeyboardHookManager.cs`` + ``InsertKeyHandler.cs``.
Installs a ``WH_KEYBOARD_LL`` global hook (via ``ctypes``/``SetWindowsHookExW``)
and decodes ``KBDLLHOOKSTRUCT`` for every key event. The hook recognises the NVDA
style "reader modifier" (Insert and/or CapsLock, configurable through
``settings.modifier``) and routes key presses to the engine callbacks:

    engine.on_modifier_gesture(vk, key_name, ctrl, alt, shift) -> bool
    engine.on_plain_key(vk, key_name, ctrl, alt, shift)        -> bool
    engine.on_char_typed(ch)
    engine.on_word_typed(word)
    engine.on_toggle_key(kind, is_on)   # kind: 'caps' | 'num' | 'scroll'

A callback returning ``True`` means "the key was consumed" and the hook swallows
it (it never reaches the focused application).

IMPORTANT threading note
-------------------------
:class:`titan_access.engine.TitanAccessEngine` calls :meth:`start` on its own
worker thread, and that thread *already* runs a Win32 ``GetMessage`` pump. A
``WH_KEYBOARD_LL`` hook is dispatched on the thread that installed it, through
that thread's message loop, so :meth:`start` only needs to install the hook --
it must **not** spin up a second message loop.

The module is import-safe on non-Windows: :meth:`start` becomes a no-op.
"""

import ctypes
import platform
import sys

_IS_WINDOWS = sys.platform.startswith("win") or platform.system() == "Windows"

# --------------------------------------------------------------------------- #
# Win32 constants
# --------------------------------------------------------------------------- #
WH_KEYBOARD_LL = 13
HC_ACTION = 0

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

KEYEVENTF_KEYUP = 0x0002
# Sentinel placed in dwExtraInfo of CapsLock toggles we inject ourselves, so the
# hook recognises and ignores them (prevents a feedback loop).
_INJECT_SENTINEL = 0x7A11A11

# KBDLLHOOKSTRUCT.flags bits (mirror InsertKeyHandler.cs)
LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10
LLKHF_ALTDOWN = 0x20
LLKHF_UP = 0x80

# Virtual key codes we care about
VK_BACK = 0x08
VK_TAB = 0x09
VK_CLEAR = 0x0C        # NumPad 5 with NumLock off
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12         # Alt
VK_CAPITAL = 0x14      # CapsLock
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21        # PageUp / NumPad 9
VK_NEXT = 0x22         # PageDown / NumPad 3
VK_END = 0x23          # NumPad 1
VK_HOME = 0x24         # NumPad 7
VK_LEFT = 0x25         # NumPad 4
VK_UP = 0x26           # NumPad 8
VK_RIGHT = 0x27        # NumPad 6
VK_DOWN = 0x28         # NumPad 2
VK_INSERT = 0x2D       # NumPad 0 with NumLock off
VK_DELETE = 0x2E       # NumPad . with NumLock off
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_NUMPAD0 = 0x60
VK_NUMPAD9 = 0x69
VK_MULTIPLY = 0x6A
VK_ADD = 0x6B
VK_SUBTRACT = 0x6D
VK_DECIMAL = 0x6E
VK_DIVIDE = 0x6F
VK_F1 = 0x70
VK_F24 = 0x87
VK_NUMLOCK = 0x90
VK_SCROLL = 0x91

# Modifier-key vk groups
_CTRL_KEYS = {0x11, 0xA2, 0xA3}
_ALT_KEYS = {0x12, 0xA4, 0xA5}
_SHIFT_KEYS = {0x10, 0xA0, 0xA1}
_WIN_KEYS = {0x5B, 0x5C}

# Punctuation key_name table (OEM virtual keys -> literal char name)
_OEM_NAMES = {
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
    0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}

# Navigation vks shared between arrows/edit-keys and the NumPad (NumLock off).
_NAV_EXTENDED_NAMES = {
    VK_LEFT: "left", VK_RIGHT: "right", VK_UP: "up", VK_DOWN: "down",
    VK_HOME: "home", VK_END: "end", VK_PRIOR: "pageup", VK_NEXT: "pagedown",
    VK_INSERT: "insert", VK_DELETE: "delete", VK_CLEAR: "clear",
}
_NAV_NUMPAD_NAMES = {
    VK_HOME: "numpad7", VK_UP: "numpad8", VK_PRIOR: "numpad9",
    VK_LEFT: "numpad4", VK_CLEAR: "numpad5", VK_RIGHT: "numpad6",
    VK_END: "numpad1", VK_DOWN: "numpad2", VK_NEXT: "numpad3",
    VK_INSERT: "numpad0", VK_DELETE: "numpaddecimal",
}
# NumPad keys that drive object navigation.
_OBJNAV_NUMPAD = {"numpad2", "numpad4", "numpad5", "numpad6", "numpad8", "numpadenter"}
# When the reader modifier is held, real arrows act like the NumPad object-nav
# keys (port of the "Insert+arrows == NumPad 2/4/6/8" branch in C#).
_ARROW_TO_NUMPAD = {
    "left": "numpad4", "right": "numpad6", "up": "numpad8", "down": "numpad2",
}
# Real (extended) caret-movement keys that trigger reading inside an edit field.
_EDIT_CARET_KEYS = {"left", "right", "up", "down", "home", "end"}
VK_RMENU = 0xA5  # right Alt (AltGr)


if _IS_WINDOWS:
    from ctypes import wintypes

    ULONG_PTR = ctypes.c_size_t
    HHOOK = ctypes.c_void_p          # opaque handle (void*) — must NOT be c_int
    LRESULT = ctypes.c_ssize_t

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    # WINFUNCTYPE = stdcall callback (correct convention for a Win32 hook proc).
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM,
                                  wintypes.LPARAM)

    # Private, fully-typed DLL handles. Setting restype/argtypes is ESSENTIAL on
    # 64-bit: without it ctypes defaults every return to a 32-bit int, which
    # truncates HMODULE/HHOOK pointers and makes SetWindowsHookExW fail (the
    # module handle it receives is a sliced, invalid pointer). use_last_error
    # lets get_last_error() report the real failure code.
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

    _user32.SetWindowsHookExW.restype = HHOOK
    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC,
                                          wintypes.HMODULE, wintypes.DWORD]
    _user32.CallNextHookEx.restype = LRESULT
    _user32.CallNextHookEx.argtypes = [HHOOK, ctypes.c_int,
                                       wintypes.WPARAM, wintypes.LPARAM]
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _user32.UnhookWindowsHookEx.argtypes = [HHOOK]
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                 ctypes.POINTER(wintypes.DWORD)]
    _user32.GetKeyboardLayout.restype = wintypes.HKL
    _user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
    _user32.GetKeyState.restype = ctypes.c_short
    _user32.GetKeyState.argtypes = [ctypes.c_int]
    _user32.ToUnicodeEx.restype = ctypes.c_int
    _user32.ToUnicodeEx.argtypes = [
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ubyte),
        wintypes.LPWSTR, ctypes.c_int, wintypes.UINT, wintypes.HKL,
    ]
    _user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE,
                                    wintypes.DWORD, ULONG_PTR]
else:
    _user32 = None
    _kernel32 = None


class KeyboardHook:
    """Installs and services the global low-level keyboard hook."""

    def __init__(self, engine):
        self.engine = engine
        # Set by the engine/browse subsystem; lets on_plain_key intercept arrows.
        self.is_in_browse_mode = False
        # Set by the engine on focus: True when the focused control is an edit /
        # document / combobox, so arrow movements trigger caret reading.
        self.is_in_edit_field = False

        self._hook = None
        self._proc = None          # strong ref to the CFUNCTYPE (avoid GC!)
        self._installed = False

        # Modifier hold-state (updated on every key event).
        self._ctrl = False
        self._alt = False
        self._ralt = False         # right Alt == AltGr (Polish diacritics)
        self._shift = False
        self._reader_mod = False   # NVDA reader modifier (Insert / CapsLock) held
        self._mod_used = False     # another key was pressed while the modifier was held

        # Echo word buffer.
        self._word = []

        # Fully-typed user32 handle (see module-level setup).
        self._user32 = _user32

    # ==================================================================== #
    # Lifecycle
    # ==================================================================== #
    def start(self):
        """Install the WH_KEYBOARD_LL hook on the current (engine worker) thread.

        Does NOT start a message loop -- the caller's thread already pumps
        messages. No-op on non-Windows platforms.
        """
        if not _IS_WINDOWS:
            print("[TitanAccess] keyboard_hook: non-Windows, hook disabled")
            return self
        if self._installed:
            return self
        try:
            self._proc = HOOKPROC(self._hook_proc)
            hmod = _kernel32.GetModuleHandleW(None)
            self._hook = _user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._proc, hmod, 0)
            self._installed = bool(self._hook)
            if not self._installed:
                err = ctypes.get_last_error()
                print(f"[TitanAccess] keyboard_hook: install failed (err={err})")
            else:
                print("[TitanAccess] keyboard_hook: installed")
        except Exception as e:
            print(f"[TitanAccess] keyboard_hook: install error: {e}")
        return self

    def stop(self):
        """Remove the hook."""
        if not _IS_WINDOWS or not self._installed:
            return
        try:
            self._user32.UnhookWindowsHookEx(self._hook)
        except Exception as e:
            print(f"[TitanAccess] keyboard_hook: unhook error: {e}")
        finally:
            self._installed = False
            self._hook = None

    # ==================================================================== #
    # Hook procedure
    # ==================================================================== #
    def _hook_proc(self, nCode, wParam, lParam):
        """Native callback. Returns 1 to swallow the key, else CallNextHookEx."""
        swallow = False
        try:
            if nCode == HC_ACTION:
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                # Ignore the CapsLock toggles we inject ourselves.
                if int(kb.dwExtraInfo) == _INJECT_SENTINEL:
                    return self._user32.CallNextHookEx(self._hook, nCode, wParam, lParam)
                vk = int(kb.vkCode)
                scan = int(kb.scanCode)
                flags = int(kb.flags)
                is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                swallow = self._process(vk, scan, flags, is_down)
        except Exception as e:  # never let an exception escape the hook
            print(f"[TitanAccess] keyboard_hook: proc error: {e}")
        if swallow:
            return 1
        return self._user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

    def _process(self, vk, scan, flags, is_down):
        """Core routing. Returns True to swallow the key."""
        extended = bool(flags & LLKHF_EXTENDED)

        # ---- 1. Modifier / toggle keys -------------------------------- #
        # The reader modifier (Insert / CapsLock per settings) is tracked here
        # and swallowed so it never reaches applications. When CapsLock is the
        # modifier, a lone tap (no other key pressed while held) still toggles
        # and announces CapsLock, like NVDA -- so the user can both use it as a
        # modifier and hear its state.
        if self._is_reader_modifier(vk, extended):
            if is_down:
                if not self._reader_mod:
                    self._mod_used = False  # fresh press starts a new "chord"
                self._reader_mod = True
            else:
                was_used = self._mod_used
                self._reader_mod = False
                if vk == VK_CAPITAL and not was_used:
                    self._caps_tap_toggle()
            return True  # swallow the modifier itself

        # Any non-modifier key while the modifier is held marks the chord as
        # "used", so releasing the modifier is not treated as a lone tap.
        if self._reader_mod and is_down:
            self._mod_used = True

        if vk in _CTRL_KEYS:
            self._ctrl = is_down
            # Pressing either Ctrl silences speech (standard screen-reader
            # behaviour). EXCEPT the synthetic left-Ctrl that AltGr injects: it
            # arrives with scanCode 0x21D (real Ctrl is 0x1D), and swallowing it
            # for speech would cut off speech every time the user types a Polish
            # diacritic (AltGr + letter).
            if is_down and scan != 0x21D:
                try:
                    self.engine.on_stop_speech_key()
                except Exception as e:
                    print(f"[TitanAccess] keyboard_hook: stop-speech error: {e}")
            return False
        if vk in _ALT_KEYS:
            self._alt = is_down
            if vk == VK_RMENU:
                self._ralt = is_down
            return False
        if vk in _SHIFT_KEYS:
            self._shift = is_down
            return False
        if vk in _WIN_KEYS:
            return False

        # Toggle keys: announce the resulting on/off state on key-up.
        if vk in (VK_CAPITAL, VK_NUMLOCK, VK_SCROLL):
            if not is_down:
                self._handle_toggle(vk)
            return False

        if not is_down:
            return False  # everything below is key-down only

        # Normalise vk -> key_name and learn whether it is a NumPad nav key.
        key_name, is_numpad_nav = self._normalize(vk, extended)

        # ---- 2. Reader-modifier gestures (Insert+key) ----------------- #
        if self._reader_mod:
            name = _ARROW_TO_NUMPAD.get(key_name, key_name)
            try:
                if self.engine.on_modifier_gesture(vk, name, self._ctrl,
                                                   self._alt, self._shift):
                    return True
            except Exception as e:
                print(f"[TitanAccess] keyboard_hook: modifier gesture error: {e}")
            # Modifier held but unhandled: do not echo, do not block.
            return False

        # ---- 3. NumPad object navigation + dial (NumLock off, no reader mod) -- #
        # NumPad Minus toggles the dial; NumPad 4/6/8/2/5/Enter drive object
        # navigation (or the dial when it is active). All route through the
        # engine's modifier-gesture handler.
        if (is_numpad_nav or key_name == "numpadsubtract") and not self._ctrl and not self._alt:
            try:
                if self.engine.on_modifier_gesture(vk, key_name, self._ctrl,
                                                   self._alt, self._shift):
                    return True
            except Exception as e:
                print(f"[TitanAccess] keyboard_hook: numpad nav error: {e}")

        # (Ctrl+Alt review shortcuts removed -- they clashed with AltGr typing on
        # a Polish keyboard, so Ctrl+Alt combos now pass straight through.)

        # ---- 4. Plain key (browse mode quick-nav / arrows) ------------ #
        try:
            if self.engine.on_plain_key(vk, key_name, self._ctrl,
                                        self._alt, self._shift):
                return True
        except Exception as e:
            print(f"[TitanAccess] keyboard_hook: plain key error: {e}")

        # ---- 4b. Edit-field caret tracking (read after the caret moves) --- #
        # In an edit / document control, arrow / Home / End movements are NOT
        # swallowed (the app moves the caret); we schedule a read of the new
        # position. Ctrl+Left/Right read by word; Ctrl+Up/Down/Home/End are left
        # to the app without a special read. Port of the C# non-blocking
        # ProcessArrowNavigation / ProcessCtrlArrowNavigation.
        if (self.is_in_edit_field and not self._alt and not self._reader_mod
                and key_name in _EDIT_CARET_KEYS):
            if not (self._ctrl and key_name not in ("left", "right")):
                try:
                    self.engine.on_edit_caret_move(key_name, self._ctrl)
                except Exception as e:
                    print(f"[TitanAccess] keyboard_hook: edit caret error: {e}")
            return False  # never swallow caret movement

        # ---- 5. Character / word echo --------------------------------- #
        # Only echo ordinary typing: no Ctrl/Alt, no reader modifier.
        if not self._ctrl and not self._alt and not self._reader_mod:
            try:
                self._echo(vk, scan)
            except Exception as e:
                print(f"[TitanAccess] keyboard_hook: echo error: {e}")

        return False

    # ==================================================================== #
    # Reader modifier detection (port of InsertKeyHandler)
    # ==================================================================== #
    def _modifier_config(self):
        """Return (use_insert, use_capslock) for the configured reader modifier."""
        try:
            mod = self.engine.settings.modifier
        except Exception:
            mod = "InsertAndCapsLock"
        use_insert = mod in ("Insert", "InsertAndCapsLock")
        use_caps = mod in ("CapsLock", "InsertAndCapsLock")
        return use_insert, use_caps

    def _is_reader_modifier(self, vk, extended):
        """Is *vk* the active NVDA reader modifier key?

        Both the extended Insert (above Home/End) and the NumPad Insert (Num0
        with NumLock off, which arrives as VK_INSERT without LLKHF_EXTENDED) act
        as the modifier when "Insert" is configured. CapsLock acts as the
        modifier when "CapsLock" is configured.
        """
        use_insert, use_caps = self._modifier_config()
        if vk == VK_INSERT and use_insert:
            return True
        if vk == VK_CAPITAL and use_caps:
            return True
        return False

    # ==================================================================== #
    # Toggle keys
    # ==================================================================== #
    def _caps_tap_toggle(self):
        """Toggle the real CapsLock and announce it (CapsLock-as-modifier tap).

        The physical CapsLock was swallowed (it is the reader modifier), so we
        re-inject a CapsLock press to flip the OS state. The injected events
        carry :data:`_INJECT_SENTINEL` in ``dwExtraInfo`` so the hook ignores
        them. We announce the *expected* new state (the inverse of the current
        one) because ``GetKeyState`` may not reflect the injected toggle yet.
        """
        try:
            cur = bool(_user32.GetKeyState(VK_CAPITAL) & 0x0001)
            _user32.keybd_event(VK_CAPITAL, 0, 0, _INJECT_SENTINEL)
            _user32.keybd_event(VK_CAPITAL, 0, KEYEVENTF_KEYUP, _INJECT_SENTINEL)
            self.engine.on_toggle_key("caps", not cur)
        except Exception as e:
            print(f"[TitanAccess] keyboard_hook: caps tap error: {e}")

    def _handle_toggle(self, vk):
        try:
            on = bool(self._user32.GetKeyState(vk) & 0x0001)
        except Exception:
            return
        kind = {VK_CAPITAL: "caps", VK_NUMLOCK: "num", VK_SCROLL: "scroll"}.get(vk)
        if kind is None:
            return
        try:
            self.engine.on_toggle_key(kind, on)
        except Exception as e:
            print(f"[TitanAccess] keyboard_hook: toggle callback error: {e}")

    # ==================================================================== #
    # vk -> key_name normalisation
    # ==================================================================== #
    def _normalize(self, vk, extended):
        """Map a virtual key to a normalized name and a NumPad-nav flag.

        Returns ``(key_name, is_numpad_nav)``. NumPad keys collapse onto names
        like ``numpad4`` so the gesture system can bind object navigation to
        them regardless of the physical NumLock state.
        """
        # Enter: the NumPad Enter carries the EXTENDED flag; the main Return key
        # does not. Only the NumPad Enter drives object-nav activation -- the
        # normal Return must keep working as a plain Enter for applications.
        if vk == VK_RETURN:
            return ("numpadenter", True) if extended else ("enter", False)

        # Explicit NumPad digits (arrive only when NumLock is ON).
        if VK_NUMPAD0 <= vk <= VK_NUMPAD9:
            return (f"numpad{vk - VK_NUMPAD0}", False)

        # NumPad operators.
        if vk == VK_MULTIPLY:
            return ("numpadmultiply", False)
        if vk == VK_ADD:
            return ("numpadadd", False)
        if vk == VK_SUBTRACT:
            return ("numpadsubtract", False)
        if vk == VK_DIVIDE:
            return ("numpaddivide", False)
        if vk == VK_DECIMAL:
            return ("numpaddecimal", False)

        # Shared navigation vks: extended => real arrows/edit keys,
        # non-extended => NumPad origin (NumLock off).
        if vk in _NAV_EXTENDED_NAMES:
            if extended:
                return (_NAV_EXTENDED_NAMES[vk], False)
            name = _NAV_NUMPAD_NAMES.get(vk, _NAV_EXTENDED_NAMES[vk])
            return (name, name in _OBJNAV_NUMPAD)

        # Letters A-Z.
        if 0x41 <= vk <= 0x5A:
            return (chr(vk).lower(), False)

        # Top-row digits 0-9.
        if 0x30 <= vk <= 0x39:
            return (chr(vk), False)

        # Function keys F1-F24.
        if VK_F1 <= vk <= VK_F24:
            return (f"f{vk - VK_F1 + 1}", False)

        # Misc named keys.
        named = {
            VK_SPACE: "space", VK_ESCAPE: "escape", VK_TAB: "tab",
            VK_BACK: "backspace",
        }
        if vk in named:
            return (named[vk], False)

        if vk in _OEM_NAMES:
            return (_OEM_NAMES[vk], False)

        return (f"vk{vk:02x}", False)

    # ==================================================================== #
    # Character / word echo (ToUnicodeEx + word buffer)
    # ==================================================================== #
    def _echo(self, vk, scan):
        # Word terminators: space / enter / tab flush the pending word, then the
        # whitespace itself is echoed as a character (engine gates on the echo
        # setting and speaks "space" / "new line").
        if vk == VK_SPACE:
            self._flush_word()
            self.engine.on_char_typed(" ")
            return
        if vk == VK_RETURN:
            self._flush_word()
            self.engine.on_char_typed("\n")
            return
        if vk == VK_TAB:
            self._flush_word()
            self.engine.on_char_typed("\t")
            return
        if vk == VK_BACK:
            if self._word:
                self._word.pop()
            return

        ch = self._vk_to_char(vk, scan)
        if not ch:
            return  # non-printable (arrows, F-keys, ...)

        if ch.isalnum():
            self._word.append(ch)
            self.engine.on_char_typed(ch)
        else:
            # Punctuation / symbol terminates the current word.
            self._flush_word()
            self.engine.on_char_typed(ch)

    def _flush_word(self):
        if self._word:
            word = "".join(self._word)
            self._word = []
            try:
                self.engine.on_word_typed(word)
            except Exception:
                pass

    def _vk_to_char(self, vk, scan):
        """Translate vk + current modifier/layout state to a unicode char.

        Uses ``ToUnicodeEx`` against the foreground window's keyboard layout so
        non-US layouts and diacritics (e.g. Polish) echo correctly. Returns
        ``None`` for keys that produce no character, and skips dead keys (while
        flushing the dead-key state so live typing is not corrupted).
        """
        u = self._user32
        # Build a synthetic key-state array: only Shift + CapsLock matter for
        # echo (we never reach here with Ctrl/Alt held).
        state = (ctypes.c_ubyte * 256)()
        if self._shift:
            state[VK_SHIFT] = 0x80
        try:
            if u.GetKeyState(VK_CAPITAL) & 0x0001:
                state[VK_CAPITAL] = 0x01
        except Exception:
            pass

        # Keyboard layout of the foreground thread (so the active app's layout
        # is honoured, not ours).
        try:
            hwnd = u.GetForegroundWindow()
            tid = u.GetWindowThreadProcessId(hwnd, None)
            hkl = u.GetKeyboardLayout(tid)
        except Exception:
            hkl = 0

        buf = ctypes.create_unicode_buffer(8)
        try:
            n = u.ToUnicodeEx(vk, scan, state, buf, len(buf), 0, hkl)
        except Exception:
            return None
        if n == -1:
            # Dead key: call again to consume/flush the pending state, skip echo.
            try:
                u.ToUnicodeEx(vk, scan, state, buf, len(buf), 0, hkl)
            except Exception:
                pass
            return None
        if n <= 0:
            return None
        ch = buf.value[:n]
        # Ignore control characters that slipped through.
        if ch and ch[0] >= " ":
            return ch[0]
        return None

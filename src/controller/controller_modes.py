"""
Controller Mode System for TCE Launcher
Implements 4 modes: System, Controller, Screen Reader, and Screen Keyboard modes
With stereo speech support, translations, and vibration feedback
"""

import pygame
import time
import threading
from typing import Optional, Dict, List
from enum import Enum

import sys as _sys

# Keyboard backend abstraction for simulated key presses.
# pynput is preferred: it injects reliably across platforms (including the very
# new Python 3.14), whereas the `keyboard` module's SendInput injection does not
# work in this environment. The `keyboard` module is only a last-resort fallback.
KEYBOARD_AVAILABLE = False
_KB_BACKEND = None  # 'pynput' | 'keyboard'
keyboard = None
_pynput_kb = None
_pynput_ctrl = None

try:
    from pynput import keyboard as _pynput_kb
    _pynput_ctrl = _pynput_kb.Controller()
    _KB_BACKEND = 'pynput'
    KEYBOARD_AVAILABLE = True
except Exception as e:
    print(f"Warning: pynput not available for key injection: {e}")

if not KEYBOARD_AVAILABLE and _sys.platform == 'win32':
    try:
        import keyboard
        _KB_BACKEND = 'keyboard'
        KEYBOARD_AVAILABLE = True
    except Exception as e:
        print(f"Warning: no keyboard backend available (pynput/keyboard): {e}")

# Special-key name -> pynput key. Single characters pass through unchanged.
# 'numN' names map to the numeric keypad (required for NVDA/JAWS review cursor).
if _pynput_kb is not None:
    _KC = _pynput_kb.KeyCode
    _PYNPUT_KEYS = {
        'enter': _pynput_kb.Key.enter, 'escape': _pynput_kb.Key.esc,
        'esc': _pynput_kb.Key.esc, 'backspace': _pynput_kb.Key.backspace,
        'tab': _pynput_kb.Key.tab, 'space': _pynput_kb.Key.space,
        'shift': _pynput_kb.Key.shift, 'ctrl': _pynput_kb.Key.ctrl,
        'alt': _pynput_kb.Key.alt, 'win': _pynput_kb.Key.cmd,
        'cmd': _pynput_kb.Key.cmd, 'insert': _pynput_kb.Key.insert,
        'delete': _pynput_kb.Key.delete, 'home': _pynput_kb.Key.home,
        'end': _pynput_kb.Key.end, 'pageup': _pynput_kb.Key.page_up,
        'pagedown': _pynput_kb.Key.page_down, 'up': _pynput_kb.Key.up,
        'down': _pynput_kb.Key.down, 'left': _pynput_kb.Key.left,
        'right': _pynput_kb.Key.right, 'capslock': _pynput_kb.Key.caps_lock,
        'f4': _pynput_kb.Key.f4, 'f12': _pynput_kb.Key.f12,
        # Numeric keypad (VK_NUMPAD0..9 = 0x60..0x69)
        'num0': _KC.from_vk(0x60), 'num1': _KC.from_vk(0x61),
        'num2': _KC.from_vk(0x62), 'num3': _KC.from_vk(0x63),
        'num4': _KC.from_vk(0x64), 'num5': _KC.from_vk(0x65),
        'num6': _KC.from_vk(0x66), 'num7': _KC.from_vk(0x67),
        'num8': _KC.from_vk(0x68), 'num9': _KC.from_vk(0x69),
    }
else:
    _PYNPUT_KEYS = {}


def _press(key):
    """Press (hold) a key using whichever backend is available."""
    if not KEYBOARD_AVAILABLE:
        print(f"[INPUT] press '{key}' ignored - no keyboard backend available")
        return
    try:
        if _KB_BACKEND == 'pynput':
            _pynput_ctrl.press(_PYNPUT_KEYS.get(key, key))
        else:
            keyboard.press(key.replace('num', '') if key.startswith('num') else key)
    except Exception as e:
        print(f"[INPUT] press '{key}' failed: {e}")


def _release(key):
    """Release a key using whichever backend is available."""
    if not KEYBOARD_AVAILABLE:
        return
    try:
        if _KB_BACKEND == 'pynput':
            _pynput_ctrl.release(_PYNPUT_KEYS.get(key, key))
        else:
            keyboard.release(key.replace('num', '') if key.startswith('num') else key)
    except Exception as e:
        print(f"[INPUT] release '{key}' failed: {e}")


# --- Numeric-keypad simulation by hardware scancode (Windows) -----------------
# NVDA/JAWS identify numpad review keys by their hardware SCANCODE, not the
# virtual key. Sending VK_NUMPAD4 gets interpreted in a NumLock-dependent way
# (announced as "numLock numpad..."), which is wrong. Sending the raw scancode
# with KEYEVENTF_SCANCODE (non-extended) produces a true physical numpad key
# that the screen reader maps to its review command regardless of NumLock.
_NUMPAD_SCANCODES = {  # Set-1 make codes for the numeric keypad
    '0': 0x52, '1': 0x4F, '2': 0x50, '3': 0x51, '4': 0x4B,
    '5': 0x4C, '6': 0x4D, '7': 0x47, '8': 0x48, '9': 0x49,
}
_sendinput_ready = False
if _sys.platform == 'win32':
    try:
        import ctypes as _ctypes
        from ctypes import wintypes as _wt

        _PUL = _ctypes.POINTER(_ctypes.c_ulong)

        class _KEYBDINPUT(_ctypes.Structure):
            _fields_ = [("wVk", _wt.WORD), ("wScan", _wt.WORD),
                        ("dwFlags", _wt.DWORD), ("time", _wt.DWORD),
                        ("dwExtraInfo", _PUL)]

        class _INPUT(_ctypes.Structure):
            class _U(_ctypes.Union):
                _fields_ = [("ki", _KEYBDINPUT)]
            _anonymous_ = ("u",)
            _fields_ = [("type", _wt.DWORD), ("u", _U)]

        _KEYEVENTF_SCANCODE = 0x0008
        _KEYEVENTF_KEYUP = 0x0002
        _sendinput_ready = True
    except Exception as e:
        print(f"[INPUT] SendInput scancode setup failed: {e}")


def _send_scancode(scan, keyup=False):
    flags = _KEYEVENTF_SCANCODE | (_KEYEVENTF_KEYUP if keyup else 0)
    ki = _KEYBDINPUT(0, scan, flags, 0, None)
    inp = _INPUT(1, _INPUT._U(ki=ki))  # type 1 = INPUT_KEYBOARD
    _ctypes.windll.user32.SendInput(1, _ctypes.byref(inp), _ctypes.sizeof(inp))


def _tap_numpad(digit):
    """Tap a physical numeric-keypad key (e.g. '4') for screen-reader review.

    Uses raw scancodes on Windows (NumLock-independent, what NVDA expects);
    elsewhere falls back to the VK-based numpad key via the normal backend.
    """
    if _sendinput_ready and digit in _NUMPAD_SCANCODES:
        scan = _NUMPAD_SCANCODES[digit]
        try:
            _send_scancode(scan, keyup=False)
            time.sleep(0.03)
            _send_scancode(scan, keyup=True)
            return
        except Exception as e:
            print(f"[INPUT] numpad scancode '{digit}' failed: {e}")
    # Fallback (non-Windows): VK-based numpad key
    _press('num' + digit)
    time.sleep(0.03)
    _release('num' + digit)


# Modifier keys that must never be left held after a simulated action. With the
# tight press/release timing used by the mode handlers a modifier key-up can get
# dropped, which leaves e.g. Insert "stuck" (every later keystroke becomes an
# NVDA command). _release_modifiers() is called after every mode action as a
# guaranteed safety net.
_MODIFIER_KEYS = ('insert', 'shift', 'ctrl', 'alt', 'win')


def _release_modifiers():
    """Force-release all modifier keys (harmless if they were not held)."""
    if not KEYBOARD_AVAILABLE:
        return
    for key in _MODIFIER_KEYS:
        _release(key)

from src.titan_core.translation import _
from src.titan_core.sound import play_sound
from src.controller.controller_vibrations import vibration_controller
from src.titan_core.stereo_speech import get_stereo_speech
from src.settings.settings import get_setting, set_setting, save_settings


class ControllerMode(Enum):
    """Controller operation modes"""
    SYSTEM = "system"  # Default mode - controller works normally
    CONTROLLER = "controller"  # Controller mode - button/stick mapping to keyboard
    SCREENREADER = "screenreader"  # Screen reader mode - NVDA/JAWS shortcuts
    KEYBOARD = "keyboard"  # Screen keyboard mode - virtual keyboard navigation


class VirtualKeyboard:
    """Virtual keyboard layout for controller navigation"""

    LAYOUT = [
        # Row 1: Number row
        ['`', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '='],
        # Row 2: QWERTY row
        ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[', ']', '\\'],
        # Row 3: ASDF row
        ['capslock', 'a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', "'"],
        # Row 4: ZXCV row
        ['shift', 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '/'],
        # Row 5: Space and Enter
        ['space', 'enter']
    ]

    def __init__(self):
        self.row = 0
        self.col = 0
        self.caps_lock_enabled = False
        self.shift_enabled = False

    def get_current_key(self) -> str:
        """Get the currently selected key"""
        if 0 <= self.row < len(self.LAYOUT):
            if 0 <= self.col < len(self.LAYOUT[self.row]):
                return self.LAYOUT[self.row][self.col]
        return ''

    def move_up(self) -> bool:
        """Move up in keyboard layout"""
        if self.row > 0:
            self.row -= 1
            # Adjust column if new row is shorter
            if self.col >= len(self.LAYOUT[self.row]):
                self.col = len(self.LAYOUT[self.row]) - 1
            return True
        return False

    def move_down(self) -> bool:
        """Move down in keyboard layout"""
        if self.row < len(self.LAYOUT) - 1:
            self.row += 1
            # Adjust column if new row is shorter
            if self.col >= len(self.LAYOUT[self.row]):
                self.col = len(self.LAYOUT[self.row]) - 1
            return True
        return False

    def move_left(self) -> bool:
        """Move left in keyboard layout"""
        if self.col > 0:
            self.col -= 1
            return True
        return False

    def move_right(self) -> bool:
        """Move right in keyboard layout"""
        if self.col < len(self.LAYOUT[self.row]) - 1:
            self.col += 1
            return True
        return False

    def type_current_key(self) -> bool:
        """Type the currently selected key"""
        if not KEYBOARD_AVAILABLE:
            return False

        key = self.get_current_key()
        if not key:
            return False

        try:
            if key == 'capslock':
                self.caps_lock_enabled = not self.caps_lock_enabled
                return True
            elif key == 'shift':
                self.shift_enabled = not self.shift_enabled
                return True
            elif key == 'space':
                _press('space')
                time.sleep(0.02)
                _release('space')
                return True
            elif key == 'enter':
                _press('enter')
                time.sleep(0.02)
                _release('enter')
                return True
            else:
                # Apply caps lock or shift
                if self.caps_lock_enabled or self.shift_enabled:
                    _press('shift')
                    time.sleep(0.01)
                    _press(key)
                    time.sleep(0.02)
                    _release(key)
                    time.sleep(0.01)
                    _release('shift')
                    # Disable shift after typing (but not caps lock)
                    if self.shift_enabled:
                        self.shift_enabled = False
                else:
                    _press(key)
                    time.sleep(0.02)
                    _release(key)
                return True
        except Exception as e:
            print(f"Error typing key '{key}': {e}")
            return False

    def backspace(self) -> bool:
        """Simulate backspace"""
        if not KEYBOARD_AVAILABLE:
            return False

        try:
            _press('backspace')
            time.sleep(0.02)
            _release('backspace')
            return True
        except Exception as e:
            print(f"Error pressing backspace: {e}")
            return False

    def get_key_description(self) -> str:
        """Get description of current key for screen reader"""
        key = self.get_current_key()
        if key == 'capslock':
            state = _("on") if self.caps_lock_enabled else _("off")
            return f"{_('Caps Lock')} {state}"
        elif key == 'shift':
            state = _("on") if self.shift_enabled else _("off")
            return f"{_('Shift')} {state}"
        elif key == 'space':
            return _("Space")
        elif key == 'enter':
            return _("Enter")
        else:
            return key.upper() if (self.caps_lock_enabled or self.shift_enabled) else key


class ControllerModeManager:
    """
    Manages controller modes and input mapping
    Implements 4 modes with stereo speech and vibration feedback
    """

    def __init__(self):
        self.current_mode = ControllerMode.SYSTEM
        self.virtual_keyboard = VirtualKeyboard()
        self.bumper_hold_time = 2.0  # seconds to hold trigger to change mode (2 seconds)
        self.left_trigger_pressed_time = None
        self.right_trigger_pressed_time = None
        self.left_trigger_mode_changed = False  # Prevent re-triggering
        self.right_trigger_mode_changed = False

        # Stereo speech support
        self.stereo_speech = get_stereo_speech()
        self.stereo_enabled = False

        # Axis state tracking
        self.last_axis_values = {}
        self.axis_deadzone = 0.3

        # Debouncing for axis movements
        self.last_axis_action_time = {}
        self.axis_repeat_delay = 0.2  # seconds

        # Load settings
        self._load_settings()

    def _load_settings(self):
        """Load controller mode settings"""
        try:
            from src.settings.settings import load_settings
            settings = load_settings()

            mode_str = settings.get('controller', {}).get('controller_mode', 'system')
            try:
                self.current_mode = ControllerMode(mode_str)
            except ValueError:
                self.current_mode = ControllerMode.SYSTEM

            # Check if stereo speech is enabled
            self.stereo_enabled = settings.get('invisible_interface', {}).get('stereo_speech', 'False').lower() in ['true', '1']
        except Exception as e:
            print(f"Error loading controller mode settings: {e}")
            self.current_mode = ControllerMode.SYSTEM
            self.stereo_enabled = False

    def _save_settings(self):
        """Save controller mode settings"""
        try:
            from src.settings.settings import load_settings, save_settings as save_settings_func
            settings = load_settings()
            if 'controller' not in settings:
                settings['controller'] = {}
            settings['controller']['controller_mode'] = self.current_mode.value
            save_settings_func(settings)
            print(f"[MODE] Saved mode setting: {self.current_mode.value}")
        except Exception as e:
            print(f"Error saving controller mode settings: {e}")

    def speak(self, text: str, position: float = 0.0, interrupt: bool = True):
        """
        Speak text with optional stereo positioning
        Compatible with TCE's speech system

        Args:
            text: Text to speak
            position: Stereo position (-1.0 left to 1.0 right)
            interrupt: Whether to interrupt current speech
        """
        try:
            if self.stereo_enabled and self.stereo_speech:
                # Use stereo speech
                self.stereo_speech.speak_async(text, position=position, use_fallback=True)
            else:
                # Fallback to accessible_output3
                import accessible_output3.outputs.auto
                speaker = accessible_output3.outputs.auto.Auto()
                speaker.output(text)
        except Exception as e:
            print(f"Error speaking: {e}")

    def change_mode(self, new_mode: ControllerMode):
        """Change controller mode with feedback"""
        if new_mode == self.current_mode:
            return

        old_mode = self.current_mode
        self.current_mode = new_mode

        # Play mode change sound
        play_sound('joystick/change_mode.ogg')

        # Vibration feedback
        vibration_controller.vibrate(duration=0.3, intensity=0.8, vibration_type="mode_change")

        # Announce mode change
        mode_names = {
            ControllerMode.SYSTEM: _("System mode"),
            ControllerMode.CONTROLLER: _("Controller mode"),
            ControllerMode.SCREENREADER: _("Screen reader mode"),
            ControllerMode.KEYBOARD: _("Screen keyboard mode")
        }

        message = mode_names.get(new_mode, _("Unknown mode"))
        self.speak(message, position=0.0, interrupt=True)

        # Save settings
        self._save_settings()

        print(f"Controller mode changed: {old_mode.value} -> {new_mode.value}")

    def cycle_mode(self):
        """Cycle to next mode (right trigger)"""
        modes = list(ControllerMode)
        current_index = modes.index(self.current_mode)
        next_index = (current_index + 1) % len(modes)
        self.change_mode(modes[next_index])

    def cycle_mode_backward(self):
        """Cycle to previous mode (left trigger)"""
        modes = list(ControllerMode)
        current_index = modes.index(self.current_mode)
        prev_index = (current_index - 1) % len(modes)
        self.change_mode(modes[prev_index])

    def handle_trigger_press(self, is_left: bool, pressed: bool):
        """
        Handle trigger (LT/RT) press/release for mode changing
        Hold trigger for 2 seconds to cycle modes
        """
        current_time = time.time()

        if is_left:
            if pressed:
                # Trigger is being held
                if self.left_trigger_pressed_time is None:
                    # Just started pressing
                    self.left_trigger_pressed_time = current_time
                    self.left_trigger_mode_changed = False
                    print(f"[MODE] Left trigger pressed, starting timer")
                elif not self.left_trigger_mode_changed:
                    # Check if held long enough
                    hold_duration = current_time - self.left_trigger_pressed_time
                    if hold_duration >= self.bumper_hold_time:
                        print(f"[MODE] Left trigger held for {hold_duration:.1f}s - previous mode!")
                        self.cycle_mode_backward()
                        self.left_trigger_mode_changed = True  # Prevent re-trigger
            else:
                # Trigger released
                if self.left_trigger_pressed_time is not None:
                    print(f"[MODE] Left trigger released")
                self.left_trigger_pressed_time = None
                self.left_trigger_mode_changed = False
        else:  # Right trigger
            if pressed:
                # Trigger is being held
                if self.right_trigger_pressed_time is None:
                    # Just started pressing
                    self.right_trigger_pressed_time = current_time
                    self.right_trigger_mode_changed = False
                    print(f"[MODE] Right trigger pressed, starting timer")
                elif not self.right_trigger_mode_changed:
                    # Check if held long enough
                    hold_duration = current_time - self.right_trigger_pressed_time
                    if hold_duration >= self.bumper_hold_time:
                        print(f"[MODE] Right trigger held for {hold_duration:.1f}s - next mode!")
                        self.cycle_mode()
                        self.right_trigger_mode_changed = True  # Prevent re-trigger
            else:
                # Trigger released
                if self.right_trigger_pressed_time is not None:
                    print(f"[MODE] Right trigger released")
                self.right_trigger_pressed_time = None
                self.right_trigger_mode_changed = False

    def handle_button_press(self, button_id: int, pressed: bool = True):
        """Handle button press/release based on current mode"""
        if self.current_mode == ControllerMode.SYSTEM:
            # System mode - do nothing, let controller work normally
            return False

        if not KEYBOARD_AVAILABLE:
            return False

        # Only handle button press events (not release)
        if not pressed:
            return False

        # Always release modifiers afterwards so none stay "stuck" (e.g. Insert
        # turning every later key into an NVDA command).
        try:
            if self.current_mode == ControllerMode.CONTROLLER:
                return self._handle_controller_mode_button(button_id)
            elif self.current_mode == ControllerMode.SCREENREADER:
                return self._handle_screenreader_mode_button(button_id)
            elif self.current_mode == ControllerMode.KEYBOARD:
                return self._handle_keyboard_mode_button(button_id)
            return False
        finally:
            _release_modifiers()

    def _handle_controller_mode_button(self, button_id: int) -> bool:
        """
        Handle button press in Controller mode
        Maps controller buttons to keyboard keys for Windows/system control
        """
        if not KEYBOARD_AVAILABLE:
            return False

        try:
            # Xbox controller mapping:
            # 0 = A (bottom action button) -> Enter
            # 1 = B (right action button) -> Escape
            # 2 = X (left action button) -> Alt+F4
            # 3 = Y (top action button) -> Backspace
            # 4 = LB (left bumper) - used for mode switching
            # 5 = RB (right bumper) - used for mode switching
            # 6 = Back/View button -> Alt
            # 7 = Start/Menu button -> Windows key
            # 8 = Left stick press
            # 9 = Right stick press
            # 10 = Xbox Guide button -> Alt+Tab

            if button_id == 0:  # A button -> Enter
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                _press('enter')
                time.sleep(0.05)
                _release('enter')
                play_sound('joystick/ui2.ogg')
                return True

            elif button_id == 1:  # B button -> Escape
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                _press('escape')
                time.sleep(0.05)
                _release('escape')
                play_sound('joystick/ui2.ogg')
                return True

            elif button_id == 3:  # Y button -> Backspace
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                _press('backspace')
                time.sleep(0.05)
                _release('backspace')
                play_sound('joystick/ui2.ogg')
                return True

            elif button_id == 2:  # X button -> Alt+F4
                vibration_controller.vibrate(duration=0.1, intensity=0.8)
                _press('alt')
                time.sleep(0.01)
                _press('f4')
                time.sleep(0.05)
                _release('f4')
                time.sleep(0.01)
                _release('alt')
                play_sound('joystick/ui2.ogg')
                return True

            elif button_id == 7:  # Start/Menu button -> Windows key
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                _press('win')
                time.sleep(0.05)
                _release('win')
                play_sound('joystick/ui2.ogg')
                return True

            elif button_id == 6:  # Back/View button -> Alt
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                _press('alt')
                time.sleep(0.05)
                _release('alt')
                play_sound('joystick/ui2.ogg')
                return True

            elif button_id == 10:  # Xbox Guide button -> Alt+Tab
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                _press('alt')
                time.sleep(0.01)
                _press('tab')
                time.sleep(0.05)
                _release('tab')
                time.sleep(0.01)
                _release('alt')
                play_sound('joystick/ui2.ogg')
                return True

        except Exception as e:
            print(f"Error in controller mode button handling: {e}")

        return False

    def _handle_screenreader_mode_button(self, button_id: int) -> bool:
        """
        Handle button press in Screen Reader mode
        Maps controller buttons to NVDA/JAWS shortcuts
        """
        if not KEYBOARD_AVAILABLE:
            return False

        try:
            if button_id == 7:  # Menu button -> NVDA+N or JAWS+J
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                _press('insert')
                time.sleep(0.01)
                _press('n')
                time.sleep(0.05)
                _release('n')
                time.sleep(0.01)
                _release('insert')
                play_sound('joystick/ui2.ogg')
                return True

            elif button_id == 0:  # Bottom button -> Check time (Insert+F12)
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                _press('insert')
                time.sleep(0.01)
                _press('f12')
                time.sleep(0.05)
                _release('f12')
                time.sleep(0.01)
                _release('insert')
                play_sound('joystick/ui2.ogg')
                return True

            elif button_id == 1:  # Right button -> Check battery (Insert+Shift+B)
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                _press('insert')
                time.sleep(0.01)
                _press('shift')
                time.sleep(0.01)
                _press('b')
                time.sleep(0.05)
                _release('b')
                time.sleep(0.01)
                _release('shift')
                time.sleep(0.01)
                _release('insert')
                play_sound('joystick/ui2.ogg')
                return True

            elif button_id == 3:  # Top button -> Exit screen reader
                vibration_controller.vibrate(duration=0.1, intensity=0.8)
                _press('insert')
                time.sleep(0.01)
                _press('q')
                time.sleep(0.05)
                _release('q')
                time.sleep(0.01)
                _release('insert')
                play_sound('joystick/ui2.ogg')
                self.speak(_("Exiting screen reader"))
                return True

            elif button_id == 2:  # Left button -> Insert+Ctrl+S
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                _press('insert')
                time.sleep(0.01)
                _press('ctrl')
                time.sleep(0.01)
                _press('s')
                time.sleep(0.05)
                _release('s')
                time.sleep(0.01)
                _release('ctrl')
                time.sleep(0.01)
                _release('insert')
                play_sound('joystick/ui2.ogg')
                return True

        except Exception as e:
            print(f"Error in screen reader mode button handling: {e}")

        return False

    def _handle_keyboard_mode_button(self, button_id: int) -> bool:
        """
        Handle button press in Screen Keyboard mode
        Virtual keyboard navigation and typing
        """
        try:
            if button_id == 0:  # Bottom button -> Type character
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                if self.virtual_keyboard.type_current_key():
                    play_sound('joystick/ui2.ogg')
                    # Announce what was typed
                    key_desc = self.virtual_keyboard.get_key_description()
                    self.speak(_("Typed {}").format(key_desc))
                return True

            elif button_id == 1:  # Right button -> Backspace
                vibration_controller.vibrate(duration=0.05, intensity=0.6)
                if self.virtual_keyboard.backspace():
                    play_sound('joystick/ui2.ogg')
                    self.speak(_("Backspace"))
                return True

        except Exception as e:
            print(f"Error in keyboard mode button handling: {e}")

        return False

    def handle_axis_movement(self, axis_id: int, value: float, controller_id: int = 0):
        """Handle analog stick movement based on current mode"""
        if not KEYBOARD_AVAILABLE:
            return False

        # Apply deadzone
        if abs(value) < self.axis_deadzone:
            value = 0.0

        # Track axis state
        axis_key = f"{controller_id}_{axis_id}"
        previous_value = self.last_axis_values.get(axis_key, 0.0)

        # Always update the last value first
        self.last_axis_values[axis_key] = value

        # Only trigger on crossing deadzone threshold
        if abs(previous_value) < self.axis_deadzone and abs(value) >= self.axis_deadzone:
            # Check debouncing
            current_time = time.time()
            last_action_time = self.last_axis_action_time.get(axis_key, 0.0)

            if current_time - last_action_time < self.axis_repeat_delay:
                return False

            self.last_axis_action_time[axis_key] = current_time

            # Handle based on mode. Release modifiers afterwards (Controller-mode
            # stick navigation uses Shift/Ctrl) so none stay stuck.
            if self.current_mode == ControllerMode.SYSTEM:
                return False  # Let system handle it
            try:
                if self.current_mode == ControllerMode.CONTROLLER:
                    return self._handle_controller_mode_axis(axis_id, value)
                elif self.current_mode == ControllerMode.SCREENREADER:
                    return self._handle_screenreader_mode_axis(axis_id, value)
                elif self.current_mode == ControllerMode.KEYBOARD:
                    return self._handle_keyboard_mode_axis(axis_id, value)
            finally:
                _release_modifiers()

        return False

    def _handle_controller_mode_axis(self, axis_id: int, value: float) -> bool:
        """
        Handle axis movement in Controller mode
        Left stick -> Arrow keys
        Right stick -> Tab/Shift+Tab, Ctrl+Tab/Ctrl+Shift+Tab
        """
        if not KEYBOARD_AVAILABLE:
            return False

        try:
            # Left stick (axis 0 = X, axis 1 = Y)
            if axis_id == 0:  # Left stick X
                vibration_controller.vibrate(duration=0.03, intensity=0.4)
                key = 'left' if value < 0 else 'right'
                _press(key)
                time.sleep(0.05)
                _release(key)
                play_sound('joystick/ui2.ogg')
                return True

            elif axis_id == 1:  # Left stick Y
                vibration_controller.vibrate(duration=0.03, intensity=0.4)
                key = 'up' if value < 0 else 'down'
                _press(key)
                time.sleep(0.05)
                _release(key)
                play_sound('joystick/ui2.ogg')
                return True

            # Right stick (axis 2 = X, axis 3 = Y)
            elif axis_id == 3:  # Right stick Y
                vibration_controller.vibrate(duration=0.03, intensity=0.4)
                if value < 0:
                    _press('shift')
                    time.sleep(0.01)
                    _press('tab')
                    time.sleep(0.05)
                    _release('tab')
                    time.sleep(0.01)
                    _release('shift')
                else:
                    _press('tab')
                    time.sleep(0.05)
                    _release('tab')
                play_sound('joystick/ui2.ogg')
                return True

            elif axis_id == 2:  # Right stick X
                vibration_controller.vibrate(duration=0.03, intensity=0.4)
                if value < 0:
                    _press('ctrl')
                    time.sleep(0.01)
                    _press('shift')
                    time.sleep(0.01)
                    _press('tab')
                    time.sleep(0.05)
                    _release('tab')
                    time.sleep(0.01)
                    _release('shift')
                    time.sleep(0.01)
                    _release('ctrl')
                else:
                    _press('ctrl')
                    time.sleep(0.01)
                    _press('tab')
                    time.sleep(0.05)
                    _release('tab')
                    time.sleep(0.01)
                    _release('ctrl')
                play_sound('joystick/ui2.ogg')
                return True

        except Exception as e:
            print(f"Error in controller mode axis handling: {e}")

        return False

    def _handle_screenreader_mode_axis(self, axis_id: int, value: float) -> bool:
        """
        Handle axis movement in Screen Reader mode
        Left stick or arrows -> Numpad 2, 8, 4, 6 for NVDA cursor
        """
        if not KEYBOARD_AVAILABLE:
            return False

        try:
            # Left stick (axis 0 = X, axis 1 = Y)
            if axis_id == 0:  # Left stick X
                vibration_controller.vibrate(duration=0.03, intensity=0.4)
                _tap_numpad('4' if value < 0 else '6')
                play_sound('joystick/ui2.ogg')
                return True

            elif axis_id == 1:  # Left stick Y
                vibration_controller.vibrate(duration=0.03, intensity=0.4)
                _tap_numpad('8' if value < 0 else '2')
                play_sound('joystick/ui2.ogg')
                return True

        except Exception as e:
            print(f"Error in screen reader mode axis handling: {e}")

        return False

    def _handle_keyboard_mode_axis(self, axis_id: int, value: float) -> bool:
        """
        Handle axis movement in Screen Keyboard mode
        Left stick -> Navigate keyboard layout
        Right stick -> Arrow keys (for moving cursor in text)
        """
        if not KEYBOARD_AVAILABLE:
            return False

        try:
            # Left stick - navigate keyboard
            if axis_id == 0:  # Left stick X
                vibration_controller.vibrate(duration=0.03, intensity=0.4)
                if value < 0:
                    if self.virtual_keyboard.move_left():
                        play_sound('joystick/ui1.ogg')
                        key_desc = self.virtual_keyboard.get_key_description()
                        # Calculate stereo position based on column
                        position = (self.virtual_keyboard.col / max(len(self.virtual_keyboard.LAYOUT[self.virtual_keyboard.row]) - 1, 1)) * 2.0 - 1.0
                        self.speak(key_desc, position=position)
                else:
                    if self.virtual_keyboard.move_right():
                        play_sound('joystick/ui1.ogg')
                        key_desc = self.virtual_keyboard.get_key_description()
                        # Calculate stereo position
                        position = (self.virtual_keyboard.col / max(len(self.virtual_keyboard.LAYOUT[self.virtual_keyboard.row]) - 1, 1)) * 2.0 - 1.0
                        self.speak(key_desc, position=position)
                return True

            elif axis_id == 1:  # Left stick Y
                vibration_controller.vibrate(duration=0.03, intensity=0.4)
                if value < 0:
                    if self.virtual_keyboard.move_up():
                        play_sound('joystick/ui1.ogg')
                        key_desc = self.virtual_keyboard.get_key_description()
                        position = (self.virtual_keyboard.col / max(len(self.virtual_keyboard.LAYOUT[self.virtual_keyboard.row]) - 1, 1)) * 2.0 - 1.0
                        self.speak(key_desc, position=position)
                else:
                    if self.virtual_keyboard.move_down():
                        play_sound('joystick/ui1.ogg')
                        key_desc = self.virtual_keyboard.get_key_description()
                        position = (self.virtual_keyboard.col / max(len(self.virtual_keyboard.LAYOUT[self.virtual_keyboard.row]) - 1, 1)) * 2.0 - 1.0
                        self.speak(key_desc, position=position)
                return True

            # Right stick - cursor movement
            elif axis_id == 2:  # Right stick X
                vibration_controller.vibrate(duration=0.03, intensity=0.4)
                key = 'left' if value < 0 else 'right'
                _press(key)
                time.sleep(0.05)
                _release(key)
                play_sound('joystick/ui1.ogg')
                return True

            elif axis_id == 3:  # Right stick Y
                vibration_controller.vibrate(duration=0.03, intensity=0.4)
                key = 'up' if value < 0 else 'down'
                _press(key)
                time.sleep(0.05)
                _release(key)
                play_sound('joystick/ui1.ogg')
                return True

        except Exception as e:
            print(f"Error in keyboard mode axis handling: {e}")

        return False

    def handle_hat_movement(self, hat_id: int, value: tuple):
        """Handle D-pad movement based on current mode"""
        if not KEYBOARD_AVAILABLE:
            return False

        if value == (0, 0):
            return False

        x, y = value

        # In keyboard mode, use D-pad same as left stick
        if self.current_mode == ControllerMode.KEYBOARD:
            if x == -1:
                return self._handle_keyboard_mode_axis(0, -1.0)
            elif x == 1:
                return self._handle_keyboard_mode_axis(0, 1.0)

            if y == 1:
                return self._handle_keyboard_mode_axis(1, -1.0)
            elif y == -1:
                return self._handle_keyboard_mode_axis(1, 1.0)

        # In screen reader mode, use D-pad for numpad (same as left stick)
        elif self.current_mode == ControllerMode.SCREENREADER:
            if not KEYBOARD_AVAILABLE:
                return False

            try:
                vibration_controller.vibrate(duration=0.03, intensity=0.4)

                # D-pad X axis -> numpad 4 (left) or 6 (right)
                if x == -1:
                    _tap_numpad('4')
                elif x == 1:
                    _tap_numpad('6')

                # D-pad Y axis -> numpad 8 (up) or 2 (down)
                if y == 1:
                    _tap_numpad('8')
                elif y == -1:
                    _tap_numpad('2')

                play_sound('joystick/ui2.ogg')
                return True
            except Exception as e:
                print(f"Error in D-pad screen reader handling: {e}")

        # For controller mode, use D-pad as arrow keys
        elif self.current_mode == ControllerMode.CONTROLLER:
            if not KEYBOARD_AVAILABLE:
                return False

            try:
                vibration_controller.vibrate(duration=0.03, intensity=0.4)
                if x == -1:
                    _press('left')
                    time.sleep(0.05)
                    _release('left')
                elif x == 1:
                    _press('right')
                    time.sleep(0.05)
                    _release('right')

                if y == 1:
                    _press('up')
                    time.sleep(0.05)
                    _release('up')
                elif y == -1:
                    _press('down')
                    time.sleep(0.05)
                    _release('down')

                play_sound('joystick/ui2.ogg')
                return True
            except Exception as e:
                print(f"Error in D-pad handling: {e}")

        return False


# Global mode manager instance
_mode_manager: Optional[ControllerModeManager] = None


def get_mode_manager() -> ControllerModeManager:
    """Get or create global mode manager instance"""
    global _mode_manager
    if _mode_manager is None:
        _mode_manager = ControllerModeManager()
    return _mode_manager


def initialize_controller_modes():
    """Initialize controller mode system"""
    global _mode_manager
    try:
        _mode_manager = ControllerModeManager()
        print("Controller mode system initialized")
        return True
    except Exception as e:
        print(f"Failed to initialize controller mode system: {e}")
        return False


def shutdown_controller_modes():
    """Shutdown controller mode system"""
    global _mode_manager
    _mode_manager = None
    print("Controller mode system shutdown")

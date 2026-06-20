"""
Simple controller vibration system for TCE Launcher
Focuses on reliability over complex features
"""

import os
import threading
import time
from typing import List, Optional, Dict, Any
from src.titan_core.translation import _
from src.platform_utils import IS_WINDOWS

# Set SDL2 environment variables for Xbox controller support
os.environ['SDL_JOYSTICK_HIDAPI_XBOX'] = '1'
os.environ['SDL_JOYSTICK_HIDAPI_XBOX_ONE'] = '1'
os.environ['SDL_JOYSTICK_HIDAPI'] = '1'

# Try to import XInput for Windows
XINPUT_AVAILABLE = False
xinput = None
XINPUT_VIBRATION = None

if IS_WINDOWS:
    try:
        import ctypes
        from ctypes import wintypes, Structure

        class XINPUT_VIBRATION(Structure):
            _fields_ = [("wLeftMotorSpeed", wintypes.WORD),
                       ("wRightMotorSpeed", wintypes.WORD)]

        try:
            xinput = ctypes.windll.xinput1_4
        except:
            try:
                xinput = ctypes.windll.xinput1_3
            except:
                xinput = None

        if xinput:
            xinput.XInputSetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_VIBRATION)]
            xinput.XInputSetState.restype = wintypes.DWORD
            XINPUT_AVAILABLE = True
            print("XInput support enabled")
        else:
            print("XInput not available")
    except Exception as e:
        print(f"Failed to initialize XInput: {e}")
else:
    print(f"XInput not available on this platform")

class SimpleControllerVibration:
    def __init__(self):
        self.vibration_enabled = True
        self.vibration_strength = 0.8
        # 'sync'  -> haptics follow the audio envelope (default, iPhone-style)
        # 'discrete' -> fixed pulses for individual UI events (legacy behaviour)
        # 'off'   -> no haptics at all
        self.haptic_mode = 'sync'
        # Experimental: drive the rumble motors from the TTS speech envelope so a
        # deaf / hard-of-hearing user can FEEL what is being spoken. Works
        # independently of haptic_mode (the user may keep general audio-haptics
        # off but still want speech to be felt). Default off.
        self.speech_haptic_sync = False
        self.last_vibration_time = {}
        self.min_vibration_interval = 0.05
        self.vibration_lock = threading.Lock()
        self._load_settings()

    def _load_settings(self):
        """Load persisted vibration settings from the 'controller' section."""
        try:
            from src.settings.settings import get_setting
            enabled = str(get_setting('vibration_enabled', 'True', 'controller')).lower()
            self.vibration_enabled = enabled in ('true', '1')
            try:
                self.vibration_strength = max(0.0, min(1.0, float(
                    get_setting('vibration_strength', '0.8', 'controller'))))
            except (TypeError, ValueError):
                self.vibration_strength = 0.8
            mode = str(get_setting('haptic_mode', 'sync', 'controller')).lower()
            self.haptic_mode = mode if mode in ('sync', 'discrete', 'off') else 'sync'
            sync_speech = str(get_setting('speech_haptic_sync', 'False', 'controller')).lower()
            self.speech_haptic_sync = sync_speech in ('true', '1')
        except Exception as e:
            print(f"[VIBRATION] Could not load settings, using defaults: {e}")

    def vibrate(self, duration: float = 0.1, intensity: float = None, vibration_type: str = "generic", force: bool = False):
        """Discrete pulse. Used only in 'discrete' haptic mode; in 'sync' mode the
        audio-synced engine drives the motors instead, so this is normally a no-op.
        Pass force=True to pulse regardless of mode (used by the Test button)."""
        if not self.vibration_enabled:
            return
        if not force and self.haptic_mode != 'discrete':
            return

        # Rate limiting check
        current_time = time.time()
        if vibration_type in self.last_vibration_time:
            time_since_last = current_time - self.last_vibration_time[vibration_type]
            if time_since_last < self.min_vibration_interval:
                return

        self.last_vibration_time[vibration_type] = current_time

        if intensity is None:
            intensity = self.vibration_strength

        intensity = max(0.0, min(1.0, intensity))

        def vibrate_thread():
            # Try XInput first (most reliable for Xbox controllers)
            if XINPUT_AVAILABLE and IS_WINDOWS:
                try:
                    left_motor = int(intensity * 65535)
                    right_motor = int(intensity * 65535)

                    for controller_id in range(4):
                        vibration = XINPUT_VIBRATION()
                        vibration.wLeftMotorSpeed = left_motor
                        vibration.wRightMotorSpeed = right_motor

                        result = xinput.XInputSetState(controller_id, ctypes.byref(vibration))
                        if result == 0:  # SUCCESS
                            def stop_vibration():
                                time.sleep(duration)
                                try:
                                    stop_vib = XINPUT_VIBRATION()
                                    stop_vib.wLeftMotorSpeed = 0
                                    stop_vib.wRightMotorSpeed = 0
                                    xinput.XInputSetState(controller_id, ctypes.byref(stop_vib))
                                except:
                                    pass
                            threading.Thread(target=stop_vibration, daemon=True).start()
                            return  # Success, exit
                except Exception as e:
                    pass  # Continue to pygame fallback

            # Pygame SDL2 rumble fallback (macOS/Linux, or if XInput failed)
            try:
                import pygame
                if pygame.joystick.get_init():
                    for i in range(pygame.joystick.get_count()):
                        try:
                            js = pygame.joystick.Joystick(i)
                            if not js.get_init():
                                js.init()
                            js.rumble(intensity, intensity, int(duration * 1000))
                            return
                        except Exception:
                            continue
            except Exception:
                pass

        # Run in background thread
        threading.Thread(target=vibrate_thread, daemon=True).start()

    def vibrate_cursor_move(self):
        """Light vibration for cursor movement"""
        self.vibrate(duration=0.05, intensity=0.3, vibration_type="cursor")

    def vibrate_menu_open(self):
        """Medium vibration for menu opening"""
        self.vibrate(duration=0.15, intensity=0.6, vibration_type="menu_open")

    def vibrate_menu_close(self):
        """Light vibration for menu closing"""
        self.vibrate(duration=0.1, intensity=0.4, vibration_type="menu_close")

    def vibrate_selection(self):
        """Medium vibration for item selection"""
        self.vibrate(duration=0.12, intensity=0.7, vibration_type="selection")

    def vibrate_error(self):
        """Strong vibration for errors"""
        self.vibrate(duration=0.2, intensity=1.0, vibration_type="error")

    def vibrate_startup(self):
        """Strong 3-second vibration for startup"""
        self.vibrate(duration=3.0, intensity=1.0, vibration_type="startup")

    def vibrate_notification(self):
        """Medium vibration for notifications"""
        self.vibrate(duration=0.4, intensity=0.8, vibration_type="notification")

    def vibrate_focus_change(self):
        """Very light vibration for focus changes"""
        self.vibrate(duration=0.03, intensity=0.2, vibration_type="focus")

    def _save_setting(self, key, value):
        try:
            from src.settings.settings import set_setting
            set_setting(key, str(value), 'controller')
        except Exception as e:
            print(f"[VIBRATION] Could not save setting {key}: {e}")

    def set_vibration_enabled(self, enabled: bool):
        """Enable or disable vibrations (persisted)"""
        self.vibration_enabled = enabled
        if not enabled:
            self.cleanup()  # zero motors immediately
        self._save_setting('vibration_enabled', enabled)

    def set_vibration_strength(self, strength: float):
        """Set vibration strength 0.0-1.0 (persisted)"""
        self.vibration_strength = max(0.0, min(1.0, strength))
        self._save_setting('vibration_strength', self.vibration_strength)

    def set_haptic_mode(self, mode: str):
        """Set haptic mode: 'sync', 'discrete' or 'off' (persisted)"""
        if mode not in ('sync', 'discrete', 'off'):
            mode = 'sync'
        self.haptic_mode = mode
        if mode != 'sync':
            try:
                from src.controller import haptic_sync
                haptic_sync.stop()
            except Exception:
                pass
        self._save_setting('haptic_mode', mode)

    def set_speech_haptic_sync(self, enabled: bool):
        """Enable/disable feeling TTS speech as rumble (experimental, persisted).

        When disabled, stop any speech-driven haptics immediately so the motors
        do not keep buzzing from an in-flight utterance.
        """
        self.speech_haptic_sync = bool(enabled)
        if not enabled:
            try:
                from src.controller import haptic_sync
                haptic_sync.stop()
            except Exception:
                pass
        self._save_setting('speech_haptic_sync', bool(enabled))

    def is_vibration_available(self) -> bool:
        """Check if vibration is available"""
        return XINPUT_AVAILABLE

    def get_controller_info(self):
        """Get controller information"""
        return {
            'count': 1 if XINPUT_AVAILABLE else 0,
            'names': ['XInput Controller'] if XINPUT_AVAILABLE else [],
            'vibration_available': XINPUT_AVAILABLE,
            'vibration_enabled': self.vibration_enabled,
            'strength': self.vibration_strength,
            'haptic_mode': self.haptic_mode,
            'speech_haptic_sync': self.speech_haptic_sync
        }

    def refresh_controllers(self):
        """Refresh controller detection"""
        try:
            import pygame
            pygame.joystick.quit()
            pygame.joystick.init()
            print("[VIBRATION] Controllers refreshed")
        except Exception as e:
            print(f"Error refreshing controllers: {e}")

    def cleanup(self):
        """Clean up controller resources"""
        if XINPUT_AVAILABLE and IS_WINDOWS:
            try:
                for controller_id in range(4):
                    stop_vib = XINPUT_VIBRATION()
                    stop_vib.wLeftMotorSpeed = 0
                    stop_vib.wRightMotorSpeed = 0
                    xinput.XInputSetState(controller_id, ctypes.byref(stop_vib))
            except:
                pass

# Global instance
vibration_controller = SimpleControllerVibration()

# Convenience functions
def initialize_vibration():
    """Initialize vibration system"""
    pass  # Already initialized

def vibrate_cursor_move():
    vibration_controller.vibrate_cursor_move()

def vibrate_menu_open():
    vibration_controller.vibrate_menu_open()

def vibrate_menu_close():
    vibration_controller.vibrate_menu_close()

def vibrate_selection():
    vibration_controller.vibrate_selection()

def vibrate_error():
    vibration_controller.vibrate_error()

def vibrate_startup():
    vibration_controller.vibrate_startup()

def vibrate_notification():
    vibration_controller.vibrate_notification()

def vibrate_focus_change():
    vibration_controller.vibrate_focus_change()

def set_vibration_enabled(enabled: bool):
    vibration_controller.set_vibration_enabled(enabled)

def set_vibration_strength(strength: float):
    vibration_controller.set_vibration_strength(strength)

def set_haptic_mode(mode: str):
    vibration_controller.set_haptic_mode(mode)

def set_speech_haptic_sync(enabled: bool):
    vibration_controller.set_speech_haptic_sync(enabled)

def get_controller_info():
    return vibration_controller.get_controller_info()

def cleanup_vibration():
    vibration_controller.cleanup()

def refresh_controllers():
    vibration_controller.refresh_controllers()

def test_vibration():
    """Fire a single test pulse at the current strength, regardless of haptic mode."""
    vibration_controller.vibrate(duration=0.6, intensity=1.0, vibration_type="test", force=True)

if __name__ == "__main__":
    test_vibration()
    cleanup_vibration()
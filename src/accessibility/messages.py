"""
Accessibility messages system for TCE Launcher.

This module provides a system for displaying timed messages to users
using either stereo speech or accessible_output3 as fallback.
"""

import threading
import time
import accessible_output3.outputs.auto
from src.titan_core.sound import play_sound
from src.titan_core.stereo_speech import speak_stereo
from src.settings.settings import get_setting


class AccessibilityMessenger:
    """
    System for displaying accessibility messages with audio notifications.

    Features:
    - Plays notification sounds before and after messages
    - Uses stereo speech or accessible_output3 for TTS
    - Thread-safe message delivery
    """

    def __init__(self):
        self.speaker = accessible_output3.outputs.auto.Auto()
        self._active_threads = []

    def speak_message(self, text, position=0.0, pitch_offset=0):
        """
        Speak a message respecting TCE TTS settings.

        Args:
            text (str): Message text to speak
            position (float): Stereo position from -1.0 (left) to 1.0 (right) (Titan TTS only)
            pitch_offset (int): Pitch offset from -10 to +10 (Titan TTS only)
        """
        try:
            # Check if Titan TTS is enabled in settings
            use_titan_tts = False
            try:
                invisible_settings = get_setting('invisible_interface', {})
                use_titan_tts = str(invisible_settings.get('stereo_speech', 'False')).lower() in ['true', '1']
            except Exception as e:
                print(f"[AccessibilityMessenger] Error reading TTS settings: {e}")

            if use_titan_tts:
                # Use Titan TTS (stereo speech)
                try:
                    speak_stereo(text, position=position, pitch_offset=pitch_offset, async_mode=False)
                    return
                except Exception as e:
                    print(f"[AccessibilityMessenger] Titan TTS error: {e}, falling back to AO3")

            # Use accessible_output3 (either by choice or as fallback)
            try:
                self.speaker.speak(text, interrupt=True)
            except Exception as e:
                print(f"[AccessibilityMessenger] AO3 speech error: {e}")

        except Exception as e:
            print(f"[AccessibilityMessenger] Error speaking message: {e}")

    def show_timed_message(self, text, delay=0, position=0.0, pitch_offset=0,
                          pre_sound=None, post_sound=None):
        """
        Show a message after a delay with optional sounds.

        Args:
            text (str): Message text to speak
            delay (float): Delay in seconds before showing the message
            position (float): Stereo position from -1.0 (left) to 1.0 (right)
            pitch_offset (int): Pitch offset from -10 to +10
            pre_sound (str): Sound file to play before message (relative to sfx theme)
            post_sound (str): Sound file to play after message (relative to sfx theme)
        """
        def _show_message():
            try:
                # Wait for delay
                if delay > 0:
                    time.sleep(delay)

                # Play pre-sound if specified
                if pre_sound:
                    try:
                        play_sound(pre_sound)
                        # Small delay after sound
                        time.sleep(0.1)
                    except Exception as e:
                        print(f"[AccessibilityMessenger] Error playing pre-sound: {e}")

                # Speak the message
                self.speak_message(text, position=position, pitch_offset=pitch_offset)

                # Wait for message to finish (approximate timing)
                # Estimate: ~150ms per word on average
                words = len(text.split())
                speech_duration = words * 0.15
                time.sleep(speech_duration)

                # Play post-sound if specified
                if post_sound:
                    try:
                        play_sound(post_sound)
                    except Exception as e:
                        print(f"[AccessibilityMessenger] Error playing post-sound: {e}")

            except Exception as e:
                print(f"[AccessibilityMessenger] Error in timed message: {e}")
            finally:
                # Remove this thread from active threads
                if threading.current_thread() in self._active_threads:
                    self._active_threads.remove(threading.current_thread())

        # Create and start thread
        thread = threading.Thread(target=_show_message, daemon=True)
        self._active_threads.append(thread)
        thread.start()

        return thread


# Global instance
_messenger_instance = None


def get_messenger():
    """Get the global AccessibilityMessenger instance."""
    global _messenger_instance
    if _messenger_instance is None:
        _messenger_instance = AccessibilityMessenger()
    return _messenger_instance


def show_invisible_ui_tip(delay=5.0):
    """
    Show tip about using invisible UI after minimization.

    Args:
        delay (float): Delay in seconds before showing the tip (default: 5.0)
    """
    messenger = get_messenger()
    message = "To use invisible interface, press tilde key"

    messenger.show_timed_message(
        text=message,
        delay=delay,
        position=0.0,
        pitch_offset=0,
        pre_sound='ui/msg.ogg',
        post_sound=None
    )

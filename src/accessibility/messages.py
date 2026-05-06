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
from src.titan_core.translation import set_language

# Get the translation function
_ = set_language(get_setting('language', 'pl'))


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
    message = _("To use invisible interface, press tilde key")

    messenger.show_timed_message(
        text=message,
        delay=delay,
        position=0.0,
        pitch_offset=0,
        pre_sound='ui/msg.ogg',
        post_sound=None
    )


def show_disable_titan_ui_tip(delay=0.6):
    """Tip played when entering a regular window from invisible UI.

    The Titan UI key bindings can swallow keystrokes the new window expects
    (arrows, tab, enter), so screen-reader users need the option to turn
    it off for the duration of that window. The brief delay lets the
    window's own focus announcement land first.

    Args:
        delay (float): Delay in seconds before speaking the tip.
    """
    messenger = get_messenger()
    message = _("Please disable Titan UI")

    messenger.show_timed_message(
        text=message,
        delay=delay,
        position=0.0,
        pitch_offset=0,
        pre_sound='ui/msg.ogg',
        post_sound=None,
    )


# --- Tab bar tip ---------------------------------------------------------
# The tab bar tip is shown only while focus stays on the virtual tab bar,
# and only when a real screen reader (not the platform TTS fallback) is
# active. Focus leaving the tab bar cancels the pending tip.

_tab_bar_tip_cancel = None


def show_tab_bar_tip(delay=4.0):
    """
    Show tip about switching between lists from the virtual tab bar.

    The tip plays after ``delay`` seconds unless ``cancel_tab_bar_tip()`` is
    called first (e.g. focus leaves the tab bar). Callers are expected to
    check that a screen reader is running before scheduling the tip.

    Args:
        delay (float): Delay in seconds before showing the tip (default: 4.0)
    """
    global _tab_bar_tip_cancel

    # Cancel any previously pending tip first
    cancel_tab_bar_tip()

    cancel_event = threading.Event()

    def _worker():
        # Wait for the delay OR a cancel request, whichever comes first
        if cancel_event.wait(timeout=delay):
            return
        messenger = get_messenger()
        messenger.speak_message(
            _("To switch between lists, use left or right arrow keys"),
            position=0.0,
            pitch_offset=0,
        )

    _tab_bar_tip_cancel = cancel_event
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return cancel_event


def cancel_tab_bar_tip():
    """Cancel any pending tab bar tip (focus left the tab bar)."""
    global _tab_bar_tip_cancel
    if _tab_bar_tip_cancel is not None:
        try:
            _tab_bar_tip_cancel.set()
        except Exception:
            pass
        _tab_bar_tip_cancel = None


# --- Screen-reader-only announcements -----------------------------------
# These helpers keep accessibility strings (tab bar, checked/unchecked
# hints, other screen-reader-only affordances) inside the `accessibility`
# translation domain. Callers should not inline _("Tab bar") themselves —
# that would make the string show up under gui/settings domains when the
# extractor runs.


def is_screen_reader_running():
    """Return True only when a real screen reader is active.

    Platform TTS fallbacks (SAPI, NSSpeech, spd) must NOT count — we use
    this to avoid those fallbacks reading accessibility-only hints aloud.
    """
    try:
        messenger = get_messenger()
        output = messenger.speaker.get_first_available_output()
        if output is None:
            return False
        if output.is_system_output():
            return False
        is_active = getattr(output, 'is_active', None)
        if callable(is_active):
            return bool(is_active())
        return True
    except Exception:
        return False


def speak_sr_only(text, interrupt=True):
    """Speak ``text`` via the active screen reader, or stay silent.

    Never falls back to SAPI/NSSpeech/spd — if no real SR is running this
    function does nothing, because these announcements are hints meant
    specifically for screen-reader users.
    """
    if not is_screen_reader_running():
        return
    try:
        get_messenger().speaker.speak(text, interrupt=interrupt)
    except Exception:
        pass


def announce_tab_bar():
    """Play the tab-bar focus sound and announce "Tab bar" to the SR.

    Sound is always played (sighted users still benefit from the earcon);
    the spoken "Tab bar" marker is emitted only when a real screen reader
    is active so the platform-TTS fallback never says it.
    """
    try:
        play_sound('ui/tapbar.ogg')
    except Exception:
        pass
    speak_sr_only(_("Tab bar"), interrupt=True)


_checklist_announce_timer = None
_checklist_announce_lock = threading.Lock()


def _speak_checklist_state_after(checked, delay_ms):
    """Speak "checked" / "unchecked" after ``delay_ms`` — SR only.

    The delay lets the SR finish its own focus/selection announcement
    first. Any pending earlier announcement is cancelled so rapid arrow-
    key nav or repeated toggles don't queue up stale speech.
    """
    global _checklist_announce_timer

    message = _("checked") if checked else _("unchecked")

    def _speak():
        speak_sr_only(message, interrupt=True)

    try:
        delay_seconds = max(0.0, delay_ms / 1000.0)
        with _checklist_announce_lock:
            pending = _checklist_announce_timer
            if pending is not None:
                try:
                    pending.cancel()
                except Exception:
                    pass
                _checklist_announce_timer = None

            if delay_seconds == 0:
                _speak()
            else:
                timer = threading.Timer(delay_seconds, _speak)
                timer.daemon = True
                _checklist_announce_timer = timer
                timer.start()
    except Exception:
        pass


def announce_checklist_item_toggle(checked, delay_ms=500):
    """Announce a check/uncheck toggle on a CheckListBox item.

    Uses the SAME earcons as a regular ``wx.CheckBox`` (``ui/X.ogg`` when
    the new state is checked, ``core/FOCUS.ogg`` when unchecked) so the
    user gets consistent auditory feedback across all checkbox widgets.
    The item name is NOT spoken — the SR already read it on focus — and
    the "checked" / "unchecked" state marker is spoken ``delay_ms`` ms
    later, only when a real screen reader is running.
    """
    try:
        play_sound('ui/X.ogg' if checked else 'core/FOCUS.ogg')
    except Exception:
        pass
    _speak_checklist_state_after(checked, delay_ms)


def announce_checklist_item_navigation(checked, delay_ms=500):
    """Announce the check state while arrowing across CheckListBox rows.

    Uses the dedicated list-item earcon ``ui/cb_listitem_checked.ogg`` —
    distinct from the toggle sound so the user can tell nav from actual
    state change — and speaks "checked" / "unchecked" ``delay_ms`` ms
    later (SR only). Intended for ``wx.EVT_LISTBOX`` handlers.
    """
    try:
        play_sound('ui/cb_listitem_checked.ogg')
    except Exception:
        pass
    _speak_checklist_state_after(checked, delay_ms)

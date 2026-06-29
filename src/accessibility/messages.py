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


def _format_titan_ui_key_label(key_string):
    """Convert internal key id (e.g. 'grave', 'shift+f2') into a human-readable label."""
    if not key_string:
        return _("Not set")
    parts = [p.strip() for p in key_string.split('+') if p.strip()]
    names = {
        'ctrl': _("Ctrl"),
        'shift': _("Shift"),
        'alt': _("Alt"),
        'win': _("Win"),
        'cmd': _("Cmd"),
        'grave': _("Accent"),
        'space': _("Space"),
        'tab': _("Tab"),
        'enter': _("Enter"),
        'escape': _("Escape"),
        'backspace': _("Backspace"),
        'delete': _("Delete"),
        'insert': _("Insert"),
        'home': _("Home"),
        'end': _("End"),
        'pageup': _("Page Up"),
        'pagedown': _("Page Down"),
        'up': _("Up"),
        'down': _("Down"),
        'left': _("Left"),
        'right': _("Right"),
    }
    display_parts = []
    for p in parts:
        if p in names:
            display_parts.append(names[p])
        elif p.startswith('f') and p[1:].isdigit():
            display_parts.append(p.upper())
        else:
            display_parts.append(p)
    return '+'.join(display_parts)


def show_invisible_ui_tip(delay=5.0):
    """
    Show tip about using invisible UI after minimization.

    Args:
        delay (float): Delay in seconds before showing the tip (default: 5.0)
    """
    messenger = get_messenger()
    try:
        key_string = (get_setting('titan_ui_key', 'grave', section='general') or 'grave').strip()
    except Exception:
        key_string = 'grave'
    keyname = _format_titan_ui_key_label(key_string)
    message = _("To use invisible interface, press {keyname} key").format(keyname=keyname)

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


# --- Titan Access (in-process screen reader) bridge ---------------------
# When the user's own Titan Access reader is running it is NOT detected by
# accessible_output3 (it is not a system AT like NVDA/JAWS), so the
# is_screen_reader_running() check below returns False and the SR-only hints
# would stay silent. These helpers route the hint straight to Titan Access,
# immediately and without the 500 ms AO3 work-around delay. Each returns True
# when Titan Access handled it, so callers can skip their fallback path.


def _ta_announce(text, interrupt=True, pitch=0):
    """Replace Titan Access's next focus announcement with ``text``.

    ``pitch`` shifts the tone (negative = a little lower, used for region names).
    """
    try:
        from titan_access.host_bridge import announce
        return announce(text, interrupt=interrupt, pitch=pitch)
    except Exception:
        return False


def _ta_announce_segments(segments, interrupt=True):
    """Replace Titan Access's next announcement with a mixed-tone phrase."""
    try:
        from titan_access.host_bridge import announce_segments
        return announce_segments(segments, interrupt=interrupt)
    except Exception:
        return False


def _ta_speak(text, interrupt=True):
    """Speak ``text`` immediately through Titan Access (no focus suppression)."""
    try:
        from titan_access.host_bridge import speak
        return speak(text, interrupt=interrupt)
    except Exception:
        return False


def _ta_state_suffix(text):
    """Append ``text`` to Titan Access's next focus announcement."""
    try:
        from titan_access.host_bridge import state_suffix
        return state_suffix(text)
    except Exception:
        return False


def is_titan_access_running():
    """True when the in-process Titan Access reader is active."""
    try:
        from titan_access.host_bridge import is_active
        return is_active()
    except Exception:
        return False


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
    # Prefer the in-process Titan Access reader (immediate, and it suppresses its
    # own duplicate read of the underlying list row); otherwise fall back to the
    # external-SR path.
    if not _ta_announce(_("Tab bar"), interrupt=True):
        speak_sr_only(_("Tab bar"), interrupt=True)


def announce_view_switched(view_name, idx, total):
    """Announce the view reached by cycling the tab bar (Left/Right arrows).

    Spoken as "<view>, <n> of <total>, <tab>" — e.g. "Applications, 1 of 4,
    tab". Routed to Titan Access so it replaces the reader's own read of the
    list row (which would otherwise say only the row text). When Titan Access
    is not the active reader this stays silent on purpose: the row text itself
    is read by whatever SR is running, so speaking here would duplicate it.

    ``idx`` is 0-based.
    """
    try:
        play_sound('ui/switch_list.ogg')
    except Exception:
        pass
    if total and total > 0:
        phrase = _("{}, {} of {}").format(view_name, idx + 1, total)
    else:
        phrase = view_name or _("Tab bar")
    # Append the control-type word ("tab" / pl "zakładka") at the end.
    phrase = "{}, {}".format(phrase, _("tab"))
    _ta_announce(phrase, interrupt=True)


# --- Drag-and-drop announcement ------------------------------------------
# Reading the region name a little lower and relabelling status-bar rows as
# "status bar item" is done by Titan Access itself (it recognises the container
# from the UIA tree), so there is no host-side helper for that here. The tab-bar
# card drag, however, is a host-only interaction with no UIA signal the reader
# could interpret, so the launcher pushes its announcement through this helper.

# A little higher than neutral -> the item being dragged.
DRAG_NAME_PITCH = 4


def announce_drag_move(name, position):
    """Announce a drag-and-drop move: the item name a little higher, then
    "at position N" at the neutral pitch -- replacing Titan Access's plain
    "selected, N of M". Returns True when Titan Access handled it; the caller
    should keep its own non-screen-reader feedback as a fallback."""
    segments = [
        (name, DRAG_NAME_PITCH),
        (_("at position {}").format(position), 0),
    ]
    return _ta_announce_segments(segments, interrupt=True)


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
    message = _("checked") if checked else _("unchecked")
    # Toggling fires no focus change, so speak the new state straight away
    # through Titan Access; only fall back to the delayed AO3 path otherwise.
    if not _ta_speak(message, interrupt=True):
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
    message = _("checked") if checked else _("unchecked")
    # Arrowing onto a row fires a focus change, so let Titan Access append the
    # state to the item name it is about to read; only fall back to the delayed
    # AO3 path when Titan Access is not the active reader.
    if not _ta_state_suffix(message):
        _speak_checklist_state_after(checked, delay_ms)


# --- Fn (function) key state ---------------------------------------------
# Laptop / notebook keyboards expose an Fn lock that changes whether the
# top row acts as F1-F12 or as hardware shortcuts. These helpers announce
# the new state with the same earcons used for opening/closing Titan UI.


def show_fn_keys_enabled():
    """Announce that the laptop Fn keys have been turned on."""
    messenger = get_messenger()
    messenger.show_timed_message(
        text=_("Fn keys enabled"),
        delay=0,
        position=0.0,
        pitch_offset=0,
        pre_sound='ui/tui_open.ogg',
        post_sound=None,
    )


def show_fn_keys_disabled():
    """Announce that the laptop Fn keys have been turned off."""
    messenger = get_messenger()
    messenger.show_timed_message(
        text=_("Fn keys disabled"),
        delay=0,
        position=0.0,
        pitch_offset=0,
        pre_sound='ui/tui_close.ogg',
        post_sound=None,
    )

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


# --- Whichever reader is listening ---------------------------------------
# The helpers above ask one question - "is Titan Access the reader?" - and
# answer it in the worst possible way when it is not: they stay silent, or
# they fall back to a flat string.  ``src.accessibility.reader_channel`` asks
# a better one: what can the reader that is listening actually TAKE?  A
# reader whose add-on has joined the Action Bus (the one in ``nvda-addon/``
# is the first) takes the position, the pitch, the role and the place in the
# list, and says so; everything else folds back into the sentence.


def _channel():
    """The reader Titan is talking to, or a channel that takes nothing."""
    try:
        from src.accessibility import reader_channel
        return reader_channel.channel()
    except Exception:
        class _Nothing:
            name = 'none'

            def can(self, _what):
                return False

            def say(self, _message):
                return False
        return _Nothing()


def _message(text, **detail):
    """One thing Titan means, before a channel decides how much survives.

    A caller builds one of these only when it wants to ask the channel
    something first - whether the role can travel as a field, say.  The
    ordinary case is :func:`_reader_announce`.
    """
    from src.accessibility import reader_channel
    return reader_channel.Message(text, **detail)


def _reader_announce(text, **detail):
    """Say one structured thing to whichever reader is listening."""
    try:
        from src.accessibility import reader_channel
        return reader_channel.announce(text, **detail)
    except Exception:
        return False


#: What Titan Access calls each kind, by its key in that component's own
#: catalogue. Asked of it rather than translated again here, so the word a
#: user hears for a question is the SAME word in both readers - two
#: vocabularies for one desktop is worse than one that is only in English.
_DIALOG_KIND_KEY = {
    'question': 'dialog.question',
    'information': 'dialog.information',
    'warning': 'dialog.warning',
    'error': 'dialog.error',
}


def _dialog_kind_label(kind):
    """The word for a dialog kind, in the user's own language.

    Titan Access's catalogue first, because that is the word its users
    already know. Titan's own translation is the floor, for a machine where
    that component is not installed.
    """
    key = _DIALOG_KIND_KEY.get(str(kind or '').strip().lower())
    if key:
        try:
            from titan_access.localization import L
            word = str(L(key) or '')
            if word and word != key:
                return word
        except Exception:
            pass
    return {'question': _("Question"), 'information': _("Information"),
            'warning': _("Warning"), 'error': _("Error")}.get(
                str(kind or '').strip().lower(), '')


def announce_dialog_kind(kind):
    """Say what kind of dialog is about to appear - to any reader.

    A skinned dialog's icon is not reliably detectable, so a confirmation
    and a notice read the same; Titan knows which it is putting up and says
    so. Titan Access has always been told (it plays the question earcon and
    says the word a little lower); every other reader was not, so the one
    dialog in Titan that asks the user to confirm something irreversible
    sounded exactly like one that does not.

    Returns True when a reader took it. Nothing is spoken by Titan itself:
    the reader is about to read the dialog, and this is a word put in front
    of that rather than a second announcement racing it.
    """
    try:
        from src.accessibility import reader_channel
        return bool(reader_channel.channel().dialog_kind(
            kind, label=_dialog_kind_label(kind)))
    except Exception:
        return False


def announce_state_suffix(text):
    """Add a state to whatever the reader reads next.

    For a state that is Titan's own and that the platform cannot report.
    Where the reader cannot take it, the caller's own delayed fallback is
    still the right answer - which is why this says whether it was taken.
    """
    try:
        from src.accessibility import reader_channel
        return bool(reader_channel.channel().state_suffix(text))
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
    # Whichever reader is listening.  Titan Access and a reader whose add-on
    # is on the bus both replace their own read of the underlying row with
    # this (``replaces_focus``), so the marker is said once rather than
    # racing the row; anything else simply hears the words.
    _reader_announce(_("Tab bar"), interrupt=True, replaces_focus=True)


def announce_view_switched(view_name, idx, total):
    """Announce the view reached by cycling the tab bar (Left/Right arrows).

    Spoken as "<view>, <n> of <total>, <tab>" — e.g. "Applications, 1 of 4,
    tab". The row text alone is what a reader would say by itself, and the
    three things this adds — which tab, where in the bar, that it IS a tab —
    are exactly what is lost. So it is said only to a reader that can put it
    IN PLACE of its own report of the row (``replaces_focus``): Titan
    Access, or a reader whose add-on is on the bus. A reader reached through
    ``accessible_output3`` alone cannot be told to suppress anything, so it
    stays silent there, as it always has — the alternative is the row read
    twice.

    ``idx`` is 0-based.
    """
    try:
        play_sound('ui/switch_list.ogg')
    except Exception:
        pass
    channel = _channel()
    if not channel.can('replaces_focus'):
        return False
    # The pieces, not the sentence.  A reader that takes a role and a place
    # in a list as FIELDS words them in its user's own verbosity settings;
    # one that does not gets them folded back in, in Titan's own wording -
    # "Applications, 1 of 4, tab" either way.  Which of the two happens is
    # the channel's business and deliberately not this function's.
    return channel.say(_message(
        view_name or _("Tab bar"),
        role=_("tab"),
        index=(idx + 1) if (total and total > 0) else None,
        count=total if (total and total > 0) else None,
        interrupt=True, replaces_focus=True))


# --- The Titan shell's taskbar groups ------------------------------------
# The taskbar has no tab bar to say which part of it the keyboard is in, and
# the shell itself may not speak (it is the system interface - a screen
# reader is already reading every focus change in it).  So arriving in a
# group is announced exactly the way the virtual tab bar is: through the
# screen reader alone, never through the platform TTS fallback, and with the
# control's own announcement following it.


def announce_search_results(count, label=None):
    """Say how many a search box found - to the screen reader alone.

    A search box is the one control where the *result* of typing is not
    where the focus is: the reader is reading the letters as they go into
    the field, and the list underneath changes silently.  Windows says the
    count, so this does too - through the reader (Titan Access first),
    never through the platform TTS, and with no sound of its own, because
    it happens on every keystroke.
    """
    if count:
        text = _("Results: {count}").format(count=count)
    else:
        text = _("No results")
    if label:
        text = "{}, {}".format(label, text)
    # Not a focus replacement: nothing is being focused.  Every reader that
    # is listening should hear it, and one reached through
    # ``accessible_output3`` alone hears it as the words.
    if _ta_speak(text, interrupt=True):
        return True
    return _reader_announce(text, interrupt=True)


def announce_shell_group(label, position=0.0):
    """Say which group of the taskbar the keyboard has just entered.

    "Dock", "Open windows", "System tray" - said once, when Tab (or one of
    the Windows shortcuts) arrives in the group, and not when the arrows
    move inside it.  Returns True when something said it.

    `position` is where that group IS across the screen, -1 .. 1 - the same
    number the focus cue is panned by, so the Start button is heard from
    the left and the clock from the right.  A reader that can place its
    voice is given it; one that cannot drops it, and the NVDA add-on then
    marks the place with a tone instead.

    This is the announcement that made the channel's `position` field mean
    anything.  The field was there from the start and NO CALLER EVER FILLED
    IT IN, which is what "there is no positioned speech" was: not a panner
    that did not work, but a panner that was never given a place to put the
    voice.
    """
    if not label:
        return False
    # `replaces_focus` is what stops the two racing: the reader says the
    # group and then reads the control it has landed on, rather than
    # cancelling one with the other.  A reader that cannot be told to
    # suppress anything still hears the group name, which is the whole of
    # what this says - there is nothing here to duplicate.
    return _reader_announce(label, interrupt=True, replaces_focus=True,
                            position=position)


# There is deliberately NO "announce this window" helper here.  A window
# says what it is by being CALLED it: the Start menu's title is "Start
# menu", and a screen reader reads the name of a window it has just entered
# by itself - Titan Access from its context presenter, NVDA from the
# foreground change.  Speaking it from the host as well was a second copy of
# the title, and one that had to be protected from being cut off (a focus
# event makes a reader cancel what it is saying), which meant holding the
# keyboard back from the window the user had just opened.  The title does
# the work instead.


def announce_shell_location(name, count):
    """Say where the file browser has just gone - to the screen reader alone.

    Navigating replaces the whole list under the reader, and the focus does
    not move while it happens, so nothing would be said at all: the window
    title changes and the list quietly holds something else.  Windows says
    where you are, so this does too - through Titan Access first, never
    through the platform TTS, and with no sound of its own.
    """
    if not name:
        return False
    text = _("{name}, {count} items").format(name=name, count=int(count or 0))
    return _reader_announce(text, interrupt=True, replaces_focus=True)


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
    if _ta_announce_segments(segments, interrupt=True):
        return True
    # A reader whose add-on is on the bus takes a pitch, but for the whole
    # utterance rather than per segment - so the two tones become two
    # announcements, the second queued behind the first.  It is offered only
    # to a reader that can suppress its own read of the row, or this would
    # be the third thing said about one arrow key.
    channel = _channel()
    if not (channel.can('replaces_focus') and channel.can('pitch')):
        return False
    said = channel.say(_message(name, pitch=DRAG_NAME_PITCH,
                                interrupt=True, replaces_focus=True))
    if not said:
        return False
    channel.say(_message(_("at position {}").format(position),
                         interrupt=False))
    return True


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


def announce_checklist_item_toggle(checked, delay_ms=500, speak=True):
    """Announce a check/uncheck toggle on a CheckListBox item.

    Uses the SAME earcons as a regular ``wx.CheckBox`` (``ui/X.ogg`` when
    the new state is checked, ``core/FOCUS.ogg`` when unchecked) so the
    user gets consistent auditory feedback across all checkbox widgets.
    The item name is NOT spoken — the SR already read it on focus — and
    the "checked" / "unchecked" state marker is spoken ``delay_ms`` ms
    later, only when a real screen reader is running.

    ``speak=False`` leaves the state to the control itself: a list whose
    rows are native check boxes (``src/ui/check_list.py``) reports the
    state through MSAA and UIA, so every reader says it in its own words
    and Titan saying it too would be the second, later copy.
    """
    try:
        play_sound('ui/X.ogg' if checked else 'core/FOCUS.ogg')
    except Exception:
        pass
    if not speak:
        return
    message = _("checked") if checked else _("unchecked")
    # Toggling fires no focus change, so speak the new state straight away
    # through Titan Access; only fall back to the delayed AO3 path otherwise.
    if not _ta_speak(message, interrupt=True):
        _speak_checklist_state_after(checked, delay_ms)


def announce_checklist_item_navigation(checked, delay_ms=500, speak=True):
    """Announce the check state while arrowing across CheckListBox rows.

    Uses the dedicated list-item earcon ``ui/cb_listitem_checked.ogg`` —
    distinct from the toggle sound so the user can tell nav from actual
    state change — and speaks "checked" / "unchecked" ``delay_ms`` ms
    later (SR only). Intended for ``wx.EVT_LISTBOX`` handlers.

    ``speak=False`` is for a list of native check boxes, which reports its
    own state to the reader (see :func:`announce_checklist_item_toggle`).
    """
    try:
        play_sound('ui/cb_listitem_checked.ogg')
    except Exception:
        pass
    if not speak:
        return
    message = _("checked") if checked else _("unchecked")
    # Arrowing onto a row fires a focus change, so let the READER append the
    # state to the item name it is about to read - Titan Access through its
    # own bridge, NVDA through its speech filter, so in both the state is
    # part of the same utterance as the name and cannot be cut off by it.
    # Only a reader that can do neither gets the delayed AO3 path.
    if not announce_state_suffix(message):
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

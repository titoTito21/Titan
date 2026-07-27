"""Automatic announcements of due tReminder reminders, by the AI assistant.

Titan watches tReminder's calendar file (the same
``%APPDATA%/Titosoft/Titan/appsettings/calendar.tcal`` the app itself reads) in a
background thread, and when a reminder falls due it announces it - so a reminder
reaches the user even when the tReminder window is closed.

An announcement is:

1. the notification sound (``ui/notify.ogg``) and an entry in the notification
   centre, then
2. the announcement text, either **spoken in the assistant's own voice**
   (Settings -> AI features -> "Announce reminders" = spoken) or read as a normal
   **text notification** through Titan TTS / the screen reader (= text).

The text itself is written by the AI in the persona's own words when AI features
are ready (e.g. "Hey, it's three o'clock - time for the dentist"); if the AI is
off or fails, a plain template is used instead. Which cloud voice speaks it is
decided by :func:`ai_provider.resolve_assistant_tts`, so it always matches the
API key that is actually configured.

The watcher never writes to the calendar file: tReminder stays the owner of the
reminders (marking done, repeats, snoozing). While the tReminder window is open
the watcher stays silent, because the app already alerts by itself.
"""

import datetime
import json
import os
import threading

from src.ai import ai_provider
from src.settings.settings import get_setting
from src.titan_core.translation import set_language

_ = set_language(get_setting('language', 'pl'))

try:
    from src.titan_core.sound import play_sound
except Exception:  # pragma: no cover - sound is optional
    def play_sound(*_a, **_k):
        pass

# How often the calendar file is checked, and how far back a reminder may be
# overdue and still be announced (so switching Titan on after a week does not
# replay a stack of stale reminders).
POLL_SECONDS = 30
MAX_LATE_HOURS = 24

SOUND_NOTIFY = 'ui/notify.ogg'


# --------------------------------------------------------------------------- #
# Reminder file + "already announced" state
# --------------------------------------------------------------------------- #
def _calendar_path():
    from src.ai.titan_tools import reminder_file_path
    return reminder_file_path()


def _state_path():
    from src.platform_utils import get_user_data_dir
    return os.path.join(get_user_data_dir(), 'reminder_announced.json')


def _load_reminders():
    """The reminder list from tReminder's calendar file ([] when missing or
    unreadable - the app may be rewriting it at this very moment)."""
    try:
        path = _calendar_path()
        if not os.path.exists(path):
            return []
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (ValueError, OSError) as e:
        print(f"[reminder_watcher] could not read reminders: {e}")
        return []


def _reminder_key(entry):
    """Stable identity of a reminder (it has no id of its own)."""
    return "{}|{}|{}".format(entry.get('name', ''), entry.get('date', ''),
                             entry.get('time', ''))


def _load_state():
    try:
        with open(_state_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _save_state(state):
    """Persist the announced keys, pruned to the last week so the file stays
    small and a reminder repeated much later can be announced again."""
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    pruned = {k: v for k, v in state.items() if v >= cutoff}
    try:
        path = _state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(pruned, f)
    except OSError as e:
        print(f"[reminder_watcher] could not save announced state: {e}")
    return pruned


def _due_datetime(entry):
    """When the reminder is due (None if the entry is malformed)."""
    try:
        d = datetime.date.fromisoformat(entry['date'])
        t = datetime.datetime.strptime(entry['time'], '%H:%M').time()
        return datetime.datetime.combine(d, t)
    except (KeyError, TypeError, ValueError):
        return None


def _treminder_window_open():
    """True while the tReminder (Titan Organizer) window exists - it alerts on
    its own then, so we keep quiet instead of announcing everything twice."""
    try:
        import win32gui
    except Exception:
        return False
    found = []

    def _cb(hwnd, _param):
        try:
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd) or ''
                if 'titan organizer' in title.lower():
                    found.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        return False
    return bool(found)


# --------------------------------------------------------------------------- #
# Announcement text
# --------------------------------------------------------------------------- #
def _plain_text(entry):
    """The fixed-template announcement, used when the AI is off or unavailable."""
    name = (entry.get('name') or '').strip()
    desc = (entry.get('description') or '').strip()
    when = (entry.get('time') or '').strip()
    if desc and desc != name:
        body = "{name}. {description}".format(name=name, description=desc)
    else:
        body = name
    if when:
        return _("Reminder for {time}: {body}").format(time=when, body=body)
    return _("Reminder: {body}").format(body=body)


def _ai_text(entry, persona):
    """Let the AI phrase the announcement in the persona's own words. Returns ''
    if AI features are off or the call fails, so the caller falls back to the
    plain template."""
    if not ai_provider.get_reminder_ai_phrasing() or not ai_provider.is_ai_ready():
        return ''
    base = (persona or {}).get('system_instruction', '') or (
        "You are a helpful voice assistant for the Titan (TCE) desktop.")
    language = (get_setting('language', 'pl') or 'pl').split('_')[0]
    system = (
        base + "\n\n"
        "You announce a reminder that has just fallen due. Write ONE short "
        "spoken sentence (two at most) telling the user what they have to do "
        "now, in your own natural words and in your own character. Include the "
        "reminder's subject and, when it helps, its time. Do NOT add greetings, "
        "quotes, markdown, emoji, explanations or anything else - output only "
        f"the sentence to be spoken, written in the language '{language}'.")
    when = "{} {}".format(entry.get('date', ''), entry.get('time', '')).strip()
    desc = (entry.get('description') or '').strip()
    prompt = "Reminder: {name}\nDue: {when}".format(
        name=(entry.get('name') or '').strip(), when=when)
    if desc:
        prompt += "\nDetails: {}".format(desc)
    try:
        text = ai_provider.generate(system, prompt, max_tokens=200)
    except Exception as e:
        print(f"[reminder_watcher] AI phrasing failed ({e}); using plain text.")
        return ''
    return (text or '').strip().strip('"')


# --------------------------------------------------------------------------- #
# Announcing
# --------------------------------------------------------------------------- #
def _log_notification(text):
    """Record the announcement in Titan's notification centre history and in the
    AI notifications buffer, so it can be reviewed again after it was spoken."""
    try:
        from src.ui.notificationcenter import add_notification
        now = datetime.datetime.now()
        add_notification(now.strftime('%Y-%m-%d'), now.strftime('%H:%M'),
                         _("Reminders"), text)
    except Exception as e:
        print(f"[reminder_watcher] could not log the notification: {e}")
    try:
        from src.buffers import ai_buffer
        ai_buffer.push_notice(text, author=_("Reminders"))
    except Exception as e:
        print(f"[reminder_watcher] buffer feed error: {e}")


def announce(entry, mode=None):
    """Announce one reminder ``entry`` (a calendar.tcal dict) right now. Runs on
    the CALLING thread and never raises; ``mode`` overrides the configured
    'voice' / 'text' announcement style."""
    mode = mode or ai_provider.get_reminder_announce()
    if mode == 'off':
        return ''
    persona = None
    try:
        from src.ai.assistant import personas as personas_mod
        persona = personas_mod.get_persona(ai_provider.get_assistant_model())
    except Exception as e:
        print(f"[reminder_watcher] persona unavailable: {e}")
    text = _ai_text(entry, persona) or _plain_text(entry)

    try:
        play_sound(SOUND_NOTIFY)
    except Exception:
        pass
    _log_notification(text)

    if mode == 'voice':
        try:
            from src.ai.assistant import voice_io
            voice_io.speak(text, persona=persona)
            return text
        except Exception as e:
            print(f"[reminder_watcher] voice announcement failed ({e}); "
                  f"falling back to text.")
    # Text mode (and the voice fallback): Titan TTS when it is on, else the
    # screen reader - the same path every other AI feature narrates through.
    try:
        from src.ai.ai_speech import speak
        speak(text)
    except Exception as e:
        print(f"[reminder_watcher] text announcement failed: {e}")
    return text


# --------------------------------------------------------------------------- #
# The watcher thread
# --------------------------------------------------------------------------- #
class _ReminderWatcher:
    """Singleton background poller. ``start()`` is safe to call repeatedly; it
    restarts the thread only when the feature is (still) enabled."""

    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def _enabled(self):
        """The announcer is part of the AI features, so it follows their master
        switch as well as its own off/text/voice setting."""
        return (ai_provider.is_ai_enabled()
                and ai_provider.get_reminder_announce() != 'off')

    def start(self):
        with self._lock:
            if self.is_running():
                return
            if not self._enabled():
                return
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name='reminder-watcher')
            self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            self._thread = None

    def refresh(self):
        """Apply changed settings: stop when switched off, start when switched on."""
        if not self._enabled():
            self.stop()
        else:
            self.start()

    def _run(self):
        # Reminders already due when Titan starts are announced on the first
        # pass (that is the point of the feature), but only the recent ones.
        state = _load_state()
        while not self._stop.wait(2.0):
            try:
                state = self._tick(state)
            except Exception as e:
                print(f"[reminder_watcher] check failed: {e}")
            if self._stop.wait(POLL_SECONDS):
                break

    def _tick(self, state):
        if not self._enabled():
            self.stop()
            return state
        entries = _load_reminders()
        if not entries:
            return state
        now = datetime.datetime.now()
        earliest = now - datetime.timedelta(hours=MAX_LATE_HOURS)
        pending = []
        for entry in entries:
            if not isinstance(entry, dict) or entry.get('done'):
                continue
            due = _due_datetime(entry)
            if due is None or due > now or due < earliest:
                continue
            key = _reminder_key(entry)
            if key in state:
                continue
            pending.append((due, key, entry))
        if not pending:
            return state
        # tReminder alerts by itself while it is open; mark nothing as announced
        # so we still speak them if the user closes it before they are dealt with.
        if _treminder_window_open():
            return state
        for _due, key, entry in sorted(pending, key=lambda p: p[0]):
            if self._stop.is_set():
                break
            state[key] = now.isoformat()
            state = _save_state(state)
            announce(entry)
        return state


_instance = _ReminderWatcher()


def start():
    """Start watching for due reminders (no-op when the feature is off)."""
    _instance.start()


def stop():
    """Stop watching."""
    _instance.stop()


def refresh():
    """Re-read the settings and start/stop accordingly (called after Save)."""
    _instance.refresh()


def is_running():
    return _instance.is_running()

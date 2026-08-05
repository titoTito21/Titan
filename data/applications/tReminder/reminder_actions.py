"""tReminder's Titan actions - the user's reminders and calendar.

Headless, because a reminder lives in one JSON file
(``%APPDATA%/Titosoft/Titan/appsettings/calendar.tcal``) that tReminder and
Titan's own announcer both read. Adding or completing one therefore needs no
window, and works whether or not the Organizer is open - which is the whole
point: the user says "remind me at six" and something has to happen even
though tReminder is closed.

The record shape is tReminder's own, so the app shows what is written here
exactly as if the user had typed it in.
"""

import datetime
import json
import os
import platform
import sys

# Titan tells us where it is (a packaged add-on runs from an extraction
# cache, so '../../..' from this file would point nowhere near Titan). The
# relative guess is the fallback for running this module by hand.
_TITAN_ROOT = os.environ.get('TITAN_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _TITAN_ROOT not in sys.path:
    sys.path.insert(0, _TITAN_ROOT)

from src.titan_core.titan_actions import fails, needs

PRIORITIES = {'low': 0, 'medium': 1, 'normal': 1, 'high': 2}
PRIORITY_NAMES = {0: 'low', 1: 'medium', 2: 'high'}
REPEATS = {'once': 3, 'every15': 0, 'daily': 1, 'weekly': 2}


def _appsettings_dir():
    system = platform.system()
    if system == 'Windows':
        base = os.getenv('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'Titosoft', 'Titan', 'appsettings')
    if system == 'Darwin':
        return os.path.join(os.path.expanduser('~'), 'Library',
                            'Application Support', 'Titosoft', 'Titan',
                            'appsettings')
    return os.path.join(os.path.expanduser('~'), '.config', 'Titosoft',
                        'Titan', 'appsettings')


def _calendar_path():
    return os.path.join(_appsettings_dir(), 'calendar.tcal')


def _load():
    try:
        with open(_calendar_path(), 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(entries):
    os.makedirs(_appsettings_dir(), exist_ok=True)
    with open(_calendar_path(), 'w', encoding='utf-8') as handle:
        json.dump(entries, handle)


def _parse_when(date, time):
    """Flexible date and time, defaulting to today and the next full hour."""
    now = datetime.datetime.now()
    text = str(date or '').strip().lower()
    if text in ('', 'today', 'dzis', 'dziś', 'dzisiaj'):
        day = now.date()
    elif text in ('tomorrow', 'jutro'):
        day = now.date() + datetime.timedelta(days=1)
    else:
        day = None
        for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                day = datetime.datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        day = day or now.date()
    clock = str(time or '').strip().replace('.', ':')
    moment = None
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            moment = datetime.datetime.strptime(clock, fmt).time()
            break
        except ValueError:
            continue
    if moment is None:
        moment = (now + datetime.timedelta(hours=1)).time().replace(
            second=0, microsecond=0)
    return day.isoformat(), moment.strftime('%H:%M')


def _describe(entry, index):
    done = ' [done]' if entry.get('done') else ''
    priority = PRIORITY_NAMES.get(entry.get('priority', 1), 'medium')
    return (f"{index}. {entry.get('name', '(no title)')} - "
            f"{entry.get('date', '?')} {entry.get('time', '?')}, "
            f"{priority} priority{done}")


def _match(entries, query):
    """Indexes of the reminders matching a name or a number the user gave."""
    wanted = str(query or '').strip().lower()
    if not wanted:
        return []
    if wanted.isdigit():
        index = int(wanted) - 1
        return [index] if 0 <= index < len(entries) else []
    exact = [i for i, e in enumerate(entries)
             if str(e.get('name', '')).lower() == wanted]
    if exact:
        return exact
    return [i for i, e in enumerate(entries)
            if wanted in str(e.get('name', '')).lower()]


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
def list_reminders(include_done=False, when=''):
    """List the user's reminders."""
    entries = _load()
    if not entries:
        return "There are no reminders."
    today = datetime.date.today().isoformat()
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    scope = str(when or '').strip().lower()
    lines = []
    for index, entry in enumerate(entries, 1):
        if entry.get('done') and not include_done:
            continue
        if scope in ('today', 'dzis', 'dziś') and entry.get('date') != today:
            continue
        if scope in ('tomorrow', 'jutro') and entry.get('date') != tomorrow:
            continue
        lines.append(_describe(entry, index))
    if not lines:
        return ("Nothing is due then." if scope
                else "There are no outstanding reminders.")
    return "\n".join(lines)


def next_reminder():
    """The next reminder that is due."""
    now = datetime.datetime.now()
    upcoming = []
    for entry in _load():
        if entry.get('done'):
            continue
        try:
            when = datetime.datetime.strptime(
                f"{entry.get('date')} {entry.get('time')}", '%Y-%m-%d %H:%M')
        except (ValueError, TypeError):
            continue
        if when >= now:
            upcoming.append((when, entry))
    if not upcoming:
        return "Nothing is coming up."
    when, entry = min(upcoming, key=lambda item: item[0])
    return (f"Next: {entry.get('name')} on {entry.get('date')} at "
            f"{entry.get('time')}.")


def create_reminder(name, description='', date='', time='', priority='medium',
                    repeat='once'):
    """Create a reminder in the Organizer."""
    if not str(name).strip():
        return needs('name', "What should the reminder say?")
    date_iso, time_hm = _parse_when(date, time)
    entries = _load()
    entries.append({
        'name': name.strip(),
        'description': (description or name).strip(),
        'date': date_iso, 'time': time_hm,
        'priority': PRIORITIES.get(str(priority).strip().lower(), 1),
        'repeat': REPEATS.get(str(repeat).strip().lower(), 3),
        'done': False,
    })
    _save(entries)
    return (f"Reminder '{name}' saved for {date_iso} at {time_hm}. Titan "
            f"announces it when it is due, even if the Organizer is closed.")


def complete_reminder(which):
    """Mark a reminder as done."""
    entries = _load()
    found = _match(entries, which)
    if not found:
        return fails(f"There is no reminder matching '{which}'.")
    if len(found) > 1:
        names = [entries[i].get('name', '?') for i in found[:8]]
        return needs('which', f"'{which}' matches {len(found)} reminders. "
                     f"Which one should be marked done?", options=names)
    entries[found[0]]['done'] = True
    _save(entries)
    return f"Marked '{entries[found[0]].get('name')}' as done."


def delete_reminder(which):
    """Delete a reminder."""
    entries = _load()
    found = _match(entries, which)
    if not found:
        return fails(f"There is no reminder matching '{which}'.")
    if len(found) > 1:
        names = [entries[i].get('name', '?') for i in found[:8]]
        return needs('which', f"'{which}' matches {len(found)} reminders. "
                     f"Which one should be deleted?", options=names)
    removed = entries.pop(found[0])
    _save(entries)
    return f"Deleted the reminder '{removed.get('name')}'."


HANDLERS = {
    'list_reminders': list_reminders,
    'next_reminder': next_reminder,
    'create_reminder': create_reminder,
    'complete_reminder': complete_reminder,
    'delete_reminder': delete_reminder,
}


if __name__ == '__main__':
    from src.titan_core.titan_actions import run_cli
    sys.exit(run_cli(HANDLERS))

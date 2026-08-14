"""
Titan's settings file, and the one rule about reading it.

The file itself is unchanged - `bg5settings.ini` in the user's data folder,
sections in square brackets and `key=value` lines under them.  What changed is
that it is no longer READ FROM DISK on every question asked of it.

`get_setting` opened, read and parsed the whole file each time it was called,
which for most of Titan is invisible - a settings dialog asks a few dozen
times and nobody notices 0.17 ms.  The shell is not most of Titan: it asks on
every paint (is there a clock? is there a Show Desktop button?), on every
layout, on every focus cue, once a second for the clock's format and TEN TIMES
A SECOND while the taskbar is deciding whether to slide out of the way.
Measured here, a thousand reads of one setting cost 169 ms of pure file I/O
and parsing, all of it on the GUI thread of the process that owns the appbar
and the shell hook.

So the parse is kept, and thrown away when the FILE changes: `os.stat` (a
couple of microseconds) says whether it has, which covers Titan's own writes
and an edit made by anything else.  `save_settings` puts what it has just
written straight into the cache as well, so a setting read immediately after
it was set cannot see the old value through a file system whose timestamps
have not caught up.

`load_settings()` still hands back a copy, because callers - the settings
wizard, the controller modes - keep the dictionary, change it and save it back
later; only `get_setting`, which reads one value and keeps nothing, is allowed
to see the cache itself.
"""

import os
import platform
import threading
import time


def get_settings_path():
    if platform.system() == 'Windows':
        appdata = os.getenv('APPDATA') or os.path.expanduser('~')
        return os.path.join(appdata, 'titosoft', 'Titan', 'bg5settings.ini')
    elif platform.system() == 'Linux':
        return os.path.expanduser('~/.config/titosoft/Titan/bg5settings.ini')
    elif platform.system() == 'Darwin':  # macOS
        return os.path.expanduser('~/Library/Application Support/titosoft/Titan/bg5settings.ini')
    else:
        raise NotImplementedError('Unsupported platform')

SETTINGS_FILE_PATH = get_settings_path()

# The file as it was last parsed, what it looked like on disk then, and when
# we last bothered to look.
_cache = {'stamp': None, 'data': {}, 'checked': 0.0}
_cache_lock = threading.Lock()

# How often the file is looked at, at most.  Asking `os.stat` is cheap next to
# parsing but not free - measured at about thirty microseconds here - and the
# shell asks for a setting several times inside a single paint.  Titan's own
# writes go into the cache as they are made, so this only delays noticing a
# change made by something OUTSIDE this process, and a quarter of a second is
# not a delay anybody can feel.
STAT_INTERVAL = 0.25


def _file_stamp():
    """What the settings file looks like from outside: when, and how big."""
    try:
        info = os.stat(SETTINGS_FILE_PATH)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def _parse_settings():
    settings = {}
    try:
        with open(SETTINGS_FILE_PATH, 'r', encoding='utf-8') as file:
            current_section = None
            for line in file:
                line = line.strip()
                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1]
                    settings[current_section] = {}
                elif '=' in line:
                    key, value = line.split('=', 1)
                    if current_section:
                        settings[current_section][key.strip()] = value.strip()
    except OSError:
        return {}
    return settings


def _current_settings():
    """The settings as they stand, parsed again only if the file changed."""
    now = time.monotonic()
    with _cache_lock:
        if (_cache['stamp'] is not None
                and now - _cache['checked'] < STAT_INTERVAL):
            return _cache['data']
    stamp = _file_stamp()
    with _cache_lock:
        _cache['checked'] = now
        if stamp is None:
            _cache['stamp'] = None
            _cache['data'] = {}
            return _cache['data']
        if _cache['stamp'] != stamp:
            _cache['data'] = _parse_settings()
            _cache['stamp'] = stamp
        return _cache['data']


def _remember(settings):
    with _cache_lock:
        _cache['data'] = {section: dict(values)
                          for section, values in settings.items()}
        _cache['stamp'] = _file_stamp()
        _cache['checked'] = time.monotonic()


def invalidate_settings_cache():
    """Forget the parsed file - for a test, or a write we did not make."""
    with _cache_lock:
        _cache['stamp'] = None
        _cache['data'] = {}
        _cache['checked'] = 0.0


def load_settings():
    """Every setting, as a dictionary of the caller's own to change."""
    return {section: dict(values)
            for section, values in _current_settings().items()}


def save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE_PATH), exist_ok=True)
    with open(SETTINGS_FILE_PATH, 'w', encoding='utf-8') as file:
        for section, values in settings.items():
            file.write(f'[{section}]\n')
            for key, value in values.items():
                file.write(f'{key}={value}\n')
            file.write('\n')
    # What was just written IS what the file holds; taking it from the file
    # again would depend on a timestamp the file system may not have updated
    # yet, and a setting read straight after being set must not see the old
    # value.
    _remember(settings)


def get_setting(key, default=None, section='general'):
    """Retrieves a specific setting value from a section."""
    return _current_settings().get(section, {}).get(key, default)


def set_setting(key, value, section='general'):
    """Sets a specific setting value in a section."""
    settings = load_settings()
    if section not in settings:
        settings[section] = {}
    settings[section][key] = value
    save_settings(settings)

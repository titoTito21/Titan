# -*- coding: utf-8 -*-
"""What the reader did, written down where a compiled Titan can be read.

A compiled Titan is built windowed: ``sys.stdout`` is None and every
``print`` in this package reaches nobody - which is how "the reader
hangs" was a report with nothing behind it. `log()` writes the line to
``.../titosoft/Titan/logs/titan_access.log`` (rotated at 2 MB) and still
prints it where there is a console. One file for the whole reader: the
supervisor's pings, the worker's death, a hook put back, a speech error.

Nothing here raises, and the file is opened per line - a reader that
loses its log must not lose anything else.
"""

import os
import sys
import threading
import time

_LOCK = threading.Lock()
_state = {'path': None, 'lines': 0, 'failed': 0}
MAX_BYTES = 2 * 1024 * 1024


def path():
    """The log file, under Titan's own logs folder."""
    if _state['path']:
        return _state['path']
    try:
        from titan_access.portable import readerHome
        base = readerHome.titan_folder()
    except Exception:                                # noqa: BLE001
        base = os.path.join(os.path.expanduser('~'), 'titosoft', 'Titan')
    folder = os.path.join(base, 'logs')
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass
    _state['path'] = os.path.join(folder, 'titan_access.log')
    return _state['path']


def _rotate(where):
    try:
        if os.path.getsize(where) > MAX_BYTES:
            old = where + '.1'
            if os.path.exists(old):
                os.remove(old)
            os.replace(where, old)
    except OSError:
        pass


def log(message, *args):
    """Write one line, stamped; print it too where a console exists."""
    try:
        text = str(message) % args if args else str(message)
    except Exception:                                # noqa: BLE001
        text = str(message)
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    line = '%s [%s] %s' % (stamp, threading.current_thread().name, text)
    try:
        if sys.stdout is not None:
            print(text, flush=True)
    except Exception:                                # noqa: BLE001
        pass
    with _LOCK:
        try:
            where = path()
            _rotate(where)
            with open(where, 'a', encoding='utf-8', errors='replace') as handle:
                handle.write(line + '\n')
            _state['lines'] += 1
        except Exception:                            # noqa: BLE001
            _state['failed'] += 1


def report():
    with _LOCK:
        return dict(_state)


def stacks(threads=None):
    """The Python stack of every thread (or the named ones), as text -
    what a reader that has stopped answering is doing, written where it
    can be read afterwards."""
    out = []
    frames = sys._current_frames()
    import traceback
    wanted = {t.ident: t.name for t in (threads or threading.enumerate())}
    for ident, frame in frames.items():
        name = wanted.get(ident)
        if threads is not None and name is None:
            continue
        out.append('-- thread %s (%s)' % (name or '?', ident))
        out.extend(line.rstrip() for line in traceback.format_stack(frame))
    return '\n'.join(out)

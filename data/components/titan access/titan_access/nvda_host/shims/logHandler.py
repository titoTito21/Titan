# -*- coding: utf-8 -*-
"""NVDA's `logHandler`: `log.info(...)` and friends, into Titan Access's
own log (`logs/titan_access.log`)."""


import threading as _threading
import time as _time

#: The same complaint from an add-on is written once a minute at most.
#: ELTEN's global plugin retries its pipe in a loop and logs every failure:
#: 336 tracebacks in the reader's log in four days, ten a second at worst,
#: each a disk write in the reader's process and each burying what else
#: the log had to say. A repeat is counted and the count is written when
#: the minute is up.
REPEAT_WINDOW_S = 60.0
_seen = {}
_seen_lock = _threading.Lock()


def _repeat(key):
    """``None`` to write the line now, or ``False`` to drop it. A line that
    ends a quiet minute says how many were dropped (``int``)."""
    now = _time.monotonic()
    with _seen_lock:
        first, dropped = _seen.get(key, (None, 0))
        if first is not None and now - first < REPEAT_WINDOW_S:
            _seen[key] = (first, dropped + 1)
            return False
        _seen[key] = (now, 0)
        if len(_seen) > 500:
            _seen.clear()
        return dropped or None


def _write(level, message, *args, key=None, **kwargs):
    try:
        text = str(message) % args if args else str(message)
    except Exception:                                # noqa: BLE001
        text = str(message)
    repeated = _repeat((level, key or text))
    if repeated is False:
        return
    if repeated:
        text += ' (and %d times more in the last minute)' % repeated
    try:
        from titan_access.log import log as _log
        _log('[NVDA add-on] %s: %s' % (level, text))
    except Exception:                                # noqa: BLE001
        print('[NVDA add-on] %s: %s' % (level, text))


class _Log(object):
    def debug(self, message, *args, **kwargs):
        pass

    def io(self, message, *args, **kwargs):
        pass

    def info(self, message, *args, **kwargs):
        _write('info', message, *args)

    def warning(self, message, *args, **kwargs):
        _write('warning', message, *args)

    debugWarning = warning

    def error(self, message, *args, **kwargs):
        _write('error', message, *args)

    def exception(self, message='', *args, **kwargs):
        import sys
        import traceback
        # The key is WHERE it failed and what kind of failure, not the
        # exception's text: ELTEN's pipe name is new on every try.
        kind, _value, tb = sys.exc_info()
        where = traceback.extract_tb(tb)[-1:] if tb is not None else []
        key = (str(message), getattr(kind, '__name__', ''),
               tuple((frame.filename, frame.lineno) for frame in where))
        _write('exception', '%s\n%s' % (message, traceback.format_exc()),
               key=key)

    critical = error

    def isEnabledFor(self, level):
        return True


log = _Log()


from . import permissive as _permissive  # noqa: E402
_permissive(globals())

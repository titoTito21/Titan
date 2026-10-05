# -*- coding: utf-8 -*-
"""NVDA's `logHandler`: `log.info(...)` and friends, into Titan Access's
own log (`logs/titan_access.log`)."""


def _write(level, message, *args, **kwargs):
    try:
        text = str(message) % args if args else str(message)
    except Exception:                                # noqa: BLE001
        text = str(message)
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
        import traceback
        _write('exception', '%s\n%s' % (message, traceback.format_exc()))

    critical = error

    def isEnabledFor(self, level):
        return True


log = _Log()


from . import permissive as _permissive  # noqa: E402
_permissive(globals())

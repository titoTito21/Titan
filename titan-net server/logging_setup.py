#!/usr/bin/env python3
"""One logging setup, applied once - and an audit trail that survives it.

**Why this exists.** Three modules each called ``logging.basicConfig`` with
a ``FileHandler`` of their own::

    logging.basicConfig(handlers=[logging.FileHandler('logs/main.log'), ...])

``basicConfig`` configures the root logger **the first time it is called and
never again** - later calls are a silent no-op unless ``force=True``. But
the handler in the argument list is CONSTRUCTED before ``basicConfig`` gets
to decide that, and constructing a ``FileHandler`` opens its file. So every
module after the first created its log file, opened it, and then had the
handler thrown away.

Measured on production: ``logs/http_server.log`` and ``logs/main.log`` were
**0 bytes, dated 9 April** - created on that day's restart and never written
to again, for five months. The symptom is the worst kind: the file is there,
its timestamp looks plausible, and nothing anywhere says it is not being
written. It was found only when somebody asked whether an account had been
broken into and there was nothing to read.

Two things follow, and they are separate:

* **A module's log belongs to that module's logger, not to the root.** Each
  gets its own rotating file attached to its own named logger, so import
  order cannot decide which of them works.
* **An audit trail is not a log.** A log is for whoever is debugging;
  :func:`audit` is for the question "who signed in, from where, and when",
  which is asked months later by somebody who is not debugging anything. It
  is one line per event, machine-readable, never truncated, and it is
  deliberately not the same file as the chatter.
"""

import json
import logging
import logging.handlers
import os
import time

#: Where they go. Relative, because every entry point runs with the
#: installation as its working directory (the systemd unit sets
#: WorkingDirectory=/opt/titan-net).
FOLDER = 'logs'

FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

#: Per file. 32 MB x 10 is about 320 MB of ceiling per log, which is what
#: `server.log` was already using and what the disk has room for. A plain
#: FileHandler grew that one to 41 MB in a single uptime, and the only
#: thing that ever shortened it was somebody truncating it by hand.
MAX_BYTES = 32 * 1024 * 1024
KEEP = 10

#: The audit trail is smaller per line and worth keeping far longer: this
#: is the file somebody reads when they are asked whether an account was
#: taken. 16 MB x 40 is a year and a half of a busy server.
AUDIT_BYTES = 16 * 1024 * 1024
AUDIT_KEEP = 40

_AUDIT_NAME = 'TitanNetAudit'


def _folder():
    try:
        os.makedirs(FOLDER, exist_ok=True)
    except Exception:                                # noqa: BLE001
        pass
    return FOLDER


def _already(logger, filename):
    """Whether this logger already writes that file.

    Asked rather than remembered in a flag, because a module may be
    imported twice under two names and the answer has to be about the
    handlers that are really attached.
    """
    for handler in logger.handlers:
        if getattr(handler, '_titan_log', None) == filename:
            return True
    return False


def configure(name, filename, level=logging.INFO, console=True):
    """Give one module's logger its own rotating file. Idempotent.

    Returns the logger, so a module can write::

        logger = logging_setup.configure('TitanNetHTTP', 'http_server.log')

    in place of its own ``basicConfig``, and be sure that its file is
    written whatever else has been imported first.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not _already(logger, filename):
        try:
            handler = logging.handlers.RotatingFileHandler(
                os.path.join(_folder(), filename), maxBytes=MAX_BYTES,
                backupCount=KEEP, encoding='utf-8')
            handler.setFormatter(logging.Formatter(FORMAT))
            handler._titan_log = filename
            logger.addHandler(handler)
        except Exception as error:                   # noqa: BLE001
            # A log that cannot be opened must not stop a server starting.
            print('[logging] could not open %s: %s' % (filename, error))
    # The root gets a console handler once, so everything still reaches
    # the journal exactly as it did before - `StandardOutput=journal` in
    # the unit file is what makes `journalctl -u titan-net` work, and
    # nothing here may take that away.
    root = logging.getLogger()
    if console and not any(isinstance(h, logging.StreamHandler)
                           and not isinstance(
                               h, logging.handlers.RotatingFileHandler)
                           for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(stream)
    if root.level > level:
        root.setLevel(level)
    return logger


# --------------------------------------------------------------------------- #
# The audit trail
# --------------------------------------------------------------------------- #
def _audit_logger():
    logger = logging.getLogger(_AUDIT_NAME)
    if not _already(logger, 'audit.log'):
        logger.setLevel(logging.INFO)
        # **Its own file and nobody else's.** It does not propagate, so a
        # change to the root's level or handlers can never quieten it -
        # which is what happened to every other log here.
        logger.propagate = False
        try:
            handler = logging.handlers.RotatingFileHandler(
                os.path.join(_folder(), 'audit.log'), maxBytes=AUDIT_BYTES,
                backupCount=AUDIT_KEEP, encoding='utf-8')
            # One JSON object per line and nothing else: this file is read
            # by a person under time pressure and by a script, and a
            # format with a message in the middle of it is neither.
            handler.setFormatter(logging.Formatter('%(message)s'))
            handler._titan_log = 'audit.log'
            logger.addHandler(handler)
        except Exception as error:                   # noqa: BLE001
            print('[logging] could not open audit.log: %s' % error)
    return logger


def audit(event, **fields):
    """Write down something that happened to an ACCOUNT. Never raises.

    ``event`` is what happened - 'login', 'login_failed', 'password_change',
    'ban', 'unban' - and the fields are whatever is known about it. A
    password never goes in here, and neither does a token: what is wanted
    months later is who, from where, and when.
    """
    row = {'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'ts': int(time.time()),
           'event': str(event)}
    for name, value in fields.items():
        if value is None:
            continue
        # Belt and braces: a caller that hands over a secret by mistake
        # must not have it written down for a year and a half.
        if any(word in name.lower()
               for word in ('password', 'token', 'secret', 'key', 'hash',
                            'session', 'cookie', 'auth', 'credential')):
            continue
        row[name] = value if isinstance(value, (int, float, bool)) \
            else str(value)[:200]
    try:
        _audit_logger().info(json.dumps(row, ensure_ascii=False))
    except Exception:                                # noqa: BLE001
        pass


def report():
    """What is really being written, for a check that can be run.

    The whole failure this file is about was invisible, so being able to
    ASK is half the fix: a file of zero bytes whose logger has no handler
    is the shape to look for.
    """
    found = {}
    for name in ('TitanNetMain', 'TitanNetHTTP', 'TitanNetServer',
                 _AUDIT_NAME):
        logger = logging.getLogger(name)
        files = [getattr(h, '_titan_log', None) for h in logger.handlers]
        files = [one for one in files if one]
        sizes = {}
        for one in files:
            try:
                sizes[one] = os.path.getsize(os.path.join(FOLDER, one))
            except OSError:
                sizes[one] = None
        found[name] = {'handlers': len(logger.handlers), 'files': sizes}
    return found

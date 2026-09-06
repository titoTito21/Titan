# -*- coding: utf-8 -*-
"""One JSON object per line, between Titan and an application it launched.

Deliberately the same wire as `data/components/elten_bridge/eltenkit/
bridge.py`, because that one is proven and its two hard-won rules apply
here word for word:

- **stdout belongs to the protocol and nothing else.** An application WILL
  `print` - Titan's own do it constantly - and one stray line corrupts the
  stream and takes the application down with a parse error that reads like
  a Titan bug. So the shim takes the real stdout away at start-up, keeps it
  privately, and points `sys.stdout` at stderr, where Titan collects it as
  the log.
- **a line longer than `MAX_LINE` ends the application** rather than making
  Titan buffer without bound.

What is different is which way the conversation runs. In the Elten port
the application ASKS and Titan answers; here the application DESCRIBES and
Titan tells it what the user did. So the shim pushes a `screen` whenever
its interface changes, and Titan pushes back one `do` at a time.
"""

import json

#: Longer than any screen a real application produces, and small enough
#: that a runaway one is stopped rather than absorbed.
MAX_LINE = 4 * 1024 * 1024

#: What the application says.
FROM_APP = (
    'ready',      # the shim is up; carries what it could not provide
    'screen',     # this is the interface now
    'said',       # something to speak that is not a control
    'gone',       # the application has finished
    'refused',    # something it asked wx for that cannot be rendered
)

#: What Titan says.
TO_APP = (
    'press',      # a button, a menu item, a row opened
    'set',        # a value the user changed
    'key',        # a key that belongs to the application, not to a control
    'close',      # leave this screen
    'quit',       # the user closed the application
    'read',       # send the screen again, whatever it is
)


def pack(kind, **rest):
    """One message as a line. Never raises: a message that cannot be
    written is a message not sent, which is recoverable; an exception on
    the wire thread is not."""
    body = dict(rest)
    body['do'] = str(kind)
    try:
        return json.dumps(body, ensure_ascii=False).encode('utf-8') + b'\n'
    except (TypeError, ValueError):
        return json.dumps({'do': str(kind)}).encode('utf-8') + b'\n'


def unpack(raw):
    """One line as a message, or None when it is not one."""
    try:
        body = json.loads(raw.decode('utf-8'))
    except (AttributeError, UnicodeDecodeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def lines(stream):
    """Whole lines off a byte stream, with a ceiling on how long one may be."""
    buffered = b''
    # **`read1`, not `read`.** `BufferedReader.read(n)` on a pipe returns
    # only when it has n bytes or the far end closes - so a whole screen
    # sat in the buffer, unread, until the application exited, and the
    # first thing this ever saw was a corpse. `read1` returns what has
    # arrived, which is what a line-based protocol needs.
    reader = getattr(stream, 'read1', None) or stream.read
    while True:
        try:
            chunk = reader(65536)
        except Exception:
            return
        if not chunk:
            if buffered:
                yield buffered
            return
        buffered += chunk
        while b'\n' in buffered:
            line, buffered = buffered.split(b'\n', 1)
            if line:
                yield line
        if len(buffered) > MAX_LINE:
            return

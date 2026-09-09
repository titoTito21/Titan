# -*- coding: utf-8 -*-
"""Telling Titan what the user is reading.

Every other bridge in this add-on runs one way: Titan asks, NVDA answers.
That is right for a question - "what is the focus on right now" - and
wrong for making Titan's own subsystems **contextual**, because Titan
would have to ask constantly to find out, and something that has to poll
never does it often enough or does it far too often.

So the reader tells the desktop, when it changes and not otherwise: which
program the user is in, what its window is called, and whether it is a
window this reader can do anything with. With that, Titan's AI, its
macros and its actions can be about the program the user is REALLY in -
which Titan cannot work out for itself, because on a machine being read
the foreground window and the window somebody is working in come apart
constantly: a menu is up, a tooltip has the foreground, the reader has
followed them into a popup owned by something else.

**It is a self-report, so nothing is being driven.** Titan serves
`client.report` to any client without asking its user for anything,
precisely because a client saying what it is looking at is not a client
acting on the desktop. Nothing here changes Titan and nothing here can.

**It costs almost nothing.** Only when the program CHANGES, never more
often than :data:`MIN_SECONDS`, always on a thread of its own - a
foreground event is on NVDA's main thread, and a named pipe there is a
reader that has stopped answering.
"""

import threading
import time

from . import i18n

_ = i18n.install(globals())

#: Never more often than this, however much the user Alt+Tabs.
MIN_SECONDS = 2.0

_LOCK = threading.RLock()
_state = {'program': '', 'at': 0.0, 'sent': 0, 'why': ''}


def report():
    with _LOCK:
        return dict(_state)


def wanted():
    from . import configSpec
    return bool(configSpec.read().get('reportContext', True))


def changed(obj):
    """Tell Titan where the user now is, if that is news. Never waits."""
    if not wanted():
        return False
    from .link import LINK
    if not LINK.connected():
        return False
    try:
        from . import perProgram
        program = str(perProgram.application_of(obj) or '')
    except Exception:                                # noqa: BLE001
        program = ''
    if not program:
        return False
    title = ''
    try:
        title = str(getattr(obj, 'name', '') or '')
    except Exception:                                # noqa: BLE001
        title = ''
    now = time.time()
    with _LOCK:
        if program == _state['program'] and now - _state['at'] < MIN_SECONDS:
            return False
        _state['program'] = program
        _state['at'] = now
    what = {'program': program, 'window': title, 'reader': 'nvda'}
    try:
        from . import virtualWindow
        if virtualWindow.reviewing():
            what['mode'] = 'virtual window'
    except Exception:                                # noqa: BLE001
        pass

    def send():
        from . import titan
        ok, said = titan.report_context(**what)
        with _LOCK:
            if ok:
                _state['sent'] += 1
            else:
                _state['why'] = str(said)
    threading.Thread(target=send, name='TitanReport', daemon=True).start()
    return True

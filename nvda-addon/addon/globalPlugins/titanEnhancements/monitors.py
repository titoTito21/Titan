# -*- coding: utf-8 -*-
"""Watch a part of the screen, and say when it changes.

JAWS calls them Frames, ZDSR calls them monitored areas, and every reader
that has them is asked for them by the same people for the same reason: a
status line at the bottom of a build, a chat window behind the one you are
typing in, a percentage in a corner, a list that fills in while you are
somewhere else. A screen reader speaks about the thing you are ON; none of
that is the thing you are on, and without something like this you find out
by going and looking.

:mod:`live` already does this for what a program DECLARES live - an ARIA
region, a status bar, something a reader module or Titan named. This is the
other half, and it is the half a user makes: **you mark it yourself**, and
what you mark is whatever you were on.

Three kinds, in the order they are tried, because each is better than the
one after it where it works at all:

* **A control**, remembered the way a label is remembered - the executable,
  the window class, the control's own dialog id and its automation id. Its
  value is read through NVDA, which is exact and costs nothing.
* **A place in the window**, when the control has nothing stable to be
  remembered by. Read by asking NVDA what object is at that point.
* **A rectangle of the screen**, read with Windows' own OCR. This is the
  one JAWS Frames really is, and it is what makes an area of a program with
  no accessibility at all watchable - a game's score, an installer's
  progress. It costs a local recognition per poll and nothing else.

**It never speaks over the thing you are doing.** A monitor's announcement
is queued, never interrupting, and a monitor that changes constantly says so
once and then slows down - the same discipline `live` has, for the same
reason: a reader that talks over you is one you switch off.
"""

import json
import os
import threading
import time

from . import i18n

_ = i18n.install(globals())

FILENAME = 'titanMonitors.json'

#: How often a monitor is looked at. Slower than a focus event and faster
#: than a person gets impatient; a monitor is for something that changes on
#: its own, not for something you are watching happen.
POLL = 1.5

#: A monitor that changes on nearly every poll is a clock, a progress bar or
#: an animation. It is said, and then it is said less often - a reader
#: reading a spinner is a reader nobody keeps on.
BUSY_ENOUGH = 4
SLOW_POLL = 8.0

#: What a monitor may be.
BY_CONTROL = 'control'
BY_POINT = 'point'
BY_AREA = 'area'
KINDS = (BY_CONTROL, BY_POINT, BY_AREA)

_LOCK = threading.RLock()
_monitors = None
_seen = {}
_thread = None
_stop = None
_state = {'said': 0, 'checks': 0, 'why': ''}


def report():
    with _LOCK:
        return dict(_state, watching=len(_monitors or []),
                   running=bool(_thread is not None and _thread.is_alive()))


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
def path():
    try:
        import globalVars
        return os.path.join(globalVars.appArgs.configPath, FILENAME)
    except Exception:                                # noqa: BLE001
        return ''


def _load():
    global _monitors
    with _LOCK:
        if _monitors is not None:
            return _monitors
        _monitors = []
        where = path()
        if where and os.path.isfile(where):
            try:
                with open(where, encoding='utf-8') as handle:
                    data = json.load(handle)
                if isinstance(data, list):
                    _monitors = [row for row in data
                                 if isinstance(row, dict) and row.get('kind')
                                 in KINDS]
            except Exception:                        # noqa: BLE001
                _monitors = []
        return _monitors


def forget():
    global _monitors
    with _LOCK:
        _monitors = None
        _seen.clear()


def save():
    where = path()
    if not where:
        return False
    with _LOCK:
        data = list(_load())
    try:
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
        return True
    except Exception:                                # noqa: BLE001
        return False


def all_monitors():
    return list(_load())


def remove(index):
    with _LOCK:
        monitors = _load()
        if not 0 <= index < len(monitors):
            return False
        gone = monitors.pop(index)
        _seen.pop(_key(gone), None)
    save()
    _keep_running()
    return True


def clear():
    with _LOCK:
        _load()[:] = []
        _seen.clear()
    save()
    _keep_running()
    return True


# --------------------------------------------------------------------------- #
# Making one
# --------------------------------------------------------------------------- #
def _program(obj=None):
    try:
        from . import perProgram
        return str(perProgram.application_of(obj) or '')
    except Exception:                                # noqa: BLE001
        return ''


def here(obj=None):
    """The object a watch is made from: **the navigator object**.

    Deliberately not the focus. A progress bar, a status line, a pane that
    fills itself in - the things anybody actually asks to have watched -
    are exactly the things nothing ever focuses, and object navigation is
    how NVDA reaches them. The navigator follows the focus unless the user
    has moved it, so this IS the focused control whenever they have not and
    the control they walked to when they have: one command covers both and
    there is no second key to remember.

    The focus and then the foreground window are the fallbacks, because an
    NVDA whose review cursor has not settled anywhere must still answer.
    """
    if obj is not None:
        return obj
    try:
        import api
    except Exception:                                # noqa: BLE001
        return None
    for ask in ('getNavigatorObject', 'getFocusObject',
                'getForegroundObject'):
        try:
            found = getattr(api, ask)()
        except Exception:                            # noqa: BLE001
            found = None
        if found is not None:
            return found
    return None


def watch_this_control(obj=None, name=''):
    """Watch the object the navigator is on. ``(ok, sentence)``."""
    obj = here(obj)
    if obj is None:
        # Translators: said when there is no control to watch.
        return False, _('There is nothing here to watch.')
    monitor = {'kind': BY_CONTROL, 'program': _program(obj),
               'name': str(name or _describe(obj)),
               'where': _anchor(obj)}
    if not monitor['where']:
        # A control with nothing stable about it cannot be found again, so
        # it is watched by WHERE it is instead - which is weaker, and said
        # to be.
        rect = _rect_of(obj)
        if not rect:
            # Translators: said when a control cannot be watched.
            return False, _('You cannot watch this control')
        monitor['kind'] = BY_POINT
        monitor['point'] = [rect[0] + rect[2] // 2, rect[1] + rect[3] // 2]
    return _add(monitor)


def watch_this_area(obj=None, name=''):
    """Watch the RECTANGLE of the object the navigator is on, with OCR.

    The area half of object navigation. Walk to the panel, the group box,
    the strip along the bottom - and watch what is DRAWN there, which works
    on a part of a window that answers nothing at all, where watching the
    control cannot. Watching the whole window instead would read everything
    that changes anywhere in it, which for a program that also has a clock
    in it is a monitor that never stops talking.
    """
    return _watch_rect(here(obj), name,
                       # Translators: said when a control cannot be watched.
                       _('You cannot watch this control'))


def watch_this_window(obj=None, name=''):
    """Watch the whole window as a RECTANGLE, read with Windows' own OCR.

    The one that works on a program with no accessibility at all, which is
    what JAWS Frames is really for.
    """
    if obj is None:
        try:
            import api
            obj = api.getForegroundObject()
        except Exception:                            # noqa: BLE001
            obj = None
    return _watch_rect(obj, name,
                       # Translators: said when a window cannot be watched.
                       _('That window has no place on the screen.'))


def _watch_rect(obj, name, refusal):
    rect = _rect_of(obj)
    if not rect or rect[2] <= 0 or rect[3] <= 0:
        # A rectangle with no width is not a small area, it is an object
        # that is not on the screen - and an OCR monitor made from one
        # would read a strip of whatever is behind it for ever.
        return False, refusal
    return _add({'kind': BY_AREA, 'program': _program(obj),
                 'name': str(name or _describe(obj)), 'rect': list(rect)})


def _add(monitor):
    with _LOCK:
        monitors = _load()
        for standing in monitors:
            if _key(standing) == _key(monitor):
                # Translators: said when the same thing is watched twice.
                return False, _('Already being watched')
        monitors.append(monitor)
    save()
    _keep_running()
    # Translators: said when a monitor is added. {what} is its name.
    return True, _('Watching {what}').format(what=monitor['name'])


def _key(monitor):
    return json.dumps({name: monitor.get(name)
                       for name in ('kind', 'program', 'where', 'point',
                                    'rect')},
                      sort_keys=True)


def _describe(obj):
    for attribute in ('name', 'windowText'):
        try:
            said = str(getattr(obj, attribute, '') or '').strip()
        except Exception:                            # noqa: BLE001
            said = ''
        if said:
            return said
    # **A control with no name is usually the one worth watching.** A
    # progress bar, a status line, a pane that draws itself: not one of
    # them is named, and calling every one of them "this area" makes the
    # list of watched areas a list of things nobody can tell apart. What it
    # IS is the next best name there is, and it is in the user's own
    # language because it is NVDA's own word for the role.
    try:
        from . import context
        role = str(context.role_name(getattr(obj, 'role', None)) or '').strip()
    except Exception:                                # noqa: BLE001
        role = ''
    if role:
        return role
    try:
        said = str(getattr(obj, 'windowClassName', '') or '').strip()
    except Exception:                                # noqa: BLE001
        said = ''
    if said:
        return said
    # Translators: the name of a monitor whose control has no name.
    return _('this area')


def _anchor(obj):
    """What would still be true about this control next time, or ''.

    The same question `labels` asks, and the same answer: an executable, a
    window class and the control's own ids. Position is deliberately not in
    it - a control that moved would be a different one.
    """
    try:
        from . import labels
        key, strong = labels.key_of(obj)
    except Exception:                                # noqa: BLE001
        return ''
    # **Only a STRONG key.** A weak one is built from where the control sits
    # among its siblings, and it moves the moment a toolbar gains a button -
    # so a monitor made from one would quietly start watching the control
    # next door. Where the control has nothing of its own to be named by,
    # its PLACE is watched instead, and the user is told that is what
    # happened.
    return key if strong else ''


def _rect_of(obj):
    try:
        location = obj.location
        if hasattr(location, 'left'):
            return (int(location.left), int(location.top),
                    int(location.width), int(location.height))
        return tuple(int(value) for value in location)
    except Exception:                                # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Reading one
# --------------------------------------------------------------------------- #
def _read(monitor):
    """What this monitor says right now, or None when it cannot be read.

    None is not empty: a monitor whose window is closed has nothing to say
    and must not be announced as having become blank.
    """
    kind = monitor.get('kind')
    if kind == BY_AREA:
        return _read_area(monitor.get('rect'))
    if kind == BY_POINT:
        return _read_object(_object_at(monitor.get('point')))
    return _read_object(_find_control(monitor))


#: Roles whose news is their CONTENTS, not their own name and value.
#:
#: A list, a tree, a table, a document: watching one of these by asking it
#: for its value answers the same string for ever, because what changes is
#: what is IN it. "Watch this list and tell me when something arrives" is
#: the commonest thing anybody asks a monitor for - a chat, a build log, a
#: queue - and reading the container instead of its rows is a monitor that
#: is never wrong and never says anything.
COLLECTIONS = frozenset({
    'LIST', 'TREEVIEW', 'TABLE', 'DATAGRID', 'DATAITEM', 'DOCUMENT',
    'TERMINAL', 'LISTITEM', 'TREEVIEWITEM',
})

#: How many rows of a collection are read. A monitor is for being told that
#: something arrived, not for reading a thousand-row table out; past this
#: the count is what changes and the count is what is said.
MAX_ROWS = 40


def _read_object(obj):
    if obj is None:
        return None
    role = ''
    try:
        role = str(getattr(getattr(obj, 'role', None), 'name', '') or '')
    except Exception:                                # noqa: BLE001
        role = ''
    if role.upper() in COLLECTIONS:
        rows = _read_rows(obj)
        if rows is not None:
            return rows
    parts = []
    for attribute in ('value', 'name', 'description'):
        try:
            said = str(getattr(obj, attribute, '') or '').strip()
        except Exception:                            # noqa: BLE001
            said = ''
        if said and said not in parts:
            parts.append(said)
    return ', '.join(parts)


def _read_rows(obj):
    """What is IN a list, a tree or a table. ``None`` when it has nothing.

    None rather than '' on purpose: a collection that cannot be walked is
    not a collection that has become empty, and announcing the second when
    it is the first is how a monitor reports a window being rebuilt as
    news.
    """
    try:
        children = list(obj.children or [])
    except Exception:                                # noqa: BLE001
        return None
    if not children:
        return None
    rows = []
    for child in children[:MAX_ROWS]:
        said = ''
        for attribute in ('name', 'value'):
            try:
                said = str(getattr(child, attribute, '') or '').strip()
            except Exception:                        # noqa: BLE001
                said = ''
            if said:
                break
        if said:
            rows.append(said)
    if not rows:
        return None
    if len(children) > MAX_ROWS:
        rows.append('(+%d)' % (len(children) - MAX_ROWS))
    return '\n'.join(rows)


def rows_added(before, now):
    """The rows ``now`` has and ``before`` had not, in order.

    What a watched list should SAY. A chat window that has gained one line
    must not be read out from the top, and a list whose rows were reordered
    is not news at all - which is why this is a set difference on the text
    rather than a comparison of the two lists position by position.
    """
    if not before:
        return [line for line in str(now or '').splitlines() if line.strip()]
    had = {line.strip() for line in str(before).splitlines()}
    return [line for line in str(now or '').splitlines()
            if line.strip() and line.strip() not in had]


def _read_area(rect):
    if not rect or len(rect) != 4:
        return None
    try:
        from . import localOcr
        reading = localOcr.read(int(rect[0]), int(rect[1]),
                                int(rect[2]), int(rect[3]))
    except Exception:                                # noqa: BLE001
        return None
    return reading.text if reading else None


def _object_at(point):
    if not point or len(point) != 2:
        return None
    try:
        import api
        from NVDAObjects import NVDAObject                    # noqa: F401
        return api.getDesktopObject().objectFromPoint(int(point[0]),
                                                      int(point[1]))
    except Exception:                                # noqa: BLE001
        return None


def _find_control(monitor):
    """The control this monitor was made from, if it is on the screen.

    Only inside the program it was made in, and only through NVDA's own
    tree: a monitor that went hunting the whole desktop for a matching
    control would eventually find the wrong one.
    """
    wanted = str(monitor.get('where') or '')
    if not wanted:
        return None
    try:
        import api
        from . import labels
        window = api.getForegroundObject()
    except Exception:                                # noqa: BLE001
        return None
    if window is None:
        return None
    if monitor.get('program') and _program(window) != monitor['program']:
        return None
    seen = 0
    stack = [window]
    while stack and seen < 400:
        obj = stack.pop(0)
        seen += 1
        try:
            if labels.key_of(obj)[0] == wanted:
                return obj
            # **All of them, not the first forty.** The walk is already
            # bounded by `seen`; capping the children was a hole rather
            # than a budget - a control past the fortieth child of its
            # parent could never be found again, so a monitor on the
            # twelfth tray icon or a deep row of a toolbar silently
            # watched nothing for ever. The same bug was in `anchors`,
            # and was found on a real taskbar.
            stack.extend(list(obj.children or []))
        except Exception:                            # noqa: BLE001
            continue
    return None


# --------------------------------------------------------------------------- #
# Watching
# --------------------------------------------------------------------------- #
def wanted():
    from . import configSpec
    return bool(configSpec.read().get('monitors', True))


def _keep_running():
    """Start the watch when there is something to watch, stop it when not.

    A thread polling nothing is a thread reading the screen for no reason,
    and this one can reach Windows' OCR - which is not something to do on a
    timer nobody asked for.
    """
    global _thread, _stop
    should = bool(_load()) and wanted()
    with _LOCK:
        running = _thread is not None and _thread.is_alive()
    if should and not running:
        start()
    elif not should and running:
        stop()


def start():
    global _thread, _stop
    with _LOCK:
        if _thread is not None and _thread.is_alive():
            return False
        _stop = threading.Event()
        _thread = threading.Thread(target=_watch, args=(_stop,),
                                   name='TitanMonitors', daemon=True)
        _thread.start()
    return True


def stop():
    global _thread, _stop
    with _LOCK:
        standing = _stop
        _thread = None
        _stop = None
    if standing is not None:
        standing.set()
        return True
    return False


def _watch(stop_event):
    interval = POLL
    busy = 0
    while not stop_event.wait(interval):
        if not wanted():
            break
        changed = check()
        with _LOCK:
            _state['checks'] += 1
        if changed:
            busy += 1
            if busy >= BUSY_ENOUGH and interval == POLL:
                interval = SLOW_POLL
                _say(_('Watched less often, this keeps changing'))
        else:
            busy = 0
            interval = POLL


def check():
    """One pass over every monitor. Answers whether anything was said."""
    said = False
    for monitor in list(_load()):
        key = _key(monitor)
        now = _read(monitor)
        if now is None:
            continue                                 # not on the screen
        with _LOCK:
            before = _seen.get(key)
            _seen[key] = now
        if before is None or now == before:
            continue
        if not str(now).strip():
            # Something that has become empty is usually a window that is
            # being rebuilt, not news.
            continue
        _announce(monitor, now, before)
        said = True
    return said


def _announce(monitor, now, before=None):
    """Say what changed - and for a list, only what ARRIVED.

    A chat window, a build log, a queue: the whole point of watching one is
    to be told that a line came in, and reading it out from the top every
    time would be a monitor nobody keeps on. A list whose rows were merely
    reordered has gained nothing and says nothing.
    """
    with _LOCK:
        _state['said'] += 1
    text = now
    if '\n' in str(now or ''):
        arrived = rows_added(before, now)
        if not arrived:
            with _LOCK:
                _state['said'] -= 1
            return
        text = ', '.join(arrived[:MAX_NEW])
    # Translators: a monitored area has changed. {what} is its name, {text}
    # what it says now.
    _say(_('{what}: {text}').format(what=monitor.get('name') or '',
                                    text=_shorten(text)))


#: How many new rows of a watched list are said. A list that has been
#: replaced wholesale would otherwise be read out, which is the thing the
#: difference exists to avoid.
MAX_NEW = 5


#: How much of a changed area is said. A monitor that has become a page of
#: text is not something to read out at somebody who is doing something
#: else; the point is to be told it changed and roughly how.
MAX_SAID = 300


def _shorten(text):
    said = ' '.join(str(text or '').split())
    return said if len(said) <= MAX_SAID else said[:MAX_SAID] + '...'


def _say(text):
    """Queued, never interrupting. A reader that talks over you is one you
    switch off, and none of this is the thing the user is doing."""
    from . import compat
    if compat.queueHandler is None or compat.speech is None:
        return

    def speak():
        try:
            compat.speech.speakMessage(str(text))
        except Exception:                            # noqa: BLE001
            pass
    compat.queueHandler.queueFunction(compat.queueHandler.eventQueue, speak)

# -*- coding: utf-8 -*-
"""Record what you did to a program, and do it again - by CONTROL, not by key.

This is the one that goes past JAWS, and the reason is not cleverness: it is
that a recorded keystroke is the wrong unit.

Every reader's answer to "I do this every Monday" is a script or a macro,
and every one of them records **keys**: Tab, Tab, Tab, Down, Space, Alt+S.
That works until the dialog gains a checkbox, the window opens at a
different size, a control is slow to appear, or the user has a different
theme - and then it does the wrong thing silently, which for somebody who
cannot see the screen is the worst possible failure. JAWS' answer to that is
to write a script in a programming language, which is why almost nobody
does.

A step here is not a key. It is **a control and what happened to it**, and
the control is remembered by :mod:`anchors` - what will still be true about
it the next time the program is opened. So:

* **Replay finds the control before it touches it.** If it is not there,
  the procedure stops and says which step and why. It never presses "the
  third thing after where I am now" and hopes.
* **A recording is readable.** It is a list of sentences - "go to Search",
  "type the text", "press Save" - so it can be checked, corrected and
  handed to somebody else. A keystroke macro can only be re-recorded.
* **It survives the window changing**, which is the entire point: a dialog
  that gains a control breaks every keystroke macro ever recorded of it and
  does not break this.

**Nothing is recorded unless asked for, and nothing is replayed silently.**
Recording is a command the user gives; replaying says every step as it goes,
stops at the first one it cannot do, and never carries on past a step that
did not happen.
"""

import json
import os
import threading
import time

from . import anchors
from . import i18n

_ = i18n.install(globals())

FILENAME = 'titanProcedures.json'

#: What a step can be.
GO = 'go'                 # move to a control
PRESS = 'press'           # do its own default action
TYPE = 'type'             # put text into it
KEY = 'key'               # send a key, for what has no control of its own
WAIT = 'wait'             # for a control to appear
STEPS = (GO, PRESS, TYPE, KEY, WAIT)

#: How long a step waits for its control to turn up. A dialog that is
#: still opening is the ordinary case, and failing on it would make the
#: whole feature unreliable in exactly the situation it is for.
APPEAR_SECONDS = 5.0

#: How long a whole procedure may take. A runaway is stopped rather than
#: left pressing things.
RUN_SECONDS = 60.0

_LOCK = threading.RLock()
_saved = None
_recording = {'on': False, 'name': '', 'steps': [], 'program': ''}
_state = {'ran': 0, 'failed': 0, 'why': ''}


def report():
    with _LOCK:
        return dict(_state, recording=_recording['on'],
                    steps=len(_recording['steps']),
                    saved=len(_load()))


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
    global _saved
    with _LOCK:
        if _saved is not None:
            return _saved
        _saved = []
        where = path()
        if where and os.path.isfile(where):
            try:
                with open(where, encoding='utf-8') as handle:
                    data = json.load(handle)
                if isinstance(data, list):
                    _saved = [row for row in data if isinstance(row, dict)
                              and row.get('name') and row.get('steps')]
            except Exception:                        # noqa: BLE001
                _saved = []
        return _saved


def forget():
    global _saved
    with _LOCK:
        _saved = None


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


def all_procedures():
    return list(_load())


def for_program(program=None):
    if program is None:
        program = anchors.program_of()
    return [row for row in _load() if (row.get('program') or '') == program]


def remove(procedure):
    with _LOCK:
        saved = _load()
        for at, row in enumerate(saved):
            if row is procedure or row == procedure:
                saved.pop(at)
                break
        else:
            return False
    return save()


def rename(procedure, name):
    said = str(name or '').strip()
    if not said:
        return False
    with _LOCK:
        for row in _load():
            if row is procedure or row == procedure:
                row['name'] = said
                break
        else:
            return False
    return save()


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #
def recording():
    with _LOCK:
        return bool(_recording['on'])


def start_recording(name=''):
    with _LOCK:
        if _recording['on']:
            # Translators: said when a recording is already running.
            return False, _('Already recording')
        _recording.update({'on': True, 'name': str(name or ''), 'steps': [],
                           'program': anchors.program_of()})
    # Translators: said when recording a procedure starts.
    return True, _('Recording on')


def stop_recording(name=''):
    """Keep what was recorded. ``(ok, sentence)``."""
    with _LOCK:
        if not _recording['on']:
            # Translators: said when nothing is being recorded.
            return False, _('Nothing is being recorded')
        steps = list(_recording['steps'])
        said = str(name or _recording['name'] or '')
        program = _recording['program']
        _recording.update({'on': False, 'name': '', 'steps': [],
                           'program': ''})
    if not steps:
        # Translators: said when a recording had no steps in it.
        return False, _('Nothing was recorded')
    if not said:
        # Translators: the default name of a recorded procedure. {n} is how
        # many steps it has.
        said = _('Procedure of {n} steps').format(n=len(steps))
    with _LOCK:
        _load().append({'name': said, 'program': program, 'steps': steps})
    save()
    # Translators: said when a procedure is kept. {what} is its name, {n}
    # how many steps.
    return True, _('Kept {what}, {n} steps').format(what=said, n=len(steps))


def cancel_recording():
    with _LOCK:
        was = _recording['on']
        _recording.update({'on': False, 'name': '', 'steps': [],
                           'program': ''})
    # Translators: said when a recording is thrown away.
    return was, _('Recording thrown away')


def _add(step):
    with _LOCK:
        if not _recording['on']:
            return False
        _recording['steps'].append(step)
        return True


def note_focus(obj):
    """The user moved to a control. One step, and never two in a row.

    Moving through a dialog with Tab produces a step per control passed
    THROUGH, and a procedure that visited every one of them would be a
    keystroke macro wearing a different hat. Only the last control of a run
    matters - it is the one they stopped on - so a `go` step replaces the
    `go` step before it.
    """
    if not recording() or obj is None:
        return False
    anchor = anchors.anchor_for(obj)
    if anchor is None:
        return False
    step = {'do': GO, 'anchor': anchor, 'what': anchors.describe(obj)}
    with _LOCK:
        steps = _recording['steps']
        if steps and steps[-1]['do'] == GO:
            steps[-1] = step
            return True
    return _add(step)


def note_press(obj=None):
    """The user did something to the control they are on.

    **The press carries its OWN anchor**, not just the `go` step before it.
    A press with no anchor is "do whatever has the focus", which on replay
    is exactly the blind action this whole module exists not to be: the
    focus at that moment is wherever the previous step left it, and if that
    step went somewhere unexpected the press lands on the wrong control
    without anything noticing.
    """
    if not recording():
        return False
    if obj is None:
        try:
            import api
            obj = api.getFocusObject()
        except Exception:                            # noqa: BLE001
            obj = None
    note_focus(obj)
    step = {'do': PRESS, 'what': anchors.describe(obj) if obj else ''}
    anchor = anchors.anchor_for(obj) if obj is not None else None
    if anchor is not None:
        step['anchor'] = anchor
    return _add(step)


def note_typing(text):
    if not recording():
        return False
    said = str(text or '')
    if not said:
        return False
    with _LOCK:
        steps = _recording['steps']
        if steps and steps[-1]['do'] == TYPE:
            # One run of typing is one step, not a step per letter.
            steps[-1]['text'] += said
            return True
    return _add({'do': TYPE, 'text': said})


def note_key(name):
    if not recording():
        return False
    return _add({'do': KEY, 'key': str(name or '')})


# --------------------------------------------------------------------------- #
# What a step says
# --------------------------------------------------------------------------- #
def said(step):
    """One step as a sentence, which is what makes a recording checkable."""
    kind = step.get('do')
    if kind == GO:
        # Translators: a step of a procedure. {what} is a control.
        return _('go to {what}').format(what=step.get('what') or '')
    if kind == PRESS:
        # Translators: a step of a procedure. {what} is a control.
        return _('press {what}').format(what=step.get('what') or '')
    if kind == TYPE:
        # Translators: a step of a procedure. {text} is what is typed.
        return _('type "{text}"').format(text=step.get('text') or '')
    if kind == KEY:
        # Translators: a step of a procedure. {key} is a key.
        return _('press the key {key}').format(key=step.get('key') or '')
    if kind == WAIT:
        # Translators: a step of a procedure. {what} is a control.
        return _('wait for {what}').format(what=step.get('what') or '')
    return str(kind or '')


def as_text(procedure):
    return '\n'.join('%d. %s' % (at + 1, said(step))
                     for at, step in enumerate(procedure.get('steps') or []))


# --------------------------------------------------------------------------- #
# Doing it again
# --------------------------------------------------------------------------- #
def _find(anchor, seconds=None):
    """The control, waiting a little for it to turn up.

    A dialog that is still opening is the ordinary case, and failing on it
    would make the whole feature unreliable in exactly the situation it is
    for.

    ``APPEAR_SECONDS`` is read HERE and not as a default argument: a default
    is bound when the function is defined, so changing the module's value -
    which is what a test and a future setting both do - would change
    nothing and the wait would silently stay what it was.
    """
    if seconds is None:
        seconds = APPEAR_SECONDS
    until = time.time() + max(0.0, seconds)
    while True:
        obj = anchors.find(anchor)
        if obj is not None:
            return obj
        if time.time() >= until:
            return None
        time.sleep(0.2)


def run(procedure, say=None):
    """Do it again. ``(ok, sentence)``.

    **It stops at the first step it cannot do**, and says which one and why.
    That is the whole safety of the thing: a procedure that carried on past
    a step that did not happen would be pressing controls in a state nobody
    predicted, which for somebody who cannot see the screen is the failure
    that matters.
    """
    steps = list((procedure or {}).get('steps') or [])
    if not steps:
        # Translators: said when a procedure has no steps.
        return False, _('There is nothing in that procedure')
    if say is None:
        def say(_text):
            return None
    started = time.time()
    here = None
    for at, step in enumerate(steps, start=1):
        if time.time() - started > RUN_SECONDS:
            with _LOCK:
                _state['failed'] += 1
            # Translators: said when a procedure took too long. {n} is the
            # step it had reached.
            return False, _('It is taking too long; stopped at step {n}'
                            ).format(n=at)
        say(_('{n}. {what}').format(n=at, what=said(step)))
        ok, why = _do(step, at)
        if not ok:
            with _LOCK:
                _state['failed'] += 1
                _state['why'] = why
            return False, why
        here = step
    with _LOCK:
        _state['ran'] += 1
    # Translators: said when a procedure has finished. {what} is its name.
    return True, _('{what}: done').format(what=procedure.get('name') or '')


def _do(step, at):
    kind = step.get('do')
    if kind in (GO, WAIT, PRESS) and step.get('anchor'):
        obj = _find(step['anchor'])
        if obj is None:
            # Translators: said when a step's control is not there. {n} is
            # the step's number, {what} the control.
            return False, _('Step {n}: {what} is not there').format(
                n=at, what=step.get('what') or '')
        if kind in (GO, WAIT):
            try:
                obj.setFocus()
            except Exception:                        # noqa: BLE001
                try:
                    import api
                    api.setNavigatorObject(obj)
                except Exception:                    # noqa: BLE001
                    pass
            return True, ''
        return _press(obj, at)
    if kind == PRESS:
        # A press with no anchor is one recorded before this carried them,
        # or one of a control that had nothing stable about it. It is the
        # weaker case and it is done rather than refused - but the step
        # before it was a `go` to a control that WAS found, so the focus is
        # where the recording left it and not wherever the user happens to
        # be.
        try:
            import api
            return _press(api.getFocusObject(), at)
        except Exception:                            # noqa: BLE001
            # Translators: said when a step could not be done. {n} is the
            # step's number.
            return False, _('Step {n} could not be done').format(n=at)
    if kind == TYPE:
        return _type(step.get('text') or '', at)
    if kind == KEY:
        return _key(step.get('key') or '', at)
    return True, ''


def _press(obj, at):
    """The control's OWN default action, never a synthesised click.

    A click at a coordinate is what a keystroke macro degrades into, and it
    is exactly what this exists not to be: the control says what pressing it
    means, and if it says nothing then Enter is sent to it, which is what a
    person would have done.
    """
    if obj is None:
        return False, _('Step {n} could not be done').format(n=at)
    try:
        if int(getattr(obj, 'actionCount', 0) or 0) > 0:
            obj.doAction(0)
            return True, ''
    except Exception:                                # noqa: BLE001
        pass
    return _key('enter', at)


def _type(text, at):
    try:
        import keyboardHandler
        for character in str(text):
            keyboardHandler.KeyboardInputGesture.fromName(
                character if character != ' ' else 'space').send()
        return True, ''
    except Exception:                                # noqa: BLE001
        # Translators: said when a step could not type. {n} is the step.
        return False, _('Step {n}: the text could not be typed').format(n=at)


def _key(name, at):
    try:
        import keyboardHandler
        keyboardHandler.KeyboardInputGesture.fromName(str(name)).send()
        return True, ''
    except Exception:                                # noqa: BLE001
        # Translators: said when a step's key could not be sent. {n} is the
        # step, {key} the key.
        return False, _('Step {n}: the key {key} could not be sent').format(
            n=at, key=name)

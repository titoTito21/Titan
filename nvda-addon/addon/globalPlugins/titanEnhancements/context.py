# -*- coding: utf-8 -*-
"""What NVDA can see right now, so Titan's subsystems are about THIS.

Titan's AI OCR, its assistant and its agent all had the same gap: they act
on "the window", and the window they meant was whatever Windows called the
foreground - which on a machine being read by NVDA is very often not what
the user is actually working in. NVDA knows precisely: it has the focused
object, the navigator object, the review cursor, whether the user is in
browse mode and what is selected. That is the context, and Titan cannot
work it out for itself because it is not the reader.

So this is the other half of the channel. Titan announces INTO NVDA; NVDA
answers what it can see, and every Titan subsystem the user reaches from
here is handed it. "Read this window" reads the window NVDA is in. "Ask
Titan about this" asks about the control the user is on, by name and role,
in the application they are in.

Three rules:

* **It is read on NVDA's own thread.** Every property of an NVDA object is
  a call into UI Automation or MSAA, and those belong to the thread whose
  COM apartment NVDA set up. Read from the bus thread they are anything
  from wrong to a hang, so this marshals and waits - the ONE place in this
  add-on that waits, and it waits with a deadline, because Titan is on the
  other end of a pipe.
* **Nothing here changes anything.** Reading what is on the screen and
  acting on it are different permissions (see :mod:`nvda_control`), and
  this side is always served: it is what makes the bridge answerable at
  all, and it is the user's own screen being described to their own
  desktop.
* **What cannot be read is absent, never invented.** A control with no name
  has no name; a review cursor that is nowhere answers nothing. Titan's
  describers say "the control has no name", which is true and useful, where
  a guessed one is neither.
"""

import threading

from . import compat

#: How long the bus thread will wait for NVDA's own thread. Measured
#: against a live NVDA: once warm this answers in 0.06 s, but the FIRST
#: call after NVDA has started took longer than two seconds and came back
#: as "NVDA was busy", which reads as a broken bridge rather than as a
#: reader that has only just got up. Titan waits six seconds for this, so
#: four leaves room to answer inside it.
MAIN_THREAD_WAIT = 4.0

#: Read at most this much of a selection or a document. A whole page belongs
#: in AI OCR or in Titan's own document reading, not in a context blob.
TEXT_LIMIT = 4000


def _on_main(function, timeout=MAIN_THREAD_WAIT):
    """Run ``function`` on NVDA's thread and bring back what it answered."""
    if compat.queueHandler is None:
        return function()
    done = threading.Event()
    box = [None, None]

    def run():
        try:
            box[0] = function()
        except Exception as error:                   # noqa: BLE001
            box[1] = error
        finally:
            done.set()
    compat.queueHandler.queueFunction(compat.queueHandler.eventQueue, run)
    if not done.wait(timeout):
        raise TimeoutError('NVDA did not answer in time')
    if box[1] is not None:
        raise box[1]
    return box[0]


# --------------------------------------------------------------------------- #
# Words for what NVDA holds as numbers
# --------------------------------------------------------------------------- #
def role_name(role):
    """The role in the user's own language, or its bare name, or ''.

    NVDA has spelled this three ways across the versions it supports -
    ``Role.displayString``, ``roleLabels[role]``, and the enum's name - so
    all three are tried rather than one being assumed and the whole context
    coming back without a single role in it.
    """
    if role is None:
        return ''
    display = getattr(role, 'displayString', None)
    if isinstance(display, str) and display:
        return display
    types = compat.controlTypes
    if types is not None:
        labels = getattr(types, 'roleLabels', None)
        if labels:
            try:
                return str(labels[role])
            except Exception:                        # noqa: BLE001
                pass
    return str(getattr(role, 'name', '') or role or '')


def state_names(states):
    """Every state as a word. An unnamed state is left out, not numbered."""
    out = []
    for state in states or ():
        display = getattr(state, 'displayString', None)
        if isinstance(display, str) and display:
            out.append(display)
            continue
        types = compat.controlTypes
        labels = getattr(types, 'stateLabels', None) if types else None
        if labels:
            try:
                out.append(str(labels[state]))
                continue
            except Exception:                        # noqa: BLE001
                pass
        name = getattr(state, 'name', '')
        if name:
            out.append(str(name).lower())
    return out


# --------------------------------------------------------------------------- #
# One object
# --------------------------------------------------------------------------- #
def describe(obj):
    """One NVDA object as plain data. ``{}`` for nothing."""
    if obj is None:
        return {}
    described = {}

    def read(key, getter):
        try:
            value = getter()
        except Exception:                            # noqa: BLE001
            return
        if value is None or value == '' or value == []:
            return
        described[key] = value

    read('name', lambda: str(obj.name or ''))
    read('role', lambda: role_name(obj.role))
    read('states', lambda: state_names(obj.states))
    read('value', lambda: str(obj.value or '')[:TEXT_LIMIT])
    read('description', lambda: str(obj.description or '')[:TEXT_LIMIT])
    read('keyboard_shortcut', lambda: str(obj.keyboardShortcut or ''))
    read('app', lambda: str(obj.appModule.appName or ''))
    read('window', lambda: str(obj.windowText or ''))
    read('class', lambda: str(obj.windowClassName or ''))
    read('hwnd', lambda: int(obj.windowHandle or 0))
    read('process', lambda: int(obj.processID or 0))
    read('automation_id', lambda: str(getattr(obj, 'UIAAutomationId', '') or ''))

    try:
        position = obj.positionInfo or {}
    except Exception:                                # noqa: BLE001
        position = {}
    if position.get('indexInGroup'):
        described['index'] = int(position['indexInGroup'])
    if position.get('similarItemsInGroup'):
        described['count'] = int(position['similarItemsInGroup'])
    if position.get('level'):
        described['level'] = int(position['level'])
    return described


def _text_of(obj, position):
    info = obj.makeTextInfo(position)
    return str(info.text or '')[:TEXT_LIMIT]


def _selection(obj):
    if compat.textInfos is None or obj is None:
        return ''
    try:
        return _text_of(obj, compat.textInfos.POSITION_SELECTION)
    except Exception:                                # noqa: BLE001
        return ''


def _review_line():
    if compat.api is None or compat.textInfos is None:
        return ''
    try:
        info = compat.api.getReviewPosition().copy()
        info.expand(compat.textInfos.UNIT_LINE)
        return str(info.text or '')[:TEXT_LIMIT]
    except Exception:                                # noqa: BLE001
        return ''


def _mode(obj):
    """'browse', 'focus' or ''. The one thing about NVDA a caller must know
    before it presses anything: in browse mode a key is the reader's."""
    try:
        interceptor = obj.treeInterceptor
    except Exception:                                # noqa: BLE001
        return ''
    if interceptor is None:
        return ''
    try:
        return 'focus' if interceptor.passThrough else 'browse'
    except Exception:                                # noqa: BLE001
        return ''


# --------------------------------------------------------------------------- #
# The whole of it
# --------------------------------------------------------------------------- #
def _gather(want_text=True):
    api = compat.api
    if api is None:
        return {'reader': 'nvda', 'available': False,
                'why': 'this NVDA does not expose its api module'}
    focus = None
    try:
        focus = api.getFocusObject()
    except Exception:                                # noqa: BLE001
        focus = None
    try:
        navigator = api.getNavigatorObject()
    except Exception:                                # noqa: BLE001
        navigator = None
    try:
        foreground = api.getForegroundObject()
    except Exception:                                # noqa: BLE001
        foreground = None

    state = {'reader': 'nvda', 'available': True,
             'focus': describe(focus)}
    if navigator is not None and navigator is not focus:
        state['navigator'] = describe(navigator)
    if foreground is not None and foreground is not focus:
        state['foreground'] = describe(foreground)
    mode = _mode(focus)
    if mode:
        state['mode'] = mode
    if want_text:
        selection = _selection(focus)
        if selection:
            state['selection'] = selection
        review = _review_line()
        if review:
            state['review'] = review
    synth = None
    try:
        from . import panner
        synth = panner.current_synth()
    except Exception:                                # noqa: BLE001
        synth = None
    if synth is not None:
        state['synth'] = str(getattr(synth, 'name', '') or '')
    return state


def read(text=True, **_):
    """The bus handler: what NVDA can see, as data.

    Answers a shape rather than a sentence, for the reason Titan's own
    bridge gives: every live bug in this repository's other bridge came
    from a client splitting up a sentence written for a person.
    """
    try:
        return _on_main(lambda: _gather(bool(text)))
    except TimeoutError:
        return {'reader': 'nvda', 'available': False,
                'why': 'NVDA was busy and did not answer in time'}
    except Exception as error:                       # noqa: BLE001
        return {'reader': 'nvda', 'available': False, 'why': str(error)}


def window(**_):
    """Just the window, for the callers that only want somewhere to point.

    AI OCR wants an HWND and nothing else, and asking for the whole context
    to get one is a UIA walk nobody needed.
    """
    def gather():
        api = compat.api
        if api is None:
            return {}
        obj = None
        try:
            obj = api.getForegroundObject()
        except Exception:                            # noqa: BLE001
            return {}
        described = describe(obj)
        return {'hwnd': described.get('hwnd', 0),
                'title': described.get('name', ''),
                'app': described.get('app', ''),
                'process': described.get('process', 0)}
    try:
        return _on_main(gather)
    except Exception:                                # noqa: BLE001
        return {}


def sentence(state=None):
    """The context as one line, for a caller that wants to put it in a prompt.

    Built here rather than in Titan because the words for a role and a state
    are NVDA's own, in the user's own language, and Titan translating its
    own would be a second vocabulary for the same screen.
    """
    state = read() if state is None else state
    if not state.get('available'):
        return ''
    focus = state.get('focus') or {}
    parts = []
    if focus.get('app'):
        parts.append('In {}'.format(focus['app']))
    if focus.get('window'):
        parts.append('window "{}"'.format(focus['window']))
    named = focus.get('name') or ''
    role = focus.get('role') or ''
    if named or role:
        parts.append('the focus is on "{}" ({})'.format(named, role)
                     if named and role else 'the focus is on {}'
                     .format(named or role))
    if focus.get('states'):
        parts.append('which is ' + ', '.join(focus['states']))
    if focus.get('index') and focus.get('count'):
        parts.append('{} of {}'.format(focus['index'], focus['count']))
    if state.get('mode') == 'browse':
        parts.append('NVDA is in browse mode')
    if state.get('selection'):
        parts.append('the selected text is "{}"'.format(state['selection']))
    elif state.get('review'):
        parts.append('the review cursor is on "{}"'.format(state['review']))
    return '. '.join(parts) + '.' if parts else ''

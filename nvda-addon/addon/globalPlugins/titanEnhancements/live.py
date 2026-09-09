# -*- coding: utf-8 -*-
"""What changed while the user was looking somewhere else.

A status bar that says "connecting", a progress that reaches a hundred, a
transcript that gains a line: every one of them happens with the focus
somewhere else entirely, and a reader that only ever speaks about the
focused control never mentions any of it. The web solved this years ago -
``aria-live`` - and the desktop never did.

JAWS's answer is Frames: the user draws a rectangle on the screen and JAWS
POLLS it, comparing pixels or text, and reads out what changed. It works,
and it costs a screen scrape several times a second, per frame, for ever.

This does not poll. Windows already sends an event when a control's name or
value changes - it is how NVDA knows a progress bar has moved - and NVDA
already delivers those events to add-ons. So a live region here is a RULE
saying which control's changes are worth hearing, and the cost of one that
never changes is nothing at all.

Three ways a region becomes live, in order of how much is known:

* **A reader module says so.** ``{'match': {'role': 'STATUSBAR'},
  'politeness': 'polite'}`` - written once, for that application, by
  somebody who has read it.
* **Titan says so**, over the bus, for its own windows and for anything
  another client wants announced. That is a push, so it needs no rule and
  no event at all.
* **The generic floor**: the status bar of the window the user is actually
  in. Almost every program has one and almost every program uses it for
  exactly this. Behind its own switch, because a program that writes the
  mouse position into its status bar would otherwise never stop talking.

**Politeness is NVDA's own priority**, not a queue of ours: 'polite' waits
for whatever is being said, 'assertive' interrupts. And nothing is ever
said twice - a status bar that is rewritten with the same text on every
timer tick is the commonest thing in Windows, and a reader that read it
each time would be unusable.
"""

import threading
import time

from . import compat

#: The same text again is not news. Long enough to cover a control that
#: rewrites itself on a timer, short enough that a genuinely repeated
#: message ("saved", then "saved") is still heard the second time.
SAME_WITHIN = 4.0

#: At most this many live announcements a second, whatever asks. A progress
#: bar changes its value hundreds of times, and the answer to that is not to
#: read it hundreds of times.
PER_SECOND = 2.0

#: A live region says a line, not a document.
MAX_LENGTH = 300

_LOCK = threading.RLock()
_last = {}
_at = 0.0
_said = 0
_dropped = 0


def report():
    with _LOCK:
        return {'said': _said, 'dropped': _dropped, 'watched': len(_last)}


def forget():
    global _at, _said, _dropped
    with _LOCK:
        _last.clear()
        _at = 0.0
        _said = 0
        _dropped = 0


def wanted():
    from . import configSpec
    return bool(configSpec.read().get('liveRegions', True))


def status_bars_wanted():
    from . import configSpec
    return bool(configSpec.read().get('liveStatusBars', True))


def _text(value):
    return str(value or '').strip()


def _role(obj):
    return _text(getattr(getattr(obj, 'role', None), 'name', '')).upper()


def _key_of(obj):
    try:
        handle = int(getattr(obj, 'windowHandle', 0) or 0)
    except (TypeError, ValueError):
        handle = 0
    return (handle, _role(obj), _text(getattr(obj, 'UIAAutomationId', '')))


def _in_foreground(obj):
    """Whether this control is in the window the user is actually in.

    A background program rewriting its status bar is not news; the same
    program in front of the user is. This is the whole of what keeps the
    generic floor quiet on a busy machine.
    """
    api = compat.api
    if api is None:
        return True
    try:
        foreground = api.getForegroundObject()
        if foreground is None:
            return True
        return int(getattr(foreground, 'processID', 0) or 0) == \
            int(getattr(obj, 'processID', 0) or 0)
    except Exception:                                # noqa: BLE001
        return True


def rule_for(obj, module=None, application=None):
    """The live rule for this control, or None.

    A module's rule first, because it was written by somebody who read the
    program; the status-bar floor second, and only for the window in front.
    """
    if module is not None:
        try:
            found = module.live_rule(obj, application)
        except Exception:                            # noqa: BLE001
            found = None
        if found is not None:
            return found
    if status_bars_wanted() and _role(obj) == 'STATUSBAR' \
            and _in_foreground(obj):
        return {'match': {}, 'politeness': 'polite'}
    return None


def _allowed_now():
    """The rate limit, asked once per announcement."""
    global _at, _dropped
    now = time.time()
    with _LOCK:
        if now - _at < (1.0 / PER_SECOND):
            _dropped += 1
            return False
        _at = now
        return True


def _fresh(key, text):
    now = time.time()
    with _LOCK:
        was = _last.get(key)
        if was and was[0] == text and (now - was[1]) < SAME_WITHIN:
            return False
        if len(_last) > 128:
            _last.clear()
        _last[key] = (text, now)
        return True


def announce(text, politeness='polite', prefix=''):
    """Say a live update. ``False`` when it was dropped, and why is counted.

    'polite' is queued behind whatever is being said and 'assertive'
    interrupts it - NVDA's own two priorities, which is the distinction
    Titan Access had to build a whole utterance queue to get.
    """
    global _said
    said = _text(text)[:MAX_LENGTH]
    if not said or not wanted():
        return False
    if prefix:
        said = '%s: %s' % (_text(prefix), said)
    speech = compat.speech
    if speech is None:
        return False

    def speak():
        try:
            priority = None
            try:
                from speech.priorities import SpeechPriority
                priority = SpeechPriority.NOW if politeness == 'assertive' \
                    else SpeechPriority.NORMAL
            except Exception:                        # noqa: BLE001
                priority = None
            if priority is None:
                speech.speakMessage(said)
            else:
                speech.speakMessage(said, priority=priority)
        except Exception:                            # noqa: BLE001
            try:
                speech.speakMessage(said)
            except Exception:                        # noqa: BLE001
                pass
    if compat.queueHandler is None:
        speak()
    else:
        compat.queueHandler.queueFunction(compat.queueHandler.eventQueue,
                                          speak)
    with _LOCK:
        _said += 1
    return True


def changed(obj, module=None, application=None):
    """A control's name or value has changed. Say it if it is a live region.

    Called from NVDA's own ``event_nameChange`` / ``event_valueChange``, so
    the cost of a program that never changes anything is zero and the cost
    of one that changes something is one dictionary lookup.
    """
    if obj is None or not wanted():
        return False
    rule = rule_for(obj, module, application)
    if rule is None:
        return False
    said = _text(getattr(obj, 'name', ''))
    try:
        value = _text(obj.value)
    except Exception:                                # noqa: BLE001
        value = ''
    if value and value != said:
        said = '%s %s' % (said, value) if said else value
    say = _text(rule.get('say'))
    if say:
        said = say
    if not said:
        return False
    if not _fresh(_key_of(obj), said):
        return False
    if not _allowed_now():
        return False
    return announce(said, rule.get('politeness', 'polite'),
                    rule.get('prefix', ''))


def pushed(text='', politeness='polite', source='', **_):
    """Titan (or any client) saying something changed. The bus handler.

    No rule, no event, no window: a program that KNOWS it has news says so.
    This is the half a reader cannot do for itself, and it is why a
    cooperating desktop can be better than any amount of watching.
    """
    said = _text(text)
    if not said:
        return {'said': False, 'why': 'there is nothing to say'}
    if not wanted():
        return {'said': False, 'why': 'live regions are switched off'}
    if not _fresh(('push', _text(source)), said):
        return {'said': False, 'why': 'that was just said'}
    ok = announce(said, politeness if politeness in ('polite', 'assertive')
                  else 'polite', _text(source))
    return {'said': bool(ok)}

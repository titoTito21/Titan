# -*- coding: utf-8 -*-
"""Everything the reader said, and the way back to what said it.

A screen reader speaks and it is gone. Every reader has some kind of speech
history - NVDA has an add-on for it, JAWS has a buffer - and all of them
answer the same small question: *what did it just say?* None of them answers
the question people actually have, which is **"where was that?"**

An error went past while you were typing. A status line said something and
the next control overwrote it. A list said "3 of 40" and you want the row it
was talking about. In every reader alive the answer is to go and look for it
again, because the words were stored and the thing that said them was not.

So this stores both. Each line carries:

* the **words**, and when,
* **what kind** of speech it was - a control, keyboard echo, a message, the
  controller (:mod:`origin` knows, because NVDA knows while it is still in
  the function that produced it),
* the **program** it happened in,
* and an **anchor** (:mod:`anchors`) - what will still be true about the
  control it was about - so the reader can go back there.

That last one is the whole idea, and it is only possible because this add-on
already had to solve "remember a control" for the place markers.

**It costs almost nothing and it never grows without bound.** A line is a
few strings appended to a deque with a ceiling; the anchor is worked out
from the focus that is already in hand. Nothing is written to disk unless
the user asks for it - a log of everything a person's reader said is not a
file to leave lying about without being told to.
"""

import threading
import time
from collections import deque

from . import anchors
from . import i18n

_ = i18n.install(globals())

#: How many lines are kept. Enough for a morning's work; small enough that
#: the whole thing is a few hundred kilobytes at worst.
KEPT = 500

_LOCK = threading.RLock()
_lines = deque(maxlen=KEPT)
_state = {'kept': 0, 'dropped': 0}


def report():
    with _LOCK:
        return dict(_state, lines=len(_lines))


def wanted():
    from . import configSpec
    return bool(configSpec.read().get('journal', True))


def forget():
    with _LOCK:
        _lines.clear()
        _state['kept'] = 0
        _state['dropped'] = 0


def note(text, kind='', obj=None):
    """One thing the reader said. Never raises; never blocks.

    Called from the speech filter, which runs on NVDA's main thread on the
    way to the synthesizer - so everything here is a string, a deque and a
    dictionary, and the anchor is only worked out for the FOCUS, which NVDA
    has already built.
    """
    if not wanted():
        return False
    said = ' '.join(str(text or '').split())
    if not said:
        return False
    with _LOCK:
        if _lines and _lines[-1]['text'] == said:
            # The same line twice running is a reader repeating itself -
            # a list that re-announced, a status bar rewritten on a timer -
            # and it is not two things that happened.
            _state['dropped'] += 1
            return False
    row = {'text': said, 'at': time.time(), 'kind': str(kind or ''),
           'program': '', 'anchor': None, 'where': ''}
    try:
        if obj is None:
            import api
            obj = api.getFocusObject()
        row['program'] = anchors.program_of(obj)
        row['anchor'] = anchors.anchor_for(obj)
        row['where'] = anchors.describe(obj)
    except Exception:                                # noqa: BLE001
        pass
    with _LOCK:
        if len(_lines) == _lines.maxlen:
            _state['dropped'] += 1
        _lines.append(row)
        _state['kept'] += 1
    return True


def lines(program=None, kind='', containing=''):
    """The journal, newest first, narrowed by whatever was asked for."""
    needle = str(containing or '').strip().lower()
    with _LOCK:
        rows = list(_lines)
    rows.reverse()
    out = []
    for row in rows:
        if program is not None and row['program'] != program:
            continue
        if kind and row['kind'] != kind:
            continue
        if needle and needle not in row['text'].lower():
            continue
        out.append(row)
    return out


def kinds():
    """Which kinds of speech are actually in the journal, for a filter."""
    with _LOCK:
        return sorted({row['kind'] for row in _lines if row['kind']})


def when(row):
    """The time of a line, as a person reads one."""
    try:
        return time.strftime('%H:%M:%S', time.localtime(row['at']))
    except Exception:                                # noqa: BLE001
        return ''


def label(row):
    """One line of the journal as it appears in a list."""
    said = row['text']
    if len(said) > 90:
        said = said[:90] + '...'
    return '%s  %s' % (when(row), said)


# --------------------------------------------------------------------------- #
# Going back to what said it
# --------------------------------------------------------------------------- #
def can_go(row):
    return bool(row and row.get('anchor'))


def go(row):
    """Go to the control this line was about. ``(ok, sentence)``.

    **The thing no other reader can do**, and the reason the anchor is
    stored beside the words. It is honest about its limits: the control has
    to still be there, and in the program it was in - a line said an hour
    ago in a dialog that has closed cannot be gone back to, and says so
    rather than moving the user somewhere plausible.
    """
    if not can_go(row):
        # Translators: said when a journal line has nothing to go back to.
        return False, _('There is nothing to go back to for that line')
    obj = anchors.find(row['anchor'])
    if obj is None:
        # Translators: said when the control a journal line was about is
        # not on the screen now.
        return False, _('What said that is not here now')
    try:
        obj.setFocus()
        # Translators: said on arriving back at what said a line.
        return True, _('{what}').format(what=row.get('where') or '')
    except Exception:                                # noqa: BLE001
        pass
    try:
        import api
        api.setNavigatorObject(obj)
        # Translators: said when the review cursor goes back to what said a
        # line, because the control cannot take the keyboard.
        return True, _('{what}, review cursor').format(
            what=row.get('where') or '')
    except Exception:                                # noqa: BLE001
        # Translators: said when what said a line cannot be reached.
        return False, _('It could not be reached')


def as_text(rows=None):
    """The journal as a page to read, oldest first - which is how it
    happened, and how somebody reads back over a morning."""
    rows = list(rows if rows is not None else lines())
    rows.reverse()
    return '\n'.join('%s  %s%s' % (
        when(row), row['text'],
        (' [%s]' % row['where']) if row.get('where') else '')
        for row in rows)

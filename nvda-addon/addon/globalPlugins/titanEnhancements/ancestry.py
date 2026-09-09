# -*- coding: utf-8 -*-
"""Where the keyboard IS, said once - and never what NVDA has just said.

This module exists because of one report: tabbing round a dialog said
"dialog, OK button" and then "dialog, Cancel button". The word "dialog"
before every single control.

Two faults, and the second is the one worth remembering.

**The small one was a cache key.** :mod:`semantics` remembered which region
it had last announced against ``obj.windowHandle`` - the handle of the
FOCUSED CONTROL. In a Win32 dialog every button is its own window, so every
Tab looked like a different window, the memory never matched and the region
was announced again. The test that covered it built every control with the
same handle, so it could not fail.

**The large one is that NVDA already does this.** ``NVDAObject.event_
focusEntered`` is fired on every ancestor the focus has newly entered, and
speaks it - which is exactly how a user hears "dialog" once when they arrive
in one, hears a group's name when they tab into the group, hears "toolbar"
when they reach the toolbar. Read out of the NVDA the user actually has
(``NVDAObjects/__init__.pyc``, which fires it for a menu bar, a popup menu
and a menu item as a full focus report and for everything else except a
LIST as a "focus entered" one). So the region layer was a second copy of a
feature that was already there, and the only thing it could add was the
duplicate.

What is left after taking the duplicate out is the part that is really
missing, and it is the part an app module buys anywhere else:

* **A LIST is entered in silence.** NVDA excludes it deliberately - a list
  announces itself through the row you land on - but a window with three
  lists in it ("Applications", "Games", "Titan IM") then gives the user no
  way to know which one they have moved to except by recognising the rows.
* **A pane with no name says nothing worth hearing.** NVDA speaks the role
  of an unnamed container, and "pane" is not information. A reader module
  can give that pane the name the program never gave it.
* **What was skipped is not the same as what was said.** Whether we may
  speak at all depends on what NVDA has just spoken, so the diff has to be
  computed HERE too - not to duplicate NVDA's, but to know what NVDA's said
  and stay off it.

So: the ancestry is diffed exactly as NVDA diffs it, every newly entered
step is marked with whether NVDA has already spoken it, and only the steps
NVDA left silent are ours. On the ordinary case - a dialog, a group, a
toolbar - that is nothing at all, and the user hears NVDA's own reporting
with nothing added and nothing repeated.

**The identity of a step is the STEP's**, never the focused control's:
``(window handle, role, name)`` of the ancestor itself. That is the whole
of the first fix, and it is why the repetition cannot come back.
"""

import threading
import time

from . import compat

#: How far up the ancestry is read. NVDA has already built and cached this
#: chain for the focus (`api.getFocusAncestors`), so the depth is a ceiling
#: on what is COMPARED rather than on anything walked: an application with
#: forty nested panes must not turn one focus event into forty tuples.
MAX_DEPTH = 24

#: Roles that are a place a user can be IN. Everything else in the chain is
#: plumbing - a client area, an unnamed pane wrapping one control - and
#: saying it would be the noise this module exists to remove.
PLACES = frozenset({
    'WINDOW', 'DIALOG', 'ALERT', 'PANE', 'PROPERTYPAGE', 'GROUPING',
    'TOOLBAR', 'MENUBAR', 'POPUPMENU', 'MENU', 'STATUSBAR', 'TABCONTROL',
    'LIST', 'TREEVIEW', 'TABLE', 'DATAGRID', 'DOCUMENT', 'FRAME',
    'SCROLLPANE', 'SPLITBUTTON', 'APPLICATION', 'PANEL',
})

#: The places worth saying that the user has just LEFT. Almost nothing is:
#: leaving a group, a toolbar or a pane is not news, and a reader that
#: narrated every exit would double what it says for nothing.
#:
#: A menu is the exception, and JAWS has said so for twenty years. Opening
#: one is announced by every reader; CLOSING one is announced by none of
#: them, so a user who pressed Escape - or pressed a key the menu did not
#: take - is left guessing whether the menu is still up and their next
#: keystroke is a command or a letter in a document. That is a real
#: question about what the keyboard will do next, which is exactly the kind
#: this add-on exists to answer.
LEAVING = frozenset({'MENUBAR', 'POPUPMENU', 'MENU'})

#: The one role NVDA enters in SILENCE (`event_focusEntered` excludes it),
#: which is therefore the one role we may speak without repeating anybody.
SILENT_TO_NVDA = frozenset({'LIST'})

#: Never more than this many newly entered places in one breath. Arriving
#: in a window enters its whole chain at once, and a reader that says six
#: container names before the control is a reader nobody waits for.
MAX_SAID = 2


class Step:
    """One place in the ancestry, with everything needed to decide about it.

    ``key`` is the ancestor's OWN identity. Getting that wrong is the whole
    of the bug this module replaces, so it is computed in one place and
    nothing else is allowed to invent one.
    """

    __slots__ = ('key', 'role', 'name', 'word', 'nvda_said')

    def __init__(self, key, role='', name='', word='', nvda_said=True):
        self.key = key
        self.role = role
        self.name = name
        self.word = word
        self.nvda_said = nvda_said

    def __eq__(self, other):
        return isinstance(other, Step) and other.key == self.key

    def __hash__(self):
        return hash(self.key)

    def __repr__(self):                              # pragma: no cover
        return f'Step({self.key!r}, {self.word!r}, said={self.nvda_said})'


def _role_name(obj):
    role = getattr(obj, 'role', None)
    return str(getattr(role, 'name', '') or '').upper()


def _key_of(obj):
    """The ancestor's own identity.

    The window handle first, because for a Win32 container it is exactly
    what "this pane and not that one" means; the role and the name after
    it, because a UIA tree can put a dozen ancestors on one handle and a
    key that could not tell them apart would collapse the chain.
    """
    try:
        handle = int(getattr(obj, 'windowHandle', 0) or 0)
    except (TypeError, ValueError):
        handle = 0
    try:
        name = str(getattr(obj, 'name', '') or '').strip()
    except Exception:                                # noqa: BLE001
        name = ''
    return (handle, _role_name(obj), name)


def _chain(obj):
    """The ancestors NVDA has already built, outermost first.

    Asked of `api.getFocusAncestors()` rather than walked: `obj.parent` is
    not a field but a call into another process that builds a whole
    NVDAObject, and walking it per focus event is what froze NVDA when the
    first version of the semantic layer shipped. For anything that is not
    the focus there is one step and no walk at all - a control this is
    asked about out of band is not worth a freeze.
    """
    if obj is None:
        return []
    api = compat.api
    if api is None:
        # No NVDA under us: one step, never a walk. The rule this whole
        # function exists for holds either way.
        try:
            parent = obj.parent
        except Exception:                            # noqa: BLE001
            return []
        return [parent] if parent is not None else []
    try:
        focus = api.getFocusObject()
    except Exception:                                # noqa: BLE001
        focus = None
    if focus is not None and focus is obj:
        try:
            chain = list(api.getFocusAncestors() or [])
        except Exception:                            # noqa: BLE001
            chain = []
        return chain[-MAX_DEPTH:]
    try:
        parent = obj.parent
    except Exception:                                # noqa: BLE001
        return []
    return [parent] if parent is not None else []


def path_of(obj, module=None):
    """The places this control is inside, outermost first.

    ``module`` is the reader module for this application, which is what
    turns an unnamed pane into a place with a name. Everything else about a
    step - its identity, its role, whether NVDA has spoken it - is read off
    the object and is true with no module at all.
    """
    steps = []
    for ancestor in _chain(obj):
        role = _role_name(ancestor)
        if role not in PLACES:
            continue
        key = _key_of(ancestor)
        try:
            name = str(getattr(ancestor, 'name', '') or '').strip()
        except Exception:                            # noqa: BLE001
            name = ''
        word = name
        said = role not in SILENT_TO_NVDA
        if module is not None:
            given = module.region_word(ancestor, role=role, name=name)
            if given:
                # A name the program never gave this pane is by definition
                # not something NVDA can have said.
                word, said = given, False
        if not word:
            from . import context
            word = context.role_name(getattr(ancestor, 'role', None))
        steps.append(Step(key, role, name, word, said))
    return steps


# --------------------------------------------------------------------------- #
# The diff
# --------------------------------------------------------------------------- #
_LOCK = threading.RLock()
_last = []

#: The answer for the control this was last asked about, so two callers in
#: one focus event get the same one.
_answer = {'key': None, 'entered': [], 'left': []}


def forget():
    with _LOCK:
        globals()['_last'] = []
        _answer.update({'key': None, 'entered': [], 'left': []})


def last_path():
    with _LOCK:
        return list(_last)


def _difference(previous, current):
    """The tail of ``current`` that ``previous`` did not already contain.

    NVDA's own rule, and computed the same way for the same reason: the
    common prefix is where the user already was, and everything after it is
    somewhere they have just arrived. Leaving a place is not entering one,
    so moving OUT of a group says nothing - which is what every reader
    does, and what makes this quiet in the ordinary case.
    """
    common = 0
    for before, after in zip(previous, current):
        if before.key != after.key:
            break
        common += 1
    return current[common:]


#: One pass may take this long, and after this many slow ones the layer
#: stands down for the session and says so.
#:
#: **Not optional.** This runs inside `event_gainFocus`, on the thread that
#: reads the screen, and every step of it is a property of an NVDA object -
#: which is a call into another process. The first version of the semantic
#: layer walked eight parents per focus event and froze NVDA ten times in
#: one session (the session before it existed: zero). The walk is gone -
#: NVDA has already built and cached this chain - but the lesson is not the
#: walk: it is that a layer on this path must be able to notice it is too
#: expensive and stop, rather than needing somebody to work out from a
#: frozen reader which add-on to blame.
SLOW_ONCE = 0.05
SLOW_ENOUGH = 5

_timing = {'calls': 0, 'total': 0.0, 'worst': 0.0, 'slow': 0, 'stopped': ''}


def timing():
    kept = dict(_timing)
    kept['average'] = (kept['total'] / kept['calls']) if kept['calls'] else 0.0
    return kept


def stood_down():
    return _timing['stopped']


def resume():
    _timing.update({'slow': 0, 'stopped': ''})


def changes(obj, module=None):
    """``(entered, left)`` since the last focus event. Usually ``([], [])``.

    Advances the memory - and answers the SAME thing when it is asked twice
    about the same control. Two different callers want this per focus
    event: the one that says where the user now is, and the one that says
    the menu has closed. Whichever asked first would otherwise consume the
    answer and leave the other with nothing, which is the shape of bug this
    module was written to remove rather than to introduce.
    """
    if _timing['stopped']:
        return [], []
    began = time.time()
    try:
        return _changes(obj, module)
    finally:
        took = time.time() - began
        _timing['calls'] += 1
        _timing['total'] += took
        if took > _timing['worst']:
            _timing['worst'] = took
        if took > SLOW_ONCE:
            _timing['slow'] += 1
            if _timing['slow'] >= SLOW_ENOUGH:
                _timing['stopped'] = (
                    'reading where the keyboard is took %d ms on this '
                    'machine, which the reader is heard hesitating over, so '
                    'it has stopped' % int(took * 1000))


def _changes(obj, module=None):
    current = path_of(obj, module)
    with _LOCK:
        kept = _answer.get('key')
        if kept is not None and kept == _key_of(obj) \
                and [step.key for step in _last] == [step.key for step
                                                     in current]:
            return list(_answer['entered']), list(_answer['left'])
        previous = list(_last)
        globals()['_last'] = current
    fresh = _difference(previous, current)
    gone = _difference(current, previous)
    ours = [step for step in fresh if not step.nvda_said and step.word]
    # Leaving is asked of the ROLE and not of the word: a menu that has
    # closed is worth saying whether or not it had a name, and it is the
    # kind of place rather than which one that the user needs.
    behind = [step for step in gone if step.role in LEAVING]
    # **Left ONE menu, or left the menus?** A submenu closing is not the
    # menus closing: Escape in a submenu, or Left arrow out of it, puts the
    # user back on the parent menu, and saying "out of menu" there would be
    # a reader announcing the opposite of what happened. So this is said
    # only when nothing menu-shaped is left in the path at all - which is
    # what Escape at the top level does, and what choosing an item does.
    if behind and any(step.role in LEAVING for step in current):
        behind = []
    entered, left = ours[-MAX_SAID:], behind[:1]
    with _LOCK:
        _answer.update({'key': _key_of(obj), 'entered': list(entered),
                        'left': list(left)})
    return entered, left


def entered(obj, module=None):
    """The places newly entered that are OURS to say. Usually ``[]``."""
    return changes(obj, module)[0]


def words(obj, module=None):
    """:func:`entered` as plain words, for a caller that only wants those."""
    return [step.word for step in entered(obj, module)]


def leaving_word(steps):
    """What to say for a menu that has just closed, or ''.

    One sentence for any number of them: closing a submenu and its parent
    in one keystroke is one event to the user, not two.
    """
    if not steps:
        return ''
    from . import i18n
    translate = i18n.install({})
    # Translators: said when the keyboard leaves a menu that was open.
    return translate('out of menu')


def sentence(obj, module=None):
    """The whole ancestry as one line - "where am I", asked for on purpose.

    Not the focus path: this is answered on demand, so it is the full
    chain and not a diff, and it deliberately does NOT advance the memory.
    A user pressing "where am I" twice must be told the same thing twice.
    """
    steps = path_of(obj, module)
    return ', '.join(step.word for step in steps if step.word)

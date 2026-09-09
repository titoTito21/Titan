# -*- coding: utf-8 -*-
"""Any window at all, as a virtual window walked with the arrow keys.

The third source for one idea. :mod:`terminal` walks a console's text,
:mod:`ocrReview` walks what a recogniser read off the screen and
:mod:`appReview` walks a Titan application's own account of itself. This
walks **whatever window the user is in**, built out of the accessibility
tree NVDA is already looking at - so the same keys, the same voice classes
and the same auditory icons apply to every program on the machine.

**Why a mode and not a change to how NVDA reads.** Emacspeak's voice lock
and its icons are what the user asked to have in Windows, and there are
two ways to do it. One is to stand in for NVDA's own report everywhere,
which buys tones and loses tables, landmarks, browse mode and everything
else NVDA knows and this does not. The other is a MODE the user turns on
and off, where this add-on IS the reader for as long as it is up, and
NVDA's own behaviour is untouched the moment it is not. The second is the
honest one, and it is what NVDA+v does.

* **Up and Down are controls, Left and Right are what is inside one** -
  the words of its text, the rows of a list. The same keys as the other
  three reviews, in the same places, for the fourth time.
* **Enter does what the control itself says it can do** - `doAction`,
  which is Press on a button, Expand on a tree, Jump on a link. Nothing
  here invents a verb, so a control that offers none says so rather than
  being clicked at blindly.
* **Every control is read in the user's own voice classes and marked with
  its own auditory icon**, which is the whole of what this is for: what a
  thing IS arrives before its name does.

**It is built once and kept**, because walking a window's tree is a call
into another process per node and doing it per keystroke would make the
arrows slow. F5 rebuilds; so does moving to another window.
"""

import threading
import time

from . import compat
from . import i18n
from . import icons

_ = i18n.install(globals())

#: How much of a window is walked. A tree is unbounded - a browser's
#: document is tens of thousands of nodes - and a review that took a
#: second to open is one nobody presses twice.
MAX_SEEN = 3000
MAX_NODES = 600

#: **And a budget in seconds, which is the one that really bites.** The
#: counts above are a guess at how long a window will take; this is the
#: measurement. Every node is a call into another process, and how long
#: that takes depends on the program: measured on this machine, a dialog
#: is 25 ms, a file manager 312 ms and a forum page in Edge **4.4
#: seconds** - 477 controls, none of which is worth waiting that long
#: with the key already pressed. A walk that runs out says so and hands
#: over what it has, which is a usable window rather than a wait.
SECONDS = 1.2

#: Roles that are furniture rather than content: the frame around a window
#: is not the window. Read out as they came, they put Minimise, Maximise
#: and both scrollbars' arrows in front of every real control, which is
#: the mistake `src/app_ui/mirror.py` documents in Titan itself.
SKIP = frozenset({
    'WINDOW', 'PANE', 'UNKNOWN', 'SCROLLBAR', 'TITLEBAR', 'FRAME',
    'CLIENT', 'LAYEREDPANE', 'SPLITTER', 'WHITESPACE', 'BORDER',
})

_LOCK = threading.RLock()
_state = {'on': False, 'nodes': [], 'at': 0, 'inner': 0, 'hwnd': 0,
          'title': '', 'moves': 0, 'presses': 0, 'partial': '', 'ms': 0}


def report():
    with _LOCK:
        return {'reviewing': _state['on'], 'controls': len(_state['nodes']),
                'at': _state['at'], 'window': _state['title'],
                'moves': _state['moves'], 'presses': _state['presses'],
                'partial': _state['partial'], 'ms': _state['ms']}


def reviewing():
    with _LOCK:
        return bool(_state['on'])


# --------------------------------------------------------------------------- #
# Building it
# --------------------------------------------------------------------------- #
def _foreground():
    try:
        import api
        return api.getForegroundObject()
    except Exception:                                # noqa: BLE001
        return None


def _text(value):
    try:
        return str(value or '').strip()
    except Exception:                                # noqa: BLE001
        return ''


def _role_name(obj):
    try:
        return str(getattr(getattr(obj, 'role', None), 'name', '') or '')
    except Exception:                                # noqa: BLE001
        return ''


def nodes_of(window, note=None):
    """Every control in a window, breadth first and bounded three ways.

    Breadth first because a dialog's own controls are near the top of its
    tree, and a depth-first walk spends the whole budget in the first
    branch it falls into - which is how a review of a browser ends up
    being a review of its toolbar.

    Bounded by how many objects are looked at, how many are kept, and -
    the one that really decides it - **how long it has taken**. ``note``
    is filled in with which of the three stopped it, so the caller can
    say "as far as it got" rather than presenting a part of a window as
    the whole of it.
    """
    if note is None:
        note = {}
    note.update({'seen': 0, 'ran_out': '', 'ms': 0})
    if window is None:
        return []
    started = time.time()
    found, seen = [], 0
    queue = [(window, 0)]
    while queue and seen < MAX_SEEN and len(found) < MAX_NODES:
        if time.time() - started > SECONDS:
            note['ran_out'] = 'time'
            break
        obj, level = queue.pop(0)
        seen += 1
        try:
            for child in (obj.children or []):
                queue.append((child, level + 1))
        except Exception:                            # noqa: BLE001
            pass
        role = _role_name(obj)
        if role.upper() in SKIP:
            continue
        name = _text(getattr(obj, 'name', ''))
        value = _text(getattr(obj, 'value', ''))
        described = _text(getattr(obj, 'description', ''))
        if not name and not value and not described:
            # Nothing to call it by. A blank row is a row somebody arrows
            # onto and is told nothing about, which is worse than a shorter
            # list.
            continue
        found.append({'name': name, 'value': value, 'description': described,
                      'role': role, 'level': level, 'obj': obj})
    note['seen'] = seen
    note['ms'] = int((time.time() - started) * 1000)
    if not note['ran_out']:
        if seen >= MAX_SEEN:
            note['ran_out'] = 'objects'
        elif len(found) >= MAX_NODES:
            note['ran_out'] = 'controls'
    return found


def start(hwnd=0):
    """Build the virtual window for whatever is in front. ``(ok, said)``."""
    window = _foreground()
    if window is None:
        # Translators: said when there is no window to walk.
        return False, _('There is no window here')
    from . import reviews
    reviews.stop_others('virtualWindow')
    note = {}
    nodes = nodes_of(window, note)
    if not nodes:
        # **An empty answer is not a failure with no name.** A window that
        # exposes nothing is exactly what AI OCR and the recognised-screen
        # review are for, so it says which door to try rather than "no".
        return False, _('This window answers nothing. Read it with NVDA+o '
                        'instead.')
    with _LOCK:
        _state.update({'on': True, 'nodes': nodes, 'at': 0, 'inner': 0,
                       'partial': str(note.get('ran_out') or ''),
                       'ms': int(note.get('ms') or 0),
                       'title': _text(getattr(window, 'name', '')),
                       'hwnd': int(getattr(window, 'windowHandle', 0) or 0)})
    if not icons.play('open-object'):
        _cue(True)
    if note.get('ran_out'):
        # **Said once, because it happened once.** The toggle itself stays
        # two words; this is the one thing about THIS window that the user
        # would otherwise find out by arrowing to the end and wondering
        # where the rest of it went.
        # Translators: said when a window was too big to be walked whole.
        _say(_('Part of it only'))
    say_here()
    # **A toggle says which state it is in and nothing else.** It carried
    # the number of controls, which is a fact about this window rather
    # than about the switch - and the first control is spoken straight
    # after it anyway, so the count was said on the way to what the user
    # actually wanted to hear. The pair has to be symmetrical or somebody
    # has to listen to work out which state they are now in.
    # Translators: said when the virtual window is turned on.
    return True, _('Virtual window on')


def stop():
    with _LOCK:
        was = _state['on']
        _state.update({'on': False, 'nodes': [], 'at': 0, 'inner': 0,
                       'hwnd': 0})
    if was and not icons.play('close-object'):
        _cue(False)
    # Translators: said when the virtual window is turned off.
    return False, _('Virtual window off')


def toggle():
    """Turn it on or off, and REMEMBER which, for this program.

    The user asked for it per program, and that is the right shape: a
    window whose controls are worth walking this way is a property of the
    program rather than a mood. A program it was turned on in gets it back
    the next time they arrive there - see :func:`consider`.
    """
    if reviewing():
        answer = stop()
        _remember(False)
        return answer
    answer = start()
    if answer[0]:
        _remember(True)
    return answer


def _remember(on):
    try:
        from . import perProgram
        perProgram.set_value('virtualWindow', perProgram.application_of(),
                             bool(on))
    except Exception:                                # noqa: BLE001
        pass


def wanted_here():
    """Whether this program is one the user walks this way."""
    try:
        from . import perProgram
        return bool(perProgram.value('virtualWindow'))
    except Exception:                                # noqa: BLE001
        return False


def consider():
    """Turn it on by itself where the user has already said they want it.

    The contextual half: a subsystem that comes on where it belongs rather
    than being asked for every time - and only ever in a program they
    themselves turned it on in, which is what keeps it from being a
    surprise.
    """
    if reviewing() or not wanted_here():
        return False
    return start()[0]


def refresh():
    if not reviewing():
        return False, _('Virtual window off')
    with _LOCK:
        at = _state['at']
    stop()
    ok, said = start()
    if ok:
        with _LOCK:
            _state['at'] = max(0, min(at, len(_state['nodes']) - 1))
        say_here()
    return ok, said


def left_the_window():
    """Whether the window this was built for has gone.

    A review that outlived its window would swallow the user's arrow keys
    in whatever they moved to, which is the one way this feature could
    make a machine worse - the same guard the terminal and OCR reviews
    each carry.
    """
    if not reviewing():
        return False
    window = _foreground()
    now = int(getattr(window, 'windowHandle', 0) or 0) if window else 0
    with _LOCK:
        was = _state['hwnd']
    if now in (0, was):
        return False
    stop()
    return True


# --------------------------------------------------------------------------- #
# Moving
# --------------------------------------------------------------------------- #
def here():
    with _LOCK:
        nodes = _state['nodes']
        at = _state['at']
        return nodes[at] if 0 <= at < len(nodes) else None


def move(delta):
    with _LOCK:
        nodes = _state['nodes']
        if not nodes:
            return _nothing()
        at = _state['at'] + delta
        if at < 0 or at >= len(nodes):
            _edge()
            return say_here(beep=False)
        _state['at'] = at
        _state['inner'] = 0
        _state['moves'] += 1
    return say_here()


def move_page(direction):
    return move(10 if direction > 0 else -10)


def move_end(to_end):
    with _LOCK:
        nodes = _state['nodes']
        if not nodes:
            return _nothing()
        _state['at'] = len(nodes) - 1 if to_end else 0
        _state['inner'] = 0
        _state['moves'] += 1
    return say_here()


def move_inside(delta):
    """Left and Right: the words of what this control says."""
    node = here()
    if node is None:
        return _nothing()
    words = _words_of(node)
    if not words:
        return say_here(beep=False)
    with _LOCK:
        at = _state['inner'] + delta
        if at < 0 or at >= len(words):
            _edge()
            at = max(0, min(_state['inner'], len(words) - 1))
        _state['inner'] = at
        _state['moves'] += 1
        said = words[at]
    _say(said)
    return True, said


def _words_of(node):
    said = ' '.join(part for part in (node.get('name'), node.get('value'))
                    if part)
    return [word for word in said.split() if word]


# --------------------------------------------------------------------------- #
# Quick navigation - a letter jumps to the next control of that kind
# --------------------------------------------------------------------------- #
#: Letter -> the roles it jumps between. NVDA's own browse-mode letters
#: where there is one, because somebody who reads the web already knows
#: them and a second set of letters for the same job is a second thing to
#: learn for nothing.
#:
#: The roles are NVDA's own names, upper case. A role NVDA spells
#: differently on some build simply never matches, which is a letter that
#: finds nothing rather than a review that raises.
QUICK = {
    'b': ('BUTTON', 'TOGGLEBUTTON', 'SPLITBUTTON', 'MENUBUTTON',
          'DROPDOWNBUTTON'),
    'h': ('HEADING', 'HEADING1', 'HEADING2', 'HEADING3', 'HEADING4',
          'HEADING5', 'HEADING6', 'GROUPING', 'PROPERTYPAGE', 'TOOLBAR'),
    'x': ('CHECKBOX',),
    'r': ('RADIOBUTTON',),
    'i': ('LISTITEM', 'TREEVIEWITEM'),
    'l': ('LIST', 'TREEVIEW'),
    'c': ('COMBOBOX',),
    'e': ('EDITABLETEXT', 'PASSWORDEDIT'),
    't': ('TABLE', 'TABLECELL', 'DATAITEM', 'DATAGRID'),
    'k': ('LINK',),
    'g': ('GRAPHIC',),
    's': ('SLIDER', 'SPINBUTTON', 'PROGRESSBAR'),
    'm': ('MENUITEM', 'MENU', 'POPUPMENU', 'MENUBAR'),
    'a': ('ALERT',),
    'o': ('TAB', 'TABCONTROL'),
}


def quick_names():
    """Letter -> what it jumps to, in words, for the help and the tests."""
    return {
        # Translators: what a quick navigation letter jumps to.
        'b': _('a button'),
        'h': _('a heading, or a part of the window'),
        'x': _('a check box'),
        'r': _('a radio button'),
        'i': _('a row of a list'),
        'l': _('a list'),
        'c': _('a combo box'),
        'e': _('a field you type in'),
        't': _('a table'),
        'k': _('a link'),
        'g': _('a picture'),
        's': _('a slider or a meter'),
        'm': _('a menu'),
        'a': _('an alert'),
        'o': _('a tab'),
    }


#: Roles that are being TYPED INTO. A letter pressed in one of these is
#: the letter, not a command.
TYPING = frozenset({'EDITABLETEXT', 'PASSWORDEDIT', 'DOCUMENT', 'TERMINAL',
                    'COMBOBOX', 'SPINBUTTON'})


def typing_now():
    """Whether the keyboard is in something the user types into.

    **The one guard the quick-navigation letters cannot do without.** This
    mode turns itself on in a program the user chose, and then a bare `b`
    would be a command rather than the letter b - so in a field, in a
    document, in a terminal, the letters are the user's. Browse mode has
    exactly this problem and answers it exactly this way.
    """
    try:
        import api
        obj = api.getFocusObject()
    except Exception:                                # noqa: BLE001
        return False
    role = _role_name(obj).upper()
    if role in TYPING:
        return True
    try:
        from . import elements
        states = elements._states_of(obj)
    except Exception:                                # noqa: BLE001
        states = []
    # A control NVDA reports as editable is one being typed into whatever
    # its role happens to be called on this toolkit.
    return any('edit' in str(state).lower() for state in states)


def jump(letter, back=False):
    """The next control of that kind, or say there is none. ``(ok, said)``.

    **It wraps round nothing and says when it found nothing**, which is
    what browse mode does: a letter that silently left the cursor where it
    was is indistinguishable from a key that is not bound.
    """
    wanted = QUICK.get(str(letter or '').lower())
    if not wanted:
        return _nothing()
    with _LOCK:
        nodes = list(_state['nodes'])
        at = _state['at']
    order = range(at - 1, -1, -1) if back else range(at + 1, len(nodes))
    for index in order:
        if str(nodes[index].get('role') or '').upper() in wanted:
            with _LOCK:
                _state['at'] = index
                _state['inner'] = 0
                _state['moves'] += 1
            return say_here()
    icons.play('search-miss')
    words = quick_names().get(str(letter).lower(), str(letter))
    # Translators: said when quick navigation finds nothing. {what} is the
    # kind of control that was looked for.
    return False, _('No more: {what}').format(what=words)


# --------------------------------------------------------------------------- #
# Acting
# --------------------------------------------------------------------------- #
def activate():
    """Do what the control itself says it can do.

    The control's OWN verb from the accessibility layer - Press, Expand,
    Check, Jump - never a synthesised click. A control that offers none
    says so, which is a true answer: clicking at a rectangle because
    nothing else was on offer is how a reader presses the wrong thing.
    """
    node = here()
    if node is None:
        return _nothing()
    obj = node.get('obj')
    with _LOCK:
        _state['presses'] += 1
    try:
        count = int(getattr(obj, 'actionCount', 0) or 0)
    except Exception:                                # noqa: BLE001
        count = 0
    if count:
        try:
            name = _text(obj.getActionName(0))
            obj.doAction(0)
            icons.play('task-done')
            return True, name or _('Done')
        except Exception:                            # noqa: BLE001
            pass
    # **Then Enter really clicks it.** A control that declares no action of
    # its own is extremely common - a custom-drawn toolbar, a browser's own
    # widgets - and for somebody who cannot see the screen "there is
    # nothing I can do here" is the least useful true sentence there is.
    # The mouse is put back afterwards, which is what makes a click safe to
    # do on somebody's behalf: the pointer is theirs and where they left it
    # may matter.
    if click_here()[0]:
        # Translators: said when a control has been clicked.
        return True, _('Clicked')
    if focus_here()[0]:
        # Translators: said when the keyboard has been moved to a control.
        return True, _('Moved to it')
    icons.play('warn-user')
    # Translators: said when nothing at all could be done with a control.
    return False, _('Nothing could be done here')


def click_here():
    """Click the middle of the control the cursor is on, then put the
    mouse back where it was.

    Through NVDA's own `mouseHandler` and `winUser`, so it is the same
    click NVDA's own "click where the review cursor is" makes.
    """
    node = here()
    if node is None:
        return _nothing()
    try:
        location = node['obj'].location
        left, top = int(location.left), int(location.top)
        width, height = int(location.width), int(location.height)
    except Exception:                                # noqa: BLE001
        return False, ''
    if width <= 0 or height <= 0:
        # A rectangle with no width is not a small control, it is one that
        # is not on the screen - and clicking its corner clicks whatever
        # is underneath it.
        return False, ''
    try:
        import mouseHandler
        import winUser
    except Exception:                                # noqa: BLE001
        return False, ''
    was = None
    try:
        was = winUser.getCursorPos()
    except Exception:                                # noqa: BLE001
        was = None
    try:
        winUser.setCursorPos(left + width // 2, top + height // 2)
        mouseHandler.executeMouseMoveEvent(left + width // 2,
                                           top + height // 2)
        winUser.mouse_event(winUser.MOUSEEVENTF_LEFTDOWN, 0, 0, None, None)
        winUser.mouse_event(winUser.MOUSEEVENTF_LEFTUP, 0, 0, None, None)
        icons.play('task-done')
        return True, ''
    except Exception:                                # noqa: BLE001
        return False, ''
    finally:
        if was is not None:
            try:
                winUser.setCursorPos(*was)
            except Exception:                        # noqa: BLE001
                pass


def focus_here():
    """Put NVDA's navigator - and the keyboard where it can go - here."""
    node = here()
    if node is None:
        return _nothing()
    obj = node.get('obj')
    try:
        import api
        api.setNavigatorObject(obj)
    except Exception:                                # noqa: BLE001
        pass
    try:
        obj.setFocus()
        return True, ''
    except Exception:                                # noqa: BLE001
        return False, ''


# --------------------------------------------------------------------------- #
# Saying
# --------------------------------------------------------------------------- #
def parts_of(node, at=0, count=0):
    """What one control says, as ``[(text, class)]``.

    The user's own semantic classes, so a window walked this way is read
    exactly as a control is read anywhere else in this add-on - the name,
    what it IS a little lower, its value and where it is a little higher.
    """
    if not node:
        return []
    parts = []
    if node.get('name'):
        parts.append((node['name'], 'name'))
    from . import context
    word = context.role_name(getattr(node.get('obj'), 'role', None))
    if word:
        parts.append((word, 'kind'))
    states = _states_of(node.get('obj'))
    for state in states:
        parts.append((state, 'state'))
    if node.get('value') and node['value'] != node.get('name'):
        parts.append((node['value'], 'value'))
    if node.get('description'):
        parts.append((node['description'], 'description'))
    if count:
        parts.append((_('{at} of {count}').format(at=at + 1, count=count),
                      'place'))
    return parts


def _states_of(obj):
    try:
        from . import elements
        return elements._states_of(obj)
    except Exception:                                # noqa: BLE001
        return []


def say_here(beep=True):
    node = here()
    if node is None:
        return _nothing()
    with _LOCK:
        at = _state['at']
        count = len(_state['nodes'])
    if beep:
        role = getattr(node.get('obj'), 'role', None)
        if not icons.play(icons.for_role(role)):
            _beep(at, count)
    parts = parts_of(node, at=at, count=count)
    _say_parts(parts)
    return True, ', '.join(text for text, _voice in parts)


def _say_parts(parts):
    if not parts:
        return
    from . import elements
    sequence = elements.sequence(parts)
    if not sequence or compat.speech is None:
        _say(', '.join(str(text) for text, _voice in parts))
        return
    try:
        from . import voices
        voices.speak_sequence(sequence)
    except Exception:                                # noqa: BLE001
        _say(', '.join(str(text) for text, _voice in parts))


def _nothing():
    # Translators: said when there is nothing at the cursor.
    return False, _('Nothing here')


def _beep(at, count):
    if compat.tones is None:
        return
    span = max(1, (count or 1) - 1)
    where = max(0.0, min(1.0, at / float(span)))
    try:
        compat.tones.beep(int(1650 - 1230 * where), 22)
    except Exception:                                # noqa: BLE001
        pass


def _edge():
    if compat.tones is None:
        return
    try:
        compat.tones.beep(220, 30)
    except Exception:                                # noqa: BLE001
        pass


def _cue(on):
    if compat.tones is None:
        return
    try:
        compat.tones.beep(660 if on else 440, 40)
    except Exception:                                # noqa: BLE001
        pass


def _say(text):
    if compat.speech is None:
        return
    try:
        compat.speech.speakMessage(str(text))
    except Exception:                                # noqa: BLE001
        pass

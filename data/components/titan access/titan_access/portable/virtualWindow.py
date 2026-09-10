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
          'title': '', 'moves': 0, 'presses': 0, 'partial': '', 'ms': 0,
          'typing': False, 'why': ''}


def report():
    with _LOCK:
        return {'reviewing': _state['on'], 'typing': _state['typing'],
                'controls': len(_state['nodes']),
                'at': _state['at'], 'window': _state['title'],
                'moves': _state['moves'], 'presses': _state['presses'],
                'partial': _state['partial'], 'ms': _state['ms'],
                'why': _state['why']}


def reviewing():
    with _LOCK:
        return bool(_state['on'])


def typing_mode():
    """Whether the keyboard has been handed to a field on purpose.

    Different from :func:`typing_now`, which ASKS NVDA where the focus
    happens to be. This is a mode the user entered by pressing Enter on a
    field and leaves by pressing Escape - and while it is on, the virtual
    window borrows no keys at all except that Escape, so every letter,
    every arrow and Enter itself are the application's.
    """
    with _LOCK:
        return bool(_state['on'] and _state['typing'])


def enter_typing():
    """Give the keyboard to the field the cursor is on. ``(ok, said)``."""
    node = here()
    if node is None:
        return _nothing()
    if not _is_a_field(node):
        return False, ''
    ok, _why = focus_here()
    if not ok:
        # A row read off the screen has no control to focus, and clicking
        # a rectangle is not the same promise: say so rather than turning
        # a mode on that nothing is behind.
        # Translators: said when a field could not be typed into.
        return False, _('This cannot be typed into')
    with _LOCK:
        _state['typing'] = True
    icons.play('open-object')
    # Translators: said when the virtual window hands the keyboard to a
    # field. The pair has to be symmetrical with 'Edit field off'.
    return True, _('Edit field on')


def leave_typing():
    """Take the keyboard back to the virtual window. ``(ok, said)``."""
    with _LOCK:
        was = _state['typing']
        _state['typing'] = False
    if not was:
        return False, ''
    icons.play('close-object')
    say_here()
    # Translators: said when the virtual window takes the keyboard back.
    return True, _('Edit field off')


def _is_a_field(node):
    """Whether Enter on this row means "type into it".

    The role the walk recorded first, and then what the control itself
    says: a toolkit that calls its field something else still reports an
    editable state, and a row this got wrong is a row whose Enter does
    the wrong thing.
    """
    if not node:
        return False
    if str(node.get('role') or '').upper() in TYPING:
        return True
    obj = node.get('obj')
    if obj is None:
        return False
    try:
        from . import elements
        states = elements._states_of(obj)
    except Exception:                                # noqa: BLE001
        return False
    return any('edit' in str(state).lower() for state in states)


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
    # **A virtual machine is walked at its GUEST's screen, always.**
    # Reading it was written as the answer to "this window exposes
    # nothing", and a VMware frame exposes plenty - a menu bar, a
    # toolbar, a tab strip, the library tree - so the walk below found
    # all of that, the fallback was never reached, and turning the
    # virtual window on in a virtual machine gave the user VMware's own
    # interface instead of the computer inside it. NVDA reads the host's
    # chrome perfectly well already; what somebody turns this on for is
    # what is INSIDE the window.
    try:
        from . import surface
        if surface.is_virtual_machine(window):
            rows = _read_the_screen(window, note)
            if rows:
                note['ms'] = int((time.time() - started) * 1000)
                return rows
            # Nothing could be read of the guest - a display that cannot
            # be photographed, no OCR language installed. The host's own
            # controls are worth less than the guest and more than
            # nothing, so it falls through rather than answering empty.
    except Exception:                                # noqa: BLE001
        pass
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
            # **A menu bar is the exception, because it is the one
            # unnamed control somebody is looking for.** wxWidgets and
            # most toolkits give it no accessible name at all, so the
            # rule below dropped it and a window walked this way had no
            # menus in it - the one part of a program a user most wants
            # to reach without hunting for the key that opens it.
            if role.upper() != 'MENUBAR':
                # Nothing to call it by. A blank row is a row somebody
                # arrows onto and is told nothing about, which is worse
                # than a shorter list.
                continue
            # Translators: the row for a window's menu bar.
            name = _('Menu bar')
        found.append({'name': name, 'value': value, 'description': described,
                      'role': role, 'level': level, 'obj': obj})
    # **The menu bar first, because that is where it is.** The walk is
    # breadth first over the accessibility tree, whose order is the order
    # a toolkit happened to build its children in - so the menus turned
    # up in the middle of a window's controls, which for somebody who
    # cannot see it is the menu bar being somewhere else every time.
    if found:
        bars = [row for row in found
                if str(row.get('role') or '').upper() == 'MENUBAR']
        if bars and found[:len(bars)] != bars:
            rest = [row for row in found if row not in bars]
            found = bars + rest
    if not found:
        # **A window that exposes nothing still has a screen.** A virtual
        # machine, a program on a toolkit nobody wired up: the walk above
        # finds nothing because there is nothing to find, and a virtual
        # window with no rows in it is the reader saying "there is nothing
        # here" about a screen full of things. So it is READ - by Windows'
        # own recogniser, locally, with nothing sent anywhere - and the
        # lines become the rows. Each keeps its rectangle, so Enter
        # presses it by clicking where it really is, which is the only way
        # to press anything in somebody else's computer.
        found = _read_the_screen(window, note)
    note['seen'] = seen
    note['ms'] = int((time.time() - started) * 1000)
    if not note['ran_out']:
        if seen >= MAX_SEEN:
            note['ran_out'] = 'objects'
        elif len(found) >= MAX_NODES:
            note['ran_out'] = 'controls'
    return found


def _read_the_screen(window, note):
    """The window as a picture, as virtual-window rows. ``[]`` when it
    cannot be read.

    Deliberately Windows' own recogniser and not the AI: this happens by
    itself, on arriving in a window, and an automatic feature may not cost
    somebody a picture of their screen at a provider. The AI is what a
    keypress asks for.
    """
    try:
        from . import localOcr
        from . import surface
        from . import virtualInput
    except Exception:                                # noqa: BLE001
        return []
    handle = 0
    try:
        handle = int(getattr(window, 'windowHandle', 0) or 0)
    except (TypeError, ValueError):
        handle = 0
    if not handle:
        return []
    # A virtual machine is read at its GUEST's screen: the frame's own
    # menu bar is the host's interface, is readable already, and reading
    # it as part of the guest puts "File Machine View" at the top of
    # somebody's console.
    try:
        if surface.is_virtual_machine(window):
            display = surface.display_of(window)
            inner = int(getattr(display, 'windowHandle', 0) or 0)
            if inner:
                handle = inner
                note['guest'] = True
    except Exception:                                # noqa: BLE001
        pass
    ready, why = localOcr.available()
    if not ready:
        note['ran_out'] = _text(why)
        return []
    reading = localOcr.read_window(handle)
    if reading is None:
        note['ran_out'] = _text(localOcr.report().get('why', ''))
        return []
    rows = []
    for node in virtualInput.build(reading,
                                   getattr(reading, 'highlights', None)):
        rows.append({'name': node.text, 'value': '', 'description': '',
                     'role': 'text', 'level': 0, 'obj': None,
                     'rect': (node.left, node.top, node.width, node.height),
                     'selected': node.selected})
    note['read'] = len(rows)
    return rows


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
                       'typing': False,
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
                       'hwnd': 0, 'typing': False})
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


def refresh(keep_place=True):
    """Build it again. ``(ok, said)``.

    ``keep_place`` is what tells "read this window again" from "the
    window has become a different window": F5 puts the cursor back where
    it was, and going up a folder must not - the row that was third in
    the folder you left has nothing to do with the third row of the one
    you arrived in.
    """
    if not reviewing():
        return False, _('Virtual window off')
    with _LOCK:
        at = _state['at']
    stop()
    ok, said = start()
    if ok and keep_place:
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
    # **Enter on a field means "type into it".** Pressing a field is not
    # a thing anybody wants done to it: its own action is usually nothing
    # at all, so Enter fell through to a click, which put the caret there
    # and left the virtual window still holding every letter - a field
    # the user was in and could not type a word into.
    if _is_a_field(node):
        ok, said = enter_typing()
        if ok or said:
            return ok, said
    if obj is None:
        # A row read off the screen: there is no control to ask what it
        # can do, so Enter is a click at the place the words are.
        ok, why = click_here()
        if ok:
            return True, _('Clicked')
        # **And when it could not, it says which of the four reasons it
        # was.** "Nothing could be done here" is the least useful true
        # sentence there is - it wears a rectangle that was never read,
        # a control off the screen, an NVDA with no mouse handler and a
        # click that really failed, and each of those is a different
        # thing to do about it.
        return False, _refusal(why)
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
    ok, why = click_here()
    if ok:
        # Translators: said when a control has been clicked.
        return True, _('Clicked')
    if focus_here()[0]:
        # Translators: said when the keyboard has been moved to a control.
        return True, _('Moved to it')
    icons.play('warn-user')
    return False, _refusal(why)


def _refusal(why):
    """What to say when Enter could do nothing, with the reason in it."""
    # Translators: said when nothing at all could be done with a control.
    said = _('Nothing could be done here')
    why = _text(why)
    if not why:
        return said
    with _LOCK:
        _state['why'] = why
    return '%s: %s' % (said, why)


def click_here():
    """Click the middle of the control the cursor is on, then put the
    mouse back where it was.

    Through NVDA's own `mouseHandler` and `winUser`, so it is the same
    click NVDA's own "click where the review cursor is" makes.
    """
    node = here()
    if node is None:
        return _nothing()
    # **A row READ off the screen has no object, and a rectangle instead.**
    # That is the whole of pressing something inside a virtual machine:
    # there is no control to ask, only a place on the screen where the
    # words are, and clicking there is what a person with a mouse would
    # do. The rectangle came from Windows' own recogniser, so it is a
    # place we were told rather than one worked out.
    rect = node.get('rect')
    if rect:
        try:
            left, top, width, height = (int(rect[0]), int(rect[1]),
                                        int(rect[2]), int(rect[3]))
        except Exception:                            # noqa: BLE001
            return False, 'the rectangle it was read at is not a rectangle'
    else:
        try:
            location = node['obj'].location
            left, top = int(location.left), int(location.top)
            width, height = int(location.width), int(location.height)
        except Exception:                            # noqa: BLE001
            return False, 'this control will not say where it is'
    if width <= 0 or height <= 0:
        # A rectangle with no width is not a small control, it is one that
        # is not on the screen - and clicking its corner clicks whatever
        # is underneath it.
        return False, 'it has no place on the screen'
    try:
        import mouseHandler
        import winUser
    except Exception as error:                       # noqa: BLE001
        return False, 'this NVDA has no mouse handler: %s' % error
    # **The window is brought forward before it is clicked.** A click into
    # a window that is not the active one is spent activating it - which
    # in a virtual machine is the whole of "it goes to the guest and
    # nothing happens": the guest only takes input once its own window
    # has it, so the first press woke VMware up and the second would have
    # been the one that landed. Doing it here means one press does what
    # the user asked for.
    _bring_forward(_point_owner(left + width // 2, top + height // 2))
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
    except Exception as error:                       # noqa: BLE001
        return False, 'the click itself failed: %s' % error
    finally:
        if was is not None:
            try:
                winUser.setCursorPos(*was)
            except Exception:                        # noqa: BLE001
                pass


def _point_owner(x, y):
    """The top-level window that owns that point on the screen.

    Asked of the POINT rather than taken from the window this was built
    for, because they are not the same window in the case that matters: a
    virtual machine is walked at its guest's screen, and the guest is a
    child several levels under the frame.
    """
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.WindowFromPoint.restype = ctypes.c_void_p
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        found = int(user32.WindowFromPoint(
            wintypes.POINT(int(x), int(y))) or 0)
    except Exception:                                # noqa: BLE001
        found = 0
    if not found:
        with _LOCK:
            return int(_state['hwnd'] or 0)
    try:
        import ctypes
        root = ctypes.windll.user32.GetAncestor(ctypes.c_void_p(int(found)),
                                                2)      # GA_ROOT
        return int(root or found)
    except Exception:                                # noqa: BLE001
        return int(found)


def _bring_forward(hwnd):
    """Make that window the active one, so a click into it is a click.

    ``AttachThreadInput`` first, because Windows refuses
    ``SetForegroundWindow`` from a process that is not already the
    foreground one - which NVDA never is. It is the same move Titan's own
    shell makes for the same reason.
    """
    hwnd = int(hwnd or 0)
    if not hwnd:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        front = int(user32.GetForegroundWindow() or 0)
        if front == hwnd:
            return True
        mine = user32.GetCurrentThreadId()
        theirs = user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), None)
        attached = bool(theirs) and bool(
            user32.AttachThreadInput(mine, theirs, True))
        try:
            user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        finally:
            if attached:
                user32.AttachThreadInput(mine, theirs, False)
        return True
    except Exception:                                # noqa: BLE001
        return False


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

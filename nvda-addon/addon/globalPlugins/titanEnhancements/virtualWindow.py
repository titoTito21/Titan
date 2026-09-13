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
          'layout': 'linear', 'clicked_at': 0.0, 'depth': None,
          'window_rect': None,
          'title': '', 'moves': 0, 'presses': 0, 'partial': '', 'ms': 0,
          'typing': False, 'why': '', 'typed': 0, 'field': None,
          'menu': None, 'letter': 0}


def report():
    with _LOCK:
        return {'reviewing': _state['on'], 'typing': _state['typing'],
                'controls': len(_state['nodes']),
                'at': _state['at'], 'window': _state['title'],
                'moves': _state['moves'], 'presses': _state['presses'],
                'partial': _state['partial'], 'ms': _state['ms'],
                'why': _state['why'], 'typed': _state.get('typed', 0),
                'here': _here_report()}


def _here_report():
    """What the cursor is on, for a diagnostic.

    "Enter on the field does nothing" cannot be answered without knowing
    what this thinks the row IS - the role it was walked as, whether it
    has a control behind it at all, and whether the rule that decides
    "type into this" says yes.
    """
    row = here()
    if row is None:
        return {}
    try:
        return {'name': _text(row.get('name'))[:40],
                'role': _text(row.get('role')),
                'has_object': row.get('obj') is not None,
                'is_a_field': bool(_is_a_field(row)),
                'typing': bool(_state['typing']),
                # Where Enter would click. "It clicks in the wrong place"
                # and "it clicks in the right place and the program
                # ignored it" are different faults and only the point
                # tells them apart.
                'rect': list(row.get('rect') or []),
                'vm': _in_a_virtual_machine()}
    except Exception as error:                       # noqa: BLE001
        return {'failed': str(error)}


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
    """Type into the row the cursor is on. ``(ok, said)``.

    **This is a mode of the VIRTUAL WINDOW**, not a hand-over to whatever
    happens to have the focus. While it is on the virtual window holds
    every printable key - the letters, the space, Enter - and puts each
    one into the place the cursor is on. That is what makes it work in
    the two cases that are not the same:

    * a real control, which is focused and then edits itself, so Up and
      Down are its lines, Left and Right its characters and Control with
      an arrow its words - the control's own behaviour, not a copy of it;
    * a row read off a PICTURE, where there is no control at all. That is
      a virtual machine, and the guest is another computer with its own
      caret: the row is clicked to put that caret where the words are,
      and the keys go to the guest's window.

    Releasing the keys instead - which is what this did first - works for
    the first and silently does nothing for the second, because there is
    nothing focused to receive them.
    """
    node = here()
    if node is None:
        return _nothing()
    obj = node.get('obj')
    if obj is not None:
        if not _is_a_field(node):
            return False, ''
        ok, _why = focus_here()
        if not ok:
            # Translators: said when a field could not be typed into.
            return False, _('This cannot be typed into')
    else:
        # A row off a picture. Clicking is how the caret gets there, and
        # it is the same click Enter would make - so a window that
        # answers a click answers this, and one that does not was never
        # going to be typed into anyway.
        ok, why = click_here()
        if not ok:
            return False, _refusal(why)
    # **The field's own text becomes the window.** Its lines are what the
    # cursor walks, its characters are what Left and Right say, and a
    # letter goes in at the caret - so a field is walked exactly as the
    # window's controls are, which is what "the edit field IS a virtual
    # window" means.
    from . import textField
    with _LOCK:
        _state['typing'] = True
        _state['field'] = textField.Field(
            text=_value_of(node), multiline=_is_multiline(node),
            readonly=False)
    icons.play('open-object')
    # Translators: said when the virtual window hands the keyboard to a
    # field. The pair has to be symmetrical with 'Edit field off'.
    said = _('Edit field on')
    _say_field()
    return True, said


def _value_of(node):
    """What the row already holds, so typing starts from the real text."""
    obj = node.get('obj')
    if obj is None:
        # A row off a picture: the words that were read are all there is,
        # and they are what the guest already shows.
        return ''
    for name in ('value', 'name'):
        try:
            found = getattr(obj, name, None)
            if isinstance(found, str) and found:
                return found
        except Exception:                            # noqa: BLE001
            continue
    return ''


def _is_multiline(node):
    role = str(node.get('role') or '').upper()
    if role in ('DOCUMENT', 'TERMINAL'):
        return True
    obj = node.get('obj')
    try:
        from . import elements
        states = elements._states_of(obj) if obj is not None else []
    except Exception:                                # noqa: BLE001
        states = []
    return any('multiline' in str(one).lower() for one in states)


def field():
    """The field being walked, or None."""
    with _LOCK:
        return _state.get('field')


def _say_field():
    """Where the caret is now, in the reader's own voice classes."""
    found = field()
    if found is None:
        return
    _say_parts(found.parts())


#: What is said back as a key is typed. A letter is echoed because a
#: reader that says nothing while somebody types is a reader they cannot
#: tell is listening; the editing keys are left to the control, which
#: announces what it did with them itself.
ECHO = True


def type_key(name, send):
    """One key against the field being walked. ``(ok, said)``.

    The field decides what the key means - :mod:`textField` is the one
    place that knows, so the two readers and the two modes cannot drift
    apart about what Backspace does - and what comes back is what to say:
    the character moved onto, the line arrived at, or the text that went.

    A key the field does not want (Tab, and Enter in a one-line field,
    which belongs to the form) is handed back to the program with
    ``send``.
    """
    if not typing_mode():
        return False, ''
    found = field()
    if found is None:
        return False, ''
    from . import textField
    was = found.text
    what, said = textField.press(found, name)
    if not what:
        # Not the field's key: it is the program's.
        try:
            send()
        except Exception:                            # noqa: BLE001
            pass
        return True, ''
    with _LOCK:
        _state['typed'] += 1
    if what == 'edge':
        _edge()
        return True, ''
    if found.text != was:
        _write_back(found.text)
    if said:
        _say(said)
    return True, ''


def open_menu(node):
    """Walk into a menu: what is on it becomes the list. ``(ok, said)``."""
    obj = node.get('obj')
    if obj is None:
        return False, ''
    note = {}
    inside = nodes_of(obj, note)
    inside = [row for row in inside if row.get('obj') is not obj]
    if not inside:
        # Translators: said when a menu has nothing on it that can be read.
        return False, _('That menu is empty')
    with _LOCK:
        _state['menu'] = {'nodes': list(_state['nodes']),
                          'at': _state['at'],
                          'title': _state['title']}
        _state.update({'nodes': inside, 'at': 0, 'inner': 0})
    icons.play('open-object')
    say_here()
    return True, ''


def in_a_menu():
    with _LOCK:
        return bool(_state.get('menu'))


def close_menu():
    """Back out of a menu to the window's own controls. ``(ok, said)``."""
    with _LOCK:
        was = _state.get('menu')
        if not was:
            return False, ''
        _state.update({'nodes': was['nodes'], 'at': was['at'],
                       'inner': 0, 'menu': None})
    icons.play('close-object')
    say_here()
    return True, ''


def _write_back(text):
    """Put the text into the real control, where there is one.

    A row read off a picture has none - there the keys have already been
    typed into the guest by the program itself, because the row was
    clicked and the guest has the keyboard.
    """
    node = here()
    obj = (node or {}).get('obj')
    if obj is None:
        return False
    for setter in ('value',):
        try:
            setattr(obj, setter, text)
            return True
        except Exception:                            # noqa: BLE001
            continue
    try:
        obj.setFocus()
    except Exception:                                # noqa: BLE001
        pass
    return False


def typed():
    with _LOCK:
        return int(_state.get('typed') or 0)


def leave_typing():
    """Take the keyboard back to the virtual window. ``(ok, said)``."""
    with _LOCK:
        was = _state['typing']
        _state['typing'] = False
        _state['field'] = None
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


def _rect_of_window(window):
    """``(left, top, width, height)`` of the window itself, or None.

    The corners are the WINDOW's, not the bounding box of whatever the
    walk happened to keep: a list's rows scrolled out of sight report
    rectangles far below the window, and a corner worked out from those
    lands on a row nobody can see.
    """
    try:
        location = window.location
        rect = (int(location.left), int(location.top),
                int(location.width), int(location.height))
    except Exception:                                # noqa: BLE001
        return None
    return rect if rect[2] > 0 and rect[3] > 0 else None


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
    # **Every node knows which kept node it is inside.** ``parent`` is
    # the id of the nearest ancestor that made it into the list - a
    # skipped pane or an unnamed control passes its own parent through -
    # which is what the interaction layout walks: the siblings of a
    # control are the nodes with the same parent, and interacting with it
    # is stepping down to the nodes whose parent it is. Ids rather than
    # indexes, because the menu bar is moved to the front below and an
    # index would move with it.
    queue = [(window, 0, None)]
    while queue and seen < MAX_SEEN and len(found) < MAX_NODES:
        if time.time() - started > SECONDS:
            note['ran_out'] = 'time'
            break
        obj, level, parent = queue.pop(0)
        seen += 1
        try:
            children = list(obj.children or [])
        except Exception:                            # noqa: BLE001
            children = []
        role = _role_name(obj)
        if role.upper() in SKIP:
            queue.extend((child, level + 1, parent) for child in children)
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
                queue.extend((child, level + 1, parent)
                             for child in children)
                continue
            # Translators: the row for a window's menu bar.
            name = _('Menu bar')
        queue.extend((child, level + 1, len(found)) for child in children)
        found.append({'name': name, 'value': value, 'description': described,
                      'role': role, 'level': level, 'obj': obj,
                      'id': len(found), 'parent': parent})
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
    _number(found)
    note['seen'] = seen
    note['ms'] = int((time.time() - started) * 1000)
    if not note['ran_out']:
        if seen >= MAX_SEEN:
            note['ran_out'] = 'objects'
        elif len(found) >= MAX_NODES:
            note['ran_out'] = 'controls'
    return found


def _number(rows):
    """Give every row an ``id`` and a ``parent`` it has not got.

    Rows read off a picture have no tree, and a caller may hand in rows
    of its own: they are all top-level, so the interaction layout treats
    them as siblings and finds nothing to step into but their words.
    """
    for index, row in enumerate(rows or []):
        if 'id' not in row:
            row['id'] = index
        if 'parent' not in row:
            row['parent'] = None
    return rows


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


def start(hwnd=0, speak=True):
    """Build the virtual window for whatever is in front. ``(ok, said)``.

    ``speak`` is False when the caller will place the cursor itself and say
    the row - which is what `refresh(keep_place=True)` does, and saying the
    first control here as well is the doubled announcement a rebuild used
    to make.
    """
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
                       'typing': False, 'depth': None,
                       'window_rect': _rect_of_window(window),
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
    if speak:
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
                       'hwnd': 0, 'typing': False, 'typed': 0,
                       'field': None, 'menu': None})
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
    ok, said = start(speak=not keep_place)
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
    # **A sub-window is FOLLOWED, not left.** An application that opens a
    # dialog over the window being walked has not taken the user
    # anywhere else: they are still in the same program, in a window that
    # sits on the one they were in. Stopping there gave them a review
    # that vanished exactly when something appeared to read.
    if _owned_by(now, was):
        return not follow(window)
    stop()
    return True


def _owned_by(now, was):
    """Whether the window in front is a sub-window of the one walked.

    Windows says so two ways and both are worth asking: an OWNED window
    (which is what a dialog of the same program is), and a window of the
    same process whose class is the dialog class. A window belonging to
    something else entirely is a different program and is left alone.
    """
    if not now or not was:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.GetWindow.restype = ctypes.c_void_p
        owner = int(user32.GetWindow(ctypes.c_void_p(int(now)), 4) or 0)
        if owner == int(was):
            return True
        buffer = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(ctypes.c_void_p(int(now)), buffer, 64)
        if str(buffer.value) != '#32770':
            return False
        mine = ctypes.wintypes.DWORD()
        theirs = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(int(was)),
                                        ctypes.byref(mine))
        user32.GetWindowThreadProcessId(ctypes.c_void_p(int(now)),
                                        ctypes.byref(theirs))
        return bool(mine.value) and mine.value == theirs.value
    except Exception:                                # noqa: BLE001
        return False


def follow(window):
    """Rebuild for a sub-window that has appeared. ``True`` if it worked.

    Said once, on arriving - not per control - which is the rule the
    dialog and ancestry layers already follow.
    """
    note = {}
    nodes = nodes_of(window, note)
    if not nodes:
        return False
    with _LOCK:
        _state.update({'nodes': nodes, 'at': 0, 'inner': 0,
                       'typing': False, 'field': None, 'menu': None,
                       'title': _text(getattr(window, 'name', '')),
                       'hwnd': int(getattr(window, 'windowHandle', 0) or 0)})
    icons.play('open-object')
    title = _text(getattr(window, 'name', ''))
    # Translators: said on arriving in a window that opened over the one
    # being walked. {title} is what it is called.
    _say(_('{title}, sub-window').format(title=title) if title
         else _('Sub-window'))
    say_here()
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
    # **The plain arrows follow whichever layout is on.** In the simple
    # layout (the default) they step through the list; on the screen
    # layout they go to the control above or below where this one really
    # is; in the interaction layout Down steps INTO the control and Up
    # back out of it, and they never move along the list at all.
    which = layout()
    if which == 'screen':
        return move_vertical(delta)
    if which == 'interact':
        return interact_in() if delta > 0 else interact_out()
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
        _state['letter'] = 0
        _state['moves'] += 1
    return say_here()


def move_page(direction):
    return move(10 if direction > 0 else -10)


def move_end(to_end):
    if layout() == 'interact':
        return interact_end(to_end)
    with _LOCK:
        nodes = _state['nodes']
        if not nodes:
            return _nothing()
        _state['at'] = len(nodes) - 1 if to_end else 0
        _state['inner'] = 0
        _state['moves'] += 1
    return say_here()


def move_inside(delta):
    """Left and Right: through what this control says.

    **The words while there are words, and then the characters.** A row
    with several words is read a word at a time, which is what somebody
    wants from a name, a value or a path. A row that is one word - or the
    END of a row that has run out of them - is read a CHARACTER at a
    time, which is how a spelling, a number or an extension is checked by
    ear. Stopping dead at the last word says nothing about what is in it.
    """
    node = here()
    if node is None:
        return _nothing()
    words = _words_of(node)
    if not words:
        return _by_character(delta)
    with _LOCK:
        at = _state['inner'] + delta
        run_out = at < 0 or at >= len(words)
        if not run_out:
            _state['inner'] = at
            _state['moves'] += 1
            said = words[at]
    if run_out:
        # Off the end of the words is where the characters begin.
        return _by_character(delta)
    _say(said)
    return True, said


def _by_character(delta):
    """One character of the row, and say it. ``(ok, said)``.

    The whole row's text, so a row of one word still reads letter by
    letter and a row whose words have run out carries on into them
    rather than stopping.
    """
    node = here()
    if node is None:
        return _nothing()
    text = ' '.join(part for part in (node.get('name'), node.get('value'))
                    if part)
    if not text:
        return say_here(beep=False)
    with _LOCK:
        at = int(_state.get('letter') or 0) + int(delta)
        if at < 0 or at >= len(text):
            _edge()
            at = max(0, min(at, len(text) - 1))
        _state['letter'] = at
        _state['moves'] += 1
    said = text[at]
    _say(said)
    return True, said


def _words_of(node):
    said = ' '.join(part for part in (node.get('name'), node.get('value'))
                    if part)
    return [word for word in said.split() if word]


# --------------------------------------------------------------------------- #
# Left and Right: by character, and by word with Control
# --------------------------------------------------------------------------- #
# The user reads a control's text the way a caret reads it: the arrows step
# a CHARACTER at a time - a spelling, a number, an extension checked by ear -
# and Control with an arrow steps a WORD, which is what a name, a value or a
# path wants. `move_inside` (words then characters) is kept for anything that
# still calls it, but the keys are these two now.
def move_char(delta):
    """One character of the row's text. ``(ok, said)``."""
    return _by_character(delta)


def move_word(delta):
    """One word of the row's text; the characters where the words run out."""
    node = here()
    if node is None:
        return _nothing()
    words = _words_of(node)
    if not words:
        return _by_character(delta)
    with _LOCK:
        at = int(_state.get('inner') or 0) + int(delta)
        run_out = at < 0 or at >= len(words)
        if not run_out:
            _state['inner'] = at
            _state['letter'] = 0
            _state['moves'] += 1
            said = words[at]
    if run_out:
        return _by_character(delta)
    _say(said)
    return True, said


# --------------------------------------------------------------------------- #
# The screen, spatially: rows, columns, diagonals - and a layout that says
# which of the two the arrows walk
# --------------------------------------------------------------------------- #
# Every control has a place on the screen - a real one from `obj.location`,
# or the rectangle a row was READ at in a picture. So the window can be
# walked as it LOOKS as well as in reading order: Shift with Left/Right is
# the control beside this one on the same line, the numpad diagonals are the
# nearest control in a corner, and Numpad 4/6 switches which the plain arrows
# follow - the reading order (linear) or the screen (spatial).
def _node_rect(node):
    """``(left, top, width, height)`` of a node, or None. Cached on it."""
    if not node:
        return None
    if '_rect' in node:
        return node['_rect']
    rect = None
    given = node.get('rect')
    if given:
        try:
            rect = (int(given[0]), int(given[1]), int(given[2]), int(given[3]))
        except Exception:                            # noqa: BLE001
            rect = None
    if rect is None:
        obj = node.get('obj')
        try:
            location = obj.location
            rect = (int(location.left), int(location.top),
                    int(location.width), int(location.height))
        except Exception:                            # noqa: BLE001
            rect = None
    node['_rect'] = rect
    return rect


def _centre(rect):
    return (rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0)


#: The three ways the arrows can read a window, in the order Numpad 4 and
#: 6 walk them. ``linear`` is the SIMPLE layout: the list as it was read,
#: Up and Down along it, Left and Right through a control's own text.
#: ``screen`` is the picture: Up and Down to the control above and below,
#: Left and Right to the control BESIDE this one on the same line. And
#: ``interact`` is outSPOKEN's: Left and Right between the controls that
#: sit together at one level, Down to step INTO one - its children, and
#: then its words and its characters - and Up to step back out, said as
#: "In, <it>" and "Out of, <it>" so the listener always knows which way
#: they went. One setting for every walked list: the palette and a
#: message ask this module which is on, so the same numpad keys mean the
#: same thing in all of them.
LAYOUTS = ('linear', 'screen', 'interact')


def layout():
    with _LOCK:
        return _state.get('layout', 'linear')


def layout_name(which):
    if which == 'screen':
        # Translators: the layout where the arrows follow the screen.
        return _('Screen layout')
    if which == 'interact':
        # Translators: the layout where Down enters a control and Up leaves.
        return _('Interaction layout')
    # Translators: the layout where the arrows follow the list as read.
    return _('Simple layout')


def layout_cycle(delta=1):
    """The next (or previous) layout, and say which. ``(ok, said)``."""
    with _LOCK:
        now = _state.get('layout', 'linear')
        at = LAYOUTS.index(now) if now in LAYOUTS else 0
        now = LAYOUTS[(at + (1 if delta > 0 else -1)) % len(LAYOUTS)]
        _state['layout'] = now
        _state['depth'] = None
    return True, layout_name(now)


def layout_toggle():
    """The next layout - kept for anything that still calls it."""
    return layout_cycle(1)


def _has_submenu(node):
    """Whether this control is a menu somebody can walk into."""
    if not node:
        return False
    role = str(node.get('role') or '').upper()
    if role in ('MENUBAR', 'MENU', 'POPUPMENU'):
        return True
    if role == 'MENUITEM':
        return 'HASPOPUP' in {str(state).upper()
                              for state in _states_of(node.get('obj'))}
    return False


def open_submenu():
    """Right on a menu: walk into it. ``(ok, said)``.

    A menu item with a submenu is opened the way Windows opens one - the
    right arrow - and the submenu's items become the list. A submenu that
    answers nothing until it is expanded is expanded first, through the
    item's own action, and asked again.
    """
    node = here()
    if not _has_submenu(node):
        return False, ''
    ok, said = open_menu(node)
    if ok:
        return ok, said
    obj = node.get('obj')
    try:
        if int(getattr(obj, 'actionCount', 0) or 0):
            obj.doAction(0)
    except Exception:                                # noqa: BLE001
        pass
    time.sleep(0.15)
    ok, said = open_menu(node)
    if ok:
        return ok, said
    _edge()
    return False, said


def move_across(delta):
    """The plain Left and Right, by layout: a character of this control's
    text in the simple layout, the control BESIDE this one on the screen
    layout, and the next control at this level - or the next word or
    character, once interacting with the text - in the interaction one.

    **A menu is the exception in every layout**: Right on a menu, a menu
    bar or an item with a submenu walks INTO it, and Left inside an
    opened menu comes back out - the keys Windows itself gives a menu.
    """
    if delta > 0 and _depth() is None and _has_submenu(here()):
        ok, said = open_submenu()
        if ok:
            return ok, said
    if delta < 0 and _depth() is None and in_a_menu():
        return close_menu()
    which = layout()
    if which == 'screen':
        return move_line(delta)
    if which == 'interact':
        return move_sibling(delta)
    return move_char(delta)


def move_across_shift(delta):
    """Shift with Left and Right: whichever of the two the plain arrows
    are NOT doing - the control beside this one in the simple layout, and
    a character of the text on the other two."""
    if layout() == 'linear':
        return move_line(delta)
    return move_char(delta)


# --------------------------------------------------------------------------- #
# The interaction layout: Left and Right along one level, Down into a
# control, Up back out of it
# --------------------------------------------------------------------------- #
def _node_text(node):
    return ' '.join(part for part in ((node or {}).get('name'),
                                      (node or {}).get('value')) if part)


def _depth():
    """How far INTO the current control the cursor is: None for the
    control itself, 'words' or 'chars' for its text. It belongs to the
    row it was set on, so any move that lands on another row is back at
    the control without every such move having to know."""
    with _LOCK:
        depth = _state.get('depth')
        at = _state['at']
    if isinstance(depth, tuple) and len(depth) == 2 and depth[1] == at:
        return depth[0]
    return None


def _set_depth(level):
    with _LOCK:
        _state['depth'] = (level, _state['at']) if level else None


def _index_of(node_id):
    with _LOCK:
        for index, node in enumerate(_state['nodes']):
            if node.get('id') == node_id:
                return index
    return None


def _siblings():
    """The indexes of every node at the current control's level."""
    node = here()
    if node is None:
        return []
    parent = node.get('parent')
    with _LOCK:
        return [index for index, other in enumerate(_state['nodes'])
                if other.get('parent') == parent]


def _children_of(node):
    with _LOCK:
        return [index for index, other in enumerate(_state['nodes'])
                if other.get('parent') == node.get('id')]


def _called(node):
    return _text(node.get('name')) or _text(node.get('role'))


def _say_in(name, rest):
    # Translators: said on stepping INTO a control in the interaction
    # layout. {name} is the control; what follows is the first thing in it.
    _say_parts([(_('In {name}').format(name=name), 'place')] + list(rest))


def _say_out(name, rest):
    # Translators: said on stepping OUT of a control in the interaction
    # layout. {name} is the control that was left.
    _say_parts([(_('Out of {name}').format(name=name), 'place')]
               + list(rest))


def move_sibling(delta):
    """Left and Right in the interaction layout."""
    depth = _depth()
    if depth == 'chars':
        return _by_character(delta)
    node = here()
    if node is None:
        return _nothing()
    if depth == 'words':
        words = _words_of(node)
        with _LOCK:
            at = int(_state.get('inner') or 0) + int(delta)
            if at < 0 or at >= len(words):
                _edge()
                at = max(0, min(at, max(len(words) - 1, 0)))
            _state['inner'] = at
            _state['letter'] = 0
            _state['moves'] += 1
        said = words[at] if words else ''
        _say(said)
        return True, said
    level = _siblings()
    with _LOCK:
        at = _state['at']
    if at not in level:
        return say_here(beep=False)
    where = level.index(at) + int(delta)
    if where < 0 or where >= len(level):
        _edge()
        return say_here(beep=False)
    with _LOCK:
        _state['at'] = level[where]
        _state['inner'] = 0
        _state['letter'] = 0
        _state['moves'] += 1
    return say_here()


def interact_end(to_end):
    """Home and End in the interaction layout: the ends of this level."""
    depth = _depth()
    node = here()
    if node is None:
        return _nothing()
    if depth == 'chars':
        text = _node_text(node)
        with _LOCK:
            _state['letter'] = max(len(text) - 1, 0) if to_end else 0
            said = text[_state['letter']] if text else ''
        _say(said)
        return True, said
    if depth == 'words':
        words = _words_of(node)
        with _LOCK:
            _state['inner'] = max(len(words) - 1, 0) if to_end else 0
            _state['letter'] = 0
            said = words[_state['inner']] if words else ''
        _say(said)
        return True, said
    level = _siblings()
    if not level:
        return say_here(beep=False)
    with _LOCK:
        _state['at'] = level[-1] if to_end else level[0]
        _state['inner'] = 0
        _state['letter'] = 0
        _state['moves'] += 1
    return say_here()


def interact_in():
    """Down in the interaction layout: into this control.

    Its children first, where it has any - a group's controls, a list's
    rows - then its words, then their characters. Each step says "In,
    <what was entered>" and the first thing inside it, as one utterance.
    """
    node = here()
    if node is None:
        return _nothing()
    depth = _depth()
    if depth == 'chars':
        _edge()
        return say_here(beep=False)
    if depth == 'words':
        words = _words_of(node)
        with _LOCK:
            inner = int(_state.get('inner') or 0)
        word = words[inner] if 0 <= inner < len(words) else ''
        if not word:
            _edge()
            return say_here(beep=False)
        text = _node_text(node)
        with _LOCK:
            _state['letter'] = max(text.find(word), 0)
        _set_depth('chars')
        _say_in(word, [(word[0], 'name')])
        return True, word[0]
    children = _children_of(node)
    if children:
        with _LOCK:
            _state['at'] = children[0]
            _state['inner'] = 0
            _state['letter'] = 0
            _state['moves'] += 1
        first = here()
        _say_in(_called(node), parts_of(first, at=0, count=len(children)))
        return True, _text(first.get('name'))
    words = _words_of(node)
    if not words:
        _edge()
        return say_here(beep=False)
    with _LOCK:
        _state['inner'] = 0
        _state['letter'] = 0
    _set_depth('words')
    _say_in(_called(node), [(words[0], 'name')])
    return True, words[0]


def interact_out():
    """Up in the interaction layout: out of this control, onto it.

    The reverse of :func:`interact_in`, step for step, said as "Out of,
    <what was left>" and then where the cursor now is.
    """
    node = here()
    if node is None:
        return _nothing()
    depth = _depth()
    if depth == 'chars':
        words = _words_of(node)
        with _LOCK:
            inner = int(_state.get('inner') or 0)
        word = words[inner] if 0 <= inner < len(words) else ''
        _set_depth('words')
        _say_out(word, [(word, 'name')])
        return True, word
    if depth == 'words':
        _set_depth(None)
        with _LOCK:
            at = _state['at']
            count = len(_state['nodes'])
        _say_out(_called(node), parts_of(node, at=at, count=count))
        return True, _text(node.get('name'))
    parent = None
    if node.get('parent') is not None:
        parent = _index_of(node.get('parent'))
    if parent is None:
        _edge()
        return say_here(beep=False)
    with _LOCK:
        _state['at'] = parent
        _state['inner'] = 0
        _state['letter'] = 0
        _state['moves'] += 1
    container = here()
    level = _siblings()
    where = level.index(parent) if parent in level else 0
    _say_out(_called(container),
             parts_of(container, at=where, count=len(level)))
    return True, _text(container.get('name'))


def _spatial_pick(want):
    """Index of the control best matching a direction test, or None.

    ``want(dx, dy)`` is True for a candidate in the wanted direction; the
    nearest such by centre distance, with movement ALONG the wanted axis
    counting for less than movement across it, so "the control below" is
    the one below rather than the one furthest to the side.
    """
    with _LOCK:
        nodes = list(_state['nodes'])
        at = _state['at']
    if not (0 <= at < len(nodes)):
        return None
    here_rect = _node_rect(nodes[at])
    if not here_rect:
        return None
    hx, hy = _centre(here_rect)
    best, best_score = None, None
    for index, node in enumerate(nodes):
        if index == at:
            continue
        rect = _node_rect(node)
        if not rect:
            continue
        cx, cy = _centre(rect)
        dx, dy = cx - hx, cy - hy
        if not want(dx, dy):
            continue
        score = dx * dx + dy * dy
        if best_score is None or score < best_score:
            best, best_score = index, score
    return best


def _go_to(index):
    if index is None:
        _edge()
        return say_here(beep=False)
    with _LOCK:
        _state['at'] = index
        _state['inner'] = 0
        _state['letter'] = 0
        _state['moves'] += 1
    return say_here()


def move_line(delta):
    """The control beside this one on the same row - Shift+Left/Right.

    "The same row" is any control whose vertical middle is within this
    one's height, which is how a reader tells a toolbar's buttons from the
    row above and below without needing them pixel-aligned.
    """
    with _LOCK:
        nodes = list(_state['nodes'])
        at = _state['at']
    rect = _node_rect(nodes[at]) if 0 <= at < len(nodes) else None
    if not rect:
        return _nothing()
    band = max(rect[3], 8)
    _hx, hy = _centre(rect)

    def want(dx, dy):
        return (dx > 0 if delta > 0 else dx < 0) and abs(dy) <= band
    return _go_to(_spatial_pick(want))


def move_vertical(delta):
    """The control above or below - the plain arrows in screen layout."""
    def want(dx, dy):
        return dy > 0 if delta > 0 else dy < 0
    return _go_to(_spatial_pick(want))


def _bounds():
    """The window's own rectangle - the bounding box of every control on
    it - as ``(left, top, right, bottom)``, or None."""
    with _LOCK:
        nodes = list(_state['nodes'])
    left = top = right = bottom = None
    for node in nodes:
        rect = _node_rect(node)
        if not rect:
            continue
        l, t, w, h = rect
        r, b = l + w, t + h
        left = l if left is None else min(left, l)
        top = t if top is None else min(top, t)
        right = r if right is None else max(right, r)
        bottom = b if bottom is None else max(bottom, b)
    if left is None:
        return None
    return left, top, right, bottom


def corner_name(dx_sign, dy_sign):
    """What a corner is called, said before the control that is in it."""
    if dy_sign > 0:
        # Translators: a corner of the window, said before what is in it.
        return _('Bottom right') if dx_sign > 0 else _('Bottom left')
    # Translators: a corner of the window, said before what is in it.
    return _('Top right') if dx_sign > 0 else _('Top left')


def _window_box():
    """``(left, top, right, bottom)`` of the window - its own rectangle
    where it is known, the bounding box of its controls where not."""
    with _LOCK:
        rect = _state.get('window_rect')
    if rect:
        return rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]
    return _bounds()


def _visible(rect, box):
    """Whether a control's rectangle is really on the window."""
    l, t, w, h = rect
    if w <= 0 or h <= 0:
        return False
    if box is None:
        return True
    left, top, right, bottom = box
    return l < right and l + w > left and t < bottom and t + h > top


def move_diagonal(dx_sign, dy_sign):
    """The control in a CORNER of the window - the numpad diagonals.

    Numpad 7/9/1/3 go to the four corners of the window itself, not to the
    nearest control diagonally from this one: the user asked for the
    corners, which is how somebody who cannot see the window jumps to where
    the OK button, the title, the first item or the status line is.

    Two things decide it, both learned from corners that landed wrong:

    * **The corner is the WINDOW's**, never the bounding box of the
      controls. A list's rows scrolled out of view report rectangles far
      below the window, so a box drawn round every control reached down
      to the last invisible row and "bottom left" was a row nobody could
      see. Only a control really on the window is a candidate.
    * **The control's OWN corner is measured**, not its centre. Measured
      by centres, a small button anywhere near the corner beat the list
      that actually fills it; measured by its own corner, the control
      that sits IN the corner wins, and a tie between a large one and a
      small one there goes to the small one - the status line over the
      list it sits under.

    The corner's name is said first, in the same utterance.
    """
    box = _window_box()
    if box is None:
        return _nothing()
    left, top, right, bottom = box
    cx = right if dx_sign > 0 else left
    cy = bottom if dy_sign > 0 else top
    with _LOCK:
        nodes = list(_state['nodes'])
    best, best_score = None, None
    for index, node in enumerate(nodes):
        rect = _node_rect(node)
        if not rect or not _visible(rect, box):
            continue
        l, t, w, h = rect
        own_x = l + w if dx_sign > 0 else l
        own_y = t + h if dy_sign > 0 else t
        score = ((own_x - cx) ** 2 + (own_y - cy) ** 2, w * h)
        if best_score is None or score < best_score:
            best, best_score = index, score
    if best is None:
        return _nothing()
    with _LOCK:
        _state['at'] = best
        _state['inner'] = 0
        _state['letter'] = 0
        _state['moves'] += 1
    return say_here(prefix=[(corner_name(dx_sign, dy_sign), 'place')])


def explore(x, y):
    """A finger at a point on the screen: the control under it, said.

    The SMALLEST control whose rectangle holds the point, because a window
    holds a pane holds a list holds the row, and the row is what the
    finger is on. Said only when it is a different control from the last
    one explored - a finger resting on a button must not read it thirty
    times a second. The cursor moves with the finger, so a double tap
    presses what was just found. ``(ok, said)``.
    """
    with _LOCK:
        nodes = list(_state['nodes'])
        box = _state.get('window_rect')
    box = (box[0], box[1], box[0] + box[2], box[1] + box[3]) if box else None
    best, best_area = None, None
    for index, node in enumerate(nodes):
        rect = _node_rect(node)
        if not rect or not _visible(rect, box):
            continue
        l, t, w, h = rect
        if not (l <= x < l + w and t <= y < t + h):
            continue
        area = w * h
        if best_area is None or area < best_area:
            best, best_area = index, area
    if best is None:
        return False, ''
    with _LOCK:
        if _state.get('explored') == best and _state['at'] == best:
            return True, ''
        _state['explored'] = best
        _state['at'] = best
        _state['inner'] = 0
        _state['letter'] = 0
        _state['moves'] += 1
    return say_here()


def click_mouse():
    """Numpad 5: a real mouse click on the control - double on a quick second.

    A click is a different thing from Enter (which does the control's own
    action, or clicks when it has none): it is the mouse, at the control's
    place, which is the only thing that reaches a control drawn in a picture
    or one whose action the toolkit does not expose. Two presses inside
    :data:`DOUBLE_CLICK` are a double click, as they are anywhere.
    """
    now = time.time()
    with _LOCK:
        double = (now - float(_state.get('clicked_at') or 0.0)) < DOUBLE_CLICK
        _state['clicked_at'] = now
    ok, why = click_here(double=double)
    if not ok:
        return False, _refusal(why) if '_refusal' in globals() else why
    # Translators: said after a double mouse click.
    # Translators: said after a single mouse click.
    return True, (_('Double-clicked') if double else _('Clicked'))


#: Two Numpad-5 presses closer together than this are a double click.
DOUBLE_CLICK = 0.4


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
    # **A menu bar is walked into, not pressed.** Pressing it opens the
    # real menu and takes the keyboard out of the review; what somebody
    # walking a window wants from the menu bar is to see what is ON it -
    # so its menus become the list, and Escape comes back out. The same
    # shape the described application's review uses, because a flyout is
    # a menu a keyboard cannot follow.
    if str(node.get('role') or '').upper() in ('MENUBAR', 'MENU',
                                               'POPUPMENU'):
        ok, said = open_menu(node)
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


#: How long the guest is given to notice where the pointer is before the
#: button event. Two moves with this between them, because one move plus
#: an immediate click is acted on at the guest's old position.
POINTER_SETTLES = 0.05


def _in_a_virtual_machine():
    """Whether the window being walked is another computer's screen."""
    try:
        from . import surface
        return bool(surface.is_virtual_machine(_foreground()))
    except Exception:                                # noqa: BLE001
        return False


def click_here(double=False):
    """Click the middle of the control the cursor is on, then put the
    mouse back where it was. ``double`` clicks twice.

    Through NVDA's own `winUser`, so it is the same click NVDA's own
    "click where the review cursor is" makes - and without telling
    NVDA the pointer moved, which is what makes it a press rather
    than a press followed by the reader narrating whatever the mouse
    landed on.
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
        import winUser
    except Exception as error:                       # noqa: BLE001
        return False, 'this NVDA has no winUser: %s' % error
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
    x, y = left + width // 2, top + height // 2
    try:
        winUser.setCursorPos(x, y)
        # **A virtual machine has to be TOLD where the pointer is before
        # it is told a button went down.** The guest tracks the host
        # pointer through its own driver, and a button event that arrives
        # in the same breath as the move is acted on at wherever the
        # guest's pointer still was - which is exactly "it clicks in the
        # guest, but not on the thing I am on". So the position is set,
        # given a moment to be noticed, and set again: the second move is
        # what makes the first one true.
        if _in_a_virtual_machine():
            time.sleep(POINTER_SETTLES)
            winUser.setCursorPos(x, y)
            time.sleep(POINTER_SETTLES)
        # **NVDA is deliberately NOT told the mouse moved.**
        # `mouseHandler.executeMouseMoveEvent` exists to make the reader
        # announce whatever is under the pointer, which is the last thing
        # anybody wants from a click made on their behalf: it read out
        # the object the pointer happened to land on instead of what was
        # pressed, and inside a window whose objects come and go it
        # raised in NVDA's own event handler (`_get__storyFieldsAndRects`,
        # 'NoneType' has no 'helperLocalBindingHandle') four times per
        # press. The pointer is put back straight afterwards anyway, so
        # there is no move to report.
        # **`dwData` and `dwExtraInfo` are DWORDs, and `None` is not a
        # DWORD.** Passing them raised `argument 4: TypeError: an integer
        # is required` on EVERY press - caught by the `except` below,
        # answered as False, and reported as "Nothing could be done
        # here". So Enter in a window read as a picture - which is the
        # whole of pressing anything inside a virtual machine - never
        # once clicked, and said the least useful true sentence there is
        # about why. `smart.py` had it right beside it the whole time.
        winUser.mouse_event(winUser.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        winUser.mouse_event(winUser.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
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
    name = node.get('name')
    if not name:
        # **A picture says what it shows.** A row that is an icon and has
        # no name is a row somebody arrows onto and is told "graphic" -
        # and the system icons are exactly the ones that can be named for
        # nothing: a warning, a folder, a printer, an hourglass.
        try:
            from . import iconNames
            ok, shows = iconNames.describe(node.get('obj'))
            if ok:
                name = shows
        except Exception:                            # noqa: BLE001
            pass
    if name:
        parts.append((name, 'name'))
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


def say_here(beep=True, prefix=None):
    """Say the control the cursor is on. ``prefix`` is ``[(text, class)]``
    said in FRONT of it, in the same utterance - the corner's name, for
    one - so nothing can cut it off."""
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
    parts = list(prefix or []) + parts_of(node, at=at, count=count)
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

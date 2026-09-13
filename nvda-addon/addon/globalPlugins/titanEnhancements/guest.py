# -*- coding: utf-8 -*-
"""Inside the guest: the pointer as the reader.

A virtual machine's window is another computer's screen, and a screen is
pixels. :mod:`surface` answers "what is on this screen" by photographing
the whole of it, which is the right answer for arriving in a window and
the wrong one for the question somebody working IN a guest asks all day:
**what am I on now**. The moment the guest takes the keyboard - VMware's
own Ctrl+G, which is the key this is bound to - a reader has nothing at
all to say, and reading the whole screen again for every step is seconds
of work to answer a question about one row of it.

So: the pointer. Two things about it can be known from the HOST, exactly
and for almost nothing.

* **What it is SHOWING.** A cursor is an icon, and a virtual machine
  passes the guest's cursor through to the host as a real ``HCURSOR`` -
  so an I-beam means a text field, a hand means something to press, an
  hourglass means the guest is busy. That is the CONTROL, named without
  reading a pixel of text.
* **Where it IS.** Which gives the one strip of the guest's screen worth
  reading - the row the pointer is on - instead of the whole of it.
  Measured: a strip is a fraction of the window, and Windows' own
  recogniser answers it in a few tens of milliseconds.

**The shape is compared two ways, and the second is why this works at
all.** :func:`iconNames.cursor_now` compares HANDLES, which is exact and
free - Windows' own cursors are shared, so the handle the pointer is
using IS the handle `LoadCursorW` hands back. A guest's cursor is not one
of those: the virtual machine builds it from the guest's own bitmap, so
it is a handle nobody else has ever seen, and comparing handles answers
nothing inside a guest - which is the whole of "the reader says nothing
in a VM". So where the handle is unknown the cursor is DRAWN and compared
against the standard shapes drawn the same way, which is the technique
:mod:`dialog_kind` already proved on dialog icons.

**Nothing here ever reads the guest's memory, installs anything in it, or
needs its tools.** It is the host's own pointer and the host's own
picture of a window it already owns.
"""

import threading
import time

from . import i18n

_ = i18n.install(globals())

_LOCK = threading.RLock()

#: What a cursor shape means, as the word for the CONTROL rather than for
#: the picture. `iconNames` names the picture ("text cursor"); somebody
#: working in a guest wants to be told what they are on.
def kinds():
    return {
        # Translators: what an I-beam pointer is resting on.
        'text cursor': _('edit box'),
        # Translators: what a hand pointer is resting on.
        'hand': _('link'),
        # Translators: said when the guest is busy.
        'hourglass': _('busy'),
        # Translators: said when the guest is busy but still answering.
        'busy': _('busy'),
        # Translators: what a crosshair pointer is resting on.
        'crosshair': _('drawing area'),
        # Translators: what a resize pointer is resting on.
        'resize': _('edge'),
        # Translators: what a move pointer is resting on.
        'move': _('movable'),
        # Translators: said when the pointer says this cannot be done.
        'not allowed': _('not allowed'),
        # Translators: what a help pointer is resting on.
        'help': _('help'),
    }

#: An ordinary arrow says nothing about what is under it, so it is not in
#: the table above and nothing is said for it - the words read off the
#: screen are the whole answer there.

#: How tall a strip around the pointer is read, in pixels of the SCREEN.
#: A row of a list, a menu entry or a field is about this tall on any
#: guest anybody runs; taller pulls in the row above and below, which is
#: worse than reading one line too few.
STRIP = 46

#: How often the guest is looked at. It is a capture and a fingerprint -
#: measured 16 ms on a 640x480 guest, and held there on a bigger one by
#: `BLOCKS_ACROSS` - so this is the rate at which a selection moving is
#: noticed, and it is deliberately not faster than somebody can listen.
TICK = 0.3

#: Two readings closer together than this are one movement, not two.
QUIET = 0.35

#: How long a strip reading may stand before it is read again even though
#: nothing seems to have moved - a guest can repaint under a still
#: pointer.
STALE = 4.0

_state = {'on': False, 'hwnd': 0, 'product': '', 'at': (0, 0),
          'shape': '', 'said': '', 'when': 0.0, 'read_at': 0.0}
_counted = {'entered': 0, 'looks': 0, 'said': 0, 'read': 0, 'why': ''}
_watcher = None
_stop = threading.Event()
_cursor_references = []


def report():
    with _LOCK:
        found = dict(_counted)
        found['model'] = {'used': _model['used'], 'why': _model['why'],
                          'kept': _model['reading'] is not None}
        found.update({'inside': _state['on'], 'window': _state['hwnd'],
                      'product': _state['product'],
                      'shape': _state['shape'], 'last': _state['said'][:60]})
    try:
        from . import vmware
        found['vmware'] = vmware.report()
    except Exception as error:                       # noqa: BLE001
        found['vmware'] = {'why': str(error)}
    return found


def forget():
    """For the tests."""
    global _cursor_references
    with _LOCK:
        _state.update({'on': False, 'hwnd': 0, 'product': '', 'at': (0, 0),
                       'shape': '', 'said': '', 'when': 0.0, 'read_at': 0.0})
        for key in _counted:
            _counted[key] = 0 if key != 'why' else ''
        _model.update({'at': 0.0, 'used': 0, 'why': '', 'reading': None,
                       'hwnd': 0})
        _seen.update({'hwnd': 0, 'blocks': None, 'ground': None,
                      'at': 0.0, 'size': (0, 0)})
        del _cursor_references[:]


def wanted():
    """Whether the user has asked for this at all."""
    try:
        from . import configSpec
        return bool(configSpec.read().get('guestCursor', False))
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Which window is a guest's screen
# --------------------------------------------------------------------------- #
#: Window class -> what the product is CALLED, for the one sentence that
#: names it. `surface` already knows which classes are a virtual machine
#: and which child the guest is painted on; this is only the name.
PRODUCTS = {
    'VMUIFrame': 'VMware',
    'MKSEmbedded': 'VMware',
    'MKSWindow': 'VMware',
    'VMwareUnityView': 'VMware',
    'VirtualBoxVM': 'VirtualBox',
    'QemuWindowClass': 'QEMU',
}


def _text(value):
    return str(value or '').strip()


def product_of(obj):
    """What virtual machine this is, by name, or ''."""
    from . import surface
    if obj is None or not surface.is_virtual_machine(obj):
        return ''
    seen = obj
    for _step in range(8):
        if seen is None:
            break
        name = PRODUCTS.get(_text(getattr(seen, 'windowClassName', '')))
        if name:
            return name
        seen = getattr(seen, 'parent', None)
    try:
        app = _text(getattr(getattr(obj, 'appModule', None), 'appName', ''))
    except Exception:                                # noqa: BLE001
        app = ''
    # Named by its own program where the class is one nobody wrote down.
    # Empty rather than a word for "a virtual machine": the caller puts
    # this INTO a sentence, and a language with cases cannot take a
    # generic noun there - "W maszyna wirtualna" is what that gives. The
    # sentence for "one we cannot name" is written out whole instead.
    return app.title()


def display_of(obj):
    """The window the guest's screen is painted on, and its handle."""
    from . import surface
    where = surface.display_of(obj)
    return where, _handle(where)


def _handle(obj):
    try:
        return int(getattr(obj, 'windowHandle', 0) or 0)
    except Exception:                                # noqa: BLE001
        return 0


# --------------------------------------------------------------------------- #
# What the pointer is showing
# --------------------------------------------------------------------------- #
def _cursor_info():
    """``(handle, x, y)`` of the pointer right now, or ``(0, 0, 0)``."""
    try:
        import ctypes

        class _INFO(ctypes.Structure):
            _fields_ = [('cbSize', ctypes.c_uint),
                        ('flags', ctypes.c_uint),
                        ('hCursor', ctypes.c_void_p),
                        ('x', ctypes.c_long), ('y', ctypes.c_long)]
        info = _INFO()
        info.cbSize = ctypes.sizeof(_INFO)
        if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(info)):
            return 0, 0, 0
        return int(info.hCursor or 0), int(info.x), int(info.y)
    except Exception:                                # noqa: BLE001
        return 0, 0, 0


def _standard_cursors():
    """The standard shapes, DRAWN once, as ``[(word, picture)]``.

    Drawn rather than compared by handle because the pointer inside a
    guest never has one of these handles: the virtual machine makes its
    own cursor out of the guest's bitmap. Once per session - this is
    asked whenever the pointer changes shape.
    """
    with _LOCK:
        if _cursor_references:
            return list(_cursor_references)
    from . import dialog_kind
    from . import iconNames
    import ctypes
    made = []
    try:
        user32 = ctypes.windll.user32
        user32.LoadCursorW.restype = ctypes.c_void_p
    except Exception:                                # noqa: BLE001
        return []
    for number, word in iconNames.CURSORS:
        try:
            handle = int(user32.LoadCursorW(None,
                                            ctypes.c_void_p(number)) or 0)
        except Exception:                            # noqa: BLE001
            continue
        if not handle:
            continue
        picture = dialog_kind._drawn(handle)
        if picture:
            made.append((word, picture))
    with _LOCK:
        del _cursor_references[:]
        _cursor_references.extend(made)
    return list(made)


def shape_of(handle):
    """What that cursor is showing, in a word. ``''`` for unknown.

    The handle first - exact, two numbers compared - and the PICTURE where
    the handle is nobody's: that is every cursor inside a guest.
    """
    if not handle:
        return ''
    from . import iconNames
    import ctypes
    try:
        user32 = ctypes.windll.user32
        user32.LoadCursorW.restype = ctypes.c_void_p
        for number, word in iconNames.CURSORS:
            known = int(user32.LoadCursorW(None,
                                           ctypes.c_void_p(number)) or 0)
            if known and known == handle:
                return word
    except Exception:                                # noqa: BLE001
        pass
    from . import dialog_kind
    try:
        picture = dialog_kind._drawn(handle)
    except Exception:                                # noqa: BLE001
        return ''
    if not picture:
        return ''
    try:
        return dialog_kind._closest(picture, _standard_cursors())
    except Exception:                                # noqa: BLE001
        return ''


def shape_now():
    """What the pointer is showing this instant."""
    handle, _x, _y = _cursor_info()
    return shape_of(handle)


# --------------------------------------------------------------------------- #
# What is written where the pointer is
# --------------------------------------------------------------------------- #
def _rect_of(hwnd):
    from . import localOcr
    return localOcr._window_rect(hwnd)


def strip_for(hwnd, y):
    """The rectangle to read - the row the pointer is on.

    The full width of the guest's screen and :data:`STRIP` tall, because
    what a row SAYS is very often not under the pointer: a list's tick, a
    menu's shortcut and a form's label all sit away from where the mouse
    is, and reading only the few pixels under it answers with a word out
    of the middle of a sentence.
    """
    rect = _rect_of(hwnd)
    if rect is None:
        return None
    left, top, right, bottom = rect
    if right - left < 2 or bottom - top < 2:
        return None
    half = STRIP // 2
    band_top = max(top, min(int(y) - half, bottom - STRIP))
    height = min(STRIP, bottom - band_top)
    if height < 4:
        return None
    return left, band_top, right - left, height


#: How often the model may be asked, at most. It is a second or two on a
#: thread of its own, and a guest whose every row needs it is one where
#: the pointer would otherwise be answered later than it moved.
MODEL_EVERY = 6.0

#: How long one whole-guest model reading stands. **Longer than the read
#: itself**, or it expires before another one could even be asked for and
#: nothing is ever reused. Measured on a real 640x480 Windows 95 guest:
#: the model took **4.6 seconds** for the whole screen and read all 17
#: lines of its desktop correctly, so four seconds was the wrong number
#: and eight is the right one - a list walked with the arrows is answered
#: out of one reading.
MODEL_KEPT = 8.0

_model = {'at': 0.0, 'used': 0, 'why': '', 'reading': None, 'hwnd': 0}


def _by_model(hwnd):
    """The WHOLE guest, read by Titan's own model, and kept.

    **A guest is exactly what Windows' recogniser is worst at.** It is
    somebody else's screen at somebody else's resolution, painted into a
    window and very often scaled down - and Windows' engine is built for
    documents on this one. Titan carries a real OCR model for precisely
    this and both readers already reach it, so it is the SECOND question
    here: asked only when the first came back with nothing.

    **The whole screen rather than the strip, and kept between moves.**
    The model is a second or two whatever it is given, so asking it per
    row would answer the pointer later than the pointer moved. Asked once
    for the whole guest, every row is then in hand and the next twenty
    moves are free - which is the opposite of what the fast path wants
    and the right trade for the slow one.

    ``None`` when it cannot, and the caller then says nothing.
    """
    from . import localOcr
    now = time.time()
    with _LOCK:
        kept = _model['reading']
        if kept is not None and _model['hwnd'] == hwnd \
                and now - _model['at'] < MODEL_KEPT:
            return kept
        if now - _model['at'] < MODEL_EVERY:
            return None
        _model['at'] = now
    try:
        reading = localOcr.read_window_model(hwnd)
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _model['why'] = '%s: %s' % (type(error).__name__, error)
        return None
    if not reading:
        return None
    with _LOCK:
        _model.update({'reading': reading, 'hwnd': hwnd, 'used':
                       _model['used'] + 1, 'at': time.time()})
    return reading


def words_at(hwnd, y):
    """What is written on the pointer's row. ``''`` when nothing is."""
    from . import localOcr
    where = strip_for(hwnd, y)
    if where is None:
        return ''
    with _LOCK:
        _counted['read'] += 1
    try:
        # **The guest's OWN picture, not the screen's.** Measured on a
        # real VMware guest sitting behind a terminal: a screen capture
        # of the guest's rectangle came back as the terminal's text, and
        # would have been announced as though it were the guest.
        reading = localOcr.read(*where, hwnd=hwnd)
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _counted['why'] = '%s: %s' % (type(error).__name__, error)
        reading = None
    if not reading:
        # Nothing is not always nothing: in a guest it is very often
        # Windows' own engine failing on somebody else's screen.
        reading = _by_model(hwnd)
    if not reading:
        return ''
    rows = reading.rows()
    if not rows:
        return ''
    # The row nearest the pointer, which on a strip this tall is nearly
    # always the only one - but a menu with tight rows can fit two, and
    # the wrong one of two is worse than a slightly short answer.
    best, distance = '', None
    for text, (_left, top, _width, height) in rows:
        middle = top + height / 2.0
        gap = abs(middle - y)
        if distance is None or gap < distance:
            best, distance = text, gap
    return _text(best)


# --------------------------------------------------------------------------- #
# Saying it
# --------------------------------------------------------------------------- #
def sentence(words, shape):
    """What to say about the pointer: what is there, and what it is."""
    said = _text(words)
    kind = kinds().get(shape, '')
    if said and kind:
        # Translators: what the pointer is on inside a virtual machine.
        # {what} is what is written there, {kind} what sort of control it
        # is - "Username, edit box".
        return _('{what}, {kind}').format(what=said, kind=kind)
    if said:
        return said
    if kind:
        return kind
    return ''


def _say(text):
    from . import dialogs
    dialogs.report(str(text or ''))


def look(say=True, force=False):
    """Read the pointer's row and say what is there. ``(ok, said)``."""
    with _LOCK:
        hwnd = _state['hwnd']
        _counted['looks'] += 1
    if not hwnd:
        return False, ''
    handle, x, y = _cursor_info()
    if not on_the_guest(hwnd, x, y):
        return False, ''
    shape = shape_of(handle)
    words = words_at(hwnd, y)
    said = sentence(words, shape)
    if not said:
        return False, ''
    now = time.time()
    with _LOCK:
        same = (said == _state['said'])
        recent = (now - _state['when']) < QUIET
        _state.update({'shape': shape, 'at': (x, y), 'read_at': now})
        if same and not force:
            return False, ''
        if recent and not force:
            return False, ''
        _state['said'] = said
        _state['when'] = now
        _counted['said'] += 1
    if say:
        _say(said)
    return True, said


# --------------------------------------------------------------------------- #
# Following it
# --------------------------------------------------------------------------- #
def inside():
    with _LOCK:
        return bool(_state['on'])


def on_the_guest(hwnd, x, y):
    """Whether the pointer is really on the guest's screen.

    The host's own half of a virtual machine's window - its menu bar, its
    tabs, its status line - is ordinary and NVDA reads it perfectly well.
    Reading a strip of it as though it were a guest would be this layer
    talking over a reader that was already doing better.
    """
    rect = _rect_of(hwnd)
    if rect is None:
        return False
    left, top, right, bottom = rect
    return left <= x < right and top <= y < bottom


def _refused(why):
    """Why this window was not taken up. **The one thing a silent reader
    cannot be asked.** "It says nothing in my VM" wears at least four
    different faults - the setting, the window not being recognised, its
    screen not being found, and the reading being empty - and only a
    record of which says them apart."""
    with _LOCK:
        _counted['why'] = str(why)
    return False


def consider(obj):
    """A virtual machine is in front: follow the pointer in it.

    **There is no key.** Ctrl+G is VMware's own and belongs to VMware;
    what a reader has to do is notice that the window in front is another
    computer's screen, which it can do by itself. So this is called from
    `event_foreground` and from nowhere else, and turning the setting on
    is the whole of what the user does.
    """
    from . import surface
    with _LOCK:
        _counted['asked'] = _counted.get('asked', 0) + 1
    if not wanted():
        _refused('the setting is off')
        return False
    try:
        # **A guest, a game and a window that draws its own interface are
        # one problem.** All three are a picture with a highlight in it
        # and no focus event behind it, and the user named all three. A
        # virtual machine is the certain case (it says what it is); a
        # window that exposes nothing at all is the other one, and
        # `surface` already decides that carefully - a terminal, a
        # browser and a dialog all have controls and are none of our
        # business.
        vm = surface.is_virtual_machine(obj)
        drawn = False if vm else surface.looks_drawn(obj)
        if not (vm or drawn):
            _refused('not a guest and not a drawn window')
            return False
    except Exception as error:                       # noqa: BLE001
        _refused('%s: %s' % (type(error).__name__, error))
        return False
    ok, _said = enter(obj)
    if not ok:
        _refused('its screen could not be found')
    return ok


def enter(obj, product='', say=True):
    """Start following the pointer on this guest's screen.

    ``(ok, said)``. False when this is not a guest's window or the user
    has not asked for it.
    """
    global _watcher
    if not wanted():
        return False, ''
    where, hwnd = display_of(obj)
    if not hwnd:
        return False, ''
    name = product or _named(obj, hwnd)
    with _LOCK:
        already = _state['on'] and _state['hwnd'] == hwnd
        _state.update({'on': True, 'hwnd': hwnd, 'product': name,
                       'said': '', 'when': 0.0})
        if not already:
            _counted['entered'] += 1
    if say and not already:
        if not name:
            try:
                from . import surface
                name = '' if surface.is_virtual_machine(obj) else _('drawn window')
            except Exception:                        # noqa: BLE001
                name = ''
        if name:
            # Translators: said on going into a virtual machine's screen.
            # {what} is the virtual machine's own name, like "VMware".
            _say(_('In {what}').format(what=name))
        else:
            # Translators: the same, for one whose name is not known.
            _say(_('In a virtual machine'))
    _take_over()
    _stop.clear()
    with _LOCK:
        running = _watcher is not None and _watcher.is_alive()
    if not running:
        _watcher = threading.Thread(target=_follow, name='TitanGuest',
                                    daemon=True)
        _watcher.start()
    return True, ''


def _named(obj, hwnd):
    """What to call this machine: its OWN name where VMware will say it.

    `product_of` answers the PRODUCT - "VMware" - which is the same sentence
    whichever of three guests the user has open. VMware itself knows the
    machine's display name ("Windows 95"), and that is what somebody with a
    Windows 95 and a Debian open needs to hear. It is asked beside the
    reading, never on it (`vmware.warm`), so the first arrival says the
    product and every one after it says the machine.
    """
    try:
        from . import vmware
        own = vmware.name_now(hwnd)
        if not own:
            vmware.warm(hwnd)
    except Exception:                                # noqa: BLE001
        own = ''
    return own or product_of(obj)


def _take_over():
    """Stop `surface` polling the same window, because this is better.

    **Both read the guest; they answer different questions.** The
    watcher polls and announces what CHANGED, which on a real Windows 95
    guest meant it said "Window-Eyes 2:42 AM" - the clock ticking - 13
    times while the user was arrowing through icons and being told
    nothing about them. Measured, on the live machine, with
    `surface: {watching: 465420, reads: 48, changed: 9, said: 13}`.

    This answers the KEY and the pointer, and says the highlighted row -
    which is what somebody moving through icons is asking about. So it
    takes the window over rather than standing aside from it, and the
    watcher has it back at the next foreground change once this is out.

    **This used to be the other way round** and that was the bug: a
    stand-down rule reading "never on top of the watcher" meant the
    watcher being busy with the clock kept the better reader from
    running at all.
    """
    try:
        from . import surface
        if int((surface.report() or {}).get('watching') or 0):
            surface.stop_now()
            with _LOCK:
                _counted['took_over'] = _counted.get('took_over', 0) + 1
            return True
    except Exception:                                # noqa: BLE001
        pass
    return False


def leave(say=False):
    """Stop following. Idempotent."""
    with _LOCK:
        was = _state['on']
        _state.update({'on': False, 'said': '', 'shape': ''})
    _stop.set()
    if was and say:
        # Translators: said on coming back out of a virtual machine.
        _say(_('Out of the guest'))
    return was


stop = leave


def _follow():
    """Watch the pointer while the guest has it.

    On a thread of its own because reading a strip is a picture and a
    recogniser, and the reader's own thread is where speech and every
    event handler live. Nothing here speaks directly: :func:`look` goes
    through `dialogs.report`, which marshals.
    """
    last = (None, None, '')
    while not _stop.wait(TICK):
        if not inside():
            return
        try:
            handle, x, y = _cursor_info()
            shape = shape_of(handle)
            with _LOCK:
                hwnd = _state['hwnd']
                since = time.time() - _state['read_at']
            if not hwnd:
                continue
            if not on_the_guest(hwnd, x, y):
                # On the host's own half of the window, where NVDA is
                # reading properly already.
                last = (x, y, shape)
                continue
            # **The picture itself, because the keys may never reach
            # us.** A virtual machine that has grabbed the keyboard has
            # its OWN low-level hook, and whichever hook was installed
            # last is called first - so inside a grabbed guest the
            # reader may not see the arrow keys at all. The one thing
            # that is always true is that the screen changed, so that is
            # what is watched. A key, when it does reach us, only makes
            # the same question be asked sooner.
            if after_key(say=True)[0]:
                last = (x, y, shape)
                continue
            # A row is a row: moving along it says nothing new, and a
            # reader that repeated itself on every pixel would be
            # unusable. What counts as a move is a different ROW, a
            # different shape, or long enough that the guest may have
            # repainted under a still pointer.
            moved = (last[1] is None or abs(y - last[1]) >= STRIP // 2
                     or shape != last[2] or since > STALE)
            if not moved:
                continue
            last = (x, y, shape)
            look(say=True)
        except Exception as error:                   # noqa: BLE001
            with _LOCK:
                _counted['why'] = '%s: %s' % (type(error).__name__, error)


def crossing(obj):
    """Called when the foreground changes. Leaves a guest we have left.

    A window that is not this guest's is a guest we are no longer in, and
    a watcher left running would be reading somebody else's screen.
    """
    if not inside():
        return False
    try:
        from . import surface
        if surface.is_virtual_machine(obj):
            _where, hwnd = display_of(obj)
            with _LOCK:
                same = hwnd and hwnd == _state['hwnd']
            if same:
                return False
    except Exception:                                # noqa: BLE001
        pass
    return leave()


# --------------------------------------------------------------------------- #
# The keyboard: what the ARROWS moved onto
# --------------------------------------------------------------------------- #
"""Following the pointer answers "what is under my mouse". It answers
nothing at all about the arrow keys, and arrowing through the icons on a
guest's desktop, the entries of its Start menu or the options of a game
is how these windows are really used - the mouse never moves.

**Nothing on the host changes when it happens.** There is no focus event,
no caret, no object: the guest draws a new highlight and that is the
whole of it. So the only thing that can be read is the picture, and the
only cheap moment to read it is the instant after a key that could have
moved something.

This is the method the patent literature calls active-element detection
and Jieshuo's "virtual screen" does on Android: **a key, then the frame,
then OCR of what CHANGED.** Three things are asked in order, and the
first that answers wins:

1. **What is highlighted.** `virtualInput.highlights` finds the row whose
   background is unlike the window's own, which in a drawn interface IS
   the selection - there is nothing else in a picture that says which
   entry the arrows are on. `localOcr` already marks every reading with
   it; nothing had ever read it here.
2. **What changed.** Where no highlight can be told - a game that marks
   its choice with an arrow or a colour rather than a bar - the rows that
   are new since the last reading are what the key did.
3. **Nothing.** Which is said by saying nothing: an arrow inside a text
   field changes a caret and no rows, and a reader that spoke on every
   keystroke would be unusable exactly where people type most.
"""

#: What a reading is kept as, so the NEXT key can say what changed.
_before = {'hwnd': 0, 'rows': (), 'at': 0.0}

#: How long after the key the picture is looked at. Long enough for the
#: guest to have painted the new highlight - it is another computer, and
#: a repaint crosses a virtual display - and short enough to feel like an
#: answer to the key rather than an afterthought.
SETTLE = 0.22

#: A reading older than this says nothing about what just changed.
BEFORE_KEPT = 20.0


def following():
    """Whether the keys are worth borrowing right now."""
    with _LOCK:
        return bool(_state['on'] and _state['hwnd'])


def _read_now(hwnd):
    """The whole window, by whichever tier can answer. ``None`` for none.

    **Exact first.** A guest in a text mode - a BIOS menu, DOS, an operating
    system being installed - is 80 by 25 character CELLS of shapes that have
    not changed since 1987, and `guestNative` reads those by matching the
    real VGA glyphs: no model, no request to anybody's provider, rectangles
    that are the characters' own, and the highlighted row read off the
    attribute rather than guessed from pixels. It answers None for anything
    it cannot be certain of, which is what leaves a graphics screen to the
    recogniser and the model behind it.
    """
    exact = None
    try:
        from . import guestNative
        rect = _rect_of(hwnd)
        where = (rect[0], rect[1]) if rect else (0, 0)
        exact = guestNative.read_window(hwnd, where[0], where[1])
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _counted['why'] = 'the exact tier: %s' % error
    if exact:
        with _LOCK:
            _counted['exact'] = _counted.get('exact', 0) + 1
        return exact
    from . import localOcr
    try:
        reading = localOcr.read_window(hwnd)
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _counted['why'] = '%s: %s' % (type(error).__name__, error)
        reading = None
    if not reading:
        reading = _by_model(hwnd)
    return reading or None


def _rows_of(reading):
    return tuple(text for text, _rect in reading.rows()) if reading else ()


def selected_in(reading):
    """The row a highlight is on, or ''.

    **The one thing in a picture that says what is selected.** A drawn
    interface marks the entry the arrows are on by inverting its
    background and by nothing else, so the highlighted rectangle and the
    row of words inside it are the answer.
    """
    if not reading:
        return ''
    marks = getattr(reading, 'highlights', None) or []
    if not marks:
        return ''
    for text, (_left, top, _width, height) in reading.rows():
        middle = top + height / 2.0
        for _mleft, mtop, _mwidth, mheight in marks:
            if mtop <= middle <= mtop + mheight:
                said = _text(text)
                if said:
                    return said
    return ''


def changed_in(reading, hwnd):
    """The rows that are new since the last reading of this window."""
    rows = _rows_of(reading)
    with _LOCK:
        was = _before['rows'] if _before['hwnd'] == hwnd else ()
        fresh = (time.time() - _before['at']) < BEFORE_KEPT
        _before.update({'hwnd': hwnd, 'rows': rows, 'at': time.time()})
    if not was or not fresh:
        return ''
    before = set(was)
    added = [row for row in rows if row and row not in before]
    if not added:
        return ''
    # A whole new screen is not "what the key did" - it is a new screen,
    # and saying forty rows after one arrow is worse than saying nothing.
    if len(added) > CHANGED_AT_MOST:
        return ''
    return ' '.join(added)


#: How many new rows still count as "the key moved something". More than
#: this is a screen that has been replaced, which the watcher's own
#: reading is for.
CHANGED_AT_MOST = 3


def after_key(say=True):
    """A navigation key was pressed: say what it moved onto.

    ``(ok, said)``. Silence is the commonest answer and the right one:
    an arrow inside a field moves a caret and no rows.
    """
    with _LOCK:
        hwnd = _state['hwnd']
    if not hwnd:
        return False, ''
    with _LOCK:
        _counted['keys'] = _counted.get('keys', 0) + 1
    # **What the key CHANGED, first.** A guest is a screen, not a list:
    # the most highlighted-looking thing on a Windows 95 desktop is the
    # taskbar, and it never moves. What the key did is the part of the
    # picture that is not what it was - and of the two places a moving
    # selection changes, the one that is now unlike the background.
    said, how = '', 'change'
    where = what_changed(hwnd)
    if where is not None:
        said = words_in(hwnd, where)
    if not said:
        # Nothing changed that could be read - the first key of all, a
        # list whose selection is drawn some other way, a menu. The row
        # detector is right for those and wrong for a desktop, which is
        # why it is second.
        reading = _read_now(hwnd)
        if reading is None:
            return False, ''
        said = selected_in(reading)
        how = 'highlight'
        if not said:
            said = changed_in(reading, hwnd)
            how = 'rows'
        else:
            changed_in(reading, hwnd)
    if not said:
        return False, ''
    now = time.time()
    with _LOCK:
        # **The same words are never said again because time has passed.**
        # This used to be `and (now - when) < QUIET`, a 0.35-second guard,
        # and the loop that calls this runs on a tick - so a pointer resting
        # anywhere, or a guest that repaints under a still pointer, was
        # "Start, Start, Start" for as long as the user left it alone.
        # Reported exactly that way, and it is right: a reader that says
        # what has not changed is a reader nobody can listen to. Only a
        # CHANGE speaks; the re-read command says it again on purpose.
        if said == _state['said']:
            _state['when'] = now
            with_same = _counted.get('unchanged', 0) + 1
            _counted['unchanged'] = with_same
            return False, ''
        _state.update({'said': said, 'when': now})
        _counted['said'] += 1
        _counted['how'] = how
    if say:
        _say(said)
    return True, said


# --------------------------------------------------------------------------- #
# What the key CHANGED, which on a screen is what it did
# --------------------------------------------------------------------------- #
"""**A guest is a SCREEN, and a screen is not a list.**

`selected_in` asks `virtualInput.highlights`, which finds a whole ROW
whose background is unlike the window's own. That is what a menu and a
list look like and it is the wrong question for a desktop: measured on a
real Windows 95 guest, the most highlighted-looking thing on it is the
TASKBAR - a grey band across the bottom of a teal screen - so arrowing
between icons was answered "Start", every time, because the taskbar never
moves and the selected icon's label is a sixth of a row wide.

So the first question is **what changed**. Pressing Down on a desktop
changes exactly two small places - the label that lost the selection and
the one that gained it - and the one that GAINED it is the one that is
now unlike the background. Nothing in that depends on the theme, the
language, the layout, or on the selection being drawn as an inverted bar
at all, which is why it is right for a guest, a game and an installer
alike and why the row detector is now only the fallback.
"""

#: The picture of the guest as it was before the last key, as blocks.
_seen = {'hwnd': 0, 'blocks': None, 'ground': None, 'at': 0.0,
         'size': (0, 0)}

#: A changed region smaller than this is a caret blinking or a clock
#: ticking, not a selection moving.
SMALLEST_CHANGE = 2

#: More changed blocks than this is a new SCREEN rather than a key, and
#: is left to the reading of the whole window.
BIGGEST_CHANGE = 220


#: How many blocks a fingerprint may have, whatever the window's size. A
#: guest can be 640x480 or a maximised 2358x1285, and the cost of looking
#: has to be the same on both - this runs several times a second.
BLOCKS_ACROSS = 60


def _block_for(width):
    from . import virtualInput
    return max(virtualInput.BLOCK, int(width) // BLOCKS_ACROSS)


def _picture_of(hwnd):
    """The guest's own picture and its size, or ``(None, 0, 0)``."""
    from . import localOcr
    rect = _rect_of(hwnd)
    if rect is None:
        return None, 0, 0
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    if width < 40 or height < 40:
        return None, 0, 0
    pixels = localOcr.from_window(hwnd, width, height)
    if pixels is None:
        return None, 0, 0
    return localOcr._Pixels(pixels, width, height), width, height


def what_changed(hwnd):
    """The region the last key changed, in SCREEN coordinates, or None.

    ``(left, top, width, height)``. Remembers this picture for the next
    key whether or not it could answer, because the next key's answer is
    the difference from THIS one.
    """
    from . import virtualInput
    picture, width, height = _picture_of(hwnd)
    if picture is None:
        return None
    block = _block_for(width)
    blocks = virtualInput.fingerprint(picture, width, height, block=block)
    ground = virtualInput._background(picture, width, height)
    with _LOCK:
        was = _seen['blocks'] if _seen['hwnd'] == hwnd else None
        stale = (time.time() - _seen['at']) > BEFORE_KEPT
        _seen.update({'hwnd': hwnd, 'blocks': blocks, 'ground': ground,
                      'at': time.time(), 'size': (width, height)})
    if not was or stale:
        return None
    moved = virtualInput.changed_blocks(was, blocks)
    if len(moved) < SMALLEST_CHANGE or len(moved) > BIGGEST_CHANGE:
        return None
    regions = virtualInput.regions_of(moved, block=block)
    if not regions:
        return None
    # **The one that is now unlike the background.** Moving a selection
    # changes two places and only one of them is the answer: the other
    # has just gone back to looking like the desktop.
    best, score = None, -1
    for region in regions:
        mark = virtualInput.unlikeness(blocks, region, ground, block=block)
        if mark > score:
            best, score = region, mark
    if best is None:
        return None
    rect = _rect_of(hwnd)
    if rect is None:
        return None
    left, top = rect[0], rect[1]
    # A little room around it: a label's last letter and the icon above
    # it are often just outside the blocks that changed.
    margin = block
    x = max(left, left + best[0] - margin)
    y = max(top, top + best[1] - margin)
    wide = min(rect[2] - x, best[2] + margin * 2)
    tall = min(rect[3] - y, best[3] + margin * 2)
    if wide < 8 or tall < 8:
        return None
    with _LOCK:
        _counted['changed'] = _counted.get('changed', 0) + 1
    return x, y, wide, tall


def words_in(hwnd, where):
    """What is written in that rectangle of the guest. ``''`` for none."""
    from . import localOcr
    try:
        reading = localOcr.read(where[0], where[1], where[2], where[3],
                                hwnd=hwnd)
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _counted['why'] = '%s: %s' % (type(error).__name__, error)
        return ''
    if not reading:
        return ''
    return _text(' '.join(text for text, _rect in reading.rows()))

# -*- coding: utf-8 -*-
"""What KIND of window you have just arrived in.

:mod:`dialog_kind` answers a narrow question well - question, warning,
error, information - and says nothing at all about every other window,
which is nearly all of them. A sighted person knows without looking
whether they are in an application, a little box that will go away again,
or a game that has painted its own screen; a reader that says only the
title says none of it.

So this is the rest of that question, and it is deliberately built out of
what Windows will simply ANSWER rather than out of a guess:

  * **game** - the window class is a game engine's. That is not a
    heuristic: ``UnityWndClass`` is Unity and nothing else, and the same
    list is what :mod:`surface` already reads to decide a window paints
    its own interface. One list, read twice.
  * **dialog** - :mod:`dialog_kind` says so, by role or by ``#32770``.
  * **small window** - a tool window, or a popup with no minimise and no
    maximise box: a palette, a tooltip-shaped thing, a little box that
    will go away again. Read off the styles, so it is the same in every
    language.
  * **application** - a top-level window with the frame an application
    has: resizeable, in the taskbar, usually with a menu.
  * **window** - anything else top-level, which is an honest answer and
    not a failure.

**The icon is described only where describing it costs nothing.** The
request was "a description of the icon by AI, or the kind of icon", and
that is the order: Titan's AI reads the window's own icon when Titan is
running with its AI features on and the user has allowed it for this
program, once per program and never again; otherwise the icon is said to
be an icon, which is what is certainly true. A layer on the arrival path
must never wait for a provider, so the AI half happens on a worker and
arrives afterwards, exactly as :mod:`labels` does for a control.

Nothing here speaks by itself. :func:`announce` composes and hands over to
:mod:`interject`, which is the one place an utterance is put in front of
NVDA's own words.
"""

import ctypes
import threading

from . import i18n

_ = i18n.install(globals())

#: Said once per window, not once per focus event inside it - which is the
#: bug the region layer had and this must not repeat.
_seen = {}
_LOCK = threading.RLock()

#: How many were told each way, for the diagnostics command.
_counted = {'game': 0, 'dialog': 0, 'tool': 0, 'application': 0,
            'desktop': 0, 'window': 0, 'none': 0}

#: Window styles. Written out rather than imported, because `win32con` is
#: not something an add-on may assume is importable inside NVDA.
_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_WS_CHILD = 0x40000000
_WS_POPUP = 0x80000000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_THICKFRAME = 0x00040000
_WS_SYSMENU = 0x00080000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000
_GA_ROOT = 2

#: Windows' own desktop. Called a "small window" by the styles alone - it
#: is a popup with no minimise and no maximise box - which is true of the
#: bits and wrong about the thing: the desktop is the one window that is
#: neither an application nor a box that will go away. Titan's own shell
#: already recognises it by exactly these two classes.
DESKTOP_CLASSES = frozenset({'Progman', 'WorkerW'})

_ICON_SMALL, _ICON_BIG, _ICON_SMALL2 = 0, 1, 2
_WM_GETICON = 0x007F
_GCLP_HICON = -14
_GCLP_HICONSM = -34
_SMTO_ABORTIFHUNG = 0x0002


def _user32():
    try:
        return ctypes.windll.user32
    except Exception:                                # noqa: BLE001
        return None


def _text(value):
    return str(value or '').strip()


def _root(hwnd):
    """The top-level window this one belongs to.

    A control's own handle is the CONTROL, and every question here is
    about the window around it.
    """
    user32 = _user32()
    if user32 is None or not hwnd:
        return int(hwnd or 0)
    try:
        user32.GetAncestor.restype = ctypes.c_void_p
        return int(user32.GetAncestor(ctypes.c_void_p(hwnd), _GA_ROOT) or hwnd)
    except Exception:                                # noqa: BLE001
        return int(hwnd)


def _handle(obj):
    try:
        return _root(int(getattr(obj, 'windowHandle', 0) or 0))
    except (TypeError, ValueError):
        return 0


def _styles(hwnd):
    """``(style, exstyle)``, or ``(0, 0)`` when Windows will not say."""
    user32 = _user32()
    if user32 is None or not hwnd:
        return 0, 0
    try:
        style = int(user32.GetWindowLongW(ctypes.c_void_p(hwnd), _GWL_STYLE))
        extra = int(user32.GetWindowLongW(ctypes.c_void_p(hwnd), _GWL_EXSTYLE))
        return style & 0xFFFFFFFF, extra & 0xFFFFFFFF
    except Exception:                                # noqa: BLE001
        return 0, 0


def is_game(obj):
    """Whether this window is a game engine's own.

    The list is :mod:`surface`'s, read rather than copied: a class added
    there for a game that paints its own menu is a class known here on the
    same day.
    """
    try:
        from . import surface
        classes = surface.GAME_CLASSES
    except Exception:                                # noqa: BLE001
        return False
    return _text(getattr(obj, 'windowClassName', '')) in classes


def kind_of(obj):
    """``(kind, how)`` for the window this object is in. ``('', '')`` when
    it cannot be told - which is a window Windows itself will not describe,
    and is reported rather than guessed at."""
    if obj is None:
        return '', ''
    if is_game(obj):
        with _LOCK:
            _counted['game'] += 1
        return 'game', 'class'
    if _text(getattr(obj, 'windowClassName', '')) in DESKTOP_CLASSES:
        with _LOCK:
            _counted['desktop'] += 1
        return 'desktop', 'class'
    try:
        from . import dialog_kind
        if dialog_kind.is_dialog(obj):
            with _LOCK:
                _counted['dialog'] += 1
            return 'dialog', 'role'
    except Exception:                                # noqa: BLE001
        pass
    hwnd = _handle(obj)
    if not hwnd:
        with _LOCK:
            _counted['none'] += 1
        return '', ''
    style, extra = _styles(hwnd)
    if not style and not extra:
        with _LOCK:
            _counted['none'] += 1
        return '', ''
    if style & _WS_CHILD:
        # Not a window of its own at all; the question was about the one
        # around it and `_root` should already have answered it.
        with _LOCK:
            _counted['none'] += 1
        return '', ''
    if extra & _WS_EX_TOOLWINDOW:
        with _LOCK:
            _counted['tool'] += 1
        return 'tool', 'style'
    boxes = style & (_WS_MINIMIZEBOX | _WS_MAXIMIZEBOX)
    if (style & _WS_POPUP) and not boxes:
        with _LOCK:
            _counted['tool'] += 1
        return 'tool', 'style'
    if (extra & _WS_EX_APPWINDOW) or (style & _WS_THICKFRAME) or boxes \
            or (style & _WS_SYSMENU):
        with _LOCK:
            _counted['application'] += 1
        return 'application', 'style'
    with _LOCK:
        _counted['window'] += 1
    return 'window', 'style'


def word(kind):
    """The kind as the word this add-on says for it."""
    return {
        # Translators: the kind of a window - a program with a window of
        # its own.
        'application': _('application'),
        # Translators: the kind of a window - one that is not a program's
        # main window and not a dialog.
        'window': _('window'),
        # Translators: the kind of a window - a game that paints its own
        # screen.
        'game': _('game'),
        # Translators: the kind of a window - a palette or a little box
        # that will go away again.
        'tool': _('small window'),
        # Translators: the kind of a window - Windows' own desktop.
        'desktop': _('desktop'),
        # Translators: the kind of a window.
        'dialog': _('dialog'),
    }.get(kind, '')


def _control_types():
    """NVDA's own role table, or None.

    Asked for directly rather than through the add-on's `compat`, because
    this module is byte-identical in Titan Access - which has no NVDA
    under it, answers None here, and falls back to the English spelling.
    """
    try:
        import controlTypes
        return controlTypes
    except Exception:                                # noqa: BLE001
        return None


def unknown_words():
    """Every spelling of NVDA's own "unknown" role, including the user's.

    Asked of NVDA rather than written down: the word is translated, so a
    list of English spellings would work on an English NVDA and nowhere
    else - which is precisely the machine this was reported from.
    """
    words = {'unknown'}
    types = _control_types()
    role = getattr(getattr(types, 'Role', None), 'UNKNOWN', None) \
        if types is not None else None
    if role is not None:
        try:
            from . import context
            said = _text(context.role_name(role))
            if said:
                words.add(said.lower())
        except Exception:                            # noqa: BLE001
            pass
    return words


def is_unknown_word(role):
    """Whether this role word is NVDA saying it does not know."""
    said = _text(role).lower()
    return bool(said) and said in unknown_words()


# --------------------------------------------------------------------------- #
# The window's own icon
# --------------------------------------------------------------------------- #
def icon_handle(hwnd):
    """The window's icon, or 0.

    ``WM_GETICON`` first and the window CLASS's icon after it, which is
    where a program that never set one of its own keeps the icon Explorer
    shows for it. Sent with a timeout: a window that has hung must not
    hold the reader, which is the rule Titan's own shell arrived at.
    """
    user32 = _user32()
    if user32 is None or not hwnd:
        return 0
    for which in (_ICON_SMALL2, _ICON_SMALL, _ICON_BIG):
        answer = ctypes.c_size_t(0)
        try:
            sent = user32.SendMessageTimeoutW(
                ctypes.c_void_p(hwnd), _WM_GETICON, which, 0,
                _SMTO_ABORTIFHUNG, 250, ctypes.byref(answer))
        except Exception:                            # noqa: BLE001
            break
        if sent and answer.value:
            return int(answer.value)
    for which in (_GCLP_HICONSM, _GCLP_HICON):
        try:
            getter = getattr(user32, 'GetClassLongPtrW', None) \
                or user32.GetClassLongW
            getter.restype = ctypes.c_void_p
            handle = getter(ctypes.c_void_p(hwnd), which)
        except Exception:                            # noqa: BLE001
            continue
        if handle:
            return int(handle)
    return 0


def has_icon(obj):
    return bool(icon_handle(_handle(obj)))


def icon_word():
    """What is said about an icon nobody has read.

    Deliberately the same word :mod:`graphics` says for one, so a user
    hears one vocabulary for one thing.
    """
    try:
        from . import graphics
        return graphics.word('icon')
    except Exception:                                # noqa: BLE001
        return _('icon')


def _may_describe(obj):
    """Whether reading this window's icon with AI is allowed AND possible.

    Three separate questions, and every one of them can be no: the user's
    own per-program switch, Titan running at all, and Titan's AI being
    reachable. Asking when any is no is a thread started to be refused -
    the bug this add-on has already fixed once on the label path.
    """
    try:
        from . import perProgram
        if not perProgram.value('autoLabel', obj):
            return False
    except Exception:                                # noqa: BLE001
        return False
    try:
        from .link import LINK
        return bool(LINK.connected())
    except Exception:                                # noqa: BLE001
        return False


#: What the AI made of a program's icon, kept per program. A window's icon
#: does not change while the program runs, and asking twice is paying
#: twice for one answer.
#:
#: This is only the answer for THIS session. The lasting copy is in
#: :mod:`labels`, whose file is the user's own and survives the program
#: restarting, an add-on update and Titan not being installed - because a
#: reading is a request, and a request paid for once should not be paid
#: for again tomorrow.
_described = {}

#: The field the lasting copy is filed under, in the program's own notes.
ICON_NOTE = 'window_icon'

#: The programs whose icon has been ASKED about this session, which is a
#: different question from what is known about it. Reading the file
#: answers the second and must not be mistaken for the first, or looking
#: something up counts as having asked for it and nothing is ever read.
_asked = set()


def described_icon(obj):
    """What is already known about this program's icon, or ``''``.

    Memory first and then the file, because the file is a read of a JSON
    document and this is asked on the way into every window.
    """
    program = _program_of(obj)
    if not program:
        return ''
    with _LOCK:
        remembered = _described.get(program)
    if remembered:
        return remembered
    if remembered == '':
        # Asked this session and answered nothing; the file was read then.
        return ''
    try:
        from . import labels
        kept = str(labels.application_note(program, ICON_NOTE) or '')
    except Exception:                                # noqa: BLE001
        kept = ''
    with _LOCK:
        _described[program] = kept
    return kept


def remember_icon(obj, text):
    """Keep what this program's icon was read as, for good."""
    program = _program_of(obj)
    said = _text(text)
    if not program or not said:
        return False
    with _LOCK:
        _described[program] = said
    try:
        from . import labels
        return bool(labels.set_application_note(program, ICON_NOTE, said))
    except Exception:                                # noqa: BLE001
        return False


def _program_of(obj):
    for name in ('appModule',):
        module = getattr(obj, name, None)
        if module is not None:
            got = _text(getattr(module, 'appName', ''))
            if got:
                return got.lower()
    return _text(getattr(obj, 'windowClassName', '')).lower()


def describe_icon_later(obj):
    """Have the AI describe this window's icon - which it cannot, yet.

    **The request was "a description of the icon by AI, or the kind of
    icon", and this is the second half, deliberately.** Titan's AI OCR
    reads a WINDOW: `graphics.read` hands it an hwnd and it photographs
    the rectangle that handle owns. There is no way to give it an
    `HICON`. So a call made here would photograph the whole window and
    answer about the window - and a maximised one does not show its own
    icon at all - while the reader announced the answer as what the icon
    shows. That is a capability that lies, which is worse than one that
    is absent: `parts_for` says the icon is an icon, which is certainly
    true, and nothing is invented.

    What would make the other half possible is one thing: a way to hand
    AI OCR a picture rather than a window handle. Until then this asks
    nothing, spends nothing, and starts no thread - the bug the label
    path had, where a thread per control was started to be told Titan is
    not running.

    Kept as a function because the per-program memory it guards is the
    part that must not be got wrong when the picture path arrives: one
    request per program in its life, never one per arrival.
    """
    program = _program_of(obj)
    if not program:
        return False
    if described_icon(obj):
        # Read once, in some session, and kept: never asked again.
        return False
    with _LOCK:
        if program in _asked:
            return False
        _asked.add(program)
    # Asked so the answer is honest in `report()` and so the switch is
    # read where a reader of this module would expect it to be.
    _may_describe(obj)
    return False


# --------------------------------------------------------------------------- #
# Saying it
# --------------------------------------------------------------------------- #
def wanted():
    from . import configSpec
    return bool(configSpec.read().get('windowKinds', True))


def parts_for(obj):
    """``[(text, voice)]`` - what to say about arriving in this window.

    The kind is said at the tone a control's TYPE is said at everywhere
    else in this add-on, because that is what it is: what the thing you
    have arrived in IS. The icon, when something is known about it, is a
    detail and is said at the detail tone.
    """
    kind, _how = kind_of(obj)
    if not kind:
        return []
    said = word(kind)
    if not said:
        return []
    parts = [(said, 'kind')]
    described = described_icon(obj)
    if described:
        parts.append((described, 'detail'))
    elif has_icon(obj):
        parts.append((icon_word(), 'detail'))
    return parts


def announce(obj):
    """Say what kind of window this is. ``''`` when nothing was said.

    Once per window: a window whose focus moves between its own controls
    is the same window, and a reader that said "application" on every
    control of it would be unusable.
    """
    if not wanted():
        return ''
    kind, _how = kind_of(obj)
    if not kind:
        return ''
    hwnd = _handle(obj)
    with _LOCK:
        if _seen.get(hwnd) == kind:
            return ''
        if len(_seen) > 64:
            # A window handle is reused as freely as any other.
            _seen.clear()
        _seen[hwnd] = kind
    try:
        describe_icon_later(obj)
    except Exception:                                # noqa: BLE001
        pass
    parts = parts_for(obj)
    if not parts:
        return ''
    try:
        from . import elements
        from . import interject
        sequence = elements.sequence(parts)
        text = ' '.join(part for part in sequence
                        if isinstance(part, str) and part.strip()).strip()
        if not text:
            return ''
        interject.prefix_next(text, 'kind')
    except Exception:                                # noqa: BLE001
        return ''
    return kind


def counts():
    with _LOCK:
        return dict(_counted)


def forget():
    """Start again - for the tests, and for the add-on being switched off."""
    with _LOCK:
        _seen.clear()
        _described.clear()
        _asked.clear()
        for key in _counted:
            _counted[key] = 0


def report():
    """What this layer has really done, for the diagnostics command."""
    found = counts()
    found.update({'enabled': wanted(),
                  'available': _user32() is not None,
                  'icons_described': len([v for v in _described.values() if v])})
    return found

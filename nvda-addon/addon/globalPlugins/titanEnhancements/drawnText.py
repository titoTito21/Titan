# -*- coding: utf-8 -*-
"""What the program DREW, read from the hook instead of from a picture.

The tier under both OCR tiers, and the one that should have been first.

A window that exposes nothing through an accessibility API has been read
here by photographing it - Windows' own recogniser, then a vision model.
Both answer a picture, and a picture is the long way round: the program
already said what it was writing, in words, when it called
``ExtTextOutW``. NVDA injects ``nvdaHelperRemote.dll`` into every process
and hooks exactly those calls, keeping what was drawn and where; that is
NVDA's **display model**, and `displayModel.getWindowTextInRect` hands it
back as text plus one rectangle per character, in screen coordinates.

So for a window whose text is drawn with GDI this is:

* **exact** - the characters the program passed to Windows, not a guess at
  their shapes, so no misread digit and no lost diacritic;
* **free** - no capture, no model, no request, nothing leaving the machine;
* **instant** - reading a structure NVDA already holds;
* **pressable** - a real rectangle per character, so a word can be clicked.

What it cannot reach is the honest part, and it decides where the OCR
tiers still earn their place:

* **A game that draws its text as textures.** Direct3D and OpenGL never
  call a GDI text function, so the model is empty and a picture is the
  only thing there is.
* **The inside of a virtual machine.** The guest's own `ExtTextOut`
  happens in the guest, on the other side of the virtual hardware; the
  host sees a framebuffer. The VM's OWN windows - its menus, its settings,
  its shutdown dialog, the parts VirtualBox is reported as making
  completely unreadable - are on this side and do come out here.
* **Anything drawn into a bitmap elsewhere and blitted in.**

An empty answer is therefore not a failure and is never reported as one:
it means "this window does not draw its text through GDI", and the caller
falls through to the recogniser exactly as before.
"""

import threading
import time

from . import compat
from . import i18n

_ = i18n.install(globals())

#: NVDA's own values for `DisplayModelTextInfo`. Whitespace narrower than
#: this is inside a word, wider than this separates one. Taken from NVDA
#: rather than chosen, so a reading here is split the way NVDA splits it.
MIN_HORIZONTAL_WHITESPACE = 8
MIN_VERTICAL_WHITESPACE = 32

_LOCK = threading.RLock()
_state = {'asked': 0, 'reads': 0, 'empty': 0, 'failed': 0,
          'repainted': 0, 'why': '', 'ms': 0.0, 'chars': 0}


def report():
    """What this tier has really done, for the diagnostics."""
    with _LOCK:
        found = dict(_state)
    found['available'] = available()[0]
    return found


def _note(why):
    with _LOCK:
        _state['failed'] += 1
        _state['why'] = str(why)
    return None


def available():
    """``(yes, why not)`` - whether the display model can be asked at all."""
    model = getattr(compat, 'displayModel', None)
    if model is None:
        return False, _('This NVDA does not expose its display model.')
    if not hasattr(model, 'getWindowTextInRect'):
        return False, _('This NVDA has no getWindowTextInRect.')
    return True, ''


def _binding_handle(hwnd):
    """The handle `getWindowTextInRect` needs, or None.

    It is the app module's `helperLocalBindingHandle` - the RPC channel to
    the copy of `nvdaHelperRemote` inside THAT process. Without an injected
    helper there is no model to read, which is what a `None` here means.
    """
    try:
        import NVDAObjects.window
        obj = NVDAObjects.window.Window(windowHandle=int(hwnd))
    except Exception as error:                       # noqa: BLE001
        return None, 'no object for that window: %s' % error
    app = getattr(obj, 'appModule', None)
    handle = getattr(app, 'helperLocalBindingHandle', None)
    if not handle:
        return None, 'nothing of NVDA is injected into that process'
    return (obj, handle), ''


#: `RedrawWindow` flags: invalidate, paint it NOW, and include children.
_RDW_INVALIDATE = 0x0001
_RDW_UPDATENOW = 0x0100
_RDW_ALLCHILDREN = 0x0080


def _repaint(hwnd):
    """Ask the window to draw itself again, and wait for it to finish.

    **The model is filled BY the drawing, not by asking.** The hooks record
    what goes through a GDI text call as it happens, so a window that has
    not repainted since NVDA was injected into its process has nothing in
    the model at all - measured on a 7-Zip that had been open for hours:
    the model answered in 0.06 ms with no characters in it, which reads
    exactly like "this program does not draw its text with GDI" and is a
    completely different thing.

    `RDW_UPDATENOW` makes the paint happen before this returns, so the
    model is populated by the time it is read. It is what the window would
    do anyway if anything had passed over it, and a program that draws
    nothing through GDI is unaffected.
    """
    try:
        import ctypes
        ctypes.windll.user32.RedrawWindow(
            ctypes.c_void_p(int(hwnd)), None, None,
            _RDW_INVALIDATE | _RDW_UPDATENOW | _RDW_ALLCHILDREN)
        return True
    except Exception:                                # noqa: BLE001
        return False


def plain(markup):
    """The words out of the model's markup.

    **The first value is not text, it is MARKUP.** `getWindowTextInRect`
    answers something HTML-like - `<text hwnd=".." color=".." ...>Open</text>`
    - which NVDA wraps in `<control>` and hands to `XMLFormatting.
    XMLTextParser`; the rectangle buffer has one entry per PLAIN character,
    not per character of the markup. Walking the markup against the
    rectangles put `<text hwnd="00000000001E020C"` into the reading as its
    first word and threw every rectangle out of step with its character.

    So the tags come off first and the entities are unescaped, and what is
    left is exactly what the rectangles count. Stripping tags is safe
    because a `<` in the drawn text arrives as `&lt;`.
    """
    import html
    import re
    text = re.sub(r'<[^>]*>', '', str(markup or ''))
    return html.unescape(text)


def _words(text, rects):
    """Plain text and `[RectLTRB]` grouped into lines of words, BY GEOMETRY.

    **The markup carries no line breaks**, so splitting on `\n` put a whole
    window on one line: 7-Zip's menu, its toolbar and its whole file list
    came back as a single row 641 by 1012, which for a reader that moves by
    line is one unreadable blob. The rectangles are what say where the lines
    are, and they are the reason this tier is worth having - so a line ends
    where the characters step down, and a word ends at a gap wider than a
    character.

    A character with no rectangle (the buffers can differ in length on a
    window that repainted mid-read) is kept in the text and cannot start a
    line, which is better than dropping what the program said.
    """
    rows = []          # [(top, bottom, [ {word} ]) ]
    word = ''
    box = None
    last = None        # the previous character's rectangle

    def rectangle_of(raw):
        try:
            return (raw.left, raw.top, raw.right, raw.bottom)
        except AttributeError:
            try:
                here = tuple(raw)[:4]
                return here if len(here) == 4 else None
            except Exception:                        # noqa: BLE001
                return None

    def close_word():
        nonlocal word, box
        if word.strip() and box:
            left, top, right, bottom = box
            place(top, bottom, {'text': word.strip(),
                                'left': int(left), 'top': int(top),
                                'width': int(max(1, right - left)),
                                'height': int(max(1, bottom - top))})
        word, box = '', None

    def place(top, bottom, entry):
        """Into the row whose band this word shares, or a new one."""
        middle = (top + bottom) / 2.0
        for row in rows:
            if row[0] <= middle <= row[1]:
                row[2].append(entry)
                row[0] = min(row[0], top)
                row[1] = max(row[1], bottom)
                return
        rows.append([top, bottom, [entry]])

    for index, character in enumerate(text):
        raw = rects[index] if index < len(rects) else None
        here = rectangle_of(raw) if raw is not None else None
        if character in '\r\n' or character.isspace():
            close_word()
            last = here or last
            continue
        if here is None:
            word += character
            continue
        if last is not None and box is not None:
            stepped = abs(here[1] - last[1]) > max(
                2, (last[3] - last[1]) / 2.0)
            gap = here[0] - last[2]
            if stepped or gap >= MIN_HORIZONTAL_WHITESPACE:
                close_word()
        word += character
        box = here if box is None else (
            min(box[0], here[0]), min(box[1], here[1]),
            max(box[2], here[2]), max(box[3], here[3]))
        last = here
    close_word()

    rows.sort(key=lambda row: (row[0], min(w['left'] for w in row[2])))
    lines = []
    for _top, _bottom, words in rows:
        words.sort(key=lambda entry: entry['left'])
        if words:
            lines.append(words)
    return lines


def read_window(hwnd):
    """What that window drew, as a `localOcr.Reading`, or None.

    None means "nothing was drawn through GDI here" - not a fault, and the
    caller falls through to the recogniser.
    """
    with _LOCK:
        _state['asked'] += 1
    ready, why = available()
    if not ready:
        return _note(why)

    from . import localOcr
    rect = localOcr._window_rect(hwnd)
    if rect is None:
        return _note('that window has no place on the screen')

    found, why = _binding_handle(hwnd)
    if found is None:
        return _note(why)
    _obj, handle = found

    left, top, right, bottom = rect
    started = time.time()

    def ask():
        return compat.displayModel.getWindowTextInRect(
            handle, int(hwnd), left, top, right, bottom,
            MIN_HORIZONTAL_WHITESPACE, MIN_VERTICAL_WHITESPACE)

    try:
        text, rects = ask()
        if not plain(text).strip():
            # Nothing in the model yet. That is either a window that does
            # not draw its text this way, or one that simply has not drawn
            # since NVDA arrived - and the two are told apart by making it
            # draw and asking again.
            if _repaint(hwnd):
                with _LOCK:
                    _state['repainted'] += 1
                text, rects = ask()
    except Exception as error:                       # noqa: BLE001
        return _note('%s: %s' % (type(error).__name__, error))
    spent = (time.time() - started) * 1000.0

    text = plain(text)
    lines = _words(text, list(rects or []))
    with _LOCK:
        _state['ms'] = round(spent, 2)
        _state['chars'] = len(text)
        if lines:
            _state['reads'] += 1
            _state['why'] = ''
        else:
            # Not a failure: the window simply does not draw its text this
            # way. Counted apart so a diagnostic can tell the two apart.
            _state['empty'] += 1
            _state['why'] = 'nothing is drawn through GDI in that window'
    if not lines:
        return None
    return localOcr.Reading(lines)

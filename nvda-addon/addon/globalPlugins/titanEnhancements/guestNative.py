# -*- coding: utf-8 -*-
"""The native half of reading a guest: `guestscreen.dll`, if it is there.

Three pieces of per-pixel work answer a virtual machine's screen, and all
three run several times a second while somebody is using one:

* taking the picture out of the window's OWN device context (never a screen
  capture, which reads whatever is in front of the guest),
* saying what CHANGED since the last one, which on a drawn screen is what
  the key did,
* and where the guest is in a TEXT mode, reading it exactly by matching each
  character cell against the real VGA glyphs (:mod:`vgaFont`).

The source is `nvda-addon/helper/guestscreen/guestscreen.cpp` and
`build.bat` builds it with whatever MSVC the machine has. **It is optional by
construction**: every call here answers None or False when the library is
missing, and the Python tiers do the same work more slowly - a reader must
never lose the reading over a build step. What the library buys, measured on
this machine's own guest: a 1920-block fingerprint in **1.1 ms** and the
changed region in **0.01 ms**, and a rendered 80 by 25 text screen read
exactly in **4 ms** where the first version of the same loop took 125.

Nothing here is injected into another process and nothing reads another
program's memory: it is the host's own window, its own pixels, in this
process. A screen reader may not risk somebody else's address space to read
a screen.
"""

import ctypes
import os
import threading

_LOCK = threading.RLock()
_state = {'library': '', 'why': '', 'captures': 0, 'refused': 0,
          'fingerprints': 0, 'texts': 0}
_dll = None
_looked = False

#: Where the library is looked for: beside this file first (which is where
#: the add-on ships it), then the build directory in the repository, so a
#: freshly built one is used without installing anything.
PLACES = (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib',
                 'guestscreen.dll'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 'guestscreen.dll'),
)


def report():
    # **Looked for before it is reported on.** Read live, this answered
    # `available: true` with an empty `library` - the state was copied and
    # the library found afterwards - which is a diagnostic that contradicts
    # itself on the one line somebody reads.
    available = library() is not None
    with _LOCK:
        found = dict(_state)
    found['available'] = available
    return found


def library():
    """The loaded library, or None. Looked for once."""
    global _dll, _looked
    with _LOCK:
        if _looked:
            return _dll
        _looked = True
    for where in PLACES:
        if not os.path.isfile(where):
            continue
        try:
            found = ctypes.CDLL(where)
        except Exception as error:                   # noqa: BLE001
            with _LOCK:
                _state['why'] = '%s would not load: %s' % (where, error)
            continue
        try:
            _declare(found)
        except Exception as error:                   # noqa: BLE001
            with _LOCK:
                _state['why'] = '%s is not the right library: %s' % (
                    where, error)
            continue
        with _LOCK:
            _dll = found
            _state['library'] = where
            _state['why'] = ''
        return found
    with _LOCK:
        if not _state['why']:
            _state['why'] = ('guestscreen.dll was not built - '
                             'nvda-addon/helper/guestscreen/build.bat')
    return None


def _declare(dll):
    u32 = ctypes.POINTER(ctypes.c_uint32)
    dll.guest_capture.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_char_p, ctypes.c_int,
                                  ctypes.POINTER(ctypes.c_int)]
    dll.guest_capture.restype = ctypes.c_int
    dll.guest_fingerprint.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, u32,
                                      ctypes.c_int]
    dll.guest_fingerprint.restype = ctypes.c_int
    dll.guest_changed.argtypes = [u32, u32, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_uint32,
                                  ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    dll.guest_changed.restype = ctypes.c_int
    dll.guest_text.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                               ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_char_p,
                               u32, u32, ctypes.POINTER(ctypes.c_int),
                               ctypes.POINTER(ctypes.c_int)]
    dll.guest_text.restype = ctypes.c_int

    # Windows Graphics Capture: a window's composed surface, for the ones
    # that draw with Direct3D/DXGI/OpenGL and give GDI one flat colour - a
    # guest, a Unity or SDL game, anything on a graphics library.
    try:
        dll.wc_supported.restype = ctypes.c_int
        dll.wc_capture.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 6 + [
            ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        dll.wc_capture.restype = ctypes.c_int
    except AttributeError:
        # An older guestscreen.dll without the capture tier still reads a
        # text screen and finds what changed; only the D3D-window capture
        # is missing, and `wgc_supported()` will say so.
        pass



def wgc_supported():
    """Whether Windows Graphics Capture is here to capture a D3D window."""
    dll = library()
    if dll is None or not hasattr(dll, 'wc_supported'):
        return False
    try:
        return bool(dll.wc_supported())
    except Exception:                                # noqa: BLE001
        return False


def capture_window(hwnd, dest_w, dest_h, src=None):
    """A window's composed picture as BGRA bytes, or None.

    The one capture that answers a window painting with Direct3D, DXGI,
    OpenGL or Vulkan - a virtual machine's guest, a Unity/SDL/Godot game,
    anything on a graphics library - all of which give the device-context
    path one flat colour. It is Windows Graphics Capture's CreateForWindow,
    which the compositor answers with the window's own surface whatever
    drew it and whether or not something is in front of it.

    **CreateForWindow wants a TOP-LEVEL window**, and the window handed here
    is very often a child - the guest is painted on a child of VMware's
    frame. So the top-level ancestor is captured and the child's rectangle
    (plus any ``src`` sub-rect, in the child's own coordinates) is cropped
    out of it.

    ``src`` is ``(x, y, w, h)`` inside ``hwnd``; whole window when omitted.
    Returns a ``ctypes`` buffer of ``dest_w * dest_h * 4`` bytes, top-down
    BGRA, or None.
    """
    dll = library()
    if dll is None or not hasattr(dll, 'wc_capture'):
        return None
    if not hwnd or dest_w <= 0 or dest_h <= 0:
        return None
    try:
        import ctypes
        import ctypes.wintypes as wintypes
        user32 = ctypes.windll.user32
        GA_ROOT = 2
        root = user32.GetAncestor(ctypes.c_void_p(int(hwnd)), GA_ROOT)
        if not root:
            root = int(hwnd)
        child = wintypes.RECT()
        top = wintypes.RECT()
        if not user32.GetWindowRect(ctypes.c_void_p(int(hwnd)),
                                    ctypes.byref(child)):
            return None
        if not user32.GetWindowRect(ctypes.c_void_p(int(root)),
                                    ctypes.byref(top)):
            return None
        off_x, off_y = child.left - top.left, child.top - top.top
        whole = child.right - child.left
        tall = child.bottom - child.top
        if src:
            off_x += int(src[0])
            off_y += int(src[1])
            whole, tall = int(src[2]), int(src[3])
        if whole <= 0 or tall <= 0:
            return None
        buffer = ctypes.create_string_buffer(dest_w * dest_h * 4)
        flat = ctypes.c_int(-1)
        ok = dll.wc_capture(ctypes.c_void_p(int(root)), int(dest_w),
                            int(dest_h), int(off_x), int(off_y),
                            int(whole), int(tall), buffer,
                            len(buffer), ctypes.byref(flat))
        with _LOCK:
            if ok:
                _state['captures'] = _state.get('captures', 0) + 1
            else:
                _state['refused'] = _state.get('refused', 0) + 1
        if not ok or flat.value == 1:
            return None
        return buffer
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _state['why'] = 'wgc: %s' % error
        return None


def forget():
    """For the tests: look for the library again."""
    global _dll, _looked
    with _LOCK:
        _dll, _looked = None, False
        _state.update({'library': '', 'why': '', 'captures': 0, 'refused': 0,
                       'fingerprints': 0, 'texts': 0})


# --------------------------------------------------------------------------- #
# The picture
# --------------------------------------------------------------------------- #
class Picture(object):
    """BGRA bytes with a size, and whether the window drew one flat colour."""

    __slots__ = ('pixels', 'width', 'height', 'flat')

    def __init__(self, pixels, width, height, flat):
        self.pixels = pixels
        self.width = int(width)
        self.height = int(height)
        self.flat = bool(flat)

    def __len__(self):
        return len(self.pixels)


def capture(hwnd, width=0, height=0):
    """That window's own picture, or None.

    A flat one is answered rather than refused - the caller decides, because
    "the window drew nothing" and "there is no library" are different things
    to do about.
    """
    dll = library()
    if dll is None or not hwnd:
        return None
    if width <= 0 or height <= 0:
        size = _window_size(hwnd)
        if size is None:
            return None
        width, height = size
    if width <= 0 or height <= 0:
        return None
    room = width * height * 4
    buffer = ctypes.create_string_buffer(room)
    flat = ctypes.c_int(0)
    try:
        ok = dll.guest_capture(ctypes.c_void_p(int(hwnd)), int(width),
                               int(height), buffer, room, ctypes.byref(flat))
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _state['why'] = 'capture raised: %s' % error
            _state['refused'] += 1
        return None
    if not ok:
        with _LOCK:
            _state['refused'] += 1
        return None
    with _LOCK:
        _state['captures'] += 1
    return Picture(buffer.raw, width, height, flat.value)


def _window_size(hwnd):
    try:
        from ctypes import wintypes
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(int(hwnd)),
                                                 ctypes.byref(rect)):
            return None
    except Exception:                                # noqa: BLE001
        return None
    return (rect.right - rect.left, rect.bottom - rect.top)


# --------------------------------------------------------------------------- #
# What changed
# --------------------------------------------------------------------------- #
#: How many blocks across a fingerprint is, whatever the size of the guest -
#: the same number `virtualInput` uses, so the two tiers answer about the
#: same grid.
BLOCKS_ACROSS = 60


def block_for(width):
    return max(8, int(width) // BLOCKS_ACROSS)


def fingerprint(picture, block=0):
    """``(blocks, across, down, block)`` for that picture, or None."""
    dll = library()
    if dll is None or picture is None:
        return None
    block = int(block) or block_for(picture.width)
    across, down = picture.width // block, picture.height // block
    if across <= 0 or down <= 0:
        return None
    blocks = (ctypes.c_uint32 * (across * down))()
    try:
        count = dll.guest_fingerprint(picture.pixels, picture.width,
                                      picture.height, block, blocks,
                                      across * down)
    except Exception:                                # noqa: BLE001
        return None
    if count <= 0:
        return None
    with _LOCK:
        _state['fingerprints'] += 1
    return blocks, across, down, block


#: How far a block's sum may move and still be the same block. A clock's
#: seconds and a caret blinking are both smaller than this.
TOLERANCE = 400


def changed(now, before, tolerance=TOLERANCE, most=12):
    """Where the picture changed, as screen-relative rectangles, biggest
    first - ``[(left, top, width, height), ...]``."""
    dll = library()
    if dll is None or now is None or before is None:
        return []
    blocks, across, down, block = now
    was, was_across, was_down, was_block = before
    if (across, down, block) != (was_across, was_down, was_block):
        return []
    room = (ctypes.c_int * (most * 4))()
    try:
        found = dll.guest_changed(blocks, was, across, down, block,
                                  int(tolerance), room, most)
    except Exception:                                # noqa: BLE001
        return []
    regions = [(room[at * 4], room[at * 4 + 1], room[at * 4 + 2],
                room[at * 4 + 3]) for at in range(max(0, found))]
    regions.sort(key=lambda one: one[2] * one[3], reverse=True)
    return regions


# --------------------------------------------------------------------------- #
# A text screen, exactly
# --------------------------------------------------------------------------- #
#: A cell size is believed only when this much of the INKED cells - the ones
#: with something drawn in them - really matched a glyph. Measured against
#: the cells of the whole screen instead, every size scored about one, because
#: most of a text screen is blank: the wrong grid then read a screen of
#: nothing and reported it as certain.
ENOUGH = 0.92

#: And there have to be enough of them to be a screen with words on it. Two
#: inked cells matching perfectly is not a text mode, it is a coincidence.
LEAST_INK = 24


class TextScreen(object):
    """What a text-mode guest says, with the colour every cell was drawn in."""

    __slots__ = ('lines', 'paper', 'ink', 'cols', 'rows', 'cell', 'matched')

    def __init__(self, lines, paper, ink, cols, rows, cell, matched):
        self.lines = lines
        self.paper = paper
        self.ink = ink
        self.cols = cols
        self.rows = rows
        self.cell = cell
        self.matched = matched

    def __bool__(self):
        return bool(any(line.strip() for line in self.lines))

    __nonzero__ = __bool__

    def highlighted(self):
        """The row drawn on a background unlike the rest of the screen.

        That is what an installer's chosen entry IS - there is nothing else
        in a text screen that says which line the arrow keys are on - and
        here it is read off the ATTRIBUTE rather than guessed from pixels.
        """
        counts = {}
        for row in self.paper:
            for colour in row:
                counts[colour] = counts.get(colour, 0) + 1
        if not counts:
            return ''
        ground = max(counts, key=lambda one: counts[one])
        best, best_count = -1, 0
        for at, row in enumerate(self.paper):
            unlike = sum(1 for colour in row if colour != ground)
            if unlike > best_count:
                best, best_count = at, unlike
        if best < 0 or best_count < max(2, self.cols // 20):
            return ''
        return self.lines[best].strip()


#: The cell sizes a text mode really uses, biggest first: a VGA 80x25 is 9x16
#: on a 720x400 signal and 8x16 on 640x400, and 8x8 is the 80x50 mode.
CELLS = ((9, 16), (8, 16), (12, 16), (8, 8), (8, 14))


def text_screen(picture, cells=CELLS, enough=ENOUGH):
    """Read that picture as a text screen, or None.

    Every cell size is tried and the one that really matches wins. **This
    only works on a picture that is the guest's own size**: VMware stretches
    a small guest into a big window with a bilinear filter, and a filtered
    glyph matches nothing - which is the honest answer here, because a wrong
    exact reading is worse than no exact reading. The model tier answers a
    stretched screen.
    """
    dll = library()
    if dll is None or picture is None or picture.flat:
        return None
    from . import vgaFont
    best = None
    for width, height in cells:
        table = vgaFont.table(width, height)
        if table is None:
            continue
        cols, rows = picture.width // width, picture.height // height
        if cols < 20 or rows < 8:
            continue
        room = cols * rows
        text = ctypes.create_string_buffer(room)
        ink = (ctypes.c_uint32 * room)()
        paper = (ctypes.c_uint32 * room)()
        matched = ctypes.c_int(0)
        inked = ctypes.c_int(0)
        try:
            cells_read = dll.guest_text(picture.pixels, picture.width,
                                        picture.height, table, width, height,
                                        cols, rows, text, ink, paper,
                                        ctypes.byref(matched),
                                        ctypes.byref(inked))
        except Exception:                            # noqa: BLE001
            continue
        if cells_read <= 0 or inked.value < LEAST_INK:
            continue
        share = float(matched.value) / float(inked.value)
        # The best grid is the one that matched, and between two that both
        # matched, the one that found more words.
        mark = (round(share, 3), inked.value)
        if best is None or mark > (round(best[0], 3), best[7]):
            best = (share, text.raw[:room], list(ink), list(paper),
                    cols, rows, (width, height), inked.value)
        if share >= 0.995:
            break
    if best is None or best[0] < enough:
        return None
    share, raw, ink, paper, cols, rows, cell, _inked = best
    lines = []
    papers = []
    inks = []
    for row in range(rows):
        piece = raw[row * cols:(row + 1) * cols]
        lines.append(piece.decode('cp437', 'replace').rstrip())
        papers.append(paper[row * cols:(row + 1) * cols])
        inks.append(ink[row * cols:(row + 1) * cols])
    with _LOCK:
        _state['texts'] += 1
    return TextScreen(lines, papers, inks, cols, rows, cell, share)


# --------------------------------------------------------------------------- #
# ...as a reading, with the rectangles a text screen really has
# --------------------------------------------------------------------------- #
def reading_of(screen, left=0, top=0):
    """A :class:`localOcr.Reading` out of a text screen, or None.

    **The rectangles are exact rather than recognised**, which is the other
    half of what this tier buys: a recogniser answers a box around where it
    thinks a word is, and here the geometry IS the screen - column times cell
    width, row times cell height - so pressing what was read lands on the
    character it was read from. `left` and `top` move the grid onto the
    screen, because that is where a caller clicks.

    A word is a run of non-blank characters, as it is everywhere else: an
    installer's line is walked word by word with the same keys as any other
    reading.
    """
    if screen is None:
        return None
    from . import localOcr
    wide, tall = screen.cell
    lines = []
    for row, text in enumerate(screen.lines):
        words = []
        at = 0
        while at < len(text):
            if text[at] == ' ':
                at += 1
                continue
            start = at
            while at < len(text) and text[at] != ' ':
                at += 1
            words.append({'text': text[start:at],
                          'left': int(left) + start * wide,
                          'top': int(top) + row * tall,
                          'width': (at - start) * wide,
                          'height': tall})
        if words:
            lines.append(words)
    if not lines:
        return None
    reading = localOcr.Reading(lines)
    # And the highlight, from the ATTRIBUTE rather than from the pixels: the
    # row whose background is unlike the rest of the screen is the row the
    # arrow keys are on, and a text screen says so exactly.
    counts = {}
    for row in screen.paper:
        for colour in row:
            counts[colour] = counts.get(colour, 0) + 1
    if counts:
        ground = max(counts, key=lambda one: counts[one])
        for row, colours in enumerate(screen.paper):
            unlike = sum(1 for colour in colours if colour != ground)
            if unlike >= max(2, screen.cols // 20):
                reading.highlights.append(
                    (int(left), int(top) + row * tall, screen.cols * wide,
                     tall))
    return reading


def read_window(hwnd, left=0, top=0):
    """A guest's window as an exact text reading, or None.

    This is the whole tier in one call: take the picture out of the window's
    own context, read it as a text screen, and answer a reading with real
    rectangles. It answers None for everything it cannot be certain about - a
    graphics mode, a guest VMware has stretched, a window that drew nothing -
    and the model tier behind it is what reads those.
    """
    picture = capture(hwnd)
    if picture is None or picture.flat:
        return None
    screen = text_screen(picture)
    if screen is None:
        return None
    return reading_of(screen, left, top)

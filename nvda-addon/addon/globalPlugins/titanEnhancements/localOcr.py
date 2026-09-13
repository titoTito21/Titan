# -*- coding: utf-8 -*-
"""NVDA's own OCR, used as the tier UNDER the AI one.

A window that draws its own interface can be read two ways, and until now
this add-on only had the expensive one. Titan's AI OCR takes a picture and
asks a vision model what is on it: it understands layout, it names controls,
it says what is highlighted - and every reading is a picture of the user's
screen sent to a provider, and money.

Windows has an OCR engine built in, NVDA already wraps it
(`contentRecog.uwpOcr`), and for the commonest thing somebody actually wants
from an unreadable window - **what does it SAY** - it is enough. It is
local, it is free, it is about a tenth of a second, and nothing leaves the
machine.

So this is the first tier, and the AI is asked only for what it alone can
do:

* **Reading the words**, and where each one is, comes from here. The
  coordinates are real screen coordinates, so a reading is navigable and a
  control can be clicked without a model having been involved at all.
* **Watching for change** comes from here too, and that is the part that
  matters most for a game: a menu that repaints constantly would spend an AI
  request per poll. Comparing this reading with the last one is free, so the
  AI is asked only when the window has really become something else.
* **Understanding** stays with the AI: which of these words is a button,
  what is highlighted, what the layout means.

Everything degrades: an NVDA without the recogniser, a Windows without the
language pack, a window that will not capture - each answers with nothing
and the caller falls back to what it did before.
"""

import threading
import time

from . import compat

_LOCK = threading.RLock()
_state = {'reads': 0, 'failed': 0, 'why': '', 'ms': 0.0}

#: Why the last window capture came back with nothing. **Ten silent
#: `return None` paths is how a reader goes blind without saying so**: the
#: guest read as empty and the only thing anybody could see was that it read
#: as empty. Written down here and answered by `report()`.
_capture = {'why': '', 'refused': 0, 'taken': 0}


def _no_picture(why):
    _capture['why'] = str(why)
    _capture['refused'] += 1
    return None

#: How long a reading may take before it is given up on. Windows OCR is
#: fast; something that is not answering is not something to wait for on a
#: watcher's poll.
TIMEOUT = 4.0


def _text(value):
    return str(value or '').strip()


def report():
    with _LOCK:
        found = dict(_state)
    # The capture is a separate question from the recogniser, and it is the
    # one that answers "the guest reads as empty".
    try:
        found['capture'] = dict(_capture)
    except Exception:                                # noqa: BLE001
        pass
    return found


def _note(why):
    with _LOCK:
        _state['why'] = str(why)
        _state['failed'] += 1
    return None


def available():
    """Whether this NVDA can read the screen locally at all. ``(ok, why)``."""
    try:
        from contentRecog import uwpOcr
    except Exception as error:                       # noqa: BLE001
        return False, 'this NVDA has no Windows OCR: %s' % error
    try:
        languages = uwpOcr.getLanguages()
    except Exception as error:                       # noqa: BLE001
        return False, 'Windows will not say which OCR languages it has: %s' \
            % error
    if not languages:
        return False, ('Windows has no OCR language installed. Add one in '
                       'Windows Settings, under Language.')
    return True, ''


def _recognizer():
    from contentRecog import uwpOcr
    from . import configSpec
    wanted = str(configSpec.read().get('localOcrLanguage', '') or '').strip()
    try:
        if wanted:
            return uwpOcr.UwpOcr(language=wanted)
    except Exception:                                # noqa: BLE001
        pass
    return uwpOcr.UwpOcr()


#: Windows' own raster operation for a straight copy.
SRCCOPY = 0x00CC0020


#: How many points are looked at before a capture is called blank. A
#: coarse grid is not enough: a Windows 95 desktop is **97% one colour**,
#: and twelve samples across a maximised guest found nothing but that
#: teal - so every capture of the user's own machine was refused as
#: "flat" and the reader fell back to photographing the screen, which is
#: whatever is in FRONT of the guest. Measured, on that guest: 132
#: colours in the same picture this called blank.
BLANK_SAMPLES = 48


def _blank(pixels, width, height):
    """Whether a capture came back as ONE colour and nothing else.

    That is what a window which would not draw itself gives - measured on
    VMware, all three `PrintWindow` flags answer pure black - and it is
    the only thing this may refuse. **A picture that is mostly one colour
    is not blank**: a desktop, a document and a game's menu are all
    mostly their background, and refusing those is refusing the case the
    whole feature exists for.
    """
    try:
        down = max(1, height // BLANK_SAMPLES)
        across = max(1, width // BLANK_SAMPLES)
        first = None
        for y in range(1, height - 1, down):
            for x in range(1, width - 1, across):
                one = pixels[y][x]
                colour = (one.rgbRed, one.rgbGreen, one.rgbBlue)
                if first is None:
                    first = colour
                elif colour != first:
                    return False
    except Exception:                                # noqa: BLE001
        return False
    return True


def _pixel_type():
    """The four bytes of one pixel, as the recogniser wants them.

    **A name in somebody else's module is not an interface.** This asked
    `screenBitmap` for `RGBQUAD` and this NVDA answers `cannot import name
    'RGBQUAD' from 'screenBitmap'` - it lives in `winGDI` here - so the
    capture returned nothing on EVERY call, in a silent path, and the whole
    guest read as an empty screen with nothing anywhere saying why. It was
    found by making the refusal say which of its ten returns it was.

    So: NVDA's own type where this NVDA has one (identical memory, and one
    fewer thing to be wrong), and OUR OWN when it has not - it is four bytes
    in a documented order, and a reader must not go blind over the spelling
    of a class name.
    """
    # `winBindings.gdi32` is where this NVDA keeps it, and `winGDI.RGBQUAD`
    # is deprecated - reading it logs a WARNING on EVERY capture, which
    # buried the log in a virtual machine. So the current home is tried
    # first, then our own (byte-identical), and the deprecated name only if
    # an older NVDA has nothing else - where it is not deprecated and logs
    # nothing.
    for where, name in (('winBindings.gdi32', 'RGBQUAD'),
                        ('screenBitmap', 'RGBQUAD')):
        try:
            module = __import__(where, fromlist=[name.split('.')[-1]])
            found = getattr(module, name, None)
            if found is not None:
                return found
        except Exception:                            # noqa: BLE001
            continue
    import ctypes

    class _OurRGBQUAD(ctypes.Structure):
        # BGRA, which is what a 32-bit DIB holds and what `GetDIBits` fills.
        _fields_ = [('rgbBlue', ctypes.c_ubyte),
                    ('rgbGreen', ctypes.c_ubyte),
                    ('rgbRed', ctypes.c_ubyte),
                    ('rgbReserved', ctypes.c_ubyte)]

    return _OurRGBQUAD


def _wgc_pixels(hwnd, width, height, source, RGBQUAD):
    """A window's composed picture through Windows Graphics Capture, packed
    into the same ``(RGBQUAD * width * height)`` the recogniser wants. Or None.

    The bytes come back top-down BGRA, which is exactly ``RGBQUAD``'s own
    order, so the copy is a straight ``memmove`` - no per-pixel work in
    Python. The native helper handles the top-level-window crop; here it is
    only asked, and only when the device-context path came back flat.
    """
    try:
        from . import guestNative
    except Exception:                                # noqa: BLE001
        return None
    try:
        buffer = guestNative.capture_window(hwnd, width, height, source)
    except Exception:                                # noqa: BLE001
        return None
    if buffer is None:
        return None
    try:
        import ctypes
        pixels = (RGBQUAD * width * height)()
        want = width * height * 4
        ctypes.memmove(ctypes.byref(pixels), buffer, want)
        return pixels
    except Exception:                                # noqa: BLE001
        return None


def from_window(hwnd, width, height, source=None):
    """A window's picture taken from its OWN device context. Or None.

    ``source`` is ``(left, top, width, height)`` INSIDE the window, for
    reading one part of it - a region a key has just changed, which is
    the whole point of noticing that a key changed one.

    **A screen capture reads whatever is IN FRONT.** NVDA's own path -
    and Titan's - photographs a rectangle of the screen, which is right
    for the window somebody is looking at and wrong for the case this
    exists for: measured on a real VMware guest sitting behind a terminal,
    a screen capture of the guest's rectangle came back as the TERMINAL's
    text, read and announced as though it were the guest.

    A window's own DC has no such problem, and on that same guest it gave
    the real thing: 92% of the points the teal of a Windows 95 desktop,
    5% the grey of its taskbar, and the taskbar found as a highlight.

    `PrintWindow` is deliberately not used: measured on the same window,
    all three of its flags failed outright and answered pure black, which
    is what a surface drawn by Direct3D does. A flat answer here is
    refused rather than returned, so the caller falls back to the screen.
    """
    if not hwnd or width <= 0 or height <= 0:
        return _no_picture('no window, or a size of nothing')
    try:
        import ctypes
        import screenBitmap                          # noqa: F401
    except Exception as error:                       # noqa: BLE001
        return _no_picture('this NVDA has no screenBitmap: %s' % error)
    RGBQUAD = _pixel_type()
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        user32.GetWindowDC.restype = ctypes.c_void_p
        for maker in (gdi32.CreateCompatibleDC, gdi32.CreateCompatibleBitmap,
                      gdi32.SelectObject):
            maker.restype = ctypes.c_void_p
    except Exception as error:                       # noqa: BLE001
        return _no_picture('GDI could not be reached: %s' % error)
    import ctypes.wintypes as wintypes

    class _BIH(ctypes.Structure):
        _fields_ = [('biSize', ctypes.c_uint32), ('biWidth', ctypes.c_int32),
                    ('biHeight', ctypes.c_int32),
                    ('biPlanes', ctypes.c_uint16),
                    ('biBitCount', ctypes.c_uint16),
                    ('biCompression', ctypes.c_uint32),
                    ('biSizeImage', ctypes.c_uint32),
                    ('biXPelsPerMeter', ctypes.c_int32),
                    ('biYPelsPerMeter', ctypes.c_int32),
                    ('biClrUsed', ctypes.c_uint32),
                    ('biClrImportant', ctypes.c_uint32)]

    class _BMI(ctypes.Structure):
        _fields_ = [('bmiHeader', _BIH), ('bmiColors', RGBQUAD * 1)]

    holder = target = bitmap = old = None
    try:
        rect = wintypes.RECT()
        if not user32.GetWindowRect(ctypes.c_void_p(hwnd),
                                    ctypes.byref(rect)):
            return _no_picture('the window would not say where it is')
        whole, tall = rect.right - rect.left, rect.bottom - rect.top
        if whole <= 0 or tall <= 0:
            return _no_picture('the window has no size')
        from_left = from_top = 0
        if source:
            from_left, from_top = int(source[0]), int(source[1])
            whole, tall = int(source[2]), int(source[3])
            if whole <= 0 or tall <= 0:
                return _no_picture('the region asked for has no size')
        holder = user32.GetWindowDC(ctypes.c_void_p(hwnd))
        if not holder:
            return _no_picture('the window would not lend its own context')
        target = gdi32.CreateCompatibleDC(ctypes.c_void_p(holder))
        bitmap = gdi32.CreateCompatibleBitmap(ctypes.c_void_p(holder),
                                              width, height)
        if not target or not bitmap:
            return _no_picture('no bitmap could be made for %d by %d'
                               % (width, height))
        old = gdi32.SelectObject(ctypes.c_void_p(target),
                                 ctypes.c_void_p(bitmap))
        # Stretched, because the recogniser asked for a size of its own -
        # `RecogImageInfo` scales by `resizeFactor` and every rectangle it
        # answers is in that scale.
        gdi32.SetStretchBltMode(ctypes.c_void_p(target), 4)   # HALFTONE
        if not gdi32.StretchBlt(ctypes.c_void_p(target), 0, 0, width, height,
                                ctypes.c_void_p(holder), from_left, from_top,
                                whole, tall, SRCCOPY):
            return _no_picture('the window would not copy itself (StretchBlt '
                               'refused)')
        info = _BMI()
        info.bmiHeader.biSize = ctypes.sizeof(_BIH)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        pixels = (RGBQUAD * width * height)()
        if not gdi32.GetDIBits(ctypes.c_void_p(target),
                               ctypes.c_void_p(bitmap), 0, height,
                               ctypes.byref(pixels), ctypes.byref(info), 0):
            return _no_picture('the bitmap would not be read back')
        if _blank(pixels, width, height):
            # **A flat picture is a window that draws with Direct3D/DXGI/
            # OpenGL** - a virtual machine's guest, a Unity or SDL game -
            # and its device context has nothing in it. Windows Graphics
            # Capture asks the compositor for the window's own composed
            # surface instead, which is the one thing that answers those.
            woven = _wgc_pixels(hwnd, width, height, source, RGBQUAD)
            if woven is not None:
                _capture['taken'] += 1
                _capture['why'] = ''
                return woven
            return _no_picture('the window drew one flat colour, and Windows '
                               'Graphics Capture could not take it either')
        _capture['taken'] += 1
        _capture['why'] = ''
        return pixels
    except Exception as error:                       # noqa: BLE001
        return _no_picture('%s: %s' % (type(error).__name__, error))
    finally:
        try:
            if old:
                gdi32.SelectObject(ctypes.c_void_p(target),
                                   ctypes.c_void_p(old))
            if bitmap:
                gdi32.DeleteObject(ctypes.c_void_p(bitmap))
            if target:
                gdi32.DeleteDC(ctypes.c_void_p(target))
            if holder:
                user32.ReleaseDC(ctypes.c_void_p(hwnd),
                                 ctypes.c_void_p(holder))
        except Exception:                            # noqa: BLE001
            pass


def _inside_window(hwnd, info):
    """Where that screen rectangle is INSIDE the window, or None.

    A window's own device context has its origin at the window's top left
    corner, so a rectangle of the screen has to be moved there before it
    can be copied out of one.
    """
    rect = _window_rect(hwnd)
    if rect is None:
        return None
    left, top, right, bottom = rect
    inside = (int(info.screenLeft) - left, int(info.screenTop) - top,
              int(info.screenWidth), int(info.screenHeight))
    if inside[0] < 0 or inside[1] < 0:
        return None
    if inside[0] + inside[2] > right - left:
        return None
    if inside[1] + inside[3] > bottom - top:
        return None
    return inside


def read(left, top, width, height, hwnd=0):
    """Read a rectangle of the screen. ``Reading`` or None.

    ``hwnd`` asks for that WINDOW's own picture rather than the screen's,
    and falls back to the screen when the window will not draw itself.
    See :func:`from_window` for why, and for what it was measured on.

    Synchronous on the outside and asynchronous underneath: NVDA's
    recogniser answers through a callback, and every caller here is a
    watcher's poll or a keypress that wants an answer before it goes on. The
    wait is bounded - a recogniser that is not answering is not something to
    hold a reader for.

    **Never on NVDA's main thread with a long timeout.** The capture itself
    is quick, but the model behind Windows OCR is another process; a caller
    on the main thread should pass a short timeout or, better, be on a
    worker of its own.
    """
    if width <= 0 or height <= 0:
        return _note('there is nothing there to read')
    try:
        import ctypes                                # noqa: F401
        import screenBitmap
        from contentRecog import RecogImageInfo
    except Exception as error:                       # noqa: BLE001
        return _note('this NVDA has no content recognition: %s' % error)
    ok, why = available()
    if not ok:
        return _note(why)
    started = time.time()
    try:
        recognizer = _recognizer()
        info = RecogImageInfo.createFromRecognizer(left, top, width, height,
                                                   recognizer)
        # NVDA's own capture path (`contentRecog.recogUi._captureWithGdi`),
        # not one of ours: it is the thing that already works on every
        # display, DPI and screen-curtain arrangement people really have.
        pixels = from_window(hwnd, info.recogWidth, info.recogHeight,
                             source=_inside_window(hwnd, info)) \
            if hwnd else None
        if pixels is None:
            bitmap = screenBitmap.ScreenBitmap(info.recogWidth,
                                               info.recogHeight)
            pixels = bitmap.captureImage(info.screenLeft, info.screenTop,
                                         info.screenWidth, info.screenHeight)
    except Exception as error:                       # noqa: BLE001
        return _note('the window could not be photographed: %s' % error)

    answer = {}
    done = threading.Event()

    def got(result):
        answer['result'] = result
        done.set()

    try:
        recognizer.recognize(pixels, info, got)
    except Exception as error:                       # noqa: BLE001
        return _note('the recogniser refused: %s' % error)
    if not done.wait(TIMEOUT):
        try:
            recognizer.cancel()
        except Exception:                            # noqa: BLE001
            pass
        return _note('the recogniser did not answer')
    result = answer.get('result')
    if isinstance(result, Exception):
        return _note('the recogniser failed: %s' % result)
    reading = Reading.of(result, info)
    # **What is HIGHLIGHTED, from the same picture, at no extra cost.**
    # In a virtual machine the highlight IS the interface - the menu entry
    # the arrows are on, the selected file, the line the cursor is in -
    # and nothing in the picture says so except the colours. The words
    # were just read out of these pixels; reading the colours out of them
    # as well is one pass over a few hundred sampled points and needs no
    # second capture.
    try:
        reading.highlights = _highlighted(pixels, info)
    except Exception:                                # noqa: BLE001
        reading.highlights = []
    with _LOCK:
        _state['reads'] += 1
        _state['ms'] = round((time.time() - started) * 1000.0, 1)
    return reading


class _Pixels(object):
    """NVDA's captured bitmap, with the two methods a reader of it needs.

    `screenBitmap` answers a two-dimensional ctypes array of RGBQUAD, and
    everything that looks at a picture here wants `size` and
    `getpixel((x, y))`. This is that and nothing else - deliberately not a
    PIL image, because bringing PIL in for a dozen sampled points would be
    a dependency for nothing.
    """

    __slots__ = ('_rows', 'size')

    def __init__(self, rows, width, height):
        self._rows = rows
        self.size = (int(width), int(height))

    def getpixel(self, where):
        x, y = where
        pixel = self._rows[int(y)][int(x)]
        return (int(pixel.rgbRed), int(pixel.rgbGreen), int(pixel.rgbBlue))


def _highlighted(pixels, info):
    """The highlighted rows of this capture, in SCREEN coordinates.

    Screen coordinates because that is what every rectangle in a
    ``Reading`` is in, and a highlight in the picture's own coordinates
    compared against a word in the screen's would match nothing - or,
    worse, match the wrong line by a margin that changes with the window's
    size.
    """
    from . import virtualInput
    picture = _Pixels(pixels, info.recogWidth, info.recogHeight)
    found = []
    for _left, top, _width, height in virtualInput.highlights(picture):
        found.append((info.screenLeft,
                      _screen_y(info, top),
                      info.screenWidth,
                      _scaled(info, height)))
    return found


def read_window(hwnd):
    """Read one window. ``Reading`` or None.

    **What the program DREW is asked first.** NVDA's display model already
    holds the words every process passed to a GDI text call, with a
    rectangle per character - exact, instant, free, and nothing leaves the
    machine. Photographing a window that had already said what it was
    writing is the long way round; it is kept for the windows that really do
    need it, which is a Direct3D game, the inside of a virtual machine, and
    anything blitted in from elsewhere.

    An empty answer from the hook is not a failure - it means this window
    does not draw its text that way - so the fall-through is silent.
    """
    if _drawn_text_wanted():
        try:
            from . import drawnText
            drawn = drawnText.read_window(hwnd)
        except Exception as error:                   # noqa: BLE001
            drawn = None
            _note('the display model could not be read: %s' % error)
        if drawn:
            return drawn

    rect = _window_rect(hwnd)
    if rect is None:
        return _note('that window has no place on the screen')
    left, top, right, bottom = rect
    return read(left, top, right - left, bottom - top, hwnd=hwnd)


def _drawn_text_wanted():
    try:
        from . import configSpec
        return bool(configSpec.read().get('drawnText', True))
    except Exception:                                # noqa: BLE001
        return True


#: What the model tier answers about itself, kept so the settings page
#: and a diagnostic can say whether it is there without asking Titan on
#: every focus.
_model = {'asked': 0, 'reads': 0, 'failed': 0, 'why': '', 'ms': 0.0}


def model_report():
    with _LOCK:
        return dict(_model)


def read_window_model(hwnd, timeout=30.0):
    """Read one window with TITAN's local model. ``Reading`` or None.

    The third tier, and the one worth having: Windows' recogniser is
    instant and reads a stylised game menu or a low-resolution guest
    badly, and the AI reads everything and is a picture of the user's
    screen sent to a provider. This is a modern OCR model running on this
    machine - nothing leaves it, nothing is spent, and it is a second or
    two rather than a tenth of one, which is why it is what a KEY asks
    for and what an automatic reading falls back to, never the poll.

    It answers the same :class:`Reading` as Windows' own, so everything
    built on that - the pieces, the scene, the cursor, the virtual window
    - works on it unchanged.
    """
    from .link import LINK
    with _LOCK:
        _model['asked'] += 1
    ok, data = LINK.bridge('ocr.read_local', timeout=timeout,
                           hwnd=int(hwnd or 0))
    if not ok:
        return _model_failed(str(data))
    if not isinstance(data, dict) or not data.get('ok'):
        return _model_failed(_text((data or {}).get('text'))
                             or 'the local model answered nothing')
    lines = []
    for one in data.get('lines') or []:
        text = _text(one.get('text'))
        if not text:
            continue
        # One line, one word: the model detects a LINE of text and this
        # is what it found, so splitting it into words here would be
        # inventing boundaries the detector did not report. `_split` is
        # what finds the real ones, from the gaps.
        lines.append([{'text': text,
                       'left': int(one.get('left') or 0),
                       'top': int(one.get('top') or 0),
                       'width': int(one.get('width') or 0),
                       'height': int(one.get('height') or 0)}])
    with _LOCK:
        _model['reads'] += 1
        _model['ms'] = float(data.get('ms') or 0.0)
    reading = Reading(lines)
    # The highlight is read from the PICTURE, and the model tier has not
    # got one here - Titan photographed it, not this. Saying nothing is
    # highlighted is honest; guessing would move the cursor.
    reading.highlights = []
    return reading


def _model_failed(why):
    with _LOCK:
        _model['failed'] += 1
        _model['why'] = str(why)
    return None


def model_available(timeout=8.0):
    """Whether Titan has the local model. ``(ok, why)``."""
    from .link import LINK
    ok, data = LINK.bridge('ocr.model', timeout=timeout)
    if not ok:
        return False, str(data)
    if not isinstance(data, dict):
        return False, 'Titan answered something else'
    return bool(data.get('installed')), _text(data.get('why'))


def _window_rect(hwnd):
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(int(hwnd)),
                                                  ctypes.byref(rect)):
            return None
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception:                                # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# What came back
# --------------------------------------------------------------------------- #
class Reading:
    """The words of a window, and where each one is ON THE SCREEN.

    Deliberately not NVDA's `LinesWordsResult`: that is a
    `RecognitionResult` meant to become a virtual document the user browses,
    and what is wanted here is the two things a watcher and a mimic need -
    the text, to compare and to say, and a rectangle per word, to press.
    """

    def __init__(self, lines=None):
        #: ``[[{'text', 'left', 'top', 'width', 'height'}, ...], ...]``
        self.lines = lines or []
        #: ``[(left, top, width, height)]`` in SCREEN coordinates - the
        #: rows whose background is unlike the window's own. Empty when it
        #: could not be told, which leaves every line plain rather than
        #: guessing at one.
        self.highlights = []

    @classmethod
    def of(cls, result, info):
        """Out of NVDA's own result, in SCREEN coordinates.

        The recogniser answers in the coordinates of the picture it was
        given, which is the window scaled by `resizeFactor` - so a rectangle
        used as it comes points at the wrong place on the screen, and by an
        amount that changes with the window's size. `RecogImageInfo` is the
        only thing that knows the conversion and it is asked for it.
        """
        # **`data` is a LIST OF LINES, not a dict.** NVDA's own
        # `LinesWordsResult` documents it as
        # `[[{"x":..,"y":..,"width":..,"height":..,"text":..}, ...], ...]`,
        # and reading it as `data['lines']` answered nothing at all - so
        # every local reading came back empty and three features that rest
        # on it (the arrow-key screen review, watching a window locally,
        # finding a control by what is written on it) each reported
        # "Windows read nothing in that window". One mistake, three
        # features, and none of them was faulty.
        data = getattr(result, 'data', None)
        if isinstance(data, dict):
            # An older NVDA, or a recogniser of somebody else's, may hand
            # back the shape this used to expect. Taking both costs a line.
            data = data.get('lines') or []
        if not isinstance(data, (list, tuple)):
            return cls()
        lines = []
        for raw_line in data:
            words = []
            for word in raw_line or []:
                if not isinstance(word, dict):
                    continue
                text = str(word.get('text') or '').strip()
                if not text:
                    continue
                words.append({
                    'text': text,
                    'left': _screen_x(info, word.get('x')),
                    'top': _screen_y(info, word.get('y')),
                    'width': _scaled(info, word.get('width')),
                    'height': _scaled(info, word.get('height')),
                })
            if words:
                lines.append(words)
        return cls(lines)

    # ---------------------------------------------------------------- words
    @property
    def text(self):
        return '\n'.join(' '.join(word['text'] for word in line)
                         for line in self.lines)

    def __bool__(self):
        return bool(self.lines)

    def words(self):
        for line in self.lines:
            for word in line:
                yield word

    def rows(self):
        """Each line as ``(text, rectangle)`` - the shape a list wants."""
        out = []
        for line in self.lines:
            text = ' '.join(word['text'] for word in line)
            left = min(word['left'] for word in line)
            top = min(word['top'] for word in line)
            right = max(word['left'] + word['width'] for word in line)
            bottom = max(word['top'] + word['height'] for word in line)
            out.append((text, (left, top, right - left, bottom - top)))
        return out

    def find(self, wanted):
        """The line whose text contains ``wanted``, or None."""
        needle = str(wanted or '').strip().lower()
        if not needle:
            return None
        for text, rect in self.rows():
            if needle == text.strip().lower():
                return text, rect
        for text, rect in self.rows():
            if needle in text.lower():
                return text, rect
        return None

    def changed_from(self, other):
        """Whether this is a different reading. Text only, on purpose.

        A word that has moved by a pixel is the same screen; a word that has
        appeared or gone is not. Comparing the text is what makes watching
        affordable - it is the whole reason this tier exists - and it is
        what the AI tier is then spared.
        """
        if other is None:
            return True
        return self.text.strip() != getattr(other, 'text', '').strip()

    def added_since(self, other):
        """The lines this reading has and the other had not, in order.

        What a watcher says. A window whose whole reading is announced on
        every change would be a reader reading a menu from the top every
        time one line of it moved.
        """
        if other is None:
            return [text for text, _rect in self.rows()]
        before = {text.strip() for text, _rect in other.rows()}
        return [text for text, _rect in self.rows()
                if text.strip() and text.strip() not in before]


def _screen_x(info, value):
    try:
        return int(info.convertXToScreen(int(value or 0)))
    except Exception:                                # noqa: BLE001
        return 0


def _screen_y(info, value):
    try:
        return int(info.convertYToScreen(int(value or 0)))
    except Exception:                                # noqa: BLE001
        return 0


def _scaled(info, value):
    try:
        return max(0, int(round(int(value or 0)
                                / float(info.resizeFactor or 1))))
    except Exception:                                # noqa: BLE001
        return 0

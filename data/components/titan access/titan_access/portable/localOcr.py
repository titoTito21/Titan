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

#: How long a reading may take before it is given up on. Windows OCR is
#: fast; something that is not answering is not something to wait for on a
#: watcher's poll.
TIMEOUT = 4.0


def _text(value):
    return str(value or '').strip()


def report():
    with _LOCK:
        return dict(_state)


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


def read(left, top, width, height):
    """Read a rectangle of the screen. ``Reading`` or None.

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
        bitmap = screenBitmap.ScreenBitmap(info.recogWidth, info.recogHeight)
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
    """Read one window. ``Reading`` or None."""
    rect = _window_rect(hwnd)
    if rect is None:
        return _note('that window has no place on the screen')
    left, top, right, bottom = rect
    return read(left, top, right - left, bottom - top)


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

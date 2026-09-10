# -*- coding: utf-8 -*-
"""A real recogniser on this machine: better than Windows', free, private.

There are three tiers under "read this window as a picture", and until now
only two of them existed. Windows' own recogniser is instant, private and
free, and it is a 2016 line recogniser: it reads a crisp dialog well and a
game's stylised menu, a low-resolution virtual machine or anything at an
angle badly or not at all. The AI tier reads all of those and understands
them - and it is a picture of the user's screen sent to a provider, money
per reading, and measured slower than the bus waits.

This is the tier in between: **a modern OCR model, running here.** It is
downloaded once, on demand and only when the user says so, and after that
it costs nothing, sends nothing anywhere and works with no network at all.

Three rules it is built on, each of which is a mistake this repository
has already paid for once:

* **It is never imported at startup.** `onnxruntime` alone is most of a
  second, and Titan spent real work getting its start-up down. Every
  import here is inside a call.
* **Absent is a normal state, not a failure.** Nothing is installed by
  default; `available()` answers why not, and every caller falls back to
  the tier below rather than raising. A machine that never runs
  :func:`install` behaves exactly as it did before.
* **What it cannot do, it says.** A model that answered a guess where it
  had nothing would be worse than the recogniser it replaced.
"""

import os
import platform
import subprocess
import sys
import threading

_LOCK = threading.RLock()

#: What is needed, and why each one. `rapidocr` is the pipeline (text
#: detection, angle, recognition); `onnxruntime` runs the models; the rest
#: are what the pipeline itself imports.
PACKAGES = ('rapidocr', 'onnxruntime')

#: Where the model files are kept: beside Titan's other per-user data, so
#: they survive an update, are never inside a packaged Titan, and can be
#: deleted by hand by anybody who wants the space back. This is what
#: makes the recogniser a DOWNLOAD rather than part of the program.
FOLDER = 'models'

_state = {'reads': 0, 'failed': 0, 'why': '', 'ms': 0.0, 'engine': None,
          'installing': False, 'last_install': ''}


def folder():
    """``%APPDATA%/titosoft/Titan/models`` - or this platform's own."""
    system = platform.system()
    if system == 'Windows':
        base = os.getenv('APPDATA') or os.path.expanduser('~')
        base = os.path.join(base, 'titosoft', 'Titan')
    elif system == 'Darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library',
                            'Application Support', 'titosoft', 'Titan')
    else:
        base = os.path.join(os.path.expanduser('~'), '.config',
                            'titosoft', 'Titan')
    return os.path.join(base, FOLDER)


def available():
    """Whether a reading can be made here and now. ``(ok, why)``.

    Asked rather than assumed on every call: a user may install this
    while Titan is running, and a Titan that had decided at start-up that
    it was absent would go on saying so until it was restarted.
    """
    missing = []
    for name in PACKAGES:
        try:
            __import__(name)
        except Exception:                            # noqa: BLE001
            missing.append(name)
    if missing:
        return False, ('the local model is not installed here (%s). '
                       'Install it from Settings -> AI features, or with '
                       'ocr.install_model.' % ', '.join(missing))
    return True, ''


def installed():
    ok, _why = available()
    return ok


# --------------------------------------------------------------------------- #
# Getting it
# --------------------------------------------------------------------------- #
def install(timeout=1800.0):
    """Fetch the recogniser onto this machine. ``(ok, sentence)``.

    **It is a download, so it is asked for rather than done.** Every
    caller of this is a user pressing something or an action being run
    deliberately; nothing here runs by itself, and nothing runs on the
    GUI thread - a pip install is minutes, and Titan's own thread is the
    one drawing the window.

    The models themselves come down on the first reading, into
    :func:`folder`, which is why the first one is slower than the rest.
    """
    with _LOCK:
        if _state['installing']:
            return False, 'The local recogniser is already being installed.'
        _state['installing'] = True
    try:
        ok, _why = available()
        if ok:
            return True, 'The local recogniser is already installed.'
        # **Into the user's own site, deliberately.** Titan's Python may
        # sit in `Program Files`, where installing needs administrator
        # rights - and asking somebody to elevate a screen reader to read
        # a window is the wrong trade entirely. `--user` needs no rights
        # at all, lands in `%APPDATA%/Python`, and is undone by deleting
        # that folder. pip falls back to it by itself when site-packages
        # is not writable; saying so is what makes it predictable rather
        # than lucky.
        found = _pip(['install', '--upgrade', '--user'] + list(PACKAGES),
                     timeout=timeout)
        if not found[0] and 'user' in (found[1] or '').lower() \
                and 'site-packages' in (found[1] or '').lower():
            # A virtual environment refuses `--user`, and there
            # site-packages is writable anyway.
            found = _pip(['install', '--upgrade'] + list(PACKAGES),
                         timeout=timeout)
        with _LOCK:
            _state['last_install'] = found[1][-400:]
        if not found[0]:
            return False, ('The local recogniser could not be installed: %s'
                           % found[1][-300:])
        ok, why = available()
        if not ok:
            return False, ('It installed and still cannot be loaded: %s' % why)
        return True, ('The local recogniser is installed into your own '
                      'user folder - no administrator rights were needed '
                      'and nothing in Titan changed. The models come down '
                      'on the first reading, into %s.' % folder())
    finally:
        with _LOCK:
            _state['installing'] = False


def _pip(arguments, timeout=1800.0):
    """Run pip for THIS interpreter. ``(ok, output)``.

    `sys.executable` rather than a `pip` on the path: Titan may be running
    from a virtual environment, from a compiled build, or beside another
    Python entirely, and installing into the wrong one produces a package
    that is there and cannot be imported.
    """
    try:
        answer = subprocess.run(
            [sys.executable, '-m', 'pip'] + list(arguments),
            capture_output=True, text=True, timeout=timeout)
    except Exception as error:                       # noqa: BLE001
        return False, '%s: %s' % (type(error).__name__, error)
    return answer.returncode == 0, (answer.stdout or '') + (answer.stderr or '')


# --------------------------------------------------------------------------- #
# Using it
# --------------------------------------------------------------------------- #
def _engine():
    """The pipeline, made once and kept.

    Building it loads the models, which is the slow part - about a second
    - and doing that per reading would make the tier useless for exactly
    the thing it is for, which is watching a window that changes.
    """
    with _LOCK:
        found = _state['engine']
    if found is not None:
        return found
    import os as _os
    from rapidocr import RapidOCR
    where = folder()
    try:
        _os.makedirs(where, exist_ok=True)
    except Exception:                                # noqa: BLE001
        pass
    # **The models live in the user's own data, not inside an install.**
    # Left to itself the library puts them beside its own package - which
    # is a folder an update replaces, a packaged Titan would have to
    # carry, and nobody would think to delete. `Global.model_root_dir` is
    # the library's own override for exactly this.
    try:
        made = RapidOCR(params={'Global.model_root_dir': where})
    except Exception:                                # noqa: BLE001
        # An older or newer rapidocr that does not take that key is
        # still a working recogniser; where it keeps its models is worth
        # less than having one.
        made = RapidOCR()
    with _LOCK:
        _state['engine'] = made
    return made


def read_array(picture):
    """Read an ``(h, w, 3)`` uint8 RGB array. ``(ok, lines_or_why)``.

    A line is ``{'text', 'box': (left, top, width, height), 'score'}`` in
    the PICTURE's own pixels - never the screen's. Whatever captured the
    picture is the only thing that knows where it came from, which is the
    rule `capture.Capture` already enforces for the AI tier: the model is
    never asked to do arithmetic about the screen.
    """
    import time
    ok, why = available()
    if not ok:
        return False, why
    started = time.time()
    try:
        engine = _engine()
    except Exception as error:                       # noqa: BLE001
        return _failed('the recogniser would not load: %s: %s'
                       % (type(error).__name__, error))
    try:
        answer = engine(picture)
    except Exception as error:                       # noqa: BLE001
        return _failed('the recogniser failed: %s: %s'
                       % (type(error).__name__, error))
    lines = _lines_of(answer)
    with _LOCK:
        _state['reads'] += 1
        _state['ms'] = round((time.time() - started) * 1000.0, 1)
    return True, lines


def _lines_of(answer):
    """RapidOCR's answer, as this module's own shape.

    **Read defensively on purpose.** This is somebody else's library and
    its result object has changed shape between major versions - boxes,
    txts and scores as three parallel lists in one, a list of triples in
    another. A tier that stopped working on an upgrade would be a tier
    nobody could rely on, and the fields wanted here are few enough to
    find either way.
    """
    boxes = getattr(answer, 'boxes', None)
    texts = getattr(answer, 'txts', None)
    scores = getattr(answer, 'scores', None)
    rows = []
    if boxes is not None and texts is not None:
        for index, box in enumerate(boxes):
            text = _text(texts[index] if index < len(texts) else '')
            if not text:
                continue
            score = 0.0
            try:
                score = float(scores[index]) if scores is not None else 0.0
            except Exception:                        # noqa: BLE001
                score = 0.0
            rows.append({'text': text, 'box': _rect_of(box), 'score': score})
        return rows
    # The older shape: an iterable of (box, text, score).
    try:
        for one in (answer or []):
            if not one or len(one) < 2:
                continue
            text = _text(one[1])
            if not text:
                continue
            score = float(one[2]) if len(one) > 2 else 0.0
            rows.append({'text': text, 'box': _rect_of(one[0]),
                         'score': score})
    except Exception:                                # noqa: BLE001
        return rows
    return rows


def _rect_of(box):
    """A four-point polygon as ``(left, top, width, height)``.

    The detector answers a QUADRILATERAL, because text can be at an
    angle; everything downstream here wants a rectangle to click in the
    middle of, so it is the bounding box - which for a screenshot of a
    window is the same thing.
    """
    try:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        left, top = int(min(xs)), int(min(ys))
        return (left, top, int(max(xs)) - left, int(max(ys)) - top)
    except Exception:                                # noqa: BLE001
        return (0, 0, 0, 0)


def _text(value):
    return str(value or '').strip()


def _failed(why):
    with _LOCK:
        _state['failed'] += 1
        _state['why'] = why
    return False, why


def report():
    with _LOCK:
        found = dict(_state)
    found['engine'] = found['engine'] is not None
    found['installed'] = installed()
    found['folder'] = folder()
    return found


def forget():
    """Throw the loaded pipeline away - for the tests, and after an
    install, so a Titan that was running when it arrived can use it."""
    with _LOCK:
        _state['engine'] = None


# --------------------------------------------------------------------------- #
# Offering it at the moment it would help
# --------------------------------------------------------------------------- #
#: The settings key that remembers the answer. Asked ONCE: a question
#: somebody has said no to and is asked again every time they read a
#: window is a question that has become a nuisance, and the offer is
#: still there in Settings and in `ocr.install_model` for anybody who
#: changes their mind.
ASKED = 'ai/local_ocr_offered'


def _asked_already():
    try:
        from src.settings.settings import get_setting
        return str(get_setting(ASKED, '') or '').strip().lower() in (
            'yes', 'no', 'true', 'false', '1', '0')
    except Exception:                                # noqa: BLE001
        return False


def _remember(answer):
    try:
        from src.settings.settings import save_settings, load_settings
        found = load_settings()
        found[ASKED] = 'yes' if answer else 'no'
        save_settings(found)
    except Exception:                                # noqa: BLE001
        pass


def offer(force=False):
    """Offer to fetch the recogniser, once, when a reading would use it.

    **Asked where the need arises**, which is somebody reading a window as
    a picture - not in a settings page they would have to already know
    about. It answers at once and does the work on a thread of its own: a
    download is minutes and the caller is in the middle of a reading.

    ``(offered, why_not)``. Nothing is offered when it is already here,
    when the user has answered before, or when there is no running Titan
    to put a question in - a dialog raised with nothing behind it answers
    itself, which is how a "yes" gets written that nobody gave.
    """
    if installed():
        return False, 'it is already installed'
    if not force and _asked_already():
        return False, 'the user has already been asked'
    try:
        from src.titan_core.client_consent import on_screen
        if not on_screen():
            return False, 'there is no running Titan to ask in'
    except Exception:                                # noqa: BLE001
        return False, 'there is nobody to ask'

    def ask():
        import wx
        from src.titan_core.translation import _
        dialog = wx.MessageDialog(
            None,
            _('Titan can read this window with a recogniser that runs on '
              'your own computer. It is a download of about 250 MB, and '
              'after it nothing leaves this machine, no reading costs '
              'anything and it needs no AI key.\n\n'
              'Download it now?'),
            _('Read this window without the AI'),
            wx.YES_NO | wx.ICON_QUESTION)
        try:
            said_yes = dialog.ShowModal() == wx.ID_YES
        finally:
            dialog.Destroy()
        _remember(said_yes)
        if said_yes:
            _fetch_on_a_thread()

    try:
        import wx
        wx.CallAfter(ask)
    except Exception as error:                       # noqa: BLE001
        return False, str(error)
    return True, ''


def _fetch_on_a_thread():
    """Fetch it without holding the window that asked."""
    def work():
        ok, said = install()
        forget()
        try:
            from src.system.notifications import show_notification
            from src.titan_core.translation import _
            show_notification(_('Local recogniser'), said)
        except Exception:                            # noqa: BLE001
            pass
        return ok
    threading.Thread(target=work, name='TitanLocalOcrInstall',
                     daemon=True).start()

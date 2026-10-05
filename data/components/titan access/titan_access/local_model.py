# -*- coding: utf-8 -*-
"""The local OCR model, owned by Titan Access and kept in its own folder.

The third tier of a local reading - a modern OCR model (RapidOCR on
ONNX Runtime) running on this machine, nothing sent anywhere - used to be
asked of TITAN (``ocr.model`` / ``ocr.read_local`` / ``ocr.install_model``
on its typed doorway). Two things made that unusable in a compiled Titan:
the doorway is frozen into Titan.exe while this component is data beside
it, so a newer reader asked an older Titan for calls it had not got; and
Titan installed the libraries with ``sys.executable -m pip``, which in a
compiled Titan is Titan.exe and not a Python at all.

So the reader carries it itself, and **everything lives inside the
component's own folder** - nothing about it needs Titan to be rebuilt:

* the libraries in ``lib/python/<platform>-<python>/`` (the same Python
  the reader runs in, so a wheel built for it loads), added to the END of
  ``sys.path`` so whatever Titan already carries - numpy above all -
  is the copy that is used;
* the model files in ``lib/ocr_models/`` (or the user's own data when the
  component folder cannot be written to).

Installing is a ``pip install --target`` with a real Python of the same
version: ``sys.executable`` when the reader runs from source, otherwise
the one the ``py`` launcher, ``PATH`` or the usual install folders have.
"""

import os
import shutil
import subprocess
import sys
import threading
import time

_LOCK = threading.RLock()

#: What is needed: the pipeline, and what runs its models.
PACKAGES = ('rapidocr', 'onnxruntime')

_state = {'reads': 0, 'failed': 0, 'why': '', 'ms': 0.0, 'engine': None,
          'installing': False, 'last_install': ''}

#: The component's own folder (``data/components/titan access``).
COMPONENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tag():
    platform = ('win' if sys.platform.startswith('win')
                else 'mac' if sys.platform == 'darwin' else 'linux')
    return '%s-cp%d%d' % (platform, sys.version_info[0], sys.version_info[1])


def library_folder():
    """Where this reader's own copy of the libraries lives."""
    return os.path.join(COMPONENT, 'lib', 'python', _tag())


def _writable(folder):
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, '.write_test')
        with open(probe, 'w') as handle:
            handle.write('x')
        os.remove(probe)
        return True
    except OSError:
        return False


def models_folder():
    """The model files: inside the component when it can be written to,
    the user's own data otherwise."""
    own = os.path.join(COMPONENT, 'lib', 'ocr_models')
    if _writable(own):
        return own
    base = os.getenv('APPDATA') or os.path.join(os.path.expanduser('~'),
                                                '.config')
    return os.path.join(base, 'titosoft', 'Titan', 'accessibility',
                        'ocr_models')


def _use_own_libraries():
    """Put the component's libraries on the path - at the END, so a
    library Titan already carries is the one imported."""
    folder = library_folder()
    if os.path.isdir(folder) and folder not in sys.path:
        sys.path.append(folder)
        if sys.platform.startswith('win'):
            # onnxruntime and opencv keep DLLs beside their packages.
            for sub in ('onnxruntime/capi', 'cv2', ''):
                where = os.path.join(folder, sub)
                if os.path.isdir(where):
                    try:
                        os.add_dll_directory(where)
                    except (OSError, AttributeError):
                        pass


def available():
    """Whether a reading can be made here and now. ``(ok, why)``."""
    _use_own_libraries()
    missing = []
    for name in PACKAGES:
        try:
            __import__(name)
        except Exception:                            # noqa: BLE001
            missing.append(name)
    if missing:
        return False, ('the local model is not installed in Titan Access '
                       '(%s missing).' % ', '.join(missing))
    return True, ''


def installed():
    return available()[0]


def _python():
    """A real Python of the reader's own version, or None."""
    want = '%d.%d' % sys.version_info[:2]
    if not getattr(sys, 'frozen', False) and sys.executable:
        return [sys.executable]
    if sys.platform.startswith('win'):
        launcher = shutil.which('py')
        if launcher:
            return [launcher, '-' + want]
        guesses = [r'C:\Python%s\python.exe' % want.replace('.', ''),
                   os.path.join(os.getenv('LOCALAPPDATA') or '', 'Programs',
                                'Python', 'Python%s' % want.replace('.', ''),
                                'python.exe')]
        for one in guesses:
            if os.path.isfile(one):
                return [one]
        found = shutil.which('python')
        return [found] if found else None
    found = shutil.which('python' + want) or shutil.which('python3')
    return [found] if found else None


def install(timeout=1800.0):
    """Fetch the libraries into the component's own folder. ``(ok, said)``.

    Minutes, and a download - asked for, never done by itself, and never
    on the GUI thread.
    """
    python = _python()
    if not python:
        return False, ('no Python %d.%d was found to install the local model '
                       'with' % sys.version_info[:2])
    target = library_folder()
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as error:
        return False, 'the folder %s cannot be written: %s' % (target, error)
    with _LOCK:
        _state['installing'] = True
    try:
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        done = subprocess.run(python + ['-m', 'pip', 'install', '--upgrade',
                                        '--target', target] + list(PACKAGES),
                              capture_output=True, text=True,
                              timeout=timeout, creationflags=flags)
        said = ((done.stdout or '') + (done.stderr or ''))[-2000:]
        ok = done.returncode == 0
    except Exception as error:                       # noqa: BLE001
        ok, said = False, '%s: %s' % (type(error).__name__, error)
    finally:
        with _LOCK:
            _state['installing'] = False
            _state['last_install'] = time.strftime('%Y-%m-%d %H:%M')
    forget()
    if ok:
        return True, ('The local model is installed in %s. The model files '
                      'come down on the first reading.' % target)
    return False, said


def _engine():
    with _LOCK:
        found = _state['engine']
    if found is not None:
        return found
    _use_own_libraries()
    from rapidocr import RapidOCR
    where = models_folder()
    try:
        os.makedirs(where, exist_ok=True)
    except OSError:
        pass
    try:
        made = RapidOCR(params={'Global.model_root_dir': where})
    except Exception:                                # noqa: BLE001
        made = RapidOCR()
    with _LOCK:
        _state['engine'] = made
    return made


def forget():
    with _LOCK:
        _state['engine'] = None


def _text(value):
    return str(value or '').strip()


def _rect_of(box):
    try:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        left, top = int(min(xs)), int(min(ys))
        return (left, top, int(max(xs)) - left, int(max(ys)) - top)
    except Exception:                                # noqa: BLE001
        return (0, 0, 0, 0)


def _lines_of(answer):
    """RapidOCR's answer, read defensively: its result has changed shape
    between major versions."""
    boxes = getattr(answer, 'boxes', None)
    texts = getattr(answer, 'txts', None)
    scores = getattr(answer, 'scores', None)
    rows = []
    if boxes is not None and texts is not None:
        for index, box in enumerate(boxes):
            text = _text(texts[index] if index < len(texts) else '')
            if not text:
                continue
            try:
                score = float(scores[index]) if scores is not None else 0.0
            except Exception:                        # noqa: BLE001
                score = 0.0
            rows.append({'text': text, 'box': _rect_of(box), 'score': score})
        return rows
    try:
        for one in (answer or []):
            if not one or len(one) < 2 or not _text(one[1]):
                continue
            rows.append({'text': _text(one[1]), 'box': _rect_of(one[0]),
                         'score': float(one[2]) if len(one) > 2 else 0.0})
    except Exception:                                # noqa: BLE001
        pass
    return rows


def _failed(why):
    with _LOCK:
        _state['failed'] += 1
        _state['why'] = why
    return {'ok': False, 'lines': [], 'text': why, 'installed': installed()}


def read_window(hwnd=0, rect=None):
    """Read a window - or ``rect`` (left, top, width, height) of it -
    with the model. Titan's doorway's shape: lines in SCREEN coordinates."""
    ok, why = available()
    if not ok:
        return {'ok': False, 'text': why, 'lines': [], 'installed': False}
    if not sys.platform.startswith('win'):
        return _read_posix()
    from . import windows_ocr
    if rect:
        left, top = int(rect[0]), int(rect[1])
        right, bottom = left + int(rect[2]), top + int(rect[3])
    else:
        whole = windows_ocr.window_rect(hwnd) if hwnd else None
        if whole is None:
            whole = windows_ocr._screen_rect()
        left, top, right, bottom = whole
    shot = windows_ocr.capture(left, top, right - left, bottom - top,
                               hwnd=hwnd)
    if shot is None:
        return _failed('that window could not be photographed')
    width, height, bits = shot
    try:
        import numpy as np
        picture = np.frombuffer(bits, dtype=np.uint8).reshape(
            height, width, 4)[:, :, 2::-1].copy()
    except Exception as error:                       # noqa: BLE001
        return _failed('the picture could not be prepared: %s' % error)
    return _read_picture(picture, left, top)


def _read_posix():
    """Linux: the screen, photographed by this reader itself through
    python-xlib (which works under XWayland too); Titan's own capture -
    a screenshot tool for a Wayland session - only when X will not
    answer."""
    picture = _x_picture()
    if picture is None:
        try:
            from src.ai.ocr import capture as capture_module
            from src.titan_core import bridge_api
            shot = capture_module.capture_screen()
            picture = (bridge_api._picture_of(shot)
                       if shot is not None else None)
        except Exception:                            # noqa: BLE001
            picture = None
    if picture is None:
        return _failed('the screen could not be photographed')
    return _read_picture(picture, 0, 0)


def _x_picture():
    """The X root window as an ``(h, w, 3)`` RGB array, or None."""
    try:
        import numpy as np
        from Xlib import X, display
        screen = display.Display().screen()
        root = screen.root
        geometry = root.get_geometry()
        image = root.get_image(0, 0, geometry.width, geometry.height,
                               X.ZPixmap, 0xffffffff)
        data = np.frombuffer(image.data, dtype=np.uint8)
        data = data.reshape(geometry.height, geometry.width, 4)
        return data[:, :, 2::-1].copy()
    except Exception:                                # noqa: BLE001
        return None


def _read_picture(picture, left, top):
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
    lines = []
    for one in _lines_of(answer):
        x, y, w, h = one['box']
        lines.append({'text': one['text'], 'score': one['score'],
                      'left': int(left) + x, 'top': int(top) + y,
                      'width': w, 'height': h})
    with _LOCK:
        _state['reads'] += 1
        _state['ms'] = round((time.time() - started) * 1000.0, 1)
        ms = _state['ms']
    return {'ok': True, 'lines': lines, 'installed': True, 'ms': ms}


def report():
    with _LOCK:
        found = dict(_state)
    found['engine'] = found['engine'] is not None
    ok, why = available()
    found['installed'] = ok
    found['why'] = found['why'] or why
    found['folder'] = models_folder()
    found['libraries'] = library_folder()
    return found


# --------------------------------------------------------------------------- #
# Answered for the shared modules, in the shape of Titan's doorway
# --------------------------------------------------------------------------- #

def call_model(_args):
    return report()


def call_install(args):
    ok, said = install(timeout=float((args or {}).get('timeout') or 1800.0))
    return {'ok': bool(ok), 'text': said, 'installed': installed()}


def call_read_local(args):
    args = args or {}
    rect = None
    if all(key in args for key in ('left', 'top', 'width', 'height')):
        rect = (args['left'], args['top'], args['width'], args['height'])
    return read_window(int(args.get('hwnd') or 0), rect=rect)

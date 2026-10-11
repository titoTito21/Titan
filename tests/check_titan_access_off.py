# -*- coding: utf-8 -*-
"""What is left of Titan Access once it has been switched off.

    python tests/check_titan_access_off.py [--as-in-titan] [--mute]

``--as-in-titan`` starts Titan's own speech and sound first, as Titan has
them before the reader: what THEY start (the Titan TTS bridges, the audio
device watcher) is Titan's and is not counted.

The real engine is started on a COPY of the user's stores, left running a
few seconds, stopped, and then asked: which of its threads are still
alive, which processes it started are still running, whether it still
holds NVDA's controller endpoint or the hidden "NVDA" window Tolk looks
for, and whether its keyboard hook is still installed. Off must mean all
of that is gone. Windows only; it presses no keys.
"""

import ctypes
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')

base = os.getenv('APPDATA') or os.path.expanduser('~')
source = os.path.join(base, 'titosoft', 'Titan')
target = tempfile.mkdtemp(prefix='titan_access_off_')
for name in ('screenreader', 'accessibility'):
    there = os.path.join(source, name)
    if os.path.isdir(there):
        shutil.copytree(there, os.path.join(target, 'titosoft', 'Titan', name),
                        ignore=shutil.ignore_patterns('*.log'))
os.environ['APPDATA'] = target
for path in (os.path.join(COMPONENT, 'lib'), COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)


def children():
    try:
        import psutil
        return {p.pid: p.name() for p in psutil.Process().children(recursive=True)}
    except Exception as e:                           # noqa: BLE001
        return {'?': str(e)}


def nvda_window():
    return bool(ctypes.windll.user32.FindWindowW('wxWindowClassNR', 'NVDA'))


def main():
    if '--as-in-titan' in sys.argv:
        # Titan's own speech is up before the reader, as it is in Titan:
        # what it starts is Titan's, not the reader's.
        from src.titan_core.stereo_speech import get_stereo_speech
        get_stereo_speech()
        try:
            from src.titan_core import sound
            sound.initialize_sound()
        except Exception as e:                       # noqa: BLE001
            print('Titan sound:', e)
        time.sleep(1.0)
    before_threads = {t.ident for t in threading.enumerate()}
    before_children = children()
    before_window = nvda_window()
    if '--mute' in sys.argv:
        # "Mute outside TCE" on: the controller endpoint must be left to
        # the system's reader.
        from titan_access.settings_store import get_settings
        settings = get_settings()
        settings.mute_outside_tce = True
        settings.save()
    from titan_access.engine import get_engine
    engine = get_engine()
    engine.start()
    time.sleep(float(os.environ.get('TA_RUN_SECONDS', '5')))
    during = {t.name for t in threading.enumerate()}
    print('threads while running:', sorted(during))
    print('children while running:', children())
    print('NVDA window while running:', nvda_window())
    print('controller endpoint held while running:',
          getattr(engine, 'nvda_ctl', None) is not None)
    engine.stop()
    time.sleep(2.0)
    left = [t for t in threading.enumerate() if t.ident not in before_threads]
    print('THREADS LEFT:', sorted(
        '%s(%s %s)' % (t.name, type(t).__module__ + '.' + type(t).__qualname__, getattr(getattr(t, '_target', None), '__qualname__', ''))
        for t in left))
    for t in left:
        if isinstance(t, threading.Timer):
            print('  timer:', t.interval, getattr(t.function, '__qualname__', t.function))
    extra = {pid: name for pid, name in children().items()
             if pid not in before_children}
    print('PROCESSES LEFT:', extra)
    print('NVDA WINDOW LEFT:', nvda_window() and not before_window)
    kb = getattr(engine, 'keyboard', None)
    print('HOOK LEFT:', bool(kb is not None and getattr(kb, '_installed', False)))
    ctl = getattr(engine, 'nvda_ctl', None)
    try:
        endpoint = bool(ctl and ctl._dll and ctl._read_owns())
    except Exception:                                # noqa: BLE001
        endpoint = False
    print('ENDPOINT LEFT:', endpoint)
    clean = not left and not extra and not endpoint and not (
        kb is not None and getattr(kb, '_installed', False))
    print('OFF MEANS OFF' if clean else 'SOMETHING WAS LEFT RUNNING')
    os._exit(0 if clean else 1)


if __name__ == '__main__':
    main()

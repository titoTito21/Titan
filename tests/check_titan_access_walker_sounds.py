# -*- coding: utf-8 -*-
"""Which sound file Titan Access really plays for the palette, a message
and the virtual window.

    python tests/check_titan_access_walker_sounds.py

The shared walkers run as they do inside Titan's process: `icons.play` ->
Titan's `sound.play_reader_sound` -> the reader set resolved theme first,
component last. Only the final step - starting the file on the mixer - is
replaced by a recorder, so nothing is heard; the host window is left out
so the user's window keeps the foreground. Fails on a wrong file.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
os.environ['APPDATA'] = tempfile.mkdtemp()       # never the user's own store
for path in (COMPONENT, TITAN):
    sys.path.insert(0, path)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from src.titan_core import sound                  # noqa: E402
played = []
sound._start_sound_file = lambda path, pan=None, **_k: (played.append(path), ('test', None))[1]

from titan_access.portable import palette, virtualWindow, hostWindow, dialogs  # noqa: E402
hostWindow.show = lambda *a, **k: (k.get('then') or (lambda: None))()
hostWindow.hide = lambda *a, **k: None
hostWindow.retitle = lambda *a, **k: None
palette._say = lambda *a, **k: None
palette.say_here = lambda *a, **k: None

problems = []


def step(what, action, want):
    mark = len(played)
    action()
    got = [os.path.basename(p) for p in played[mark:]]
    where = [os.path.relpath(p, TITAN) for p in played[mark:]]
    print('%-34s -> %s' % (what, where))
    if got != want:
        problems.append('%s: wanted %r, played %r' % (what, want, got))


rows = [{'label': 'Jeden'}, {'label': 'Dwa'}]
step('palette opens', lambda: palette.show(rows, 'Paleta'), ['sr_menu_on.ogg'])
step('a level inside it (no sound)', lambda: palette.show(rows, 'Poziom'), [])
step('a message replaces the palette', lambda: palette.page('Odpowiedz AI', 'AI'),
     ['sr_message.ogg'])
step('palette/message closes', palette.stop, ['sr_menu_off.ogg'])
step('an AI answer (dialogs.message)', lambda: dialogs.message('Odpowiedz.\nDruga linia.', 'Perun'),
     ['sr_message.ogg'])
step('the message closes', palette.stop, ['sr_menu_off.ogg'])


class _Window(object):
    name = 'Okno probne'
    windowHandle = 0
    location = (0, 0, 100, 100)


virtualWindow._foreground = lambda: _Window()
virtualWindow.nodes_of = lambda window, note=None: [
    {'name': 'OK', 'role': 'button', 'rect': (0, 0, 10, 10)}]
virtualWindow.say_here = lambda *a, **k: None
step('virtual window on', virtualWindow.start, ['virtual_window_on.ogg'])
step('virtual window off', virtualWindow.stop, ['virtual_window_off.ogg'])

print()
print('PROBLEMS:' if problems else 'ALL GOOD', *problems, sep='\n  ')
sys.exit(1 if problems else 0)

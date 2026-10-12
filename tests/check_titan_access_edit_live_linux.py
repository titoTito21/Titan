# -*- coding: utf-8 -*-
"""The edit-field path on Linux, against a REAL GtkTextView read over AT-SPI.

    python3 tests/check_titan_access_edit_live_linux.py      (WSLg or a desktop)

A GTK window with a wrapping multiline text view runs in a process of its
own; the reader's handler and KeyboardHook._process (fed exactly as
`atspi_keys` feeds it, the typed character from the keysym) read it
through AT-SPI 2. What the program does with each key is played through
the text's own interface (caret offset, inserted text). Nothing is pressed,
speech is recorded, the home is a fresh one. Fails on anything wrong.
"""

import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
HOME = tempfile.mkdtemp(prefix='titan_access_edit_linux_')
os.environ.update(HOME=HOME, APPDATA=HOME, XDG_CONFIG_HOME=os.path.join(HOME, '.config'),
                  NO_AT_BRIDGE='0')
os.environ.setdefault('GDK_BACKEND', 'x11')
os.environ.setdefault('GTK_MODULES', 'gail:atk-bridge')
for path in (COMPONENT, TITAN):
    sys.path.insert(0, path)

TITLE = 'TitanAccessEditProbe%d' % os.getpid()
TEXT = 'Ala ma kota.\nDrugi wiersz tutaj.\nTrzeci.'
APP = r'''
import gi, sys
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
w = Gtk.Window(title=%r)
w.set_default_size(320, 200)
v = Gtk.TextView()
v.set_wrap_mode(Gtk.WrapMode.WORD)
v.get_buffer().set_text(%r)
w.add(v)
w.connect("destroy", Gtk.main_quit)
w.show_all()
Gtk.main()
''' % (TITLE, TEXT)
app = subprocess.Popen([sys.executable, '-c', APP])

from titan_access import atspi_focus, atspi_keys       # noqa: E402
from titan_access import localization as loc            # noqa: E402
from titan_access.contracts import AccessibleObject     # noqa: E402
from titan_access.engine import TitanAccessEngine       # noqa: E402
from titan_access.editable_text import EditableTextHandler  # noqa: E402
from titan_access.keyboard_hook import KeyboardHook     # noqa: E402

said, problems = [], []


class Recorder:
    def speak_async(self, text, position=0.0, interrupt=True, pitch_offset=0, **_k):
        said.append(text)

    speak = speak_async

    def stop(self):
        pass


def find_text(Atspi):
    desktop = Atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        app_ = desktop.get_child_at_index(i)
        stack = [app_]
        seen = 0
        while stack and seen < 400:
            node = stack.pop()
            seen += 1
            try:
                if node.get_role() == Atspi.Role.FRAME and node.get_name() != TITLE:
                    continue
                if node.get_role() == Atspi.Role.TEXT:
                    return node
                for j in range(node.get_child_count()):
                    stack.append(node.get_child_at_index(j))
            except Exception:
                pass
    return None


def main():
    Atspi = atspi_focus.atspi()
    if Atspi is None:
        print('no AT-SPI here'); return 1
    node = None
    for _ in range(60):
        node = find_text(Atspi)
        if node is not None:
            break
        time.sleep(0.25)
    if node is None:
        print('the GTK text view did not appear'); return 1
    text_iface = node.get_text_iface() if hasattr(node, 'get_text_iface') else node
    Atspi.Text.set_caret_offset(text_iface, 0)

    loc.set_language('pl')
    engine = TitanAccessEngine()
    engine.speech = Recorder()
    engine._muted_for_foreground = lambda: False
    engine.settings.phonetic_letters = False
    engine.settings.keyboard_echo = 'CharactersAndWords'
    engine.settings.set('Symbols', 'PunctuationLevel', 'none')   # lines as written
    engine.editable = EditableTextHandler(engine)
    queued = []
    engine.submit_read = queued.append
    engine.post_to_worker = queued.append
    engine.current_object = AccessibleObject(role='edit', name='Pole', native=node)
    engine.editable.set_element(engine.current_object)
    hook = KeyboardHook(engine)
    hook.is_in_edit_field = True
    hook._process(0x7C, 0, 0, True); hook._process(0x7C, 0, 0x80, False)

    def caret():
        return Atspi.Text.get_caret_offset(text_iface)

    def all_text():
        return Atspi.Text.get_text(text_iface, 0, -1)

    def line_end(pos):
        t = all_text()
        i = t.find('\n', pos)
        return len(t) if i < 0 else i

    def line_start(pos):
        return all_text().rfind('\n', 0, pos) + 1

    VK = {'right': (0xff53, 0x27), 'left': (0xff51, 0x25), 'end': (0xff57, 0x23),
          'home': (0xff50, 0x24), 'down': (0xff54, 0x28)}

    def program(key):
        pos = caret()
        if key == 'right':
            new = pos + 1
        elif key == 'left':
            new = pos - 1
        elif key == 'end':
            new = line_end(pos)
        elif key == 'home':
            new = line_start(pos)
        else:
            col = pos - line_start(pos)
            nxt = line_end(pos) + 1
            new = min(nxt + col, line_end(nxt))
        Atspi.Text.set_caret_offset(text_iface, max(0, new))

    def press(key, want):
        keysym, _vk = VK[key]
        vk, ext = atspi_keys.vk_of(keysym)
        mark = len(said)
        hook._posix_char = atspi_keys.typed_char(keysym)
        hook._process(vk, 0, 0x01 if ext else 0, True)
        program(key)
        hook._process(vk, 0, (0x01 if ext else 0) | 0x80, False)
        time.sleep(0.05)
        while queued:
            queued.pop(0)()
        words = [w.strip() for w in said[mark:]]
        print('%-6s caret=%-3d said %r' % (key, caret(), words))
        if words != want:
            problems.append('%s: wanted %r, said %r' % (key, want, words))

    press('right', ['l'])
    press('right', ['a'])
    press('end', ['Ala ma kota.'])
    press('left', ['kropka'])
    press('right', ['nowa linia'])
    press('down', ['Drugi wiersz tutaj.'])
    press('home', ['Drugi wiersz tutaj.'])
    press('right', ['r'])

    def type_key(keysym, inserted, want, altgr=False):
        vk, _ext = atspi_keys.vk_of(keysym)
        mark = len(said)
        if altgr:
            hook._process(0xA5, 0, 0x01, True)
        hook._posix_char = atspi_keys.typed_char(keysym)
        hook._process(vk, 0, 0, True)
        Atspi.EditableText.insert_text(node.get_editable_text_iface()
                                       if hasattr(node, 'get_editable_text_iface') else node,
                                       caret(), inserted, len(inserted.encode('utf-8')))
        hook._process(vk, 0, 0x80, False)
        if altgr:
            hook._process(0xA5, 0, 0x81, False)
        words = said[mark:]
        print('type %-4r said %r' % (inserted, words))
        if not words or words[-1] != want:
            problems.append('typing %r: wanted %r, said %r' % (inserted, want, words))

    type_key(0x1b1, 'ą', 'ą', altgr=True)     # aogonek
    type_key(0x1bf, 'ż', 'ż', altgr=True)     # zabovedot
    type_key(0x40, '@', 'małpa')
    type_key(0x20ac, '€', 'euro', altgr=True)
    print('the text now:', repr(all_text()[:30]))
    return 0


try:
    code = main()
finally:
    app.kill()
print()
print('PROBLEMS:' if problems else 'ALL GOOD', *problems, sep='\n  ')
sys.exit(1 if problems or code else 0)

# -*- coding: utf-8 -*-
"""Run the REAL Titan Access engine headlessly and drive Windows with keys.

    python tests/check_titan_access_live.py [menu|sysmenu|alttab|columns|vw|palette|settings|checkbox|all]

The suites prove the parts. What proved that menus and the Alt+Tab switcher
were silent - a five-element speech segment unpacked as two, inside the
provider's listener - was this: the engine started with its speech replaced
by a recorder, and a classic menu, the system menu and Alt+Tab driven with
injected keys. Every scenario prints what the reader SAID, marked with the
key that caused it, so a silence is visible as a mark with nothing under
it. Nothing here needs Titan running; NVDA may be running beside it.

Windows only. It really presses keys on this machine: do not type while it
runs. The windows it opens (msinfo32, charmap) are closed at the end.
"""

import ctypes
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')


def _work_on_a_copy_of_the_users_stores():
    """A probe must never change the user's settings.

    A walked-settings scenario flipped "announce block controls" OFF in the
    user's REAL `screenReader.ini` and a scheme scenario left a pause in
    their speech-scheme store - and the next morning the compiled Titan,
    reading that file, said no window, no list and no status-bar item,
    which was reported as a regression. So every probe runs on a COPY:
    the user's `titosoft/Titan` folder is copied to a temporary one and
    APPDATA points there before anything of the reader is imported. Pass
    ``--real`` to run on the real stores, knowingly.
    """
    if '--real' in sys.argv:
        sys.argv.remove('--real')
        return
    import shutil
    import tempfile
    base = os.getenv('APPDATA') or os.path.expanduser('~')
    source = os.path.join(base, 'titosoft', 'Titan')
    target = tempfile.mkdtemp(prefix='titan_access_probe_')
    for name in ('screenreader', 'accessibility', 'logs'):
        there = os.path.join(source, name)
        if os.path.isdir(there):
            shutil.copytree(there, os.path.join(target, 'titosoft', 'Titan', name),
                            ignore=shutil.ignore_patterns('*.log'))
    os.environ['APPDATA'] = target
    print('probing on a copy of the user\'s stores:', target, flush=True)


_work_on_a_copy_of_the_users_stores()
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    sys.stdout.reconfigure(errors='replace')
except Exception:                                    # noqa: BLE001
    pass

user32 = ctypes.windll.user32
T0 = time.time()
said = []


class RecordingSpeech:
    """The speech adapter, replaced: every line and every segment kept."""
    supports_pitch = True

    def __init__(self, settings=None):
        pass

    def speak(self, text, position=0.0, interrupt=True, pitch_offset=0):
        said.append((round(time.time() - T0, 2), 'I' if interrupt else 'q',
                     text))
        print('SAY', said[-1], flush=True)

    speak_async = speak

    def speak_segments(self, segments, gap_ms=0):
        said.append((round(time.time() - T0, 2), 'seg%d' % gap_ms,
                     ' | '.join(str(s[0]) for s in segments)))
        print('SAY', said[-1], flush=True)

    def stop(self):
        pass

    def is_speaking(self):
        return False

    def apply_settings(self):
        print('APPLY_SETTINGS', flush=True)

    def set_rate(self, *a):
        pass

    def set_volume(self, *a):
        pass

    def set_pitch(self, *a):
        pass

    def set_engine(self, *a):
        pass

    def set_voice(self, *a):
        pass

    def get_voices(self):
        return []

    def get_engines(self):
        return []

    def wait_until_done(self, *a, **k):
        return True

    def pending_count(self):
        return 0


KEYEVENTF_KEYUP = 0x2
KEYEVENTF_EXTENDEDKEY = 0x1
VK_MENU, VK_TAB, VK_SPACE, VK_RETURN, VK_ESCAPE = 0x12, 0x09, 0x20, 0x0D, 0x1B
VK_DOWN, VK_RIGHT = 0x28, 0x27
#: The keys that exist twice on a keyboard: the extended flag is what
#: tells the real arrow from NumPad 2 with NumLock off. Injected without
#: it, a Down arrow reached the reader as NumPad 2 - its object-navigation
#: key - and walked into the row's first cell, which read exactly like a
#: bug in Explorer until the probe was suspected instead.
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E}


def key(vk, up=False):
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    user32.keybd_event(vk, 0, flags, 0)


def tap(vk):
    key(vk)
    time.sleep(0.05)
    key(vk, True)


def mark(text):
    said.append((round(time.time() - T0, 2), 'MARK', text))
    print('MARK', text, flush=True)


def plain(engine, name, vk=0, shift=False):
    return engine.on_plain_key(vk, name, False, False, shift)


def start_engine():
    import titan_access.speech_adapter as speech_adapter
    speech_adapter.SpeechAdapter = RecordingSpeech
    from titan_access.engine import TitanAccessEngine
    engine = TitanAccessEngine()
    print('engine started:', engine.start(), flush=True)
    time.sleep(1.5)
    return engine


def open_program(name, wait=3.0):
    process = subprocess.Popen([os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'System32', name)])
    time.sleep(wait)
    return process


def scenario_menu(engine):
    """A classic Win32 menu bar (msinfo32): Alt, Enter, Down, Right, Escape."""
    process = open_program('msinfo32.exe')
    mark('alt (menu bar)'); tap(VK_MENU); time.sleep(1.0)
    mark('enter (open the menu)'); tap(VK_RETURN); time.sleep(1.0)
    mark('down'); tap(VK_DOWN); time.sleep(0.8)
    mark('right (next menu)'); tap(VK_RIGHT); time.sleep(0.8)
    mark('escape'); tap(VK_ESCAPE); time.sleep(0.5); tap(VK_ESCAPE); time.sleep(0.7)
    return process


def scenario_sysmenu(engine, process=None):
    """The window's system menu (Alt+Space), a classic popup menu."""
    process = process or open_program('msinfo32.exe')
    mark('alt+space'); key(VK_MENU); time.sleep(0.05); tap(VK_SPACE)
    key(VK_MENU, True); time.sleep(1.0)
    mark('down'); tap(VK_DOWN); time.sleep(0.8)
    mark('escape'); tap(VK_ESCAPE); time.sleep(0.7)
    return process


def scenario_alttab(engine, process=None):
    """The Alt+Tab switcher: two rows, then Escape."""
    process = process or open_program('msinfo32.exe')
    mark('alt+tab'); key(VK_MENU); time.sleep(0.1); tap(VK_TAB); time.sleep(1.2)
    mark('tab again'); tap(VK_TAB); time.sleep(1.2)
    mark('escape'); tap(VK_ESCAPE); time.sleep(0.2); key(VK_MENU, True); time.sleep(1.0)
    return process


def scenario_columns(engine, process=None):
    """A report-mode list (msinfo32's right pane): a row with its columns."""
    process = process or open_program('msinfo32.exe')
    mark('tab to the list'); tap(VK_TAB); time.sleep(1.0)
    mark('down'); tap(VK_DOWN); time.sleep(1.0)
    mark('down'); tap(VK_DOWN); time.sleep(1.0)
    return process


def scenario_vw(engine, process=None):
    """Insert+NumPad minus: the virtual window, walked two rows down."""
    process = process or open_program('charmap.exe', 2.5)
    mark('insert+numpad minus')
    engine.on_modifier_gesture(0x6D, 'numpadsubtract', False, False, False,
                               with_modifier=True)
    time.sleep(0.8)
    mark('down'); plain(engine, 'down'); time.sleep(0.5)
    mark('down'); plain(engine, 'down'); time.sleep(0.5)
    mark('escape'); plain(engine, 'escape'); time.sleep(0.5)
    return process


def scenario_palette(engine, process=None):
    """Insert+Shift+Space: the command palette."""
    process = process or open_program('charmap.exe', 2.5)
    mark('insert+shift+space')
    engine.on_modifier_gesture(VK_SPACE, 'space', False, False, True,
                               with_modifier=True)
    time.sleep(0.8)
    mark('down'); plain(engine, 'down'); time.sleep(0.4)
    mark('escape'); plain(engine, 'escape'); time.sleep(0.4)
    return process


def scenario_settings(engine, process=None):
    """Insert+Ctrl+G: the reader's settings walked; a switch flipped twice."""
    process = process or open_program('charmap.exe', 2.5)
    mark('insert+ctrl+g')
    engine.on_modifier_gesture(0x47, 'g', True, False, False,
                               with_modifier=True)
    time.sleep(0.8)
    mark('down, down'); plain(engine, 'down'); time.sleep(0.3)
    plain(engine, 'down'); time.sleep(0.3)
    mark('enter (a section)'); plain(engine, 'return'); time.sleep(0.6)
    mark('down'); plain(engine, 'down'); time.sleep(0.4)
    mark('enter (flip)'); plain(engine, 'return'); time.sleep(0.6)
    mark('enter (flip back)'); plain(engine, 'return'); time.sleep(0.6)
    for _step in range(3):
        mark('escape'); plain(engine, 'escape'); time.sleep(0.4)
    return process


def scenario_checkbox(engine, process=None):
    """Tab to charmap's check box; Space twice: checked, then unchecked."""
    process = process or open_program('charmap.exe', 2.5)
    mark('tab to the check box')
    for _step in range(12):
        tap(VK_TAB); time.sleep(0.45)
        current = engine.current_object
        if current is not None and current.role == 'checkbox':
            print('CHECKBOX', current.name, sorted(current.states), flush=True)
            break
    mark('space'); tap(VK_SPACE); time.sleep(0.8)
    mark('space again'); tap(VK_SPACE); time.sleep(0.8)
    return process


def scenario_web(engine, process=None):
    """A web page in a browser, read as a document: the reader's own
    virtual buffer over the browser's UI Automation tree, with NVDA off.
    Down walks the lines, `h` jumps between headings, `k` between links,
    Tab reaches the form."""
    page = os.environ.get('TITAN_WEB_PAGE') or ''
    if not page:
        # The page written beside this check, or one in %TEMP%: an
        # environment variable does not cross from a WSL shell into the
        # Windows Python, so the path is looked for rather than only asked.
        for candidate in (os.path.join(HERE, 'titan_web_test.html'),
                          os.path.join(os.environ.get('TEMP', ''),
                                       'titan_web_test.html')):
            if candidate and os.path.isfile(candidate):
                page = 'file:///' + candidate.replace('\\', '/')
                break
    exe = ''
    for candidate in (r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                      r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                      r'C:\Program Files\Mozilla Firefox\firefox.exe'):
        if os.path.isfile(candidate):
            exe = candidate
            break
    if not exe or not page:
        print('no browser or no TITAN_WEB_PAGE', flush=True)
        return None
    process = subprocess.Popen([exe, '--new-window', page])
    time.sleep(5.0)
    mark('page open (browse mode by itself?)')
    time.sleep(1.0)
    for _ in range(4):
        mark('down'); plain(engine, 'down', 0x28); time.sleep(0.6)
    mark('h (next heading)'); plain(engine, 'h', 0x48); time.sleep(0.7)
    mark('h (next heading)'); plain(engine, 'h', 0x48); time.sleep(0.7)
    mark('k (next link)'); plain(engine, 'k', 0x4B); time.sleep(0.7)
    mark('shift+h (previous heading)'); plain(engine, 'h', 0x48, shift=True); time.sleep(0.7)
    mark('control+home'); engine.on_plain_key(0x24, 'home', True, False, False); time.sleep(0.7)
    return process


def scenario_worker(engine, process=None):
    """The reader's worker thread, pinged across a window being minimised.

    Minimising Titan puts the focus on a WINDOW (the desktop, the next
    program), and a window is a container: its announcement is deferred
    and then posted to the worker - the first thread message the loop
    ever saw in ordinary use, and the one that killed it (`msg.hwnd`,
    a field `MSG` has not got). A TIMEOUT here is the reader dead with
    `running` still True.
    """
    import threading
    process = process or open_program('charmap.exe', 2.5)

    def ping(tag):
        done = threading.Event()
        engine.post_to_worker(done.set)
        ok = done.wait(4.0)
        mark('%s: worker %s' % (tag, 'answered' if ok else 'TIMEOUT'))
        return ok
    ping('before')
    hwnd = user32.GetForegroundWindow()
    mark('minimise the window in front')
    user32.ShowWindow(hwnd, 6)                        # SW_MINIMIZE
    time.sleep(1.5)
    ping('after minimise')
    time.sleep(1.0)
    ping('a second later')
    user32.ShowWindow(hwnd, 9)                        # SW_RESTORE
    time.sleep(1.0)
    ping('after restore')
    return process


PROBE_PAGE = """<!doctype html><html><head><title>Titan Access probe</title></head>
<body><h1>Probe heading</h1><p>Some text about cats and dogs.</p>
<a href="#one">First link</a> <a href="#two">Second link</a>
<h2>A table</h2>
<table><tr><th>Name</th><th>Age</th></tr>
<tr><td>Anna</td><td>31</td></tr><tr><td>Bartek</td><td>42</td></tr></table>
<form><label>Search <input type="text" name="q"></label>
<button type="button">Go</button></form></body></html>"""


def scenario_document(engine, process=None):
    """A web page: the elements list, find, and the table's cells.

    Writes a small page, opens it in a NEW browser window, waits for
    browse mode, then drives the three document commands straight on the
    engine (no keys injected) and closes that window alone - never the
    browser the user may have open beside it.
    """
    import tempfile
    page = os.path.join(tempfile.gettempdir(), 'titan_access_probe.html')
    with open(page, 'w', encoding='utf-8') as handle:
        handle.write(PROBE_PAGE)
    # `start` resolves the browser the way the shell does (App Paths), which
    # a bare `msedge` on PATH does not; a new window, so only that window is
    # closed at the end.
    subprocess.Popen(['cmd', '/c', 'start', '', 'msedge', '--new-window', page],
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for _wait in range(30):
        time.sleep(0.5)
        if engine.browse is not None and engine.browse.is_active:
            break
    time.sleep(1.5)
    browse = engine.browse
    mark('browse active: %s web: %s' % (browse.is_active, browse.is_web))
    if browse.is_active:
        browse._ensure_document()
        time.sleep(1.0)
        mark('nodes: %d' % len(browse._nodes()))
        mark('elements list'); engine.action_elements_list(); time.sleep(0.8)
        plain(engine, 'down'); time.sleep(0.4)
        plain(engine, 'return'); time.sleep(0.6)      # the headings
        plain(engine, 'return'); time.sleep(0.8)      # jump to the first heading
        mark('find "bartek"'); browse._find_query = 'bartek'
        browse.find_next(first=True); time.sleep(0.8)
        mark('table: right'); browse.table_move(0, 1); time.sleep(0.8)
        mark('table: up'); browse.table_move(-1, 0); time.sleep(0.8)
        mark('table: down twice'); browse.table_move(1, 0); time.sleep(0.5)
        browse.table_move(1, 0); time.sleep(0.8)
        mark('table: down at the edge'); browse.table_move(1, 0); time.sleep(0.6)
    sup = getattr(engine, 'supervisor', None)
    mark('supervisor: %s' % (sup.report() if sup else 'none'))
    try:
        from titan_access import log as _log
        mark('log: %s (%d lines)' % (_log.path(), _log.report().get('lines', 0)))
    except Exception as e:                           # noqa: BLE001
        mark('log: %s' % e)
    # Close the probe's window and nothing else.
    _close_windows_titled('Titan Access probe')
    return None


def _close_windows_titled(fragment):
    import ctypes.wintypes as wt
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def each(hwnd, _lp):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if fragment in buf.value and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
        return True
    user32.EnumWindows(each, 0)
    for hwnd in found:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)       # WM_CLOSE


SCENARIOS = {
    'document': scenario_document,
    'worker': scenario_worker,
    'web': scenario_web,
    'menu': scenario_menu, 'sysmenu': scenario_sysmenu,
    'alttab': scenario_alttab, 'columns': scenario_columns,
    'vw': scenario_vw, 'palette': scenario_palette,
    'settings': scenario_settings, 'checkbox': scenario_checkbox,
}


def main(argv):
    wanted = argv[1:] or ['all']
    if 'all' in wanted:
        wanted = list(SCENARIOS)
    engine = start_engine()
    processes = []
    try:
        for name in wanted:
            run = SCENARIOS.get(name)
            if run is None:
                print('no such scenario:', name)
                continue
            print('==== %s' % name, flush=True)
            processes.append(run(engine))
            time.sleep(0.5)
    finally:
        for process in processes:
            try:
                process.terminate()
            except Exception:                        # noqa: BLE001
                pass
        time.sleep(0.3)
        engine.stop()
    print('==== SPOKEN')
    for line in said:
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

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


SCENARIOS = {
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

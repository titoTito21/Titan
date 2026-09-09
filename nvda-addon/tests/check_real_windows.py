# -*- coding: utf-8 -*-
"""Is a real window on this machine a drawn surface? Asked of real windows.

The unit tests ask :func:`surface.looks_drawn` about objects the tests
build, which proves the rule and proves nothing about the machine. This
asks it about every window that is actually open - the terminal, Explorer,
the browser, Titan, NVDA's own dialogs - and fails if any of them is
classified as a window that exposes nothing.

That is the direction the mistake matters in. A drawn window missed costs
a feature; an ordinary window mistaken for one puts a question in front of
somebody about their terminal, which is the report this check exists
because of.

    python nvda-addon/tests/check_real_windows.py

Needs no NVDA. The signals it feeds the classifier - the window class, the
control type and whether the window has any accessible children at all -
are read from Windows through UI Automation, which is where NVDA reads
them too.
"""

import ctypes
import os
import sys
import types
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(HERE), 'addon')
sys.path.insert(0, os.path.join(ADDON, 'globalPlugins'))
if 'globalPluginHandler' not in sys.modules:
    stub = types.ModuleType('globalPluginHandler')

    class _GlobalPlugin:
        def __init__(self):
            pass

        def terminate(self):
            pass
    stub.GlobalPlugin = _GlobalPlugin
    sys.modules['globalPluginHandler'] = stub

from titanEnhancements import surface                            # noqa: E402

user32 = ctypes.windll.user32

#: UI Automation's control types, as the names NVDA uses for the same
#: things. Only the few that matter to the classifier.
_CONTROL_TYPES = {50032: 'WINDOW', 50033: 'PANE', 50026: 'GROUPING',
                  50018: 'MENUBAR', 50021: 'TOOLBAR', 50008: 'LIST',
                  50036: 'DOCUMENT', 50031: 'TITLEBAR'}


class Window:
    """A real window, shaped the way the classifier expects an object."""

    def __init__(self, hwnd, title, window_class, role, children):
        self.windowHandle = hwnd
        self.name = title
        self.windowClassName = window_class
        self.role = types.SimpleNamespace(name=role)
        self.children = children
        self.appModule = types.SimpleNamespace(appName='')


def _uia():
    import comtypes.client
    module = comtypes.client.GetModule('UIAutomationCore.dll')
    return comtypes.client.CreateObject(
        '{ff48dba4-60ef-4201-aa87-54103eef594e}',
        interface=module.IUIAutomation)


def _windows():
    """Every visible top-level window with a title."""
    found = []
    ENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def each(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
                return True
            length = user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
            if length <= 0:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(ctypes.c_void_p(hwnd), title, length + 1)
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(ctypes.c_void_p(hwnd), name, 256)
            found.append((int(hwnd), title.value, name.value))
        except Exception:                            # noqa: BLE001
            pass
        return True
    user32.EnumWindows(ENUM(each), None)
    return found


def look():
    uia = _uia()
    walker = uia.RawViewWalker
    rows = []
    for hwnd, title, window_class in _windows():
        role, children = 'WINDOW', []
        try:
            element = uia.ElementFromHandle(hwnd)
            role = _CONTROL_TYPES.get(element.CurrentControlType, 'PANE')
            child = walker.GetFirstChildElement(element)
            while child is not None and len(children) < 40:
                try:
                    children.append(types.SimpleNamespace(
                        name=child.CurrentName or ''))
                except Exception:                    # noqa: BLE001
                    children.append(types.SimpleNamespace(name=''))
                child = walker.GetNextSiblingElement(child)
        except Exception:                            # noqa: BLE001
            pass
        window = Window(hwnd, title, window_class, role, children)
        rows.append((window, surface.looks_drawn(window)))
    return rows


def _plain(text):
    """A window title this console can print.

    Titles carry anything - a spinner, an emoji, a language this code page
    has never heard of - and a check that falls over printing one has
    failed for a reason that has nothing to do with what it checks.
    """
    try:
        encoding = sys.stdout.encoding or 'ascii'
        return str(text or '').encode(encoding, 'replace').decode(encoding)
    except Exception:                                # noqa: BLE001
        return str(text or '').encode('ascii', 'replace').decode('ascii')


def main():
    rows = look()
    if not rows:
        print('no windows to look at')
        return 1
    drawn = [row for row in rows if row[1]]
    print('%d windows open; %d would be read as a picture\n'
          % (len(rows), len(drawn)))
    print('%-28s %-30s %-8s %s' % ('class', 'title', 'children', 'drawn?'))
    print('-' * 84)
    for window, is_drawn in sorted(rows, key=lambda row: not row[1]):
        print('%-28s %-30s %-8d %s'
              % (_plain(window.windowClassName)[:28],
                 _plain(window.name)[:30],
                 len(window.children), 'YES' if is_drawn else ''))
    # The programs a user is certainly not to be asked about.
    ordinary = ('CASCADIA_HOSTING_WINDOW_CLASS', 'ConsoleWindowClass',
                'CabinetWClass', 'Chrome_WidgetWin_1', 'MozillaWindowClass',
                '#32770', 'ApplicationFrameWindow')
    wrong = [window for window, is_drawn in rows
             if is_drawn and window.windowClassName in ordinary]
    if wrong:
        print('\nWRONG: these have controls and would have been asked about:')
        for window in wrong:
            print('   %s (%s)' % (_plain(window.name),
                                  _plain(window.windowClassName)))
        return 1
    print('\nNo ordinary window was mistaken for a drawn one.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

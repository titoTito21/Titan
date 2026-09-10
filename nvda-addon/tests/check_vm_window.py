# -*- coding: utf-8 -*-
"""Which child of a real virtual machine window would be READ? Asked of it.

The unit tests ask :func:`surface.display_of` about window trees the tests
build, which proves the rule and proved nothing about VMware - where the
guest console is nested five levels down, where the frame carries a
one-pixel auto-hide strip that has no children, and where a SECOND,
parked console sits at (-31797, -31820). Each of those made the reader
pick a window nobody can see, and every one of them looked like success
from the outside: the watch started, read twenty-one times, and said
nothing, because reading a one-pixel window succeeds.

    python nvda-addon/tests/check_vm_window.py

Needs no NVDA and changes nothing. It builds the same shape NVDA's own
``obj.children`` has - a window's direct child windows - out of the live
tree, and runs the real function against it. With no virtual machine open
it says so and passes: this is a check about the machine in front of you.
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

user32 = ctypes.windll.user32
try:
    user32.SetProcessDPIAware()
except Exception:                                    # noqa: BLE001
    pass

ENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

#: The frames worth asking about. Deliberately the FRAME classes, not the
#: guest ones: what this checks is the walk down to the guest.
FRAMES = ('VMUIFrame', 'VirtualBoxVM', 'QWidget')


def _class(handle):
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(ctypes.c_void_p(handle), buffer, 256)
    return str(buffer.value)


def _title(handle):
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(ctypes.c_void_p(handle), buffer, 512)
    return str(buffer.value)


def _location(handle):
    rect = wintypes.RECT()
    user32.GetWindowRect(ctypes.c_void_p(handle), ctypes.byref(rect))
    return (rect.left, rect.top,
            rect.right - rect.left, rect.bottom - rect.top)


def _direct_children(handle):
    """A window's OWN children - which is what NVDA's `children` answers.

    `EnumChildWindows` is recursive, so the parent has to be asked of each
    one; taking its answer whole would hand the walk a flat list and prove
    nothing about the nesting this check exists for.
    """
    found = []

    def each(child, _lparam):
        if user32.GetParent(ctypes.c_void_p(child)) == handle:
            found.append(int(child))
        return True

    user32.EnumChildWindows(ctypes.c_void_p(handle), ENUM(each), None)
    return found


def _build(handle, program, depth=0):
    node = types.SimpleNamespace(
        windowClassName=_class(handle), windowHandle=int(handle),
        location=_location(handle), children=[],
        role=types.SimpleNamespace(name='WINDOW'),
        appModule=types.SimpleNamespace(appName=program))
    if depth < 10:
        node.children = [_build(child, program, depth + 1)
                         for child in _direct_children(handle)]
    return node


def _program_of(handle):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(ctypes.c_void_p(handle),
                                    ctypes.byref(pid))
    handle_process = ctypes.windll.kernel32.OpenProcess(0x0410, False,
                                                        pid.value)
    if not handle_process:
        return ''
    try:
        buffer = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                handle_process, 0, buffer, ctypes.byref(size)):
            return os.path.splitext(os.path.basename(buffer.value))[0].lower()
    finally:
        ctypes.windll.kernel32.CloseHandle(handle_process)
    return ''


def _frames():
    found = []

    def each(handle, _lparam):
        if user32.IsWindowVisible(ctypes.c_void_p(handle)) \
                and _class(handle) in FRAMES:
            found.append(int(handle))
        return True

    user32.EnumWindows(ENUM(each), None)
    return found


def main():
    from titanEnhancements import surface

    windows = [handle for handle in _frames()
               if surface.is_virtual_machine(
                   _build(handle, _program_of(handle), depth=10))]
    if not windows:
        print('No virtual machine window is open, so there is nothing to '
              'ask. Open one and run this again.')
        return 0

    wrong = []
    for handle in windows:
        program = _program_of(handle)
        window = _build(handle, program)
        if not surface._on_the_screen(getattr(window, 'location', None)):
            # Windows parks a minimised window at (-32000, -32000). There
            # is nothing on the screen to read, which is not a fault.
            print('%s %r\n  minimised - nothing to read'
                  % (_class(handle), _title(handle)))
            continue
        chosen = surface.display_of(window)
        where = getattr(chosen, 'location', None) or (0, 0, 0, 0)
        print('%s %r' % (_class(handle), _title(handle)))
        print('  reads: %s %s at (%d, %d) %dx%d'
              % (getattr(chosen, 'windowHandle', 0),
                 getattr(chosen, 'windowClassName', ''),
                 where[0], where[1], where[2], where[3]))
        if getattr(chosen, 'windowHandle', 0) == handle:
            wrong.append('%s: the guest was not found at all - the whole '
                         'window would be read, menu bar and all' % program)
            continue
        if where[2] < surface.SMALLEST_DISPLAY[0] \
                or where[3] < surface.SMALLEST_DISPLAY[1]:
            wrong.append('%s: %dx%d is too small to be a screen'
                         % (program, where[2], where[3]))
        if not surface._on_the_screen(where):
            wrong.append('%s: the window chosen is off the screen - a '
                         'parked console, which reads as nothing for ever'
                         % program)
    if wrong:
        print()
        for one in wrong:
            print('WRONG: %s' % one)
        return 1
    print('\nEvery virtual machine window would be read at its guest.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

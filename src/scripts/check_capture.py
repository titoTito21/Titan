# -*- coding: utf-8 -*-
"""Can AI OCR photograph what is on this screen? Asked of real windows.

`capture.py` has three routes and the third exists for programs the first
two cannot see at all - a game that has taken the display. Which route a
window needs is a property of the machine and of the program, so it cannot
be settled by a unit test: this asks about the windows that are really
open, says which route answered, and fails if a window that is plainly
there comes back as a blank picture.

    python src/scripts/check_capture.py

Takes no pictures of anything but this machine's own screen, sends nothing
anywhere, and needs no AI key: it stops at the picture, which is the half
that was broken.
"""

import ctypes
import os
import sys
from ctypes import wintypes

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', '..')))

user32 = ctypes.windll.user32


def _windows(limit=6):
    found = []
    ENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def each(hwnd, _lparam):
        if len(found) >= limit:
            return False
        try:
            if not user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
                return True
            length = user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
            if length <= 0:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(ctypes.c_void_p(hwnd), title, length + 1)
            rect = wintypes.RECT()
            user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
            if rect.right - rect.left < 200 or rect.bottom - rect.top < 100:
                return True
            found.append((int(hwnd), title.value))
        except Exception:                            # noqa: BLE001
            pass
        return True
    user32.EnumWindows(ENUM(each), None)
    return found


def _plain(text):
    encoding = sys.stdout.encoding or 'ascii'
    return str(text or '').encode(encoding, 'replace').decode(encoding)


def main():
    from src.ai.ocr import capture, duplication
    problems = []

    print('THE COMPOSITOR, which is the only route that sees a game')
    ready, why = duplication.available()
    print('   available: %s%s' % (ready, '' if ready else ' - ' + why))
    if ready:
        rgb, where, size = duplication.grab_elsewhere()
        if rgb is None:
            print('   no frame: %s' % where)
            problems.append('the compositor route produced no frame')
        else:
            flat = float(rgb.std()) < 1.0
            print('   frame %s at %s, mean %.1f, std %.1f%s'
                  % (size, where, rgb.mean(), rgb.std(),
                     '   BLANK' if flat else ''))
            if flat:
                problems.append('the compositor route produced a blank frame')

    print()
    print('REAL WINDOWS, through the whole of capture()')
    for hwnd, title in _windows():
        try:
            shot = capture.capture(scope='window', hwnd=hwnd)
        except Exception as error:                   # noqa: BLE001
            print('   %-34s raised %s' % (_plain(title)[:34], error))
            problems.append('%s raised' % _plain(title)[:34])
            continue
        print('   %-34s %-8s %-11s blank=%s'
              % (_plain(title)[:34], shot.source,
                 '%dx%d' % (shot.width, shot.height)
                 if getattr(shot, 'width', 0) else '?', shot.blank))
        if shot.blank:
            problems.append('%s came back blank' % _plain(title)[:34])

    print()
    print('THE WHOLE SCREEN')
    shot = capture.capture_screen()
    print('   %s blank=%s size=%s' % (shot.source, shot.blank,
                                      shot.screen_size))
    if shot.blank:
        problems.append('the whole screen came back blank')

    print()
    if problems:
        print('PROBLEMS:')
        for one in problems:
            print('   ' + one)
        return 1
    print('Every window that is really there came back as a picture.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

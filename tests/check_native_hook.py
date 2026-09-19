# -*- coding: utf-8 -*-
"""Prove the native keyboard hook survives what unhooks the Python one.

    python tests/check_native_hook.py

Windows only, and it really injects keys on this machine (a few harmless
letters, sent while a fresh Notepad-less console has the foreground - the
keys are SWALLOWED by the hook under test, so nothing is typed anywhere).
Do not type while it runs; it takes about ten seconds.

Three things are measured, each of which the reader's own Python hook
could not promise:

1. a decider that keeps a key: the key is swallowed and counted;
2. a decider that is SLOW (sleeps longer than the deadline): the key goes
   through to the system after the deadline, is counted as late, and the
   hook is STILL installed and still sees the next key - where Windows
   would have unhooked a slow Python callback and the next key would have
   gone past the reader unseen;
3. a window asked whether it answers: the console says yes, an invented
   handle says "not a window".
"""

import ctypes
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)

from titan_access import native_hook                          # noqa: E402

KEYEVENTF_KEYUP = 0x2
VK_F13, VK_F14 = 0x7C, 0x7D     # keys no program on this machine binds


def tap(vk):
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def main():
    if not native_hook.available():
        print('the native hook is not there:', native_hook.why_not())
        return 2
    seen = []
    slow = {'on': False}

    def decider(vk, scan, flags, is_down, extra):
        seen.append((vk, is_down))
        if slow['on'] and vk == VK_F14:
            time.sleep(0.6)             # four times the deadline
        return vk in (VK_F13, VK_F14)   # keep both test keys off the system

    hook = native_hook.NativeHook(decider, timeout_ms=150)
    ok = hook.install()
    print('installed:', ok, native_hook.status())
    if not ok:
        return 1
    failures = []
    try:
        time.sleep(0.3)
        # 1. a kept key
        tap(VK_F13)
        time.sleep(0.3)
        status = native_hook.status()
        print('after a kept key:', status)
        if status['swallowed'] < 2:
            failures.append('F13 was not swallowed')
        # 2. a slow decision
        slow['on'] = True
        tap(VK_F14)
        time.sleep(1.5)
        status = native_hook.status()
        print('after a slow decision:', status)
        if status['late'] < 1:
            failures.append('the slow decision was not counted as late')
        if not status['installed']:
            failures.append('the hook is gone after a slow decision')
        # the next key is still seen
        slow['on'] = False
        before = status['events']
        tap(VK_F13)
        time.sleep(0.3)
        status = native_hook.status()
        print('after the next key:', status)
        if status['events'] <= before:
            failures.append('the hook did not see the key after the slow one')
        if status['longestWaitMs'] < 140:
            failures.append('the deadline was not what held the hook')
        # 3. a window asked with a deadline
        console = ctypes.windll.kernel32.GetConsoleWindow()
        answers = native_hook.window_responding(console, 300)
        nowhere = native_hook.window_responding(0x12345, 300)
        print('console answers:', answers, '; an invented handle:', nowhere)
        if console and answers != 1:
            failures.append('the console did not answer')
        if nowhere != -1:
            failures.append('an invented handle was not refused')
    finally:
        hook.uninstall()
        print('uninstalled:', native_hook.status())
    if failures:
        print('FAILED:', '; '.join(failures))
        return 1
    print('OK: kept, late-but-alive, and windows asked with a deadline')
    return 0


if __name__ == '__main__':
    sys.exit(main())

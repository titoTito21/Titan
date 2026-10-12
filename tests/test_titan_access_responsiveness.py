# -*- coding: utf-8 -*-
"""What keeps the reader's own thread free: deferred work on one scheduler
thread instead of a thread per event, no UI Automation call into a window
that has stopped answering, an add-on's repeated complaint written once a
minute, and a key whose decision was slow written down.

Run directly: python tests/test_titan_access_responsiveness.py. Nothing is
spoken, shown or pressed.
"""

import ast
import os
import sys
import tempfile
import threading
import time
import unittest

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='titan_ta_resp_')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(ROOT, 'data', 'components', 'titan access')
sys.path.insert(0, ROOT)
sys.path.insert(0, COMPONENT)

from titan_access import later  # noqa: E402

PACKAGE = os.path.join(COMPONENT, 'titan_access')


class DeferredWorkMakesNoThreads(unittest.TestCase):

    def test_jobs_run_in_order_of_time(self):
        seen = []
        done = threading.Event()
        later.call_later(0.05, lambda: seen.append('second'))
        later.call_later(0.0, lambda: seen.append('first'))
        later.call_later(0.08, done.set)
        self.assertTrue(done.wait(5))
        self.assertEqual(seen, ['first', 'second'])

    def test_a_hundred_jobs_are_one_thread(self):
        done = threading.Event()
        count = []
        for _ in range(100):
            later.call_later(0.01, lambda: count.append(1))
        later.call_later(0.05, done.set)
        ours = [one for one in threading.enumerate()
                if one.name == 'TitanAccessLater']
        self.assertEqual(len(ours), 1)
        self.assertTrue(done.wait(5))
        self.assertEqual(len(count), 100)

    def test_a_failing_job_does_not_stop_the_scheduler(self):
        done = threading.Event()
        later.call_later(0.0, lambda: 1 / 0)
        later.call_later(0.01, done.set)
        self.assertTrue(done.wait(5))

    def test_the_focus_path_starts_no_timer_threads(self):
        """`threading.Timer` on the reader's hot paths was measured holding
        the worker in Thread.start() for over four seconds."""
        for name in ('engine.py', 'editable_text.py', 'menu_tracker.py'):
            with open(os.path.join(PACKAGE, name), encoding='utf-8') as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == 'Timer' \
                        and getattr(node.value, 'id', '') == 'threading':
                    self.fail('%s:%d starts a threading.Timer'
                              % (name, node.lineno))


class AWindowThatDoesNotAnswerIsNotAsked(unittest.TestCase):

    def test_cannot_tell_means_go_ahead(self):
        from titan_access import native_hook
        self.assertTrue(native_hook.window_answers(0))
        keep = native_hook.window_responding, native_hook._python_responding
        try:
            native_hook.window_responding = lambda h, t=300: None
            native_hook._python_responding = lambda h, t: None
            self.assertTrue(native_hook.window_answers(1234))
            native_hook._python_responding = lambda h, t: 0
            if native_hook._IS_WINDOWS:
                self.assertFalse(native_hook.window_answers(1234))
            native_hook.window_responding = lambda h, t=300: 1
            self.assertTrue(native_hook.window_answers(1234))
        finally:
            native_hook.window_responding, native_hook._python_responding = \
                keep

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows only')
    def test_a_real_desktop_answers(self):
        import ctypes
        from titan_access import native_hook
        desktop = ctypes.windll.user32.GetDesktopWindow()
        self.assertEqual(native_hook._python_responding(desktop, 200), 1)
        self.assertEqual(native_hook._python_responding(0x7FFFFFF0, 200), -1)

    def test_the_focus_path_asks_first(self):
        for name in ('uia_focus.py', 'context_presenter.py'):
            with open(os.path.join(PACKAGE, name), encoding='utf-8') as f:
                text = f.read()
            at = text.index('ControlFromHandle(hwnd)')
            self.assertIn('window_answers(hwnd)', text[max(0, at - 400):at],
                          name)


class AnAddOnsRepeatedComplaintIsWrittenOnce(unittest.TestCase):

    def setUp(self):
        from titan_access.nvda_host.shims import logHandler
        self.handler = logHandler
        self.handler._seen.clear()
        self.lines = []
        import titan_access.log as ta_log
        self._keep = ta_log.log
        ta_log.log = self.lines.append

    def tearDown(self):
        import titan_access.log as ta_log
        ta_log.log = self._keep

    def _fail(self, name):
        try:
            open('\\\\.\\pipe\\' + name + 'out', 'rb', 0)
        except OSError:
            self.handler.log.exception('Elten pipe')

    def test_the_same_failure_with_a_new_name_is_one_line(self):
        for n in range(20):
            self._fail('elten%dzz' % n)
        self.assertEqual(len(self.lines), 1)
        self.assertIn('Elten pipe', self.lines[0])

    def test_the_count_is_said_when_the_minute_is_up(self):
        for n in range(5):
            self._fail('elten%dzz' % n)
        first, _dropped = self.handler._seen[next(iter(self.handler._seen))]
        key = next(iter(self.handler._seen))
        self.handler._seen[key] = (first - 61, 4)
        self._fail('elten99zz')
        self.assertEqual(len(self.lines), 2)
        self.assertIn('4 times more', self.lines[1])

    def test_different_messages_are_all_written(self):
        self.handler.log.info('one')
        self.handler.log.info('two')
        self.handler.log.info('one')
        self.assertEqual(len(self.lines), 2)


class ASlowKeyIsWrittenDown(unittest.TestCase):

    def test_slow_decisions_are_kept_and_logged(self):
        from titan_access import keyboard_hook
        hook = keyboard_hook.KeyboardHook.__new__(keyboard_hook.KeyboardHook)
        lines = []
        keep = keyboard_hook.log
        keyboard_hook.log = lines.append
        try:
            hook._note_slow(0x28, True, 0.01)
            self.assertEqual(hook.slow_keys(), [])
            hook._note_slow(0x28, True, 0.25)
            hook._note_slow(0x26, False, 0.4)
            self.assertEqual(hook.slow_keys()[0], (400, 0x26, False))
            self.assertEqual(len(lines), 1)
            self.assertIn('0x28', lines[0])
        finally:
            keyboard_hook.log = keep


if __name__ == '__main__':
    unittest.main()

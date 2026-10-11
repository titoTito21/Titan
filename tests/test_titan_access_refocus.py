# -*- coding: utf-8 -*-
"""A control focused again by nobody is not read again.

Reported as: the Windows taskbar reads its buttons twice - once, and a
second later again. The taskbar re-focuses the button when its thumbnail
comes up, through UI Automation or as a late MSAA event; the engine's
duplicate window was 0.35 s and the provider's MSAA one 0.6 s, so the
second one passed both. Now: the same control again, with no input from
the user since it was read, is not news (up to 10 s); an MSAA focus up to
3 s after a UIA one, with no input between, is that UIA focus arriving
late. The user's input is asked of Windows (`user_input`); here it is a
stand-in. Run directly.
"""
import os
import sys
import tempfile
import time
import unittest

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='ta_refocus_')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'titan access'))

from titan_access import user_input, provider_manager   # noqa: E402
from titan_access.engine import TitanAccessEngine       # noqa: E402
from titan_access.contracts import AccessibleObject     # noqa: E402


def _button(name='Firefox', bounds=(10, 1000, 60, 1040)):
    obj = AccessibleObject(provider='uia')
    obj.role, obj.name, obj.bounds, obj.automation_id = 'button', name, bounds, ''
    return obj


class _Input(object):
    def __init__(self):
        self.when = None

    def __call__(self):
        return self.when


class ActedSince(unittest.TestCase):

    def test_the_keystroke_that_caused_it_is_not_a_new_one(self):
        self.assertFalse(user_input.acted_since(100.0, last=lambda: 100.1))
        self.assertTrue(user_input.acted_since(100.0, last=lambda: 101.0))
        self.assertTrue(user_input.acted_since(100.0, last=lambda: None))


class TheEngineDoesNotReadAnUnpromptedRefocus(unittest.TestCase):

    def setUp(self):
        self.engine = object.__new__(TitanAccessEngine)
        self.engine._last_focus_key = None
        self.engine._last_focus_time = 0.0
        self.engine._announce_token = 0
        self.said = []
        self.engine.announce_object = lambda obj: self.said.append(obj.name)
        self.input = _Input()
        self.saved = user_input.last_input_time
        user_input.last_input_time = self.input

    def tearDown(self):
        user_input.last_input_time = self.saved

    def _focus(self, obj, after):
        self.engine._last_focus_time -= after   # as if `after` s had passed
        if self.input.when is not None:
            self.input.when -= after
        self.engine._announce_focus(obj)

    def test_the_taskbar_button_a_second_later_is_read_once(self):
        self.input.when = time.time() - 0.05     # the Tab that focused it
        self.engine._announce_focus(_button())
        self._focus(_button(), after=1.0)
        self.assertEqual(self.said, ['Firefox'])

    def test_after_a_key_it_is_read_again(self):
        self.input.when = time.time() - 0.05
        self.engine._announce_focus(_button())
        self.input.when = time.time() + 5        # pressed something since
        self._focus(_button(), after=1.0)
        self.assertEqual(self.said, ['Firefox', 'Firefox'])

    def test_another_control_in_between_is_read(self):
        self.input.when = time.time() - 0.05
        self.engine._announce_focus(_button())
        self._focus(_button('Explorer', (70, 1000, 120, 1040)), after=1.0)
        self._focus(_button(), after=1.0)
        self.assertEqual(self.said, ['Firefox', 'Explorer', 'Firefox'])

    def test_long_after_it_is_read_again(self):
        self.input.when = time.time() - 0.05
        self.engine._announce_focus(_button())
        self._focus(_button(), after=11.0)
        self.assertEqual(len(self.said), 2)


class AnMsaaFocusAfterUiaIsTheSameFocusLate(unittest.TestCase):

    def setUp(self):
        self.pm = object.__new__(provider_manager.ProviderManager)
        import threading
        self.pm._lock = threading.RLock()
        self.pm._last_uia_time = 0.0
        self.pm._last_key = None
        self.pm._last_time = 0.0
        self.said = []
        self.pm._listeners = [lambda obj: self.said.append(obj.name)]
        self.input = _Input()
        self.saved = (user_input.last_input_time, provider_manager._MSAA_DEBOUNCE)
        user_input.last_input_time = self.input
        provider_manager._MSAA_DEBOUNCE = 0.0
        self.threads = []
        real = provider_manager.threading.Thread

        def run_now(target, daemon=True):
            class _T(object):
                def start(self_inner):
                    target()
            return _T()
        provider_manager.threading.Thread = run_now
        self.real_thread = real

    def tearDown(self):
        user_input.last_input_time, provider_manager._MSAA_DEBOUNCE = self.saved
        provider_manager.threading.Thread = self.real_thread

    def test_a_late_msaa_duplicate_with_another_name_is_not_read(self):
        self.input.when = time.time() - 0.05
        self.pm._on_uia(_button())
        self.pm._last_uia_time -= 1.0
        self.input.when -= 1.0
        msaa = _button('Firefox - 1 running window', (11, 1001, 59, 1039))
        msaa.provider = 'msaa'
        self.pm._on_msaa(msaa)
        self.assertEqual(self.said, ['Firefox'])

    def test_an_msaa_window_the_user_moved_to_is_read(self):
        self.input.when = time.time() - 0.05
        self.pm._on_uia(_button())
        self.pm._last_uia_time -= 1.0
        self.input.when = time.time() + 5
        legacy = _button('OK', (0, 0, 50, 20))
        legacy.provider = 'msaa'
        self.pm._on_msaa(legacy)
        self.assertEqual(self.said, ['Firefox', 'OK'])


if __name__ == '__main__':
    unittest.main()

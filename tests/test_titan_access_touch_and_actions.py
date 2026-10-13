# -*- coding: utf-8 -*-
"""The touchpad and Titan's actions as Titan Access's own, not NVDA's.

The pad's contacts go through NVDA's own tracker, ported
(`titan_access/touch_tracker.py`), and come out as the gestures NVDA makes;
outside a walked list they mean what they mean in NVDA's object mode. And
Titan's actions are asked of Titan, which Titan Access is inside.

Run directly: python tests/test_titan_access_touch_and_actions.py.
Nothing is spoken, shown, pressed or clicked; the pad is not read.
"""

import os
import sys
import tempfile
import threading
import time
import types
import unittest

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='titan_ta_touch_')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(ROOT, 'data', 'components', 'titan access')
sys.path.insert(0, ROOT)
sys.path.insert(0, COMPONENT)

from titan_access import touch_tracker                    # noqa: E402
from titan_access.portable import touchRecognizer, trackpad  # noqa: E402


class _Fingers(unittest.TestCase):
    """Contacts fed the way the pad sends them; gestures collected."""

    def setUp(self):
        self.heard = []
        self.kept = (touchRecognizer.listener, touchRecognizer.manager_factory)
        touchRecognizer.forget()
        touchRecognizer.listener = lambda action, x, y: self.heard.append(
            (action, x, y))
        touchRecognizer.manager_factory = touch_tracker.TrackerManager

    def tearDown(self):
        touchRecognizer.listener, touchRecognizer.manager_factory = self.kept
        touchRecognizer.forget()

    def _stroke(self, fingers, path, seconds):
        """Every finger along ``path`` (a list of (dx, dy) from its start)
        over ``seconds``, then lifted - lifted by NOT being in a report, as
        the pad does it."""
        steps = len(path)
        for step, (dx, dy) in enumerate(path):
            trackpad.feed([(f, 500 + 120 * f + dx, 400 + dy, True)
                           for f in range(fingers)])
            time.sleep(seconds / max(1, steps))
        trackpad.feed([])

    def _settled(self, wanted=None, seconds=2.0):
        end = time.time() + seconds
        while time.time() < end:
            names = [one[0] for one in self.heard]
            if wanted is not None and wanted in names:
                return names
            time.sleep(0.05)
        return [one[0] for one in self.heard]


class NvdasTrackerMakesTheGestures(_Fingers):

    def test_a_tap(self):
        self._stroke(1, [(0, 0), (1, 0)], 0.05)
        self.assertIn('tap', self._settled('tap'))

    def test_a_double_tap_is_one_gesture(self):
        self._stroke(1, [(0, 0), (1, 1)], 0.04)
        time.sleep(0.05)
        self._stroke(1, [(0, 0), (0, 1)], 0.04)
        names = self._settled('double_tap')
        self.assertIn('double_tap', names)
        self.assertNotIn('tap', names)

    def test_a_flick_by_its_velocity(self):
        self._stroke(1, [(i * 30, 0) for i in range(6)], 0.12)
        self.assertIn('flickright', self._settled('flickright'))

    def test_two_fingers_flicking_up(self):
        self._stroke(2, [(0, -i * 30) for i in range(6)], 0.12)
        self.assertIn('2finger_flickup', self._settled('2finger_flickup'))

    def test_a_finger_left_down_hovers(self):
        for i in range(12):
            trackpad.feed([(0, 300 + i, 300, True)])
            time.sleep(0.05)
        names = self._settled('hover', 1.0)
        trackpad.feed([])
        self.assertIn('hoverdown', names)
        self.assertIn('hover', names)
        self.assertIn('hoverup', self._settled('hoverup', 1.0))

    def test_the_gestures_are_named_as_nvda_names_them(self):
        tracker = touch_tracker.MultiTouchTracker(
            touch_tracker.TouchAction.TAP, 1, 2, 0.0, 0.1, numFingers=3,
            actionCount=2)
        self.assertEqual(touchRecognizer.gesture_name(tracker),
                         '3finger_double_tap')


class ThePadNeedsNoNvdaHere(unittest.TestCase):

    def test_available_asks_only_for_windows_and_a_receiver(self):
        from titan_access.portable import compat
        self.assertIsNone(compat.inputCore)          # this is not NVDA
        keep = (touchRecognizer.listener, touchRecognizer.manager_factory)
        try:
            touchRecognizer.listener = lambda *a: None
            touchRecognizer.manager_factory = touch_tracker.TrackerManager
            ok, why = trackpad.available()
            if sys.platform.startswith('win'):
                self.assertTrue(ok, why)
            self.assertNotIn('NVDA', why)
            self.assertIsNone(trackpad._tracker_manager())
        finally:
            touchRecognizer.listener, touchRecognizer.manager_factory = keep

    def test_the_engine_gives_the_tracker(self):
        with open(os.path.join(COMPONENT, 'titan_access', 'engine.py'),
                  encoding='utf-8') as f:
            source = f.read()
        self.assertIn('touchRecognizer.manager_factory = '
                      'touch_tracker.TrackerManager', source)


class TheGesturesMeanWhatTheyMeanInNvda(unittest.TestCase):

    def _engine(self):
        from titan_access import engine as eng
        e = eng.TitanAccessEngine.__new__(eng.TitanAccessEngine)
        self.done = []
        e._object_nav = lambda d: self.done.append(('nav', d))
        e.action_stop_speaking = lambda *a: self.done.append(('stop',))
        e.action_say_all = lambda *a: self.done.append(('sayall',))
        e._object_at_point = lambda x, y: types.SimpleNamespace(
            role='button', name='Zapisz', bounds=(0, 0, 1, 1))
        e.announce_object = lambda obj, **k: self.done.append(
            ('read', obj.name))
        e._say = lambda *a: None
        from titan_access.portable import touchWalk
        self.keep = touchWalk.handle
        touchWalk.handle = lambda action, x, y: (False, '')
        return e

    def tearDown(self):
        from titan_access.portable import touchWalk
        touchWalk.handle = self.keep

    def test_each_gesture(self):
        e = self._engine()
        for action in ('flickright', 'flickleft', 'flickup', 'flickdown',
                       '2finger_tap', '2finger_flickdown', 'tap',
                       'double_tap'):
            e._on_touch(action, 10, 10)
        self.assertEqual(self.done, [
            ('nav', 'next'), ('nav', 'previous'), ('nav', 'parent'),
            ('nav', 'child'), ('stop',), ('sayall',), ('read', 'Zapisz'),
            ('nav', 'activate')])


class TitansActionsAreAskedOfTitan(unittest.TestCase):

    def setUp(self):
        from titan_access.portable import gestures, commands, palette
        self.gestures, self.commands, self.palette = gestures, commands, palette
        self.shown = []
        self.kept = (palette.show, gestures.LINK)
        palette.show = lambda rows, title, **k: (
            self.shown.append((title, rows)) or (True, title))
        addons = {'addons': [{'id': 'tnotes', 'label': 'Notatki',
                              'actions': ['create_note', 'list_notes']}]}
        described = {'actions': [{'name': 'create_note',
                                  'summary': 'Write a new note'}]}
        gestures.LINK = types.SimpleNamespace(
            bridge=lambda call, **k: (True, addons if call == 'addons.list'
                                      else described if call ==
                                      'addons.actions' else {}),
            connected=lambda: True)

    def tearDown(self):
        self.palette.show, self.gestures.LINK = self.kept

    def test_the_list_is_fresh_from_titan(self):
        from titan_access.portable import link
        keep = link.LINK.bridge
        link.LINK.bridge = self.gestures.LINK.bridge
        try:
            self.commands.titan_actions()
            title, rows = self.shown[-1]
            self.assertIn('Notatki (2)', [row['label'] for row in rows])
            rows[0]['run']()
            title, actions = self.shown[-1]
            self.assertEqual(title, 'Notatki')
            self.assertTrue(any('Write a new note' in row['label']
                                for row in actions), actions)
        finally:
            link.LINK.bridge = keep

    def test_what_can_titan_do_opens_it_here(self):
        keep = (self.commands.LINK, self.commands.titan_actions)
        opened = []
        self.commands.LINK = types.SimpleNamespace(connected=lambda: True)
        self.commands.titan_actions = lambda: opened.append(True)
        said = []
        keep_report = self.commands.dialogs.report
        self.commands.dialogs.report = lambda t, *a, **k: said.append(t)
        try:
            self.commands.refresh_actions(None)
        finally:
            self.commands.LINK, self.commands.titan_actions = keep
            self.commands.dialogs.report = keep_report
        self.assertEqual(opened, [True])
        self.assertFalse(any('NVDA' in str(one) for one in said), said)



class TheGesturesThatMeanTheSameEverywhere(_Fingers):

    def _taps(self, fingers, times):
        for _ in range(times):
            self._stroke(fingers, [(0, 0), (1, 0)], 0.04)
            time.sleep(0.05)

    def test_the_tracker_makes_them(self):
        self._taps(2, 2)
        self.assertIn('2finger_double_tap', self._settled('2finger_double_tap'))
        self.heard.clear()
        self._taps(1, 3)
        self.assertIn('triple_tap', self._settled('triple_tap'))
        self.heard.clear()
        self._taps(2, 3)
        self.assertIn('2finger_triple_tap', self._settled('2finger_triple_tap'))

    def test_each_runs_its_command_before_any_list(self):
        from titan_access import engine as eng
        e = eng.TitanAccessEngine.__new__(eng.TitanAccessEngine)
        ran = []
        e._palette_run = lambda name: ran.append(name) or (True, '')
        for action in ('2finger_double_tap', 'triple_tap',
                       '2finger_triple_tap'):
            e._on_touch(action, 10, 10)
        self.assertEqual(ran, ['virtual_window', 'titan_window',
                               'ocr_review'])


class ATapClicksOnceADoubleTapTwice(unittest.TestCase):

    def setUp(self):
        from titan_access.portable import icons, touchWalk
        self.touchWalk = touchWalk
        self.kept = [(icons, 'play', icons.play)]
        icons.play = lambda *a, **k: True

    def tearDown(self):
        for module, name, value in self.kept:
            setattr(module, name, value)

    def _only(self, name):
        keep = self.touchWalk.walker
        self.kept.append((self.touchWalk, 'walker', keep))
        self.touchWalk.walker = lambda: name

    def _swap(self, module, name, value):
        self.kept.append((module, name, getattr(module, name)))
        setattr(module, name, value)

    def test_the_screen_review(self):
        from titan_access.portable import ocrReview
        clicks = []
        self._swap(ocrReview, 'click', lambda double=False: clicks.append(
            double) or (True, ''))
        self._only('ocrReview')
        self.touchWalk.handle('tap', 1, 1)
        self.touchWalk.handle('double_tap', 1, 1)
        self.assertEqual(clicks, [False, True])

    def test_the_virtual_window(self):
        from titan_access.portable import virtualWindow
        clicks = []
        self._swap(virtualWindow, 'here', lambda: {'name': 'Zapisz'})
        self._swap(virtualWindow, 'click_here',
                   lambda double=False, sound=True: clicks.append(double)
                   or (True, ''))
        self._only('virtualWindow')
        self.touchWalk.handle('tap', 1, 1)
        self.touchWalk.handle('double_tap', 1, 1)
        self.assertEqual(clicks, [False, True])

    def test_a_reading_line_on_a_page_and_an_ordinary_row(self):
        from titan_access.portable import palette, smart
        done = []
        line = smart.twice('k', lambda: done.append('once') or (True, ''),
                           lambda: done.append('twice') or (True, ''),
                           report=None)
        command = lambda: done.append('command') or (True, '')  # noqa: E731
        self._swap(palette, 'here', lambda: {'label': 'x', 'run': line})
        self._only('palette')
        self.touchWalk.handle('tap', 1, 1)
        self.touchWalk.handle('double_tap', 1, 1)
        self._swap(palette, 'here', lambda: {'label': 'y', 'run': command})
        self.touchWalk.handle('double_tap', 1, 1)
        self.assertEqual(done, ['once', 'twice', 'command'])

    def test_the_ocr_cursor(self):
        from titan_access.portable import smart
        pressed = []
        self._swap(smart, 'here', lambda: {'control': {'name': 'OK'}})
        self._swap(smart, '_press_one', lambda control, double: pressed.append(
            double) or (True, ''))
        self._only('smart')
        self.touchWalk.handle('tap', 1, 1)
        self.touchWalk.handle('double_tap', 1, 1)
        self.assertEqual(pressed, [False, True])

    def test_a_finger_finds_a_control_of_the_ocr_cursor(self):
        from titan_access.portable import smart
        said = []
        self._swap(smart, 'say', lambda moved: said.append(
            moved['control']['name']) or True)
        with smart._LOCK:
            keep = dict(smart._state)
            smart._state.update({'controls': [
                {'name': 'A', 'rect': (0, 0, 10, 10)},
                {'name': 'B', 'rect': (20, 0, 10, 10)}], 'at': -1})
        try:
            smart._explored['at'] = None
            smart.explore(25, 5)
            smart.explore(26, 6)                      # same control: quiet
            self.assertEqual(said, ['B'])
        finally:
            with smart._LOCK:
                smart._state.clear()
                smart._state.update(keep)


if __name__ == '__main__':
    unittest.main()

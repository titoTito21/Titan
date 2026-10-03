# -*- coding: utf-8 -*-
"""The reader watched, logged, and its document walked.

The supervisor pings the worker and restarts a dead or silent one; the
log writes where a compiled Titan can be read; the elements list, find and
table navigation work on the buffer in hand; the selection is reported as
it changes. Nothing here starts the real engine, speaks or opens a window.

Run directly: ``python tests/test_titan_access_stability.py``.
"""

import io
import os
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)


class _Engine:
    """The little of an engine the supervisor touches."""

    def __init__(self, answers=True, alive=True):
        self.running = True
        self.answers = answers
        self._bg_alive = True
        self._bg_thread = threading.Thread(target=lambda: None)
        self._bg_thread.start()
        self._bg_thread.join()
        self._thread = threading.Thread(target=lambda: time.sleep(0.5)) if alive else None
        if alive:
            self._thread.start()
        self.keyboard = None
        self.restarted_bg = 0

    def post_to_worker(self, fn):
        if self.answers:
            fn()

    def _start_bg_worker(self):
        self.restarted_bg += 1
        self._bg_alive = True
        self._bg_thread = threading.Thread(target=lambda: time.sleep(0.5))
        self._bg_thread.start()


class TheSupervisor(unittest.TestCase):

    def setUp(self):
        from titan_access import log
        self.log = log
        self._old_path = log._state['path']
        log._state['path'] = os.path.join(tempfile.mkdtemp(), 'titan_access.log')

    def tearDown(self):
        self.log._state['path'] = self._old_path

    def _supervisor(self, engine, **kw):
        from titan_access.supervisor import Supervisor
        restarts = []
        sup = Supervisor(engine, every=0.05, patience=0.1, silent_limit=2,
                         restart=lambda why: restarts.append(why), **kw)
        return sup, restarts

    def test_an_answering_worker_is_left_alone(self):
        engine = _Engine()
        sup, restarts = self._supervisor(engine)
        self.assertEqual(sup.check_once(), 'ok')
        self.assertEqual(restarts, [])
        self.assertEqual(sup.counts['answered'], 1)

    @unittest.skipUnless(sys.platform.startswith('win'), 'restarts are Windows')
    def test_a_silent_worker_is_restarted_after_the_limit(self):
        engine = _Engine(answers=False)
        sup, restarts = self._supervisor(engine)
        self.assertEqual(sup.check_once(), 'silent')
        self.assertEqual(restarts, [])
        self.assertEqual(sup.check_once(), 'restarted')
        self.assertEqual(restarts, ['silent'])
        self.assertIn('did not answer', io.open(self.log.path(), encoding='utf-8').read())

    @unittest.skipUnless(sys.platform.startswith('win'), 'restarts are Windows')
    def test_a_dead_worker_is_restarted_at_once(self):
        engine = _Engine(alive=True)
        engine._thread.join()
        sup, restarts = self._supervisor(engine)
        self.assertEqual(sup.check_once(), 'restarted')
        self.assertEqual(restarts, ['dead'])

    def test_a_dead_background_worker_is_started_again(self):
        engine = _Engine()
        sup, _restarts = self._supervisor(engine)
        sup.check_once()
        self.assertEqual(engine.restarted_bg, 1)

    def test_a_stopped_engine_is_not_pinged(self):
        engine = _Engine()
        engine.running = False
        sup, _r = self._supervisor(engine)
        self.assertEqual(sup.check_once(), 'stopped')
        self.assertEqual(sup.counts['pings'], 0)

    def test_the_engine_starts_and_stops_one(self):
        source = io.open(os.path.join(COMPONENT, 'titan_access', 'engine.py'),
                         encoding='utf-8').read()
        self.assertIn('self._start_supervisor()', source)
        self.assertIn('self.supervisor.stop()', source)
        self.assertEqual(source.count('print(f"[TitanAccess]'), 0)


class TheLog(unittest.TestCase):

    def test_it_writes_stamped_lines_and_rotates(self):
        from titan_access import log
        old = log._state['path']
        folder = tempfile.mkdtemp()
        log._state['path'] = os.path.join(folder, 'titan_access.log')
        try:
            log.log('hello %s', 'world')
            text = io.open(log.path(), encoding='utf-8').read()
            self.assertIn('hello world', text)
            self.assertRegex(text, r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \[')
            with open(log.path(), 'ab') as handle:
                handle.write(b'x' * (log.MAX_BYTES + 10))
            log.log('after')
            self.assertTrue(os.path.exists(log.path() + '.1'))
            self.assertIn('after', io.open(log.path(), encoding='utf-8').read())
            self.assertIn('thread', log.stacks())
        finally:
            log._state['path'] = old


class TheDocumentIsWalkedFoundAndTabled(unittest.TestCase):

    def setUp(self):
        from titan_access.browse_mode import BrowseModeHandler
        from titan_access.virtual_buffer import VNode, VirtualDocument
        self.nodes = [
            VNode(name='Welcome', role='heading', level=1),
            VNode(name='Home', role='link'),
            VNode(name='Some text about cats', role='text'),
            VNode(name='Search', role='edit'),
            VNode(name='About cats', role='link'),
        ]
        self.h = BrowseModeHandler.__new__(BrowseModeHandler)
        self.h._lock = threading.RLock()
        self.h._doc = VirtualDocument(nodes=self.nodes, source='uia')
        self.h._index = 0
        self.h._char_pos = 0
        self.h._scan = False
        self.h.engine = type('E', (), {})()
        self.h.engine.said = []
        self.h.engine.speak = lambda text, *a, **k: self.h.engine.said.append(str(text))
        self.h.engine.play = lambda *a, **k: None
        self.h._ensure_document = lambda *a, **k: True
        self.h._nodes = lambda: self.nodes
        self.h._node_at = lambda i: self.nodes[i] if 0 <= i < len(self.nodes) else None
        self.h._dispatch = lambda fn: fn()
        self.announced = []
        self.h._announce_node = lambda node, *a, **k: self.announced.append(node.name)
        from titan_access.portable import palette
        self._old_show = palette.show
        self.shown = []
        palette.show = lambda rows, title, back=None, kind='', at=0: (
            self.shown.append((title, rows)) or (True, ''))
        self._old_stop = palette.stop
        palette.stop = lambda: None

    def tearDown(self):
        from titan_access.portable import palette
        palette.show = self._old_show
        palette.stop = self._old_stop

    def test_the_elements_list_counts_each_kind_and_jumps(self):
        ok, _said = self.h.elements_list()
        self.assertTrue(ok)
        title, rows = self.shown[-1]
        labels = [row['label'] for row in rows]
        self.assertTrue(any('(2)' in one for one in labels), labels)   # two links
        self.assertTrue(any('(1)' in one for one in labels), labels)   # one heading
        rows[0]['run']()                                   # the links
        _title, link_rows = self.shown[-1]
        self.assertEqual([r['label'] for r in link_rows], ['Home', 'About cats'])
        link_rows[1]['run']()
        self.assertEqual(self.h._index, 4)
        self.assertEqual(self.announced, ['About cats'])

    def test_find_goes_forward_then_back_and_says_when_nothing(self):
        self.h._find_query = 'cats'
        self.assertTrue(self.h.find_next())
        self.assertEqual(self.h._index, 2)
        self.assertTrue(self.h.find_next())
        self.assertEqual(self.h._index, 4)
        self.assertFalse(self.h.find_next())
        self.assertTrue(any('cats' in s for s in self.h.engine.said))
        self.assertTrue(self.h.find_next(backward=True))
        self.assertEqual(self.h._index, 2)
        self.h._find_query = ''
        self.assertFalse(self.h.find_next())

    def test_outside_a_table_the_arrows_say_so(self):
        self.assertFalse(self.h.table_move(1, 0))
        self.assertTrue(self.h.engine.said)

    def test_a_cell_is_matched_by_its_rectangle_when_the_buffer_is_cached(self):
        from titan_access.virtual_buffer import VNode

        class Rect:
            left, top, right, bottom = 10, 20, 30, 40

        class Element:
            BoundingRectangle = Rect()

            def GetRuntimeId(self):
                return (1,)
        node = VNode(name='31', role='cell', rect=(10, 20, 30, 40))
        self.assertTrue(self.h._same_element(node, Element()))
        self.assertFalse(self.h._same_element(VNode(name='x', rect=(0, 0, 1, 1)), Element()))

    def test_the_table_neighbour_through_a_grid(self):
        class Grid:
            RowCount, ColumnCount = 2, 2
            def GetItem(self, r, c):
                return ('cell', r, c)

        class GridControl:
            def GetGridPattern(self):
                return Grid()

        class Item:
            Row, Column = 0, 0
            ContainingGrid = GridControl()

        class Element:
            def GetGridItemPattern(self):
                return Item()
        from titan_access.virtual_buffer import VNode
        node = VNode(name='a', role='cell', element=Element())
        self.assertEqual(self.h._table_neighbour(node, 1, 0), (('cell', 1, 0), (1, 0)))
        self.assertEqual(self.h._table_neighbour(node, -1, 0), (None, (0, 0)))
        self.assertEqual(self.h._table_neighbour(VNode(name='x'), 1, 0), (None, None))

    def test_the_keys_reach_them(self):
        source = io.open(os.path.join(COMPONENT, 'titan_access', 'browse_mode.py'),
                         encoding='utf-8').read()
        self.assertIn('if ctrl and alt and vk in', source)
        self.assertIn('if key_name == "f3":', source)
        engine = io.open(os.path.join(COMPONENT, 'titan_access', 'engine.py'),
                         encoding='utf-8').read()
        for spec in ('"f7"', '"control+f"', '"shift+f1"', '"f"'):
            self.assertIn('g.register(', engine)
            self.assertIn(spec, engine)


class NotificationsFromAConsoleAreNotABabble(unittest.TestCase):

    def _listener(self):
        from titan_access.uia_notifications import UIANotifications
        said = []
        listener = UIANotifications(lambda text, interrupt: said.append((text, interrupt)))
        listener._from_terminal = lambda sender: getattr(sender, 'terminal', False)
        return listener, said

    def test_a_senders_burst_is_one_notification(self):
        listener, said = self._listener()

        class Sender:
            def GetRuntimeId(self):
                return (1, 2, 3)
        for i in range(10):
            listener.notification(Sender(), 0, 0, 'fragment %d' % i, '')
        self.assertEqual(len(said), 1, said)
        self.assertEqual(listener.counts['burst'], 9)

    def test_an_interrupt_comes_at_most_every_two_seconds(self):
        from titan_access import uia_notifications
        listener, said = self._listener()
        old = uia_notifications.NOTIFY_MIN_GAP
        uia_notifications.NOTIFY_MIN_GAP = 0.0
        try:
            class Sender:
                def GetRuntimeId(self):
                    return (9,)
            listener.notification(Sender(), 0, 0, 'first', '')
            listener.notification(Sender(), 0, 0, 'second', '')
            self.assertEqual([one[1] for one in said], [True, False])
        finally:
            uia_notifications.NOTIFY_MIN_GAP = old

    def test_a_console_is_left_to_the_terminal_module(self):
        listener, said = self._listener()

        class Console:
            terminal = True

            def GetRuntimeId(self):
                return (4,)
        listener.notification(Console(), 0, 0, 'output', '')
        self.assertEqual(said, [])
        self.assertEqual(listener.counts['terminal'], 1)

    def test_the_words_are_one_line(self):
        listener, said = self._listener()

        class Sender:
            def GetRuntimeId(self):
                return (5,)
        listener.notification(Sender(), 0, 3, 'a\nb   c', '')
        self.assertEqual(said, [('a b c', False)])


class TheSelectionIsReportedAsItChanges(unittest.TestCase):

    def _handler(self, selections):
        from titan_access.editable_text import EditableTextHandler
        h = EditableTextHandler.__new__(EditableTextHandler)
        h.engine = type('E', (), {})()
        h.engine.said = []
        h.engine.current_object = None
        h.engine.speak = lambda text, *a, **k: h.engine.said.append(str(text))
        from titan_access import settings_store
        h.engine.settings = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), 'r.ini'))
        it = iter(selections)
        h._selection_text = lambda: next(it)
        return h

    def test_what_joined_and_what_left(self):
        h = self._handler(['one', 'one two', 'one'])
        h.read_selection_change()
        self.assertIn('one', h.engine.said[-1])
        h.read_selection_change()
        self.assertIn('two', h.engine.said[-1])
        self.assertNotIn('one two', h.engine.said[-1])
        h.read_selection_change()
        self.assertIn('two', h.engine.said[-1])

    def test_the_hook_passes_shift(self):
        hook = io.open(os.path.join(COMPONENT, 'titan_access', 'keyboard_hook.py'),
                       encoding='utf-8').read()
        self.assertIn('self.engine.on_edit_caret_move(key_name, self._ctrl,\n'
                      '                                                   self._shift)', hook)


if __name__ == '__main__':
    unittest.main(verbosity=1)

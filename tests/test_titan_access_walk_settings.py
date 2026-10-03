# -*- coding: utf-8 -*-
"""The walked lists' own settings really change what a walked list does.

Each switch of the "Virtual windows and the palette" section is read by
the shared `palette` / `virtualWindow` modules through the switchboard, so
each is tested by flipping it and walking a list: the kind and the place
disappear from a row, the title is not said, the tone is not played, the
end wraps round, the layout is kept. No window, no sound, no speech.

Run directly: ``python tests/test_titan_access_walk_settings.py``.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)


class TheWalkSwitchesAreReal(unittest.TestCase):

    def setUp(self):
        from titan_access.portable import palette, switchboard, icons, hostWindow
        self.palette, self.switchboard = palette, switchboard
        self.values = {}
        self._old_read = switchboard.read
        self._old_value = switchboard.value
        self._old_write = switchboard.write
        switchboard.read = lambda name, default=True: bool(self.values.get(name, default))
        switchboard.value = lambda name, default=None: self.values.get(name, default)
        switchboard.write = lambda name, value: self.values.__setitem__(name, value) or True
        self.said = []
        self._old_say_parts = palette._say_parts
        palette._say_parts = lambda parts: self.said.append(list(parts))
        self._old_say = palette._say
        palette._say = lambda text: self.said.append([(str(text), 'title')])
        self.beeped = []
        self._old_beep = palette._beep
        palette._beep = lambda at, count: self.beeped.append(at)
        self._old_edge = palette._edge
        palette._edge = lambda: self.said.append([('<edge>', 'edge')])
        self._old_play = icons.play
        icons.play = lambda name, *a, **k: False
        self._old_host = hostWindow.show
        self.hosted = []
        hostWindow.show = lambda title, walking, then=None: (
            self.hosted.append(title), then and then())
        palette.stop()

    def tearDown(self):
        from titan_access.portable import palette, switchboard, icons, hostWindow
        palette.stop()
        switchboard.read = self._old_read
        switchboard.value = self._old_value
        switchboard.write = self._old_write
        palette._say_parts = self._old_say_parts
        palette._say = self._old_say
        palette._beep = self._old_beep
        palette._edge = self._old_edge
        icons.play = self._old_play
        hostWindow.show = self._old_host

    def _rows(self):
        return [{'label': 'One', 'role': 'page', 'run': lambda: (True, '')},
                {'label': 'Two', 'role': 'page', 'run': lambda: (True, '')},
                {'label': 'Three', 'role': 'page', 'run': lambda: (True, '')}]

    def _classes(self, parts):
        return [voice for _text, voice in parts]

    def test_kind_and_position_are_switches(self):
        self.palette.show(self._rows(), 'A list')
        parts = self.said[-1]
        self.assertIn('kind', self._classes(parts))
        self.assertIn('place', self._classes(parts))
        self.palette.stop()
        self.values.update({'walkSayKind': False, 'walkSayPosition': False})
        self.said[:] = []
        self.palette.show(self._rows(), 'A list')
        parts = self.said[-1]
        self.assertEqual(self._classes(parts), ['name'])

    def test_the_title_is_a_switch(self):
        self.palette.show(self._rows(), 'A list')
        self.assertEqual(self.said[0], [('A list', 'title')])
        self.palette.stop()
        self.values['walkSayTitle'] = False
        self.said[:] = []
        self.palette.show(self._rows(), 'A list')
        self.assertNotIn([('A list', 'title')], self.said)

    def test_the_row_tone_is_a_switch(self):
        self.palette.show(self._rows(), 'A list')
        self.palette.move(1)
        self.assertTrue(self.beeped)
        self.palette.stop()
        self.values['walkRowBeep'] = False
        self.beeped[:] = []
        self.palette.show(self._rows(), 'A list')
        self.palette.move(1)
        self.assertEqual(self.beeped, [])

    def test_wrapping_is_a_switch(self):
        self.palette.show(self._rows(), 'A list')
        self.palette.move_end(True)
        self.palette.move(1)
        self.assertIn([('<edge>', 'edge')], self.said)
        self.assertEqual(self.palette.here()['label'], 'Three')
        self.palette.stop()
        self.values['walkWrap'] = True
        self.said[:] = []
        self.palette.show(self._rows(), 'A list')
        self.palette.move_end(True)
        self.palette.move(1)
        self.assertNotIn([('<edge>', 'edge')], self.said)
        self.assertEqual(self.palette.here()['label'], 'One')

    def test_the_host_window_is_a_switch(self):
        self.palette.show(self._rows(), 'A list')
        self.assertEqual(self.hosted, ['A list'])
        self.palette.stop()
        self.values['walkHostWindow'] = False
        self.hosted[:] = []
        self.palette.show(self._rows(), 'A list')
        self.assertEqual(self.hosted, [])
        self.assertTrue(self.said)                     # still announced

    def test_the_layout_is_kept_and_read_back(self):
        from titan_access.portable import virtualWindow
        with virtualWindow._LOCK:
            virtualWindow._state.pop('layout', None)
        self.values['walkLayout'] = 'screen'
        self.assertEqual(virtualWindow.layout(), 'screen')
        virtualWindow.layout_cycle(1)
        self.assertEqual(self.values['walkLayout'], 'interact')
        self.assertEqual(virtualWindow.layout(), 'interact')
        with virtualWindow._LOCK:
            virtualWindow._state.pop('layout', None)
        self.values['walkLayout'] = 'nonsense'
        self.assertEqual(virtualWindow.layout(), 'linear')

    def test_every_walk_switch_is_in_the_schema_and_both_readers_declare_it(self):
        from titan_access import settings_schema
        import io
        names = {e.key for e in settings_schema.entries() if e.key.startswith('walk')}
        self.assertEqual(names, {'walkLayout', 'walkSayKind', 'walkSayPosition',
                                 'walkSayTitle', 'walkRowBeep', 'walkWrap',
                                 'walkHostWindow'})
        spec = io.open(os.path.join(TITAN, 'nvda-addon', 'addon', 'globalPlugins',
                                    'titanEnhancements', 'configSpec.py'),
                       encoding='utf-8').read()
        for name in names:
            self.assertIn("'%s'" % name, spec)


if __name__ == '__main__':
    unittest.main(verbosity=1)

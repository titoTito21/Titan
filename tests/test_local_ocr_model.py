# -*- coding: utf-8 -*-
"""The local recogniser: the tier between Windows' own and the AI.

    python tests/test_local_ocr_model.py

Nothing here downloads anything, loads a model or reaches the network -
what is tested is the shape the tier promises and the way it degrades
when nothing is installed, which is the state most machines are in and
the one a reader has to survive.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
if TITAN not in sys.path:
    sys.path.insert(0, TITAN)


class AbsentIsANormalState(unittest.TestCase):
    """Nothing is installed by default, and a machine that never fetches
    it behaves exactly as it did before."""

    def setUp(self):
        from src.ai.ocr import local_model
        self.model = local_model

    def test_it_says_whether_it_is_there_rather_than_raising(self):
        ok, why = self.model.available()
        self.assertIsInstance(ok, bool)
        if not ok:
            self.assertTrue(why, 'absent, and it will not say why')

    def test_the_report_answers_whether_or_not_it_is_installed(self):
        found = self.model.report()
        for key in ('installed', 'reads', 'failed', 'why', 'folder'):
            self.assertIn(key, found)

    def test_reading_without_it_is_a_reason_not_an_exception(self):
        ok, answer = self.model.read_array(None)
        if not ok:
            self.assertIsInstance(answer, str)
            self.assertTrue(answer)

    def test_nothing_is_imported_at_module_level(self):
        """`onnxruntime` alone is most of a second, and Titan spent real
        work getting its start-up down."""
        source = open(os.path.join(TITAN, 'src', 'ai', 'ocr',
                                   'local_model.py'), encoding='utf-8').read()
        head = source[:source.index('def folder(')]
        for heavy in ('onnxruntime', 'rapidocr', 'numpy'):
            self.assertNotIn('\nimport %s' % heavy, head)
            self.assertNotIn('\nfrom %s' % heavy, head)


class WhatItAnswers(unittest.TestCase):
    """The shape, which is what everything downstream is written against."""

    def setUp(self):
        from src.ai.ocr import local_model
        self.model = local_model

    def test_a_polygon_becomes_a_rectangle(self):
        """The detector answers a QUADRILATERAL, because text can be at
        an angle; everything downstream wants a rectangle to click in the
        middle of."""
        found = self.model._rect_of([[10, 20], [90, 22], [90, 40], [10, 38]])
        self.assertEqual(found, (10, 20, 80, 20))

    def test_a_box_it_cannot_read_is_a_zero_rectangle_not_a_crash(self):
        self.assertEqual(self.model._rect_of(None), (0, 0, 0, 0))
        self.assertEqual(self.model._rect_of('nonsense'), (0, 0, 0, 0))

    def test_both_shapes_of_the_librarys_answer_are_read(self):
        """This is somebody else's library and its result object has
        changed shape between major versions. A tier that stopped working
        on an upgrade would be a tier nobody could rely on."""
        class Newer:
            boxes = [[[0, 0], [10, 0], [10, 5], [0, 5]]]
            txts = ['Save']
            scores = [0.98]
        rows = self.model._lines_of(Newer())
        self.assertEqual(rows[0]['text'], 'Save')
        self.assertAlmostEqual(rows[0]['score'], 0.98, places=2)

        older = [([[0, 0], [10, 0], [10, 5], [0, 5]], 'Open', 0.9)]
        rows = self.model._lines_of(older)
        self.assertEqual(rows[0]['text'], 'Open')

    def test_an_answer_of_nothing_is_no_lines_rather_than_a_failure(self):
        self.assertEqual(self.model._lines_of(None), [])
        self.assertEqual(self.model._lines_of([]), [])


class TheDoorwayBothReadersUse(unittest.TestCase):
    """The model lives in Titan, so the add-on stays small and Titan
    Access reaches the same one - through the same call."""

    def test_reading_is_served_and_installing_is_not(self):
        """Reading sends nothing anywhere and costs nothing; fetching it
        is a download, and a download is asked for."""
        from src.titan_core import bridge_api
        self.assertIn('ocr.read_local', bridge_api.CALLS)
        self.assertIn('ocr.model', bridge_api.CALLS)
        self.assertIn('ocr.install_model', bridge_api.CALLS)
        self.assertIn('ocr.read_local', bridge_api.READ_ONLY)
        self.assertIn('ocr.model', bridge_api.READ_ONLY)
        self.assertNotIn('ocr.install_model', bridge_api.READ_ONLY)

    def test_a_reading_answers_SCREEN_coordinates(self):
        """`Capture` alone knows what it photographed and where, so the
        conversion happens in Titan rather than being handed to the
        caller as arithmetic it cannot check."""
        source = open(os.path.join(TITAN, 'src', 'titan_core',
                                   'bridge_api.py'), encoding='utf-8').read()
        at = source.index('def _ocr_read_local(')
        end = source.index('\ndef ', at + 10)
        self.assertIn('rect_to_screen', source[at:end])

    def test_the_picture_is_decoded_without_an_imaging_library(self):
        """Titan deliberately has none - `_encode_png` is written the
        same way and this is its mirror."""
        source = open(os.path.join(TITAN, 'src', 'titan_core',
                                   'bridge_api.py'), encoding='utf-8').read()
        at = source.index('def _picture_of(')
        end = source.index('\ndef ', at + 10)
        block = source[at:end]
        self.assertIn('zlib', block)
        self.assertNotIn('PIL', block)


class ItIsADownloadAndNotPartOfTitan(unittest.TestCase):
    """234 MB of onnxruntime and its models against a Titan a fraction of
    that. A user who never asks to read a game as a picture should carry
    none of it."""

    def test_it_is_not_a_requirement(self):
        text = open(os.path.join(TITAN, 'requirements.txt'),
                    encoding='utf-8').read().lower()
        for name in ('rapidocr', 'onnxruntime', 'opencv'):
            self.assertNotIn(name, text,
                             '%s would be installed for everybody' % name)

    def test_both_build_paths_exclude_it(self):
        """`local_model.py` imports them inside a call, so PyInstaller
        cannot see them by following the code - which means a build
        machine that HAS them installed would bake them in unless it is
        told not to, and it would do it silently."""
        spec = open(os.path.join(TITAN, 'Titan.spec'), encoding='utf-8').read()
        build = open(os.path.join(TITAN, 'compiletorelease.py'),
                     encoding='utf-8').read()
        for name in ('rapidocr', 'onnxruntime'):
            self.assertIn(name, spec, 'Titan.spec does not exclude %s' % name)
            self.assertIn(name, build,
                          'compiletorelease.py does not exclude %s' % name)
        self.assertIn('--exclude-module', build)

    def test_the_models_go_into_the_users_own_folder(self):
        """Not beside the library: that is a folder an update replaces, a
        packaged Titan would have to carry, and nobody would think to
        delete."""
        from src.ai.ocr import local_model
        where = local_model.folder()
        self.assertIn('Titan', where)
        self.assertTrue(where.endswith('models'))
        source = open(os.path.join(TITAN, 'src', 'ai', 'ocr',
                                   'local_model.py'), encoding='utf-8').read()
        self.assertIn('Global.model_root_dir', source)


class OfferedWhereTheNeedArises(unittest.TestCase):
    """Somebody reading a window is the moment to offer it - not a
    settings page they would have to already know about."""

    def setUp(self):
        from src.ai.ocr import local_model
        self.model = local_model

    def test_it_is_offered_from_the_reading_itself(self):
        source = open(os.path.join(TITAN, 'src', 'ai', 'ocr',
                                   'recognizer.py'), encoding='utf-8').read()
        at = source.index('def read_screen(')
        end = source.index('\ndef ', at + 10)
        self.assertIn('local_model.offer()', source[at:end])

    def test_it_is_offered_before_the_provider_is_checked(self):
        """"There is no AI key" is exactly the person this helps most:
        with the local model they can read the window at all."""
        source = open(os.path.join(TITAN, 'src', 'ai', 'ocr',
                                   'recognizer.py'), encoding='utf-8').read()
        at = source.index('def read_screen(')
        block = source[at:source.index('\ndef ', at + 10)]
        self.assertLess(block.index('local_model.offer()'),
                        block.index('vision_unavailable_reason'))

    def test_nothing_is_offered_when_there_is_nobody_to_ask(self):
        """A dialog raised with nothing behind it answers itself, which is
        how a yes gets written that nobody gave."""
        offered, why = self.model.offer()
        self.assertIsInstance(offered, bool)
        if not offered:
            self.assertTrue(why)

    def test_it_is_asked_once(self):
        """A question somebody has said no to and is asked again every
        time they read a window has become a nuisance."""
        source = open(os.path.join(TITAN, 'src', 'ai', 'ocr',
                                   'local_model.py'), encoding='utf-8').read()
        at = source.index('def offer(')
        block = source[at:source.index('\ndef ', at + 10)]
        self.assertIn('_asked_already', block)

    def test_offering_it_never_installs_by_itself(self):
        """It is a download of a few hundred megabytes."""
        source = open(os.path.join(TITAN, 'src', 'ai', 'ocr',
                                   'local_model.py'), encoding='utf-8').read()
        at = source.index('def offer(')
        block = source[at:source.index('\ndef _fetch_on_a_thread', at)]
        self.assertIn('ID_YES', block)


class TheIconModelIsNotWiredToSpeech(unittest.TestCase):
    """Measured and found wrong too often to speak.

    On this machine it announced GitHub Desktop and two folder windows
    all as "information", and Windows' own folder icon as "envelope". A
    reader that says "envelope" for a folder is worse than one that says
    "icon", so it stays unreached until a bigger picture makes it right.
    """

    def setUp(self):
        from src.ai.ocr import icon_model
        self.icons = icon_model

    def test_nothing_that_speaks_reaches_it(self):
        guilty = []
        for where in ('nvda-addon', os.path.join('data', 'components',
                                                 'titan access')):
            for root, _dirs, names in os.walk(os.path.join(TITAN, where)):
                for name in names:
                    if not name.endswith('.py'):
                        continue
                    path = os.path.join(root, name)
                    with open(path, encoding='utf-8', errors='replace') as f:
                        if 'icon_model' in f.read():
                            guilty.append(os.path.relpath(path, TITAN))
        self.assertEqual(guilty, [],
                         'a reader now speaks through the icon model')

    def test_the_measurement_is_written_down(self):
        """So the next person does not have to find it out again."""
        source = open(os.path.join(TITAN, 'src', 'ai', 'ocr',
                                   'icon_model.py'), encoding='utf-8').read()
        self.assertIn('NOT_YET_SPOKEN', source)
        self.assertIn('SHDefExtractIconW', source,
                      'the next thing to try is not written down')

    def test_it_declines_rather_than_guessing(self):
        """A zero-shot model always has a nearest label; the floor and
        the margin are what stop it being a confident lie."""
        self.assertGreater(self.icons.SURE_ENOUGH, 0.15)
        self.assertGreater(self.icons.CLEAR_MARGIN, 0.0)
        escapes = [one for one in self.icons.VOCABULARY if not one[0]]
        self.assertTrue(escapes, 'nothing for a logo to land on')

    def test_absent_is_a_normal_state(self):
        ok, why = self.icons.available()
        self.assertIsInstance(ok, bool)
        if not ok:
            self.assertTrue(why)

if __name__ == '__main__':
    unittest.main(verbosity=2)

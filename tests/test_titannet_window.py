"""Two Titan-Net faults the user reported, and the checks that hold them.

    python tests/test_titannet_window.py

Nothing here opens a window, plays a sound, speaks or reaches the network.
"""

import io
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
sys.path.insert(0, TITAN)


def read(*parts):
    with io.open(os.path.join(TITAN, *parts), encoding='utf-8') as handle:
        return handle.read()


class TheDownloadCount(unittest.TestCase):
    """The repository said every application had been downloaded nought
    times, however many times it had.

    The column is `downloads`, the details endpoint answers `SELECT ar.*`,
    the web repository reads `app.downloads` and the server sums
    `SUM(downloads)`. One reader in the whole of Titan asked for
    `download_count`, a name nothing writes - so `.get(name, 0)` handed
    back its default, every time, and looked exactly like a working field.
    """

    def test_the_client_asks_for_the_name_the_server_sends(self):
        source = read('src', 'network', 'titan_net_gui.py')
        self.assertIn("app.get('downloads', 0)", source)
        self.assertNotIn("app.get('download_count'", source)

    def test_nothing_anywhere_writes_download_count(self):
        """If a producer is ever added, this is where to notice."""
        for parts in (('titan-net server', 'models.py'),
                      ('titan-net server', 'http_server.py'),
                      ('titan-net server', 'web', 'js', 'repository.js')):
            self.assertNotIn('download_count', read(*parts), parts[-1])

    def test_the_column_is_downloads(self):
        models = read('titan-net server', 'models.py')
        self.assertIn('downloads INTEGER DEFAULT 0', models)
        self.assertIn('SET downloads = downloads + 1', models)


class WhyTitanNetDidNotOpen(unittest.TestCase):
    """"Sometimes there is an error opening Titan-Net", and never a reason.

    `show_titan_net_window` answers with nothing for two completely
    different causes - the connection has gone, or the window would not
    build - and it ANNOUNCED that itself while every caller then said
    "Error opening Titan-Net" as well. Both announcements interrupt, so
    the second erased the first: the true sentence was said and wiped, and
    what was left was the useless one. A dropped socket is what makes it
    intermittent, since the window refreshes every fifteen seconds.
    """

    def module(self):
        from src.network import titan_net_gui
        return titan_net_gui

    def test_a_lost_connection_is_reported_as_a_lost_connection(self):
        gui = self.module()
        self.assertIsNone(gui.show_titan_net_window(
            None, types.SimpleNamespace(is_connected=False)))
        self.assertIn('Titan-Net', gui.last_open_problem())

    def test_the_reason_is_cleared_before_each_attempt(self):
        """A stale reason read after a later success would name a failure
        that did not happen."""
        gui = self.module()
        gui.show_titan_net_window(None, types.SimpleNamespace(is_connected=False))
        self.assertTrue(gui.last_open_problem())

    def test_the_opener_no_longer_announces_it_itself(self):
        source = read('src', 'network', 'titan_net_gui.py')
        opener = source[source.index('def show_titan_net_window'):]
        self.assertNotIn('speak_notification', opener)

    def test_every_face_of_titan_asks_why(self):
        """The main window, the Invisible UI, Klango mode and a launcher.
        A face that does not ask says the useless sentence, or - which is
        what three of them did - says nothing at all."""
        for parts in (('src', 'ui', 'gui.py'),
                      ('src', 'ui', 'invisibleui.py'),
                      ('src', 'system', 'klangomode.py'),
                      ('src', 'titan_core', 'launcher_manager.py')):
            self.assertIn('last_open_problem', read(*parts), parts[-1])

    def test_the_sentence_it_says_is_translated(self):
        from src.titan_core.translation import set_language
        for language, expect in (('pl', 'Titan-Net'), ('en', 'Titan-Net')):
            translate = set_language(language)
            said = translate("Titan-Net could not open: {error}")
            self.assertIn(expect, said)
            self.assertIn('{error}', said)
            if language == 'pl':
                self.assertNotEqual(said, "Titan-Net could not open: {error}")


if __name__ == '__main__':
    unittest.main(verbosity=2)

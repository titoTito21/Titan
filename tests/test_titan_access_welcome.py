# -*- coding: utf-8 -*-
"""Titan Access's welcome window.

The help text exists in both languages, the window is "Welcome to Titan
Access" with a read-only edit field holding it, a tick box that is on by
default and an OK button, and unticking the box means the window is not
offered again. Built, never shown; the settings are a temporary store.

Run directly: ``python tests/test_titan_access_welcome.py``.
"""

import os
import sys
import tempfile
import unittest

_HOME = tempfile.mkdtemp(prefix='ta_welcome_')
os.environ['APPDATA'] = _HOME
os.environ['HOME'] = _HOME

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)

from titan_access import welcome_screen, localization        # noqa: E402
from titan_access.settings_store import get_settings          # noqa: E402

_APP = None


def _wx():
    global _APP
    try:
        import wx
    except Exception:                                # noqa: BLE001
        raise unittest.SkipTest('no wx')
    if wx.GetApp() is None:
        _APP = wx.App(False)
    return wx


class TheHelpIsInBothLanguages(unittest.TestCase):

    def test_both_files_say_the_shortcuts(self):
        pl = welcome_screen.help_text('pl')
        en = welcome_screen.help_text('en')
        self.assertIn('Insert+c', pl)
        self.assertIn('Insert+C', en)
        self.assertIn('Titan Access stops working', en)
        self.assertNotEqual(pl, en)
        self.assertEqual(len(pl.splitlines()), len(en.splitlines()))

    def test_an_unknown_language_falls_back_to_english(self):
        self.assertEqual(welcome_screen.help_text('xx'),
                         welcome_screen.help_text('en'))


class TheWindow(unittest.TestCase):

    def setUp(self):
        self.wx = _wx()
        settings = get_settings()
        settings.show_welcome = True
        settings.save()

    def tearDown(self):
        localization.set_language('pl')

    def _build(self):
        dialog = welcome_screen.build(None)
        self.addCleanup(lambda: dialog and dialog.Destroy())
        return dialog

    def test_it_is_the_window_asked_for(self):
        wx = self.wx
        localization.set_language('pl')
        dialog = self._build()
        self.assertEqual(dialog.GetTitle(), 'Witamy w Titan access')
        self.assertTrue(dialog.text.IsMultiLine())
        self.assertFalse(dialog.text.IsEditable())
        self.assertEqual(dialog.text.GetValue().replace('\r', ''),
                         welcome_screen.help_text('pl'))
        self.assertEqual(dialog.check.GetLabel(),
                         'Pokaż ekran powitalny przy starcie')
        self.assertTrue(dialog.check.GetValue())
        self.assertEqual(dialog.ok.GetId(), wx.ID_OK)
        self.assertEqual(dialog.ok.GetLabel(), 'OK')

    def test_english(self):
        localization.set_language('en')
        dialog = self._build()
        self.assertEqual(dialog.GetTitle(), 'Welcome to Titan Access')
        self.assertIn('Insert+Shift+Space', dialog.text.GetValue())

    def test_the_box_is_on_by_default(self):
        self.assertTrue(get_settings().show_welcome)
        self.assertTrue(welcome_screen.wanted())

    def test_unticked_it_is_never_offered_again(self):
        dialog = welcome_screen.build(None)
        dialog.check.SetValue(False)
        dialog.close()
        self.assertFalse(get_settings().show_welcome)
        self.assertFalse(welcome_screen.wanted())
        offered = []
        old = self.wx.CallAfter
        self.wx.CallAfter = lambda fn, *a: offered.append(fn)
        try:
            self.assertFalse(welcome_screen.offer())
        finally:
            self.wx.CallAfter = old
        self.assertEqual(offered, [])
        # And saved, so it is still off after a restart.
        from titan_access.settings_store import SettingsStore
        self.assertFalse(SettingsStore().show_welcome)

    def test_left_ticked_it_is_offered(self):
        dialog = welcome_screen.build(None)
        dialog.close()
        self.assertTrue(get_settings().show_welcome)
        offered = []
        old = self.wx.CallAfter
        self.wx.CallAfter = lambda fn, *a: offered.append(fn)
        try:
            self.assertTrue(welcome_screen.offer())
        finally:
            self.wx.CallAfter = old
        self.assertEqual(offered, [welcome_screen._show])


class TheEngineOffersIt(unittest.TestCase):

    def test_a_start_offers_and_a_supervisor_restart_does_not(self):
        from titan_access import engine
        asked = []
        old = welcome_screen.offer
        welcome_screen.offer = lambda: asked.append(1)
        try:
            fresh = engine.TitanAccessEngine.__new__(engine.TitanAccessEngine)
            fresh._offer_welcome()
            self.assertEqual(asked, [1])
            fresh.is_restart = True
            fresh._offer_welcome()
            self.assertEqual(asked, [1])
        finally:
            welcome_screen.offer = old


if __name__ == '__main__':
    unittest.main()

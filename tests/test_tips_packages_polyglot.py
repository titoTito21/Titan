# -*- coding: utf-8 -*-
"""Settings -> General: the usage tips switch and the Titan-Net package
folder; and Polyglot's windows, labelled for a screen reader.

Nothing here speaks, shows a window or reaches the network: settings are
read from a temporary APPDATA, the windows are built and never shown.
Run it directly - `tests/` has no `__init__.py`.
"""

import os
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='titan_tips_')

from src.settings import settings  # noqa: E402


def _set(key, value, section):
    settings.set_setting(key, value, section=section)


class TheUsageTipsHaveASwitch(unittest.TestCase):

    def setUp(self):
        from src.accessibility import messages
        self.messages = messages
        self.said = []
        self._speak = messages.AccessibilityMessenger.speak_message
        self._show = messages.AccessibilityMessenger.show_timed_message
        messages.AccessibilityMessenger.speak_message = (
            lambda _self, text, **k: self.said.append(text))
        messages.AccessibilityMessenger.show_timed_message = (
            lambda _self, text, **k: self.said.append(text))
        messages._messenger_instance = object.__new__(messages.AccessibilityMessenger)

    def tearDown(self):
        self.messages.AccessibilityMessenger.speak_message = self._speak
        self.messages.AccessibilityMessenger.show_timed_message = self._show
        self.messages._messenger_instance = None
        self.messages.cancel_tab_bar_tip()

    def test_on_by_default(self):
        _set('speak_usage_tips', 'True', 'general')
        self.assertTrue(self.messages.usage_tips_enabled())

    def test_off_silences_every_tip(self):
        _set('speak_usage_tips', 'False', 'general')
        self.assertFalse(self.messages.usage_tips_enabled())
        self.assertIsNone(self.messages.show_invisible_ui_tip(delay=0))
        self.assertIsNone(self.messages.show_disable_titan_ui_tip(delay=0))
        self.assertIsNone(self.messages.show_tab_bar_tip(delay=0))
        self.assertEqual(self.said, [])

    def test_on_says_them(self):
        _set('speak_usage_tips', 'True', 'general')
        self.messages.show_invisible_ui_tip(delay=0)
        event = self.messages.show_tab_bar_tip(delay=0.01)
        self.assertIsInstance(event, threading.Event)
        for _ in range(100):
            if len(self.said) >= 2:
                break
            threading.Event().wait(0.02)
        self.assertEqual(len(self.said), 2)

    def test_a_waiting_tip_is_dropped_when_switched_off(self):
        _set('speak_usage_tips', 'True', 'general')
        self.messages.show_tab_bar_tip(delay=0.2)
        _set('speak_usage_tips', 'False', 'general')
        threading.Event().wait(0.4)
        self.assertEqual(self.said, [])


class PackagesGoWhereTheUserChose(unittest.TestCase):

    def setUp(self):
        from src.network import package_downloads
        self.pd = package_downloads
        self.folder = tempfile.mkdtemp(prefix='titan_pkgs_')

    def tearDown(self):
        _set('packages_folder', '', 'titannet')

    def test_the_default_is_the_users_downloads(self):
        _set('packages_folder', '', 'titannet')
        self.assertEqual(self.pd.packages_folder(create=False),
                         self.pd.user_downloads_folder())

    def test_a_chosen_folder_is_used_and_made(self):
        chosen = os.path.join(self.folder, 'pakiety')
        _set('packages_folder', chosen, 'titannet')
        self.assertEqual(self.pd.packages_folder(), chosen)
        self.assertTrue(os.path.isdir(chosen))

    def test_a_package_is_never_written_over(self):
        _set('packages_folder', self.folder, 'titannet')
        app = {'name': 'tCalc', 'version': '1.2', 'uploader_username': 'anna'}
        first = self.pd.save_path_for(app)
        self.assertEqual(os.path.basename(first), 'anna_tCalc_v1.2.TCEPACKAGE')
        open(first, 'wb').close()
        self.assertNotEqual(self.pd.save_path_for(app), first)

    def test_the_window_saves_there(self):
        from src.network import titan_net_gui
        _set('packages_folder', self.folder, 'titannet')
        path = titan_net_gui.TitanNetMainWindow._build_package_save_path(
            None, {'name': 'x', 'version': '1'})
        self.assertEqual(os.path.dirname(path), self.folder)


_APP = []


def _app():
    import wx
    if not wx.GetApp():
        _APP.append(wx.App(False))   # kept alive: an unreferenced App is collected
    return wx.GetApp()


class TheSettingsWindowHasBoth(unittest.TestCase):

    def test_built_loaded_and_saved(self):
        import wx
        _app()
        from src.ui import settingsgui
        _set('speak_usage_tips', 'True', 'general')
        _set('packages_folder', '', 'titannet')
        frame = settingsgui.SettingsFrame(None)
        try:
            self.assertTrue(frame.usage_tips_cb.GetValue())
            self.assertEqual(frame.packages_folder_ctrl.GetValue(), '')
            for control in (frame.usage_tips_cb, frame.packages_folder_ctrl,
                            frame.packages_folder_btn):
                parent = control.GetParent()
                while parent is not None and parent is not frame.general_panel:
                    parent = parent.GetParent()
                self.assertIs(parent, frame.general_panel)
            # The field's own label is the window right before it.
            self.assertIsInstance(_before(frame.packages_folder_ctrl), wx.StaticText)
        finally:
            frame.Destroy()

    def test_saved_into_their_sections(self):
        import re
        source = open(os.path.join(ROOT, 'src', 'ui', 'settingsgui.py'),
                      encoding='utf-8').read()
        self.assertRegex(source, r"'speak_usage_tips': str\(self\.usage_tips_cb\.GetValue\(\)\)")
        self.assertIn("self.settings.setdefault('titannet', {})['packages_folder']", source)


def _before(control):
    """The sibling created just before `control` - what Windows names it after."""
    siblings = list(control.GetParent().GetChildren())
    index = siblings.index(control)
    return siblings[index - 1] if index else None


class PolyglotIsLabelled(unittest.TestCase):

    def test_every_field_of_the_language_dialog_has_its_own_label(self):
        import wx
        _app()
        frame = wx.Frame(None)
        sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'polyglot'))
        from polyglotkit import settings_page
        dialog = settings_page.LanguageDialog(frame, settings_page.Languages([]))
        try:
            fields = [dialog.ident, dialog.name, dialog.extensions, dialog.find,
                      dialog.command, dialog.compile, dialog.output,
                      dialog.env, dialog.note]
            for field in fields:
                label = _before(field)
                self.assertIsInstance(label, wx.StaticText, field.GetName())
                self.assertEqual(label.GetLabel().replace('&', '').rstrip(':')[:12],
                                 field.GetName()[:12])
            # One Alt+letter per control, or a mnemonic lands somewhere else.
            keys = [c.GetLabel().split('&')[1][0].lower()
                    for c in dialog.ident.GetParent().GetChildren()
                    if '&' in c.GetLabel()]
            self.assertEqual(len(keys), len(set(keys)), keys)
        finally:
            dialog.dialog.Destroy()
            frame.Destroy()

    def test_the_window_holds_the_keyboard_against_the_invisible_ui(self):
        """Opened from the Invisible UI's components, its arrows, Enter and
        Escape must be the window's while it is up, and given back after."""
        import importlib.util
        import wx
        _app()
        calls = []

        class Recorder(object):
            def temporarily_disable_titan_ui(self, name):
                calls.append(('take', name))

            def _on_dialog_close(self, name, _event):
                calls.append(('give', name))

        titan = wx.Frame(None)
        titan.invisible_ui = Recorder()
        spec = importlib.util.spec_from_file_location(
            'polyglot_window_test',
            os.path.join(ROOT, 'data', 'components', 'polyglot', 'init.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        during = []
        original = wx.Dialog.ShowModal
        wx.Dialog.ShowModal = lambda self: (during.append(list(calls)),
                                            wx.ID_CANCEL)[1]
        try:
            module.show_window(None)
        finally:
            wx.Dialog.ShowModal = original
            titan.Destroy()
        self.assertEqual(during, [[('take', 'polyglot')]])
        self.assertEqual(calls, [('take', 'polyglot'), ('give', 'polyglot')])

    def test_the_languages_list_is_named_by_its_own_label(self):
        import wx
        _app()
        frame = wx.Frame(None)
        from polyglotkit import settings_page
        panel = settings_page.build(frame)
        try:
            label = _before(panel.listing)
            self.assertIsInstance(label, wx.StaticText)
            self.assertIn('L', label.GetLabel())
        finally:
            frame.Destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)

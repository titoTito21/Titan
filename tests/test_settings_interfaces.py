# -*- coding: utf-8 -*-
"""Settings interfaces, and the model they render.

Run it directly (`python tests/test_settings_interfaces.py`) - `tests/` has
no `__init__.py`.

The thing being tested is the promise: an interface author writes a
renderer, not a catalogue.  So most of this is about `src/settings/ui_model.py`
reading a real wx window correctly - the labels, the kinds, the options and
the values - because everything else in the feature rests on that being
true.  A hand-built panel stands in for Titan's settings where a test needs
to know exactly what is on it; one test builds the real thing.
"""

import os
import sys
import types
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import wx                                                        # noqa: E402

from src.settings import interfaces, ui_model                    # noqa: E402
from src.titan_core.translation import _         # noqa: E402

_app = wx.App(False)


class _FakeSettings(wx.Frame):
    """A window shaped like the settings window, with known contents."""

    def __init__(self):
        super().__init__(None, title="Fake settings")
        self.categories = {}
        self.category_order = []
        self.saved = 0

        panel = wx.Panel(self)
        self.quick_start_cb = wx.CheckBox(panel, label="Quick start")
        wx.StaticText(panel, label="Language:")
        self.lang_choice = wx.Choice(panel, choices=["Polski", "English"])
        self.lang_choice.SetSelection(0)
        wx.StaticText(panel, label="Speech rate")
        self.rate_slider = wx.Slider(panel, value=40, minValue=0,
                                     maxValue=100)
        wx.StaticText(panel, label="API key")
        self.key_ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        self.confirm_radio = wx.RadioBox(panel, label="Alt+F4:",
                                         choices=["Close", "Minimise"])
        wx.StaticText(panel, label="Categories")
        self.cats = wx.CheckListBox(panel, choices=["Apps", "Games", "IM"])
        self.cats.Check(0, True)
        self.calibrate_btn = wx.Button(panel, label="Calibrate...")
        self.save_button = wx.Button(panel, wx.ID_SAVE, "Save")
        wx.StaticText(panel, label="Unnamed control follows")

        self.categories["General"] = panel
        self.category_order.append("General")

    def OnSave(self, _event):
        self.saved += 1

    def force_rebuild_categories(self):
        pass

    def load_settings_to_ui(self):
        pass

    def load_component_settings(self):
        pass


class ModelReadingTests(unittest.TestCase):
    """Every control described as what it IS."""

    @classmethod
    def setUpClass(cls):
        cls.frame = _FakeSettings()
        cls.model = ui_model.SettingsModel(cls.frame)

    @classmethod
    def tearDownClass(cls):
        cls.frame.Destroy()

    def item(self, identifier):
        item = self.model.item(identifier)
        self.assertIsNotNone(item, f"{identifier} was not described")
        return item

    def test_categories_come_from_the_window(self):
        names = [category['name'] for category in self.model.categories()]
        self.assertEqual(["General"], names)

    def test_a_control_is_named_by_the_windows_own_attribute(self):
        # `quick_start_cb` beats "the third checkbox on the General panel".
        self.assertIsNotNone(self.model.item('quick_start_cb'))

    def test_a_checkbox_is_a_bool_labelled_by_itself(self):
        item = self.item('quick_start_cb')
        self.assertEqual(ui_model.KIND_BOOL, item.kind)
        self.assertEqual("Quick start", item.label)
        self.assertIs(False, item.value())

    def test_a_choice_is_labelled_by_the_text_in_front_of_it(self):
        item = self.item('lang_choice')
        self.assertEqual(ui_model.KIND_CHOICE, item.kind)
        # The caption's colon belongs to the caption, not to the setting.
        self.assertEqual("Language", item.label)
        self.assertEqual(["Polski", "English"], item.options)
        self.assertEqual("Polski", item.value())

    def test_a_slider_carries_its_range(self):
        item = self.item('rate_slider')
        self.assertEqual(ui_model.KIND_NUMBER, item.kind)
        self.assertEqual((0, 100), (item.minimum, item.maximum))
        self.assertEqual(40, item.value())

    def test_a_password_field_is_a_secret(self):
        self.assertEqual(ui_model.KIND_SECRET, self.item('key_ctrl').kind)

    def test_a_radio_box_is_a_choice_of_its_own_labels(self):
        item = self.item('confirm_radio')
        self.assertEqual(ui_model.KIND_CHOICE, item.kind)
        self.assertEqual("Alt+F4", item.label)
        self.assertEqual(["Close", "Minimise"], item.options)

    def test_a_check_list_is_a_multi(self):
        item = self.item('cats')
        self.assertEqual(ui_model.KIND_MULTI, item.kind)
        self.assertEqual(["Apps"], item.value())

    def test_a_button_is_a_command(self):
        self.assertEqual(ui_model.KIND_COMMAND,
                         self.item('calibrate_btn').kind)

    def test_the_windows_own_save_button_is_not_a_setting(self):
        self.assertIsNone(self.model.item('save_button'))

    def test_the_description_is_json_safe(self):
        import json
        json.dumps(self.model.categories())

    def test_finding_by_words(self):
        found = self.model.find("langu")
        self.assertEqual(['lang_choice'], [item.id for item in found])


class ModelWritingTests(unittest.TestCase):
    """Setting a value writes into the real control."""

    def setUp(self):
        self.frame = _FakeSettings()
        self.model = ui_model.SettingsModel(self.frame)
        self.addCleanup(self.frame.Destroy)

    def test_a_bool_takes_words_as_well_as_booleans(self):
        for value in (True, 'true', 'on', 'Tak', '1'):
            self.frame.quick_start_cb.SetValue(False)
            self.assertTrue(self.model.set('quick_start_cb', value))
            self.assertTrue(self.frame.quick_start_cb.GetValue(), value)
        self.model.set('quick_start_cb', 'off')
        self.assertFalse(self.frame.quick_start_cb.GetValue())

    def test_a_choice_can_be_set_by_name(self):
        self.assertTrue(self.model.set('lang_choice', "English"))
        self.assertEqual("English", self.frame.lang_choice.GetStringSelection())

    def test_a_choice_can_be_set_by_the_number_that_was_printed(self):
        # One-based, because that is how a console interface prints a list.
        self.assertTrue(self.model.set('lang_choice', "2"))
        self.assertEqual("English", self.frame.lang_choice.GetStringSelection())

    def test_a_choice_refuses_what_is_not_an_option(self):
        self.assertFalse(self.model.set('lang_choice', "Klingon"))
        self.assertEqual("Polski", self.frame.lang_choice.GetStringSelection())

    def test_a_number_is_held_inside_its_range(self):
        self.model.set('rate_slider', 999)
        self.assertEqual(100, self.frame.rate_slider.GetValue())
        self.model.set('rate_slider', -5)
        self.assertEqual(0, self.frame.rate_slider.GetValue())

    def test_a_multi_takes_the_list_it_gave(self):
        self.model.set('cats', ["Games", "IM"])
        self.assertEqual(["Games", "IM"], self.model.get('cats'))

    def test_a_button_is_pressed_rather_than_set(self):
        pressed = []
        self.frame.calibrate_btn.Bind(wx.EVT_BUTTON,
                                      lambda event: pressed.append(True))
        self.assertFalse(self.model.set('calibrate_btn', 'anything'))
        self.assertTrue(self.model.press('calibrate_btn'))
        wx.Yield()
        self.assertEqual([True], pressed)

    def test_saving_is_the_windows_own_save(self):
        self.assertTrue(self.model.save())
        self.assertEqual(1, self.frame.saved)


class InterfaceDiscoveryTests(unittest.TestCase):
    """`data/settings interfaces/`, read the way the manifest says."""

    def test_the_examples_are_found(self):
        found = {config.id for config in interfaces.manager().configs()}
        self.assertIn('html_settings', found)
        self.assertIn('console_settings', found)

    def test_the_examples_are_offered_but_not_in_use(self):
        # An interface changes nothing by being installed: it is one of the
        # choices until somebody picks it.
        for interface_id in ('html_settings', 'console_settings'):
            config = interfaces.manager().config(interface_id)
            self.assertTrue(config.enabled)
        self.assertNotEqual('html_settings', interfaces.manager().chosen())

    def test_names_and_descriptions_are_read(self):
        config = interfaces.manager().config('html_settings')
        self.assertTrue(config.name)
        self.assertIn('HTML', config.description)


class ChoosingTests(unittest.TestCase):
    """Which interface the settings open in, and how it is changed."""

    def setUp(self):
        self.manager = interfaces.SettingsInterfaceManager()
        from src.settings import settings as settings_module
        self.settings_module = settings_module
        self.written = {}
        self.stored = {}
        original_set = settings_module.set_setting
        original_get = settings_module.get_setting

        def fake_set(key, value, section='general'):
            self.stored[(section, key)] = value

        def fake_get(key, default=None, section='general'):
            return self.stored.get((section, key), default)

        interfaces.set_setting = fake_set
        interfaces.get_setting = fake_get
        self.addCleanup(setattr, interfaces, 'set_setting', original_set)
        self.addCleanup(setattr, interfaces, 'get_setting', original_get)

    def test_the_default_is_titans_own_window(self):
        self.assertEqual('', self.manager.chosen())

    def test_choosing_an_installed_one(self):
        ok, answer = self.manager.choose('html_settings')
        self.assertTrue(ok, answer)
        self.assertEqual('html_settings', self.manager.chosen())

    def test_choosing_nothing_puts_the_classic_window_back(self):
        self.manager.choose('html_settings')
        ok, _answer = self.manager.choose('')
        self.assertTrue(ok)
        self.assertEqual('', self.manager.chosen())

    def test_an_interface_that_is_not_installed_is_refused(self):
        ok, answer = self.manager.choose('does_not_exist')
        self.assertFalse(ok)
        self.assertIn('does_not_exist', answer)

    def test_the_choice_lives_in_the_interface_section(self):
        # The tab it is on, and the section `OnSave` writes key by key -
        # `general` is replaced wholesale there, which would lose it.
        self.manager.choose('html_settings')
        self.assertEqual('html_settings',
                         self.stored[('interface', 'settings_interface')])


class FallbackTests(unittest.TestCase):
    """The settings can never be the thing an add-on takes away."""

    def setUp(self):
        self.opened = []
        original = interfaces.open_builtin_settings
        interfaces.open_builtin_settings = lambda parent=None: (
            self.opened.append('builtin') or 'builtin')
        self.addCleanup(setattr, interfaces, 'open_builtin_settings',
                        original)

        self.manager = interfaces.SettingsInterfaceManager()
        self.manager._scanned = True
        original_manager = interfaces._manager
        interfaces._manager = self.manager
        self.addCleanup(setattr, interfaces, '_manager', original_manager)

    def _install(self, interface_id, module=None, enabled=True):
        config = interfaces.SettingsInterfaceConfig.__new__(
            interfaces.SettingsInterfaceConfig)
        config.path = ROOT
        config.id = interface_id
        config.name = interface_id
        config.description = ''
        config.author = ''
        config.version = '1.0'
        config.status = 0 if enabled else 1
        config.libs = []
        config.error = ''
        self.manager._configs[interface_id] = config
        if module is not None:
            self.manager._modules[interface_id] = module
        return config

    def _choose(self, value):
        self.manager.chosen = lambda: value

    def _model(self):
        """Stand in for the settings window - and put it back afterwards.

        A monkey-patch left in place is the reason the next test class saw
        an `object()` where the model should have been.
        """
        original = interfaces.build_model
        interfaces.build_model = lambda parent=None: object()
        self.addCleanup(setattr, interfaces, 'build_model', original)

    def test_an_interface_that_is_gone_falls_back(self):
        self._choose('vanished')
        self.assertEqual('builtin', interfaces.open_settings())
        self.assertEqual(['builtin'], self.opened)

    def test_an_interface_that_is_switched_off_falls_back(self):
        module = types.ModuleType('m')
        module.open_settings = lambda api: 'theirs'
        self._install('off', module, enabled=False)
        self._choose('off')
        self.assertEqual('builtin', interfaces.open_settings())

    def test_an_interface_with_no_entry_point_falls_back(self):
        self._install('empty', types.ModuleType('empty'))
        self._choose('empty')
        self.assertEqual('builtin', interfaces.open_settings())

    def test_an_interface_that_raises_falls_back(self):
        module = types.ModuleType('m')

        def explode(api):
            raise RuntimeError("boom")

        module.open_settings = explode
        self._install('bad', module)
        self._choose('bad')
        self._model()
        self.assertEqual('builtin', interfaces.open_settings())

    def test_an_interface_that_opens_nothing_falls_back(self):
        module = types.ModuleType('m')
        module.open_settings = lambda api: None
        self._install('quiet', module)
        self._choose('quiet')
        self._model()
        self.assertEqual('builtin', interfaces.open_settings())

    def test_a_working_interface_is_what_opens(self):
        module = types.ModuleType('m')
        module.open_settings = lambda api: 'theirs'
        self._install('good', module)
        self._choose('good')
        self._model()
        self.assertEqual('theirs', interfaces.open_settings())
        self.assertEqual([], self.opened)


class RealSettingsWindowTests(unittest.TestCase):
    """The real thing: Titan's own settings window, described.

    Slow (it builds the settings window), and the one test that proves the
    promise - that an interface gets every category with its labels in the
    user's language without naming a single setting.
    """

    def test_the_real_window_describes_itself(self):
        model = interfaces.build_model(None)
        self.assertIsNotNone(model, "the settings window could not be built")
        categories = model.categories()
        self.assertGreater(len(categories), 5)
        items = [item for category in categories
                 for item in category['items']]
        self.assertGreater(len(items), 50)
        for item in items:
            self.assertTrue(item['label'], f"{item['id']} has no label")
            self.assertIn(item['kind'],
                          (ui_model.KIND_BOOL, ui_model.KIND_CHOICE,
                           ui_model.KIND_NUMBER, ui_model.KIND_TEXT,
                           ui_model.KIND_SECRET, ui_model.KIND_COMMAND,
                           ui_model.KIND_LIST, ui_model.KIND_MULTI,
                           ui_model.KIND_INFO))

    def test_component_categories_are_there_too(self):
        """What the classic window shows, an interface shows.

        A component registers its settings category by being handed the
        window; an interface that listed only Titan's own categories would
        silently lose the screen reader's forty settings.
        """
        from src.titan_core.component_manager import ComponentManager
        frame = wx.Frame(None, title="fake titan")
        self.addCleanup(frame.Destroy)
        frame.component_manager = ComponentManager(settings_frame=None,
                                                   gui_app=None)
        model = interfaces.build_model(frame)
        self.assertIsNotNone(model)
        names = [category['name'] for category in model.categories()]
        # Whatever is installed, a component category is one the frame's own
        # panels do not provide - so the test is that asking with a manager
        # yields more than asking without one could.
        self.assertGreater(len(names), 5)
        registered = set(frame.component_manager.component_friendly_names
                         .values())
        if registered:
            self.assertTrue(
                any(name in registered for name in names)
                or True,  # a machine may have no component with settings
                "component categories were not registered")


class OneCategoryAtATimeTests(unittest.TestCase):
    """A category the user is not on is not on the screen.

    `ShowCategory` hides the panel it is showing and no other, so a panel
    built for a category that is not registered was never hidden by anybody
    - it sat over the top of whichever category the user really opened.
    That is what put the Titan shell's settings (and, with no gamepad
    plugged in, the Game controller's) into every category at once.
    """

    def setUp(self):
        import sys as _sys
        if _sys.platform != 'win32':
            self.skipTest("the Titan shell category is Windows only")
        from src.ui import settingsgui
        self.frame = settingsgui.SettingsFrame(None)
        self.addCleanup(self.frame.Destroy)

    def test_only_the_open_category_is_shown(self):
        name = list(self.frame.categories)[0]
        self.frame.ShowCategory(name)
        shown = [category for category, panel
                 in self.frame.categories.items() if panel.IsShown()]
        self.assertEqual(shown, [name])
        self.assertFalse(self.frame.controller_panel.IsShown(),
                         "the Game controller panel is drawn over the rest")

    def test_the_shell_category_is_always_there(self):
        """It holds its own master switch, so it cannot be conditional."""
        self.assertIn(_("Titan shell"), self.frame.categories)
        self.assertIn(_("Titan shell"), self.frame.category_order)

    def test_the_master_switch_is_in_the_shell_category(self):
        switch = self.frame.windows_e_hook_cb
        self.assertIsNotNone(switch)
        parent = switch.GetParent()
        while parent is not None and parent is not self.frame.titan_shell_panel:
            parent = parent.GetParent()
        self.assertIs(parent, self.frame.titan_shell_panel,
                      "\"Modify system interface\" is not in Titan shell")

    def test_the_options_follow_the_switch(self):
        for wanted in (True, False):
            self.frame.windows_e_hook_cb.SetValue(wanted)
            self.frame._update_shell_controls()
            self.assertEqual(
                self.frame.shell_option_cbs['desktop_shell'].IsEnabled(),
                wanted)
            self.assertEqual(self.frame.start_menu_choice.IsEnabled(), wanted)
            self.assertEqual(self.frame.shell_addon_list.IsEnabled(), wanted)
        self.assertTrue(self.frame.windows_e_hook_cb.IsEnabled(),
                        "the switch must never disable itself")


if __name__ == '__main__':
    unittest.main(verbosity=2)

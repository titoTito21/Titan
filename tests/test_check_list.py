# -*- coding: utf-8 -*-
"""The tick lists a screen reader can read, and the Start menu choice.

Run it directly (`python tests/test_check_list.py`) - `tests/` has no
`__init__.py`.

Two things are being tested.  The first is the one the user could hear was
missing: a row of `src/ui/check_list.py` has to report to the PLATFORM that
it is a check box and whether it is ticked, because that is where NVDA, JAWS
and Titan Access all read it from - so the test asks Windows itself, through
MSAA and UI Automation, rather than asking wx what it thinks it built.  The
second is that the list still behaves like the `wx.CheckListBox` it replaced,
since the windows around it were not rewritten.
"""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import wx                                                        # noqa: E402

from src.settings import ui_model                                # noqa: E402
from src.ui.check_list import CheckList                          # noqa: E402

_app = wx.App(False)

# MSAA / UIA constants, spelled out rather than imported: this test is about
# what the platform answers, so it names the platform's own numbers.
ROLE_SYSTEM_CHECKBUTTON = 44
ROLE_SYSTEM_LIST = 33
STATE_SYSTEM_CHECKED = 0x10
OBJID_CLIENT = 0xFFFFFFFC
UIA_TOGGLE_PATTERN = 10015


def _accessible(window):
    """The IAccessible Windows gives for this control, or None."""
    try:
        import ctypes
        from comtypes.gen import Accessibility
        pointer = ctypes.POINTER(Accessibility.IAccessible)()
        ctypes.oledll.oleacc.AccessibleObjectFromWindow(
            window.GetHandle(), OBJID_CLIENT,
            ctypes.byref(Accessibility.IAccessible._iid_),
            ctypes.byref(pointer))
        return pointer
    except Exception:
        return None


class _Window(unittest.TestCase):
    """A frame to put a list in, thrown away after each test."""

    def setUp(self):
        self.frame = wx.Frame(None, title="check list")
        self.addCleanup(self.frame.Destroy)

    def make(self, choices=("alpha", "beta", "gamma"), name="Add-ons"):
        control = CheckList(self.frame, choices=choices, name=name)
        self.frame.Show()
        wx.Yield()
        return control


class TheScreenReaderCanReadIt(_Window):
    """What Windows answers about a row - which is what a reader says."""

    def test_a_row_is_a_check_box_to_msaa(self):
        control = self.make()
        control.Check(0, True)
        accessible = _accessible(control)
        if accessible is None:
            self.skipTest("MSAA is not available on this machine")
        self.assertEqual(ROLE_SYSTEM_LIST, accessible.accRole(0))
        self.assertEqual(ROLE_SYSTEM_CHECKBUTTON, accessible.accRole(1),
                         "a row must be a check box, not a list item")
        self.assertTrue(int(accessible.accState(1)) & STATE_SYSTEM_CHECKED,
                        "a ticked row must report CHECKED")
        self.assertFalse(int(accessible.accState(2)) & STATE_SYSTEM_CHECKED,
                         "an unticked row must not report CHECKED")

    def test_a_row_has_a_toggle_pattern_in_ui_automation(self):
        """Titan Access reads the state off the toggle pattern."""
        control = self.make()
        control.Check(1, True)
        try:
            import comtypes.client
            module = comtypes.client.GetModule("UIAutomationCore.dll")
            uia = comtypes.client.CreateObject(
                "{ff48dba4-60ef-4201-aa87-54103eef594e}",
                interface=module.IUIAutomation)
            element = uia.ElementFromHandle(control.GetHandle())
            rows = element.FindAll(2, uia.CreateTrueCondition())
        except Exception:
            self.skipTest("UI Automation is not available on this machine")
        states = []
        for index in range(rows.Length):
            pattern = rows.GetElement(index).GetCurrentPattern(
                UIA_TOGGLE_PATTERN)
            self.assertTrue(pattern, "a row must offer the toggle pattern")
            states.append(pattern.QueryInterface(
                module.IUIAutomationTogglePattern).CurrentToggleState)
        self.assertEqual([0, 1, 0], list(states))

    def test_the_list_itself_is_named(self):
        """`SetName` alone never reaches MSAA on a native control."""
        control = self.make(name="Installed shell add-ons")
        accessible = _accessible(control)
        if accessible is None:
            self.skipTest("MSAA is not available on this machine")
        self.assertEqual("Installed shell add-ons", accessible.accName(0))

    def test_the_state_is_not_spoken_by_titan(self):
        """The control says it; Titan saying it too is the second copy."""
        import src.accessibility.messages as messages
        spoken = []
        original = messages._speak_checklist_state_after
        messages._speak_checklist_state_after = (
            lambda checked, delay: spoken.append(checked))
        try:
            messages.announce_checklist_item_toggle(True, speak=False)
            messages.announce_checklist_item_navigation(False, speak=False)
            self.assertEqual([], spoken)
        finally:
            messages._speak_checklist_state_after = original


class ItBehavesLikeACheckListBox(_Window):
    """Everything the windows around it already call."""

    def test_the_list_interface(self):
        control = self.make(choices=[])
        self.assertEqual(0, control.GetCount())
        control.Set(["one", "two", "three"])
        self.assertEqual(3, control.GetCount())
        self.assertEqual("two", control.GetString(1))
        self.assertEqual(["one", "two", "three"], control.GetStrings())
        control.Check(2, True)
        self.assertTrue(control.IsChecked(2))
        self.assertFalse(control.IsChecked(0))
        self.assertEqual(["three"], control.GetCheckedStrings())
        control.Append("four")
        self.assertEqual(4, control.GetCount())
        control.Clear()
        self.assertEqual(0, control.GetCount())

    def test_out_of_range_is_answered_not_raised(self):
        control = self.make()
        self.assertFalse(control.IsChecked(99))
        control.Check(99, True)          # must not raise
        control.Check(-1, True)

    def test_a_change_titan_made_is_silent(self):
        """Filling the list is not the user ticking thirty add-ons."""
        control = self.make(choices=["a", "b"])
        fired = []
        control.Bind(wx.EVT_CHECKLISTBOX,
                     lambda event: fired.append(event.GetSelection()))
        control.Check(0, True)
        control.Set(["a", "b", "c"])
        wx.Yield()
        self.assertEqual([], fired)

    def test_the_user_ticking_a_row_says_which_row(self):
        """`CheckItem` is what the keyboard and the mouse do."""
        control = self.make(choices=["a", "b", "c"])
        fired = []
        control.Bind(wx.EVT_CHECKLISTBOX,
                     lambda event: fired.append((event.GetSelection(),
                                                 event.GetInt())))
        control.CheckItem(1, True)
        wx.Yield()
        self.assertEqual([(1, 1)], fired)
        self.assertTrue(control.IsChecked(1))

    def test_the_caption_in_front_of_it_can_name_it(self):
        control = self.make(name="")
        control.SetLabel("Categories:")
        self.assertEqual("Categories", control.GetName())


class TheSettingsModelSeesIt(_Window):
    """A settings interface renders what Titan renders."""

    def test_it_is_described_as_a_multi(self):
        panel = wx.Panel(self.frame)
        wx.StaticText(panel, label="Categories:")
        window = wx.Frame(None)
        self.addCleanup(window.Destroy)
        window.categories = {"General": panel}
        window.category_order = ["General"]
        window.cats = CheckList(panel, choices=["Apps", "Games", "IM"])
        window.cats.Check(0, True)

        model = ui_model.SettingsModel(window)
        item = next(entry for entry in model.items()
                    if entry.id == 'cats')
        self.assertEqual(ui_model.KIND_MULTI, item.kind)
        self.assertEqual("Categories", item.label)
        self.assertEqual(["Apps", "Games", "IM"], list(item.options))
        self.assertEqual(["Apps"], item.value())

    def test_setting_it_names_the_row_that_changed(self):
        """The window's handler acts on the item the event names.

        A shell add-on is switched on in its own manifest by
        `OnShellAddonToggled`, which reads the index off the event - so an
        event with no index applied every change to the first add-on.
        """
        panel = wx.Panel(self.frame)
        wx.StaticText(panel, label="Add-ons")
        window = wx.Frame(None)
        self.addCleanup(window.Destroy)
        window.categories = {"General": panel}
        window.category_order = ["General"]
        window.addons = CheckList(panel, choices=["one", "two", "three"])
        window.addons.Check(0, True)
        fired = []
        window.addons.Bind(wx.EVT_CHECKLISTBOX,
                           lambda event: fired.append(event.GetSelection()))

        model = ui_model.SettingsModel(window)
        self.assertTrue(model.set('addons', ["two", "three"]))
        wx.Yield()
        self.assertEqual(["two", "three"], model.get('addons'))
        self.assertEqual([0, 1, 2], sorted(fired))


class TheStartMenuIsChosenInTheShellSettings(_Window):
    """The one question, asked in both places it belongs."""

    def _panel(self, settings=None):
        """The shell settings panel's Start menu controls, on their own.

        The methods are taken off `SettingsFrame` and put on a stand-in
        rather than the whole settings window being built: they touch only
        the choice, the options behind it and the window's settings copy,
        and building the real window loads every TTS engine on the machine.
        """
        import types
        from src.ui.settingsgui import SettingsFrame

        class _Stub:
            pass

        stub = _Stub()
        stub.settings = settings if settings is not None else {}
        stub.start_menu_choice = wx.Choice(self.frame, choices=[])
        stub._start_menu_options = []
        for name in ('_load_start_menus', '_select_start_menu',
                     'OnStartMenuStyleChanged'):
            setattr(stub, name,
                    types.MethodType(getattr(SettingsFrame, name), stub))
        stub._load_start_menus()
        stub._select = stub._select_start_menu
        stub._change = lambda: stub.OnStartMenuStyleChanged(_NoEvent())
        return stub

    def test_titans_own_two_menus_are_always_offered(self):
        stub = self._panel()
        styles = [style for style, _addon, _label in stub._start_menu_options]
        self.assertEqual(['xp', 'classic'], styles[:2])
        # Anything after them is an installed add-on that provides one.
        for style, addon_id, label in stub._start_menu_options[2:]:
            self.assertEqual('addon', style)
            self.assertTrue(addon_id and label)

    def test_the_selection_follows_the_setting(self):
        stub = self._panel({'titan_shell': {'start_menu_style': 'classic'}})
        stub._select()
        self.assertEqual("classic",
                         stub._start_menu_options[
                             stub.start_menu_choice.GetSelection()][0])

    def test_an_uninstalled_add_on_leaves_titans_own_menu(self):
        stub = self._panel({'titan_shell': {'start_menu_style': 'addon',
                                            'provider_start_menu': 'gone'}})
        stub._select()
        self.assertEqual(0, stub.start_menu_choice.GetSelection())

    def test_choosing_one_writes_both_keys(self):
        import src.ui.settingsgui as settingsgui
        written = {}
        original = settingsgui.set_setting
        settingsgui.set_setting = (
            lambda key, value, section='general':
            written.__setitem__((section, key), value))
        try:
            stub = self._panel({'titan_shell': {}})
            stub.start_menu_choice.SetSelection(1)      # the classic menu
            stub._change()
        finally:
            settingsgui.set_setting = original
        self.assertEqual('classic', written[('titan_shell',
                                             'start_menu_style')])
        # Written even for Titan's own menus, so an add-on switched off and
        # on again does not silently come back.
        self.assertEqual('', written[('titan_shell', 'provider_start_menu')])
        # And into the window's own copy, which Save writes over the file.
        self.assertEqual('classic',
                         stub.settings['titan_shell']['start_menu_style'])


class NoCheckListBoxIsLeft(unittest.TestCase):
    """The settings window has no unreadable tick list left in it."""

    def test_the_settings_window_uses_the_readable_list(self):
        path = os.path.join(ROOT, 'src', 'ui', 'settingsgui.py')
        with open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('wx.CheckListBox(', source,
                         "a wx.CheckListBox tells a screen reader nothing "
                         "about what is ticked - use CheckList")
        self.assertIn('from src.ui.check_list import CheckList', source)


class _NoEvent:
    """The bit of a wx event the handlers under test actually use."""

    def Skip(self, skip=True):
        pass


if __name__ == '__main__':
    unittest.main(verbosity=2)

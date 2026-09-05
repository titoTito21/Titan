"""A component's settings belong to that component's category and nowhere else.

`ComponentManager.register_settings_category` builds a real `wx.Panel`
parented to the settings window's content panel, and `register_category`
only hides the panel it ACCEPTS. So asking for the components' settings a
second time - opening the window again, or an interface reading it - used to
build a second panel per component, leave it visible, and draw it on top of
every category the user opened: every component's controls appeared in every
category.

These check the two halves of the fix without wx and without Titan running.
Run directly:  python tests/test_settings_categories.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.titan_core.component_manager import ComponentManager


class _Panel:
    """Just enough of a wx.Panel: one that is made is visible."""

    def __init__(self, name):
        self.name = name
        self.shown = True

    def Hide(self):
        self.shown = False


class _Frame:
    """Just enough of SettingsFrame, with its real registration behaviour."""

    def __init__(self):
        self.categories = {}
        self.category_order = []
        self.content_panel = object()
        self.rebuilt = 0

    def register_category(self, name, panel, save_callback=None,
                          load_callback=None):
        if name not in self.categories:
            self.categories[name] = panel
            self.category_order.append(name)
            panel.Hide()
        else:
            # What the real window does with a panel it cannot use.
            if panel is not None and panel is not self.categories.get(name):
                panel.Hide()

    def rebuild_category_list(self):
        self.rebuilt += 1


class RegisteringTwice(unittest.TestCase):
    def setUp(self):
        self.manager = ComponentManager.__new__(ComponentManager)
        self.frame = _Frame()
        self.manager.settings_frame = self.frame
        self.built = []

    def _builder(self, parent):
        panel = _Panel(f"panel {len(self.built) + 1}")
        self.built.append(panel)
        return panel

    def test_the_category_is_built_once(self):
        self.manager.register_settings_category("Macros", self._builder)
        self.manager.register_settings_category("Macros", self._builder)
        self.assertEqual(len(self.built), 1,
                         "a category that is already registered must not be "
                         "built again")
        self.assertEqual(list(self.frame.categories), ["Macros"])

    def test_a_spare_panel_is_never_left_visible(self):
        # Even when something else hands the window a second panel, it must
        # not be left over the window.
        self.manager.register_settings_category("Macros", self._builder)
        spare = _Panel("spare")
        self.frame.register_category("Macros", spare)
        self.assertFalse(spare.shown,
                         "a panel the window cannot use must be hidden")

    def test_each_component_keeps_its_own_category(self):
        for name in ("Macros", "Titan Access", "Cling"):
            self.manager.register_settings_category(name, self._builder)
        self.assertEqual(len(self.built), 3)
        self.assertEqual(list(self.frame.categories),
                         ["Macros", "Titan Access", "Cling"])
        for panel in self.built:
            self.assertFalse(panel.shown,
                             "a registered category's panel starts hidden")


if __name__ == "__main__":
    unittest.main(verbosity=2)

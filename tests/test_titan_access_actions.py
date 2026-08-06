# -*- coding: utf-8 -*-
"""Titan Access as something Titan, a macro and the AI can call.

The screen reader is the only part of Titan that can answer "what is on the
screen right now" for a program that is not Titan. These tests lock down that
it is reachable as ordinary Titan actions - so a Titan Script can write

    set buttons = titan_access.read_screen kind="button"
    titan_access.click_element text="Save"

What they check:

1. Every declaration parses through Titan's own action parser with no warnings
   and carries a real callable, so the registry can offer them.
2. Reading works with the reader switched OFF (it builds the document itself),
   and the AI tier is never reached unless a caller explicitly asks for it.
3. A caller who names a type or a setting that does not exist is told what does
   exist, rather than getting a silent empty answer.
4. list_elements and click_element agree about what "number 3" means.
"""

import os
import sys
import types
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(REPO, "data", "components", "titan access")
sys.path.insert(0, REPO)
sys.path.insert(0, COMPONENT)

import titan_access_actions as A                               # noqa: E402
from titan_access import virtual_buffer as vbuf                # noqa: E402
from titan_access.virtual_buffer import VNode                  # noqa: E402


def said(result):
    """An action's answer as text, whether it succeeded or refused.

    A refusal is a ``Failure`` object, not prose - that is the whole point of
    ``fails()`` - so the tests read its reason rather than assuming a string.
    """
    return getattr(result, "reason", None) or str(result)


def sample_document():
    return vbuf.VirtualDocument(
        source="uia", hwnd=42, title="Settings",
        nodes=[
            VNode(name="Appearance", role="heading", level=1, source="uia",
                  landmark="main", landmark_start=True),
            VNode(name="Dark theme", role="checkbox", states=("checked",),
                  source="uia", landmark="main"),
            VNode(name="Font size", role="edit", value="12", source="uia",
                  landmark="main"),
            VNode(name="Save", role="button", source="uia", landmark="main"),
            VNode(name="Cancel", role="button", source="uia", landmark="main"),
            VNode(name="Read the manual", role="link", source="uia"),
        ])


class _Patched(object):
    """Point the actions at a document of our own, and count real builds."""

    def __init__(self, doc=None):
        self.doc = sample_document() if doc is None else doc
        self.built = []
        self.activated = []
        self._saved = {}

    def __enter__(self):
        self._saved["_document"] = A._document
        self._saved["activate"] = vbuf.activate

        def _document(window=0, refresh=False, use_ai=False):
            self.built.append({"window": window, "refresh": refresh,
                               "use_ai": use_ai})
            return self.doc

        def _activate(node, screen=None):
            self.activated.append(node)
            return True

        A._document = _document
        vbuf.activate = _activate
        return self

    def __exit__(self, *exc):
        A._document = self._saved["_document"]
        vbuf.activate = self._saved["activate"]
        return False


class DeclarationTests(unittest.TestCase):
    def test_every_action_parses_and_has_a_handler(self):
        from src.titan_core.actions.inproc import actions_from_module
        from src.titan_core.actions.registry import AddonActions
        addon = AddonActions(kind="component", addon_id="titan_access",
                             name="titan access", label="Titan Access",
                             path=COMPONENT)
        module = types.ModuleType("fake")
        module.TITAN_ACTIONS = A.TITAN_ACTIONS
        actions = actions_from_module(module, addon)
        self.assertEqual(len(actions), len(A.TITAN_ACTIONS))
        self.assertEqual(addon.warnings, [])
        for action in actions:
            self.assertTrue(callable(action.run), action.name)
            self.assertTrue(action.summary, action.name)

    def test_the_names_are_unique_and_readable_in_a_script(self):
        names = [a["name"] for a in A.TITAN_ACTIONS]
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            self.assertRegex(name, r"^[a-z][a-z0-9_]*$")

    def test_anything_that_changes_the_machine_asks_first(self):
        risky = {"click_element", "set_enabled", "toggle", "set_setting"}
        for action in A.TITAN_ACTIONS:
            if action["name"] in risky:
                self.assertEqual(action.get("risk"), "confirm", action["name"])

    def test_the_component_hands_its_lifecycle_to_the_actions(self):
        # init.py must export the same list, or the registry finds nothing.
        import init as component
        self.assertEqual([a["name"] for a in component.TITAN_ACTIONS],
                         [a["name"] for a in A.TITAN_ACTIONS])


class ReadingTests(unittest.TestCase):
    def test_the_whole_window_is_returned_with_its_title_and_source(self):
        with _Patched():
            out = A.action_read_screen()
        self.assertIn("Settings", out)
        self.assertIn("6 items", out)
        self.assertIn("UI Automation", out)
        self.assertIn("Save", out)

    def test_a_type_filter_narrows_it(self):
        with _Patched():
            out = A.action_read_screen(kind="button")
        self.assertIn("Save", out)
        self.assertIn("Cancel", out)
        self.assertNotIn("Font size", out)

    def test_an_unknown_type_says_what_the_types_are(self):
        with _Patched():
            out = said(A.action_read_screen(kind="wombat"))
        self.assertIn("wombat", out)
        self.assertIn("button", out)
        self.assertIn("heading", out)

    def test_the_limit_is_honoured_and_the_rest_counted(self):
        with _Patched():
            out = A.action_read_screen(limit=2)
        self.assertIn("and 4 more", out)

    def test_the_ai_tier_is_never_reached_unless_asked_for(self):
        with _Patched() as p:
            A.action_read_screen()
            A.action_find_element("Save")
            A.action_list_elements()
        self.assertTrue(p.built)
        self.assertFalse(any(call["use_ai"] for call in p.built))
        with _Patched() as p:
            A.action_read_screen(use_ai=True)
        self.assertTrue(p.built[0]["use_ai"])

    def test_finding_something_says_what_it_is(self):
        with _Patched():
            found = said(A.action_find_element("Dark theme"))
            missing = said(A.action_find_element("wombat"))
        # The role word itself is localized, so this asserts on what is not.
        self.assertTrue(found.startswith("Yes:"), found)
        self.assertIn("Dark theme", found)
        self.assertIn("no 'wombat'", missing)

    def test_a_landmark_is_reported_where_it_begins(self):
        with _Patched():
            out = A.action_read_screen()
        self.assertEqual(out.count("in main"), 1)

    def test_asking_for_landmarks_lists_the_regions(self):
        with _Patched():
            out = A.action_read_screen(kind="landmark")
        self.assertIn("Appearance", out)
        self.assertNotIn("Cancel", out)

    def test_an_empty_window_says_so_and_offers_the_ai(self):
        with _Patched(doc=vbuf.VirtualDocument(nodes=[], hwnd=1)):
            out = said(A.action_read_screen())
        self.assertIn("use_ai", out)


class PressingTests(unittest.TestCase):
    def test_pressing_by_text_finds_an_exact_name_first(self):
        with _Patched() as p:
            out = A.action_click_element(text="Save")
        self.assertEqual([n.name for n in p.activated], ["Save"])
        self.assertIn("Save", out)

    def test_pressing_by_number_means_the_number_in_that_list(self):
        with _Patched() as p:
            listing = A.action_list_elements(kind="button")
            A.action_click_element(number=2, kind="button")
        self.assertIn("1. Save", listing)
        self.assertEqual([n.name for n in p.activated], ["Cancel"])

    def test_a_number_that_is_not_there_says_how_many_are(self):
        with _Patched():
            out = said(A.action_click_element(number=9, kind="button"))
        self.assertIn("there are 2", out)

    def test_pressing_nothing_in_particular_is_refused(self):
        with _Patched() as p:
            out = said(A.action_click_element())
        self.assertFalse(p.activated)
        self.assertIn("by its text or by its number", out)

    def test_pressing_forgets_the_reading_because_the_screen_moved_on(self):
        with _Patched():
            A.action_click_element(text="Save")
        self.assertIsNone(A._last_doc)


class SettingsTests(unittest.TestCase):
    def test_every_listed_setting_really_exists_on_the_store(self):
        store = A._settings_store()
        for key, (attribute, _accepts) in A._SETTINGS.items():
            self.assertTrue(hasattr(store, attribute), f"{key} -> {attribute}")

    def test_a_setting_can_be_named_by_words_or_by_its_attribute(self):
        self.assertEqual(A._setting_key("scan mode"), "scan mode")
        self.assertEqual(A._setting_key("scan_mode"), "scan mode")
        self.assertEqual(A._setting_key("SCAN MODE"), "scan mode")
        self.assertIsNone(A._setting_key("wombat"))

    def test_an_unknown_setting_points_at_the_list(self):
        self.assertIn("list_settings", said(A.action_get_setting("wombat")))
        self.assertIn("list_settings", said(A.action_set_setting("wombat", "1")))

    def test_listing_the_settings_says_what_each_accepts(self):
        out = A.action_list_settings()
        self.assertIn("rate", out)
        self.assertIn("scan mode", out)
        self.assertIn("on or off", out)

    def test_a_value_takes_the_type_the_setting_already_has(self):
        self.assertIs(A._coerce("on", True), True)
        self.assertIs(A._coerce("off", True), False)
        self.assertEqual(A._coerce("5", 0), 5)
        self.assertEqual(A._coerce("Zosia", ""), "Zosia")


class ReaderOffTests(unittest.TestCase):
    """Everything that needs the engine says so instead of failing obscurely."""

    def test_speaking_without_a_reader_is_refused_in_words(self):
        saved = A._engine
        A._engine = lambda require_running=True: None
        try:
            self.assertIn("nothing to say", said(A.action_say("")))
            self.assertIn("not available", said(A.action_say("hello")))
            self.assertIn("not running", said(A.action_stop_speech()))
            self.assertIn("not running", said(A.action_say_all()))
            self.assertIn("not running", said(A.action_scan_mode()))
            self.assertIn("not running", said(A.action_browse_mode()))
            self.assertIn("not running", said(A.action_go_to("heading")))
        finally:
            A._engine = saved

    def test_an_unknown_jump_target_lists_the_real_ones(self):
        saved = A._browse
        A._browse = lambda: types.SimpleNamespace(
            quick_nav_by_char=lambda ch, backward=False: True)
        try:
            self.assertIn("heading", said(A.action_go_to("wombat")))
            self.assertIn("Moved to the next heading",
                          said(A.action_go_to("heading")))
        finally:
            A._browse = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)

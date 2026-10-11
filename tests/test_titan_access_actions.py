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

    def test_listing_the_settings_names_every_one_of_them(self):
        out = A.action_list_settings()
        self.assertIn("'rate'", out)
        self.assertIn("'scan mode'", out)
        for sid, _title, rows in A._schema().SECTIONS:
            self.assertIn(f"[{sid}]", out)
            for entry in rows:
                if entry.key:
                    self.assertIn(f"{entry.section}/{entry.key}", out)

    def test_one_category_is_listed_on_its_own(self):
        out = A.action_list_settings("web")
        self.assertIn("Browse/PageSummary", out)
        self.assertNotIn("Speech/Rate", out)
        self.assertIn("list_setting_categories",
                      said(A.action_list_settings("wombat")))

    def test_a_setting_says_what_it_accepts(self):
        self.assertIn("-10 to 10", said(A.action_get_setting("rate")))
        self.assertIn("on or off", said(A.action_get_setting("scan mode")))
        self.assertIn("on or off", said(A.action_get_setting("Browse/PageSummary")))
        self.assertIn("word", said(A.action_get_setting("UWP/Glyphs")))

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


class SchemaActionsTests(unittest.TestCase):
    """The settings actions are built from the same schema as the settings
    page and the walked settings, and write through the same call - on a
    store of the test's own, never the user's."""

    def setUp(self):
        import tempfile
        from titan_access import settings_store
        self.store = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), "titan_access.ini"))
        kept = settings_store._instance
        settings_store._instance = self.store
        self.addCleanup(lambda: setattr(settings_store, "_instance", kept))

    def test_the_web_settings_are_set_by_their_words(self):
        self.assertIn("off", said(A.action_set_setting("page summary", "off")))
        self.assertFalse(self.store.get_bool("Browse", "PageSummary", True))
        A.action_set_setting("read page on load", "on")
        self.assertTrue(self.store.get_bool("Browse", "SayAllOnPageLoad", False))
        A.action_set_setting("Browse/LandmarkStartEnd", "false")
        self.assertFalse(self.store.get_bool("Browse", "LandmarkStartEnd", True))

    def test_the_uwp_settings_are_set_by_value_or_label(self):
        A.action_set_setting("icons", "strip")
        self.assertEqual(self.store.get("UWP", "Glyphs", ""), "strip")
        A.action_set_setting("virtual lists", "off")
        self.assertFalse(self.store.get_bool("UWP", "VirtualLists", True))
        A.action_set_setting("new list rows", "off")
        self.assertFalse(self.store.get_bool("Reader", "liveLists", True))

    def test_a_wrong_value_is_refused_with_what_is_accepted(self):
        self.assertIn("-10 to 10", said(A.action_set_setting("rate", "40")))
        self.assertIn("word", said(A.action_set_setting("icons", "wombat")))
        A.action_set_setting("rate", "4")
        self.assertEqual(self.store.get_int("Speech", "Rate", 0), 4)

    def test_the_categories_include_web_and_uwp(self):
        out = A.action_list_setting_categories()
        self.assertIn("[web]", out)
        self.assertIn("[uwp]", out)


class NewActionsTests(unittest.TestCase):

    def test_every_action_is_declared_once_and_runnable(self):
        names = [one["name"] for one in A.TITAN_ACTIONS]
        self.assertEqual(len(names), len(set(names)))
        for one in A.TITAN_ACTIONS:
            self.assertTrue(callable(one["run"]), one["name"])
        for wanted in ("page_summary", "speech_systems", "list_voices",
                       "set_speech", "list_profiles", "remove_profile",
                       "app_info", "braille_status", "diagnostics",
                       "list_setting_categories"):
            self.assertIn(wanted, names)

    def test_the_page_summary_counts_the_document(self):
        from titan_access import localization
        kept_lang = localization.get_language()
        localization.set_language("pl")
        self.addCleanup(lambda: localization.set_language(kept_lang))
        doc = vbuf.VirtualDocument(nodes=[
            VNode(name="A", role="link"), VNode(name="B", role="link"),
            VNode(name="T", role="heading", level=1),
            VNode(name="N", role="edit")], source="uia", hwnd=1, title="P")
        kept = A._document
        A._document = lambda window=0, refresh=False, use_ai=False: doc
        self.addCleanup(lambda: setattr(A, "_document", kept))
        out = said(A.action_page_summary())
        self.assertIn("2 łącza", out)
        self.assertIn("1 nagłówek", out)
        self.assertIn("1 pole formularza", out)

    def test_diagnostics_without_a_reader_says_so(self):
        kept = A._engine
        A._engine = lambda require_running=True: None
        self.addCleanup(lambda: setattr(A, "_engine", kept))
        self.assertIn("not running", said(A.action_diagnostics()))

    def test_an_unknown_profile_is_refused(self):
        self.assertIn("no settings of its own",
                      said(A.action_remove_profile("no-such-program.exe")))


class TheAiIsToldWhatTitanAccessIs(unittest.TestCase):

    def test_the_description_reaches_the_add_on_listing(self):
        from src.titan_core.actions import inproc, registry
        from src.titan_core.actions.manifest import AddonActions
        addon = AddonActions('component', 'titan_access', 'titan access',
                             COMPONENT, label='Titan Access')
        addon.transport = 'inproc'
        kept = inproc.candidate_owners
        inproc.candidate_owners = lambda _addon: [A]
        self.addCleanup(lambda: setattr(inproc, "candidate_owners", kept))
        registry._merge_python_declared(addon)
        self.assertIn("screen reader", addon.description)
        self.assertIn("UWP", addon.description)
        self.assertIn("about", addon.description)
        self.assertLessEqual(len(A.TITAN_DESCRIPTION), 800)
        self.assertIn("page_summary", [a.name for a in addon.actions])

    def test_both_prompts_carry_the_live_note(self):
        # The paragraph is no longer written into either prompt: it is read
        # out of the reader when the prompt is built, so it cannot go stale.
        for path in ("src/ai/ai_agent.py", "src/ai/assistant/voice_assistant.py"):
            with open(os.path.join(REPO, path), encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("titan_access_note()", text)
            self.assertNotIn("TITAN ACCESS is Titan's own screen reader", text)

    def test_the_note_is_read_out_of_the_reader(self):
        from src.ai import action_tools
        from src.titan_core.actions.manifest import AddonActions
        from src.titan_core.actions import inproc
        addon = AddonActions('component', 'titan_access', 'titan access',
                             COMPONENT, label='Titan Access')
        addon.transport = 'inproc'
        kept = (inproc.candidate_owners, action_tools.core_actions.find_addon,
                action_tools.actions_enabled)
        inproc.candidate_owners = lambda _addon: [A]
        action_tools.core_actions.find_addon = lambda _id: addon
        action_tools.actions_enabled = lambda: True

        def put_back():
            (inproc.candidate_owners, action_tools.core_actions.find_addon,
             action_tools.actions_enabled) = kept
        self.addCleanup(put_back)
        note = action_tools.titan_access_note()
        self.assertIn("TITAN ACCESS", note)
        self.assertIn("titan_access.about", note)
        # Every action the reader declares NOW is named, the newest too.
        for entry in A.TITAN_ACTIONS:
            self.assertIn(entry['name'], note)
        # Its settings categories and its script language, from the code.
        from titan_access import settings_schema, ta_scripts
        for sid, _title, _rows in settings_schema.SECTIONS:
            self.assertIn("[%s]" % sid, note)
        for trigger in ta_scripts.TRIGGERS:
            self.assertIn(trigger[0].split()[1], note)
        for _p, _t, what in ta_scripts.STATEMENTS:
            self.assertIn(what.split()[0], note)

    def test_a_blocked_reader_is_not_described(self):
        from src.ai import action_tools
        from src.titan_core.actions.manifest import AddonActions
        addon = AddonActions('component', 'titan_access', 'titan access',
                             COMPONENT, label='Titan Access')
        kept = (action_tools.core_actions.find_addon,
                action_tools.blocked_addons)
        action_tools.core_actions.find_addon = lambda _id: addon
        action_tools.blocked_addons = lambda: {'titan_access'}

        def put_back():
            (action_tools.core_actions.find_addon,
             action_tools.blocked_addons) = kept
        self.addCleanup(put_back)
        self.assertEqual(action_tools.titan_access_note(), '')

    def test_about_lists_every_action_with_its_summary(self):
        text = A.action_about()
        for entry in A.TITAN_ACTIONS:
            self.assertIn("  %s - " % entry['name'], text)


class FakeBinding(object):
    def __init__(self, action_id, key_spec, handler, name=''):
        self.action_id, self.key_spec, self.handler = action_id, key_spec, handler
        self.name = name or action_id


class FakeEngine(object):
    def __init__(self):
        import threading
        self.said, self.played, self.tones = [], [], []
        self.ran = threading.Event()
        self.gestures = types.SimpleNamespace(_bindings=[
            FakeBinding("sayAll", "a", self.ran.set, "Say all"),
            FakeBinding("readTime", "f12", lambda: None, "Read the time"),
        ])
        self.current_object = types.SimpleNamespace(
            name="Zapisz", role="button", value="12", states=set(),
            pos_in_set=3, size_of_set=9, description="")
        self.sound = types.SimpleNamespace(
            play_tone=lambda **kw: self.tones.append(kw))

    def speak(self, text, interrupt=True, **_kw):
        self.said.append(text)

    def play(self, name, obj=None):
        self.played.append(name)

    def _shortcut_key_text(self, binding):
        return "Insert+" + binding.key_spec


class TheReaderDoesMoreThanRead(unittest.TestCase):

    def setUp(self):
        self.engine = FakeEngine()
        kept = A._engine
        A._engine = lambda require_running=True: self.engine
        self.addCleanup(lambda: setattr(A, "_engine", kept))

    def test_read_aloud_says_and_answers(self):
        self.assertEqual(A.action_read_aloud("value"), "12")
        self.assertEqual(self.engine.said, ["12"])
        self.assertIn("3", said(A.action_read_aloud("position")))
        self.assertIn("one of", said(A.action_read_aloud("nonsense")))

    def test_last_spoken(self):
        from titan_access import speech_adapter
        kept = speech_adapter.spoken
        speech_adapter.spoken = lambda: ["a", "b", "c"]
        self.addCleanup(lambda: setattr(speech_adapter, "spoken", kept))
        self.assertEqual(A.action_last_spoken(2), "b\nc")
        A.action_read_aloud("last")
        self.assertEqual(self.engine.said[-1], "c")

    def test_beep_and_cue(self):
        A.action_beep(440, 50, -1)
        self.assertEqual(self.engine.tones[0]["frequency"], 440.0)
        self.assertEqual(self.engine.tones[0]["pan"], -1.0)
        self.assertIn("edge", A._cue_names())
        A.action_play_cue("edge")
        self.assertEqual(self.engine.played, ["edge"])
        self.assertIn("has no sound", said(A.action_play_cue("wibble")))

    def test_shortcuts_and_commands(self):
        text = A.action_list_shortcuts()
        self.assertIn("sayAll: Insert+a (Say all)", text)
        self.assertIn("readTime", text)
        self.assertNotIn("sayAll", A.action_list_shortcuts("time"))
        self.assertEqual(A.action_run_command("say all"), "Ran Say all.")
        self.assertTrue(self.engine.ran.wait(2))
        self.assertIn("no command", said(A.action_run_command("nothing")))

    def test_pass_key_never_passes_the_reader_modifier(self):
        from titan_access import keyboard_hook
        sent = []
        kept = keyboard_hook.send_combo
        keyboard_hook.send_combo = lambda combo: sent.append(combo) or True
        self.addCleanup(lambda: setattr(keyboard_hook, "send_combo", kept))
        A.action_pass_key("insert+ctrl+s")
        self.assertEqual(sent, ["ctrl+s"])
        self.assertIn("Say which key", said(A.action_pass_key("insert")))


class ReaderScriptsAreWrittenChecked(unittest.TestCase):

    def setUp(self):
        import tempfile
        from titan_access.portable import readerHome
        home = tempfile.mkdtemp(prefix="ta_actions_scripts_")
        kept = readerHome.folder
        readerHome.folder = lambda: home
        self.addCleanup(lambda: setattr(readerHome, "folder", kept))
        kept_engine = A._engine
        A._engine = lambda require_running=True: None
        self.addCleanup(lambda: setattr(A, "_engine", kept_engine))

    def test_write_read_delete(self):
        text = 'when key "insert+shift+k"\nread focus\nbeep 880 40\n'
        self.assertEqual(A.action_write_script("mine", text),
                         "Saved and loaded mine.")
        self.assertEqual(A.action_read_script("mine"), text)
        self.assertIn("already", said(A.action_write_script("mine", text)))
        self.assertIn("mine", A.action_list_scripts())
        self.assertEqual(A.action_delete_script("mine"), "Deleted mine.")
        self.assertIn("no script", said(A.action_read_script("mine")))

    def test_a_script_with_a_mistake_is_not_saved(self):
        answer = said(A.action_write_script("bad", 'when key insert+j\nsay "x"'))
        self.assertIn("was not saved", answer)
        self.assertIn("line 1", answer)
        self.assertIn("no script", said(A.action_read_script("bad")))

    def test_a_name_cannot_leave_the_folder(self):
        from titan_access import ta_scripts
        answer = said(A.action_write_script(
            "../../escape", 'when reader starts\nsay "x"\n'))
        self.assertIn("needs a name", answer)
        A.action_write_script("a/b\\c", 'when reader starts\nsay "x"\n')
        self.assertTrue(os.path.isfile(os.path.join(ta_scripts.folder(),
                                                    "abc.tas")))

    def test_the_language_is_the_readers(self):
        self.assertIn("when notification", A.action_script_language())
        self.assertIn("Skrypty Titan Access", A.action_script_language("pl"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
"""Titan Access: the "Browsing the web" and "UWP apps" settings categories.

Each switch is flipped and the behaviour it names is asked for - a setting
that is stored and read by nothing is the failure this guards against:

* ``Browse/PageSummary``      - "Na stronie: 2 łącza, 1 nagłówek" on arrival
* ``Browse/SayAllOnPageLoad`` - the page read from its top on arrival
* ``Browse/LandmarkStartEnd`` - "koniec: nawigacja" leaving a region
* ``UWP/Glyphs``              - an icon as its word, left out, or as it is
* ``UWP/NameIconControls``    - an icon-only button given a name
* ``UWP/VirtualLists``        - a virtualised list realised at its edge
* ``Reader/liveLists``        - new rows at the end of a list read
and that both categories are in the schema the settings page and the walked
settings are built from, so the two cannot disagree.
"""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(REPO, "data", "components", "titan access")
sys.path.insert(0, REPO)
sys.path.insert(0, COMPONENT)
sys.path.insert(0, os.path.join(REPO, "tests"))

from test_titan_access_document_mode import make_handler       # noqa: E402
from titan_access.virtual_buffer import VNode                   # noqa: E402
from titan_access import settings_schema                        # noqa: E402


def _polish(test):
    from titan_access import localization
    kept = localization.get_language()
    localization.set_language('pl')
    test.addCleanup(lambda: localization.set_language(kept))


def _page_nodes():
    return [
        VNode(name="Start", role="link", landmark="nawigacja", landmark_start=True),
        VNode(name="Wiadomości", role="link", landmark="nawigacja"),
        VNode(name="Tytuł", role="heading", level=1, landmark="główny",
              landmark_start=True),
        VNode(name="Szukaj", role="edit", landmark="główny"),
        VNode(name="Stopka", role="text"),
    ]


class TheWebCategory(unittest.TestCase):

    def setUp(self):
        _polish(self)

    def _handler(self, **settings):
        handler, engine = make_handler(nodes=_page_nodes())
        engine.settings.get_bool = lambda section, key, default: \
            settings.get(key, default)
        engine.settings.get_int = lambda section, key, default: \
            settings.get(key, default)
        import titan_access.browse_mode as bm
        kept = bm._foreground_window_title
        bm._foreground_window_title = lambda: "Strona testowa"
        self.addCleanup(lambda: setattr(bm, "_foreground_window_title", kept))
        handler._dispatch = lambda fn: fn()
        handler._ensure_document = lambda *a, **k: True
        self.read_all = []
        handler.say_all = lambda: self.read_all.append(handler._index) or True
        return handler, engine

    def test_the_summary_counts_what_quick_navigation_finds(self):
        handler, _engine = self._handler()
        text = handler.page_summary_text()
        self.assertTrue(text.startswith("Na stronie: "), text)
        self.assertIn("2 łącza", text)
        self.assertIn("1 nagłówek", text)
        self.assertIn("1 pole formularza", text)
        self.assertNotIn("tabel", text)              # none: left out

    def test_arriving_on_a_page_says_its_summary_when_switched_on(self):
        handler, engine = self._handler(PageSummary=True, SayAllOnPageLoad=False)
        handler._announce_web_entry(None)
        self.assertTrue(any(str(s).startswith("Na stronie") for s in engine.spoken))
        self.assertEqual(self.read_all, [])

    def test_the_summary_is_not_said_when_switched_off(self):
        handler, engine = self._handler(PageSummary=False, SayAllOnPageLoad=False)
        handler._announce_web_entry(None)
        self.assertFalse(any(str(s).startswith("Na stronie") for s in engine.spoken))
        self.assertIn("Strona testowa", engine.spoken[0])

    def test_a_page_is_read_from_its_top_when_switched_on(self):
        handler, _engine = self._handler(PageSummary=False, SayAllOnPageLoad=True)
        handler._index = 3
        handler._announce_web_entry(None)
        self.assertEqual(self.read_all, [0])

    def test_leaving_a_region_says_it_ended(self):
        handler, _engine = self._handler(LandmarkStartEnd=True)
        nodes = _page_nodes()
        handler._last_landmark = ""
        self.assertIsNotNone(handler._landmark_segment(nodes[0]))
        said = handler._landmark_segment(nodes[2])[0]
        self.assertIn("koniec: nawigacja", said)
        self.assertIn("główny", said)
        said = handler._landmark_segment(nodes[4])[0]
        self.assertEqual(said, "koniec: główny")

    def test_regions_are_crossed_in_silence_when_switched_off(self):
        handler, _engine = self._handler(LandmarkStartEnd=False)
        nodes = _page_nodes()
        handler._last_landmark = ""
        for node in nodes:
            self.assertIsNone(handler._landmark_segment(node))


class TheUwpCategory(unittest.TestCase):

    def _store(self, **values):
        from titan_access import settings_store

        class _Store(object):
            def get_bool(self, section, key, default):
                return values.get(key, default)

            def get(self, section, key, default=None):
                return values.get(key, default)
        kept = settings_store.get_settings
        settings_store.get_settings = lambda: _Store()
        self.addCleanup(lambda: setattr(settings_store, "get_settings", kept))

    def test_an_icon_is_its_word_left_out_or_left_as_it_is(self):
        from titan_access import uwp
        cancel = ""
        self._store(Glyphs="word")
        self.assertNotIn(cancel, uwp.clean(cancel))
        self.assertTrue(uwp.clean(cancel).strip())
        self.assertEqual(uwp.clean(" pon."), "pon.")
        self._store(Glyphs="strip")
        self.assertEqual(uwp.clean(cancel), "")
        self._store(Glyphs="off")
        self.assertEqual(uwp.clean(cancel), cancel)
        # Off keeps an icon-only line in scan mode, too.
        self.assertEqual(uwp.node_name(cancel, "text"), cancel)

    def test_an_icon_only_button_is_named_only_when_switched_on(self):
        from titan_access import uwp
        self._store(NameIconControls=True)
        self.assertEqual(uwp.node_name("", "button", framework="XAML",
                                       automation_id="SetBirthdateCard"),
                         "Set birthdate card")
        self._store(NameIconControls=False)
        self.assertEqual(uwp.node_name("", "button", framework="XAML",
                                       automation_id="SetBirthdateCard"), "")

    def test_a_virtualised_list_is_extended_only_when_switched_on(self):
        from titan_access import virtual_lists
        from titan_access.browse_mode import _VK_DOWN
        calls = []
        kept = (virtual_lists.is_list_edge, virtual_lists.extend)
        virtual_lists.is_list_edge = lambda nodes, here, delta: True
        virtual_lists.extend = lambda nodes, here, delta: calls.append(here) or 0
        self.addCleanup(lambda: (setattr(virtual_lists, "is_list_edge", kept[0]),
                                 setattr(virtual_lists, "extend", kept[1])))
        for wanted, expected in ((True, 1), (False, 0)):
            calls.clear()
            handler, engine = make_handler(nodes=_page_nodes())
            engine.settings.get_bool = lambda section, key, default, w=wanted: \
                w if (section, key) == ("UWP", "VirtualLists") else default
            handler._move_line(1)
            self.assertEqual(len(calls), expected, wanted)

    def test_new_rows_are_read_only_when_switched_on(self):
        from titan_access.live_lists import LiveLists
        self.assertIn("switched_on", LiveLists.__init__.__code__.co_varnames)
        with open(os.path.join(COMPONENT, "titan_access", "engine.py"),
                  encoding="utf-8") as handle:
            src = handle.read()
        self.assertIn('switchboard.read("liveLists", True)', src)


class BothCategoriesAreOneSchema(unittest.TestCase):
    """The settings page and the walked settings are built from the same
    table, so a category in it is in both."""

    def test_the_categories_are_in_the_page_and_the_walk(self):
        from titan_access import settings_walk, settings_panel
        ids = [sid for sid, _t, _r in settings_schema.SECTIONS]
        self.assertIn("web", ids)
        self.assertIn("uwp", ids)
        walk_ids = [sid for sid, _t, _r in settings_walk.SCHEMA]
        self.assertEqual(ids, walk_ids)
        if settings_panel._schema is not None:
            self.assertIn("web", settings_panel.SECTIONS)
            self.assertIn("uwp", settings_panel.SECTIONS)

    def test_the_web_category_holds_the_three_settings_asked_for(self):
        rows = dict((sid, rows) for sid, _t, rows in settings_schema.SECTIONS)
        keys = [e.key for e in rows["web"]]
        for key in ("SayAllOnPageLoad", "PageSummary", "LandmarkStartEnd"):
            self.assertIn(key, keys)
        self.assertEqual([e.key for e in rows["uwp"]],
                         ["Glyphs", "NameIconControls", "VirtualLists", "liveLists"])

    def test_a_value_written_in_the_walk_is_what_the_reader_reads(self):
        import tempfile
        from titan_access import settings_store, settings_walk, uwp
        store = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), "titan_access.ini"))
        kept = settings_store._instance
        settings_store._instance = store
        self.addCleanup(lambda: setattr(settings_store, "_instance", kept))
        walk = dict(((s, k), (s, k, l, kind, x, d)) for _sid, _t, rows
                    in settings_walk.SCHEMA for (s, k, l, kind, x, d) in rows)
        settings_walk.set_value(walk[("Browse", "PageSummary")], False)
        settings_walk.set_value(walk[("Browse", "LandmarkStartEnd")], False)
        settings_walk.set_value(walk[("UWP", "Glyphs")], "strip")
        settings_walk.set_value(walk[("UWP", "VirtualLists")], False)
        handler, engine = make_handler(nodes=_page_nodes())
        engine.settings = store
        self.assertFalse(handler._browse_setting("PageSummary", True))
        self.assertFalse(handler._browse_setting("LandmarkStartEnd", True))
        self.assertFalse(handler._uwp_setting("VirtualLists", True))
        self.assertEqual(uwp.glyph_mode(), "strip")
        self.assertFalse(settings_walk.value_of(
            walk[("Browse", "PageSummary")], store) in (True, "true"))

if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
"""Titan Access: the virtual document, scan mode, OCR assistance, progress bars.

What these lock down:

1. The virtual document is built from whatever a window is willing to answer -
   UI Automation, MSAA, or (for a program that has neither) the raw child
   windows, where a nameless Edit is labelled from the Static text beside it.
2. Quick navigation matches on Titan role keys, so ``b`` finds a button whether
   the document came from a web page, from a legacy dialog or from the AI's
   reading of a picture.
3. Scan mode (reader modifier + Space) turns an ordinary application into that
   document, and leaves again on Escape or when the user changes window.
4. AI OCR is gated - it never reads anything with AI features off - and its
   labelling picks the caption that is really beside a control.
5. Progress bars follow NVDA exactly (110 Hz doubling every 25%, 40 ms, beep
   every 1%, speech every 10%) with 0% panned hard left and 100% hard right.
"""

import os
import sys
import threading
import time
import types
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(REPO, "data", "components", "titan access")
sys.path.insert(0, REPO)
sys.path.insert(0, COMPONENT)

from titan_access import quick_nav as qn                       # noqa: E402
from titan_access import virtual_buffer as vbuf                # noqa: E402
from titan_access import ocr_assist                            # noqa: E402
from titan_access import progress_monitor as pm                # noqa: E402
from titan_access.virtual_buffer import VNode                  # noqa: E402
from titan_access.browse_mode import _same_place               # noqa: E402


class FakeEngine(object):
    """Enough engine for the handler: speech, sounds and a settings object."""

    def __init__(self, **settings):
        self.spoken = []
        self.segments = []
        self.sounds = []
        self.tones = []
        self.current_object = None
        self.provider = None
        self.settings = types.SimpleNamespace(
            scan_mode=settings.get("scan_mode", True),
            ai_ocr=settings.get("ai_ocr", False),   # never call a real provider
            ai_ocr_labels=settings.get("ai_ocr_labels", True),
            get=lambda section, key, default="": settings.get(key, default))
        engine = self

        class _Sound(object):
            def play_tone(self, frequency=880.0, duration_ms=25, pan=0.0, gain=0.5):
                engine.tones.append((round(frequency, 2), duration_ms, round(pan, 3)))
        self.sound = _Sound()
        self.speech = None

    def speak(self, text, obj=None, interrupt=True, pitch_offset=0):
        self.spoken.append(text)

    def speak_segments(self, segments):
        self.segments.append(list(segments))
        self.spoken.append(", ".join(t for t, _p in segments if t))

    def speak_async(self, *a, **k):
        self.speak(*a, **k)

    def play(self, sound_name, obj=None):
        self.sounds.append(sound_name)

    def announce_object(self, obj, for_navigation=False, play_cursor=True):
        self.spoken.append(getattr(obj, "name", ""))

    def submit_read(self, fn):
        fn()          # run inline: the tests want the result, not the thread


def make_handler(engine=None, nodes=None, source="uia"):
    from titan_access.browse_mode import BrowseModeHandler

    engine = engine or FakeEngine()
    handler = BrowseModeHandler(engine)
    if nodes is not None:
        doc = vbuf.VirtualDocument(nodes=list(nodes), source=source, hwnd=1,
                                   title="Test window")
        handler._doc = doc
        handler._index = 0
        handler._scan = True
        handler._scan_hwnd = 1
        # A document that is never stale: these tests are about navigation.
        handler._cheap_stale = lambda _doc: False
    return handler, engine


def nodes_sample():
    return [
        VNode(name="Welcome", role="heading", level=1, source="uia"),
        VNode(name="Some text here", role="text", source="uia"),
        VNode(name="Open", role="button", source="uia"),
        VNode(name="Name", role="edit", value="Anna", source="uia"),
        VNode(name="Details", role="link", source="uia"),
        VNode(name="Agree", role="checkbox", states=("unchecked",), source="uia"),
    ]


class QuickNavRoleTests(unittest.TestCase):
    def test_roles_cover_every_navigable_type(self):
        for key in ("h", "k", "b", "e", "x", "r", "c", "i", "t", "g", "f"):
            qn_type = qn.type_for_key(key)
            self.assertNotEqual(qn_type, qn.QuickNavType.NONE, key)
            if not qn.is_heading(qn_type):
                self.assertTrue(qn.roles_for(qn_type), key)

    def test_button_key_finds_a_button_from_any_source(self):
        for source in ("uia", "msaa", "win32", "ocr", "ia2"):
            handler, engine = make_handler(
                nodes=[VNode(name="Text", role="text", source=source),
                       VNode(name="Save", role="button", source=source)],
                source=source)
            handler._quick_nav(qn.QuickNavType.BUTTON, backward=False)
            self.assertEqual(handler._index, 1, source)
            self.assertIn("Save", " ".join(engine.spoken), source)

    def test_heading_level_is_respected(self):
        handler, _ = make_handler(nodes=[
            VNode(name="Top", role="heading", level=1),
            VNode(name="Sub", role="heading", level=2),
        ])
        handler._quick_nav(qn.QuickNavType.HEADING2, backward=False)
        self.assertEqual(handler._index, 1)

    def test_missing_type_is_reported_not_silent(self):
        handler, engine = make_handler(nodes=[VNode(name="Only text", role="text")])
        handler._quick_nav(qn.QuickNavType.BUTTON, backward=False)
        self.assertTrue(engine.spoken)
        self.assertIn("edge.ogg", engine.sounds)


class NavigationTests(unittest.TestCase):
    def test_arrows_walk_the_document_and_stop_at_the_edges(self):
        handler, engine = make_handler(nodes=nodes_sample())
        handler._move_line(+1)
        self.assertEqual(handler._index, 1)
        handler._move_line(-1)
        self.assertEqual(handler._index, 0)
        handler._move_line(-1)          # already at the top
        self.assertEqual(handler._index, 0)
        self.assertIn("edge.ogg", engine.sounds)

    def test_ctrl_home_and_end(self):
        handler, _ = make_handler(nodes=nodes_sample())
        handler._move_to_end(first=False)
        self.assertEqual(handler._index, len(nodes_sample()) - 1)
        handler._move_to_end(first=True)
        self.assertEqual(handler._index, 0)

    def test_page_movement_is_clamped_not_refused(self):
        handler, _ = make_handler(nodes=nodes_sample())
        handler._move_line(+100)
        self.assertEqual(handler._index, len(nodes_sample()) - 1)

    def test_word_movement_reads_words(self):
        handler, engine = make_handler(nodes=[VNode(name="one two three",
                                                    role="text")])
        handler._move_word(+1)
        self.assertEqual(engine.spoken[-1], "two")
        handler._move_word(+1)
        self.assertEqual(engine.spoken[-1], "three")
        handler._move_word(-1)
        self.assertEqual(engine.spoken[-1], "two")

    def test_announcement_says_name_role_and_state(self):
        handler, engine = make_handler(
            nodes=[VNode(name="Agree", role="checkbox", states=("unchecked",),
                         source="msaa")])
        handler._announce_node(handler._doc.nodes[0], move_focus=False)
        line = engine.spoken[-1]
        self.assertIn("Agree", line)
        self.assertEqual(len(engine.segments[-1]), 3)   # name / role / state

    def test_edit_value_is_read_with_the_name(self):
        node = VNode(name="Name", role="edit", value="Anna", source="msaa")
        self.assertEqual(node.text, "Name Anna")


class ScanModeTests(unittest.TestCase):
    def test_escape_leaves_scan_mode(self):
        handler, engine = make_handler(nodes=nodes_sample())
        self.assertTrue(handler.scan_active)
        handler.handle_key(0x1B, "escape", False, False, False)
        self.assertFalse(handler.scan_active)
        self.assertTrue(engine.spoken)

    def test_changing_window_ends_scan_mode(self):
        handler, _ = make_handler(nodes=nodes_sample())
        vbuf_foreground = vbuf.foreground_hwnd
        vbuf.foreground_hwnd = lambda: 999          # some other window
        try:
            handler.update_for_focus(types.SimpleNamespace(name="x", role="button"))
        finally:
            vbuf.foreground_hwnd = vbuf_foreground
        self.assertFalse(handler.scan_active)

    def test_scan_can_be_switched_off_in_settings(self):
        engine = FakeEngine(scan_mode=False)
        handler, _ = make_handler(engine)
        self.assertFalse(handler.toggle_scan())

    def test_keys_are_claimed_in_scan_mode_but_not_in_pass_through(self):
        handler, _ = make_handler(nodes=nodes_sample())
        self.assertTrue(handler.handle_key(0x28, "down", False, False, False))
        handler._pass_through = True
        self.assertFalse(handler.handle_key(0x28, "down", False, False, False))

    def test_tab_is_left_to_the_application(self):
        handler, _ = make_handler(nodes=nodes_sample())
        self.assertFalse(handler.handle_key(0x09, "tab", False, False, False))

    def test_activation_uses_the_node_source(self):
        pressed = []
        node = VNode(name="Open", role="button", source="win32", hwnd=42)
        original = vbuf.activate
        vbuf.activate = lambda n, screen=None: pressed.append(n) or True
        try:
            handler, engine = make_handler(nodes=[node])
            handler._activate_current()
        finally:
            vbuf.activate = original
        self.assertEqual(pressed, [node])
        self.assertIn("clicked.ogg", engine.sounds)


class LegacyWin32Tests(unittest.TestCase):
    """The tier that reads a program with no accessibility of any kind."""

    def test_static_text_to_the_left_labels_a_nameless_edit(self):
        raw = [
            (1, "static", "text", "User name", (10, 10, 90, 30)),
            (2, "edit", "edit", "", (100, 10, 300, 30)),
        ]
        self.assertEqual(vbuf._nearby_label(raw, 1), "User name")

    def test_static_text_above_labels_a_nameless_edit(self):
        raw = [
            (1, "static", "text", "Password", (10, 10, 200, 28)),
            (2, "edit", "edit", "", (10, 32, 200, 52)),
        ]
        self.assertEqual(vbuf._nearby_label(raw, 1), "Password")

    def test_unrelated_text_far_away_is_not_borrowed(self):
        raw = [
            (1, "static", "text", "Somewhere else", (10, 500, 200, 520)),
            (2, "edit", "edit", "", (10, 10, 200, 30)),
        ]
        self.assertEqual(vbuf._nearby_label(raw, 1), "")

    def test_window_classes_map_to_roles(self):
        # A "Button" window is NOT in the table: its style decides whether it is
        # a push button, a tick box, an option or a group frame (_button_role).
        self.assertNotIn("button", vbuf._CLASS_TO_ROLE)
        self.assertEqual(vbuf._CLASS_TO_ROLE["edit"], "edit")
        self.assertEqual(vbuf._CLASS_TO_ROLE["syslistview32"], "list")
        self.assertEqual(vbuf._CLASS_TO_ROLE["msctls_trackbar32"], "slider")

    def test_signature_notices_a_changed_window(self):
        doc = vbuf.VirtualDocument(nodes=[VNode(name="x")], hwnd=1,
                                   signature=(1, "Old title", (0, 0, 10, 10), 1))
        original = vbuf.signature_for
        vbuf.signature_for = lambda hwnd, d=None: (1, "New title", (0, 0, 10, 10), 1)
        try:
            self.assertTrue(vbuf.looks_stale(doc))
        finally:
            vbuf.signature_for = original


class OcrAssistTests(unittest.TestCase):
    def test_reading_is_refused_when_ai_features_are_off(self):
        settings = types.SimpleNamespace(ai_ocr=True)
        import src.ai.ai_provider as provider
        original = provider.vision_unavailable_reason
        provider.vision_unavailable_reason = lambda: "AI features are switched off."
        try:
            self.assertFalse(ocr_assist.available(settings))
            self.assertIsNone(ocr_assist.read_window(123, settings=settings))
        finally:
            provider.vision_unavailable_reason = original

    def test_reading_is_refused_when_the_reader_says_no(self):
        settings = types.SimpleNamespace(ai_ocr=False)
        self.assertEqual(ocr_assist.unavailable_reason(settings), "off")
        self.assertFalse(ocr_assist.available(settings))

    def test_elements_become_nodes_with_screen_rectangles(self):
        shot = types.SimpleNamespace(
            rect_to_screen=lambda rect: (int(rect[0]) * 2, int(rect[1]) * 2,
                                         int(rect[2]) * 2, int(rect[3]) * 2))
        element = types.SimpleNamespace(name="Install", role="button", value="",
                                        text="", state="", checked=None,
                                        rect=[10, 20, 50, 15])
        region = types.SimpleNamespace(label="Setup", elements=[element],
                                       rect=None)
        screen = types.SimpleNamespace(regions=[region], capture=shot,
                                       elements=[element], title="Setup",
                                       summary="")
        ocr_assist._cache[7] = (screen, __import__("time").time())
        try:
            nodes = ocr_assist.build_nodes(7, VNode)
        finally:
            ocr_assist.forget(7)
        names = [n.name for n in nodes]
        self.assertIn("Install", names)
        button = [n for n in nodes if n.name == "Install"][0]
        self.assertEqual(button.role, "button")
        self.assertEqual(button.source, "ocr")
        self.assertEqual(button.rect, (20, 40, 120, 70))    # x2 scale, w/h added

    def test_label_for_prefers_text_inside_then_left_then_above(self):
        shot = types.SimpleNamespace(
            rect_to_screen=lambda rect: (int(rect[0]), int(rect[1]),
                                         int(rect[2]), int(rect[3])))

        def element(name, rect):
            return types.SimpleNamespace(name=name, text="", rect=rect)

        # A caption to the left of the field, and an unrelated one far away.
        screen = types.SimpleNamespace(
            capture=shot,
            elements=[element("E-mail", [10, 10, 60, 20]),
                      element("Something else", [10, 400, 100, 20])])
        ocr_assist._cache[9] = (screen, __import__("time").time())
        try:
            label = ocr_assist.label_for(9, (100, 10, 300, 30))
        finally:
            ocr_assist.forget(9)
        self.assertEqual(label, "E-mail")


class ProgressBarTests(unittest.TestCase):
    def test_pan_runs_left_to_right(self):
        self.assertAlmostEqual(pm.pan_for_percent(0), -1.0)
        self.assertAlmostEqual(pm.pan_for_percent(50), 0.0)
        self.assertAlmostEqual(pm.pan_for_percent(100), 1.0)

    def test_pitch_is_nvdas_curve(self):
        # NVDA: beepMinHZ * 2 ** (percentage / 25.0), beepMinHZ = 110.
        self.assertAlmostEqual(pm.tone_for_percent(0), 110.0)
        self.assertAlmostEqual(pm.tone_for_percent(25), 220.0)
        self.assertAlmostEqual(pm.tone_for_percent(50), 440.0)
        self.assertAlmostEqual(pm.tone_for_percent(100), 1760.0)

    def test_percentage_from_a_range(self):
        self.assertAlmostEqual(pm._percent(5, 0, 20), 25.0)
        self.assertIsNone(pm._percent(5, 10, 10))
        self.assertIsNone(pm._percent(None, 0, 100))

    def test_percentage_from_a_value_string(self):
        self.assertAlmostEqual(pm._parse_percent_text("45%"), 45.0)
        self.assertAlmostEqual(pm._parse_percent_text(" 7,5 "), 7.5)
        self.assertIsNone(pm._parse_percent_text("busy"))

    def _monitor(self, **settings):
        engine = FakeEngine(**settings)
        monitor = pm.ProgressMonitor(engine)
        monitor._target = object()
        monitor._target_kind = "uia"
        monitor._target_name = "Copying"
        return monitor, engine

    def test_speech_every_ten_percent_beep_every_one(self):
        monitor, engine = self._monitor(ProgressMode="SpeechAndSound")
        for value in (0, 3, 7, 11, 15, 22, 30):
            monitor._report(float(value), "SpeechAndSound")
        # Beeps: every step moved at least 1%.
        self.assertEqual(len(engine.tones), 7)
        # Speech: the first sighting plus 0, 11, 22, 30 -> four values.
        percents = [t for t in engine.spoken if "percent" in t or "procent" in t
                    or t.strip().split(" ")[0].isdigit()]
        self.assertGreaterEqual(len(percents), 3)
        self.assertLessEqual(len(percents), 5)

    def test_beep_only_mode_never_speaks(self):
        monitor, engine = self._monitor(ProgressMode="Sound")
        for value in (0, 20, 40, 60, 80, 100):
            monitor._report(float(value), "Sound")
        self.assertTrue(engine.tones)
        self.assertEqual(engine.spoken, [])

    def test_speech_only_mode_never_beeps(self):
        monitor, engine = self._monitor(ProgressMode="Speech")
        for value in (0, 20, 40):
            monitor._report(float(value), "Speech")
        self.assertEqual(engine.tones, [])
        self.assertTrue(engine.spoken)

    def test_the_beep_travels_with_the_value(self):
        monitor, engine = self._monitor(ProgressMode="Sound")
        monitor._report(0.0, "Sound")
        monitor._report(100.0, "Sound")
        self.assertAlmostEqual(engine.tones[0][2], -1.0)     # 0% hard left
        self.assertAlmostEqual(engine.tones[-1][2], 1.0)     # 100% hard right
        self.assertLess(engine.tones[0][0], engine.tones[-1][0])   # pitch rises

    def test_a_bar_that_does_not_move_says_nothing_twice(self):
        monitor, engine = self._monitor(ProgressMode="SpeechAndSound")
        monitor._report(40.0, "SpeechAndSound")
        before = len(engine.tones)
        monitor._report(40.2, "SpeechAndSound")
        self.assertEqual(len(engine.tones), before)

    def test_completion_is_announced_once(self):
        monitor, engine = self._monitor(ProgressMode="Speech")
        monitor._report(50.0, "Speech")
        monitor._report(100.0, "Speech")
        monitor._report(100.0, "Speech")
        completions = [t for t in engine.spoken if t in ("complete", "gotowe")]
        self.assertEqual(len(completions), 1)


class WebDocumentTests(unittest.TestCase):
    """A page is read flat, the way NVDA reads it.

    No grouping or landmark lines of their own: the regions ride on the content
    they contain, are announced once when the cursor crosses into them, and are
    still what quick navigation jumps between.
    """

    class _Cache(object):
        """Just enough of :mod:`titan_access.uia_cache` for _flatten_web."""
        ARIA_ROLE, NAME = "aria", "name"

        @staticmethod
        def get(item, key, default=None):
            return item.get(key, default)

        @staticmethod
        def text(item, key):
            return (item.get(key) or "").strip()

        @staticmethod
        def rect_of(item):
            return item.get("rect", ())

    def test_a_named_group_is_an_entry_in_an_app_and_never_in_a_page(self):
        self.assertTrue(vbuf._wrapper_worth_keeping("GroupControl", "Options",
                                                    web=False))
        self.assertFalse(vbuf._wrapper_worth_keeping("GroupControl", "Options",
                                                     web=True))
        self.assertFalse(vbuf._wrapper_worth_keeping("GroupControl", "",
                                                     web=False))

    def test_landmarks_label_the_content_instead_of_standing_before_it(self):
        elements = [
            {"aria": "navigation", "name": "", "rect": (0, 0, 200, 50)},
            {"aria": "main", "name": "", "rect": (0, 50, 200, 400)},
        ]
        nodes = [
            VNode(name="Home", role="link", rect=(5, 5, 60, 20)),
            VNode(name="News", role="link", rect=(65, 5, 120, 20)),
            VNode(name="Headline", role="heading", level=1,
                  rect=(5, 60, 190, 90)),
            VNode(name="Footer note", role="text", rect=(0, 500, 200, 520)),
        ]
        vbuf._flatten_web(self._Cache, elements, nodes)
        self.assertEqual([n.landmark for n in nodes],
                         ["navigation", "navigation", "main", ""])
        self.assertEqual([n.landmark_start for n in nodes],
                         [True, False, True, False])

    def test_the_innermost_region_wins(self):
        elements = [
            {"aria": "main", "name": "", "rect": (0, 0, 500, 500)},
            {"aria": "search", "name": "Site search", "rect": (10, 10, 100, 40)},
        ]
        nodes = [VNode(name="Query", role="edit", rect=(15, 15, 90, 35))]
        vbuf._flatten_web(self._Cache, elements, nodes)
        self.assertEqual(nodes[0].landmark, "Site search")

    def test_quick_nav_jumps_between_regions_not_to_group_entries(self):
        nodes = [
            VNode(name="Home", role="link", landmark="navigation",
                  landmark_start=True),
            VNode(name="News", role="link", landmark="navigation"),
            VNode(name="Headline", role="heading", level=1, landmark="main",
                  landmark_start=True),
        ]
        handler, _ = make_handler(nodes=nodes)
        handler._index = 0
        handler._quick_nav(qn.QuickNavType.LANDMARK, backward=False)
        self.assertEqual(handler._index, 2)

    def test_the_region_is_announced_on_entry_and_not_repeated(self):
        handler, engine = make_handler()
        first = VNode(name="Home", role="link", landmark="navigation",
                      landmark_start=True)
        second = VNode(name="News", role="link", landmark="navigation")
        said_first = " ".join(t for t, _p in handler._segments_for(first))
        said_second = " ".join(t for t, _p in handler._segments_for(second))
        self.assertIn("navigation", said_first)
        self.assertNotIn("navigation", said_second)
        self.assertNotIn("group", said_first.lower())


class ResponsivenessTests(unittest.TestCase):
    """A navigation key must never wait for the document to be rebuilt."""

    def test_the_staleness_check_never_touches_ui_automation(self):
        handler, _ = make_handler(nodes=nodes_sample())
        handler._scan = False                      # web document
        handler._doc.built_at = time.time()
        handler._doc.signature = handler._cheap_signature(handler._doc)

        def _boom():
            raise AssertionError("the staleness check resolved the document root")

        handler._document_root = _boom
        handler._resolve_document_root = _boom
        self.assertFalse(handler._cheap_stale(handler._doc))

    def test_a_stale_document_is_refreshed_behind_the_keystroke(self):
        handler, engine = make_handler(nodes=nodes_sample())
        handler._scan = False
        handler._cheap_stale = lambda _doc: True
        started = threading.Event()
        release = threading.Event()
        built = []

        def _slow_build(hwnd=0, allow_ocr=False):
            started.set()
            release.wait(2.0)
            built.append(True)
            return None

        handler._build_document = _slow_build
        handler._move_line(+1)                     # the keystroke
        # It answered from the buffer it already had, while the build waits.
        self.assertTrue(started.wait(2.0))
        self.assertEqual(built, [])
        self.assertEqual(handler._index, 1)
        self.assertIn("Some text here", " ".join(engine.spoken))
        release.set()

    def test_only_one_refresh_runs_at_a_time(self):
        handler, _ = make_handler(nodes=nodes_sample())
        handler._scan = False
        release = threading.Event()
        calls = []

        def _slow_build(hwnd=0, allow_ocr=False):
            calls.append(True)
            release.wait(2.0)
            return None

        handler._build_document = _slow_build
        for _ in range(5):
            handler._schedule_rebuild()
        time.sleep(0.15)
        self.assertEqual(len(calls), 1)
        release.set()

    def test_a_refresh_keeps_the_cursor_on_the_same_entry(self):
        nodes = nodes_sample()
        rebuilt = [VNode(name="Banner", role="text", source="uia")] + [
            VNode(name=n.name, role=n.role, value=n.value, level=n.level,
                  source="uia") for n in nodes]
        self.assertEqual(_same_place(rebuilt, nodes[2], 2), 3)   # "Open" moved
        self.assertEqual(_same_place(rebuilt, None, 2), 2)       # nothing to match
        self.assertEqual(_same_place([], nodes[2], 2), 0)


class GroupAnnouncementTests(unittest.TestCase):
    """Titan stops saying "group" where NVDA does not say it."""

    def test_an_unnamed_group_is_not_announced_at_all(self):
        from titan_access.context_presenter import ContextPresenter
        self.assertIsNone(ContextPresenter._segment_for("group", ""))
        self.assertIsNone(ContextPresenter._segment_for("group", "   "))

    def test_a_named_group_still_is(self):
        from titan_access.context_presenter import ContextPresenter
        segment = ContextPresenter._segment_for("group", "Options")
        self.assertIsNotNone(segment)
        self.assertIn("Options", segment[0])

    def test_web_content_is_recognised_by_its_framework(self):
        from titan_access.context_presenter import _is_web_content
        for framework in ("Chrome", "Gecko", "WebView", "Edge", "Blink"):
            self.assertTrue(_is_web_content(
                types.SimpleNamespace(framework_id=framework)), framework)
        for framework in ("Win32", "WPF", "XAML", ""):
            self.assertFalse(_is_web_content(
                types.SimpleNamespace(framework_id=framework)), framework)


if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
"""A web page in Titan Access reads once per thing, and reads at all.

Each case is the shape a real page answered with, measured in Edge on
2026-10-05 (forum.audiogames.net, tyflopodcast.net, pl.wikipedia.org):

* a heading holding a link was two lines with the same words - it is one
  line, a heading that is also a link (H and K both find it);
* a list item holding a link or a number was two lines - the item gives
  way and its content keeps "3 of 9";
* a list item was announced as "heading level 1" because it had a level;
* a radio button and its <label>, an edit field and its <label>, a table
  and its caption were each said twice;
* off-screen content (everything below the viewport, and "visually
  hidden" text) was dropped, so a page held only what was scrolled into
  view;
* with the focus outside the page, the document chosen was Edge's own
  empty shell, of exactly the page's size - so the page read as nothing.

Run directly: ``python tests/test_titan_access_web_pages.py``.
"""

import os
import sys
import tempfile
import unittest

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='titan_access_web_')
HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)

from titan_access import virtual_buffer as vbuf          # noqa: E402
from titan_access.virtual_buffer import VNode           # noqa: E402


def node(role, name, rect, level=0, pos=0, size=0):
    return VNode(name=name, role=role, rect=rect, level=level,
                 pos_in_set=pos, size_of_set=size, raw=(role, name))


def lines(nodes):
    return [(n.role, n.name) for n in nodes]


class OneLinePerThing(unittest.TestCase):

    def test_a_heading_that_is_a_link_is_one_line(self):
        merged = vbuf.merge_web_containers([
            node('heading', 'General Game Discussion', (0, 0, 400, 30), 3),
            node('link', 'General Game Discussion', (5, 5, 300, 25)),
            node('text', 'Discuss everything', (0, 40, 400, 60)),
        ])
        self.assertEqual(lines(merged), [
            ('heading', 'General Game Discussion'),
            ('text', 'Discuss everything')])
        self.assertTrue(merged[0].link)
        # Enter follows the link, not the heading.
        self.assertEqual(merged[0].raw, ('link', 'General Game Discussion'))

    def test_a_list_item_gives_way_and_keeps_its_place(self):
        merged = vbuf.merge_web_containers([
            node('listitem', 'Index', (0, 0, 100, 20), 1, 1, 9),
            node('link', 'Index', (2, 2, 60, 18)),
            node('listitem', 'Today 08:32by darren', (0, 30, 200, 50), 1, 3, 3),
            node('link', 'Today 08:32', (2, 32, 90, 48)),
            node('text', 'by darren', (92, 32, 190, 48)),
        ])
        self.assertEqual(lines(merged), [
            ('link', 'Index'), ('link', 'Today 08:32'), ('text', 'by darren')])
        self.assertEqual((merged[0].pos_in_set, merged[0].size_of_set), (1, 9))
        self.assertEqual(merged[1].pos_in_set, 3)

    def test_a_link_absorbs_its_text(self):
        merged = vbuf.merge_web_containers([
            node('link', 'Pobierz plik', (0, 0, 200, 20)),
            node('text', 'Pobierz plik', (2, 2, 190, 18)),
        ])
        self.assertEqual(lines(merged), [('link', 'Pobierz plik')])

    def test_a_label_beside_its_control_is_not_said_again(self):
        merged = vbuf.merge_web_containers([
            node('text', 'Szukaj:', (0, 0, 60, 20)),
            node('edit', 'Szukaj:', (70, 0, 300, 20)),
            node('radio', 'Mały', (0, 30, 20, 50)),
            node('text', 'Mały', (25, 30, 80, 50)),
        ])
        self.assertEqual(lines(merged), [('edit', 'Szukaj:'),
                                         ('radio', 'Mały')])

    def test_a_group_of_radios_with_labels_reads_as_the_radios(self):
        merged = vbuf.merge_web_containers([
            node('listitem', 'MałyNormalny', (0, 0, 300, 60), 1),
            node('radio', 'Mały', (0, 0, 20, 20)),
            node('text', 'Mały', (25, 0, 80, 20)),
            node('radio', 'Normalny', (0, 30, 20, 50)),
            node('text', 'Normalny', (25, 30, 120, 50)),
        ])
        self.assertEqual(lines(merged), [('radio', 'Mały'),
                                         ('radio', 'Normalny')])

    def test_a_table_caption_is_the_table_name(self):
        merged = vbuf.merge_web_containers([
            node('grid', 'Ślepota', (0, 0, 500, 300)),
            node('text', 'Ślepota', (10, 5, 200, 25)),
            node('cell', 'amaurosis', (10, 40, 200, 60)),
        ])
        self.assertEqual(lines(merged), [('grid', 'Ślepota'),
                                         ('cell', 'amaurosis')])

    def test_different_words_are_left_alone(self):
        original = [node('heading', 'Ankieta', (0, 0, 400, 30), 2),
                    node('text', 'Prosimy', (0, 40, 400, 60)),
                    node('link', 'Kliknij', (0, 70, 200, 90))]
        self.assertEqual(lines(vbuf.merge_web_containers(list(original))),
                         lines(original))


class AListItemIsNotAHeading(unittest.TestCase):

    def test_the_role_decides(self):
        self.assertFalse(node('listitem', 'Index', (0, 0, 1, 1), 1).is_heading)
        self.assertTrue(node('heading', 'Ankieta', (0, 0, 1, 1), 2).is_heading)


class TheHeadingLinkIsAHeadingAndALink(unittest.TestCase):

    def test_quick_navigation_finds_it_both_ways(self):
        from titan_access import browse_mode, quick_nav as qn
        one = node('heading', 'Beorg', (0, 0, 1, 1), 3)
        one.link = True
        match = browse_mode.BrowseModeHandler._matches
        self.assertTrue(match(one, qn.QuickNavType.LINK))
        self.assertTrue(match(one, qn.type_for_key('h')))


class _Fake(object):
    def __init__(self, ctype, cls='', children=(), area=100):
        self.ControlTypeName = ctype
        self.ClassName = cls
        self.FrameworkId = 'Chrome'
        self._children = list(children)
        self._area = area

    def GetChildren(self):
        return self._children


class ThePageNotEdgesShell(unittest.TestCase):

    def test_the_document_the_renderer_hosts_wins_a_tie(self):
        from titan_access import browse_mode
        shell = _Fake('DocumentControl', 'WebView')
        page = _Fake('DocumentControl', '')
        window = _Fake('PaneControl', '', [
            _Fake('PaneControl', 'View', [shell]),
            _Fake('PaneControl', 'Chrome_RenderWidgetHostHWND', [page])])
        keep = (browse_mode._ctype, browse_mode._control_area)
        browse_mode._ctype = lambda c: c.ControlTypeName
        browse_mode._control_area = lambda c: c._area
        try:
            handler = browse_mode.BrowseModeHandler.__new__(
                browse_mode.BrowseModeHandler)
            self.assertIs(handler._find_main_document(window), page)
        finally:
            browse_mode._ctype, browse_mode._control_area = keep


class OffScreenIsStillThePage(unittest.TestCase):

    def test_web_keeps_what_an_application_skips(self):
        class Meta(type):
            def __getattr__(cls, name):
                return 'other:' + name

        class UC(object, metaclass=Meta):
            IS_OFFSCREEN, CONTROL_TYPE, NAME, ARIA_ROLE = 1, 2, 3, 4
            LEVEL, POSITION_IN_SET, SIZE_OF_SET = 5, 6, 7

            @staticmethod
            def flag(cached, prop, default):
                return True if prop == UC.IS_OFFSCREEN else default

            @staticmethod
            def get(cached, prop, default=None):
                return {UC.CONTROL_TYPE: 50005, UC.ARIA_ROLE: ''}.get(
                    prop, default)

            @staticmethod
            def text(cached, prop):
                return 'Below the fold' if prop == UC.NAME else ''

            @staticmethod
            def number(cached, prop):
                return 0

            @staticmethod
            def pattern_value(*args):
                return args[-1]

            @staticmethod
            def rect_of(cached):
                return (0, 5000, 100, 5020)

        self.assertIsNone(vbuf._node_from_cached(UC, object(), web=False))
        found = vbuf._node_from_cached(UC, object(), web=True)
        self.assertEqual((found.role, found.name), ('link', 'Below the fold'))


if __name__ == '__main__':
    unittest.main()

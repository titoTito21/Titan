# -*- coding: utf-8 -*-
"""Quick-navigation type vocabulary for browse mode.

Python port of ``ScreenReader/BrowseMode/QuickNavTypes.cs``. Browse mode lets a
user jump through a web document by element type using single letters
(NVDA-style): ``h`` next heading, ``k`` next link, ``b`` next button, and so on.
Holding Shift reverses the direction.

This module is pure data + small helpers; it imports nothing heavy (no UIA, no
ctypes) so it is safe to import everywhere. The actual UIA matching lives in
:mod:`titan_access.browse_mode`, which consults the tables exposed here:

    KEY_TO_TYPE          letter -> QuickNavType
    CONTROL_TYPE_MATCH   QuickNavType -> uiautomation ControlTypeName values
    ARIA_MATCH           QuickNavType -> localized-control-type substrings
    type_label(t)        localized spoken name for a type

# LOCALE KEYS TO ADD: quickNav.formField = form field
# LOCALE KEYS TO ADD: quickNav.landmark = landmark
# LOCALE KEYS TO ADD: quickNav.frame = frame
# LOCALE KEYS TO ADD: quickNav.blockQuote = block quote
# LOCALE KEYS TO ADD: quickNav.paragraph = paragraph
# LOCALE KEYS TO ADD: quickNav.annotation = annotation
# LOCALE KEYS TO ADD: quickNav.heading = heading
# LOCALE KEYS TO ADD: quickNav.unvisitedLink = unvisited link
# LOCALE KEYS TO ADD: quickNav.visitedLink = visited link
# LOCALE KEYS TO ADD: quickNav.headingLevel = heading level {0}
"""

from enum import IntEnum


class QuickNavType(IntEnum):
    """Element categories reachable by single-letter quick navigation."""

    NONE = 0

    # Headings (H, 1-6)
    HEADING = 1
    HEADING1 = 2
    HEADING2 = 3
    HEADING3 = 4
    HEADING4 = 5
    HEADING5 = 6
    HEADING6 = 7

    # Links (K, U, V)
    LINK = 10
    UNVISITED_LINK = 11
    VISITED_LINK = 12

    # Form fields (F, E, B, X, R, C)
    FORM_FIELD = 20
    EDIT_FIELD = 21
    BUTTON = 22
    CHECKBOX = 23
    RADIO_BUTTON = 24
    COMBO_BOX = 25

    # Lists (L, I)
    LIST = 30
    LIST_ITEM = 31

    # Tables (T)
    TABLE = 40
    TABLE_CELL = 41

    # Graphics (G)
    GRAPHIC = 50

    # Structural (D / N, M, Q)
    LANDMARK = 60
    FRAME = 61
    BLOCK_QUOTE = 62

    # Separator (S)
    SEPARATOR = 70

    # Text (P)
    PARAGRAPH = 80

    # Annotation (A)
    ANNOTATION = 90


# --------------------------------------------------------------------------- #
# Key -> type map (lower-case letters/digits). Uppercase = forward, Shift =
# backward; the letter itself is case-insensitive (the engine reports the base
# virtual key, the Shift flag carries the direction).
# --------------------------------------------------------------------------- #
KEY_TO_TYPE = {
    'h': QuickNavType.HEADING,
    '1': QuickNavType.HEADING1,
    '2': QuickNavType.HEADING2,
    '3': QuickNavType.HEADING3,
    '4': QuickNavType.HEADING4,
    '5': QuickNavType.HEADING5,
    '6': QuickNavType.HEADING6,

    'k': QuickNavType.LINK,
    'u': QuickNavType.UNVISITED_LINK,
    'v': QuickNavType.VISITED_LINK,

    'f': QuickNavType.FORM_FIELD,
    'e': QuickNavType.EDIT_FIELD,
    'b': QuickNavType.BUTTON,
    'c': QuickNavType.COMBO_BOX,
    'r': QuickNavType.RADIO_BUTTON,
    'x': QuickNavType.CHECKBOX,

    'l': QuickNavType.LIST,
    'i': QuickNavType.LIST_ITEM,

    't': QuickNavType.TABLE,
    'g': QuickNavType.GRAPHIC,

    'd': QuickNavType.LANDMARK,
    'n': QuickNavType.LANDMARK,
    'm': QuickNavType.FRAME,
    'q': QuickNavType.BLOCK_QUOTE,

    's': QuickNavType.SEPARATOR,
    'p': QuickNavType.PARAGRAPH,
    'a': QuickNavType.ANNOTATION,
}


# --------------------------------------------------------------------------- #
# Localized spoken labels. Most types reuse the existing ``ctrlType.*`` keys so
# announcements stay consistent with normal focus reading; the few web-only
# concepts get dedicated ``quickNav.*`` keys (listed at the top of this file).
# --------------------------------------------------------------------------- #
_TYPE_LABEL_KEY = {
    QuickNavType.HEADING: "quickNav.heading",
    QuickNavType.HEADING1: "quickNav.heading",
    QuickNavType.HEADING2: "quickNav.heading",
    QuickNavType.HEADING3: "quickNav.heading",
    QuickNavType.HEADING4: "quickNav.heading",
    QuickNavType.HEADING5: "quickNav.heading",
    QuickNavType.HEADING6: "quickNav.heading",
    QuickNavType.LINK: "ctrlType.hyperlink",
    QuickNavType.UNVISITED_LINK: "quickNav.unvisitedLink",
    QuickNavType.VISITED_LINK: "quickNav.visitedLink",
    QuickNavType.FORM_FIELD: "quickNav.formField",
    QuickNavType.EDIT_FIELD: "ctrlType.edit",
    QuickNavType.BUTTON: "ctrlType.button",
    QuickNavType.CHECKBOX: "ctrlType.checkBox",
    QuickNavType.RADIO_BUTTON: "ctrlType.radioButton",
    QuickNavType.COMBO_BOX: "ctrlType.comboBox",
    QuickNavType.LIST: "ctrlType.list",
    QuickNavType.LIST_ITEM: "ctrlType.listItem",
    QuickNavType.TABLE: "ctrlType.table",
    QuickNavType.TABLE_CELL: "ctrlType.dataItem",
    QuickNavType.GRAPHIC: "ctrlType.image",
    QuickNavType.LANDMARK: "quickNav.landmark",
    QuickNavType.FRAME: "quickNav.frame",
    QuickNavType.BLOCK_QUOTE: "quickNav.blockQuote",
    QuickNavType.SEPARATOR: "ctrlType.separator",
    QuickNavType.PARAGRAPH: "quickNav.paragraph",
    QuickNavType.ANNOTATION: "quickNav.annotation",
}


# --------------------------------------------------------------------------- #
# Matching tables consumed by browse_mode. ``CONTROL_TYPE_MATCH`` holds the
# uiautomation ``ControlTypeName`` strings that satisfy a type; ``ARIA_MATCH``
# holds substrings looked for (lower-cased) in an element's LocalizedControlType
# / ItemStatus, which is how Chromium/Gecko expose ARIA roles.
# --------------------------------------------------------------------------- #
_HEADINGS = (QuickNavType.HEADING, QuickNavType.HEADING1, QuickNavType.HEADING2,
             QuickNavType.HEADING3, QuickNavType.HEADING4, QuickNavType.HEADING5,
             QuickNavType.HEADING6)
_LINKS = (QuickNavType.LINK, QuickNavType.UNVISITED_LINK, QuickNavType.VISITED_LINK)
_FORM_FIELDS = (QuickNavType.FORM_FIELD, QuickNavType.EDIT_FIELD, QuickNavType.BUTTON,
                QuickNavType.CHECKBOX, QuickNavType.RADIO_BUTTON, QuickNavType.COMBO_BOX)

CONTROL_TYPE_MATCH = {
    QuickNavType.LINK: ("HyperlinkControl",),
    QuickNavType.UNVISITED_LINK: ("HyperlinkControl",),
    QuickNavType.VISITED_LINK: ("HyperlinkControl",),
    QuickNavType.BUTTON: ("ButtonControl", "SplitButtonControl"),
    QuickNavType.EDIT_FIELD: ("EditControl", "DocumentControl"),
    QuickNavType.COMBO_BOX: ("ComboBoxControl",),
    QuickNavType.CHECKBOX: ("CheckBoxControl",),
    QuickNavType.RADIO_BUTTON: ("RadioButtonControl",),
    QuickNavType.LIST: ("ListControl",),
    QuickNavType.LIST_ITEM: ("ListItemControl",),
    QuickNavType.TABLE: ("TableControl", "DataGridControl"),
    QuickNavType.TABLE_CELL: ("DataItemControl", "HeaderItemControl"),
    QuickNavType.GRAPHIC: ("ImageControl",),
    QuickNavType.SEPARATOR: ("SeparatorControl",),
    QuickNavType.FRAME: ("DocumentControl",),
    QuickNavType.FORM_FIELD: ("EditControl", "ComboBoxControl", "CheckBoxControl",
                              "RadioButtonControl", "ButtonControl"),
    QuickNavType.PARAGRAPH: ("TextControl",),
}

ARIA_MATCH = {
    QuickNavType.LINK: ("link",),
    QuickNavType.UNVISITED_LINK: ("link",),
    QuickNavType.VISITED_LINK: ("link",),
    QuickNavType.BUTTON: ("button",),
    QuickNavType.EDIT_FIELD: ("edit", "text box", "textbox", "search"),
    QuickNavType.COMBO_BOX: ("combo", "combobox", "listbox"),
    QuickNavType.CHECKBOX: ("check",),
    QuickNavType.RADIO_BUTTON: ("radio",),
    QuickNavType.LIST: ("list",),
    QuickNavType.LIST_ITEM: ("list item", "listitem"),
    QuickNavType.TABLE: ("table", "grid"),
    QuickNavType.GRAPHIC: ("image", "img", "graphic"),
    QuickNavType.SEPARATOR: ("separator",),
    QuickNavType.LANDMARK: ("navigation", "main", "banner", "contentinfo",
                            "complementary", "search", "region", "form"),
    QuickNavType.FRAME: ("document", "frame"),
    QuickNavType.BLOCK_QUOTE: ("blockquote", "block quote"),
    QuickNavType.PARAGRAPH: ("paragraph",),
    QuickNavType.ANNOTATION: ("annotation", "comment"),
}


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #
def type_for_key(key):
    """Map a pressed character to a :class:`QuickNavType` (NONE if not a key)."""
    if not key:
        return QuickNavType.NONE
    return KEY_TO_TYPE.get(str(key).lower(), QuickNavType.NONE)


def is_quick_nav_key(key):
    """True if ``key`` is bound to a quick-navigation type."""
    return bool(key) and str(key).lower() in KEY_TO_TYPE


def is_heading(qn_type):
    return qn_type in _HEADINGS


def is_link(qn_type):
    return qn_type in _LINKS


def is_form_field(qn_type):
    return qn_type in _FORM_FIELDS


def heading_level(qn_type):
    """Specific heading level requested (1-6), or 0 for any heading."""
    return {
        QuickNavType.HEADING1: 1, QuickNavType.HEADING2: 2, QuickNavType.HEADING3: 3,
        QuickNavType.HEADING4: 4, QuickNavType.HEADING5: 5, QuickNavType.HEADING6: 6,
    }.get(qn_type, 0)


def type_label(qn_type):
    """Localized spoken name for ``qn_type`` (falls back to its enum name)."""
    from titan_access.localization import L
    key = _TYPE_LABEL_KEY.get(qn_type)
    if key:
        return L(key)
    return getattr(qn_type, "name", str(qn_type)).lower().replace("_", " ")

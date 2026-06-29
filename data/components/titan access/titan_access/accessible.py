# -*- coding: utf-8 -*-
"""Element description for Titan Access.

Python port of the announcement-assembly logic in the C# ``ScreenReaderEngine``
(``AnnounceElement`` plus ``UIAutomationHelper.FormatElementDescription``). Turns
an :class:`~titan_access.contracts.AccessibleObject` into a *pitched* three-part
announcement, honouring the user's verbosity settings:

    name   @ NAME_PITCH  (0)   the accessible name (plus value for fields)
    role   @ ROLE_PITCH  (-4)  the control type, e.g. "Button"
    state  @ STATE_PITCH (+4)  checked / selected / expanded / ...

followed by optional context spoken at the neutral pitch: list position
("3 of 10"), hierarchy level ("level 2") and a parameter such as a link URL.

The engine speaks each ``(text, pitch_offset)`` segment at its own pitch (see
``TitanAccessEngine.speak_segments``); a TTS path without pitch control flattens
the list back to one line, for which :func:`describe_line` is provided.

Pitches are defined locally (NOT imported from :mod:`titan_access.engine`) to
avoid a circular import; they intentionally mirror the engine's constants.
"""

from typing import List, Optional, Tuple

from titan_access import localization as loc
from titan_access.localization import L, role_label, state_label
from titan_access.contracts import (
    AccessibleObject,
    ROLE_BUTTON, ROLE_SPLIT_BUTTON, ROLE_EDIT, ROLE_PASSWORD, ROLE_CHECKBOX,
    ROLE_RADIO, ROLE_COMBOBOX, ROLE_LISTITEM, ROLE_TREEITEM, ROLE_MENUITEM,
    ROLE_TAB, ROLE_SLIDER, ROLE_SPINNER, ROLE_PROGRESSBAR, ROLE_SCROLLBAR,
    ROLE_LINK, ROLE_TEXT, ROLE_HEADING, ROLE_IMAGE, ROLE_CELL, ROLE_GRIDITEM,
    ROLE_LISTBOX, ROLE_TREE, ROLE_TABLE, ROLE_GRID, ROLE_GROUP, ROLE_TOOLBAR,
    ROLE_STATUSBAR, ROLE_MENU, ROLE_MENUBAR, ROLE_TABCONTROL, ROLE_DIALOG,
    ROLE_WINDOW, ROLE_PANE, ROLE_DOCUMENT, ROLE_SEPARATOR,
    STATE_SELECTED, STATE_CHECKED, STATE_UNCHECKED, STATE_PARTIAL, STATE_EXPANDED,
    STATE_COLLAPSED, STATE_PRESSED, STATE_UNAVAILABLE, STATE_READONLY,
    STATE_REQUIRED, STATE_PROTECTED, STATE_BUSY, STATE_HASPOPUP,
)

# Pitches for the three-part announcement. Mirror the engine constants; kept
# local on purpose to avoid importing the engine (circular import).
NAME_PITCH = 0
ROLE_PITCH = -4
STATE_PITCH = 4

# Offscreen has no contracts constant but localization understands the literal.
_STATE_OFFSCREEN = "offscreen"


# --------------------------------------------------------------------------- #
# Role classification — which verbosity flag gates the control-type segment.
# --------------------------------------------------------------------------- #
# "Basic" controls are the simple interactive widgets; "block" controls are the
# structural containers. The control type is only spoken when its class is
# enabled (Verbosity/AnnounceBasicControls or Verbosity/AnnounceBlockControls).
_BASIC_ROLES = {
    ROLE_BUTTON, ROLE_SPLIT_BUTTON, ROLE_EDIT, ROLE_PASSWORD, ROLE_CHECKBOX,
    ROLE_RADIO, ROLE_COMBOBOX, ROLE_LISTITEM, ROLE_TREEITEM, ROLE_MENUITEM,
    ROLE_TAB, ROLE_SLIDER, ROLE_SPINNER, ROLE_PROGRESSBAR, ROLE_SCROLLBAR,
    ROLE_LINK, ROLE_TEXT, ROLE_HEADING, ROLE_IMAGE, ROLE_CELL, ROLE_GRIDITEM,
}
_BLOCK_ROLES = {
    ROLE_LISTBOX, ROLE_TREE, ROLE_TABLE, ROLE_GRID, ROLE_GROUP, ROLE_TOOLBAR,
    ROLE_STATUSBAR, ROLE_MENU, ROLE_MENUBAR, ROLE_TABCONTROL, ROLE_DIALOG,
    ROLE_WINDOW, ROLE_PANE, ROLE_DOCUMENT, ROLE_SEPARATOR,
}

# Order in which states are announced (focused/offscreen handled separately).
_STATE_ORDER = (
    STATE_SELECTED, STATE_CHECKED, STATE_PARTIAL, STATE_EXPANDED,
    STATE_COLLAPSED, STATE_PRESSED, STATE_UNAVAILABLE, STATE_READONLY,
    STATE_REQUIRED, STATE_PROTECTED, STATE_BUSY, STATE_HASPOPUP,
    _STATE_OFFSCREEN,
)


def _role_class_enabled(role, settings) -> bool:
    """Is the control type for ``role`` allowed by the verbosity settings?"""
    if role in _BLOCK_ROLES:
        return settings.get_bool("Verbosity", "AnnounceBlockControls", True)
    # Basic controls and anything unclassified follow the basic-controls flag.
    return settings.get_bool("Verbosity", "AnnounceBasicControls", True)


def _name_segment(obj: AccessibleObject) -> str:
    """Accessible name, with the value appended for fields when it adds info."""
    name = (obj.name or "").strip()
    value = (obj.value or "").strip()
    if value and value != name and obj.role in (
            ROLE_EDIT, ROLE_COMBOBOX, ROLE_SLIDER, ROLE_SPINNER,
            ROLE_PROGRESSBAR, ROLE_DOCUMENT):
        # Never speak the literal content of a protected field.
        if obj.role == ROLE_PASSWORD or obj.has(STATE_PROTECTED):
            return name
        return f"{name}, {value}".strip(", ").strip()
    return name


def _state_segment(obj: AccessibleObject) -> str:
    """Comma-joined localized state labels (focus is implied, so omitted)."""
    parts = [state_label(s) for s in _STATE_ORDER if obj.has(s)]
    # A check box that is neither checked nor indeterminate carries no state from
    # the provider, so its state would be silent. Announce it explicitly as
    # "unchecked" so the user always hears the box's state.
    if obj.role == ROLE_CHECKBOX and not (
            obj.has(STATE_CHECKED) or obj.has(STATE_PARTIAL)):
        unchecked = state_label(STATE_UNCHECKED)
        if unchecked:
            parts.append(unchecked)
    return ", ".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def describe(obj: Optional[AccessibleObject], settings,
             for_navigation: bool = False,
             role_label_override: Optional[str] = None
             ) -> List[Tuple[str, int]]:
    """Build the pitched announcement for ``obj``.

    Returns a list of ``(text, pitch_offset)`` segments. ``for_navigation`` is
    set when the user moved here with object navigation; with the
    ``Navigation/AnnounceControlTypesNavigation`` setting on, that forces the
    control type to be spoken even if ``ElementType`` is otherwise off.

    ``role_label_override``, when given, replaces the spoken control type (and
    forces it to be spoken even if the type segment is otherwise off). The host
    app supplies it for widgets whose UIA role is too generic -- e.g. a
    status-bar slot read as "status bar item" rather than "list item".
    """
    if obj is None:
        return [(L("element.none"), NAME_PITCH)]

    segments: List[Tuple[str, int]] = []

    want_name = settings.get_bool("Verbosity", "ElementName", True)
    want_type = settings.get_bool("Verbosity", "ElementType", True)
    want_state = settings.get_bool("Verbosity", "ElementState", True)
    want_param = settings.get_bool("Verbosity", "ElementParameter", True)
    want_desc = settings.get_bool("Verbosity", "ElementDescription", True)
    want_position = settings.get_bool("Verbosity", "AnnounceListPosition", True)
    want_level = settings.get_bool("Navigation", "AnnounceHierarchyLevel", True)

    # 1) Name (+ value) at the neutral pitch.
    name = _name_segment(obj)
    if want_name and name:
        segments.append((name, NAME_PITCH))

    # 2) Control type at a lower pitch.
    if role_label_override:
        # The host pinned an exact control-type label for this announcement;
        # speak it regardless of the verbosity flags.
        segments.append((role_label_override, ROLE_PITCH))
    else:
        type_forced = (for_navigation and
                       settings.get_bool("Navigation",
                                         "AnnounceControlTypesNavigation", True))
        if (want_type or type_forced) and _role_class_enabled(obj.role, settings):
            role_text = role_label(obj.role)
            if role_text:
                segments.append((role_text, ROLE_PITCH))

    # 3) States at a higher pitch.
    if want_state:
        state_text = _state_segment(obj)
        if state_text:
            segments.append((state_text, STATE_PITCH))

    # 3b) Description at the neutral pitch. Carries the UIA full description AND
    # any enrichment an app module appended in ``customize_object`` (the file
    # type in Explorer, the document statistics in Notepad, the calculator
    # display, ...). NVDA reads object descriptions by default; without this the
    # whole app-module customisation layer was silently dropped. Skipped when it
    # merely repeats the name or value so we never say the same thing twice.
    if want_desc:
        desc = (obj.description or "").strip()
        value = (obj.value or "").strip()
        if desc and desc != name and desc != value:
            segments.append((desc, NAME_PITCH))

    # 4) List / collection position ("3 of 10").
    if want_position and obj.pos_in_set > 0 and obj.size_of_set > 0:
        segments.append(
            (L("element.positionOf", obj.pos_in_set, obj.size_of_set),
             NAME_PITCH))

    # 5) Hierarchy level ("level 2").
    if want_level and obj.level > 0:
        segments.append((L("engine.hierarchyLevel", obj.level), NAME_PITCH))

    # 6) Parameter (e.g. a link URL).
    if want_param and obj.parameter:
        segments.append((obj.parameter, NAME_PITCH))

    # Make sure we always say *something* (e.g. all verbosity off, no name).
    if not segments:
        segments.append((role_label(obj.role) or L("element.unknown"), NAME_PITCH))

    return segments


def describe_line(obj: Optional[AccessibleObject], settings,
                  for_navigation: bool = False) -> str:
    """Flatten :func:`describe` into a single string for non-pitched output."""
    return ", ".join(text for text, _pitch in describe(obj, settings,
                                                        for_navigation)
                     if text)

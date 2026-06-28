# -*- coding: utf-8 -*-
"""Presentation-type classification for Titan Access (NVDA port).

Port of NVDA's ``NVDAObjects.NVDAObject._get_presentationType`` plus the
``_findSimpleNext`` / simple-navigation helpers (``source/NVDAObjects/__init__.py``).
NVDA classifies every object as one of:

* ``CONTENT``     — meaningful to the user (interactive control, or static text
  with actual text), announced and stepped onto during navigation;
* ``LAYOUT``      — a structural / presentational container (unnamed pane, group,
  custom, window wrapper), **skipped** while navigating but descended through;
* ``UNAVAILABLE`` — invisible / offscreen, ignored.

Both object navigation (:mod:`titan_access.object_nav`) and the browse-mode
virtual buffer (:mod:`titan_access.browse_mode`) use this so the user moves only
between content elements (NVDA's "simple review mode"), instead of stopping on
every wrapper pane.

All functions operate on a vendored ``uiautomation.Control`` and never raise.
"""

CONTENT = "content"
LAYOUT = "layout"
UNAVAILABLE = "unavailable"

# Interactive / inherently-meaningful control types: always content when visible.
_CONTENT_CTYPES = {
    "ButtonControl", "SplitButtonControl", "CheckBoxControl", "RadioButtonControl",
    "ComboBoxControl", "EditControl", "DocumentControl", "HyperlinkControl",
    "ListItemControl", "TreeItemControl", "MenuItemControl", "TabItemControl",
    "SliderControl", "SpinnerControl", "ProgressBarControl", "ScrollBarControl",
    "DataItemControl", "HeaderItemControl", "CalendarControl", "MenuControl",
}
# Pure layout/structural containers: content only when they carry a name.
_LAYOUT_CTYPES = {
    "PaneControl", "GroupControl", "CustomControl", "WindowControl",
    "TitleBarControl", "ThumbControl", "ToolTipControl",
}

# Recursion budget so a pathological tree can never stall the worker thread.
_BUDGET = 600


def presentation_type(control):
    """Classify *control* as CONTENT / LAYOUT / UNAVAILABLE (NVDA presType)."""
    if control is None:
        return UNAVAILABLE
    try:
        if control.IsOffscreen:
            return UNAVAILABLE
    except Exception:
        pass
    try:
        ct = control.ControlTypeName or ""
    except Exception:
        return LAYOUT
    try:
        name = (control.Name or "").strip()
    except Exception:
        name = ""
    if ct in _CONTENT_CTYPES:
        return CONTENT
    if ct == "TextControl":
        return CONTENT if name else LAYOUT
    if ct in _LAYOUT_CTYPES:
        return CONTENT if name else LAYOUT
    # Other named containers (list / tree / table / toolbar / image …) are
    # content when labelled, otherwise treated as layout and skipped.
    return CONTENT if name else LAYOUT


# --------------------------------------------------------------------------- #
# Raw tree accessors (None-safe)
# --------------------------------------------------------------------------- #
def _first_child(c):
    try:
        return c.GetFirstChildControl()
    except Exception:
        return None


def _last_child(c):
    try:
        return c.GetLastChildControl()
    except Exception:
        return None


def _next(c):
    try:
        return c.GetNextSiblingControl()
    except Exception:
        return None


def _previous(c):
    try:
        return c.GetPreviousSiblingControl()
    except Exception:
        return None


def _parent(c):
    try:
        return c.GetParentControl()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Simple (flattened) navigation — faithful port of NVDA's _findSimpleNext
# --------------------------------------------------------------------------- #
def _find_simple_next(c, use_child=False, use_parent=True, go_previous=False,
                      budget=None):
    if budget is None:
        budget = [_BUDGET]
    if c is None or budget[0] <= 0:
        return None
    budget[0] -= 1

    first_last = _last_child if go_previous else _first_child
    sibling = _previous if go_previous else _next

    found = None
    if use_child:
        child = first_last(c)
        ptype = presentation_type(child) if child is not None else None
        if ptype == CONTENT:
            found = child
        elif ptype == LAYOUT:
            found = _find_simple_next(child, use_child=True, use_parent=False,
                                      go_previous=go_previous, budget=budget)
        elif child is not None:
            found = _find_simple_next(child, use_child=False, use_parent=False,
                                      go_previous=go_previous, budget=budget)
    if found is not None:
        return found

    nxt = sibling(c)
    ptype = presentation_type(nxt) if nxt is not None else None
    if ptype == CONTENT:
        found = nxt
    elif ptype == LAYOUT:
        found = _find_simple_next(nxt, use_child=True, use_parent=False,
                                  go_previous=go_previous, budget=budget)
    elif nxt is not None:
        found = _find_simple_next(nxt, use_child=False, use_parent=False,
                                  go_previous=go_previous, budget=budget)
    if found is not None:
        return found

    parent = _parent(c) if use_parent else None
    while parent is not None and budget[0] > 0:
        budget[0] -= 1
        nxt = sibling(parent)
        ptype = presentation_type(nxt) if nxt is not None else None
        if ptype == CONTENT:
            found = nxt
        elif ptype == LAYOUT:
            found = _find_simple_next(nxt, use_child=True, use_parent=False,
                                      go_previous=go_previous, budget=budget)
        elif nxt is not None:
            found = _find_simple_next(nxt, use_child=False, use_parent=False,
                                      go_previous=go_previous, budget=budget)
        if found is not None:
            return found
        parent = _parent(parent)
    return None


def simple_next(c):
    return _find_simple_next(c, go_previous=False)


def simple_previous(c):
    return _find_simple_next(c, go_previous=True)


def simple_parent(c):
    parent = _parent(c)
    guard = 0
    while parent is not None and guard < 64:
        if presentation_type(parent) == CONTENT:
            return parent
        parent = _parent(parent)
        guard += 1
    return parent


def simple_first_child(c):
    child = _first_child(c)
    if child is None:
        return None
    ptype = presentation_type(child)
    if ptype == LAYOUT:
        return _find_simple_next(child, use_child=True, use_parent=False)
    if ptype == UNAVAILABLE:
        return simple_next(child)
    return child

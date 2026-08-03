# -*- coding: utf-8 -*-
"""What Windows itself can still tell us about the window being read.

An app is rarely *completely* inaccessible. A game launcher draws its own
buttons but keeps a real title bar; an Electron app exposes half a tree; an
installer is a normal dialog with one custom-painted page. Where UI Automation
does answer, its answer is exact - the real rectangle, the real enabled state,
the real value - and a vision model's estimate of the same thing is not.

So AI OCR reads both and lets Windows win on geometry and state wherever the
two are talking about the same control. On a genuinely inaccessible window this
returns nothing and the AI's reading stands alone, which is the case the whole
feature exists for; the merge simply costs nothing there.

Everything runs through :func:`src.ai.ui_tools._uia_call`, which owns the COM
apartment the rest of Titan's UIA code uses - creating a second one from a
different thread is what produced the COM crashes this codebase has already
been through once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class UIAElement:
    name: str
    role: str
    value: str
    enabled: bool
    rect: Tuple[int, int, int, int]      # screen pixels: left, top, right, bottom
    # Only present when the control exposes the matching pattern. These are the
    # facts a picture can only be guessed at: a slider's real range, whether a
    # tick box is really ticked.
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    number: Optional[float] = None
    checked: Optional[bool] = None

    @property
    def centre(self) -> Tuple[int, int]:
        left, top, right, bottom = self.rect
        return ((left + right) // 2, (top + bottom) // 2)


# UIA control type -> our roles. Only the ones that mean something different
# from 'other' are listed.
_ROLE_BY_TYPE = {
    'button': 'button', 'check box': 'checkbox', 'combo box': 'combobox',
    'edit': 'edit', 'link': 'link', 'list item': 'listitem', 'list': 'other',
    'menu item': 'menuitem', 'progress bar': 'progress',
    'radio button': 'radio', 'slider': 'slider', 'tab item': 'tab',
    'text': 'text', 'image': 'image', 'hyperlink': 'link',
}


def snapshot(max_items: int = 250) -> List[UIAElement]:
    """Every named control of the foreground window, or [] when there are none."""
    try:
        from src.ai import ui_tools
    except Exception:
        return []
    try:
        return ui_tools._uia_call(lambda: _snapshot_impl(ui_tools, max_items),
                                  timeout=20) or []
    except Exception as exc:
        print(f"[AI OCR] UI Automation snapshot failed: {exc}")
        return []


def _snapshot_impl(ui_tools, max_items: int) -> List[UIAElement]:
    root = ui_tools._foreground_element()
    if root is None:
        return []
    out: List[UIAElement] = []
    for element in ui_tools._walk_elements(root):
        if len(out) >= max_items:
            break
        try:
            if ui_tools._el_offscreen(element):
                continue
            name = ui_tools._el_name(element) or ''
            value = ui_tools._el_value(element) or ''
            if not name and not value:
                continue
            rect = ui_tools._el_rect(element)
            if not rect:
                continue
            left, top, right, bottom = rect
            if right - left < 2 or bottom - top < 2:
                continue
            control_type = ui_tools._el_type(element) or ''
            low, high, number = _range_of(ui_tools, element)
            out.append(UIAElement(
                name=name.strip(), role=_ROLE_BY_TYPE.get(control_type, 'other'),
                value=value.strip(), enabled=bool(ui_tools._el_enabled(element)),
                rect=(left, top, right, bottom),
                minimum=low, maximum=high, number=number,
                checked=_checked_state(ui_tools, element)))
        except Exception:
            continue
    return out


# UIA_RangeValuePatternId - a slider, a meter, a spin box.
_P_RANGE_VALUE = 10003


def _range_of(ui_tools, element):
    """(minimum, maximum, value) from the range pattern, or three Nones."""
    pattern = ui_tools._pattern(element, _P_RANGE_VALUE,
                                'IUIAutomationRangeValuePattern')
    if pattern is None:
        return None, None, None
    try:
        return (float(pattern.CurrentMinimum), float(pattern.CurrentMaximum),
                float(pattern.CurrentValue))
    except Exception:
        return None, None, None


def _checked_state(ui_tools, element):
    """True / False from the toggle or selection pattern, else None."""
    toggle = ui_tools._pattern(element, ui_tools._P_TOGGLE,
                               'IUIAutomationTogglePattern')
    if toggle is not None:
        try:
            # 0 = off, 1 = on, 2 = indeterminate (which is neither).
            state = int(toggle.CurrentToggleState)
            if state in (0, 1):
                return bool(state)
            return None
        except Exception:
            pass
    selection = ui_tools._pattern(element, ui_tools._P_SELECTION_ITEM,
                                  'IUIAutomationSelectionItemPattern')
    if selection is not None:
        try:
            return bool(selection.CurrentIsSelected)
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
# Merging
# --------------------------------------------------------------------------- #
def merge(screen, capture, elements: List[UIAElement]) -> int:
    """Correct ``screen`` in place from ``elements``. Returns how many matched.

    Matching is by name, not by position: a vision model gets a label right far
    more often than it gets a rectangle right, so the name is the reliable key
    and the rectangle is the thing worth replacing. A match also brings the
    real enabled state with it - "the Install button is greyed out" is exactly
    the kind of thing a picture makes ambiguous and Windows makes certain.
    """
    if not elements or screen is None or capture is None:
        return 0

    by_name = {}
    for element in elements:
        key = _normalise(element.name)
        if key and key not in by_name:
            by_name[key] = element

    matched = 0
    for target in screen.elements:
        key = _normalise(target.name)
        if not key:
            continue
        found = by_name.get(key)
        if found is None:
            continue
        target.rect = _to_image_rect(capture, found.rect)
        target.source = 'merged'
        if found.value and not target.value:
            target.value = found.value
        # A slider's range and a tick box's state are facts Windows holds and a
        # picture can only imply. Taking them here is what lets the mimic put a
        # real wx.Slider on screen instead of a pair of nudge buttons.
        if found.minimum is not None and found.maximum is not None:
            target.minimum, target.maximum = found.minimum, found.maximum
            if found.number is not None:
                target.value = _format_number(found.number)
        if found.checked is not None:
            target.state = _with_checked(target.state, found.checked)
        if not found.enabled:
            if 'disabled' not in (target.state or '').lower():
                target.state = (target.state + ', disabled').strip(', ') \
                    if target.state else 'disabled'
        elif 'disabled' in (target.state or '').lower():
            # The model read a control as greyed out that Windows says is live.
            # Windows is right, and the difference matters: a user who is told
            # a button is disabled does not press it.
            target.state = ', '.join(
                part for part in (target.state or '').split(',')
                if 'disabled' not in part.lower()).strip(', ')
        matched += 1
    return matched


def add_missing(screen, capture, elements: List[UIAElement], region_name: str) -> int:
    """Add controls UI Automation can see that the model did not mention.

    Deliberately separate from :func:`merge` and used only when the model found
    very little: on a normal window this would double every entry, but on a
    window the model could barely read it is the difference between a usable
    mimic and an empty one.
    """
    from src.ai.ocr.model import Element, Region

    if not elements or screen is None:
        return 0
    known = {_normalise(item.name) for item in screen.elements if item.name}
    extra = []
    for found in elements:
        key = _normalise(found.name)
        if not key or key in known:
            continue
        known.add(key)
        state = '' if found.enabled else 'disabled'
        if found.checked is not None:
            state = _with_checked(state, found.checked)
        extra.append(Element(
            name=found.name, role=found.role,
            value=(_format_number(found.number) if found.number is not None
                   else found.value),
            state=state, minimum=found.minimum, maximum=found.maximum,
            rect=_to_image_rect(capture, found.rect),
            source='uia', region=region_name))
    if extra:
        screen.regions.append(Region(name=region_name, role='content',
                                     elements=extra))
    return len(extra)


def _to_image_rect(capture, rect: Tuple[int, int, int, int]):
    """Screen rectangle -> the image coordinates the rest of the code speaks."""
    left, top, right, bottom = rect
    factor = max(1, capture.factor)
    origin_x, origin_y = capture.origin
    return ((left - origin_x) / float(factor), (top - origin_y) / float(factor),
            max(1.0, (right - left) / float(factor)),
            max(1.0, (bottom - top) / float(factor)))


def _normalise(name: str) -> str:
    """Compare labels the way a person would: case and padding do not count."""
    return ' '.join((name or '').split()).strip().lower()


def _format_number(value: float) -> str:
    """A number the way a person writes it: 70, not 70.0."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip('0').rstrip('.')


def _with_checked(state: str, checked: bool) -> str:
    """Replace whatever the picture said about ticked-ness with the truth."""
    kept = [part.strip() for part in (state or '').split(',')
            if part.strip() and 'check' not in part.strip().lower()]
    kept.append('checked' if checked else 'unchecked')
    return ', '.join(kept)

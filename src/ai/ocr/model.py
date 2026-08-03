# -*- coding: utf-8 -*-
"""The Screen model: what the AI has to produce, and what the mimic renders.

This is the contract between a language model and an accessible window, so it
is deliberately small and deliberately strict.

* **Small**, because every field is something the model has to get right, and a
  schema with thirty keys is a schema with thirty ways to be wrong.
* **Strict**, because the output drives real clicks. Anything unparseable,
  out of bounds or self-contradictory is dropped here rather than shown to the
  user as if it were real. A mimic that silently omits a button is annoying; a
  mimic that offers a button which is actually somewhere else is dangerous.

A screen is regions, a region is elements. That is the whole shape: it maps
one-to-one onto the Titan tab-bar-and-list interaction, so the renderer needs
no cleverness, and it is a shape vision models are reliably good at.

``from_ai`` never raises: a model that returns half a document, prose around
the JSON or an unknown role produces the best Screen that can be salvaged plus
a warning, because "here is most of the menu" beats an error message.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# What a control can be. Anything else the model invents is mapped to 'other'
# rather than rejected - a new role is a naming difference, not a failure.
ROLES = (
    'button', 'menuitem', 'listitem', 'tab', 'checkbox', 'radio', 'link',
    'edit', 'combobox', 'slider', 'progress', 'value', 'heading', 'text',
    'image', 'other',
)

# Roles a user can press. Text and headings are readable, not pressable.
ACTIONABLE_ROLES = frozenset({
    'button', 'menuitem', 'listitem', 'tab', 'checkbox', 'radio', 'link',
    'edit', 'combobox', 'slider', 'other',
})

# What kind of screen this is. Drives nothing but the spoken summary - the
# renderer is the same either way - but it is what tells a user whether they
# are looking at a menu or at a game's heads-up display.
KINDS = ('menu', 'dialog', 'form', 'document', 'table', 'hud', 'desktop',
         'error', 'unknown')

_ROLE_ALIASES = {
    'menu item': 'menuitem', 'menu_item': 'menuitem',
    'list item': 'listitem', 'list_item': 'listitem', 'option': 'listitem',
    'check box': 'checkbox', 'checkbutton': 'checkbox',
    'radio button': 'radio', 'radiobutton': 'radio',
    'textbox': 'edit', 'text box': 'edit', 'textfield': 'edit',
    'input': 'edit', 'field': 'edit',
    'dropdown': 'combobox', 'select': 'combobox', 'combo box': 'combobox',
    'label': 'text', 'paragraph': 'text', 'static': 'text',
    'title': 'heading', 'header': 'heading',
    'progressbar': 'progress', 'progress bar': 'progress',
    'icon': 'image', 'picture': 'image',
    'hyperlink': 'link',
}


@dataclass
class Element:
    """One thing on the screen."""

    name: str = ''
    role: str = 'text'
    value: str = ''
    state: str = ''              # free text: 'disabled', 'checked', 'selected'
    text: str = ''               # the full body when the name is only a label
    rect: Optional[Tuple[float, float, float, float]] = None   # image pixels
    hint: str = ''
    # Range for a slider, a meter or a progress bar. A slider whose range is
    # unknown can still be nudged, but it cannot be given a value - so this is
    # what decides whether the mimic offers a real wx.Slider or two buttons.
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    source: str = 'ai'           # 'ai' | 'uia' | 'merged'
    region: str = ''             # filled in by Screen, for flat listings

    @property
    def enabled(self) -> bool:
        return 'disabled' not in (self.state or '').lower()

    @property
    def actionable(self) -> bool:
        return (self.role in ACTIONABLE_ROLES and self.rect is not None
                and self.enabled)

    @property
    def checked(self) -> Optional[bool]:
        """True / False for a tick box, None when the state does not say."""
        state = (self.state or '').lower()
        if 'unchecked' in state or 'not checked' in state:
            return False
        if 'checked' in state or 'ticked' in state:
            return True
        if 'selected' in state and self.role in ('checkbox', 'radio'):
            return True
        return None

    @property
    def number(self) -> Optional[float]:
        """The value as a number, when it is one ("70", "70%", "7,5")."""
        raw = (self.value or '').strip().replace('%', '').replace(',', '.')
        raw = raw.split('/')[0].strip()        # "7/10" -> 7
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @property
    def has_range(self) -> bool:
        return (self.minimum is not None and self.maximum is not None
                and self.maximum > self.minimum)

    @property
    def editable(self) -> bool:
        """Can the mimic offer a real control that changes this?"""
        return (self.rect is not None and self.enabled
                and self.role in ('edit', 'checkbox', 'radio', 'slider',
                                  'combobox'))

    @property
    def key(self) -> str:
        """Identity across two separate readings of the same screen.

        Not the model's own ids: those are invented afresh every call, so
        ``e3`` in one answer has nothing to do with ``e3`` in the next. Name
        and role do survive, which is what makes a live diff possible.
        """
        return f"{self.region}|{self.role}|{(self.name or self.text)[:60].strip().lower()}"

    def spoken(self) -> str:
        """One line, in the order a screen reader would say it."""
        parts = []
        if self.name:
            parts.append(self.name)
        elif self.text:
            parts.append(self.text if len(self.text) <= 120
                         else self.text[:120] + '...')
        if self.value:
            parts.append(self.value)
        if self.role not in ('text', 'heading', 'other'):
            parts.append(self.role)
        if self.state:
            parts.append(self.state)
        return ', '.join(part for part in parts if part) or '(empty)'


@dataclass
class Region:
    """A part of the screen that belongs together: a panel, a menu, a dialog.

    ``rect`` is what makes a region more than a heading: it is the area the
    part occupies, so the reconstruction can build a real container there
    instead of stacking everything in a column.
    """

    name: str = ''
    role: str = 'content'
    elements: List[Element] = field(default_factory=list)
    rect: Optional[Tuple[float, float, float, float]] = None   # image pixels

    @property
    def label(self) -> str:
        return self.name or self.role or 'Screen'

    @property
    def is_window(self) -> bool:
        """A part that is a window in its own right on the real screen.

        A dialog, a popup or a message box drawn on top of everything else is
        not a panel of the screen behind it - it is another window. The
        reconstruction gives it another window too.
        """
        return self.role in ('dialog', 'window', 'popup', 'messagebox')


@dataclass
class Screen:
    """One reading of one screen."""

    title: str = ''
    kind: str = 'unknown'
    summary: str = ''
    regions: List[Region] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    taken_at: float = field(default_factory=time.time)
    capture: Any = None          # the Capture this was read from
    raw: str = ''                # the model's answer, for diagnostics

    @property
    def elements(self) -> List[Element]:
        out: List[Element] = []
        for region in self.regions:
            out.extend(region.elements)
        return out

    def region_named(self, name: str) -> Optional[Region]:
        for region in self.regions:
            if region.label == name:
                return region
        return None

    def diff(self, previous: Optional['Screen']) -> Dict[str, List[Element]]:
        """What changed since ``previous``: added, removed, changed.

        This is what live mode announces. Re-reading a whole HUD out loud every
        few seconds would be unusable; "Health 40" the moment it drops is the
        entire point of watching a screen.
        """
        empty: Dict[str, List[Element]] = {'added': [], 'removed': [], 'changed': []}
        if previous is None:
            return empty
        before = {element.key: element for element in previous.elements}
        after = {element.key: element for element in self.elements}
        for key, element in after.items():
            if key not in before:
                empty['added'].append(element)
            else:
                old = before[key]
                if (old.value or '') != (element.value or '') or \
                        (old.state or '') != (element.state or ''):
                    empty['changed'].append(element)
        for key, element in before.items():
            if key not in after:
                empty['removed'].append(element)
        return empty


# --------------------------------------------------------------------------- #
# Parsing the model's answer
# --------------------------------------------------------------------------- #
def from_ai(raw: str, capture=None) -> Screen:
    """Turn one model answer into a Screen, salvaging what can be salvaged."""
    screen = Screen(capture=capture, raw=raw or '')
    data = _load_json(raw)
    if data is None:
        screen.warnings.append('the model did not answer with usable JSON')
        # A model that ignored the format still read the screen - keep its prose
        # rather than showing the user nothing at all.
        prose = (raw or '').strip()
        if prose:
            screen.summary = prose[:2000]
            screen.regions = [Region(name='Text', role='content', elements=[
                Element(role='text', text=line.strip())
                for line in prose.splitlines() if line.strip()])]
        return screen

    screen.title = _clean(data.get('title'))
    screen.summary = _clean(data.get('summary'))
    kind = _clean(data.get('kind')).lower()
    screen.kind = kind if kind in KINDS else 'unknown'
    for warning in data.get('warnings') or []:
        text = _clean(warning)
        if text:
            screen.warnings.append(text)

    raw_regions = data.get('regions')
    if not isinstance(raw_regions, list) or not raw_regions:
        # Some models flatten the structure away entirely. An element list with
        # no regions is a perfectly good screen with exactly one region.
        raw_regions = [{'name': screen.title or 'Screen',
                        'elements': data.get('elements') or []}]

    dropped = 0
    for raw_region in raw_regions:
        if not isinstance(raw_region, dict):
            continue
        region_rect = _rect_from(raw_region.get('rect')
                                 or raw_region.get('bounds'))
        if region_rect is not None and capture is not None \
                and not capture.contains_rect(region_rect):
            region_rect = None
        region = Region(name=_clean(raw_region.get('name')),
                        role=(_clean(raw_region.get('role')) or 'content').lower(),
                        rect=region_rect)
        for raw_element in raw_region.get('elements') or []:
            element, was_dropped = _element_from(raw_element, region.label, capture)
            dropped += was_dropped
            if element is not None:
                region.elements.append(element)
        if region.elements:
            screen.regions.append(region)

    if dropped:
        # Said out loud, because a silently shorter list is how a user ends up
        # believing a button is not there.
        screen.warnings.append(
            f"{dropped} element(s) were reported at impossible positions and "
            f"were left out")
    if not screen.regions:
        screen.warnings.append('nothing readable was found on this screen')
    return screen


def _element_from(data: Any, region_label: str, capture) -> Tuple[Optional[Element], int]:
    if not isinstance(data, dict):
        return None, 0

    name = _clean(data.get('name') or data.get('label'))
    text = _clean(data.get('text'))
    if not name and not text and not _clean(data.get('value')):
        return None, 0

    role = _clean(data.get('role') or data.get('type')).lower()
    role = _ROLE_ALIASES.get(role, role)
    if role not in ROLES:
        role = 'other' if role else 'text'

    rect = _rect_from(data.get('rect') or data.get('box') or data.get('bounds'))
    dropped = 0
    if rect is not None and capture is not None and not capture.contains_rect(rect):
        # Out of the picture entirely: keep what it says, refuse to click it.
        rect = None
        dropped = 1

    return Element(
        name=name, role=role, value=_clean(data.get('value')),
        state=_clean(data.get('state')), text=text, rect=rect,
        hint=_clean(data.get('hint')), region=region_label,
        minimum=_number(data.get('min')), maximum=_number(data.get('max'))), dropped


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace('%', '').replace(',', '.').strip())
    except (TypeError, ValueError):
        return None


def _rect_from(value: Any) -> Optional[Tuple[float, float, float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, w, h = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def _clean(value: Any) -> str:
    if value is None:
        return ''
    text = str(value).replace('\r', ' ').strip()
    return re.sub(r'[ \t]{2,}', ' ', text)


def _load_json(raw: str) -> Optional[Dict[str, Any]]:
    """Find the JSON object in the answer, however it was wrapped."""
    if not raw:
        return None
    text = raw.strip()
    # A fenced block, with or without a language tag.
    fence = re.search(r'```(?:json)?\s*(.*?)```', text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {'elements': data}
    except Exception:
        pass
    # Prose around the object: take the outermost braces.
    start, end = text.find('{'), text.rfind('}')
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            pass
    # A bare array of elements.
    start, end = text.find('['), text.rfind(']')
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, list):
                return {'elements': data}
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
# The schema the model is given. Kept next to the parser on purpose: the two
# drift apart the moment they live in different files.
# --------------------------------------------------------------------------- #
SCHEMA_TEXT = """{
  "title": "<what this screen is, in a few words>",
  "kind": "menu|dialog|form|document|table|hud|desktop|error|unknown",
  "summary": "<one or two sentences: what a person who cannot see it needs to know first>",
  "regions": [
    {
      "name": "<what this part of the screen is, e.g. Main menu, Toolbar, Status bar>",
      "role": "menu|toolbar|list|content|status|hud|group|panel|dialog|popup",
      "rect": [x, y, width, height],
      "elements": [
        {
          "name": "<the visible label, transcribed exactly>",
          "role": "button|menuitem|listitem|tab|checkbox|radio|link|edit|combobox|slider|progress|value|heading|text|image",
          "value": "<the current value, for a field, slider, meter or counter; otherwise empty>",
          "state": "<disabled|checked|unchecked|selected|focused, or empty>",
          "text": "<the full text, when this is a paragraph rather than a label>",
          "min": "<for a slider, meter or progress bar: the value at its low end, if it is written on screen>",
          "max": "<the same for its high end>",
          "rect": [x, y, width, height],
          "hint": "<only if something non-obvious matters, e.g. 'greyed out until the licence is scrolled to the end'>"
        }
      ]
    }
  ],
  "warnings": ["<anything you could not read, or are unsure about>"]
}"""


def elements_as_lines(screen: Screen) -> List[str]:
    """The whole screen as plain lines - what "copy everything" produces."""
    lines: List[str] = []
    if screen.title:
        lines.append(screen.title)
    if screen.summary:
        lines.append(screen.summary)
    for region in screen.regions:
        lines.append('')
        lines.append(f"[{region.label}]")
        for element in region.elements:
            lines.append('  ' + element.spoken())
    return lines

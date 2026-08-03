# -*- coding: utf-8 -*-
"""One Element -> one real wx control, wired to the real application.

This is the part that turns a *reading* into an *interface*. Both rebuilt views
use it, so they cannot drift apart:

    form_view.py   stacks the controls in a column inside the mimic window
    overlay.py     puts each control exactly where the real one is, on top of
                   the real window

The rules are the same in both, and they are what keep a rebuilt control
honest:

* **A control appears as itself or not at all.** A slider whose range nobody
  knows does not become an invented 0-100 scale - it becomes Less/More buttons,
  which is what the keyboard would do to it anyway. A closed combo box does not
  become a wx.Choice with guessed items - it becomes a button that opens the
  real one so the next reading can see what is in it.
* **Nothing is sent until the user commits.** Typing into a field does not type
  into the program letter by letter (which would fight with the program's own
  handling of every keystroke); the field is sent on Enter or on leaving it.
  A slider is sent when it is released, not on every tick of a drag.
* **The control shows what the program has**, not what the user asked for. The
  caller re-reads after every action and rebuilds from the new reading, so a
  value the program clamped or refused shows the value the program kept.
* **A disabled control is disabled.** It stays visible and stays where it is,
  exactly as a greyed-out button does in the program itself.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence

import wx

from src.ai.ocr.model import Element
from src.network.im_ui_common import _

# What ``on_action`` is called with. The caller maps these onto
# src.ai.ocr.actions - they are deliberately the vocabulary of the actions
# module rather than of wx, so a view never has to know how a click is made.
#   ('press',  element, None)     press it / open it
#   ('toggle', element, bool)     tick, untick, choose
#   ('text',   element, str)      replace the contents of a field
#   ('slider', element, float)    move a slider to a value
#   ('nudge',  element, int)      move a slider one step, +1 or -1
ActionCallback = Callable[[str, Element, object], None]

# Anything narrower than this cannot be focused with a mouse or seen at all, and
# a model that reports a two-pixel button has misread something. The control is
# still built - the entry is real - just at a size a person can use.
MIN_WIDTH = 28
MIN_HEIGHT = 20

# Above this a text element is a paragraph rather than a label, and gets a
# multi-line box so a screen reader can walk it line by line.
LONG_TEXT = 90


def has_real_controls(screen) -> bool:
    """Is there anything on this screen worth rebuilding as controls?

    A menu or a wall of text is more useful as a list; a settings page or a
    dialog is far more useful rebuilt. This is what decides which view a fresh
    reading opens in.
    """
    if screen is None:
        return False
    return any(element.editable for element in screen.elements)


def is_actionable(element: Element) -> bool:
    """Can this element be pressed or changed, as opposed to only read?"""
    return bool(element) and element.actionable


def build_control(parent: wx.Window, element: Element,
                  on_action: Optional[ActionCallback] = None,
                  first_in_group: bool = False) -> Optional[wx.Window]:
    """Build the one control that stands for ``element``.

    Returns a live wx window (never a sizer), already carrying its accessible
    name and its current value, or None when the element is not something a
    control can represent at all.

    ``first_in_group`` marks the radio button that starts a group - see
    :func:`group_starts`, which is what makes a set of option buttons behave
    like one set rather than like unrelated ticks.
    """
    role = element.role
    builder = _BUILDERS.get(role, _build_text)
    try:
        if role == 'radio':
            control = _build_radio(parent, element, on_action, first_in_group)
        else:
            control = builder(parent, element, on_action)
    except Exception as exc:            # a broken element must not kill the view
        print(f"[AI OCR] could not build a control for {element.name!r}: {exc}")
        return None
    if control is None:
        return None

    control.SetName(accessible_name(element))
    if not element.enabled:
        control.Disable()
    if element.hint:
        try:
            control.SetToolTip(element.hint)
        except Exception:
            pass
    control._ocr_element = element
    return control


def accessible_name(element: Element) -> str:
    """What a screen reader should say for this control.

    The role and the value are usually announced by the control itself (a
    wx.CheckBox says "checkbox, checked"), so this is the *label* - with the
    element's own text folded in when it has no label of its own, because an
    unnamed field is the one thing a screen reader cannot recover from.
    """
    name = element.name or element.text or element.value
    if not name:
        name = _("unlabelled {role}").format(role=element.role)
    if len(name) > 120:
        name = name[:120] + '...'
    if element.state and element.role in ('button', 'menuitem', 'listitem',
                                          'tab', 'link', 'other'):
        # Roles wx has no state of its own for: say it in the name or it is lost.
        name = f"{name}, {element.state}"
    return name


# --------------------------------------------------------------------------- #
# The builders
# --------------------------------------------------------------------------- #
def _build_button(parent, element, on_action):
    label = element.name or element.text or element.value or _("(unnamed)")
    if len(label) > 80:
        label = label[:80] + '...'
    button = wx.Button(parent, label=label, style=wx.BU_EXACTFIT)
    if on_action is not None:
        button.Bind(wx.EVT_BUTTON, lambda e: on_action('press', element, None))
    return button


def _build_combobox(parent, element, on_action):
    """A closed combo box: a button that opens the real one.

    What is *in* a combo box cannot be seen until it is open, and a wx.Choice
    filled with guesses would be a list of items that may not exist. Pressing
    this opens the real drop-down; the reading that follows sees the items and
    lists them as they are.
    """
    label = element.name or _("Drop-down list")
    if element.value:
        label = f"{label}: {element.value}"
    button = wx.Button(parent, label=label, style=wx.BU_EXACTFIT)
    if on_action is not None:
        button.Bind(wx.EVT_BUTTON, lambda e: on_action('press', element, None))
    return button


def _build_checkbox(parent, element, on_action):
    label = element.name or _("Option")
    if element.checked is None:
        # The reading could not tell whether it is ticked. A three-state box
        # says exactly that; a plain unticked one would be read as "off", which
        # is a statement about the program that nobody checked.
        box = wx.CheckBox(parent, label=label,
                          style=wx.CHK_3STATE | wx.CHK_ALLOW_3RD_STATE_FOR_USER)
        box.Set3StateValue(wx.CHK_UNDETERMINED)
    else:
        box = wx.CheckBox(parent, label=label)
        box.SetValue(bool(element.checked))
    if on_action is not None:
        box.Bind(wx.EVT_CHECKBOX,
                 lambda e: on_action('toggle', element, box.GetValue()))
    return box


def _build_radio(parent, element, on_action, first_in_group=False):
    """One option button, in a real group with the ones next to it.

    wx groups radio buttons by creation order: the one carrying ``RB_GROUP``
    starts a set and every plain one after it joins it. Since the controls are
    created in reading order, a run of option buttons in the same region of the
    screen is exactly the run wx needs - and a real group is what makes the
    arrow keys move between the options and a screen reader say "2 of 4".

    A lone option button gets ``RB_SINGLE`` instead, so it cannot silently
    swallow the next one to be built.
    """
    style = wx.RB_GROUP if first_in_group else wx.RB_SINGLE
    button = wx.RadioButton(parent, label=element.name or _("Option"),
                            style=style)
    button.SetValue(bool(element.checked))
    if on_action is not None:
        button.Bind(wx.EVT_RADIOBUTTON,
                    lambda e: on_action('toggle', element, True))
    return button


def cluster_radio_runs(items: Sequence, element_of=lambda item: item) -> List:
    """Bring each region's option buttons together, keeping reading order.

    Reading order alone is not enough to build option buttons with: it is
    spatial, so a tick box that happens to sit between two options splits them,
    and wx - which groups by creation order - would then build two groups where
    the screen has one. Each region's options are gathered behind the first of
    them; everything else keeps the order it had.
    """
    result: List = []
    last_index: dict = {}
    for item in items:
        element = element_of(item)
        if element.role != 'radio':
            result.append(item)
            continue
        previous = last_index.get(element.region)
        if previous is None:
            result.append(item)
            last_index[element.region] = len(result) - 1
            continue
        position = previous + 1
        result.insert(position, item)
        for region, index in list(last_index.items()):
            if index >= position:
                last_index[region] = index + 1
        last_index[element.region] = position
    return result


def group_starts(elements: Sequence[Element]) -> List[bool]:
    """For each element, whether it begins a group of option buttons.

    A run of radios in the same region is one group; a radio on its own, or one
    separated from the next by anything else, is its own. The reading never says
    which options belong together, so this is a guess - but it is the guess the
    layout itself makes, and a wrong one is corrected by the next reading rather
    than changing anything in the program.
    """
    flags: List[bool] = []
    run = 0
    for index, element in enumerate(elements):
        if element.role != 'radio':
            flags.append(False)
            run = 0
            continue
        previous = elements[index - 1] if index else None
        same_run = (previous is not None and previous.role == 'radio'
                    and previous.region == element.region)
        if same_run:
            run += 1
            flags.append(False)
            continue
        # A run of one is not a group; wx must not be told it starts one, or the
        # next radio built anywhere in this window would join it.
        following = elements[index + 1] if index + 1 < len(elements) else None
        starts = (following is not None and following.role == 'radio'
                  and following.region == element.region)
        flags.append(bool(starts))
        run = 1 if starts else 0
    return flags


def _build_edit(parent, element, on_action):
    multiline = len(element.value or element.text or '') > LONG_TEXT
    style = wx.TE_MULTILINE if multiline else wx.TE_PROCESS_ENTER
    field = wx.TextCtrl(parent, value=element.value or element.text or '',
                        style=style)
    field._ocr_committed = field.GetValue()

    if on_action is None:
        return field

    def _commit(event=None):
        if event is not None:
            event.Skip()
        text = field.GetValue()
        if text == field._ocr_committed:
            return
        field._ocr_committed = text
        on_action('text', element, text)

    if not multiline:
        field.Bind(wx.EVT_TEXT_ENTER, lambda e: _commit())
    field.Bind(wx.EVT_KILL_FOCUS, _commit)
    return field


def _build_slider(parent, element, on_action):
    if not element.has_range:
        return _build_nudger(parent, element, on_action)

    low, high = int(element.minimum), int(element.maximum)
    if high <= low:
        return _build_nudger(parent, element, on_action)
    number = element.number
    value = int(number) if number is not None else low
    value = max(low, min(high, value))

    slider = wx.Slider(parent, value=value, minValue=low, maxValue=high,
                       style=wx.SL_HORIZONTAL)
    slider._ocr_committed = value

    if on_action is None:
        return slider

    def _commit(event):
        event.Skip()
        current = slider.GetValue()
        if current == slider._ocr_committed:
            return
        slider._ocr_committed = current
        on_action('slider', element, current)

    # Released, not dragged: a slider sent on every tick of a drag would fire
    # twenty clicks into the program for one movement.
    slider.Bind(wx.EVT_SCROLL_THUMBRELEASE, _commit)
    slider.Bind(wx.EVT_SCROLL_CHANGED, _commit)          # keyboard, page, end
    return slider


def _build_nudger(parent, element, on_action):
    """A slider with no known range: two buttons, because that is the truth.

    A wx.Slider needs a minimum and a maximum. Inventing 0-100 for a volume bar
    that is really 0-11 would show the user a number that means nothing and
    move the real control to the wrong place. Less and More press the real
    slider and let the program decide what one step is.
    """
    panel = wx.Panel(parent)
    row = wx.BoxSizer(wx.HORIZONTAL)
    name = element.name or _("Slider")

    down = wx.Button(panel, label=_("Less"), style=wx.BU_EXACTFIT)
    down.SetName(_("{name}, less").format(name=name))
    up = wx.Button(panel, label=_("More"), style=wx.BU_EXACTFIT)
    up.SetName(_("{name}, more").format(name=name))
    if on_action is not None:
        down.Bind(wx.EVT_BUTTON, lambda e: on_action('nudge', element, -1))
        up.Bind(wx.EVT_BUTTON, lambda e: on_action('nudge', element, 1))

    if element.value:
        row.Add(wx.StaticText(panel, label=element.value),
                flag=wx.ALIGN_CENTRE_VERTICAL | wx.RIGHT, border=4)
    row.Add(down, flag=wx.RIGHT, border=2)
    row.Add(up)
    panel.SetSizer(row)
    panel._ocr_focus = down
    return panel


def _build_progress(parent, element, on_action):
    """A meter: a real gauge when its range is known, otherwise its text."""
    number = element.number
    if element.has_range and number is not None:
        span = int(element.maximum - element.minimum) or 1
        gauge = wx.Gauge(parent, range=span, style=wx.GA_HORIZONTAL)
        gauge.SetValue(int(max(0, min(span, number - element.minimum))))
        return gauge
    return _build_text(parent, element, on_action)


def _build_text(parent, element, on_action):
    """Text, a heading, a value, a picture's description.

    A read-only text box rather than a static label, and deliberately so: a
    wx.StaticText cannot be focused, so on this overlay - where the keyboard is
    the only way around - it would be text a screen reader user could never
    reach. Read-only means it reads like a label and cannot be edited.
    """
    body = element.text or element.name or element.value
    if element.value and element.name and element.value not in body:
        body = f"{element.name}: {element.value}"
    if not body:
        return None
    style = wx.TE_READONLY | wx.BORDER_NONE
    if len(body) > LONG_TEXT or '\n' in body:
        style |= wx.TE_MULTILINE
    return wx.TextCtrl(parent, value=body, style=style)


_BUILDERS = {
    'button': _build_button,
    'menuitem': _build_button,
    'listitem': _build_button,
    'tab': _build_button,
    'link': _build_button,
    'other': _build_button,
    'combobox': _build_combobox,
    'checkbox': _build_checkbox,
    'radio': _build_radio,
    'edit': _build_edit,
    'slider': _build_slider,
    'progress': _build_progress,
    'value': _build_text,
    'heading': _build_text,
    'text': _build_text,
    'image': _build_text,
}


# --------------------------------------------------------------------------- #
# The menu bar
# --------------------------------------------------------------------------- #
# What the reading calls the strip of menu titles along the top of a window.
MENU_REGION_ROLES = frozenset({'menu', 'menubar', 'menu bar', 'menu_bar'})


def menu_bar_elements(screen) -> List[Element]:
    """The window's menu bar, as elements, or an empty list.

    A menu bar is a real thing on the screen and it is the one part of a window
    that a keyboard user reaches by a standard key rather than by Tab - so it is
    reproduced as a real menu (see :func:`build_menu`) as well as being placed
    where it really is.
    """
    if screen is None:
        return []
    for region in screen.regions:
        role = (region.role or '').lower()
        items = [element for element in region.elements
                 if element.role in ('menuitem', 'button')]
        if role in MENU_REGION_ROLES and len(items) >= 2 and not region.is_window:
            return items
    # No region says "menu bar", but a row of menu items at the top is one.
    items = [element for element in screen.elements if element.role == 'menuitem']
    return items if len(items) >= 2 else []


def build_menu(elements: Sequence[Element],
               on_action: Optional[ActionCallback] = None) -> Optional[wx.Menu]:
    """A real wx.Menu of ``elements``, each choice pressing the real thing.

    What is *inside* a menu cannot be seen until it is open, so choosing an
    entry here clicks the real menu title; the reading that follows sees the
    drop-down that opened and gives it a surface of its own.
    """
    if not elements:
        return None
    menu = wx.Menu()
    for element in elements:
        label = (element.name or element.text or _("(unnamed)")).replace('&', '&&')
        if element.checked is not None:
            item = menu.AppendCheckItem(wx.ID_ANY, label)
            item.Check(bool(element.checked))
        else:
            item = menu.Append(wx.ID_ANY, label)
        if not element.enabled:
            item.Enable(False)
        if on_action is not None:
            menu.Bind(wx.EVT_MENU,
                      lambda e, target=element: on_action('press', target, None),
                      item)
    return menu


def focus_target(control: wx.Window) -> wx.Window:
    """The window that should really take the focus for ``control``.

    A composite (the Less/More pair) is a panel, and focusing a panel announces
    nothing; its first button is what the user meant.
    """
    return getattr(control, '_ocr_focus', control)


def focusable(control: wx.Window) -> bool:
    return bool(control) and control.IsEnabled() and control.IsShown()

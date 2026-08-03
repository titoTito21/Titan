# -*- coding: utf-8 -*-
"""The screen rebuilt as controls, stacked in a column inside the mimic.

The reading list says "Volume, 70, slider". This says it with a real
wx.Slider whose arrow keys move the program's real slider. For a settings page
or a dialog that is the difference between being told what is there and being
able to use it.

This is the *docked* rebuild: one region at a time, laid out top to bottom
inside the mimic window, reachable with Tab like any Titan dialog. It is the
right shape when the real window is somewhere else (minimised, on another
monitor, behind a full-screen game) or when the user simply wants an ordinary
Titan form rather than something floating over another program.

When the real window is there to be stood on, :mod:`src.ai.ocr.overlay` puts
the very same controls at the very same coordinates as the real ones instead -
control over control, window over window. Both build their controls with
:mod:`src.ai.ocr.controls`, so a fix to how a slider commits, or to what a
screen reader says for a field, lands in both at once.
"""

from __future__ import annotations

from typing import List, Optional

import wx

from src.ai.ocr import controls as controls_mod
from src.ai.ocr.controls import has_real_controls          # noqa: F401  (re-export)
from src.ai.ocr.model import Element, Region, Screen
from src.network.im_ui_common import _

# Roles that carry their own label, so a separate one in front would make a
# screen reader say the name twice.
_SELF_LABELLED = frozenset({'button', 'menuitem', 'listitem', 'tab', 'link',
                            'other', 'checkbox', 'radio', 'combobox', 'text',
                            'heading', 'value', 'image'})


class ScreenForm(wx.ScrolledWindow):
    """The controls of one region, rebuilt and stacked."""

    def __init__(self, parent: wx.Window, on_action=None):
        super().__init__(parent, style=wx.VSCROLL | wx.HSCROLL)
        self.on_action = on_action
        self.SetScrollRate(0, 12)
        self.SetName(_("Rebuilt controls"))
        self._controls: List[wx.Window] = []
        self._sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self._sizer)

    # ---------------------------------------------------------------- building
    def rebuild(self, screen: Optional[Screen],
                region: Optional[Region]) -> int:
        """Throw the controls away and build them again. Returns how many.

        Rebuilt rather than updated in place, because between two readings a
        control can change role, disappear or move to another region, and a
        form that patches itself would keep a stale control the program no
        longer has.
        """
        remembered = self._focused_key()
        self._clear()

        elements = list(region.elements) if region is not None else []
        if not elements:
            self._sizer.Add(
                wx.StaticText(self, label=self._empty_text(screen)),
                flag=wx.ALL, border=8)
            self.Layout()
            self.FitInside()
            return 0

        # Option buttons are grouped by creation order, so the runs have to be
        # worked out over the whole region before anything is built.
        for element, first in zip(elements, controls_mod.group_starts(elements)):
            self._add(element, first)

        self.Layout()
        self.FitInside()
        self._restore_focus(remembered)
        return len(self._controls)

    def _empty_text(self, screen: Optional[Screen]) -> str:
        if screen is None:
            return _("Nothing has been read yet. Press F5 to read the screen.")
        return _("Nothing in this part of the screen could be rebuilt as a "
                 "control.")

    def _add(self, element: Element, first_in_group: bool = False) -> None:
        control = controls_mod.build_control(self, element, self._fire,
                                             first_in_group)
        if control is None:
            return

        if element.role not in _SELF_LABELLED:
            label = wx.StaticText(self, label=self._label_for(element))
            self._sizer.Add(label, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=8)
        self._sizer.Add(control, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
                        border=8)
        self._controls.append(control)

        if element.hint:
            hint = wx.StaticText(self, label=_("({hint})").format(
                hint=element.hint))
            self._sizer.Add(hint, flag=wx.LEFT | wx.RIGHT, border=8)

    def _label_for(self, element: Element) -> str:
        name = element.name or _("Field")
        if element.state:
            return f"{name} ({element.state})"
        return name

    def _clear(self) -> None:
        self._controls = []
        self._sizer.Clear(delete_windows=True)

    # ----------------------------------------------------------------- acting
    def _fire(self, kind: str, element: Element, value) -> None:
        if self.on_action is not None:
            self.on_action(kind, element, value)

    # ------------------------------------------------------------------ focus
    def focus_first(self) -> bool:
        for control in self._controls:
            if controls_mod.focusable(control):
                controls_mod.focus_target(control).SetFocus()
                return True
        self.SetFocus()
        return False

    def _focused_key(self) -> str:
        """Which element the focus is on, in a form that survives a rebuild."""
        window = self.FindFocus()
        while window is not None and window is not self:
            element = getattr(window, '_ocr_element', None)
            if element is not None:
                return element.key
            window = window.GetParent()
        return ''

    def _restore_focus(self, key: str) -> None:
        """Put the focus back on the same control after a rebuild.

        Every action is followed by a re-read and a rebuild. Without this the
        focus would jump to the top of the form after every keystroke, which
        makes changing three settings in a row impossible.
        """
        if not key:
            return
        for control in self._controls:
            element = getattr(control, '_ocr_element', None)
            if element is not None and element.key == key \
                    and controls_mod.focusable(control):
                controls_mod.focus_target(control).SetFocus()
                return

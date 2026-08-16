# -*- coding: utf-8 -*-
"""
A list of tick boxes Windows itself knows are tick boxes.

`wx.CheckListBox` on Windows is an owner-drawn list box: wxWidgets paints the
little square itself, so as far as the platform is concerned there is no
check box there at all.  Measured with `AccessibleObjectFromWindow` on a
`wx.CheckListBox` holding three items, the first of them ticked:

    item 1 'alpha' role 34 (list item) state 0x300004   - not CHECKED
    UIA: toggle pattern: False

That is why NVDA said the name of the add-on and nothing about whether it was
switched on - the state a screen reader would read is not there to read.
Titan worked around it by *speaking* "checked" / "unchecked" itself, which
only ever worked for the readers Titan can speak through, said the state half
a second after the row was read, and said nothing at all to JAWS or Narrator.

The same list built as a report-mode `wx.ListCtrl` with `EnableCheckBoxes()`
- which is `LVS_EX_CHECKBOXES`, the native list-view check box Explorer
itself uses - answers:

    item 1 'alpha' role 44 (check box) state 0x300010   - CHECKED
    UIA: toggle pattern: True, ToggleState 1

So every screen reader reads it, from the platform, with no help from Titan:
NVDA and JAWS out of MSAA, Titan Access out of the UIA toggle pattern it
already reads for every check box (`uia_focus._read_states`).  Titan is left
with the one part that is genuinely its own - the earcon - and says nothing.

The control keeps `wx.CheckListBox`'s interface (`Set`, `Check`, `IsChecked`,
`GetString`, `GetCount`...) and fires `wx.EVT_CHECKLISTBOX` and
`wx.EVT_LISTBOX` with the item index in `GetSelection()`, so it goes where
one already is without the window around it changing.
"""

import wx

# How tall the list makes itself, in rows.
MIN_ROWS = 3
MAX_ROWS = 8


class CheckList(wx.ListCtrl):
    """A one-column report list whose rows are real check boxes."""

    def __init__(self, parent, id=wx.ID_ANY, choices=(), name='',
                 size=wx.DefaultSize, style=0, **kwargs):
        super().__init__(
            parent, id, size=size,
            style=(wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL
                   | wx.BORDER_SUNKEN | style),
            **kwargs)
        # Switched on before anything is put in: a list view grows its check
        # boxes when the extended style arrives, not when the rows do.
        self.native_checkboxes = bool(self.EnableCheckBoxes(True))
        # The one column carries the list's own name, and the header is not
        # shown: a name is what MSAA answers with, not something to read.
        self.InsertColumn(0, name or '')
        # A change Titan made itself is not the user ticking something, so it
        # neither plays a sound nor tells the window it happened.
        self._quiet = 0
        self._last_focused = -1
        self._name = ''
        self._accessible = None
        if name:
            self.SetName(name)
        if choices:
            self.Set(choices)
        self.Bind(wx.EVT_LIST_ITEM_CHECKED, self._on_checked)
        self.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self._on_checked)
        self.Bind(wx.EVT_LIST_ITEM_FOCUSED, self._on_focused)
        self.Bind(wx.EVT_SIZE, self._on_size)

    # -- what it is called -------------------------------------------------
    def SetName(self, name):
        """Name it for wx **and** for MSAA.

        A native list view has no window text, so `SetName` alone reaches
        nothing that reads the screen; `a11y.name_control` is what gives it an
        accessible name, and it is the same helper the shell's own native
        controls use.
        """
        self._name = name or ''
        super().SetName(self._name)
        try:
            self.SetColumn(0, self._column(self._name))
        except Exception:
            pass
        try:
            from src.shell.a11y import name_control
            self._accessible = name_control(self, self._name)
        except Exception:
            pass

    def SetLabel(self, label):
        # Several call sites name the list by the caption in front of it; a
        # list control has no label of its own, so that caption is its name.
        self.SetName((label or '').rstrip(':').strip())

    @staticmethod
    def _column(text):
        item = wx.ListItem()
        item.SetText(text or '')
        return item

    # -- the wx.CheckListBox interface -------------------------------------
    def Set(self, choices):
        with _Quiet(self):
            self.DeleteAllItems()
            for index, label in enumerate(choices or ()):
                self.InsertItem(index, str(label))
        self._last_focused = -1
        self._fit()

    def Append(self, label):
        with _Quiet(self):
            index = self.InsertItem(self.GetItemCount(), str(label))
        self._fit()
        return index

    def Clear(self):
        with _Quiet(self):
            self.DeleteAllItems()
        self._last_focused = -1
        self._fit()

    def GetCount(self):
        return self.GetItemCount()

    def GetString(self, index):
        return self.GetItemText(index, 0)

    def GetStrings(self):
        return [self.GetItemText(index, 0)
                for index in range(self.GetItemCount())]

    def Check(self, index, check=True):
        if 0 <= index < self.GetItemCount():
            with _Quiet(self):
                self.CheckItem(index, bool(check))

    def IsChecked(self, index):
        if 0 <= index < self.GetItemCount():
            return bool(self.IsItemChecked(index))
        return False

    def GetCheckedItems(self):
        return [index for index in range(self.GetItemCount())
                if self.IsItemChecked(index)]

    def GetCheckedStrings(self):
        return [self.GetItemText(index, 0)
                for index in self.GetCheckedItems()]

    def GetSelection(self):
        return self.GetFirstSelected()

    def SetSelection(self, index):
        if 0 <= index < self.GetItemCount():
            self.Select(index)
            self.Focus(index)

    # -- events ------------------------------------------------------------
    def _on_checked(self, event):
        event.Skip()
        if self._quiet:
            return
        index = event.GetIndex()
        checked = self.IsChecked(index)
        # The earcon only: what the state IS comes from the control now, in
        # whatever words the user's own screen reader uses for a check box.
        try:
            from src.accessibility.messages import (
                announce_checklist_item_toggle)
            announce_checklist_item_toggle(checked, speak=False)
        except Exception as error:
            print(f"[CheckList] could not play the toggle sound: {error}")
        self._post(wx.EVT_CHECKLISTBOX.typeId, index)

    def _on_focused(self, event):
        event.Skip()
        index = event.GetIndex()
        if self._quiet or index < 0 or index == self._last_focused:
            return
        self._last_focused = index
        try:
            from src.accessibility.messages import (
                announce_checklist_item_navigation)
            announce_checklist_item_navigation(self.IsChecked(index),
                                               speak=False)
        except Exception as error:
            print(f"[CheckList] could not play the focus sound: {error}")
        self._post(wx.EVT_LISTBOX.typeId, index)

    def _post(self, event_type, index):
        """Fire the event a `wx.CheckListBox` would have fired.

        The index goes in as the command int, which is what both
        `GetSelection()` and `GetInt()` answer with - so a handler written
        for a check list box works here unchanged.
        """
        try:
            event = wx.CommandEvent(event_type, self.GetId())
            event.SetEventObject(self)
            event.SetInt(index)
            wx.PostEvent(self, event)
        except Exception as error:
            print(f"[CheckList] could not fire {event_type}: {error}")

    def _on_size(self, event):
        event.Skip()
        self._fit_column()

    def _fit_column(self):
        """One column, the width of the list: there is nothing to line up."""
        try:
            width = self.GetClientSize().width
            if width > 4:
                self.SetColumnWidth(0, width - 4)
        except Exception:
            pass

    def _fit(self):
        """Be as tall as what is in it, the way a check list box is.

        A list control asks its sizer for almost nothing, so a list dropped
        where a `wx.CheckListBox` was would come out a couple of rows high
        whatever it held.  Between three and eight rows: enough to see there
        is a list, never so much that one add-on's list owns the panel.
        """
        self._fit_column()
        try:
            rows = min(max(self.GetItemCount(), MIN_ROWS), MAX_ROWS)
            row = self.GetCharHeight() + 6
            self.SetMinSize((-1, rows * row + 8))
            self.InvalidateBestSize()
        except Exception:
            pass


class _Quiet:
    """Inside this, a change is Titan's own and fires nothing."""

    def __init__(self, control):
        self.control = control

    def __enter__(self):
        self.control._quiet += 1
        return self.control

    def __exit__(self, *_error):
        self.control._quiet = max(0, self.control._quiet - 1)
        return False

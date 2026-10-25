# -*- coding: utf-8 -*-
"""
The subagents the user has, in a window: a list, and Add / Change / Delete.

The model is `src/ai/subagents.py`; this only edits its store. Every control
is a native one with a name, so a screen reader reads the list as a list and
each field by its label - there is nothing here a reader has to be taught.
"""

import wx

from src.ai import subagents
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

_ = set_language(get_setting('language', 'pl'))


class SubagentDialog(wx.Dialog):
    """One subagent's fields."""

    def __init__(self, parent, name='', entry=None):
        super().__init__(parent, title=_("Subagent"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        entry = entry or {}
        sizer = wx.BoxSizer(wx.VERTICAL)

        def field(label, value, style=0, size=(-1, -1)):
            sizer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.TOP, 8)
            ctrl = wx.TextCtrl(self, value=value, style=style, size=size)
            ctrl.SetName(label.rstrip(':'))
            sizer.Add(ctrl, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)
            return ctrl

        self.name = field(_("&Name:"), name)
        if entry.get('builtin') is False and name:
            self.name.SetEditable(False)
        self.description = field(_("&What it is for:"),
                                 entry.get('description', ''))
        self.instructions = field(_("&Instructions:"),
                                  entry.get('instructions', ''),
                                  wx.TE_MULTILINE, (420, 110))

        sizer.Add(wx.StaticText(self, label=_("&Tools it may use:")), 0,
                  wx.LEFT | wx.TOP, 8)
        from src.ui.check_list import CheckList
        self._groups = list(subagents.GROUPS)
        self.tools = CheckList(
            self, choices=[f"{g} - {subagents.GROUPS[g]}" for g in self._groups],
            name=_("Tools it may use"))
        chosen = entry.get('tools') or ['all']
        for index, group in enumerate(self._groups):
            if group in chosen:
                self.tools.Check(index, True)
        sizer.Add(self.tools, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        sizer.Add(wx.StaticText(self, label=_("&Steps at most:")), 0,
                  wx.LEFT | wx.TOP, 8)
        self.steps = wx.SpinCtrl(self, min=1, max=subagents.MAX_STEPS,
                                 initial=int(entry.get('max_steps')
                                             or subagents.DEFAULT_STEPS))
        self.steps.SetName(_("Steps at most"))
        sizer.Add(self.steps, 0, wx.LEFT, 8)

        sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0,
                  wx.ALL | wx.EXPAND, 8)
        self.SetSizerAndFit(sizer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _on_ok(self, event):
        if not subagents.slug(self.name.GetValue()):
            wx.MessageBox(_("A subagent needs a name."), _("Subagent"),
                          wx.OK | wx.ICON_WARNING, self)
            return
        if not self.instructions.GetValue().strip():
            wx.MessageBox(_("Say how the subagent should work."),
                          _("Subagent"), wx.OK | wx.ICON_WARNING, self)
            return
        event.Skip()

    def values(self):
        groups = [g for i, g in enumerate(self._groups) if self.tools.IsChecked(i)]
        return dict(name=self.name.GetValue(),
                    description=self.description.GetValue(),
                    instructions=self.instructions.GetValue(),
                    tools=groups, max_steps=self.steps.GetValue())


class SubagentsDialog(wx.Dialog):
    """Every subagent there is; the user's own can be changed and deleted."""

    def __init__(self, parent):
        super().__init__(parent, title=_("Subagents"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label=_(
            "A subagent is a separate AI run the agent and the assistants can "
            "hand part of a task to. Built-in ones cannot be deleted; a "
            "subagent of your own with the same name replaces one.")),
            0, wx.ALL, 8)
        self.list = wx.ListBox(self, size=(460, 200))
        self.list.SetName(_("Subagents"))
        sizer.Add(self.list, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.add_btn = wx.Button(self, label=_("&Add..."))
        self.edit_btn = wx.Button(self, label=_("&Change..."))
        self.delete_btn = wx.Button(self, label=_("&Delete"))
        close = wx.Button(self, wx.ID_CLOSE, _("Close"))
        for button in (self.add_btn, self.edit_btn, self.delete_btn, close):
            row.Add(button, 0, wx.ALL, 4)
        sizer.Add(row, 0, wx.ALL, 4)
        self.SetSizerAndFit(sizer)
        self.SetEscapeId(wx.ID_CLOSE)
        self.add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        self.edit_btn.Bind(wx.EVT_BUTTON, self._on_edit)
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_edit)
        close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        self._names = []
        self.refill()

    def refill(self, keep=None):
        found = subagents.definitions()
        self._names = sorted(found)
        self.list.Set([self._row(name, found[name]) for name in self._names])
        if self._names:
            index = self._names.index(keep) if keep in self._names else 0
            self.list.SetSelection(index)

    @staticmethod
    def _row(name, entry):
        kind = _("built in") if entry.get('builtin') else _("your own")
        return f"{name} ({kind}) - {subagents.shown_description(name, entry)}"

    def _selected(self):
        index = self.list.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self._names):
            return None, None
        name = self._names[index]
        return name, subagents.definitions().get(name)

    def _edit(self, name='', entry=None):
        dialog = SubagentDialog(self, name, entry)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            values = dialog.values()
        finally:
            dialog.Destroy()
        try:
            key = subagents.save(**values)
        except Exception as e:                       # noqa: BLE001
            wx.MessageBox(_("The subagent could not be saved: {error}").format(
                error=e), _("Subagents"), wx.OK | wx.ICON_ERROR, self)
            return
        self.refill(key)
        self.list.SetFocus()

    def _on_add(self, event):
        self._edit()

    def _on_edit(self, event):
        name, entry = self._selected()
        if name:
            self._edit(name, entry)

    def _on_delete(self, event):
        name, entry = self._selected()
        if not name:
            return
        if entry.get('builtin'):
            wx.MessageBox(_("A built-in subagent cannot be deleted."),
                          _("Subagents"), wx.OK | wx.ICON_INFORMATION, self)
            return
        if wx.MessageBox(_("Delete the subagent {name}?").format(name=name),
                         _("Subagents"), wx.YES_NO | wx.ICON_QUESTION,
                         self) != wx.YES:
            return
        subagents.remove(name)
        self.refill()
        self.list.SetFocus()


def show(parent=None):
    dialog = SubagentsDialog(parent)
    try:
        dialog.ShowModal()
    finally:
        dialog.Destroy()

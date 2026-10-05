# -*- coding: utf-8 -*-
"""The NVDA add-ons installed in Titan Access, managed in one window.

A list of the add-ons - each a real check box (on: it runs) - and Install
(a ``.nvda-addon`` file), Remove, Migrate from NVDA and Close. Every
change is applied at once: the add-ons are loaded again, so a switched-on
global plugin is running by the time the window is closed."""

from titan_access.localization import L

from . import installed, install, migrate, migratable, reload, remove, \
    set_enabled


def _list_class(wx):
    """Titan's own native check list (MSAA reports its rows as check boxes
    with their state), or wx's where Titan's is not there."""
    try:
        from src.ui.check_list import CheckList
        return CheckList
    except Exception:                                # noqa: BLE001
        return wx.CheckListBox


def show(parent=None):
    import wx

    dialog = wx.Dialog(parent, title=L('nvdaHost.manager.title'),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    sizer = wx.BoxSizer(wx.VERTICAL)
    label = wx.StaticText(dialog, label=L('nvdaHost.manager.list'))
    sizer.Add(label, 0, wx.ALL, 6)
    listing = _list_class(wx)(dialog, size=(520, 260))
    try:
        listing.SetName(L('nvdaHost.manager.list'))
    except Exception:                                # noqa: BLE001
        pass
    sizer.Add(listing, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
    note = wx.StaticText(dialog, label='')
    sizer.Add(note, 0, wx.ALL, 6)
    buttons = wx.BoxSizer(wx.HORIZONTAL)
    install_button = wx.Button(dialog, label=L('nvdaHost.manager.install'))
    remove_button = wx.Button(dialog, label=L('nvdaHost.manager.remove'))
    migrate_button = wx.Button(dialog, label=L('nvdaHost.manager.migrate'))
    close_button = wx.Button(dialog, wx.ID_CLOSE)
    for one in (install_button, remove_button, migrate_button, close_button):
        buttons.Add(one, 0, wx.ALL, 4)
    sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
    dialog.SetSizerAndFit(sizer)
    dialog.SetEscapeId(wx.ID_CLOSE)
    records = []

    def describe(record):
        kinds = ', '.join(L('nvdaHost.kind.' + kind) for kind in
                          record['kinds']) or L('nvdaHost.kind.data')
        return '%s %s - %s (%s)' % (record['name'], record['version'],
                                    record['summary'], kinds)

    def fill(select=0):
        records[:] = installed()
        listing.Set([describe(one) for one in records])
        for at, one in enumerate(records):
            listing.Check(at, bool(one['enabled']))
        if records:
            listing.SetSelection(min(select, len(records) - 1))
        remove_button.Enable(bool(records))
        migrate_button.Enable(bool(migratable()))

    def toggled(event):
        at = event.GetInt() if hasattr(event, 'GetInt') else \
            listing.GetSelection()
        if 0 <= at < len(records):
            set_enabled(records[at]['name'], listing.IsChecked(at))
            reload()
            note.SetLabel(L('nvdaHost.manager.applied'))

    def install_one(_event):
        with wx.FileDialog(dialog, L('nvdaHost.manager.install'),
                           wildcard='NVDA add-on (*.nvda-addon)|*.nvda-addon',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) \
                as chooser:
            if chooser.ShowModal() != wx.ID_OK:
                return
            path = chooser.GetPath()
        ok, said = install(path)
        if ok:
            reload()
            note.SetLabel(L('nvdaHost.manager.installed').format(name=said))
        else:
            wx.MessageBox(said, L('nvdaHost.manager.title'),
                          wx.OK | wx.ICON_ERROR, dialog)
        fill()

    def remove_one(_event):
        at = listing.GetSelection()
        if not 0 <= at < len(records):
            return
        name = records[at]['name']
        if wx.MessageBox(L('nvdaHost.manager.removeQuestion').format(
                name=name), L('nvdaHost.manager.title'),
                wx.YES_NO | wx.ICON_QUESTION, dialog) != wx.YES:
            return
        remove(name)
        reload()
        fill(at)

    def migrate_all(_event):
        done = migrate()
        reload()
        good = [name for name, ok, _why in done if ok]
        note.SetLabel(L('nvdaHost.migrate.done').format(count=len(good)))
        fill()

    listing.Bind(wx.EVT_CHECKLISTBOX, toggled)
    install_button.Bind(wx.EVT_BUTTON, install_one)
    remove_button.Bind(wx.EVT_BUTTON, remove_one)
    migrate_button.Bind(wx.EVT_BUTTON, migrate_all)
    fill()
    listing.SetFocus()
    dialog.ShowModal()
    dialog.Destroy()

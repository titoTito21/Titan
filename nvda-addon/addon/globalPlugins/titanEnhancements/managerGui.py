# -*- coding: utf-8 -*-
"""One window for the things the user has made: markers, monitors, sounds.

A chooser is not a manager. A list you pick one thing out of and that then
closes is right for "go to this marker" and wrong for the half-hour once a
month when somebody sits down to tidy up what they have accumulated - rename
the marker they called "Edit" three months ago, take away the monitor that
turned out to be noisy, hear what "selected" would sound like before
committing to it.

So this is a real manager: a tab per kind of thing, a list of what is there,
and the buttons that act on the one chosen. It stays open while you work.

**It is accessible because it is native.** A `wx.Notebook` is a real tab
control - the platform says "tab, 1 of 3" without a word being written here
- and each page is a real list with real buttons. That is the same rule the
Titan shell arrived at and the same one every other window in this add-on
follows.

**Nothing here is a second opinion about anything.** Every page reads and
writes the module that owns it - :mod:`markers`, :mod:`monitors`,
:mod:`schemes` - so what is shown is what is really in force, and a manager
that showed one thing while the reader did another would be worse than not
having one.
"""

from . import i18n
from . import icons
from . import markers
from . import monitors
from . import schemes

_ = i18n.install(globals())


def build():
    """The dialog class, or None when there is no wx."""
    try:
        import wx
        from gui import guiHelper
    except Exception:                                # noqa: BLE001
        return None

    class Manager(wx.Dialog):

        def __init__(self, parent):
            # Translators: the title of the manager window.
            super().__init__(parent, title=_('Titan manager'),
                             style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
            main = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
            self.book = main.addItem(wx.Notebook(self))
            self._markers_page()
            self._monitors_page()
            self._scheme_page()
            self._icons_page()
            main.addDialogDismissButtons(self.CreateButtonSizer(wx.CLOSE))
            self.Bind(wx.EVT_BUTTON, self._close, id=wx.ID_CLOSE)
            self.EscapeId = wx.ID_CLOSE
            self.Sizer = main.sizer
            main.sizer.Fit(self)
            self.CentreOnScreen()

        # ---------------------------------------------------------- markers
        def _markers_page(self):
            import wx
            from gui import guiHelper
            page = wx.Panel(self.book)
            # Translators: a page of the manager window.
            self.book.AddPage(page, _('Place markers'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: the list of place markers.
            self.markers = helper.addLabeledControl(
                _('&Markers'), wx.ListBox, style=wx.LB_SINGLE)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the manager window.
            go = buttons.addButton(page, label=_('&Go there'))
            go.Bind(wx.EVT_BUTTON, self._go_to_marker)
            # Translators: a button in the manager window.
            rename = buttons.addButton(page, label=_('Re&name...'))
            rename.Bind(wx.EVT_BUTTON, self._rename_marker)
            # Translators: a button in the manager window.
            forget = buttons.addButton(page, label=_('&Forget'))
            forget.Bind(wx.EVT_BUTTON, self._forget_marker)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._fill_markers()

        def _fill_markers(self, at=0):
            self._marker_rows = markers.all_markers()
            self.markers.Set([
                '%s%s' % (row.get('name') or '',
                          (' - ' + row['program']) if row.get('program')
                          else '')
                for row in self._marker_rows])
            if self._marker_rows:
                self.markers.SetSelection(
                    max(0, min(at, len(self._marker_rows) - 1)))

        def _chosen_marker(self):
            at = self.markers.GetSelection()
            return self._marker_rows[at] \
                if 0 <= at < len(self._marker_rows) else None

        def _go_to_marker(self, _event):
            row = self._chosen_marker()
            if row is None:
                return
            _ok, said = markers.go(row)
            self._said(said)

        def _rename_marker(self, _event):
            import wx
            row = self._chosen_marker()
            if row is None:
                return
            # Translators: asked when renaming a place marker.
            dialog = wx.TextEntryDialog(self, _('What should it be called?'),
                                        # Translators: the title of that box.
                                        _('Rename'),
                                        value=row.get('name') or '')
            try:
                if dialog.ShowModal() == wx.ID_OK:
                    markers.rename(row, dialog.GetValue())
                    self._fill_markers(at=self.markers.GetSelection())
            finally:
                dialog.Destroy()

        def _forget_marker(self, _event):
            row = self._chosen_marker()
            if row is None:
                return
            at = self.markers.GetSelection()
            markers.remove(row)
            self._fill_markers(at=at)
            # Translators: said when a place marker is forgotten.
            self._said(_('Marker forgotten'))

        # --------------------------------------------------------- monitors
        def _monitors_page(self):
            import wx
            from gui import guiHelper
            page = wx.Panel(self.book)
            # Translators: a page of the manager window.
            self.book.AddPage(page, _('Watched areas'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: the list of watched areas.
            self.monitors = helper.addLabeledControl(
                _('&Watched'), wx.ListBox, style=wx.LB_SINGLE)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the manager window.
            check = buttons.addButton(page, label=_('&Read it now'))
            check.Bind(wx.EVT_BUTTON, self._read_monitor)
            # Translators: a button in the manager window.
            forget = buttons.addButton(page, label=_('S&top watching'))
            forget.Bind(wx.EVT_BUTTON, self._forget_monitor)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._fill_monitors()

        def _fill_monitors(self, at=0):
            kinds = {
                # Translators: a kind of watched area.
                monitors.BY_CONTROL: _('a control'),
                # Translators: a kind of watched area.
                monitors.BY_POINT: _('a place in the window'),
                # Translators: a kind of watched area.
                monitors.BY_AREA: _('an area of the screen'),
            }
            self._monitor_rows = monitors.all_monitors()
            self.monitors.Set([
                '%s (%s%s)' % (row.get('name') or '',
                               kinds.get(row.get('kind'), ''),
                               (', ' + row['program']) if row.get('program')
                               else '')
                for row in self._monitor_rows])
            if self._monitor_rows:
                self.monitors.SetSelection(
                    max(0, min(at, len(self._monitor_rows) - 1)))

        def _read_monitor(self, _event):
            at = self.monitors.GetSelection()
            if not 0 <= at < len(self._monitor_rows):
                return
            now = monitors._read(self._monitor_rows[at])
            if now is None:
                # Translators: said when a watched area cannot be read now.
                self._said(_('That is not on the screen now'))
                return
            self._said(monitors._shorten(now))

        def _forget_monitor(self, _event):
            at = self.monitors.GetSelection()
            if not 0 <= at < len(self._monitor_rows):
                return
            monitors.remove(at)
            self._fill_monitors(at=at)
            # Translators: said when a watched area is forgotten.
            self._said(_('No longer watching'))

        # ------------------------------------------------- auditory icons
        def _icons_page(self):
            """Emacspeak's icons: what each one marks, and whether it plays.

            A tick list rather than a list plus a button, because "is this
            one on" is the whole question and a check box is what Windows
            itself reports as one.
            """
            import wx
            from gui import guiHelper
            from .classManager import _check_list_class
            page = wx.Panel(self.book)
            # Translators: a page of the manager window.
            self.book.AddPage(page, _('Auditory icons'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: the list of auditory icons.
            self.icons = helper.addLabeledControl(
                _('&Icons'), _check_list_class())
            self.icons.Bind(wx.EVT_CHECKLISTBOX, self._icon_toggled)
            self.icons.Bind(wx.EVT_LISTBOX, self._icon_chosen)
            # Translators: the text that says what an auditory icon marks.
            self.icon_meaning = helper.addItem(wx.TextCtrl(
                page, style=wx.TE_READONLY, size=(-1, -1)))
            self.icon_meaning.SetName(_('What this marks'))
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the manager window.
            hear = buttons.addButton(page, label=_('&Hear it'))
            hear.Bind(wx.EVT_BUTTON, self._hear_icon)
            # Translators: a button in the manager window.
            folder = buttons.addButton(page, label=_('&Where they are'))
            folder.Bind(wx.EVT_BUTTON, self._icon_folder)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._fill_icons()

        def _fill_icons(self, at=0):
            self._icon_rows = icons.described()
            self.icons.Set([row['id'] for row in self._icon_rows])
            for index, row in enumerate(self._icon_rows):
                self.icons.Check(index, row['on'])
            if self._icon_rows:
                self.icons.SetSelection(
                    max(0, min(at, len(self._icon_rows) - 1)))
                self._icon_chosen(None)

        def _chosen_icon(self):
            at = self.icons.GetSelection()
            rows = getattr(self, '_icon_rows', [])
            return rows[at] if 0 <= at < len(rows) else None

        def _icon_chosen(self, _event):
            row = self._chosen_icon()
            if row is None:
                return
            said = row['meaning']
            if not row['file']:
                # Translators: shown for an icon with no sound file.
                said = _('{what} - there is no sound for this one').format(
                    what=said)
            self.icon_meaning.SetValue(said)

        def _icon_toggled(self, event):
            at = event.GetSelection()
            rows = getattr(self, '_icon_rows', [])
            if not 0 <= at < len(rows):
                return
            icons.set_wanted(rows[at]['id'], self.icons.IsChecked(at))
            rows[at]['on'] = self.icons.IsChecked(at)

        def _hear_icon(self, _event):
            row = self._chosen_icon()
            if row is None:
                return
            if not icons.try_it(row['id']):
                # Translators: said when an icon cannot be played.
                self._said(_('That one has no sound'))

        def _icon_folder(self, _event):
            # **Where to put your own.** Replacing an icon is dropping a
            # wave file with the right name into a folder, so the folder is
            # what this answers - and it is the user's own one, which wins
            # over the add-on's.
            where = icons.their_folder() or icons.OURS
            self._said(where)

        # ----------------------------------------------------- sound scheme
        def _scheme_page(self):
            import wx
            from gui import guiHelper
            page = wx.Panel(self.book)
            # Translators: a page of the manager window.
            self.book.AddPage(page, _('Sound scheme'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: text at the top of the sound scheme page.
            helper.addItem(wx.StaticText(page, label=_(
                'A state said in words costs a word every time. Choosing a '
                'sound for one you already expect - a tick box being ticked, '
                'a row being selected - takes the word away and leaves the '
                'sound. Nothing is chosen for you.')))
            # Translators: the list of control states.
            self.states = helper.addLabeledControl(
                _('&States'), wx.ListBox, style=wx.LB_SINGLE)
            self.states.Bind(wx.EVT_LISTBOX, self._state_chosen)
            self._ways = [schemes.AS_WORD, schemes.AS_SOUND, schemes.AS_BOTH]
            words = schemes.way_names()
            # Translators: how a control's state is answered.
            self.way = helper.addLabeledControl(
                _('Answer it with'), wx.Choice,
                choices=[words[way] for way in self._ways])
            self.way.Bind(wx.EVT_CHOICE, self._way_chosen)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the manager window.
            hear = buttons.addButton(page, label=_('&Hear it'))
            hear.Bind(wx.EVT_BUTTON, self._hear_state)
            # Translators: a button in the manager window.
            back = buttons.addButton(page, label=_('Put them all &back'))
            back.Bind(wx.EVT_BUTTON, self._reset_scheme)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._fill_states()

        def _fill_states(self, at=0):
            self._state_rows = schemes.described()
            words = schemes.way_names()
            self.states.Set(['%s - %s' % (row['label'],
                                          words.get(row['way'], ''))
                             for row in self._state_rows])
            if self._state_rows:
                self.states.SetSelection(
                    max(0, min(at, len(self._state_rows) - 1)))
            self._show_way()

        def _chosen_state(self):
            at = self.states.GetSelection()
            return self._state_rows[at] \
                if 0 <= at < len(self._state_rows) else None

        def _show_way(self):
            row = self._chosen_state()
            if row is None:
                return
            try:
                self.way.SetSelection(self._ways.index(row['way']))
            except ValueError:
                self.way.SetSelection(0)

        def _state_chosen(self, _event):
            self._show_way()

        def _way_chosen(self, _event):
            row = self._chosen_state()
            if row is None:
                return
            at = self.states.GetSelection()
            index = self.way.GetSelection()
            if 0 <= index < len(self._ways):
                schemes.set_way(row['state'], self._ways[index])
                self._fill_states(at=at)

        def _hear_state(self, _event):
            row = self._chosen_state()
            if row is not None:
                schemes.try_it(row['state'])

        def _reset_scheme(self, _event):
            schemes.reset(None)
            self._fill_states()

        # ---------------------------------------------------------- helpers
        def _said(self, text):
            from . import dialogs
            dialogs.report(text)

        def _close(self, _event):
            self.Destroy()

    return Manager


def show(parent=None):
    """Put the manager up. Answers whether it could."""
    manager = build()
    if manager is None:
        return False
    try:
        import gui
        import wx
        if parent is None:
            parent = gui.mainFrame

        def open_it():
            dialog = manager(parent)
            dialog.Show()
        wx.CallAfter(open_it)
        return True
    except Exception:                                # noqa: BLE001
        return False

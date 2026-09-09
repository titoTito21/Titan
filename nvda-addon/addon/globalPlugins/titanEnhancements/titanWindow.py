# -*- coding: utf-8 -*-
"""Titan, in a window of NVDA's own.

The Titan menu is right for a command - "run the macro that files my
downloads" - and wrong for a subsystem. What Titan can start, what its
settings hold, what arrived while a window was shut, what its widgets and
its status bar say: those are SCREENS, and offering them as a flat list of
actions whose arguments are typed in as text is offering them in the shape
that is hardest to use.

So: one window, a page per subsystem, opened with NVDA+shift+i or from the
menu. :mod:`titan` is the map it is built from; nothing here knows how the
bridge works and nothing in the bridge knows this exists.

**It is accessible because it is native.** A `wx.Notebook` is a real tab
control, a list is a real list, a button is a real button - NVDA announces
every one of them, counts them and follows the arrows through them with
not one line written here. That is the rule the Titan shell, the Elten
renderer and this add-on's own manager window each arrived at separately.

**Nothing waits on the GUI thread.** A bridge call is a named pipe to
another process, and Titan may be starting an application at the other end
of it - measured at up to forty-five seconds. NVDA's main thread is where
speech, braille and every event handler live, so a window that asked Titan
a question and waited for the answer would be a reader that had stopped
answering, which is the same fault Titan itself had when an OCR action ran
on ITS main thread. Every call goes to a worker and comes back through
`wx.CallAfter`.
"""

import threading

from . import i18n
from . import titan

_ = i18n.install(globals())

#: What can be started, and where each list comes from. A kind whose list
#: Titan cannot answer is left out of the chooser rather than being an
#: empty page nobody can act on.
STARTABLE = ('applications', 'games', 'cling', 'im', 'menu')


def _label_of(row, *names):
    for name in names:
        said = str(row.get(name) or '').strip()
        if said:
            return said
    return ''


def build():
    """The dialog class, or None when there is no wx."""
    try:
        import wx
        from gui import guiHelper
    except Exception:                                # noqa: BLE001
        return None

    class TitanWindow(wx.Dialog):

        def __init__(self, parent):
            # Translators: the title of the Titan window.
            super().__init__(parent, title=_('Titan'),
                             style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
            main = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
            self.book = main.addItem(wx.Notebook(self))
            self._start_page()
            self._settings_page()
            self._arrived_page()
            self._widgets_page()
            self._status_page()
            main.addDialogDismissButtons(self.CreateButtonSizer(wx.CLOSE))
            self.Bind(wx.EVT_BUTTON, self._close, id=wx.ID_CLOSE)
            self.EscapeId = wx.ID_CLOSE
            self.Sizer = main.sizer
            main.sizer.Fit(self)
            self.CentreOnScreen()
            self._kind_chosen(None)

        # ------------------------------------------------------- the worker
        def _do(self, work, then=None, saying=''):
            """Ask Titan on a thread; answer on the GUI thread.

            `saying` is what the user hears while it happens. It is said
            only for the things that really take a moment - starting an
            application - because a reader that narrates every list it
            fills is one people switch off.
            """
            if saying:
                self._say(saying)

            def run():
                try:
                    answer = work()
                except Exception as error:           # noqa: BLE001
                    answer = (False, '%s: %s' % (type(error).__name__, error))
                if then is None:
                    return
                try:
                    wx.CallAfter(self._answered, then, answer)
                except Exception:                    # noqa: BLE001
                    pass
            threading.Thread(target=run, name='TitanWindow',
                             daemon=True).start()

        def _answered(self, then, answer):
            # The window may have been closed while Titan was thinking, and
            # asking a destroyed wx object anything raises inside wx's own
            # event loop, where nothing catches it.
            if not self:
                return
            try:
                then(answer[0], answer[1])
            except RuntimeError:
                pass

        def _say(self, text):
            from . import dialogs
            dialogs.report(text)

        def _refused(self, said):
            # Titan's own sentence, in the user's own language: it names
            # the one thing that changes the answer, which a translation of
            # ours would not.
            self._say(str(said) or _('Titan did not answer'))

        # -------------------------------------------------------- starting
        def _start_page(self):
            import wx
            from gui import guiHelper
            page = wx.Panel(self.book)
            # Translators: a page of the Titan window.
            self.book.AddPage(page, _('Start'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            self._kinds = [
                # Translators: a kind of thing Titan can start.
                ('applications', _('Applications')),
                # Translators: a kind of thing Titan can start.
                ('games', _('Games')),
                # Translators: a kind of thing Titan can start.
                ('cling', _('Cling (Klango applications)')),
                # Translators: a kind of thing Titan can start.
                ('im', _('Titan IM')),
                # Translators: a kind of thing Titan can start.
                ('menu', _("Titan's own menu")),
            ]
            self.kind = helper.addLabeledControl(
                # Translators: the chooser on the Start page.
                _('&What'), wx.Choice,
                choices=[label for _id, label in self._kinds])
            self.kind.SetSelection(0)
            self.kind.Bind(wx.EVT_CHOICE, self._kind_chosen)
            # Translators: the list on the Start page.
            self.things = helper.addLabeledControl(
                _('&Titan has'), wx.ListBox, style=wx.LB_SINGLE)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the Titan window.
            start = buttons.addButton(page, label=_('&Open in Titan'))
            start.Bind(wx.EVT_BUTTON, self._start_it)
            # Translators: a button in the Titan window - it opens the
            # application as a screen here, in the reader, rather than as a
            # window over on Titan's own screen.
            here = buttons.addButton(page, label=_('Open &here'))
            here.Bind(wx.EVT_BUTTON, self._open_here)
            self._here_button = here
            helper.addItem(buttons)
            page.Sizer = helper.sizer

        def _kind_chosen(self, _event):
            at = self.kind.GetSelection()
            kind = self._kinds[at][0] if 0 <= at < len(self._kinds) else ''
            self._kind = kind
            # Only an application can be opened as a screen in here: a game
            # is played on Titan's own screen and a menu entry is a command,
            # so the button says so by being unavailable rather than by
            # answering with a refusal after it is pressed.
            self._here_button.Enable(kind == 'applications')
            self.things.Set([_('Asking Titan...')])
            readers = {
                'applications': titan.applications,
                'games': titan.games,
                'cling': titan.cling_applications,
                'im': titan.im_modules,
                'menu': titan.menu_groups,
            }
            self._do(readers[kind], self._things_are)

        def _things_are(self, ok, rows):
            if not ok:
                self.things.Set([])
                self._refused(rows)
                return
            self._things = []
            labels = []
            if self._kind == 'menu':
                for group in rows:
                    group_label = _label_of(group, 'label', 'id')
                    for entry in group.get('entries') or []:
                        if not isinstance(entry, dict):
                            continue
                        self._things.append(entry)
                        labels.append('%s: %s' % (group_label,
                                                  _label_of(entry, 'label',
                                                            'id')))
            else:
                for row in rows:
                    self._things.append(row)
                    labels.append(_label_of(row, 'name', 'label', 'id') or '?')
            self.things.Set(labels)
            if labels:
                self.things.SetSelection(0)

        def _chosen_thing(self):
            at = self.things.GetSelection()
            rows = getattr(self, '_things', [])
            return rows[at] if 0 <= at < len(rows) else None

        def _start_it(self, _event):
            row = self._chosen_thing()
            if row is None:
                return
            name = _label_of(row, 'name', 'label', 'id')
            kind = self._kind
            if kind == 'menu':
                entry = _label_of(row, 'id')
                self._do(lambda: titan.run_menu(entry), self._reported,
                         # Translators: said while Titan does something.
                         _('Opening {what}').format(what=name))
                return
            openers = {
                'applications': titan.open_application,
                'games': titan.open_game,
                'cling': titan.open_cling,
                'im': titan.open_im,
            }
            which = _label_of(row, 'id') if kind in ('cling', 'im') else name
            self._do(lambda: openers[kind](which), self._reported,
                     _('Opening {what}').format(what=name))

        def _reported(self, ok, said):
            if not ok:
                self._refused(said)
                return
            # Translators: said when Titan did what it was asked and said
            # nothing of its own about it.
            self._say(str(said) or _('Done'))

        def _open_here(self, _event):
            row = self._chosen_thing()
            if row is None:
                return
            name = _label_of(row, 'name', 'label', 'id')
            from . import appScreen
            self.Hide()
            appScreen.open_application(name, parent=self.Parent)
            self.Destroy()

        # -------------------------------------------------------- settings
        def _settings_page(self):
            import wx
            from gui import guiHelper
            page = wx.Panel(self.book)
            # Translators: a page of the Titan window.
            self.book.AddPage(page, _("Titan's settings"))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: the category chooser on the settings page.
            self.category = helper.addLabeledControl(
                _('&Category'), wx.Choice, choices=[])
            self.category.Bind(wx.EVT_CHOICE, self._category_chosen)
            # Translators: the list of settings.
            self.settings = helper.addLabeledControl(
                _('&Settings'), wx.ListBox, style=wx.LB_SINGLE)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the Titan window.
            change = buttons.addButton(page, label=_('C&hange...'))
            change.Bind(wx.EVT_BUTTON, self._change_setting)
            # Translators: a button in the Titan window.
            save = buttons.addButton(page, label=_('Sa&ve'))
            save.Bind(wx.EVT_BUTTON, self._save_settings)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._categories = []
            self._do(titan.settings, self._settings_are)

        def _settings_are(self, ok, rows):
            if not ok:
                self._refused(rows)
                return
            self._categories = rows
            self.category.Set([_label_of(row, 'name') or '?' for row in rows])
            if rows:
                self.category.SetSelection(0)
                self._category_chosen(None)

        def _category_chosen(self, _event):
            at = self.category.GetSelection()
            if not 0 <= at < len(self._categories):
                return
            self._items = [item for item
                           in (self._categories[at].get('items') or [])
                           if isinstance(item, dict)]
            self.settings.Set([_setting_line(item) for item in self._items])
            if self._items:
                self.settings.SetSelection(0)

        def _chosen_setting(self):
            at = self.settings.GetSelection()
            rows = getattr(self, '_items', [])
            return rows[at] if 0 <= at < len(rows) else None

        def _change_setting(self, _event):
            import wx
            item = self._chosen_setting()
            if item is None:
                return
            kind = str(item.get('kind') or '')
            control = str(item.get('id') or '')
            label = str(item.get('label') or control)
            if kind == 'info':
                self._say(str(item.get('value') or label))
                return
            if kind == 'command':
                self._do(lambda: titan.press_setting(control), self._changed)
                return
            if kind == 'bool':
                value = not _truthy(item.get('value'))
                self._do(lambda: titan.set_setting(control, value),
                         self._changed)
                return
            if kind in ('choice', 'list'):
                options = [str(option) for option in
                           (item.get('options') or [])]
                if not options:
                    # Translators: said when a setting offers no options.
                    self._say(_('There is nothing to choose here'))
                    return
                with wx.SingleChoiceDialog(self, label, _('Titan'),
                                           options) as chooser:
                    current = str(item.get('value') or '')
                    if current in options:
                        chooser.SetSelection(options.index(current))
                    if chooser.ShowModal() != wx.ID_OK:
                        return
                    picked = options[chooser.GetSelection()]
                self._do(lambda: titan.set_setting(control, picked),
                         self._changed)
                return
            if kind in ('text', 'number', 'secret'):
                with wx.TextEntryDialog(
                        self, label, _('Titan'),
                        '' if kind == 'secret'
                        else str(item.get('value') or '')) as box:
                    if box.ShowModal() != wx.ID_OK:
                        return
                    typed = box.GetValue()
                self._do(lambda: titan.set_setting(control, typed),
                         self._changed)
                return
            # **A kind this add-on has not been taught is not silently
            # dropped.** A tick list is several answers at once and Titan's
            # own window is where it is set; saying so is an answer, and a
            # button that did nothing would not be.
            self._say(_('{what} is set in Titan\'s own settings window')
                      .format(what=label))

        def _changed(self, ok, said):
            if not ok:
                self._refused(said)
                return
            if said:
                self._say(str(said))
            # What Titan holds has moved, so what is shown must move with
            # it - a settings window showing what a setting USED to be is
            # worse than one that shows nothing.
            self._do(titan.settings, self._settings_again)

        def _settings_again(self, ok, rows):
            if not ok:
                return
            at = self.category.GetSelection()
            where = self.settings.GetSelection()
            self._categories = rows
            self.category.Set([_label_of(row, 'name') or '?' for row in rows])
            if not rows:
                return
            self.category.SetSelection(max(0, min(at, len(rows) - 1)))
            self._category_chosen(None)
            if 0 <= where < self.settings.GetCount():
                self.settings.SetSelection(where)

        def _save_settings(self, _event):
            self._do(titan.save_settings, self._reported)

        # ---------------------------------------------------- what arrived
        def _arrived_page(self):
            import wx
            from gui import guiHelper
            page = wx.Panel(self.book)
            # Translators: a page of the Titan window.
            self.book.AddPage(page, _('What arrived'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: the list of notifications and buffers.
            self.arrived = helper.addLabeledControl(
                _('&What arrived'), wx.ListBox, style=wx.LB_SINGLE)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the Titan window.
            read = buttons.addButton(page, label=_('&Read it'))
            read.Bind(wx.EVT_BUTTON, self._read_arrived)
            # Translators: a button in the Titan window.
            again = buttons.addButton(page, label=_('Read the &list again'))
            again.Bind(wx.EVT_BUTTON, lambda _event: self._fill_arrived())
            # Translators: a button in the Titan window.
            clear = buttons.addButton(page, label=_('&Clear the notifications'))
            clear.Bind(wx.EVT_BUTTON, self._clear_arrived)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._fill_arrived()

        def _fill_arrived(self):
            self._arrived = []
            self._do(titan.notifications, self._notifications_are)

        def _notifications_are(self, ok, rows):
            labels = []
            if ok:
                for row in rows:
                    self._arrived.append(('notification', row))
                    labels.append(_label_of(row, 'text', 'message', 'title')
                                  or '?')
            self.arrived.Set(labels)
            self._do(titan.buffers, self._buffers_are)

        def _buffers_are(self, ok, rows):
            if not ok:
                if not self.arrived.GetCount():
                    self._refused(rows)
                return
            labels = list(self.arrived.GetStrings())
            for category in rows:
                where = _label_of(category, 'name', 'id')
                for buffer in category.get('buffers') or []:
                    if not isinstance(buffer, dict):
                        continue
                    count = buffer.get('count')
                    self._arrived.append(('buffer', dict(
                        buffer, category=_label_of(category, 'id'))))
                    labels.append('%s: %s (%s)'
                                  % (where, _label_of(buffer, 'name', 'id'),
                                     count if count is not None else '?'))
            self.arrived.Set(labels)
            if labels and self.arrived.GetSelection() < 0:
                self.arrived.SetSelection(0)

        def _read_arrived(self, _event):
            at = self.arrived.GetSelection()
            rows = getattr(self, '_arrived', [])
            if not 0 <= at < len(rows):
                return
            kind, row = rows[at]
            if kind == 'notification':
                from . import dialogs
                dialogs.browse(_label_of(row, 'text', 'message', 'title'),
                               _('Titan'))
                return
            name = _label_of(row, 'id', 'name')
            category = str(row.get('category') or '')
            self._do(lambda: titan.read_buffer_category(name, category),
                     self._buffer_read)

        def _buffer_read(self, ok, rows):
            from . import dialogs
            if not ok:
                self._refused(rows)
                return
            lines = []
            for row in rows:
                if isinstance(row, dict):
                    lines.append(_label_of(row, 'text', 'message', 'name'))
                else:
                    lines.append(str(row))
            if not lines:
                # Translators: said when a buffer has nothing in it.
                self._say(_('Nothing in there'))
                return
            dialogs.browse('\n'.join(lines), _('Titan'))

        def _clear_arrived(self, _event):
            self._do(titan.clear_notifications, self._cleared)

        def _cleared(self, ok, said):
            self._reported(ok, said)
            self._fill_arrived()

        # --------------------------------------------------------- widgets
        def _widgets_page(self):
            import wx
            from gui import guiHelper
            page = wx.Panel(self.book)
            # Translators: a page of the Titan window.
            self.book.AddPage(page, _('Widgets'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: the list of Titan's widgets.
            self.widgets = helper.addLabeledControl(
                _('&Widgets'), wx.ListBox, style=wx.LB_SINGLE)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the Titan window.
            read = buttons.addButton(page, label=_('&Read it'))
            read.Bind(wx.EVT_BUTTON, self._read_widget)
            # Translators: a button in the Titan window.
            press = buttons.addButton(page, label=_('&Press it'))
            press.Bind(wx.EVT_BUTTON, self._press_widget)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._do(titan.widgets, self._widgets_are)

        def _widgets_are(self, ok, rows):
            if not ok:
                self._refused(rows)
                return
            self._widget_rows = rows
            self.widgets.Set(['%s (%s)' % (_label_of(row, 'name', 'id'),
                                           _label_of(row, 'type') or '?')
                              for row in rows])
            if rows:
                self.widgets.SetSelection(0)

        def _chosen_widget(self):
            at = self.widgets.GetSelection()
            rows = getattr(self, '_widget_rows', [])
            return _label_of(rows[at], 'id', 'name') \
                if 0 <= at < len(rows) else ''

        def _read_widget(self, _event):
            widget = self._chosen_widget()
            if widget:
                self._do(lambda: titan.read_widget(widget), self._reported)

        def _press_widget(self, _event):
            widget = self._chosen_widget()
            if widget:
                self._do(lambda: titan.press_widget(widget), self._reported)

        # ---------------------------------------------------------- status
        def _status_page(self):
            import wx
            from gui import guiHelper
            page = wx.Panel(self.book)
            # Translators: a page of the Titan window.
            self.book.AddPage(page, _('Status bar'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: the list of what Titan's status bar says.
            self.status = helper.addLabeledControl(
                _('Titan\'s &status bar'), wx.ListBox, style=wx.LB_SINGLE)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the Titan window.
            again = buttons.addButton(page, label=_('Read it a&gain'))
            again.Bind(wx.EVT_BUTTON, lambda _event: self._fill_status())
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._fill_status()

        def _fill_status(self):
            self._do(titan.statusbar, self._status_is)

        def _status_is(self, ok, rows):
            if not ok:
                self._refused(rows)
                return
            self.status.Set([_label_of(row, 'text', 'key') for row in rows])
            if rows:
                self.status.SetSelection(0)

        # --------------------------------------------------------- closing
        def _close(self, _event):
            self.Destroy()

    return TitanWindow


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on', 'tak')
    return bool(value)


def _setting_line(item):
    """One setting as a row: what it is called, and what it is set to.

    A settings list that showed only the names would make the user open
    every one of them to find out what it holds, which for somebody
    working by ear is the whole window being useless.
    """
    label = str(item.get('label') or item.get('id') or '?')
    kind = str(item.get('kind') or '')
    if kind == 'bool':
        # Translators: a setting that is on. / Translators: one that is off.
        return '%s: %s' % (label, _('on') if _truthy(item.get('value'))
                           else _('off'))
    if kind == 'command':
        return label
    if kind == 'secret':
        value = item.get('value')
        # Translators: how a password or key is shown - never its value.
        return '%s: %s' % (label, _('set') if value else _('not set'))
    value = item.get('value')
    if value in (None, ''):
        return label
    return '%s: %s' % (label, value)


def show(parent=None):
    """Put the Titan window up. Answers whether it could."""
    window = build()
    if window is None:
        return False
    try:
        import gui
        import wx
        if parent is None:
            parent = gui.mainFrame

        def open_it():
            window(parent).Show()
        wx.CallAfter(open_it)
        return True
    except Exception:                                # noqa: BLE001
        return False

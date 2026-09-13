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
            # **The list is called what is IN it.** It was "Titan has",
            # which is a sentence about the window rather than the name of
            # the thing the keyboard has landed on - so a reader said
            # "Titan has, list" where it should say "Applications, list".
            # The label follows the chooser, which is what Titan's own
            # window does (`views.list` carries a `short_name` per view).
            #
            # The static text is kept rather than made by `addLabeledControl`,
            # because that helper hands back the control and throws the
            # label away - and this one has to be renamed.
            self._things_label = wx.StaticText(page, label='')
            helper.addItem(self._things_label)
            self.things = helper.addItem(
                wx.ListBox(page, style=wx.LB_SINGLE))
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # **Open means the virtual window**, which is the shape
            # everything else in this add-on is walked in. It used to
            # build a window of native controls instead, and that is a
            # second interface to be in rather than the one the user has
            # already learned - it is still there, as "As real controls"
            # on the Titan menu, for a form that is easier to fill in than
            # to read.
            here = buttons.addButton(page, label=_('&Open'))
            here.Bind(wx.EVT_BUTTON, self._open_here)
            # Translators: a button in the Titan window - it opens the
            # thing on Titan's own screen instead of here.
            start = buttons.addButton(page, label=_('Open in &Titan'))
            start.Bind(wx.EVT_BUTTON, self._start_it)
            helper.addItem(buttons)
            page.Sizer = helper.sizer

        def _kind_chosen(self, _event):
            at = self.kind.GetSelection()
            kind = self._kinds[at][0] if 0 <= at < len(self._kinds) else ''
            self._kind = kind
            name = self._kinds[at][1] if 0 <= at < len(self._kinds) else ''
            self._things_label.SetLabel(name)
            # **Open always opens.** It used to be unavailable for
            # anything but an application, because only an application can
            # be a virtual window - but "open" has an obvious meaning for
            # a game and a menu entry too, and a first button that is
            # greyed out for four of the five kinds is a button nobody
            # trusts. It opens what it can here and hands the rest to
            # Titan, which is what the user meant either way.
            # Both, because they are read by different things: wx uses the
            # static text in front of the control, and a screen reader
            # asks the control itself.
            self.things.SetName(name)
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
            """Open the application as a VIRTUAL WINDOW, walked with the
            arrows - not as a window of native controls.

            The window is destroyed rather than left behind it: the review
            borrows the arrow keys, and a window still on the screen that
            no longer answers them is worse than no window.
            """
            row = self._chosen_thing()
            if row is None:
                return
            if self._kind != 'applications':
                # A game is played on Titan's own screen and a menu entry
                # is a command: there is no virtual window to be had, and
                # the honest thing is to do what "open" means for it.
                self._start_it(None)
                return
            name = _label_of(row, 'name', 'label', 'id')
            from . import appReview
            _ok, said = appReview.start(name)
            self._say(said)
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
            # **Shaped like the JAWS Settings Center**, because that is the
            # shape people who set a lot of settings by ear already know:
            # one list of settings with their values on the row, and SPACE
            # acts on the row - a tick box is ticked, a choice is opened, a
            # command is run. Pressing a button called "Change" is one more
            # thing to Tab to for something that should be a keystroke.
            self.settings = helper.addLabeledControl(
                # Translators: the list of settings.
                _('&Settings'), wx.ListBox, style=wx.LB_SINGLE)
            self.settings.Bind(wx.EVT_CHAR_HOOK, self._setting_key)
            self.settings.Bind(wx.EVT_LISTBOX, self._setting_chosen)
            # **And where the setting is a word, it IS an edit field.** A
            # setting that holds text or a number is edited in place, in a
            # real `wx.TextCtrl` that appears for it and goes away again -
            # not in a dialog on top of the window, which is a second
            # place for the keyboard to be.
            self.field_label = wx.StaticText(page, label='')
            helper.addItem(self.field_label)
            self.field = helper.addItem(
                wx.TextCtrl(page, style=wx.TE_PROCESS_ENTER))
            self.field.Bind(wx.EVT_TEXT_ENTER, self._field_entered)
            self.field.Hide()
            self.field_label.Hide()
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the Titan window.
            save = buttons.addButton(page, label=_('Sa&ve'))
            save.Bind(wx.EVT_BUTTON, self._save_settings)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._categories = []
            self._do(titan.settings, self._settings_are)

        def _setting_key(self, event):
            import wx
            code = event.GetKeyCode()
            if code in (wx.WXK_SPACE, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                self._change_setting(None)
                return
            event.Skip()

        def _setting_chosen(self, _event):
            """Show the edit field for a setting that is a word.

            It follows the cursor rather than waiting to be asked for, so
            arriving on a setting that is text puts the field there ready -
            which is what "then it is an edit field" means.
            """
            item = self._chosen_setting()
            if item is None:
                return
            kind = str(item.get('kind') or '')
            wanted = kind in ('text', 'number', 'secret')
            self.field_label.Show(wanted)
            self.field.Show(wanted)
            if wanted:
                label = str(item.get('label') or item.get('id') or '')
                self.field_label.SetLabel(label)
                self.field.SetName(label)
                self.field.ChangeValue(
                    '' if kind == 'secret' else str(item.get('value') or ''))
            self.Layout()

        def _field_entered(self, _event):
            item = self._chosen_setting()
            if item is None:
                return
            control = str(item.get('id') or '')
            typed = self.field.GetValue()
            self._do(lambda: titan.set_setting(control, typed), self._changed)

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
                self._setting_chosen(None)

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
                # The field is already there, under the list, holding this
                # setting's value. Space puts the keyboard in it; Enter in
                # the field is what commits.
                self._setting_chosen(None)
                self.field.SetFocus()
                self.field.SetInsertionPointEnd()
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
            # **Entering a widget puts you IN it.** There were three
            # buttons under this list, and what somebody arriving at a
            # widget wants is the widget - walked with the arrow keys,
            # the way everything else on this desktop is walked. So Enter
            # and a double click open it, which is what Enter means on a
            # row everywhere else, and the button that only repeated that
            # is gone. Read and Press stay: they are different VERBS and
            # cannot both be Enter.
            self.widgets.Bind(wx.EVT_LISTBOX_DCLICK, self._walk_widget)
            self.widgets.Bind(wx.EVT_CHAR_HOOK, self._widget_key)
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

        def _widget_key(self, event):
            """Enter opens the widget; everything else is the list's."""
            import wx
            if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                self._walk_widget(event)
                return
            event.Skip()

        def _read_widget(self, _event):
            widget = self._chosen_widget()
            if widget:
                self._do(lambda: titan.read_widget(widget), self._reported)

        def _press_widget(self, _event):
            widget = self._chosen_widget()
            if widget:
                self._do(lambda: titan.press_widget(widget), self._reported)

        def _walk_widget(self, _event):
            """Leave the window and walk the widget with the arrows.

            The window is closed rather than left open behind it: the
            review borrows the arrow keys, and a window still on the
            screen that no longer answers them is worse than no window.
            """
            at = self.widgets.GetSelection()
            rows = getattr(self, '_widget_rows', [])
            if not 0 <= at < len(rows):
                return
            from . import widgetReview
            name = _label_of(rows[at], 'id', 'name')
            label = _label_of(rows[at], 'name', 'id')
            _ok, said = widgetReview.start(name, label)
            self._say(said)
            self.Destroy()

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
    if kind == 'multi':
        # **A tick list is said as WORDS, never as the list it is.** Its
        # value really is a list, and a list put into a row through `str()`
        # is `['tNotes', 'tEdit']` - brackets, quotes and commas, which a
        # screen reader then reads out one punctuation mark at a time.
        # Titan learned this about a character sheet and it is the same
        # mistake one field smaller.
        ticked = [str(one) for one in (item.get('value') or [])]
        # Translators: a tick list with nothing ticked in it.
        return '%s: %s' % (label, ', '.join(ticked) if ticked else _('none'))
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

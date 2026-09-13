# -*- coding: utf-8 -*-
"""A Titan application, as a window of NVDA's own.

Titan's applications are ordinary wxPython programs in subprocesses of
their own. `src/app_ui` runs one against a shim `wx` that **describes** its
interface instead of drawing it - a flat list of controls with a kind, a
label and a value, and no layout at all, because a sizer says where a
button sits on a rectangle and an interface made of speech has no
rectangle. Titan's own bridge serves that as `app.list` / `open` / `screen`
/ `press` / `set` / `key` / `close`.

So the reader can build the application's screen out of **its own native
controls**. That is worth doing rather than merely reading the description
aloud: a real `wx.CheckBox` is announced by Windows as a check box with a
state, a real list is counted and walked by NVDA with no code here, and a
real button is pressed with Space. For somebody who cannot see a screen,
this is frequently a better interface than the application's own.

**Everything here was learned once already, in Elten**, and the notes in
`CLAUDE.md` are not decoration - each of these is a bug that shipped:

* What counts as "the screen changed" is what the controls HOLD, and never
  the INDEX. The cursor moving is not the screen changing, and rebuilding
  the form for it takes the keyboard away on every arrow key.
* The control just set is left out of BOTH sides of that comparison, or a
  form is rebuilt on every keystroke and a typed word comes out backwards.
* An application announces what it did (`said`), and that is news the
  screen behind it does not carry - it is said FIRST and separately.
* A control kind this renderer has not been taught becomes a line of text
  rather than disappearing. A control silently missing is the worst
  possible answer for somebody who cannot see the window.

**Nothing waits on NVDA's main thread.** Opening an application is a
subprocess start - measured in seconds - and pressing something waits on
that application's own handler.
"""

import threading

from . import i18n
from . import titan

_ = i18n.install(globals())

#: Kinds this builds a real control for. Anything else is described as a
#: line of text, which is the floor and never nothing.
KINDS = ('label', 'text', 'multiline', 'button', 'check', 'choice', 'list',
         'table', 'tree', 'slider', 'gauge', 'tabs')

#: The keys an application is given rather than a control. `Escape` is
#: deliberately not among them: the application answers it, but so does
#: this window, and a key that both close on is a window that vanishes.
KEYS = {
    'F1': 'f1', 'F2': 'f2', 'F3': 'f3', 'F4': 'f4', 'F5': 'f5',
    'DELETE': 'delete', 'BACK': 'back', 'HOME': 'home', 'END': 'end',
    'PAGEUP': 'pageup', 'PAGEDOWN': 'pagedown',
}


def fingerprint(screen, ignore=None):
    """What the screen HOLDS, as one comparable string.

    Deliberately not the index: the cursor moving is not the screen
    changing. `ignore` is the control the user has just set - it holds what
    was typed a moment ago and differs from itself on every keystroke.
    """
    if not isinstance(screen, dict):
        return ''
    parts = [str(screen.get('title') or ''), str(screen.get('kind') or '')]
    for control in screen.get('controls') or []:
        if not isinstance(control, dict):
            continue
        if ignore is not None and control.get('id') == ignore:
            parts.append('~%s' % control.get('id'))
            continue
        parts.append('|'.join(str(control.get(name, ''))
                              for name in ('id', 'kind', 'label', 'value',
                                           'options', 'items', 'columns')))
    return '\n'.join(parts)


def line_for(control):
    """One control as a sentence - the floor under every control kind."""
    label = str(control.get('label') or '')
    kind = str(control.get('kind') or '')
    value = control.get('value')
    if value in (None, ''):
        return label or kind
    return '%s: %s' % (label or kind, value)


def row_text(row):
    """One row of a list, a table or a tree, whatever shape it arrived in.

    A table's row is a list of cells and a list's row is a string; a
    renderer that assumed one of the two would show `['a', 'b']` to
    somebody who cannot see it.
    """
    if isinstance(row, (list, tuple)):
        return ', '.join(str(cell) for cell in row)
    if isinstance(row, dict):
        for name in ('text', 'label', 'name'):
            if row.get(name):
                return str(row[name])
        return ', '.join(str(value) for value in row.values())
    return str(row)


def build():
    """The dialog class, or None when there is no wx."""
    try:
        import wx
        from gui import guiHelper
    except Exception:                                # noqa: BLE001
        return None

    class AppScreen(wx.Dialog):
        """One described application, for as long as it is open."""

        def __init__(self, parent, session, screen, name=''):
            self.session = session
            self.screen = screen if isinstance(screen, dict) else {}
            self.app_name = name or str(self.screen.get('title') or '')
            super().__init__(parent, title=self.app_name or _('Titan'),
                             style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
            self._controls = {}
            self._setting = None
            self._panel = None
            self._sizer = wx.BoxSizer(wx.VERTICAL)
            self.SetSizer(self._sizer)
            self._render()
            self.Bind(wx.EVT_CHAR_HOOK, self._key)
            self.Bind(wx.EVT_CLOSE, self._closing)
            self.CentreOnScreen()

        # ------------------------------------------------------- the worker
        def _do(self, work, then=None):
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
            threading.Thread(target=run, name='TitanAppScreen',
                             daemon=True).start()

        def _answered(self, then, answer):
            if not self:
                return
            try:
                then(answer[0], answer[1])
            except RuntimeError:
                pass

        def _say(self, text, voice_class='notification'):
            from . import dialogs
            dialogs.report(text, voice_class=voice_class)

        # -------------------------------------------------------- rendering
        def _render(self):
            """Build the screen as real controls.

            The whole panel is replaced rather than mended: a described
            screen is a flat list with no identity between one reading and
            the next, and matching controls up would be a second opinion
            about what changed on top of the one `fingerprint` already
            gives.
            """
            import wx
            from gui import guiHelper
            where = self._focused_id()
            if self._panel is not None:
                self._sizer.Detach(self._panel)
                self._panel.Destroy()
            self._panel = wx.Panel(self)
            self._controls = {}
            helper = guiHelper.BoxSizerHelper(self._panel,
                                              orientation=wx.VERTICAL)
            controls = [control for control
                        in (self.screen.get('controls') or [])
                        if isinstance(control, dict)]
            if not controls:
                # An application with no window open is not one with nothing
                # to say - Titan's own organiser hides its only window - so
                # this says what happened rather than showing an empty box.
                helper.addItem(wx.StaticText(
                    self._panel,
                    label=_('This application has nothing on the screen.')))
            for control in controls:
                self._build_one(helper, control)
            if self.screen.get('menus'):
                buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
                # Translators: a button that opens the application's menus.
                menu = buttons.addButton(self._panel, label=_('&Menu'))
                menu.Bind(wx.EVT_BUTTON, self._open_menu)
                helper.addItem(buttons)
            self._panel.SetSizer(helper.sizer)
            self._sizer.Add(self._panel, 1, wx.EXPAND | wx.ALL, 5)
            self.SetTitle(str(self.screen.get('title') or self.app_name
                              or _('Titan')))
            self.Layout()
            self._sizer.Fit(self)
            self._put_the_keyboard_back(where)

        def _build_one(self, helper, control):
            import wx
            kind = str(control.get('kind') or '')
            label = str(control.get('label') or '')
            identifier = control.get('id')
            if kind == 'button':
                button = wx.Button(self._panel, label=label or _('Button'))
                button.Bind(wx.EVT_BUTTON,
                            lambda _event, at=identifier: self._press(at))
                helper.addItem(button)
                self._controls[identifier] = button
                return
            if kind == 'check':
                box = wx.CheckBox(self._panel, label=label)
                box.SetValue(bool(control.get('value')))
                box.Bind(wx.EVT_CHECKBOX,
                         lambda event, at=identifier:
                         self._set(at, event.IsChecked()))
                helper.addItem(box)
                self._controls[identifier] = box
                return
            if kind == 'choice':
                options = [str(option) for option in
                           (control.get('options') or [])]
                choice = helper.addLabeledControl(label or _('Choose'),
                                                  wx.Choice, choices=options)
                index = control.get('index')
                if isinstance(index, int) and 0 <= index < len(options):
                    choice.SetSelection(index)
                choice.Bind(wx.EVT_CHOICE,
                            lambda event, at=identifier:
                            self._set(at, event.GetSelection()))
                self._controls[identifier] = choice
                return
            if kind in ('list', 'table', 'tree'):
                rows = [row_text(row) for row in (control.get('items') or [])]
                listing = helper.addLabeledControl(
                    label or _('List'), wx.ListBox, choices=rows,
                    style=wx.LB_SINGLE)
                index = control.get('index')
                if isinstance(index, int) and 0 <= index < len(rows):
                    listing.SetSelection(index)
                listing.Bind(wx.EVT_LISTBOX,
                             lambda event, at=identifier:
                             self._set(at, event.GetSelection(), quiet=True))
                listing.Bind(wx.EVT_LISTBOX_DCLICK,
                             lambda _event: self._key_to_app('enter'))
                self._controls[identifier] = listing
                return
            if kind in ('text', 'multiline'):
                style = wx.TE_MULTILINE if kind == 'multiline' else 0
                field = helper.addLabeledControl(
                    label or _('Field'), wx.TextCtrl, style=style)
                field.SetValue(str(control.get('value') or ''))
                field.Bind(wx.EVT_KILL_FOCUS,
                           lambda event, at=identifier, box=field:
                           self._typed(event, at, box))
                self._controls[identifier] = field
                return
            if kind == 'slider':
                low = _whole(control.get('minimum'), 0)
                high = _whole(control.get('maximum'), 100)
                slider = helper.addLabeledControl(
                    label or _('Slider'), wx.Slider, minValue=low,
                    maxValue=max(high, low + 1))
                slider.SetValue(_whole(control.get('value'), low))
                slider.Bind(wx.EVT_SCROLL_CHANGED,
                            lambda event, at=identifier:
                            self._set(at, event.GetPosition()))
                self._controls[identifier] = slider
                return
            if kind == 'gauge':
                # A meter is READ, not set - so it is a read-only field
                # rather than a `wx.Gauge`, which a reader cannot land on.
                self._read_only(helper, identifier, line_for(control))
                return
            if kind == 'tabs':
                options = [str(page) for page in (control.get('items') or
                                                  control.get('options') or [])]
                if options:
                    tabs = helper.addLabeledControl(label or _('Pages'),
                                                    wx.Choice, choices=options)
                    index = control.get('index')
                    if isinstance(index, int) and 0 <= index < len(options):
                        tabs.SetSelection(index)
                    tabs.Bind(wx.EVT_CHOICE,
                              lambda event, at=identifier:
                              self._set(at, event.GetSelection()))
                    self._controls[identifier] = tabs
                    return
            # `label`, and everything this renderer has never heard of.
            self._read_only(helper, identifier, line_for(control))

        def _read_only(self, helper, identifier, text):
            """Text the user can land on, read and copy.

            A `wx.StaticText` cannot be focused and a reader cannot put its
            cursor in one, so a line of an application's own text would be
            unreachable - the same answer AI OCR's rebuilt forms and
            Elten's `Static` both arrived at.
            """
            import wx
            if not str(text).strip():
                return
            field = wx.TextCtrl(self._panel, value=str(text),
                                style=wx.TE_READONLY | wx.TE_MULTILINE
                                if '\n' in str(text) else wx.TE_READONLY)
            field.SetName(str(text))
            helper.addItem(field)
            if identifier is not None:
                self._controls[identifier] = field

        # ---------------------------------------------------------- acting
        def _press(self, control):
            self._setting = None
            self._do(lambda: titan.press_described(self.session, control),
                     self._came_back)

        def _set(self, control, value, quiet=False):
            self._setting = control
            self._do(lambda: titan.set_described(self.session, control, value),
                     self._came_back if not quiet else self._quietly)

        def _typed(self, event, control, box):
            event.Skip()
            self._set(control, box.GetValue(), quiet=True)

        def _key_to_app(self, key):
            self._setting = None
            self._do(lambda: titan.key_described(self.session, key),
                     self._came_back)

        def _quietly(self, ok, answer):
            """A change the user made themselves: no announcement.

            Moving through a list and typing into a field are things the
            reader has already spoken about. What matters is that the
            SCREEN is kept up to date, in case the application answered by
            changing something else.
            """
            self._came_back(ok, answer, quiet=True)

        def _came_back(self, ok, answer, quiet=False):
            if not ok:
                self._say(str(answer))
                return
            from . import appReview
            said = ' '.join(appReview.announcements(answer))
            screen = answer.get('screen') if isinstance(answer, dict) else None
            if said:
                # News first: the screen behind a save usually looks exactly
                # as it did before, so a user handed only the screen is told
                # nothing at all about what happened.
                self._say(said)
            if not isinstance(screen, dict):
                if not quiet and not said and isinstance(answer, dict) \
                        and answer.get('answered') is False:
                    # Translators: said when an application has not answered
                    # yet - which is a different thing from it doing nothing.
                    self._say(_('The application has not answered yet'))
                return
            before = fingerprint(self.screen, ignore=self._setting)
            after = fingerprint(screen, ignore=self._setting)
            self.screen = screen
            if before != after:
                self._render()

        # --------------------------------------------------------- the keys
        def _key(self, event):
            import wx
            code = event.GetKeyCode()
            if code == wx.WXK_ESCAPE:
                self.Close()
                return
            if code == wx.WXK_F5:
                self._refresh()
                return
            for name, key in KEYS.items():
                if code == getattr(wx, 'WXK_' + name, None):
                    if self._takes_its_own_keys() and name in ('BACK',
                                                               'DELETE'):
                        break
                    self._key_to_app(key)
                    return
            if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                if self._enter_belongs_to_the_app():
                    self._key_to_app('enter')
                    return
            event.Skip()

        def _takes_its_own_keys(self):
            """Whether the control under the keyboard is being typed into.

            Backspace and Delete in a field are the letter just typed, and
            forwarding them to the application while somebody corrects a
            word is how a field becomes impossible to use.
            """
            import wx
            focused = self.FindFocus()
            return isinstance(focused, wx.TextCtrl) and \
                not focused.HasFlag(wx.TE_READONLY)

        def _enter_belongs_to_the_app(self):
            """A one-line field does not own Enter; a list does not either.

            Elten's own rule, and the reason a number typed into a field
            and accepted with Enter used to do nothing at all: the field
            kept the key and had nothing to do with it.
            """
            import wx
            focused = self.FindFocus()
            if isinstance(focused, wx.Button):
                return False
            if isinstance(focused, wx.TextCtrl) and \
                    focused.HasFlag(wx.TE_MULTILINE):
                return False
            return True

        def _refresh(self):
            self._setting = None
            self._do(lambda: titan.described_screen(self.session),
                     self._came_back)

        # ---------------------------------------------------------- menus
        def _open_menu(self, _event):
            import wx
            menu = wx.Menu()
            self._menu_doing = {}
            for group in self.screen.get('menus') or []:
                if not isinstance(group, dict):
                    continue
                where = str(group.get('label') or '')
                for item in group.get('items') or []:
                    if not isinstance(item, dict) or item.get('id') is None:
                        continue
                    entry = menu.Append(wx.ID_ANY, '%s: %s'
                                        % (where, item.get('label') or ''))
                    self._menu_doing[entry.GetId()] = item.get('id')
            if not self._menu_doing:
                return
            self.Bind(wx.EVT_MENU, self._menu_chosen)
            self.PopupMenu(menu)
            menu.Destroy()

        def _menu_chosen(self, event):
            control = self._menu_doing.get(event.GetId())
            if control is not None:
                self._press(control)

        # -------------------------------------------------------- keyboard
        def _focused_id(self):
            focused = self.FindFocus()
            for identifier, control in self._controls.items():
                if control is focused:
                    return identifier
            return None

        def _put_the_keyboard_back(self, where):
            """The control the user was on, or the first that will take it.

            A rebuilt panel has no focus at all, and a dialog that answers
            no key is one the user has to Tab back into after every press.
            """
            control = self._controls.get(where)
            if control is not None:
                try:
                    control.SetFocus()
                    return
                except Exception:                    # noqa: BLE001
                    pass
            for child in self._panel.GetChildren():
                if child.AcceptsFocusFromKeyboard():
                    child.SetFocus()
                    return

        # --------------------------------------------------------- closing
        def _closing(self, event):
            event.Skip()
            session = self.session
            # The application is a process: leaving the window open on
            # Titan's side would leave it running with nobody rendering it.
            threading.Thread(
                target=lambda: titan.close_described(session),
                name='TitanAppClose', daemon=True).start()

    return AppScreen


def _whole(value, fallback=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def open_application(name, parent=None):
    """Open a Titan application as a window here. Answers whether it could.

    The open happens on a thread: it starts a subprocess at the other end,
    which is seconds, and NVDA's main thread is where speech lives.
    """
    screen_class = build()
    if screen_class is None:
        return False
    try:
        import gui
        import wx
    except Exception:                                # noqa: BLE001
        return False
    if parent is None:
        parent = gui.mainFrame
    from . import dialogs
    # Translators: said while a Titan application is being opened.
    dialogs.report(_('Opening {what}').format(what=name))

    def work():
        ok, data = titan.open_described(name)

        def show():
            if not ok:
                dialogs.message(str(data))
                return
            session = str(data.get('session') or '')
            if not session:
                # Translators: said when Titan could not describe an
                # application's interface.
                dialogs.message(_('Titan did not open that application.'))
                return
            from . import appReview
            said = ' '.join(appReview.announcements(data))
            if data.get('mirror'):
                # **A mirror is a weaker thing and says so.** A described
                # screen is the application's own account of itself; a
                # mirrored one is what Windows can see of its window, where
                # a control Windows cannot name has no name here either.
                said = (said + ' ' if said else '') + _(
                    'This is read off the window, so it says less than the '
                    'application could.')
            if said:
                dialogs.report(said)
            screen_class(parent, session, data.get('screen'), name).Show()
        wx.CallAfter(show)
    threading.Thread(target=work, name='TitanAppOpen', daemon=True).start()
    return True

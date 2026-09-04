# -*- coding: utf-8 -*-
"""Elten's screens, as real wx windows.

Copyright (C) 2026 titosoft. Part of the Elten API bridge, licensed under the
GNU General Public License version 3 or later; see `LICENSE` beside this
component.

Elten itself has no graphical interface at all - it is entirely self-voicing,
built on a single-threaded polling loop that reads the keyboard and speaks.
That is a deliberate design and a real one, but it is not Titan's: Titan's
own applications are wx windows a screen reader already knows how to read,
with the keyboard behaving the way it behaves everywhere else on this
desktop. So `Form`, `ListBox`, `EditBox`, `Button` and `CheckBox` - the
controls an Elten application actually builds its OWN screens out of, not
just the three stock dialogs - are answered here with real `wx` widgets.

**Every call into this class runs on the GUI thread**, marshalled there by
`bridge.Application._on_gui`, so the methods below create and touch wx
objects directly rather than through another layer of dispatch.
"""

import wx

#: The skin icon that suits each kind of control, by the keys every Titan
#: skin carries (`skins/<name>/icons/*.png`). An Elten application's screen
#: is a Titan window, so it wears the skin the user chose - the colours, the
#: fonts and the pictures - like every other window on this desktop.
CONTROL_ICONS = {
    'listbox': 'apps',
    'tablebox': 'components',
    'editbox': 'edit',
    'checkbox': 'settings',
    'filestree': 'folder',
    'button': 'open',
}

#: What a button's own label suggests it does, where a skin has a picture
#: for it. Matched on the lower-cased label in the user's own language as
#: well as English, because that is what the label actually is.
BUTTON_ICONS = (
    (('back', 'wstecz', 'powrót', 'powrot'), 'back'),
    (('close', 'zamknij', 'exit', 'wyjdź', 'wyjdz'), 'close'),
    (('cancel', 'anuluj'), 'close'),
    (('open', 'otwórz', 'otworz'), 'open'),
    (('save', 'zapisz'), 'save'),
    (('add', 'dodaj', 'new', 'nowa', 'nowy'), 'add'),
    (('delete', 'usuń', 'usun', 'remove'), 'delete'),
    (('edit', 'edytuj', 'zmień', 'zmien'), 'edit'),
    (('search', 'szukaj', 'wyszukaj'), 'search'),
    (('refresh', 'odśwież', 'odswiez'), 'refresh'),
    (('settings', 'ustawienia'), 'settings'),
    (('help', 'pomoc'), 'help'),
)


def _name(window, name):
    """Give a control a name every screen reader can read.

    `SetName` alone is wx's own name and never reaches a reader for a native
    control - a list view answers with its own IAccessible, whose name comes
    from window text these controls have none of. Titan already learned this
    building the shell, and `a11y.name_control` is the one way in: it names
    the control for wx AND for MSAA. Without it an Elten application's list
    is an unnamed box, which for the people these applications are written
    for is the whole interface missing.
    """
    if not name:
        return window
    try:
        from src.shell.a11y import name_control
        name_control(window, name)
        return window
    except Exception:
        try:
            window.SetName(name)
        except Exception:
            pass
    return window


def _skin():
    """Titan's current skin, or None when there is not one to be had."""
    try:
        from src.titan_core.skin_manager import get_current_skin
        return get_current_skin()
    except Exception:
        return None


def _t(text):
    """One of the bridge's own words, in the user's language.

    Almost nothing here has words of its own - the labels, headers and
    prompts all come from the application, already translated by its own
    catalogue - so this is only for the few controls Titan builds itself,
    like the player's transport buttons.
    """
    try:
        from .. import init as component
        return component._(text)
    except Exception:
        pass
    try:
        import gettext
        import os
        from src.titan_core.translation import language_code
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return gettext.translation('elten_bridge',
                                   os.path.join(here, 'languages'),
                                   languages=[language_code or 'en'],
                                   fallback=True).gettext(text)
    except Exception:
        return text


def _cue(name, pan=None):
    """One of Titan's own interface sounds, straight from the user's theme.

    **This is what makes navigating an Elten application sound like
    navigating Titan.** Elten's controls are self-voicing and play their
    own cue as the cursor moves; the controls here are real wx controls
    that move natively, so nothing in Ruby runs on an arrow key and the
    whole interface was silent - the one place on this desktop where
    moving through a list made no sound at all.

    `pan` is Titan's own -1 (left) to 1 (right), which is the spelling
    every part of Titan outside `sound.py` uses; `sound.play_sound` takes
    0 to 1, and handing one straight to the other is what once put the
    shell's sounds in the left speaker.
    """
    try:
        from src.titan_core import sound
    except Exception:
        return False
    try:
        where = None if pan is None else max(0.0, min(1.0,
                                                      (float(pan) + 1.0) / 2.0))
        sound.play_sound(name, pan=where)
        return True
    except Exception:
        return False


def _cue_for(elten_name, pan=None):
    """A cue by the name ELTEN uses for it, through Titan's theme."""
    from . import cues as cues_module
    titan = cues_module.titan_cue(elten_name)
    return _cue(titan, pan) if titan else False


def _spread(index, count):
    """Where in the stereo image a row that far down a list belongs.

    The same idea as Elten's own `lpos` and as Titan's own lists: the
    first row is to the left and the last to the right, so how far
    through a list you are is something you can hear.
    """
    try:
        count = int(count)
        index = int(index)
    except (TypeError, ValueError):
        return 0.0
    if count <= 1 or index < 0:
        return 0.0
    return max(-1.0, min(1.0, (index / float(count - 1)) * 2.0 - 1.0))


def _dress(window, skin=None):
    """Put the skin's colours on a window. Never raises: a skin that cannot
    be read must not stop an application's screen from appearing."""
    skin = skin or _skin()
    if skin is None:
        return window
    try:
        skin.apply_to_window(window)
    except Exception:
        pass
    return window


def _icon_for(key, size=(16, 16), skin=None):
    """One of the skin's pictures, or None."""
    skin = skin or _skin()
    if skin is None or not key:
        return None
    try:
        path = skin.get_icon_path(key)
        if not path:
            return None
        return skin.get_icon(key, size)
    except Exception:
        return None


def _button_icon_key(label):
    lowered = str(label or '').strip().lower()
    if not lowered:
        return ''
    for words, key in BUTTON_ICONS:
        for word in words:
            if word in lowered:
                return key
    return ''


class WxUI(object):
    """Elten's screens for one running application, in one wx window.

    A single top-level frame is reused for every form the application opens
    in turn - which is what Elten's own single screen does - so moving from
    a category list to a station list is a new set of controls in the same
    window, not a new window stacking up behind the last one. Only a
    genuinely modal question (`confirm`, `select_action` used as a menu, an
    `input_text` prompt) gets its own dialog on top.
    """

    def __init__(self, parent, title):
        self.parent = parent
        self.title = title or 'Elten'
        self._frame = None
        self._forms = {}
        self._next_form = 0

    # ----------------------------------------------------------- the frame
    def _ensure_frame(self):
        if self._frame is not None:
            return self._frame
        frame = wx.Frame(self.parent, title=self.title,
                         style=wx.DEFAULT_FRAME_STYLE)
        frame.SetSize((640, 480))
        _dress(frame)
        # The window's own icon, so an Elten application in the task bar
        # looks like the rest of this desktop rather than like nothing.
        bitmap = _icon_for('apps', (32, 32))
        if bitmap is not None:
            try:
                icon = wx.Icon()
                icon.CopyFromBitmap(bitmap)
                frame.SetIcon(icon)
            except Exception:
                pass
        self._frame = frame
        return frame

    def show(self):
        frame = self._ensure_frame()
        frame.Show()
        frame.Raise()
        return frame

    def close(self):
        """Everything this application put on the screen, gone.

        Closing the window must not raise, whatever state it was left in -
        an application's own bug must not become one more crash on top of
        it, at the moment Titan is trying to clean up after it.
        """
        for form_id in list(self._forms):
            try:
                self.close_form(form_id)
            except Exception:
                pass
        if self._frame is not None:
            try:
                self._frame.Destroy()
            except Exception:
                pass
            self._frame = None

    # ------------------------------------------------------- the keyboard
    def open_keyboard(self, application, title=''):
        """A window that owns the keyboard, for an application with no form.

        A game drives a `Runner` and nothing else - Purrposterous holds Left
        and Right to move, Space to feed - and a `Runner` on its own had no
        window at all, so not one key ever reached it. The game ran, ticked,
        and could not be played; which is also why it made no sound, because
        nothing ever happened in it.

        So this is the equivalent of Elten's own screen: a real Titan window
        whose whole job is to have the focus and report keys. It is
        deliberately almost empty - a game is heard, not read - but it is a
        real window with a real accessible name, and the one control in it
        is what the reader lands on and what the keys are typed into.
        """
        frame = self._ensure_frame()
        panel = _clear(frame)
        _dress(panel)
        sizer = wx.BoxSizer(wx.VERTICAL)
        # A read-only field rather than a bare panel: something has to hold
        # the focus for the keyboard to reach the application at all, and a
        # named control is something a reader can announce having entered.
        surface = wx.TextCtrl(panel, value='',
                              style=wx.TE_MULTILINE | wx.TE_READONLY)
        _name(surface, title or self.title)
        sizer.Add(surface, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)
        panel.SetSizer(sizer)
        self._keyboard = surface

        from . import keys as keys_module

        def down(event):
            try:
                names = keys_module.names_for(event.GetKeyCode())
                for name in names:
                    application.key_down(name, repeat=False)
                if not names:
                    event.Skip()
            except Exception as error:
                application._note('bridge', 'a key failed: %s' % error)

        def up(event):
            try:
                for name in keys_module.names_for(event.GetKeyCode()):
                    application.key_up(name)
            except Exception:
                pass
            event.Skip()

        # A game wants the arrows and Tab as GAME keys, so the hook is what
        # takes them - `EVT_KEY_DOWN` never sees Tab, which wx spends on
        # moving the focus.
        surface.Bind(wx.EVT_CHAR_HOOK, down)
        surface.Bind(wx.EVT_KEY_UP, up)

        def gone(_event):
            # The window lost the keyboard: nothing may stay held, or a game
            # walks into a wall for ever because Left never came up.
            application.keys_released()
            _event.Skip()
        surface.Bind(wx.EVT_KILL_FOCUS, gone)

        frame.SetTitle(title or self.title)
        frame.Show()
        frame.Raise()
        surface.SetFocus()
        return True

    def say_on_screen(self, text):
        """Put a line where a sighted person can read it too.

        The applications are self-voicing and everything is already spoken;
        this is the same words, kept in the window, so somebody watching
        over a shoulder is not looking at an empty box.
        """
        surface = getattr(self, '_keyboard', None)
        if surface is None:
            return False
        try:
            surface.AppendText(text + '\n')
            return True
        except Exception:
            return False

    # --------------------------------------------------------------- forms
    def open_form(self, application, specs, cancel_index=None, accept_index=None,
                  header=''):
        """Build one screen out of the controls an application named.

        `specs` is a list of `{"kind": ..., ...}` dicts, one per control, in
        the order the application listed them - which is also the tab
        order, matching a Titan window. Every interaction is reported back
        as an event carrying the form id and the control's INDEX, never a
        name the application invented, so the Ruby side matches replies to
        the field it actually asked about.
        """
        frame = self._ensure_frame()
        panel = _clear(frame)
        skin = _skin()
        _dress(panel, skin)
        sizer = wx.BoxSizer(wx.VERTICAL)
        if header:
            row = wx.BoxSizer(wx.HORIZONTAL)
            bitmap = _icon_for('apps', (16, 16), skin)
            if bitmap is not None:
                row.Add(wx.StaticBitmap(panel, bitmap=bitmap),
                        flag=wx.RIGHT | wx.ALIGN_CENTRE_VERTICAL, border=6)
            label = wx.StaticText(panel, label=header)
            font = label.GetFont()
            font.MakeBold()
            label.SetFont(font)
            row.Add(label, flag=wx.ALIGN_CENTRE_VERTICAL)
            sizer.Add(row, flag=wx.ALL, border=8)

        self._next_form += 1
        form_id = self._next_form
        widgets = []
        for index, spec in enumerate(specs):
            widget = _build_control(panel, spec, self._reporter(
                application, form_id, index), skin)
            widgets.append(widget)
            sizer.Add(widget.window, flag=wx.EXPAND | wx.LEFT | wx.RIGHT
                      | wx.BOTTOM, border=8)

        panel.SetSizer(sizer)
        panel.Layout()
        self._forms[form_id] = _Form(frame, panel, widgets)

        # **The keyboard has to land ON something.** A wx dialog focuses
        # its first control by itself; a frame does not, so a form opened
        # this way left the keyboard on the panel - and every arrow key
        # went to a control that was not there. From the outside that is
        # exactly "down and right do not work": the board was on the
        # screen, correct, named, and could not be moved about at all.
        #
        # The first control that can take it, which is also the first one
        # Tab would reach - so where the keyboard starts and where it
        # goes next agree.
        for widget in widgets:
            if widget.focus():
                break

        def on_key(event):
            """Keys the application asked about, and nothing else.

            Elten turns every key that reaches a focused control into a
            `:key_<name>` event on it, and applications bind a handful:
            Left and Right to open and close a category, Delete to remove a
            row, a letter as a shortcut. The rest belong to the widget - a
            ListBox's own Up and Down, everything typed into an EditBox -
            and are passed straight through, because re-implementing what a
            native control already does correctly is how the keyboard stops
            behaving the way it does in the rest of Titan.
            """
            try:
                key = event.GetKeyCode()
                if key == wx.WXK_ESCAPE:
                    application.send_event('control', form=form_id,
                                           control=None, name='escape')
                    return
                focused = self._focused_index(form_id)
                # The control's own menu, where everybody looks for it:
                # the Applications key, Shift+F10, and Alt for the menu
                # bar. The application is asked to build it, because what
                # is in it is the application's (`bind_context`).
                if key in (wx.WXK_MENU, wx.WXK_WINDOWS_MENU) or \
                        (key == wx.WXK_F10 and event.ShiftDown()):
                    application.send_event('control', form=form_id,
                                           control=focused, name='context')
                    return
                if key == wx.WXK_ALT and not event.ControlDown():
                    application.send_event('control', form=form_id,
                                           control=focused, name='menu')
                    return
                name = _navigation_key(key)
                if name and focused is not None:
                    widget = widgets[focused]
                    # Never steal a key an EditBox is being typed into; only
                    # Left and Right have a meaning there that a text field
                    # does not already own, and even those it does.
                    if widget.kind == 'editbox':
                        event.Skip()
                        return
                    # A ListBox owns its own Up and Down; taking those would
                    # stop it moving at all.
                    if widget.kind == 'listbox' and name in ('key_up',
                                                             'key_down'):
                        event.Skip()
                        return
                    application.send_event('control', form=form_id,
                                           control=focused, name=name,
                                           shift=event.ShiftDown())
                    return
            except Exception as error:
                application._note('bridge', 'a key failed: %s' % error)
            # **A form's keys have to reach a `Runner` as well.** The file
            # manager is a `FilesTree` driven from a Runner - Escape
            # leaves, Enter opens, Ctrl+O opens in the associated
            # program - and a Runner asks `key_pressed?`, which is filled
            # by the key stream and not by a control's own events. A form
            # that only reported control events therefore answered none
            # of those keys: the file manager listed a folder and could
            # not be used.
            #
            # It is reported after the control has had its say, so a
            # ListBox still owns its own Up and Down and a field still
            # gets what is typed into it - and a key nothing is listening
            # for costs one line on the wire.
            try:
                from . import keys as keys_module
                for name in keys_module.names_for(event.GetKeyCode()):
                    application.key_down(name, repeat=False)
            except Exception:
                pass
            event.Skip()

        panel.Bind(wx.EVT_CHAR_HOOK, on_key)

        def on_close(event):
            try:
                application.send_event('control', form=form_id, control=None,
                                       name='escape')
            except Exception:
                pass
            event.Veto()               # Ruby decides whether to really close.

        frame.Bind(wx.EVT_CLOSE, on_close)
        if widgets:
            widgets[0].window.SetFocus()
        frame.Show()
        return form_id

    def close_form(self, form_id):
        form = self._forms.pop(form_id, None)
        if form is None:
            return False
        try:
            form.panel.Destroy()
        except Exception:
            pass
        return True

    def set_control(self, form_id, index, changes):
        """Push a change an application made in Ruby back onto the widget -
        `list.options = [...]`, `box.text = "..."`, an item disabled."""
        form = self._forms.get(form_id)
        if form is None or not (0 <= index < len(form.widgets)):
            return False
        form.widgets[index].apply(changes)
        return True

    def _keep_focus(self):
        """Where the keyboard is now, to put it back afterwards.

        **A modal dialog takes the keyboard and never gives it back.**
        Windows returns it to the FRAME when a dialog closes, not to the
        control inside it - so after any menu, confirmation or page of
        text, the arrows went to a window with nothing in it. From the
        outside that is a board on the screen that will not move and a
        list that will not scroll: "down and right do not work".

        Everything modal here goes through `_modal`, which remembers and
        restores; a control that has since been destroyed falls back to
        the form that is open, and then to the keyboard surface, so there
        is always somewhere for the next key to land.
        """
        try:
            return wx.Window.FindFocus()
        except Exception:
            return None

    def _give_focus_back(self, remembered):
        try:
            if remembered and remembered:
                remembered.SetFocus()
                return True
        except Exception:
            pass
        for form in reversed(list(self._forms.values())):
            for widget in form.widgets:
                try:
                    if widget.focus():
                        return True
                except Exception:
                    continue
        surface = getattr(self, '_keyboard', None)
        try:
            if surface:
                surface.SetFocus()
                return True
        except Exception:
            pass
        return False

    def _modal(self, show):
        """Show something modal and put the keyboard back where it was."""
        remembered = self._keep_focus()
        try:
            return show()
        finally:
            self._give_focus_back(remembered)

    def popup_menu(self, form_id, index, items):
        """The control's own menu, as a real Windows menu.

        This is what Elten's `bind_context` becomes here. The media
        catalogue puts "add to favourites" in one and the file manager
        puts copy, paste, rename and delete in one, and until now they
        were reachable by nothing at all - the block was recorded and
        never called.

        A real `wx.Menu` rather than a list of Titan's own, because a
        menu is a thing Windows itself knows about: a screen reader
        announces it as a menu, says how many items are in it, follows
        the arrows into a submenu and back out, and closes on Escape,
        with none of that written here. It is opened by the Applications
        key, by Shift+F10 and by the right mouse button, which is where
        everybody already looks for it.
        """
        form = self._forms.get(form_id)
        if form is None:
            return None
        chosen = {'at': None}
        menu = wx.Menu()

        def fill(into, entries, path):
            for position, entry in enumerate(entries):
                label = str(entry.get('label') or '')
                children = entry.get('items')
                here = path + [position]
                if children:
                    inner = wx.Menu()
                    fill(inner, children, here)
                    into.AppendSubMenu(inner, label)
                    continue
                if not label:
                    into.AppendSeparator()
                    continue
                item = into.Append(wx.ID_ANY, label)

                def picked(_event, at=tuple(here)):
                    chosen['at'] = list(at)
                into.Bind(wx.EVT_MENU, picked, item)

        fill(menu, items or [], [])
        if menu.GetMenuItemCount() == 0:
            return None
        _cue_for('menu_open')
        remembered = self._keep_focus()
        window = form.panel
        if 0 <= index < len(form.widgets):
            window = form.widgets[index].window or window
        try:
            window.PopupMenu(menu)
        finally:
            menu.Destroy()
            self._give_focus_back(remembered)
            _cue_for('menu_close')
        return chosen['at']

    def focus_control(self, form_id, index):
        form = self._forms.get(form_id)
        if form is None or not (0 <= index < len(form.widgets)):
            return False
        return bool(form.widgets[index].focus())

    def _focused_index(self, form_id):
        form = self._forms.get(form_id)
        if form is None:
            return None
        focused = wx.Window.FindFocus()
        for index, widget in enumerate(form.widgets):
            if widget.owns(focused):
                return index
        return None

    def _reporter(self, application, form_id, index):
        """How a widget tells the application something happened.

        Nothing this returns may raise: it is called from inside a wx event
        handler, where an exception escapes into the event loop and takes
        the window - and with it every other control - down with it.
        """
        def report(name, **fields):
            try:
                application.send_event('control', form=form_id, control=index,
                                       name=name, **fields)
            except Exception as error:
                application._note('bridge', 'reporting %s failed: %s'
                                  % (name, error))
        return report

    # ------------------------------------------------------------ dialogs
    def confirm(self, text, title):
        dialog = wx.MessageDialog(self._ensure_frame(), text, title,
                                  wx.YES_NO | wx.ICON_QUESTION)
        _cue_for('dialog_open')
        try:
            return self._modal(dialog.ShowModal) == wx.ID_YES
        finally:
            dialog.Destroy()
            _cue_for('dialog_close')

    def select(self, rows, header, start):
        """A single-choice list - Elten's `selector`, `select_action`.

        `rows` is `[(key, label), ...]`; the answer is the key of whichever
        row was chosen, or None when the dialog was cancelled.
        """
        labels = [label for _key, label in rows]
        keys = [key for key, _label in rows]
        index = 0
        if start:
            for position, key in enumerate(keys):
                if key == start:
                    index = position
                    break
        dialog = _ChoiceDialog(self._ensure_frame(), header or self.title,
                               labels, index)
        _cue_for('menu_open')
        try:
            if self._modal(dialog.ShowModal) != wx.ID_OK:
                return None
            chosen = dialog.chosen()
            return keys[chosen] if 0 <= chosen < len(keys) else None
        finally:
            dialog.Destroy()
            _cue_for('menu_close')

    def display_text(self, text, header):
        """A page to READ - an application's help, its rules, a changelog.

        A read-only `wx.TextCtrl` and not a message box, deliberately: a
        message box is one unnavigable blob, and what somebody wants from a
        page of rules is their reader's own cursor, arrow keys, say-all and
        Ctrl+C. Escape closes it, which is what `escapable` means.
        """
        dialog = wx.Dialog(self._ensure_frame(), title=header or self.title,
                           style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        dialog.SetSize((640, 480))
        sizer = wx.BoxSizer(wx.VERTICAL)
        field = wx.TextCtrl(dialog, value=text,
                            style=wx.TE_MULTILINE | wx.TE_READONLY
                            | wx.TE_DONTWRAP * 0)
        field.SetName(header or self.title)
        sizer.Add(field, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)
        buttons = dialog.CreateStdDialogButtonSizer(wx.OK)
        if buttons is not None:
            sizer.Add(buttons, flag=wx.EXPAND | wx.ALL, border=8)
        dialog.SetSizer(sizer)
        _dress(dialog)
        field.SetFocus()
        field.SetInsertionPoint(0)
        _cue_for('dialog_open')
        try:
            self._modal(dialog.ShowModal)
        finally:
            dialog.Destroy()
            _cue_for('dialog_close')
        return None

    def input_text(self, prompt, default, multiline, password):
        style = wx.OK | wx.CANCEL
        if multiline:
            style |= wx.TE_MULTILINE
        if password:
            style |= wx.TE_PASSWORD
        dialog = wx.TextEntryDialog(self._ensure_frame(), prompt, self.title,
                                    value=default, style=style)
        try:
            if self._modal(dialog.ShowModal) != wx.ID_OK:
                return None
            return dialog.GetValue()
        finally:
            dialog.Destroy()

    def choose_path(self, header, start, directory, extensions):
        """The platform's own file or folder picker."""
        parent = self._ensure_frame()
        if directory:
            dialog = wx.DirDialog(parent, header or self.title,
                                  defaultPath=start or '')
            getter = 'GetPath'
        else:
            wildcard = 'All files (*.*)|*.*'
            if extensions:
                pattern = ';'.join('*%s' % name if name.startswith('.')
                                   else '*.%s' % name for name in extensions)
                wildcard = '%s|%s|%s' % (header or 'Files', pattern, wildcard)
            dialog = wx.FileDialog(parent, header or self.title,
                                   defaultDir=start or '', wildcard=wildcard)
            getter = 'GetPath'
        try:
            if self._modal(dialog.ShowModal) != wx.ID_OK:
                return None
            return getattr(dialog, getter)()
        finally:
            dialog.Destroy()

    def progress(self, text):
        # A one-line status; a real progress window is a later refinement.
        frame = self._ensure_frame()
        try:
            wx.GetTopLevelParent(frame).SetStatusText(text)
        except Exception:
            pass


class _Form(object):
    __slots__ = ('frame', 'panel', 'widgets')

    def __init__(self, frame, panel, widgets):
        self.frame = frame
        self.panel = panel
        self.widgets = widgets


def _clear(frame):
    """A fresh panel for the next screen, the old one gone.

    Elten replaces its one screen with the next; a Titan window built the
    same way is one frame whose content is swapped, not a tower of panels
    accumulating underneath each other.
    """
    for child in list(frame.GetChildren()):
        child.Destroy()
    return wx.Panel(frame)


#: wx virtual key code -> Elten's own event name, for the keys applications
#: actually bind (`.on(:key_left)`, `:key_delete`, ...). Letters are handled
#: separately since there are twenty-six of them and they are ordinary.
_NAV_KEYS = {
    wx.WXK_LEFT: 'key_left', wx.WXK_RIGHT: 'key_right',
    wx.WXK_UP: 'key_up', wx.WXK_DOWN: 'key_down',
    wx.WXK_DELETE: 'key_delete', wx.WXK_SPACE: 'key_space',
    wx.WXK_HOME: 'key_home', wx.WXK_END: 'key_end',
    wx.WXK_PAGEUP: 'key_pageup', wx.WXK_PAGEDOWN: 'key_pagedown',
}


def _navigation_key(code):
    if code in _NAV_KEYS:
        return _NAV_KEYS[code]
    if 65 <= code <= 90:                              # A-Z
        return 'key_%s' % chr(code).lower()
    return ''


# --------------------------------------------------------------- controls
class _ChoiceDialog(wx.Dialog):
    """Elten's `select_action` / `selector` - the front screen of nearly
    every application.

    It is a dialog of Titan's own rather than `wx.SingleChoiceDialog` for
    one reason that can be heard: the stock dialog's list navigates
    natively and silently, so the control an Elten user is in more than any
    other was the one place on this desktop where moving through a list
    made no sound. This is the same real `wx.ListBox` - so a screen reader
    reads it exactly as before - wearing the user's skin and playing the
    user's own focus, select and end-of-list cues, panned by how far down
    the list the cursor is.
    """

    def __init__(self, parent, header, labels, index=0):
        wx.Dialog.__init__(self, parent, title=header,
                           style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetSize((520, 420))
        skin = _skin()
        _dress(self, skin)
        sizer = wx.BoxSizer(wx.VERTICAL)
        listbox = wx.ListBox(self, choices=labels, style=wx.LB_SINGLE)
        _name(listbox, header)
        if labels:
            listbox.SetSelection(max(0, min(int(index or 0), len(labels) - 1)))
        try:
            if skin is not None:
                skin.apply_to_listbox(listbox)
        except Exception:
            pass
        sizer.Add(listbox, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)
        # **No Ok and no Cancel.** Elten's menus have neither, and they are
        # right not to: this is a menu, so Enter chooses and Escape leaves,
        # and two buttons underneath are two more things for somebody
        # arrowing through the list to tab past on the way to nowhere.
        # They still work as keys - `wx.Dialog` answers Enter and Escape
        # with ID_OK and ID_CANCEL itself - so nothing is lost by not
        # drawing them.
        self.SetSizer(sizer)
        self.listbox = listbox

        def moved(_event):
            _cue_for('listbox_focus',
                     _spread(listbox.GetSelection(), listbox.GetCount()))
        listbox.Bind(wx.EVT_LISTBOX, moved)

        def take(_event):
            _cue_for('listbox_select')
            self.EndModal(wx.ID_OK)
        listbox.Bind(wx.EVT_LISTBOX_DCLICK, take)

        def on_char(event):
            code = event.GetKeyCode()
            if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                take(event)
                return
            if code in (wx.WXK_UP, wx.WXK_NUMPAD_UP) \
                    and listbox.GetSelection() <= 0:
                _cue_for('endoflist', -1.0)
                return
            if code in (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN) \
                    and listbox.GetSelection() >= listbox.GetCount() - 1:
                _cue_for('endoflist', 1.0)
                return
            if code == wx.WXK_ESCAPE:
                self.EndModal(wx.ID_CANCEL)
                return
            event.Skip()
        listbox.Bind(wx.EVT_CHAR_HOOK, on_char)
        listbox.SetFocus()

    def chosen(self):
        return self.listbox.GetSelection()


class _Widget(object):
    """One control on a form: the wx object, and how to change it later."""

    def __init__(self, kind, window):
        self.kind = kind
        self.window = window

    def dress(self, skin=None):
        """Wear the skin the user chose - its colours, and its picture."""
        skin = skin or _skin()
        if skin is None:
            return self
        _dress(self.window, skin)
        for child in self._skinnable():
            _dress(child, skin)
            try:
                if isinstance(child, wx.ListBox):
                    skin.apply_to_listbox(child)
                elif isinstance(child, wx.Button):
                    skin.apply_to_button(child)
            except Exception:
                pass
        self.decorate(skin)
        return self

    def _skinnable(self):
        found = [self.window]
        try:
            found += list(self.window.GetChildren())
        except Exception:
            pass
        return found

    def decorate(self, _skin):
        """A picture for this control, where the skin has a fitting one."""
        return self

    def owns(self, focused):
        return focused is self.window

    def focus(self):
        """Put the keyboard here, and say whether it went.

        An application asks for this constantly - AudioMemory calls
        `grid.focus` after every pick and after every dialog - and a
        `focus` that did nothing left the player nowhere with a board
        still on the screen. Answering honestly matters as much: a form
        looking for somewhere to start uses this, and a control that
        cannot take the keyboard (a label, an unknown kind) must not
        swallow it.
        """
        try:
            if not self.window.AcceptsFocus():
                return False
            self.window.SetFocus()
            return True
        except Exception:
            return False

    def apply(self, changes):
        pass


class _ButtonWidget(_Widget):
    def __init__(self, panel, spec, report):
        button = wx.Button(panel, label=str(spec.get('label') or ''))
        def pressed(_event):
            _cue_for('button_press')
            report('press')
        button.Bind(wx.EVT_BUTTON, pressed)
        _Widget.__init__(self, 'button', button)

    def decorate(self, skin):
        # A button that says "Back" gets the skin's own back arrow. Matched
        # on what it SAYS, in the user's language as well as English, since
        # that is what the label is.
        key = _button_icon_key(self.window.GetLabel())
        bitmap = _icon_for(key, (16, 16), skin) if key else None
        if bitmap is not None:
            try:
                self.window.SetBitmap(bitmap)
            except Exception:
                pass
        return self

    def apply(self, changes):
        if 'label' in changes:
            self.window.SetLabel(str(changes['label'] or ''))
            self.decorate(None)
        if 'enabled' in changes:
            self.window.Enable(bool(changes['enabled']))


class _CheckBoxWidget(_Widget):
    def __init__(self, panel, spec, report):
        box = wx.CheckBox(panel, label=str(spec.get('label') or ''))
        box.SetValue(bool(spec.get('checked')))
        def ticked(event):
            _cue_for('listbox_statechecked' if event.IsChecked()
                     else 'listbox_stateunchecked')
            report('changed', checked=event.IsChecked())
        box.Bind(wx.EVT_CHECKBOX, ticked)
        _Widget.__init__(self, 'checkbox', box)

    def apply(self, changes):
        if 'checked' in changes:
            self.window.SetValue(bool(changes['checked']))
        if 'label' in changes:
            self.window.SetLabel(str(changes['label'] or ''))


class _EditBoxWidget(_Widget):
    def __init__(self, panel, spec, report):
        style = wx.TE_MULTILINE if spec.get('multiline') else 0
        if spec.get('password'):
            style |= wx.TE_PASSWORD
        if spec.get('readonly'):
            style |= wx.TE_READONLY
        header = str(spec.get('header') or '')
        outer = wx.Panel(panel)
        box = wx.BoxSizer(wx.VERTICAL)
        if header:
            label = wx.StaticText(outer, label=header)
            box.Add(label, flag=wx.BOTTOM, border=2)
        field = wx.TextCtrl(outer, value=str(spec.get('text') or ''),
                            style=style)
        _name(field, header)
        limit = spec.get('max_length')
        if isinstance(limit, int) and limit > 0:
            field.SetMaxLength(limit)
        box.Add(field, flag=wx.EXPAND)
        outer.SetSizer(box)
        field.Bind(wx.EVT_TEXT,
                  lambda event: report('changed', text=event.GetString()))
        _Widget.__init__(self, 'editbox', outer)
        self.field = field

    def owns(self, focused):
        return focused is self.field

    def apply(self, changes):
        if 'text' in changes and changes['text'] != self.field.GetValue():
            self.field.ChangeValue(str(changes['text'] or ''))
        if 'enabled' in changes:
            self.field.Enable(bool(changes['enabled']))


class _ListBoxWidget(_Widget):
    def __init__(self, panel, spec, report):
        style = wx.LB_SINGLE
        header = str(spec.get('header') or '')
        outer = wx.Panel(panel)
        box = wx.BoxSizer(wx.VERTICAL)
        label = None
        if header:
            label = wx.StaticText(outer, label=header)
            box.Add(label, flag=wx.BOTTOM, border=2)
        options = [str(item) for item in (spec.get('options') or [])]
        listbox = wx.ListBox(outer, choices=options, style=style)
        _name(listbox, header)
        index = spec.get('index')
        if isinstance(index, int) and 0 <= index < len(options):
            listbox.SetSelection(index)
        elif options:
            listbox.SetSelection(0)
        box.Add(listbox, flag=wx.EXPAND)
        outer.SetSizer(box)
        quiet = bool(spec.get('silent'))

        def moved(event):
            where = listbox.GetSelection()
            if not quiet:
                _cue_for('listbox_focus', _spread(where, listbox.GetCount()))
            report('changed', index=where)

        def chosen(_event):
            if not quiet:
                _cue_for('listbox_select')
            report('select', index=listbox.GetSelection())

        listbox.Bind(wx.EVT_LISTBOX, moved)
        listbox.Bind(wx.EVT_LISTBOX_DCLICK, chosen)

        def on_char(event):
            code = event.GetKeyCode()
            if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                chosen(event)
                return
            # The end of a list is something to HEAR. wx moves nothing and
            # fires no event there, so a list that had run out was
            # indistinguishable from one that had stopped responding.
            if code in (wx.WXK_UP, wx.WXK_NUMPAD_UP) \
                    and listbox.GetSelection() <= 0:
                if not quiet:
                    _cue_for('endoflist', -1.0)
                return
            if code in (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN) \
                    and listbox.GetSelection() >= listbox.GetCount() - 1:
                if not quiet:
                    _cue_for('endoflist', 1.0)
                return
            event.Skip()
        listbox.Bind(wx.EVT_CHAR_HOOK, on_char)

        _Widget.__init__(self, 'listbox', outer)
        self.listbox = listbox
        self.label = label

    def owns(self, focused):
        return focused is self.listbox

    def focus(self):
        self.listbox.SetFocus()
        return True

    def apply(self, changes):
        if 'options' in changes:
            selection = self.listbox.GetSelection()
            self.listbox.Set([str(item) for item in changes['options'] or []])
            if 0 <= selection < self.listbox.GetCount():
                self.listbox.SetSelection(selection)
        if 'index' in changes:
            index = changes['index']
            if isinstance(index, int) and 0 <= index < self.listbox.GetCount():
                self.listbox.SetSelection(index)
                self.listbox.EnsureVisible(index)
        if 'header' in changes:
            # The file tree puts the folder it is showing in its own header,
            # so the name a reader announces follows where the user is.
            header = str(changes['header'] or '')
            if self.label is not None:
                self.label.SetLabel(header)
            _name(self.listbox, header)


class _TableBoxWidget(_Widget):
    """A list with columns - `wx.ListCtrl` in report mode.

    The control Titan uses for the same job everywhere else, and the reason
    it is worth using rather than drawing one: a screen reader announces a
    report-mode list column by column, with the heading, which is exactly
    what a table of "group, forums, threads, posts" is for.
    """

    def __init__(self, panel, spec, report):
        header = str(spec.get('header') or '')
        outer = wx.Panel(panel)
        box = wx.BoxSizer(wx.VERTICAL)
        if header:
            box.Add(wx.StaticText(outer, label=header), flag=wx.BOTTOM,
                    border=2)
        table = wx.ListCtrl(outer, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        _name(table, header)
        self.table = table
        self._columns = [str(name) for name in (spec.get('columns') or [])]
        for position, name in enumerate(self._columns):
            table.InsertColumn(position, name)
        self._fill(spec.get('rows') or [])
        index = spec.get('index')
        if isinstance(index, int) and 0 <= index < table.GetItemCount():
            table.Select(index)
            table.Focus(index)
        box.Add(table, proportion=1, flag=wx.EXPAND)
        outer.SetSizer(box)

        quiet = bool(spec.get('silent'))

        def row_moved(event):
            if not quiet:
                _cue_for('table_marker',
                         _spread(event.GetIndex(), table.GetItemCount()))
            report('changed', index=event.GetIndex())

        def row_chosen(event):
            if not quiet:
                _cue_for('listbox_select')
            report('select', index=event.GetIndex())

        table.Bind(wx.EVT_LIST_ITEM_SELECTED, row_moved)
        table.Bind(wx.EVT_LIST_ITEM_ACTIVATED, row_chosen)
        _Widget.__init__(self, 'tablebox', outer)

    def owns(self, focused):
        return focused is self.table

    def focus(self):
        self.table.SetFocus()
        return True

    def _fill(self, rows):
        self.table.DeleteAllItems()
        if not self._columns and rows:
            # A table whose columns nobody named still has to show its rows.
            for position in range(len(rows[0])):
                self.table.InsertColumn(position, '')
            self._columns = [''] * len(rows[0])
        for row in rows:
            cells = row if isinstance(row, list) else [row]
            position = self.table.InsertItem(self.table.GetItemCount(),
                                             str(cells[0]) if cells else '')
            for column in range(1, min(len(cells), len(self._columns))):
                self.table.SetItem(position, column, str(cells[column]))
        for position in range(len(self._columns)):
            self.table.SetColumnWidth(position, wx.LIST_AUTOSIZE_USEHEADER)

    def apply(self, changes):
        if 'rows' in changes:
            self._fill(changes['rows'] or [])
        if 'index' in changes:
            index = changes['index']
            if isinstance(index, int) and 0 <= index < self.table.GetItemCount():
                self.table.Select(index)
                self.table.Focus(index)


class _FilesTreeWidget(_Widget):
    """Inside a form, a folder is a button saying which one, not a tree."""

    def __init__(self, panel, spec, report):
        self._path = str(spec.get('path') or '')
        label = '%s: %s' % (str(spec.get('header') or 'Folder'),
                            self._path or '...')
        button = wx.Button(panel, label=label)
        def pressed(_event):
            _cue_for('button_press')
            report('press')
        button.Bind(wx.EVT_BUTTON, pressed)
        _Widget.__init__(self, 'filestree', button)

    def apply(self, changes):
        if 'path' in changes:
            self._path = str(changes['path'] or '')
            self.window.SetLabel(self._path or '...')


class _GridBoxWidget(_Widget):
    """A board is a GRID, and a screen reader has to be told so.

    AudioMemory's board was a `wx.ListBox`, which MSAA reports as a list -
    so a reader announced "item 7 of 16" for a square that is row 2,
    column 3. A position on a board is two numbers and losing one of them
    loses the game: a player cannot aim at a square whose column nobody
    said.

    `wx.grid.Grid` is a real table to MSAA and UI Automation - it answers
    with a row, a column and a cell, and the reader says all three - so a
    board is announced the way a board is. The arrow keys are the grid's
    own, which is also how every other table on this desktop moves.
    """

    def __init__(self, panel, spec, report):
        import wx.grid

        header = str(spec.get('header') or '')
        outer = wx.Panel(panel)
        box = wx.BoxSizer(wx.VERTICAL)
        label = None
        if header:
            label = wx.StaticText(outer, label=header)
            box.Add(label, flag=wx.BOTTOM, border=2)

        width = max(1, int(spec.get('width') or 1))
        height = max(1, int(spec.get('height') or 1))
        grid = wx.grid.Grid(outer)
        grid.CreateGrid(height, width)
        grid.EnableEditing(False)
        grid.DisableDragGridSize()
        # Rows and columns are numbered from one, because that is how a
        # person counts squares out loud.
        for column in range(width):
            grid.SetColLabelValue(column, str(column + 1))
        for row in range(height):
            grid.SetRowLabelValue(row, str(row + 1))
        _name(grid, header)
        self.grid = grid
        self.label = label
        self._width = width
        self._height = height
        self._fill(spec.get('cells') or [])
        x = int(spec.get('x') or 0)
        y = int(spec.get('y') or 0)
        if 0 <= y < height and 0 <= x < width:
            grid.SetGridCursor(y, x)
        box.Add(grid, proportion=1, flag=wx.EXPAND)
        outer.SetSizer(box)

        # Elten's own two switches, and a board really uses them:
        # AudioMemory sets `silent` because the game itself makes a sound
        # at every square, and cueing over that would be two sounds for
        # one move.
        self.quiet = bool(spec.get('silent'))
        walls = spec.get('border_sound')
        self.walls = True if walls is None else bool(walls)

        def moved(event):
            if not self.quiet:
                _cue_for('listbox_focus', _spread(event.GetCol(), width))
            report('changed', x=event.GetCol(), y=event.GetRow())
            event.Skip()

        def chosen(event):
            if not self.quiet:
                _cue_for('listbox_select')
            report('select', x=event.GetCol(), y=event.GetRow())

        grid.Bind(wx.grid.EVT_GRID_SELECT_CELL, moved)
        grid.Bind(wx.grid.EVT_GRID_CELL_LEFT_DCLICK, chosen)

        # Enter AND Space, which is what Elten's own grid binds
        # (`reset_action_bindings`: `:enter` and `:space`). A game that
        # tells the player to press Space and answers only to Enter is a
        # game that appears not to respond.
        choose_keys = (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE)
        # Which way each arrow goes, so an edge can be reported as the
        # direction it was walked into.
        arrows = {wx.WXK_LEFT: (-1, 0), wx.WXK_NUMPAD_LEFT: (-1, 0),
                  wx.WXK_RIGHT: (1, 0), wx.WXK_NUMPAD_RIGHT: (1, 0),
                  wx.WXK_UP: (0, -1), wx.WXK_NUMPAD_UP: (0, -1),
                  wx.WXK_DOWN: (0, 1), wx.WXK_NUMPAD_DOWN: (0, 1)}
        towards = {(-1, 0): 'left', (1, 0): 'right',
                   (0, -1): 'up', (0, 1): 'down'}

        def on_char(event):
            code = event.GetKeyCode()
            if code in choose_keys:
                report('select', x=grid.GetGridCursorCol(),
                       y=grid.GetGridCursorRow())
                return
            step = arrows.get(code)
            if step is not None:
                # An arrow that cannot move is not nothing happening: a
                # board tells the player they are against the edge, and
                # AudioMemory plays a sound at the wall it hit. wx moves
                # nothing and fires no event, so the edge has to be
                # noticed here.
                column = grid.GetGridCursorCol()
                row = grid.GetGridCursorRow()
                ahead = (column + step[0], row + step[1])
                if not (0 <= ahead[0] < self._width
                        and 0 <= ahead[1] < self._height):
                    if self.walls and not self.quiet:
                        _cue_for('border', _spread(column, width))
                    report('border', x=column, y=row,
                           direction=towards.get(step, ''),
                           dx=step[0], dy=step[1])
                    return
            event.Skip()
        grid.Bind(wx.EVT_CHAR_HOOK, on_char)

        _Widget.__init__(self, 'gridbox', outer)

    def owns(self, focused):
        try:
            return focused is self.grid or focused is self.grid.GetGridWindow()
        except Exception:
            return focused is self.grid

    def focus(self):
        # The GRID window, not the wrapper: a `wx.grid.Grid` is a panel
        # with a child that does the drawing and the keys, and focusing
        # the wrapper leaves the arrows going nowhere.
        try:
            self.grid.SetFocus()
            self.grid.GetGridWindow().SetFocus()
        except Exception:
            self.grid.SetFocus()
        return True

    def _fill(self, cells):
        for row in range(self._height):
            values = cells[row] if row < len(cells) else []
            for column in range(self._width):
                value = values[column] if column < len(values) else ''
                self.grid.SetCellValue(row, column, str(value or ''))

    def apply(self, changes):
        if 'silent' in changes:
            self.quiet = bool(changes['silent'])
        if 'border_sound' in changes:
            self.walls = bool(changes['border_sound'])
        if 'cells' in changes:
            self._fill(changes['cells'] or [])
        if 'x' in changes or 'y' in changes:
            x = changes.get('x', self.grid.GetGridCursorCol())
            y = changes.get('y', self.grid.GetGridCursorRow())
            try:
                if 0 <= y < self._height and 0 <= x < self._width:
                    self.grid.SetGridCursor(int(y), int(x))
            except Exception:
                pass
        if 'header' in changes:
            header = str(changes['header'] or '')
            if self.label is not None:
                self.label.SetLabel(header)
            _name(self.grid, header)


class _PlayerWidget(_Widget):
    """Elten's `Player` - a radio station or a podcast episode on a form.

    In Elten this is a control you arrow through to seek. Here it is a
    real, named control with real buttons, because that is how everything
    else on this desktop is built: a reader announces "Playing, <station>"
    when the keyboard lands on it, Space plays and pauses, Left and Right
    seek where there is anything to seek through, and the buttons do the
    same for somebody using the mouse.

    The sound itself is Titan's mixer's - see `host.Stream` - so the
    user's theme volume and their output device apply to a radio station
    exactly as to everything else.
    """

    def __init__(self, panel, spec, report):
        outer = wx.Panel(panel)
        box = wx.BoxSizer(wx.VERTICAL)
        label = str(spec.get('label') or '')
        self.state = wx.TextCtrl(outer, value=label,
                                 style=wx.TE_READONLY)
        _name(self.state, label)
        box.Add(self.state, flag=wx.EXPAND | wx.BOTTOM, border=4)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.toggle = wx.Button(outer, label=_t('Play'))
        stop = wx.Button(outer, label=_t('Stop'))
        row.Add(self.toggle, flag=wx.RIGHT, border=4)
        row.Add(stop)
        box.Add(row)
        outer.SetSizer(box)
        self._label = label

        def toggled(_event):
            _cue_for('button_press')
            report('player', do='toggle')

        def stopped(_event):
            _cue_for('button_press')
            report('player', do='stop')

        self.toggle.Bind(wx.EVT_BUTTON, toggled)
        stop.Bind(wx.EVT_BUTTON, stopped)

        # Elten's own keys on a player, and the same amounts.
        moves = {wx.WXK_SPACE: 'toggle',
                 wx.WXK_LEFT: 'back', wx.WXK_NUMPAD_LEFT: 'back',
                 wx.WXK_RIGHT: 'forward', wx.WXK_NUMPAD_RIGHT: 'forward',
                 wx.WXK_UP: 'louder', wx.WXK_NUMPAD_UP: 'louder',
                 wx.WXK_DOWN: 'quieter', wx.WXK_NUMPAD_DOWN: 'quieter',
                 wx.WXK_HOME: 'start', wx.WXK_END: 'end'}

        def on_char(event):
            what = moves.get(event.GetKeyCode())
            if what is not None and not event.ControlDown():
                report('player', do=what)
                return
            event.Skip()
        self.state.Bind(wx.EVT_CHAR_HOOK, on_char)

        _Widget.__init__(self, 'player', outer)

    def owns(self, focused):
        return focused in (self.window, self.state, self.toggle)

    def focus(self):
        self.state.SetFocus()
        return True

    def apply(self, changes):
        if 'label' in changes:
            self._label = str(changes['label'] or '')
        if 'status' in changes:
            words = '%s. %s' % (self._label, str(changes['status'] or ''))
            self.state.ChangeValue(words)
            # The accessible name carries it too: this control changes
            # while the keyboard is sitting on it, and a name that still
            # said "Playing" while it was paused would be a lie the
            # reader repeats.
            _name(self.state, words)
        if 'playing' in changes:
            self.toggle.SetLabel(_t('Pause') if changes['playing']
                                 else _t('Play'))


class _ChoiceListWidget(_Widget):
    """Elten's `ChoiceListBox` - rows whose VALUE you change, not rows you
    pick between.

    MileByMile's "create a game" screen is three of these: card set,
    distance, number of decks. Rendered as a list, a row was a row - the
    value could be read and never changed, so the form could only ever
    start the game it opened with. What it is is a combo box per row,
    which is the control Titan's own settings window uses for exactly
    this: the arrows change the value, Tab moves between them, and a
    screen reader announces the new value itself. Nothing here says
    anything out loud, because the platform already does.
    """

    def __init__(self, panel, spec, report):
        outer = wx.Panel(panel)
        header = str(spec.get('header') or '')
        box = wx.StaticBoxSizer(wx.VERTICAL, outer, header) if header \
            else wx.BoxSizer(wx.VERTICAL)
        parent = box.GetStaticBox() if header else outer
        rows = spec.get('rows') or []
        self.choices = []
        for number, row in enumerate(rows):
            options = [str(item) for item in (row.get('options') or [])]
            # A row with no choices is a plain line of text, not a combo
            # box with nothing in it.
            if not options:
                box.Add(wx.StaticText(parent, label=str(row.get('label') or '')),
                        flag=wx.ALL, border=4)
                self.choices.append(None)
                continue
            # The row's own label, or - when a row has none, which is how
            # a one-row list is written - the header. A combo box with no
            # name is a control a reader can only call "combo box".
            name = str(row.get('label') or '') or header
            line = wx.BoxSizer(wx.HORIZONTAL)
            if name:
                line.Add(wx.StaticText(parent, label=name),
                         flag=wx.RIGHT | wx.ALIGN_CENTRE_VERTICAL, border=6)
            choice = wx.Choice(parent, choices=options)
            _name(choice, name)
            index = int(row.get('index') or 0)
            choice.SetSelection(max(0, min(index, len(options) - 1)))
            line.Add(choice, proportion=1)
            box.Add(line, flag=wx.EXPAND | wx.ALL, border=4)
            self.choices.append(choice)

            def picked(_event, at=number, control=choice):
                _cue_for('listbox_focus')
                report('changed', row=at, choice=control.GetSelection(),
                       index=at)
            choice.Bind(wx.EVT_CHOICE, picked)

        outer.SetSizer(box)
        _Widget.__init__(self, 'choicelist', outer)

    def owns(self, focused):
        return focused is self.window or focused in self.choices

    def focus(self):
        for choice in self.choices:
            if choice is not None:
                choice.SetFocus()
                return True
        return _Widget.focus(self)

    def apply(self, changes):
        rows = changes.get('rows')
        if not rows:
            return
        for choice, row in zip(self.choices, rows):
            if choice is None:
                continue
            options = [str(item) for item in (row.get('options') or [])]
            if options and list(choice.GetStrings()) != options:
                choice.Set(options)
            index = int(row.get('index') or 0)
            if options:
                choice.SetSelection(max(0, min(index, len(options) - 1)))


_BUILDERS = {
    'choicelist': _ChoiceListWidget,
    'player': _PlayerWidget,
    'button': _ButtonWidget,
    'checkbox': _CheckBoxWidget,
    'editbox': _EditBoxWidget,
    'listbox': _ListBoxWidget,
    'tablebox': _TableBoxWidget,
    'filestree': _FilesTreeWidget,
    'gridbox': _GridBoxWidget,
}


def _build_control(panel, spec, report, skin=None):
    kind = str(spec.get('kind') or '')
    builder = _BUILDERS.get(kind)
    if builder is None:
        # An unrecognised control is a real control, not nothing: the label
        # says what it should have been, so an application built against a
        # kind this build does not have yet fails visibly instead of being
        # one silently missing row.
        text = wx.StaticText(panel, label='[%s: %s]'
                             % (kind or 'control',
                                spec.get('label') or spec.get('header') or ''))
        return _Widget(kind or 'unknown', _dress(text, skin))
    widget = builder(panel, spec, report)
    widget.dress(skin)
    return widget

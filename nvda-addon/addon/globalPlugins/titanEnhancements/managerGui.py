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

from . import compat
from . import i18n
from . import icons
from . import labels
from . import markers
from . import monitors
from . import perProgram
from . import procedures
from . import schemes

_ = i18n.install(globals())


def _text(value):
    return str(value or '').strip()


def _modules_described():
    try:
        from . import readerModules
        return readerModules.describe() or []
    except Exception:                                # noqa: BLE001
        return []


def _facts_about(program):
    """Every line the reader can honestly say about one program.

    A fact that could not be worked out is ABSENT rather than guessed at
    - the whole value of this page is that each line can be trusted.
    """
    lines = []
    module = None
    for row in _modules_described():
        if _text(row.get('id')).lower() == program:
            module = row
            break
    if module:
        # Translators: a line about a program in the manager. {label} is
        # the module's name and {source} where it came from.
        lines.append(_('Reader module: {label} ({source})').format(
            label=_text(module.get('label')) or _text(module.get('id')),
            source=_text(module.get('source')) or '?'))
        # Translators: a line about a program's reader module: how many
        # rules of each kind it has.
        lines.append(_('  {lists} list, {regions} region, {controls} '
                       'control, {live} live rule(s)').format(
            lists=module.get('lists', 0), regions=module.get('regions', 0),
            controls=module.get('controls', 0), live=module.get('live', 0)))
    else:
        # Translators: a line about a program with no reader module.
        lines.append(_('Reader module: none'))
    try:
        named = labels.for_application(program)
        described = sum(1 for row in named.values()
                        if isinstance(row, dict) and row.get('description'))
        # Translators: a line about a program in the manager.
        lines.append(_('Named controls: {named}, of which described: '
                       '{described}').format(named=len(named),
                                             described=described))
        icon = labels.application_note(program, 'window_icon')
        if icon:
            # Translators: a line about a program: what its icon was read as.
            lines.append(_('Its icon: {what}').format(what=icon))
    except Exception:                                # noqa: BLE001
        pass
    try:
        mine = [row for row in procedures.all_procedures()
                if _text(row.get('program')).lower() == program]
        # Translators: a line about a program in the manager.
        lines.append(_('Recorded scripts: {count}').format(count=len(mine)))
    except Exception:                                # noqa: BLE001
        pass
    try:
        answers = perProgram.answers_for(program)
        if answers:
            # Translators: a line about a program: the switches it answers
            # for itself rather than taking the general setting.
            lines.append(_('Its own answers: {what}').format(
                what=', '.join('%s=%s' % (name, 'on' if value else 'off')
                               for name, value in sorted(answers.items()))))
    except Exception:                                # noqa: BLE001
        pass
    return lines


def _warn_if_titan_must_play(where):
    """A file NVDA cannot play itself is played by Titan's mixer.

    The user asked for exactly this warning: choosing an `.ogg` when TCE is
    not running would otherwise be a choice that seems to do nothing. Said
    once, at the moment of choosing, with the file still chosen - it will
    sound as soon as TCE is running.
    """
    import os
    if os.path.splitext(str(where or ''))[1].lower() in icons.NVDA_PLAYS:
        return False
    try:
        from .link import LINK
        connected = LINK.connected()
    except Exception:                                # noqa: BLE001
        connected = False
    if connected:
        return False
    try:
        import wx
        import gui
        gui.messageBox(
            # Translators: shown when a sound file NVDA cannot play itself
            # is chosen while Titan is not running.
            _('A file of this kind is played by Titan\'s own mixer, so it '
              'needs the TCE environment running. TCE is not running now: '
              'the file is kept, and will sound once TCE is started.'),
            # Translators: the title of that warning.
            _('This sound needs TCE'), wx.OK | wx.ICON_WARNING)
    except Exception:                                # noqa: BLE001
        pass
    return True


def _sound_wildcard():
    """The file chooser's filter: wave files NVDA plays itself and the
    formats Titan's mixer decodes - `.ogg` above all, which is what every
    sound in Titan's themes is."""
    # Translators: the kinds of file offered when choosing a sound.
    return '%s (*.wav;*.ogg;*.mp3;*.flac)|*.wav;*.ogg;*.mp3;*.flac' % _(
        'Sound files')


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
            # **A page that will not build is ONE page.** Every tab was
            # built straight into `__init__`, so anything that raised in
            # any of them took the whole manager down - and because the
            # dialog is put up from a `wx.CallAfter`, the traceback went
            # to NVDA's log and the user got no window and no sentence at
            # all. Measured for real: one missing helper in the labels
            # page and all six tabs were unreachable.
            for page in (self._programs_page, self._markers_page,
                         self._monitors_page, self._procedures_page,
                         self._labels_page, self._scheme_page,
                         self._icons_page):
                self._build_page(page)
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

        def _build_page(self, build_it):
            """One page, and its failure is its own.

            The page is named in the log with what went wrong, because a
            tab that is quietly absent is the failure this add-on keeps
            taking back out.
            """
            try:
                build_it()
            except Exception as error:               # noqa: BLE001
                name = getattr(build_it, '__name__', 'a page')
                if compat.log is not None:
                    try:
                        compat.log.error(
                            'Titan manager: %s could not be built: %s: %s'
                            % (name, type(error).__name__, error))
                    except Exception:                # noqa: BLE001
                        pass

        # --------------------------------------------------------- programs
        def _programs_page(self):
            """Everything the reader knows about one program, in one place.

            **No screen reader has this**, and the reason is that no
            screen reader has the pieces: what the program is WRITTEN IN,
            whether a module claims it and whether that module actually
            fires, how many of its controls have been named, what has
            been recorded in it, and which switches it answers for
            itself. Each of those already had a home; a person asking
            "why does this program read badly" had to visit five of them.
            """
            import wx
            from gui import guiHelper
            page = wx.Panel(self.book)
            # Translators: a page of the manager window.
            self.book.AddPage(page, _('Programs'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: the list of programs the reader knows something
            # about.
            self.programs = helper.addLabeledControl(
                _('P&rograms'), wx.ListBox, style=wx.LB_SINGLE)
            self.programs.Bind(wx.EVT_LISTBOX, self._program_shown)
            # Translators: what is known about the chosen program.
            self.program_facts = helper.addLabeledControl(
                _('&What is known'), wx.TextCtrl,
                style=wx.TE_MULTILINE | wx.TE_READONLY)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the manager window.
            forget = buttons.addButton(page, label=_('Forget e&verything'))
            forget.Bind(wx.EVT_BUTTON, self._forget_program)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._fill_programs_page()

        def _known_programs(self):
            """Every program anything is known about, from every store."""
            found = set()
            for where in (lambda: labels.everything().keys(),
                          lambda: perProgram.all_programs(),
                          lambda: [_text(row.get('program'))
                                   for row in procedures.all_procedures()],
                          lambda: [_text(row.get('id'))
                                   for row in _modules_described()]):
                try:
                    found.update(_text(one).lower() for one in where() if one)
                except Exception:                    # noqa: BLE001
                    continue
            return sorted(one for one in found if one)

        def _fill_programs_page(self, at=0):
            self._program_rows = self._known_programs()
            self.programs.Set(self._program_rows)
            if self._program_rows:
                self.programs.SetSelection(
                    max(0, min(at, len(self._program_rows) - 1)))
            self._program_shown()

        def _chosen_program(self):
            at = self.programs.GetSelection()
            return self._program_rows[at] \
                if 0 <= at < len(self._program_rows) else ''

        def _program_shown(self, _event=None):
            program = self._chosen_program()
            if not program:
                self.program_facts.SetValue('')
                return
            self.program_facts.SetValue('\n'.join(_facts_about(program)))

        def _forget_program(self, _event):
            """Take away everything the reader has learned about it.

            Asked first, because it is the one button here that throws
            something away and there is no undo: the names somebody typed
            go with it.
            """
            import wx
            program = self._chosen_program()
            if not program:
                return
            answer = wx.MessageBox(
                # Translators: asked before forgetting what is known about
                # a program. {program} is its name.
                _('Forget every name, description and answer for {program}? '
                  'This cannot be undone.').format(program=program),
                # Translators: the title of that question.
                _('Forget everything?'), wx.YES_NO | wx.ICON_QUESTION, self)
            if answer != wx.YES:
                return
            at = self.programs.GetSelection()
            try:
                for key in list(labels.for_application(program)):
                    labels.remove_key(program, key)
            except Exception:                        # noqa: BLE001
                pass
            try:
                for name in list(perProgram.answers_for(program)):
                    perProgram.clear(name, program)
            except Exception:                        # noqa: BLE001
                pass
            self._fill_programs_page(at=at)
            # Translators: said when everything known about a program is
            # thrown away.
            self._said(_('Forgotten'))

        # ------------------------------------------------------- procedures
        def _procedures_page(self):
            """The recorded procedures, all of them, across every program.

            **A chooser is not a manager**, and until now a procedure had
            only a chooser: the command lists the ones belonging to the
            program in front and runs the chosen one. Everything else a
            person wants after a few months - what have I recorded, what
            was that one called, read it back, throw that one away - had
            nowhere to happen, and a recording nobody can find again is a
            recording nobody makes a second time.
            """
            import wx
            from gui import guiHelper
            page = wx.Panel(self.book)
            # Translators: a page of the manager window.
            self.book.AddPage(page, _('Scripts'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: the list of recorded procedures.
            self.procedures = helper.addLabeledControl(
                _('&Scripts'), wx.ListBox, style=wx.LB_SINGLE)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the manager window.
            run = buttons.addButton(page, label=_('&Run'))
            run.Bind(wx.EVT_BUTTON, self._run_procedure)
            # Translators: a button in the manager window - read the steps.
            steps = buttons.addButton(page, label=_('&Steps'))
            steps.Bind(wx.EVT_BUTTON, self._read_procedure)
            # Translators: a button in the manager window.
            rename = buttons.addButton(page, label=_('Re&name...'))
            rename.Bind(wx.EVT_BUTTON, self._rename_procedure)
            # Translators: a button in the manager window.
            forget = buttons.addButton(page, label=_('&Forget'))
            forget.Bind(wx.EVT_BUTTON, self._forget_procedure)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._fill_procedures()

        def _fill_procedures(self, at=0):
            self._procedure_rows = list(procedures.all_procedures() or [])
            self.procedures.Set([
                '%s%s (%d)' % (row.get('name') or '',
                               (' - ' + row['program']) if row.get('program')
                               else '',
                               len(row.get('steps') or []))
                for row in self._procedure_rows])
            if self._procedure_rows:
                self.procedures.SetSelection(
                    max(0, min(at, len(self._procedure_rows) - 1)))

        def _chosen_procedure(self):
            at = self.procedures.GetSelection()
            return self._procedure_rows[at] \
                if 0 <= at < len(self._procedure_rows) else None

        def _run_procedure(self, _event):
            """Run it - with this window out of the way first.

            A procedure acts on the controls of the program it was
            recorded in, and this dialog is in front of that program: run
            from here it would look for them behind itself. So the manager
            closes and the procedure starts after it has gone.
            """
            row = self._chosen_procedure()
            if row is None:
                return
            self.EndModal(0) if self.IsModal() else self.Hide()

            def go():
                _ok, said = procedures.run(row, say=self._say_outside)
                self._say_outside(said)
            # NVDA's own timer, reached the way `focus` reaches it -
            # `compat` does not carry `core`, and a bare `wx.CallLater`
            # would run this on a dialog that is on its way out.
            try:
                import core
                core.callLater(400, go)
            except Exception:                        # noqa: BLE001
                go()

        def _read_procedure(self, _event):
            row = self._chosen_procedure()
            if row is None:
                return
            from . import dialogs
            # Translators: the title of the window showing a script's steps.
            dialogs.browse(procedures.as_text(row), _('The steps'))

        def _rename_procedure(self, _event):
            import wx
            row = self._chosen_procedure()
            if row is None:
                return
            # Translators: asked when renaming a recorded script.
            dialog = wx.TextEntryDialog(self, _('What should it be called?'),
                                        # Translators: the title of that box.
                                        _('Rename'),
                                        value=row.get('name') or '')
            try:
                if dialog.ShowModal() == wx.ID_OK:
                    procedures.rename(row, dialog.GetValue())
                    self._fill_procedures(at=self.procedures.GetSelection())
            finally:
                dialog.Destroy()

        def _forget_procedure(self, _event):
            row = self._chosen_procedure()
            if row is None:
                return
            at = self.procedures.GetSelection()
            procedures.remove(row)
            self._fill_procedures(at=at)
            # Translators: said when a recorded script is forgotten.
            self._said(_('Script forgotten'))

        # ----------------------------------------------------------- labels
        def _labels_page(self):
            """Every control that has been given a name, per program.

            JAWS has had this for thirty years and calls it a custom
            label; what is here besides is the DESCRIPTION - what a
            picture, an icon or a chart was read as - which is a request
            paid for once and worth being able to see, correct and throw
            away like anything else the user has accumulated.
            """
            import wx
            from gui import guiHelper
            page = wx.Panel(self.book)
            # Translators: a page of the manager window.
            self.book.AddPage(page, _('Control names'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: the list of programs that have named controls.
            self.label_programs = helper.addLabeledControl(
                _('&Program'), wx.Choice, choices=[])
            self.label_programs.Bind(wx.EVT_CHOICE, self._program_chosen)
            # Translators: the list of named controls of that program.
            self.labels = helper.addLabeledControl(
                _('&Controls'), wx.ListBox, style=wx.LB_SINGLE)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the manager window.
            rename = buttons.addButton(page, label=_('Re&name...'))
            rename.Bind(wx.EVT_BUTTON, self._rename_label)
            # Translators: a button in the manager window - everything
            # else that can be decided about a control.
            more = buttons.addButton(page, label=_('&Everything else...'))
            more.Bind(wx.EVT_BUTTON, self._customise_label)
            # Translators: a button in the manager window - read the stored
            # description of a picture.
            describe = buttons.addButton(page, label=_('&Description'))
            describe.Bind(wx.EVT_BUTTON, self._read_description)
            # Translators: a button in the manager window.
            forget = buttons.addButton(page, label=_('&Forget'))
            forget.Bind(wx.EVT_BUTTON, self._forget_label)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._fill_programs()

        def _fill_programs(self, at=0):
            store = labels.everything()
            self._label_programs = sorted(store)
            self.label_programs.Set(self._label_programs)
            if self._label_programs:
                self.label_programs.SetSelection(
                    max(0, min(at, len(self._label_programs) - 1)))
            self._fill_labels()

        def _program_chosen(self, _event):
            self._fill_labels()

        def _current_program(self):
            at = self.label_programs.GetSelection()
            return self._label_programs[at] \
                if 0 <= at < len(self._label_programs) else ''

        def _fill_labels(self, at=0):
            program = self._current_program()
            rows = labels.for_application(program) if program else {}
            self._label_rows = sorted(rows.items())
            said = []
            for key, row in self._label_rows:
                if isinstance(row, dict):
                    name = str(row.get('label') or '')
                    source = str(row.get('source') or '')
                    extra = str(row.get('description') or '')
                else:
                    name, source, extra = str(row), '', ''
                # A control with only a description has no name to show, so
                # the key stands in - it is what the control IS to Windows.
                shown = name or key
                if source:
                    shown = '%s [%s]' % (shown, source)
                if extra:
                    # Translators: marks a control whose picture has been
                    # read and remembered.
                    shown = '%s - %s' % (shown, _('described'))
                said.append(shown)
            self.labels.Set(said)
            if self._label_rows:
                self.labels.SetSelection(
                    max(0, min(at, len(self._label_rows) - 1)))

        def _chosen_label(self):
            at = self.labels.GetSelection()
            return self._label_rows[at] \
                if 0 <= at < len(self._label_rows) else (None, None)

        def _rename_label(self, _event):
            import wx
            key, row = self._chosen_label()
            if key is None:
                return
            current = row.get('label', '') if isinstance(row, dict) \
                else str(row or '')
            # Translators: asked when renaming a control.
            dialog = wx.TextEntryDialog(self, _('What should it be called?'),
                                        # Translators: the title of that box.
                                        _('Rename'), value=current)
            try:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                labels.rename_key(self._current_program(), key,
                                  dialog.GetValue())
                self._fill_labels(at=self.labels.GetSelection())
            finally:
                dialog.Destroy()

        def _customise_label(self, _event):
            """The rest of what may be decided about the chosen control.

            The same fields the command offers on the control the user is
            standing on - said, added, the voice, and never announcing it
            - for a control in another program that may not even be
            running. Editing here is by KEY, because there is no object.
            """
            import wx
            key, row = self._chosen_label()
            if key is None:
                return
            if not isinstance(row, dict):
                row = {}
            program = self._current_program()
            fields = [
                # Translators: a field: the word to say instead of the
                # control type.
                ('role_word', _('Say it is a'), row.get('role_word', '')),
                # Translators: a field: something to say after the control.
                ('note', _('And add'), row.get('note', '')),
            ]
            for name, label, value in fields:
                dialog = wx.TextEntryDialog(self, label,
                                            # Translators: the title.
                                            _('This control'), value=value)
                try:
                    if dialog.ShowModal() != wx.ID_OK:
                        return
                    labels.set_field(program, key, name, dialog.GetValue())
                finally:
                    dialog.Destroy()
            answer = wx.MessageBox(
                # Translators: asked in the manager about one control.
                _('Never announce this control?'),
                # Translators: the title of that question.
                _('This control'), wx.YES_NO | wx.ICON_QUESTION, self)
            labels.set_field(program, key, 'silent', answer == wx.YES)
            self._fill_labels(at=self.labels.GetSelection())
            # Translators: said when what was decided about a control is
            # kept.
            self._said(_('Kept'))

        def _read_description(self, _event):
            key, row = self._chosen_label()
            if key is None:
                return
            text = row.get('description', '') if isinstance(row, dict) else ''
            if not text:
                # Translators: said about a control whose picture has never
                # been read.
                self._said(_('That one has no description'))
                return
            from . import dialogs
            # Translators: the title of the window showing what a picture
            # was read as.
            dialogs.browse(text, _('What this shows'))

        def _forget_label(self, _event):
            key, _row = self._chosen_label()
            if key is None:
                return
            at = self.labels.GetSelection()
            labels.remove_key(self._current_program(), key)
            self._fill_labels(at=at)
            # Translators: said when a control's stored name is forgotten.
            self._said(_('Forgotten'))

        def _say_outside(self, text):
            """Say something once this window is no longer in front."""
            try:
                from . import compat
                if compat.ui is not None and str(text or '').strip():
                    compat.ui.message(str(text))
            except Exception:                        # noqa: BLE001
                pass

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
            # **Where the sound comes from.** The built-in one, Titan's
            # own for the same event, or a file of the user's - the same
            # three answers the sound scheme has, so a user learns one
            # rule. A real `wx.Choice`, so a reader announces the answer
            # itself.
            self._icon_sources = list(icons.SOURCES)
            names = icons.source_names()
            # Translators: where an auditory icon's sound comes from.
            self.icon_source = helper.addLabeledControl(
                _('The sound comes from'), wx.Choice,
                choices=[names[source] for source in self._icon_sources])
            self.icon_source.Bind(wx.EVT_CHOICE, self._icon_source_chosen)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the manager window.
            hear = buttons.addButton(page, label=_('&Hear it'))
            hear.Bind(wx.EVT_BUTTON, self._hear_icon)
            # Translators: a button in the manager window - pick a sound
            # file of the user's own for this icon.
            choose = buttons.addButton(page, label=_('Choose a &file...'))
            choose.Bind(wx.EVT_BUTTON, self._icon_file)
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
            if row.get('source') == icons.SOURCE_EXTERNAL and row.get(
                    'external'):
                said = '%s (%s)' % (said, row['external'])
            self.icon_meaning.SetValue(said)
            try:
                self.icon_source.SetSelection(
                    self._icon_sources.index(row.get('source')))
            except (ValueError, AttributeError):
                pass

        def _icon_source_chosen(self, _event):
            row = self._chosen_icon()
            if row is None:
                return
            index = self.icon_source.GetSelection()
            if not 0 <= index < len(self._icon_sources):
                return
            source = self._icon_sources[index]
            if source == icons.SOURCE_EXTERNAL and not row.get('external'):
                self._icon_file(None)
                return
            icons.set_source(row['id'], source, row.get('external', ''))
            self._fill_icons(at=self.icons.GetSelection())

        def _icon_file(self, _event):
            """A wave file of the user's own, for this icon."""
            import wx
            row = self._chosen_icon()
            if row is None:
                return
            with wx.FileDialog(
                    self,
                    # Translators: the title of the file chooser for a sound.
                    _('Choose a sound file'),
                    wildcard=_sound_wildcard(),
                    style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as chooser:
                if chooser.ShowModal() != wx.ID_OK:
                    self._fill_icons(at=self.icons.GetSelection())
                    return
                where = chooser.GetPath()
            icons.set_source(row['id'], icons.SOURCE_EXTERNAL, where)
            self._fill_icons(at=self.icons.GetSelection())
            _warn_if_titan_must_play(where)

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
            self._sources = list(schemes.SOURCES)
            names = schemes.source_names()
            # Translators: where a state's sound comes from.
            self.source = helper.addLabeledControl(
                _('The sound comes from'), wx.Choice,
                choices=[names[source] for source in self._sources])
            self.source.Bind(wx.EVT_CHOICE, self._source_chosen)
            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the manager window.
            hear = buttons.addButton(page, label=_('&Hear it'))
            hear.Bind(wx.EVT_BUTTON, self._hear_state)
            # Translators: a button in the manager window - pick a sound
            # file of the user's own for this state.
            choose = buttons.addButton(page, label=_('Choose a &file...'))
            choose.Bind(wx.EVT_BUTTON, self._state_file)
            # Translators: a button in the manager window.
            back = buttons.addButton(page, label=_('Put them all &back'))
            back.Bind(wx.EVT_BUTTON, self._reset_scheme)
            helper.addItem(buttons)
            page.Sizer = helper.sizer
            self._fill_states()

        def _fill_states(self, at=0):
            self._state_rows = schemes.described()
            words = schemes.way_names()
            sources = schemes.source_names()
            self.states.Set(['%s - %s, %s' % (row['label'],
                                              words.get(row['way'], ''),
                                              sources.get(row['source'], ''))
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
            try:
                self.source.SetSelection(
                    self._sources.index(row.get('source')))
            except (ValueError, AttributeError):
                pass

        def _source_chosen(self, _event):
            row = self._chosen_state()
            if row is None:
                return
            index = self.source.GetSelection()
            if not 0 <= index < len(self._sources):
                return
            source = self._sources[index]
            if source == schemes.SOURCE_EXTERNAL and not row.get('external'):
                self._state_file(None)
                return
            schemes.set_source(row['state'], source, row.get('external', ''))
            self._fill_states(at=self.states.GetSelection())

        def _state_file(self, _event):
            import wx
            row = self._chosen_state()
            if row is None:
                return
            with wx.FileDialog(
                    self, _('Choose a sound file'),
                    wildcard=_sound_wildcard(),
                    style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as chooser:
                if chooser.ShowModal() != wx.ID_OK:
                    self._fill_states(at=self.states.GetSelection())
                    return
                where = chooser.GetPath()
            schemes.set_source(row['state'], schemes.SOURCE_EXTERNAL, where)
            self._fill_states(at=self.states.GetSelection())
            _warn_if_titan_must_play(where)

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
            # **Nothing catches what raises inside a `CallAfter`.** It runs
            # later, in wx's own loop, long after `show()` has answered -
            # so a manager that could not be built answered True, said
            # nothing, and simply did not appear. Whatever happens here
            # the user is told something.
            try:
                dialog = manager(parent)
                dialog.Show()
            except Exception as error:               # noqa: BLE001
                if compat.log is not None:
                    try:
                        compat.log.error('Titan manager: %s: %s'
                                         % (type(error).__name__, error))
                    except Exception:                # noqa: BLE001
                        pass
                try:
                    from . import dialogs
                    # Translators: said when the manager window will not open.
                    dialogs.report(_('The manager could not be opened. If '
                                     'the add-on was just updated, restart '
                                     'NVDA rather than reloading plugins.'))
                except Exception:                    # noqa: BLE001
                    pass
        wx.CallAfter(open_it)
        return True
    except Exception:                                # noqa: BLE001
        return False

# -*- coding: utf-8 -*-
"""Settings -> Polyglot: the languages, and adding one.

The page edits the user's ``runtimes.json`` and nothing else, so what it
shows is what Polyglot really runs with and the file can still be edited by
hand. A built-in language can be changed (its interpreter's path, a
command) and put back; one of the user's own can be removed. Nothing is
written until Titan's settings are saved, like every other category.

Commands are shown as one line - ``{exe} --std {file}`` - and kept as the
list of arguments ``runtimes.py`` runs, a part with a space in it written in
double quotes.
"""

import os
import re
import subprocess

from . import runtimes
from .i18n import _

CATEGORY = 'Polyglot'
_ID = re.compile(r'^[a-z0-9][a-z0-9_.+-]*$')


# ----------------------------------------------------------- the text forms
def split_command(text):
    """``{exe} "a b" {file}`` -> ``['{exe}', 'a b', '{file}']``.

    Double quotes group, and nothing else is special: a Windows path's
    backslashes are kept as they are, which ``shlex`` would not do.
    """
    parts, current, quoted, started = [], [], False, False
    for char in str(text or ''):
        if char == '"':
            quoted = not quoted
            started = True
        elif char.isspace() and not quoted:
            if started:
                parts.append(''.join(current))
            current, started = [], False
        else:
            current.append(char)
            started = True
    if started:
        parts.append(''.join(current))
    return parts


def join_command(parts):
    out = []
    for part in parts or []:
        part = str(part)
        out.append('"%s"' % part if (not part or any(c.isspace() for c in part))
                   else part)
    return ' '.join(out)


def split_extensions(text):
    found = []
    for word in re.split(r'[\s,;]+', str(text or '')):
        word = word.strip().lower()
        if not word:
            continue
        word = word if word.startswith('.') else '.' + word
        if word not in found:
            found.append(word)
    return found


def split_lines(text):
    return [line.strip() for line in str(text or '').splitlines()
            if line.strip()]


def split_env(text):
    """``KEY=VALUE`` per line. Answers (the dict, the lines it refused)."""
    env, refused = {}, []
    for line in split_lines(text):
        key, sep, value = line.partition('=')
        if not sep or not key.strip():
            refused.append(line)
            continue
        env[key.strip()] = value.strip()
    return env, refused


def join_env(env):
    return '\n'.join('%s=%s' % (k, v) for k, v in (env or {}).items())


# -------------------------------------------------------------- the model
class Languages(object):
    """The page's working copy of the user's table."""

    def __init__(self, entries=None):
        self.entries = [dict(e) for e in (entries if entries is not None
                                          else runtimes.read_user_entries())]
        self.builtin = {r.id: r for r in runtimes.builtin()}
        self.changed = False

    def table(self):
        return runtimes.runtimes_from(self.entries, include_disabled=True)

    def find(self, runtime_id):
        for runtime in self.table():
            if runtime.id == runtime_id:
                return runtime
        return None

    def _index(self, runtime_id):
        for index, entry in enumerate(self.entries):
            if str(entry.get('id')) == runtime_id:
                return index
        return -1

    def is_builtin(self, runtime_id):
        return runtime_id in self.builtin

    def problems(self, entry, adding):
        """What is wrong with an entry, in sentences; empty when it is fine."""
        out = []
        runtime_id = str(entry.get('id') or '')
        if not _ID.match(runtime_id):
            out.append(_("The identifier must be lower-case letters, digits "
                         "and - _ . + only, for example: kotlin."))
        elif adding and self.find(runtime_id) is not None:
            out.append(_("There is already a language called {}.").format(
                runtime_id))
        if not entry.get('extensions'):
            out.append(_("Give at least one file extension, for example: "
                         ".kt"))
        if not entry.get('command') and not entry.get('compile') and not (
                self.is_builtin(runtime_id)
                and self.builtin[runtime_id].inprocess):
            out.append(_("Give the command that runs a program, or the "
                         "command that compiles it."))
        return out

    def shared_extensions(self, entry):
        """Extensions ``entry`` shares with another language that is on."""
        mine = set(entry.get('extensions') or [])
        out = []
        for runtime in self.table():
            if runtime.id == entry.get('id') or runtime.disabled:
                continue
            for ext in runtime.extensions:
                if ext in mine:
                    out.append('%s (%s)' % (ext, runtime.name))
        return out

    def put(self, entry):
        """Store a full entry: a built-in one only as what it changes."""
        runtime_id = str(entry['id'])
        if self.is_builtin(runtime_id):
            entry = runtimes.difference(self.builtin[runtime_id], entry)
        index = self._index(runtime_id)
        if self.is_builtin(runtime_id) and entry == {'id': runtime_id}:
            if index >= 0:
                del self.entries[index]
        elif index >= 0:
            self.entries[index] = entry
        else:
            self.entries.append(entry)
        self.changed = True

    def remove(self, runtime_id):
        """Remove one of the user's languages, or put a built-in one back."""
        index = self._index(runtime_id)
        if index >= 0:
            del self.entries[index]
            self.changed = True
            return True
        return False

    def set_disabled(self, runtime_id, disabled):
        runtime = self.find(runtime_id)
        if runtime is None:
            return
        entry = runtimes.entry_of(runtime)
        entry['disabled'] = bool(disabled)
        self.put(entry)

    def save(self):
        if self.changed:
            runtimes.write_user_entries(self.entries)
            self.changed = False


def check(runtime):
    """One sentence: is the program there, and what does it say it is."""
    if runtime.inprocess:
        return _("{} is built into Polyglot and needs nothing.").format(
            runtime.name)
    exe = runtime.executable()
    if not exe:
        names = ', '.join(runtime.find) or _("nothing")
        return _("{}: no interpreter or compiler was found. Looked for: "
                 "{}.").format(runtime.name, names)
    version = ''
    for flag in ('--version', '-version', '-v', '/?'):
        try:
            kwargs = {}
            if runtimes.IS_WINDOWS:
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            done = subprocess.run([exe, flag], capture_output=True, timeout=8,
                                  stdin=subprocess.DEVNULL, **kwargs)
        except Exception:
            continue
        text = (done.stdout + done.stderr).decode('utf-8', 'replace')
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines and done.returncode == 0:
            version = lines[0][:160]
            break
        if lines and not version:
            version = lines[0][:160]
    if version:
        return _("{}: found {}. It says: {}").format(runtime.name, exe,
                                                      version)
    return _("{}: found {}.").format(runtime.name, exe)


# ------------------------------------------------------------------ the UI
def _name_for_readers(control, name):
    """Name a native control for MSAA as well as for wx: `SetName` alone
    never reaches a screen reader for a list view or an edit box."""
    try:
        from src.shell import a11y
        a11y.name_control(control, name)
    except Exception:
        control.SetName(name)


def _state_word(runtime):
    if runtime.disabled:
        return _("switched off")
    return _("ready") if runtime.available() else _("not found")


def _source_word(runtime):
    return {'builtin': _("built in"), 'changed': _("built in, changed"),
            'user': _("added by you")}.get(runtime.source, runtime.source)


def row_label(runtime):
    """One row of the list: what a reader says for the language.

    Whether the language is switched on is the row's TICK, which every
    screen reader reads from the platform; it is deliberately not in the
    words, so ticking a row does not rename it (a settings interface finds
    a row by its words, and a row that renamed itself as it was ticked
    could never be found again).
    """
    state = _("ready") if runtime.available() else _("not found")
    return _("{name} ({files}): {state}").format(
        name=runtime.name, files=' '.join(runtime.extensions) or '-',
        state=state)


def details(runtime):
    """Everything about one language, as lines to read."""
    if runtime is None:
        return _("No language is selected.")
    lines = [_("Language: {}").format(runtime.name),
             _("Identifier: {}").format(runtime.id),
             _("Files: {}").format(' '.join(runtime.extensions) or '-'),
             _("State: {}").format(_state_word(runtime)),
             _("Source: {}").format(_source_word(runtime))]
    if runtime.inprocess:
        lines.append(_("Interpreter: built into Polyglot"))
    else:
        lines.append(_("Interpreter: {}").format(
            runtime.executable() or _("not found")))
        if runtime.command:
            lines.append(_("Run command: {}").format(
                join_command(runtime.command)))
        if runtime.compile:
            lines.append(_("Compile command: {}").format(
                join_command(runtime.compile)))
    if runtime.note:
        # A built-in language's note is in the catalogue; one the user
        # wrote is not, and comes back as written.
        lines.append(_("Note: {}").format(_(runtime.note)))
    return '\n'.join(lines)


def _group(parent, title):
    """A `wx.StaticBox` group: a reader says which group it entered."""
    import wx
    sizer = wx.StaticBoxSizer(wx.VERTICAL, parent, title)
    return sizer, sizer.GetStaticBox()


class LanguageDialog(object):
    """Adding a language, or changing one: every field of a runtime."""

    def __init__(self, parent, languages, runtime=None):
        import wx
        from . import tce_ui
        self.wx = wx
        self.languages = languages
        self.adding = runtime is None
        title = _("Add a language") if self.adding else \
            _("Change {}").format(runtime.name)
        self.dialog = wx.Dialog(parent, title=title,
                                style=wx.DEFAULT_DIALOG_STYLE |
                                wx.RESIZE_BORDER, size=(680, 720))
        dialog = self.dialog
        entry = runtimes.entry_of(runtime) if runtime else {
            'id': '', 'name': '', 'extensions': [], 'find': [],
            'command': ['{exe}', '{file}'], 'compile': [],
            'output': '{name}' + runtimes.EXE, 'env': {}, 'sdk': True,
            'note': '', 'disabled': False}
        panel = wx.ScrolledWindow(dialog)
        panel.SetScrollRate(0, 10)

        def section(title):
            sizer, box = _group(panel, title)
            grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
            grid.AddGrowableCol(1, 1)
            sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 4)
            return sizer, box, grid

        def field(where, label, value, multiline=False, name=None):
            box, grid = where
            # The label is made FIRST, and in the same parent as its box.
            # Windows names an edit box after the static text just before
            # it in creation order, and a mnemonic (&Name) jumps to the
            # control after its label - made after its box, a label named
            # every field with the PREVIOUS row's label.
            text = wx.StaticText(box, label=label)
            style = wx.TE_MULTILINE if multiline else 0
            control = wx.TextCtrl(box, value=value, style=style,
                                  size=(-1, 70 if multiline else -1))
            _name_for_readers(control,
                              name or label.replace('&', '').rstrip(':'))
            grid.Add(text, 0, wx.ALIGN_TOP | wx.TOP, 4)
            grid.Add(control, 1, wx.EXPAND)
            return control

        about, about_box, about_grid = section(_("The language"))
        here = (about_box, about_grid)
        self.ident = field(here, _("&Identifier:"), entry['id'])
        if not self.adding:
            self.ident.SetEditable(False)
        self.name = field(here, _("&Name:"), entry['name'])
        self.extensions = field(here, _("File &extensions:"),
                                ' '.join(entry['extensions']))
        # No&te, not N&ote: Alt+O is "Compiled &output file".
        self.note = field(here, _("No&te:"), entry['note'], name=_("Note"))
        self.disabled = wx.CheckBox(about_box, label=_("S&witched off"))
        self.disabled.SetValue(bool(entry['disabled']))
        about.Add(self.disabled, 0, wx.ALL, 4)

        running, run_box, run_grid = section(_("Running it"))
        here = (run_box, run_grid)
        self.find = field(here, _("Interpreter or com&piler (one path or "
                                  "program name per line, the first found "
                                  "is used):"),
                          '\n'.join(entry['find']), multiline=True,
                          name=_("Interpreter or compiler"))
        browse = wx.Button(run_box, label=_("&Browse for the program..."))
        run_grid.Add((0, 0))
        run_grid.Add(browse, 0)
        self.command = field(here, _("&Run command:"),
                             join_command(entry['command']))
        self.compile = field(here, _("&Compile command (empty if the "
                                     "language is not compiled):"),
                             join_command(entry['compile']),
                             name=_("Compile command"))
        self.output = field(here, _("Compiled &output file:"),
                            entry['output'])
        self.env = field(here, _("En&vironment variables (NAME=value, one "
                                 "per line):"), join_env(entry['env']),
                         multiline=True, name=_("Environment variables"))
        self.sdk = wx.CheckBox(run_box, label=_(
            "Put Titan's &SDK folder on the language's search paths"))
        self.sdk.SetValue(bool(entry['sdk']))
        running.Add(self.sdk, 0, wx.ALL, 4)
        help_label = wx.StaticText(run_box,
                                   label=_("How a command is written:"))
        help_text = wx.TextCtrl(run_box, value=_(
            "In a command: {exe} is the interpreter or compiler found above, "
            "{file} the program's file, {dir} its folder, {name} the file's "
            "name without its extension, {out} the file the compile command "
            "made, {sdk} Polyglot's SDK folder, {python} Titan's own Python. "
            "A part with a space in it goes in double quotes. A compiled "
            "language usually runs with the command {out}."),
            style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 90))
        _name_for_readers(help_text, _("How a command is written"))
        running.Add(help_label, 0, wx.LEFT | wx.TOP, 4)
        running.Add(help_text, 0, wx.EXPAND | wx.ALL, 4)

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(about, 0, wx.EXPAND | wx.ALL, 8)
        box.Add(running, 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(box)

        # wx's stock buttons are labelled in wx's language, not Titan's:
        # a Polish Titan's dialog said "Cancel".
        buttons = wx.StdDialogButtonSizer()
        buttons.AddButton(wx.Button(dialog, wx.ID_OK, "OK"))
        buttons.AddButton(wx.Button(dialog, wx.ID_CANCEL, _("Cancel")))
        buttons.Realize()
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        dialog.SetSizer(outer)
        browse.Bind(wx.EVT_BUTTON, self._on_browse)
        dialog.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        tce_ui.cue_tree(dialog)
        (self.ident if self.adding else self.name).SetFocus()
        self.result = None

    def _on_browse(self, _event):
        from . import tce_ui
        wx = self.wx
        wildcard = _("Programs") + " (*.exe;*.bat;*.cmd)|*.exe;*.bat;*.cmd|" \
            if runtimes.IS_WINDOWS else ''
        with wx.FileDialog(self.dialog, _("Choose the interpreter or "
                                          "compiler"),
                           wildcard=wildcard + _("All files") + " (*.*)|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as chooser:
            if tce_ui.modal(chooser) != wx.ID_OK:
                return
            path = chooser.GetPath()
        lines = split_lines(self.find.GetValue())
        if path in lines:
            lines.remove(path)
        self.find.SetValue('\n'.join([path] + lines))
        self.find.SetFocus()

    def entry(self):
        env, refused = split_env(self.env.GetValue())
        return {'id': self.ident.GetValue().strip().lower(),
                'name': self.name.GetValue().strip(),
                'extensions': split_extensions(self.extensions.GetValue()),
                'find': split_lines(self.find.GetValue()),
                'command': split_command(self.command.GetValue()),
                'compile': split_command(self.compile.GetValue()),
                'output': self.output.GetValue().strip(),
                'env': env, 'sdk': self.sdk.GetValue(),
                'note': self.note.GetValue().strip(),
                'disabled': self.disabled.GetValue()}, refused

    def _on_ok(self, event):
        from . import tce_ui
        entry, refused = self.entry()
        problems = self.languages.problems(entry, self.adding)
        if refused:
            problems.append(_("These lines are not NAME=value: {}").format(
                '; '.join(refused)))
        if problems:
            tce_ui.message(self.dialog, '\n'.join(problems),
                           self.dialog.GetTitle(), 'warning')
            return
        shared = self.languages.shared_extensions(entry)
        if shared and not tce_ui.ask(
                self.dialog,
                _("These extensions also belong to another language: {}. A "
                  "language you added is used for them first. Keep them?")
                .format(', '.join(shared)), self.dialog.GetTitle()):
            return
        if not entry['name']:
            entry['name'] = entry['id']
        self.result = entry
        event.Skip()

    def show(self):
        from . import tce_ui
        try:
            if tce_ui.modal(self.dialog) == self.wx.ID_OK:
                return self.result
            return None
        finally:
            self.dialog.Destroy()


def build(parent):
    """The category's panel. ``panel.languages`` is its working copy.

    The languages are a list of real check boxes (Titan's `CheckList`, the
    control Titan's own settings use for every list of things to switch on
    and off): a ticked language is switched on. That is also what makes the
    category usable from every settings interface - a report list of
    columns is not a control `ui_model` can describe, so the HTML page,
    the console and the walked settings showed Polyglot as a row of buttons
    acting on a list nobody could reach. What the columns said is now the
    read-only details under the list, which every interface reads as text.
    """
    import wx
    from src.ui.check_list import CheckList
    from . import tce_ui
    panel = wx.Panel(parent)
    panel.languages = Languages()
    panel.ids = []
    intro = wx.StaticText(panel, label=_(
        "The languages add-ons may be written in. A ticked language is "
        "switched on. Add one by giving its interpreter or compiler, or "
        "change where a built-in language finds its own. Changes are "
        "written when the settings are saved."))
    intro.Wrap(560)

    group, box = _group(panel, _("Languages"))
    # Made before the list, which Windows names after the static text in
    # front of it.
    label = wx.StaticText(box, label=_("&Languages:"))
    listing = CheckList(box, name=_("Languages"))
    listing.SetMinSize((-1, 220))
    panel.listing = listing
    # Which language the buttons below act on. In Titan's own window it
    # follows the list; to a settings interface (the HTML page, the console,
    # the walked settings) it is the only way to pick a row - `ui_model`
    # describes the tick list as values, not as a cursor, so without it
    # Change, Check and Remove acted on whichever row happened to be first.
    target_label = wx.StaticText(box, label=_("Language the &buttons act on:"))
    target = wx.Choice(box)
    _name_for_readers(target, _("Language the buttons act on"))
    panel.target = target
    details_label = wx.StaticText(box, label=_("&Details:"))
    details_box = wx.TextCtrl(box, style=wx.TE_MULTILINE | wx.TE_READONLY,
                              size=(-1, 120))
    _name_for_readers(details_box, _("Details"))
    panel.details = details_box

    add = wx.Button(box, label=_("&Add a language..."))
    edit = wx.Button(box, label=_("C&hange..."))
    remove = wx.Button(box, label=_("&Remove"))
    test = wx.Button(box, label=_("Chec&k"))
    open_file = wx.Button(box, label=_("Open the languages &file"))

    def selected():
        index = listing.GetFirstSelected()
        if index < 0 or index >= len(panel.ids):
            return None
        return panel.languages.find(panel.ids[index])

    def refill(keep=None):
        table = panel.languages.table()
        panel.ids = [runtime.id for runtime in table]
        listing.Set([row_label(runtime) for runtime in table])
        target.Set([runtime.name for runtime in table])
        for row, runtime in enumerate(table):
            listing.Check(row, not runtime.disabled)
        if panel.ids:
            row = panel.ids.index(keep) if keep in panel.ids else 0
            # Quietly: Titan putting the cursor back is not the user moving.
            listing._last_focused = row
            listing.Select(row)
            listing.Focus(row)
        buttons_follow()

    def buttons_follow(_event=None):
        if _event is not None:
            _event.Skip()
        runtime = selected()
        index = listing.GetFirstSelected()
        if 0 <= index < target.GetCount() and target.GetSelection() != index:
            target.SetSelection(index)
        details_box.SetValue(details(runtime))
        edit.Enable(runtime is not None)
        test.Enable(runtime is not None)
        if runtime is None:
            remove.Enable(False)
            return
        if runtime.source == 'user':
            remove.SetLabel(_("&Remove"))
            remove.Enable(True)
        else:
            remove.SetLabel(_("&Restore default"))
            remove.Enable(runtime.source == 'changed')
        panel.Layout()

    def on_target(event):
        event.Skip()
        index = target.GetSelection()
        if 0 <= index < listing.GetItemCount():
            # Quietly: the cursor is moved for the user, not by them.
            listing._last_focused = index
            listing.Select(index)
            listing.Focus(index)
            listing.EnsureVisible(index)
            buttons_follow()

    def on_ticked(event):
        index = event.GetInt()
        if 0 <= index < len(panel.ids):
            panel.languages.set_disabled(panel.ids[index],
                                         not listing.IsChecked(index))
            # The row keeps its words (a tick is not in them); only the
            # details change, and the Restore button with them.
            buttons_follow()

    def on_add(_event):
        entry = LanguageDialog(panel, panel.languages).show()
        if entry:
            panel.languages.put(entry)
            refill(entry['id'])
        listing.SetFocus()

    def on_edit(_event=None):
        runtime = selected()
        if runtime is None:
            return
        entry = LanguageDialog(panel, panel.languages, runtime).show()
        if entry:
            panel.languages.put(entry)
            refill(runtime.id)
        listing.SetFocus()

    def on_remove(_event):
        runtime = selected()
        if runtime is None:
            return
        if runtime.source == 'user':
            question = _("Remove {}?").format(runtime.name)
        else:
            question = _("Put {} back the way Polyglot ships it?").format(
                runtime.name)
        if not tce_ui.ask(panel, question, CATEGORY):
            return
        panel.languages.remove(runtime.id)
        refill(runtime.id)
        listing.SetFocus()

    def on_test(_event):
        runtime = selected()
        if runtime is None:
            return
        wx.BeginBusyCursor()
        try:
            text = check(runtime)
        finally:
            wx.EndBusyCursor()
        # Also under the details, where a settings interface that pressed
        # the button reads it - the message box is on Titan's screen.
        details_box.SetValue(details(runtime) + chr(10) + text)
        tce_ui.message(panel, text, CATEGORY,
                       'information' if runtime.available() else 'warning')
        listing.SetFocus()

    def on_open_file(_event):
        panel.languages.save()
        path = ensure_user_table()
        try:
            if runtimes.IS_WINDOWS:
                os.startfile(path)
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as error:
            tce_ui.message(panel, str(error), CATEGORY, 'error')

    def on_key(event):
        code = event.GetKeyCode()
        if code == wx.WXK_DELETE and remove.IsEnabled():
            on_remove(event)
        elif code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            on_edit()
        else:
            event.Skip()

    add.Bind(wx.EVT_BUTTON, on_add)
    edit.Bind(wx.EVT_BUTTON, on_edit)
    remove.Bind(wx.EVT_BUTTON, on_remove)
    test.Bind(wx.EVT_BUTTON, on_test)
    open_file.Bind(wx.EVT_BUTTON, on_open_file)
    listing.Bind(wx.EVT_LIST_ITEM_SELECTED, buttons_follow)
    listing.Bind(wx.EVT_CHECKLISTBOX, on_ticked)
    target.Bind(wx.EVT_CHOICE, on_target)
    listing.Bind(wx.EVT_LIST_ITEM_ACTIVATED, on_edit)
    # CheckList plays its own checked/unchecked earcon as the row moves;
    # Titan's list sounds add the end of the list, and Enter/Delete.
    tce_ui.cue_list(listing, plays_own_focus=True)
    listing.Bind(wx.EVT_CHAR_HOOK, on_key)

    group.Add(label, 0, wx.LEFT | wx.TOP, 4)
    group.Add(listing, 1, wx.EXPAND | wx.ALL, 4)
    group.Add(target_label, 0, wx.LEFT | wx.TOP, 4)
    group.Add(target, 0, wx.ALL, 4)
    group.Add(details_label, 0, wx.LEFT | wx.TOP, 4)
    group.Add(details_box, 0, wx.EXPAND | wx.ALL, 4)
    row_of_buttons = wx.WrapSizer(wx.HORIZONTAL)
    for button in (add, edit, remove, test, open_file):
        row_of_buttons.Add(button, 0, wx.ALL, 4)
    group.Add(row_of_buttons, 0, wx.ALL, 0)
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(intro, 0, wx.ALL, 8)
    sizer.Add(group, 1, wx.EXPAND | wx.ALL, 8)
    panel.SetSizer(sizer)
    tce_ui.cue_tree(panel, skip=(listing,))
    panel.refill = refill
    refill()
    return panel


def load(panel):
    """Read the file again: the panel shows what is on the disk."""
    panel.languages = Languages()
    panel.refill()


def save(panel):
    panel.languages.save()


def register(component_manager):
    component_manager.register_settings_category(CATEGORY, build, save, load)


def ensure_user_table():
    """The user's languages file, written with a commented example."""
    path = runtimes.user_table_path()
    if not os.path.isfile(path):
        import json
        os.makedirs(os.path.dirname(path), exist_ok=True)
        sample = {
            '_comment': "Settings -> Polyglot edits this file. An entry with "
                        "the id of a built-in language changes only what it "
                        "names. Placeholders: {file} {dir} {name} {out} {exe} "
                        "{sdk} {python}. 'find' lists paths or names looked "
                        "for on PATH.",
            'runtimes': []}
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(sample, handle, indent=2, ensure_ascii=False)
    return path


def open_page(parent=None):
    """Titan's settings window, at the Polyglot category."""
    try:
        from src.settings import interfaces
        window = interfaces.settings_frame(parent)
        if window is None:
            return None
        interfaces.ensure_component_categories(window, parent)
        if CATEGORY in getattr(window, 'categories', {}):
            names = [window.category_list.GetString(i)
                     for i in range(window.category_list.GetCount())]
            for index, name in enumerate(names):
                if name.strip() == CATEGORY:
                    window.category_list.SetSelection(index)
                    break
            window.ShowCategory(CATEGORY)
        window.Show()
        window.Raise()
        return window
    except Exception as error:
        print('[polyglot] could not open the settings: %s' % error)
        return None

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


class LanguageDialog(object):
    """Adding a language, or changing one: every field of a runtime."""

    def __init__(self, parent, languages, runtime=None):
        import wx
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
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1, 1)

        def field(label, value, multiline=False, name=None):
            # The label is made FIRST. Windows names an edit box after the
            # static text just before it in creation order, and a mnemonic
            # (&Name) jumps to the control after its label - so a label made
            # after its box named every field with the PREVIOUS row's label
            # (the first with none) and sent every Alt+letter one field too
            # far. That is what "the settings are not labelled" was.
            text = wx.StaticText(panel, label=label)
            style = wx.TE_MULTILINE if multiline else 0
            control = wx.TextCtrl(panel, value=value, style=style,
                                  size=(-1, 70 if multiline else -1))
            _name_for_readers(control,
                              name or label.replace('&', '').rstrip(':'))
            grid.Add(text, 0, wx.ALIGN_TOP | wx.TOP, 4)
            grid.Add(control, 1, wx.EXPAND)
            return control

        self.ident = field(_("&Identifier:"), entry['id'])
        if not self.adding:
            self.ident.SetEditable(False)
        self.name = field(_("&Name:"), entry['name'])
        self.extensions = field(_("File &extensions:"),
                                ' '.join(entry['extensions']))
        self.find = field(_("Interpreter or com&piler (one path or program "
                            "name per line, the first found is used):"),
                          '\n'.join(entry['find']), multiline=True,
                          name=_("Interpreter or compiler"))
        browse = wx.Button(panel, label=_("&Browse for the program..."))
        grid.Add((0, 0))
        grid.Add(browse, 0)
        self.command = field(_("&Run command:"),
                             join_command(entry['command']))
        self.compile = field(_("&Compile command (empty if the language is "
                               "not compiled):"),
                             join_command(entry['compile']),
                             name=_("Compile command"))
        self.output = field(_("Compiled &output file:"), entry['output'])
        self.env = field(_("En&vironment variables (NAME=value, one per "
                           "line):"), join_env(entry['env']), multiline=True,
                         name=_("Environment variables"))
        # No&te, not N&ote: Alt+O is "Compiled &output file".
        self.note = field(_("No&te:"), entry['note'], name=_("Note"))
        self.sdk = wx.CheckBox(panel, label=_(
            "Put Titan's &SDK folder on the language's search paths"))
        self.sdk.SetValue(bool(entry['sdk']))
        self.disabled = wx.CheckBox(panel, label=_("S&witched off"))
        self.disabled.SetValue(bool(entry['disabled']))
        help_label = wx.StaticText(panel, label=_("How a command is written:"))
        help_text = wx.TextCtrl(panel, value=_(
            "In a command: {exe} is the interpreter or compiler found above, "
            "{file} the program's file, {dir} its folder, {name} the file's "
            "name without its extension, {out} the file the compile command "
            "made, {sdk} Polyglot's SDK folder, {python} Titan's own Python. "
            "A part with a space in it goes in double quotes. A compiled "
            "language usually runs with the command {out}."),
            style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 90))
        _name_for_readers(help_text, _("How a command is written"))

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
        box.Add(self.sdk, 0, wx.LEFT | wx.TOP, 8)
        box.Add(self.disabled, 0, wx.LEFT | wx.TOP, 8)
        box.Add(help_label, 0, wx.LEFT | wx.TOP, 8)
        box.Add(help_text, 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(box)

        buttons = dialog.CreateButtonSizer(wx.OK | wx.CANCEL)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        dialog.SetSizer(outer)
        browse.Bind(wx.EVT_BUTTON, self._on_browse)
        dialog.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        (self.ident if self.adding else self.name).SetFocus()
        self.result = None

    def _on_browse(self, _event):
        wx = self.wx
        wildcard = _("Programs") + " (*.exe;*.bat;*.cmd)|*.exe;*.bat;*.cmd|" \
            if runtimes.IS_WINDOWS else ''
        with wx.FileDialog(self.dialog, _("Choose the interpreter or "
                                          "compiler"),
                           wildcard=wildcard + _("All files") + " (*.*)|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as chooser:
            if chooser.ShowModal() != wx.ID_OK:
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
        wx = self.wx
        entry, refused = self.entry()
        problems = self.languages.problems(entry, self.adding)
        if refused:
            problems.append(_("These lines are not NAME=value: {}").format(
                '; '.join(refused)))
        if problems:
            wx.MessageBox('\n'.join(problems), self.dialog.GetTitle(),
                          wx.OK | wx.ICON_WARNING, self.dialog)
            return
        shared = self.languages.shared_extensions(entry)
        if shared:
            answer = wx.MessageBox(
                _("These extensions also belong to another language: {}. A "
                  "language you added is used for them first. Keep them?")
                .format(', '.join(shared)), self.dialog.GetTitle(),
                wx.YES_NO | wx.ICON_QUESTION, self.dialog)
            if answer != wx.YES:
                return
        if not entry['name']:
            entry['name'] = entry['id']
        self.result = entry
        event.Skip()

    def show(self):
        try:
            if self.dialog.ShowModal() == self.wx.ID_OK:
                return self.result
            return None
        finally:
            self.dialog.Destroy()


def build(parent):
    """The category's panel. ``panel.languages`` is its working copy."""
    import wx
    panel = wx.Panel(parent)
    panel.languages = Languages()
    intro = wx.StaticText(panel, label=_(
        "The languages add-ons may be written in. Add one by giving its "
        "interpreter or compiler, or change where a built-in language finds "
        "its own. Changes are written when the settings are saved."))
    intro.Wrap(560)
    # Made before the list, which Windows names after the static text in
    # front of it - made after, the list was named with the introduction.
    label = wx.StaticText(panel, label=_("&Languages:"))
    listing = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
                          size=(-1, 260))
    _name_for_readers(listing, _("Languages"))
    for index, (title, width) in enumerate((
            (_("Language"), 170), (_("Files"), 110), (_("State"), 100),
            (_("Source"), 130), (_("Interpreter"), 260))):
        listing.InsertColumn(index, title, width=width)
    panel.listing = listing

    add = wx.Button(panel, label=_("&Add a language..."))
    edit = wx.Button(panel, label=_("C&hange..."))
    remove = wx.Button(panel, label=_("&Remove"))
    toggle = wx.Button(panel, label=_("Switch o&ff"))
    test = wx.Button(panel, label=_("Chec&k"))
    open_file = wx.Button(panel, label=_("Open the languages &file"))

    def selected():
        index = listing.GetFirstSelected()
        if index < 0:
            return None
        return panel.languages.find(panel.ids[index])

    def refill(keep=None):
        listing.DeleteAllItems()
        panel.ids = []
        for row, runtime in enumerate(panel.languages.table()):
            panel.ids.append(runtime.id)
            listing.InsertItem(row, runtime.name)
            listing.SetItem(row, 1, ' '.join(runtime.extensions))
            listing.SetItem(row, 2, _state_word(runtime))
            listing.SetItem(row, 3, _source_word(runtime))
            listing.SetItem(row, 4, _("built in") if runtime.inprocess
                            else (runtime.executable() or '-'))
        if panel.ids:
            row = panel.ids.index(keep) if keep in panel.ids else 0
            listing.Select(row)
            listing.Focus(row)
        buttons_follow()

    def buttons_follow(_event=None):
        runtime = selected()
        edit.Enable(runtime is not None)
        toggle.Enable(runtime is not None)
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
        toggle.SetLabel(_("Switch o&n") if runtime.disabled
                        else _("Switch o&ff"))
        panel.Layout()

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
        if wx.MessageBox(question, CATEGORY, wx.YES_NO | wx.ICON_QUESTION,
                         panel) != wx.YES:
            return
        panel.languages.remove(runtime.id)
        refill(runtime.id)
        listing.SetFocus()

    def on_toggle(_event):
        runtime = selected()
        if runtime is None:
            return
        panel.languages.set_disabled(runtime.id, not runtime.disabled)
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
        wx.MessageBox(text, CATEGORY, wx.OK | wx.ICON_INFORMATION, panel)
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
            wx.MessageBox(str(error), CATEGORY, wx.OK | wx.ICON_ERROR, panel)

    def on_key(event):
        if event.GetKeyCode() == wx.WXK_DELETE and remove.IsEnabled():
            on_remove(event)
        elif event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            on_edit()
        else:
            event.Skip()

    add.Bind(wx.EVT_BUTTON, on_add)
    edit.Bind(wx.EVT_BUTTON, on_edit)
    remove.Bind(wx.EVT_BUTTON, on_remove)
    toggle.Bind(wx.EVT_BUTTON, on_toggle)
    test.Bind(wx.EVT_BUTTON, on_test)
    open_file.Bind(wx.EVT_BUTTON, on_open_file)
    listing.Bind(wx.EVT_LIST_ITEM_SELECTED, buttons_follow)
    listing.Bind(wx.EVT_LIST_ITEM_ACTIVATED, on_edit)
    listing.Bind(wx.EVT_KEY_DOWN, on_key)

    row_of_buttons = wx.WrapSizer(wx.HORIZONTAL)
    for button in (add, edit, remove, toggle, test, open_file):
        row_of_buttons.Add(button, 0, wx.ALL, 4)
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(intro, 0, wx.ALL, 8)
    sizer.Add(label, 0, wx.LEFT | wx.TOP, 8)
    sizer.Add(listing, 1, wx.EXPAND | wx.ALL, 8)
    sizer.Add(row_of_buttons, 0, wx.ALL, 4)
    panel.SetSizer(sizer)
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

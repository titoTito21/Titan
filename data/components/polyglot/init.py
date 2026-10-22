# -*- coding: utf-8 -*-
"""Polyglot - Titan applications, games and components in other languages.

An application, a game or a component no longer has to be Python: its
``openfile`` (or its ``init.<ext>``) may be Lua, Ruby, JavaScript, C#,
PowerShell, Go, C... - whatever a runtime in ``polyglotkit/runtimes.py`` or
the user's own ``runtimes.json`` answers. Lua is interpreted by this
component itself; every other language needs its interpreter or compiler on
the machine, and says so in a sentence when it is missing.

Nothing in Titan is changed: the component reaches Titan's application and
game managers from outside (`polyglotkit/hooks.py`), so it works in a Titan
built before it existed and can be installed from Titan-Net.
"""

import os
import shutil
import sys

COMPONENT_DIR = os.path.dirname(os.path.abspath(__file__))
if COMPONENT_DIR not in sys.path:
    sys.path.insert(0, COMPONENT_DIR)

from polyglotkit import hooks, runtimes, components   # noqa: E402
from polyglotkit.i18n import _                        # noqa: E402

EXAMPLES_DIR = os.path.join(COMPONENT_DIR, 'examples')
_KINDS = {'applications': 'applications', 'games': 'games',
          'components': 'components'}

# The managers are reached the moment the component is loaded, so a program
# in another language can be opened from the very first menu Titan builds.
try:
    hooks.install()
except Exception as _error:                                  # noqa: N816
    print('[polyglot] could not reach the managers: %s' % _error)


# ---------------------------------------------------------------- the window
def _languages_text():
    lines = []
    for item in [r.describe() for r in runtimes.all_runtimes()]:
        state = _("ready") if item['available'] else _("not found")
        lines.append("%s (%s): %s" % (item['name'], ', '.join(item['extensions']),
                                      state))
    return lines


def show_window(parent=None):
    import wx

    dialog = wx.Dialog(parent, title=_("Programming languages"),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                       size=(720, 460))
    intro = wx.StaticText(dialog, label=_(
        "Applications, games and components may be written in these "
        "languages. Lua needs nothing; the others need their interpreter or "
        "compiler on this computer."))
    listing = wx.ListCtrl(dialog, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
    listing.SetName(_("Languages"))
    for index, title in enumerate((_("Language"), _("Files"), _("State"),
                                   _("Interpreter"))):
        listing.InsertColumn(index, title, width=(180, 120, 110, 280)[index])
    for row, item in enumerate(r.describe() for r in runtimes.all_runtimes()):
        listing.InsertItem(row, item['name'])
        listing.SetItem(row, 1, ' '.join(item['extensions']))
        listing.SetItem(row, 2, _("ready") if item['available']
                        else _("not found"))
        listing.SetItem(row, 3, item['path'] if item['path'] != 'built in'
                        else _("built in"))
    if listing.GetItemCount():
        listing.Select(0)
        listing.Focus(0)

    examples = wx.Button(dialog, label=_("&Install the examples"))
    table = wx.Button(dialog, label=_("&Open the languages file"))
    close = wx.Button(dialog, wx.ID_CANCEL, _("&Close"))

    def on_examples(_event):
        wx.MessageBox(install_examples(), _("Programming languages"),
                      wx.OK | wx.ICON_INFORMATION, dialog)

    def on_table(_event):
        path = ensure_user_table()
        try:
            os.startfile(path)
        except Exception as error:
            wx.MessageBox(str(error), _("Programming languages"),
                          wx.OK | wx.ICON_ERROR, dialog)

    examples.Bind(wx.EVT_BUTTON, on_examples)
    table.Bind(wx.EVT_BUTTON, on_table)
    buttons = wx.BoxSizer(wx.HORIZONTAL)
    for button in (examples, table, close):
        buttons.Add(button, 0, wx.ALL, 4)
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(intro, 0, wx.ALL | wx.EXPAND, 8)
    sizer.Add(listing, 1, wx.ALL | wx.EXPAND, 8)
    sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
    dialog.SetSizer(sizer)
    listing.SetFocus()
    dialog.ShowModal()
    dialog.Destroy()


def _on_menu(event=None):
    show_window()


# -------------------------------------------------------- examples and table
def _user_data(kind):
    try:
        from src.platform_utils import get_user_resource_path
        return get_user_resource_path(os.path.join('data', kind))
    except Exception:
        return os.path.join(os.path.dirname(runtimes.user_dir()), 'data', kind)


def install_examples(overwrite=False):
    """Copy the example programs into the user's own data folders."""
    copied, kept = [], []
    for kind, target_kind in _KINDS.items():
        source_root = os.path.join(EXAMPLES_DIR, kind)
        if not os.path.isdir(source_root):
            continue
        target_root = _user_data(target_kind)
        os.makedirs(target_root, exist_ok=True)
        for name in sorted(os.listdir(source_root)):
            source = os.path.join(source_root, name)
            target = os.path.join(target_root, name)
            if not os.path.isdir(source):
                continue
            if os.path.exists(target) and not overwrite:
                kept.append(name)
                continue
            if os.path.exists(target):
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(source, target)
            copied.append(name)
    try:
        from src.titan_core import actions
        actions.invalidate()
    except Exception:
        pass
    parts = []
    if copied:
        parts.append(_("Installed: {}.").format(', '.join(copied)))
    if kept:
        parts.append(_("Already there, left as they were: {}.").format(
            ', '.join(kept)))
    if not parts:
        parts.append(_("There are no examples to install."))
    parts.append(_("The new applications and games appear in Titan's lists "
                   "after Titan is restarted; the component example is "
                   "started then too."))
    return ' '.join(parts)


def ensure_user_table():
    """The user's languages file, written with a commented example."""
    path = runtimes.user_table_path()
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import json
        sample = {
            '_comment': "Add a language, or tell an existing one where its "
                        "interpreter is. Placeholders: {file} {dir} {name} "
                        "{out} {exe} {sdk}. 'find' lists paths or names "
                        "looked for on PATH.",
            'runtimes': [
                {'id': 'javascript', 'find': ['C:/Program Files/nodejs/node.exe',
                                              'node']},
                {'id': 'example', 'name': 'Example language',
                 'extensions': ['.example'],
                 'command': ['{exe}', '{file}'], 'find': ['example-interpreter']},
            ]}
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(sample, handle, indent=2, ensure_ascii=False)
    return path


# ------------------------------------------------------------ the component
def add_menu(component_manager):
    component_manager.register_menu_function(_("Programming languages"),
                                             _on_menu)
    # Components in other languages are started here and not in
    # initialize(): their Components-menu entries must exist before Titan
    # builds its menu bar.
    try:
        started = components.start_all(component_manager)
        if started:
            print('[polyglot] components started: %s' % ', '.join(started))
    except Exception as error:
        print('[polyglot] could not start the components: %s' % error)


def initialize(app=None):
    hooks.install()
    components.initialize_all()


def shutdown():
    components.stop_all()


# ------------------------------------------------------------------ actions
def action_list_languages():
    lines = _languages_text()
    return _("Languages Titan programs may be written in:") + "\n" + \
        "\n".join("- " + line for line in lines)


def action_run_file(path, kind='app'):
    """Run a source file as an application (or a game)."""
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(str(path))))
    if not os.path.isfile(path):
        return _("There is no file at {}.").format(path)
    runtime = runtimes.for_file(path)
    if runtime is None:
        return _("No language is registered for {}.").format(
            os.path.basename(path))
    if not runtime.available():
        return runtime.why_not()
    pid = hooks.launch(path, os.path.dirname(path),
                       'game' if str(kind).lower() == 'game' else 'app',
                       runtime)
    return _("Started {} ({}).").format(os.path.basename(path), runtime.name) \
        if pid else _("{} could not be started.").format(os.path.basename(path))


def action_install_examples():
    return install_examples()


def action_components():
    running = components.running()
    if not running:
        return _("No component in another language is running.")
    lines = []
    for name, component in running.items():
        state = component.error or _("running")
        lines.append("- %s (%s): %s" % (name, component.runtime.name, state))
    return "\n".join(lines)


TITAN_ACTIONS = [
    {'name': 'list_languages',
     'summary': "List the programming languages Titan applications, games "
                "and components may be written in, and whether each one's "
                "interpreter is on this computer.",
     'run': action_list_languages},
    {'name': 'run_file',
     'summary': "Run a program written in another language (a .lua, .rb, "
                ".js, .cs, .ps1... file) as a Titan application or game.",
     'params': {'path': {'type': 'string', 'required': True,
                         'description': "The source file."},
                'kind': {'type': 'string', 'enum': ['app', 'game'],
                         'description': "app (default) or game."}},
     'risk': 'confirm', 'run': action_run_file},
    {'name': 'install_examples',
     'summary': "Copy the example programs in other languages into the "
                "user's applications, games and components.",
     'risk': 'confirm', 'run': action_install_examples},
    {'name': 'components',
     'summary': "Say which components written in other languages are "
                "running.",
     'run': action_components},
]

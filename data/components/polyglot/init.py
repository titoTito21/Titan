# -*- coding: utf-8 -*-
"""Polyglot - every kind of Titan add-on, in other languages.

An application, a game, a component, a Titan IM module, a widget, a
statusbar applet, a launcher, a settings interface, a shell add-on, a
gamepad mode, a TTS engine or a macro no longer has to be Python: its program may be
Lua, Ruby, JavaScript, C#,
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
from polyglotkit import adapters, stubs                # noqa: E402
from polyglotkit import settings_page                  # noqa: E402
from polyglotkit.i18n import _                        # noqa: E402

EXAMPLES_DIR = os.path.join(COMPONENT_DIR, 'examples')
#: The component's name, in every language: it is a name, not a description.
TITLE = 'Polyglot'
# example folder -> the data folder it is installed into
_KINDS = {'applications': 'applications', 'games': 'games',
          'components': 'components', 'titanIM_modules': 'titanIM_modules',
          'applets': 'applets', 'statusbar_applets': 'statusbar_applets',
          'launchers': 'launchers', 'settings interfaces': 'settings interfaces',
          'shell addons': 'shell addons',
          'gamepad modes': os.path.join('gamepad', 'modes'),
          'titantts engines': 'titantts engines', 'macros': 'macros'}

# The managers are reached the moment the component is loaded, so a program
# in another language can be opened from the very first menu Titan builds.
try:
    hooks.install()
except Exception as _error:                                  # noqa: N816
    print('[polyglot] could not reach the managers: %s' % _error)

# Every other kind is found by its loader through a Python entry file, which
# is written here for any add-on whose program is in another language - the
# loaders that run after the components (the Invisible UI's widgets, the
# shell, the settings interfaces, Titan IM) find it this very session.
try:
    _written = stubs.ensure_all()
    if _written:
        print('[polyglot] entries written: %s' % _written)
except Exception as _error:                                  # noqa: N816
    print('[polyglot] could not prepare the add-ons: %s' % _error)


# ---------------------------------------------------------------- the window
def _languages_text():
    lines = []
    for item in [r.describe() for r in runtimes.all_runtimes()]:
        state = _("ready") if item['available'] else _("not found")
        lines.append("%s (%s): %s" % (item['name'], ', '.join(item['extensions']),
                                      state))
    return lines


def _name_for_readers(control, name):
    """Name a native control for MSAA, not only for wx.

    `SetName` alone is wx's own bookkeeping and never reaches a screen
    reader for a list view or an edit box; `a11y.name_control` is what
    does (the rule the Titan shell learned first).
    """
    try:
        from src.shell import a11y
        a11y.name_control(control, name)
    except Exception:
        control.SetName(name)


def _show_text(parent, title, text):
    """A result to READ: a read-only text box, not a message box.

    The examples, the prepared add-ons and the list of add-ons in other
    languages are many lines long. In a message box a reader says them once
    and they are gone; in a text box its own cursor, say-all and Ctrl+C
    work. Escape and Close leave.
    """
    import wx
    dialog = wx.Dialog(parent, title=title,
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                       size=(640, 420))
    label = wx.StaticText(dialog, label=title)
    box = wx.TextCtrl(dialog, value=str(text or ''),
                      style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
    _name_for_readers(box, title)
    close = wx.Button(dialog, wx.ID_CANCEL, _("&Close"))
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(label, 0, wx.ALL, 8)
    sizer.Add(box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
    sizer.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
    dialog.SetSizer(sizer)
    dialog.SetEscapeId(wx.ID_CANCEL)
    box.SetFocus()
    try:
        dialog.ShowModal()
    finally:
        dialog.Destroy()


def show_window(parent=None):
    import wx

    dialog = wx.Dialog(parent, title=TITLE,
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                       size=(720, 460))
    intro = wx.StaticText(dialog, label=_(
        "Every kind of Titan add-on - applications, games, components, "
        "Titan IM modules, widgets, statusbar applets, launchers, settings "
        "interfaces, shell add-ons, gamepad modes and TTS engines - may be "
        "written in these languages. Lua needs nothing; the others need "
        "their interpreter or compiler on this computer."))
    # The label comes immediately BEFORE the list it names: Windows names a
    # list after the static text in front of it, which was the whole
    # introduction paragraph.
    listing_label = wx.StaticText(dialog, label=_("&Languages:"))
    listing = wx.ListCtrl(dialog, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
    _name_for_readers(listing, _("Languages"))
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
    prepare = wx.Button(dialog, label=_("&Prepare add-ons in other languages"))
    addons_button = wx.Button(dialog, label=_("&Add-ons in other languages"))
    table = wx.Button(dialog, label=_("Language &settings..."))
    close = wx.Button(dialog, wx.ID_CANCEL, _("&Close"))

    def on_examples(_event):
        _show_text(dialog, _("Install the examples"), install_examples())
        listing.SetFocus()

    def on_table(_event):
        dialog.EndModal(wx.ID_CANCEL)
        wx.CallAfter(settings_page.open_page, parent)

    def on_prepare(_event):
        _show_text(dialog, _("Prepare add-ons in other languages"),
                   prepare_addons())
        listing.SetFocus()

    def on_addons(_event):
        _show_text(dialog, _("Add-ons in other languages"), action_addons())
        listing.SetFocus()

    examples.Bind(wx.EVT_BUTTON, on_examples)
    prepare.Bind(wx.EVT_BUTTON, on_prepare)
    addons_button.Bind(wx.EVT_BUTTON, on_addons)
    table.Bind(wx.EVT_BUTTON, on_table)
    buttons = wx.BoxSizer(wx.HORIZONTAL)
    for button in (examples, prepare, addons_button, table, close):
        buttons.Add(button, 0, wx.ALL, 4)
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(intro, 0, wx.ALL | wx.EXPAND, 8)
    sizer.Add(listing_label, 0, wx.LEFT | wx.RIGHT, 8)
    sizer.Add(listing, 1, wx.ALL | wx.EXPAND, 8)
    sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
    dialog.SetSizer(sizer)
    dialog.SetEscapeId(wx.ID_CANCEL)
    listing.SetFocus()
    # Opened from the Invisible UI's components, its arrows, Enter and
    # Escape would otherwise still be the Invisible UI's while this window
    # is in front (CLAUDE.md, "A Titan window in front means the keys are
    # that window's").
    try:
        from src.shell.keyboard_handover import take_keyboard, give_keyboard_back
    except Exception:
        take_keyboard = give_keyboard_back = None
    if take_keyboard:
        take_keyboard('polyglot')
    try:
        dialog.ShowModal()
    finally:
        dialog.Destroy()
        if give_keyboard_back:
            give_keyboard_back('polyglot')


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
        stubs.ensure_all()
    except Exception as error:
        print('[polyglot] could not prepare the examples: %s' % error)
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
    parts.append(_("The new add-ons appear in Titan after Titan is "
                   "restarted."))
    return ' '.join(parts)


def ensure_user_table():
    """The user's languages file (Settings -> Polyglot edits it)."""
    return settings_page.ensure_user_table()


# ------------------------------------------------------------ the component
def add_menu(component_manager):
    component_manager.register_menu_function(TITLE,
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


def add_settings_category(component_manager):
    settings_page.register(component_manager)


def initialize(app=None):
    hooks.install()
    components.initialize_all()


def shutdown():
    components.stop_all()
    adapters.stop_all()


def prepare_addons():
    """Write the Python entry of every add-on in another language."""
    written = stubs.ensure_all()
    found = stubs.foreign_addons()
    if not found:
        return _("There is no add-on in another language.")
    lines = [_("Add-ons in other languages: {}.").format(len(found))]
    if written:
        names = ', '.join(name for names in written.values() for name in names)
        lines.append(_("Prepared now: {}.").format(names))
        lines.append(_("They are loaded when Titan is restarted."))
    else:
        lines.append(_("All of them were ready."))
    return ' '.join(lines)


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


def action_prepare_addons():
    return prepare_addons()


def action_addons():
    found = stubs.foreign_addons()
    if not found:
        return _("There is no add-on in another language.")
    live = adapters.running()
    lines = []
    for kind, name, folder, source, runtime in found:
        key = (kind, os.path.normcase(os.path.abspath(folder)))
        addon = live.get(key)
        if addon is None:
            state = _("not loaded")
        elif addon.error:
            state = addon.error
        else:
            state = _("running")
        lines.append("- %s (%s, %s): %s" % (name, kind, runtime.name, state))
    return "\n".join(lines)


def _load_through_titan(kind, name, folder):
    """The add-on, loaded by the loader Titan itself uses for its kind."""
    if kind == 'statusbar_applet':
        from src.titan_core.statusbar_applet_manager import StatusbarAppletManager
        manager = StatusbarAppletManager()
        entry = manager.applets.get(name)
        if entry is None:
            raise RuntimeError("Titan's statusbar did not load it.")
        module = entry['module']
        return [module.get_statusbar_item_text()]
    if kind == 'widget':
        from src.ui.main_window_actions import _widget_modules
        for found, module, info in _widget_modules():
            if found == name:
                if info.get('error'):
                    raise RuntimeError(info['error'])
                widget = module.get_widget_instance(lambda *a, **k: None)
                return [info.get('name'), widget.get_current_element()]
        raise RuntimeError("Titan's widget list did not load it.")
    if kind == 'im_module':
        from src.network.im_module_manager import TitanIMModuleManager
        manager = TitanIMModuleManager()
        manager.load_modules()
        if not any(i['id'] == name for i in manager.modules):
            raise RuntimeError("Titan IM did not load it.")
        return ['status: %r' % manager.get_status_text(name)]
    if kind == 'gamepad_mode':
        from src.controller import gamepad_mode_api
        for mode in gamepad_mode_api.load_custom_modes():
            if mode.mode_id == 'custom:' + name:
                return [mode.get_display_name()]
        raise RuntimeError("Titan's gamepad modes did not load it.")
    if kind == 'tts_engine':
        from src.tts.engine_registry import get_engine_registry
        registry = get_engine_registry()
        for engine in registry.get_all_engines():
            if getattr(type(engine), 'polyglot_addon', None) is not None and                     os.path.normcase(type(engine).polyglot_addon.folder) ==                     os.path.normcase(os.path.abspath(folder)):
                return [engine.engine_name] + [v.get('display_name', v.get('id'))
                                               for v in engine.get_voices()]
        raise RuntimeError("Titan's TTS engines did not load it.")
    if kind == 'shell_addon':
        from src.shell import addons as shell_addons
        manager = shell_addons.manager()
        manager.scan(force=True)
        config = manager.config(name)
        if config is None or not config.enabled:
            raise RuntimeError("It is switched off: {}.enable puts it on.".format(
                name))
        addon = manager.load(name)
        if addon is None:
            raise RuntimeError("Titan's shell did not load it.")
        found = []
        for surface, hooks_of in shell_addons.HOOKS.items():
            for hook in hooks_of:
                if addon.hook(hook) is None or hook in ('setup', 'teardown',
                                                        'on_shell_start',
                                                        'on_shell_stop'):
                    continue
                if hook == 'start_menu_items':
                    # This add-on's own answer, checked the way the shell
                    # checks every answer.
                    entries = shell_addons._entries(
                        addon.hook(hook)(addon.api, None), addon)
                    found.extend('%s: %s%s' % (
                        hook, e.get('label'),
                        '' if callable(e.get('action')) else ' (no action)')
                        for e in entries)
                else:
                    found.append(hook)
        return found
    if kind == 'settings_interface':
        from src.settings import interfaces
        module = interfaces.manager().module(name)
        if module is None or not callable(getattr(module, 'open_settings',
                                                  None)):
            raise RuntimeError("Titan's settings did not load it.")
        return ['open_settings']
    if kind == 'launcher':
        from src.titan_core.launcher_manager import LauncherManager
        manager = LauncherManager()
        config = manager.get_launcher_by_name(name)
        if config is None:
            raise RuntimeError("Titan does not list it as a launcher.")
        module = manager._load_module(manager._find_init_file(config.path),
                                      name)
        if module is None or not callable(getattr(module, 'start', None)):
            raise RuntimeError("Titan's launcher manager did not load it.")
        return ['start']
    raise RuntimeError('Polyglot cannot check a %s.' % kind)


def _while_titan_runs(function, seconds=30.0):
    """Run ``function`` on a thread of its own and wait for it WITHOUT
    stopping Titan: this is called on Titan's GUI thread, and that is the
    thread whose wx.Timer polls the gamepad - blocking it would stop the
    very loop the virtual pad is there to be read by."""
    import threading
    import time
    box = {}

    def run():
        try:
            box['value'] = function()
        except Exception as error:
            box['error'] = error
    worker = threading.Thread(target=run, name='PolyglotCheck', daemon=True)
    worker.start()
    try:
        import wx
        app = wx.GetApp()
    except Exception:
        app = None
    end = time.time() + seconds
    while worker.is_alive() and time.time() < end:
        if app is not None and wx.IsMainThread():
            app.Yield(True)
        time.sleep(0.02)
    if 'error' in box:
        raise box['error']
    if worker.is_alive():
        raise RuntimeError('it did not finish in %d s' % seconds)
    return box.get('value')


def _run_on_its_surface(kind, name, folder):
    """Use the add-on where Titan uses it, not only load it.

    * a shell add-on: Titan's own Start menu (the classic one, which needs
      no shell running) is built - not shown - and the add-on's entry is
      found among the menu's entries and chosen through the menu's own
      `_activate_entry`, exactly as Enter on it would;
    * a gamepad mode: the real gamepad mode manager is switched to it and
      handed a button press through `handle_button_press`, which is where
      a pad's button arrives - then the mode the user had is put back.
    """
    if kind == 'shell_addon':
        from src.ui.classic_start_menu import ClassicStartMenu
        menu = ClassicStartMenu(None)
        try:
            # A command is ('addon', the item); a branch is ('folder',
            # ('__addon__', the item)) - both carry which add-on said it.
            ours = []
            for entry in menu.addon_entries():
                item = entry.payload
                if isinstance(item, tuple):
                    item = item[1] if len(item) > 1 else {}
                if isinstance(item, dict) and item.get('addon') == name                         and entry.kind == 'addon':
                    ours.append(entry)
            if not ours:
                raise RuntimeError("Titan's Start menu does not offer it.")
            for entry in ours:
                menu._activate_entry(entry)
            return ['Start menu: chose %s' % ', '.join(e.label for e in ours)]
        finally:
            try:
                menu.Destroy()
            except Exception:
                pass
    if kind == 'gamepad_mode':
        from src.controller.controller_modes import get_mode_manager
        manager = get_mode_manager()
        previous = manager._current_cycle_entry()
        mode = next((m for m in manager.custom_modes
                     if m.mode_id == 'custom:' + name), None)
        if mode is None:
            raise RuntimeError("Titan's gamepad does not offer it.")
        addon = getattr(type(mode), 'polyglot_addon', None)
        try:
            manager.change_mode(mode)
            answers = ['active: %s' % manager._mode_description(
                manager._current_cycle_entry())]
            try:
                # A virtual pad: SDL reports it like a USB one, so Titan's
                # own polling loop reads the button - the whole way a real
                # pad's button goes.
                from polyglotkit import virtualpad
                seen = len(addon.history) if addon else 0
                answers.append(_while_titan_runs(lambda: virtualpad.press(0)))
                reached = [args for name, args in list(addon.history)[seen:]
                           if name == 'handle_button'] if addon else []
                answers.append('the mode was handed button %s by Titan'
                               % (reached[0][0] if reached else 'NONE'))
            except Exception as error:
                # No virtual pads here: hand the button to the manager,
                # which is where the polling loop would have.
                used = manager.handle_button_press(0, True)
                answers.append('virtual pad unavailable (%s); button 0 %s'
                               % (error, 'used' if used else 'not used'))
            return answers
        finally:
            manager.change_mode(previous)
    return []


def action_check_addon(name, run=False):
    """Load one add-on in another language the way Titan does, and ask it
    what Titan would ask; ``run`` also uses it where Titan uses it (a shell
    add-on's Start menu entry chosen, a gamepad mode handed a button)."""
    wanted = str(name or '').strip().lower()
    run = str(run).strip().lower() in ('1', 'true', 'yes', 'on')
    for kind, found, folder, source, runtime in stubs.foreign_addons():
        if found.lower() != wanted:
            continue
        try:
            stubs.ensure(kind, folder)
            answers = _load_through_titan(kind, found, folder)
            if run:
                answers = list(answers) + _run_on_its_surface(kind, found,
                                                              folder)
        except Exception as error:
            return _("{} ({}, {}) could not be loaded: {}").format(
                found, kind, runtime.name, error)
        return _("{} ({}, {}) is loaded by Titan and answers: {}").format(
            found, kind, runtime.name,
            '; '.join(str(a) for a in answers) or '-')
    return _("There is no add-on called {} in another language.").format(name)


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
    {'name': 'prepare_addons',
     'summary': "Make every add-on written in another language loadable: "
                "write the small Python entry each kind of add-on is found "
                "by. Run before packing such an add-on.",
     'run': action_prepare_addons},
    {'name': 'addons',
     'summary': "List the add-ons of every kind (Titan IM modules, widgets, "
                "statusbar applets, launchers, settings interfaces, shell "
                "add-ons, gamepad modes, TTS engines) written in other "
                "languages, and whether each is running.",
     'run': action_addons},
    {'name': 'check_addon',
     'summary': "Load one add-on written in another language through the "
                "loader Titan uses for its kind, and say what it answers "
                "(a statusbar text, a widget's element, a shell add-on's "
                "Start menu entries...) - nothing is opened or run.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The add-on's folder name."},
                'run': {'type': 'boolean',
                        'description': "Also use it where Titan does: a "
                                       "shell add-on's Start menu entry is "
                                       "chosen, a gamepad mode is handed a "
                                       "button."}},
     'run': action_check_addon},
    {'name': 'components',
     'summary': "Say which components written in other languages are "
                "running.",
     'run': action_components},
]

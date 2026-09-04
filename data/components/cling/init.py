# -*- coding: utf-8 -*-
"""Cling - the Klango subsystem for Titan.

Klango was a whole desktop for blind users, and the applications written for it
- Mole No More, the piano, the typing course, the soundscapes - are still on
people's disks and still being written.  They are not Windows programs: an
application is a folder of texts, sounds, levels and a topology, and it needs a
platform underneath it that speaks, plays a sound at a place, keeps a score and
owns the keyboard.  Cling is that platform, inside Titan.

What that means concretely:

* **An application is a folder in `data/cling/`** - the layout Klango
  applications already have, `kni.txt` and `lang/` and `skin/` unchanged.  The
  user's own overlay wins over the bundled one and a packaged `.TCD` is found
  exactly like a directory, because discovery is Titan's own.
* **Everything Cling ships is inside the component.**  Its own applications
  are in `apps/`, its written-here logic in `logic/`, its Lua in
  `clingkit/lua/`, its languages in `languages/`.  `data/cling/` holds the
  USER's - the applications they installed and Klango's own library if they
  have it - so this folder can be copied to another Titan, or packaged as a
  `.TCD`, and still be whole.
* **The voice is Titan's.**  Whatever TTS the user chose, at the rate they set,
  positioned - a mole on the left of the board is heard on the left.
* **The account is Titan-Net's.**  Klango applications ask for a Klango account
  for their scores and their chats; there is no such thing here, and the user
  already has an identity on this desktop, so that is the one they are given.
* **The rules come from the data where the data has them** - five engines, one
  per genre - and from the application's own `main.lua` where it brings its
  own, run by the Lua interpreter this component carries.  Nothing has to be
  installed for either.
"""

import configparser
import gettext
import os
import sys

COMPONENT_DIR = os.path.dirname(os.path.abspath(__file__))
if COMPONENT_DIR not in sys.path:
    sys.path.insert(0, COMPONENT_DIR)
LIB_DIR = os.path.join(COMPONENT_DIR, 'lib')
if os.path.isdir(LIB_DIR) and LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

# The package is `clingkit`, not `cling`, and the reason is worth writing down:
# the component manager registers this module as `sys.modules['<folder name>']`
# BEFORE it executes it, so a package sharing the folder's name is shadowed by a
# half-built module and every `from cling import ...` fails with "cannot import
# name". The component is still called Cling everywhere a person can see it -
# and because these names are re-exported below, another add-on that says
# `import cling; cling.engines.register(...)` gets exactly what it expects.
from clingkit import account as cling_account       # noqa: E402
from clingkit import catalog, engines, runner, store  # noqa: E402
from clingkit import lua as cling_lua               # noqa: E402
from clingkit import host, pag, resources, topology  # noqa: E402  (re-exported)


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------
LANGUAGES_DIR = os.path.join(COMPONENT_DIR, 'languages')


def _setup_translations():
    try:
        from src.titan_core.translation import language_code
        language = language_code
    except Exception:
        language = 'pl'
    try:
        return gettext.translation('cling', LANGUAGES_DIR, languages=[language],
                                   fallback=True).gettext
    except Exception:
        return lambda text: text


_ = _setup_translations()


def _language():
    try:
        from src.titan_core.translation import language_code
        return language_code
    except Exception:
        return ''


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
CONFIG_NAME = 'cling.ini'


def _config_path():
    try:
        from src.platform_utils import get_user_resource_path
        base = get_user_resource_path('')
    except Exception:
        base = COMPONENT_DIR
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        base = COMPONENT_DIR
    return os.path.join(base, CONFIG_NAME)


def get_setting(key, default='True'):
    parser = configparser.ConfigParser()
    try:
        parser.read(_config_path(), encoding='utf-8')
        return parser.get('Cling', key, fallback=default)
    except Exception:
        return default


def set_setting(key, value):
    parser = configparser.ConfigParser()
    path = _config_path()
    try:
        parser.read(path, encoding='utf-8')
    except Exception:
        pass
    if 'Cling' not in parser:
        parser['Cling'] = {}
    parser['Cling'][key] = str(value)
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            parser.write(handle)
    except OSError as error:
        print('[cling] could not save settings: %s' % error)


def _truthy(value):
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_gui_app = None
_browser = None
_listbox = None
_iui = None


def _wx():
    import wx
    return wx


def _speak(text):
    try:
        from src.titan_core.stereo_speech import speak_stereo
        speak_stereo(text)
    except Exception:
        print('[cling] %s' % text)


def applications(enabled_only=True):
    """Every installed Cling application, in the user's language."""
    found = catalog.discover(language=_language())
    if enabled_only:
        found = [app for app in found if app.enabled and not app.hidden]
    return found


def find_application(name):
    """One application by identifier or by the name the user would say."""
    if not name:
        return None
    wanted = str(name).strip().lower()
    found = applications(enabled_only=False)
    for app in found:
        if app.id.lower() == wanted:
            return app
    for app in found:
        if app.name(_language()).lower() == wanted:
            return app
    for app in found:
        if wanted in app.name(_language()).lower() or wanted in app.id.lower():
            return app
    return None


def open_browser(parent=None):
    """Open the Cling window, or bring the open one forward."""
    global _browser
    wx = _wx()
    try:
        if _browser is not None and not _browser.IsBeingDeleted():
            _browser.Raise()
            return _browser
    except RuntimeError:
        pass
    from clingkit import ui
    _browser = ui.ClingBrowser(parent or _gui_app, translate=_,
                               language=_language())
    _browser.Bind(wx.EVT_WINDOW_DESTROY, _forget_browser)
    _browser.Show()
    # Cling reads what is installed, unpacks a package it has not seen and
    # looks for Klango's library before the list is a list, so "it is open"
    # and "it is ready" are not the same moment. This is the second one, and
    # it is the one worth saying to somebody who cannot see the window.
    _speak(_('Cling is ready'))
    return _browser


def _forget_browser(event):
    global _browser
    _browser = None
    event.Skip()


def run_application(app, parent=None):
    from clingkit import ui
    return ui.run_app(app, parent=parent or _gui_app, translate=_,
                      language=_language())


# ---------------------------------------------------------------------------
# Installing an application
# ---------------------------------------------------------------------------
def install_from_folder(source):
    """Copy a Klango application folder into `data/cling/`. Returns (id, error).

    A folder is copied rather than linked or moved: the user's Klango
    installation is not Cling's to change, and an application that stopped
    working because Titan had moved it would be the worst possible answer.
    """
    import shutil

    source = os.path.abspath(str(source or ''))
    if not os.path.isdir(source):
        return '', _('There is no folder there.')
    if not catalog.looks_like_app(source):
        return '', _('That folder has no kni.txt, so it is not a Klango or '
                     'Cling application.')
    target_root = catalog.user_apps_dir()
    name = os.path.basename(source.rstrip(os.sep)) or 'application'
    target = os.path.join(target_root, name)
    if os.path.exists(target):
        return '', _('An application called %s is already installed.') % name
    try:
        shutil.copytree(source, target)
    except (OSError, shutil.Error) as error:
        return '', _('It could not be copied: %s') % error
    _remember_category(source, target)
    return name, ''


def _remember_category(source, target):
    """Write down which part of Klango an application was installed from.

    A Klango application knows where it belongs by where it SITS -
    `apps/simplegames/mole` is a game because of the folder above it - and
    that folder is exactly what installing it into `data/cling/` throws away.
    So the category is read off the source path once, here, and written into
    the installed copy's own manifest.  The user's original is never touched;
    this is Cling's copy, and a note in it is Cling's to make.
    """
    category = catalog._category_of('', source)
    if category == 'other':
        return
    manifest = os.path.join(target, catalog.MANIFEST)
    parser = configparser.ConfigParser()
    try:
        if os.path.isfile(manifest):
            parser.read(manifest, encoding='utf-8')
        if catalog.MANIFEST_SECTION not in parser:
            parser[catalog.MANIFEST_SECTION] = {}
        parser[catalog.MANIFEST_SECTION]['category'] = category
        with open(manifest, 'w', encoding='utf-8') as handle:
            parser.write(handle)
    except (OSError, configparser.Error) as error:
        print('[cling] could not note the category for %s: %s' % (target, error))


def install_many(source_root):
    """Install every application under a Klango `apps/` tree. Returns a report."""
    source_root = os.path.abspath(str(source_root or ''))
    if not os.path.isdir(source_root):
        return _('There is no folder there.')
    installed = []
    skipped = []
    for directory, subdirectories, _files in os.walk(source_root):
        if catalog.looks_like_app(directory):
            subdirectories[:] = []          # an application is not a container
            name, error = install_from_folder(directory)
            if name:
                installed.append(name)
            else:
                skipped.append('%s: %s' % (os.path.basename(directory), error))
    if not installed and not skipped:
        return _('No Klango applications were found there.')
    lines = []
    if installed:
        lines.append(_('Installed: %s') % ', '.join(sorted(installed)))
    if skipped:
        lines.append(_('Left alone: %s') % '; '.join(skipped))
    return '\n'.join(lines)


def _ask_and_install():
    wx = _wx()
    dialog = wx.DirDialog(_gui_app, _('Choose a Klango application folder, or '
                                      'the folder its applications are in'),
                          style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return
        chosen = dialog.GetPath()
    finally:
        dialog.Destroy()
    if catalog.looks_like_app(chosen):
        name, error = install_from_folder(chosen)
        report = _('Installed %s.') % name if name else error
    else:
        report = install_many(chosen)
    wx.MessageBox(report, _('Cling'), wx.OK | wx.ICON_INFORMATION)
    if _browser is not None:
        try:
            _browser.refresh()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Titan component hooks
# ---------------------------------------------------------------------------
def add_menu(component_manager):
    component_manager.register_menu_function(_('Cling'), _on_menu_action)


def _on_menu_action(_event=None):
    open_browser()


def get_gui_hooks():
    return {'on_gui_init': _on_gui_init}


def _on_gui_init(gui_app):
    """A Cling view in the main window, beside applications and games."""
    global _gui_app, _listbox
    wx = _wx()
    _gui_app = gui_app
    _listbox = wx.ListBox(gui_app.main_panel)
    _fill_listbox()
    _listbox.Bind(wx.EVT_LISTBOX, lambda event: _play('core/focus.ogg'))
    gui_app.component_manager.register_view(
        view_id='cling', label=_('Cling:'), control=_listbox,
        on_show=_fill_listbox, on_activate=_on_view_activate,
        position='after_network')


def _fill_listbox():
    if _listbox is None:
        return
    try:
        _listbox.Clear()
    except RuntimeError:
        return
    found = applications()
    if not found:
        _listbox.Append(_('No Cling applications are installed'))
        _listbox.SetClientData(0, None)
        return
    for index, app in enumerate(found):
        _listbox.Append(app.name(_language()))
        _listbox.SetClientData(index, app)


def _on_view_activate(_event=None):
    if _listbox is None:
        return
    wx = _wx()
    selection = _listbox.GetSelection()
    if selection == wx.NOT_FOUND:
        return
    app = _listbox.GetClientData(selection)
    if app is None:
        open_browser()
        return
    run_application(app)


def _play(name):
    try:
        from src.titan_core.sound import play_sound
        play_sound(name)
    except Exception:
        pass


def get_iui_hooks():
    return {'on_iui_init': _on_iui_init}


def _on_iui_init(iui):
    """A Cling category in the Invisible UI, its applications as elements."""
    global _iui
    _iui = iui
    names = [app.name(_language()) for app in applications()]
    if not names:
        names = [_('No Cling applications are installed')]
    position = max(0, len(iui.categories) - 1)
    iui.categories.insert(position, {
        'name': _('Cling'),
        'sound': 'core/focus.ogg',
        'elements': names,
        'action': _iui_action,
    })


def _iui_action(name):
    app = find_application(name)
    if app is None:
        _speak(_('No Cling applications are installed'))
        return
    _restore_titan()
    run_application(app)


def get_klango_hooks():
    return {'on_klango_init': _on_klango_init}


def _on_klango_init(klango_mode):
    """A Cling submenu in Klango mode - which is where it belongs most."""
    items = [{'name': app.name(_language()), 'type': 'action',
              'action': (lambda a=app: (_restore_titan(), run_application(a)))}
             for app in applications()]
    if not items:
        items = [{'name': _('No Cling applications are installed'),
                  'type': 'action',
                  'action': lambda: _speak(
                      _('No Cling applications are installed'))}]
    menu = {'name': _('Cling'), 'type': 'submenu', 'items': items,
            'expanded': False}
    if len(klango_mode.main_menu) > 5:
        klango_mode.main_menu.insert(5, menu)
    else:
        klango_mode.main_menu.append(menu)


def _restore_titan():
    """Bring Titan's window back the one way everything else brings it back."""
    try:
        frame = _gui_app
        if frame is not None and hasattr(frame, 'restore_from_tray'):
            frame.restore_from_tray()
    except Exception:
        pass


def add_settings_category(component_manager):
    wx = _wx()

    def build(parent):
        panel = wx.Panel(parent)
        box = wx.BoxSizer(wx.VERTICAL)

        panel.online_scores = wx.CheckBox(
            panel, label=_('Send high scores to my Titan-Net account'))
        box.Add(panel.online_scores, flag=wx.LEFT | wx.TOP, border=10)

        panel.read_everything = wx.CheckBox(
            panel, label=_('Read out everything an application says'))
        box.Add(panel.read_everything, flag=wx.LEFT | wx.TOP, border=10)

        who = cling_account.whoami()
        box.Add(wx.StaticText(panel, label=_('Account: %s') % who.describe()),
                flag=wx.LEFT | wx.TOP, border=10)
        box.Add(wx.StaticText(panel, label=cling_lua.describe()),
                flag=wx.LEFT | wx.TOP, border=10)
        box.Add(wx.StaticText(
            panel, label=_('Applications are read from: %s')
            % catalog.user_apps_dir()), flag=wx.LEFT | wx.TOP, border=10)

        button = wx.Button(panel, label=_('Install a Klango application...'))
        button.Bind(wx.EVT_BUTTON, lambda event: _ask_and_install())
        box.Add(button, flag=wx.LEFT | wx.TOP, border=10)

        panel.SetSizer(box)
        panel.Layout()
        return panel

    def save(panel):
        set_setting('online_scores', panel.online_scores.GetValue())
        set_setting('read_everything', panel.read_everything.GetValue())

    def load(panel):
        panel.online_scores.SetValue(_truthy(get_setting('online_scores', 'True')))
        panel.read_everything.SetValue(
            _truthy(get_setting('read_everything', 'True')))

    component_manager.register_settings_category(_('Cling'), build, save, load)


def initialize(_app=None):
    """Called once the event loop is running."""
    print('[cling] %d application(s) installed; %s'
          % (len(applications()), cling_lua.describe()))


def shutdown():
    from clingkit import ui
    for surface in list(getattr(ui, '_open', {}).values()):
        try:
            surface.Close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Titan actions - what Titan, its AI and other add-ons can ask of Cling
# ---------------------------------------------------------------------------
try:
    from src.titan_core.actions import fails, needs
except Exception:
    def fails(reason):
        return reason

    def needs(name, prompt, options=None, kind='string', default=''):
        return prompt


def action_list(**_kwargs):
    found = applications()
    if not found:
        return ('No Cling applications are installed. They go in %s.'
                % catalog.user_apps_dir())
    lines = []
    for app in found:
        summary = app.summary(_language())
        lines.append('- %s (%s, %s)%s'
                     % (app.name(_language()), app.id, app.engine,
                        ': %s' % summary if summary else ''))
    return 'Cling applications:\n' + '\n'.join(lines)


def action_run(name='', **_kwargs):
    if not name:
        return needs('name', "Which Cling application should I open?",
                     options=[app.name(_language()) for app in applications()])
    app = find_application(name)
    if app is None:
        return fails("There is no Cling application called '%s'." % name)
    if app.locked:
        return fails(app.locked_reason())
    try:
        import wx
        wx.CallAfter(run_application, app)
    except Exception as error:
        return fails('It could not be opened: %s' % error)
    return 'Opened %s.' % app.name(_language())


def action_details(name='', **_kwargs):
    if not name:
        return needs('name', "Which application do you mean?")
    app = find_application(name)
    if app is None:
        return fails("There is no Cling application called '%s'." % name)
    if app.locked:
        return app.locked_reason()
    lines = ['%s (%s)' % (app.name(_language()), app.id),
             app.summary(_language()) or '',
             'Engine: %s' % app.engine,
             'Category: %s' % app.category,
             'Version: %s' % (app.version or '-'),
             'Language: %s' % (app.texts.locale if app.texts else '-'),
             'Folder: %s' % app.path,
             ('Original Klango package: %s' % app.package)
             if app.package else '']
    lines.extend('Problem: %s' % problem for problem in app.problems)
    return '\n'.join(line for line in lines if line)


def action_scores(name='', **_kwargs):
    if not name:
        return needs('name', "Which application's scores?")
    app = find_application(name)
    if app is None:
        return fails("There is no Cling application called '%s'." % name)
    local = store.Store(app.id, cling_account.profile())
    rows = local.scores()
    lines = ['%d. %s: %d' % (position, entry.get('name') or '-',
                             int(entry.get('points', 0)))
             for position, entry in enumerate(rows, start=1)]
    shared = cling_account.leaderboard(app.id)
    if shared:
        lines.append('On Titan-Net:')
        lines.extend('%d. %s: %d' % (position, row.get('name') or '?',
                                     int(row.get('points', 0) or 0))
                     for position, row in enumerate(shared, start=1))
    return '\n'.join(lines) or 'No scores yet for %s.' % app.name(_language())


def action_install(path='', **_kwargs):
    if not path:
        return needs('path', 'Where is the Klango application folder?',
                     kind='folder')
    if catalog.looks_like_app(path):
        name, error = install_from_folder(path)
        return ('Installed %s.' % name) if name else fails(error)
    return install_many(path)


def action_account(**_kwargs):
    who = cling_account.whoami()
    return ('%s Cling applications play under the profile "%s".'
            % (who.describe(), who.profile))


def action_emulate(name='', **_kwargs):
    """Load an application's OWN Klango code and report how far it gets.

    This is the emulation path, as opposed to the engines that re-create a
    genre from an application's data. It is deliberately a report rather than
    a way to play: what it is for is saying, precisely, which of Klango's
    primitives an application still needs - so the next one written is the one
    that is actually in the way.
    """
    if not name:
        return needs('name', "Which application's own code should I load?")
    app = find_application(name)
    if app is None:
        return fails("There is no Cling application called '%s'." % name)
    try:
        from clingkit import host as host_module, klango
    except Exception as error:
        return fails('the emulation layer is not available: %s' % error)
    try:
        host = host_module.ClingHost(app, _language())
        session, started = klango.boot(host)
    except Exception as error:
        return fails('it could not be loaded: %s' % error)
    lines = ['%s: %d Lua file(s) loaded, main() %s'
             % (app.name(_language()), len(session.loaded),
                'ran' if started else 'did not run')]
    lines.extend('  ' + line for line in session.report()[:20])
    return '\n'.join(lines)


def action_status(**_kwargs):
    found = applications()
    by_engine = {}
    for app in found:
        by_engine[app.engine] = by_engine.get(app.engine, 0) + 1
    locked = [app for app in found if app.locked]
    lines = ['Cling: %d application(s) installed.' % len(found)]
    if locked:
        lines.append('  %d of them are Klango packages Cling cannot open yet: %s'
                     % (len(locked), ', '.join(sorted(app.id for app in locked))))
    for engine in sorted(by_engine):
        lines.append('  %s: %d' % (engine, by_engine[engine]))
    lines.append(cling_lua.describe())
    lines.append('Engines available: %s' % ', '.join(engines.names()))
    lines.append('Applications are read from %s' % catalog.user_apps_dir())
    lines.append(cling_account.whoami().describe())
    return '\n'.join(lines)


TITAN_ACTIONS = [
    {'name': 'list_applications',
     'summary': 'List the Klango/Cling applications and games installed.',
     'run': action_list},
    {'name': 'run',
     'summary': "Open one of the user's Cling applications or games by name.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': 'What the application is called.'}},
     'promote': True, 'run': action_run},
    {'name': 'details',
     'summary': 'What one Cling application is, which engine runs it and where '
                'it is installed.',
     'params': {'name': {'type': 'string', 'required': True,
                         'description': 'What the application is called.'}},
     'run': action_details},
    {'name': 'scores',
     'summary': "One application's high scores, this machine's and the shared "
                'Titan-Net table.',
     'params': {'name': {'type': 'string', 'required': True,
                         'description': 'What the application is called.'}},
     'run': action_scores},
    {'name': 'install',
     'summary': 'Install a Klango application folder (or every application '
                'under a folder) into the user\'s Cling applications.',
     'params': {'path': {'type': 'string', 'required': True,
                         'description': 'The folder to install from.'}},
     'risk': 'confirm', 'run': action_install},
    {'name': 'emulate',
     'summary': "Load an application's OWN Klango code (rather than Cling's "
                'engine for it) and report how far it gets and which Klango '
                'primitives are still missing.',
     'params': {'name': {'type': 'string', 'required': True,
                         'description': 'What the application is called.'}},
     'run': action_emulate},
    {'name': 'account',
     'summary': 'Which account Cling applications play under. Klango asked for '
                'its own; Cling uses the Titan-Net one.',
     'run': action_account},
    {'name': 'status',
     'summary': 'What Cling has installed, which engines it can drive and '
                'which Lua it is using.',
     'run': action_status},
]

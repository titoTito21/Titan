# -*- coding: utf-8 -*-
"""
Settings interfaces: somebody else's window onto Titan's own settings.

Titan has one settings window, written in wxPython, and it is a good one -
but it is one.  Somebody who would rather have their settings as a web page,
in Qt, on a console, as one question at a time read aloud, or as a wizard
that asks six things and stops, has until now had to change Titan.

`data/settings interfaces/` is the answer, and it is deliberately shaped
like `data/launchers/`, because it is the same idea one level down: a
launcher replaces Titan's main window, a settings interface replaces its
settings window.  One is chosen at a time (Settings -> Interface -> "Settings
interface", where Titan's own window is called **Classic**), Titan's own is
the default and always available, and every way into the settings in the
whole program goes through `open_settings()` here -
so choosing one changes the Settings entry in the menu bar, in the Invisible
UI, in Klango mode, in the Start menu, on the desktop's menu and in
`titan.open_settings` alike.

**The interface does not need to know what a setting is.**  That is the
part that makes this possible at all: it is handed `api.categories()` -
every category, every setting, its label in the user's language, its kind,
its options and its current value, read out of Titan's own settings window
by `src/settings/ui_model.py`.  So an interface author writes a renderer,
not a catalogue, and a setting added to Titan tomorrow appears in their
interface with no change to it.  Saving is `api.save()`, which is Titan's
own save with all its side effects, not a write to the ini file.

    __settings_ui__.TCE            the manifest ([settings interface])
    init.py                        open_settings(api) -> a window, or True

An interface that fails to load, fails to open, or is no longer installed
means Titan's own window opens instead.  Settings are the place a user goes
to fix things, up to and including "turn this interface off", so they can
never be the thing an add-on takes away.
"""

import configparser
import importlib.util
import os
import sys
import types

from src.platform_utils import (discover_data_entries as _discover,
                                is_frozen as _is_frozen)
from src.settings.settings import get_setting, set_setting

INTERFACE_DIR = 'settings interfaces'
MANIFEST = '__settings_ui__.TCE'
SECTION = 'settings interface'

#: The one function an interface must define, and the whole of the contract.
ENTRY_POINT = 'open_settings'

#: The keys `__settings_ui__.TCE` understands, beside `name_<lang>` /
#: `description_<lang>`.  Written down because it is what an interface author -
#: and the AI creation kit, which writes interfaces - is checked against: a
#: manifest key nobody reads is a promise the author believes has been kept.
MANIFEST_KEYS = ('name', 'description', 'author', 'version', 'status', 'libs')

#: Where the choice is kept.  Empty means Titan's own window, which is what
#: the Interface tab calls **Classic**.  The `interface` section on purpose:
#: it is the tab the choice is on, and `OnSave` writes that section key by
#: key while it replaces `general` wholesale.
SETTING_KEY = 'settings_interface'
SETTING_SECTION = 'interface'


def _localised(get, key, fallback=''):
    """`name_pl` before `name`, the way `__app.TCE` has always worked.

    An add-on's name is the add-on author's to write, so it is not a
    translatable string of Titan's - but the applications' manifest solved
    this years ago with `name_pl=` / `name_en=` beside `name=`, and a file
    that is read by the same eyes should not answer the same question a
    second way.
    """
    try:
        from src.titan_core.translation import language_code
    except Exception:
        language_code = 'en'
    for candidate in (f'{key}_{language_code}', key):
        value = get(candidate, '')
        if value:
            return value
    return fallback


class SettingsInterfaceConfig:
    """One `__settings_ui__.TCE`, parsed."""

    def __init__(self, path, folder_name):
        self.path = path
        self.id = folder_name
        self.name = folder_name
        self.description = ''
        self.author = ''
        self.version = '1.0'
        # 0 = offered, 1 = not offered.  An interface changes nothing by
        # being installed - it is one of the choices in Settings ->
        # Interface until somebody picks it - so `status = 0` is what an
        # interface ships with, unlike a shell add-on, which starts doing
        # things the moment it is switched on.
        self.status = 1
        self.libs = []
        self.error = ''
        self._parse()

    def _parse(self):
        parser = configparser.ConfigParser()
        try:
            parser.read(os.path.join(self.path, MANIFEST), encoding='utf-8')
        except Exception as error:
            self.error = str(error)
            return
        if not parser.has_section(SECTION):
            self.error = f"no [{SECTION}] section"
            return
        get = lambda key, fallback='': parser.get(SECTION, key,
                                                  fallback=fallback)
        self.name = _localised(get, 'name', self.id)
        self.description = _localised(get, 'description')
        self.author = get('author')
        self.version = get('version', '1.0')
        try:
            self.status = int(get('status', '1'))
        except ValueError:
            self.status = 1
        self.libs = [part.strip() for part in get('libs').split(',')
                     if part.strip()]

    @property
    def enabled(self):
        return self.status == 0

    def as_dict(self):
        return {'id': self.id, 'name': self.name,
                'description': self.description, 'author': self.author,
                'version': self.version, 'enabled': self.enabled,
                'path': self.path, 'error': self.error}


class SettingsUIAPI:
    """What a settings interface is handed.

    Everything an interface needs and nothing it does not: the settings as
    data, the ways to change and save them, and the few things every Titan
    window has to be able to do (speak, translate, know its parent).
    """

    def __init__(self, config, model, parent=None):
        self.config = config
        self.id = config.id
        self.path = config.path
        self.model = model
        self._parent = parent

    # -- the settings -----------------------------------------------------
    def categories(self):
        """Every category, with every setting on it, as plain data.

        `[{'name': 'General', 'items': [{'id', 'label', 'kind', 'value',
        'options', 'minimum', 'maximum', 'enabled', 'category'}, ...]}, ...]`
        - JSON-safe on purpose, so an interface can hand it straight to a web
        page or print it on a console.
        """
        return self.model.categories()

    def items(self):
        """Every setting, flattened - for an interface with no categories."""
        return [item.describe() for item in self.model.items()]

    def find(self, text):
        """The settings whose label or category matches what was typed."""
        return [item.describe() for item in self.model.find(text)]

    def get(self, item_id):
        return self.model.get(item_id)

    def set(self, item_id, value):
        """Change one setting.  Nothing is written until `save`."""
        return self.model.set(item_id, value)

    def press(self, item_id):
        """Press one of the settings that is a button (a dialog, a wizard)."""
        return self.model.press(item_id)

    def refresh(self):
        """Read the window again - after a save, or a category appearing."""
        self.model.read()
        return True

    def save(self):
        """Titan's own save: the ini file AND everything that hangs off it."""
        return self.model.save()

    def cancel(self):
        return self.model.cancel()

    # -- being a Titan window --------------------------------------------
    def call(self, function, *args, **kwargs):
        """Run something on the GUI thread and wait for its answer.

        The settings are wx controls, so reading and writing them off the
        GUI thread is undefined behaviour rather than an error you would
        see.  An interface that has a loop of its own - a console asking
        questions, a web server answering requests - lives on a thread of
        its own and reaches the settings through here.  Called from the GUI
        thread it simply calls, so an interface never has to ask which
        thread it is on.
        """
        import wx
        if wx.IsMainThread():
            return function(*args, **kwargs)
        import threading
        done = threading.Event()
        box = {}

        def run():
            try:
                box['value'] = function(*args, **kwargs)
            except Exception as error:
                box['error'] = error
            finally:
                done.set()

        wx.CallAfter(run)
        if not done.wait(20):
            raise TimeoutError("the GUI thread did not answer")
        if 'error' in box:
            raise box['error']
        return box.get('value')

    def parent(self):
        return self._parent

    def file(self, *parts):
        return os.path.join(self.path, *parts)

    def translate(self, text):
        from src.titan_core.translation import _
        return _(text)

    def language(self):
        return get_setting('language', 'pl')

    def speak(self, text, interrupt=True):
        try:
            from src.titan_core.sound import speak
            speak(text, interrupt=interrupt)
            return True
        except Exception:
            return False

    def open_builtin(self):
        """Open Titan's own settings window - the way back, always there."""
        return open_builtin_settings(self._parent)

    def log(self, message):
        print(f"[settings interface {self.id}] {message}")


class SettingsInterfaceManager:
    """Finds them, loads them, and opens the chosen one."""

    def __init__(self):
        self._configs = {}
        self._modules = {}
        self._scanned = False

    def scan(self, force=False):
        if self._scanned and not force:
            return self._configs
        configs = {}
        try:
            entries = _discover(INTERFACE_DIR)
        except Exception as error:
            print(f"[SettingsInterfaces] could not look: {error}")
            entries = {}
        for folder_name, path in entries.items():
            if not os.path.isfile(os.path.join(path, MANIFEST)):
                continue
            config = SettingsInterfaceConfig(path, folder_name)
            if config.error:
                print(f"[SettingsInterfaces] {folder_name}: {config.error}")
            configs[folder_name] = config
        self._configs = configs
        self._scanned = True
        return configs

    def configs(self):
        return list(self.scan().values())

    def available(self):
        """The ones the user may choose - enabled and readable."""
        return [config for config in self.configs()
                if config.enabled and not config.error]

    def config(self, interface_id):
        return self.scan().get(interface_id)

    def describe(self):
        return [config.as_dict() for config in self.configs()]

    # ------------------------------------------------------------------
    def chosen(self):
        """Which interface the user picked, or '' for Titan's own."""
        return str(get_setting(SETTING_KEY, '', SETTING_SECTION) or '').strip()

    def choose(self, interface_id):
        """Pick one - '' puts Titan's own window back."""
        interface_id = (interface_id or '').strip()
        if interface_id:
            config = self.config(interface_id)
            if config is None:
                return False, f"There is no settings interface '{interface_id}'."
            if not config.enabled:
                return False, f"'{config.name}' is switched off."
        set_setting(SETTING_KEY, interface_id, SETTING_SECTION)
        return True, interface_id

    def module(self, interface_id):
        if interface_id in self._modules:
            return self._modules[interface_id]
        config = self.config(interface_id)
        if config is None or not config.enabled:
            return None
        init_path = _init_file(config.path)
        if init_path is None:
            print(f"[SettingsInterfaces] {interface_id}: no init.py")
            return None
        module = _load_module(init_path, config)
        if module is None:
            return None
        self._modules[interface_id] = module
        return module


_manager = None


def manager():
    global _manager
    if _manager is None:
        _manager = SettingsInterfaceManager()
    return _manager


# --------------------------------------------------------------------------
# Opening the settings - the one way in, for the whole of Titan
# --------------------------------------------------------------------------
def settings_frame(parent=None, create=True):
    """Titan's own settings window, the one everything else registers into.

    It normally lives on the main window (`frame.settings_frame`), built a
    moment after Titan's own window is shown; a Titan started into Klango
    mode or a launcher may not have one yet, and then it is made here and
    put where the rest of Titan looks for it - never a second window that
    the components have not registered their categories into.
    """
    import wx
    frame = parent
    if frame is None or not hasattr(frame, 'settings_frame'):
        app = wx.GetApp()
        top = app.GetTopWindow() if app else None
        frame = top if top is not None and hasattr(top, 'settings_frame') \
            else frame
    existing = getattr(frame, 'settings_frame', None)
    if existing is not None:
        try:
            existing.GetTitle()
            return existing
        except RuntimeError:
            existing = None
    if not create:
        return None
    manager = getattr(frame, 'component_manager', None)         or component_manager(frame)
    try:
        from src.titan_core.translation import _
        from src.ui.settingsgui import SettingsFrame
        window = SettingsFrame(None, title=_("Settings"),
                               component_manager=manager)
    except Exception as error:
        print(f"[SettingsInterfaces] could not build the settings: {error}")
        import traceback
        traceback.print_exc()
        return None
    try:
        if frame is not None:
            frame.settings_frame = window
        if manager is not None:
            manager.settings_frame = window
            manager.register_component_settings()
            window.rebuild_category_list()
            window.load_component_settings()
    except Exception as error:
        print(f"[SettingsInterfaces] could not register categories: {error}")
    return window


def open_builtin_settings(parent=None):
    """Titan's own settings window, shown."""
    window = settings_frame(parent)
    if window is None:
        return None
    try:
        window.Show()
        window.Raise()
    except Exception as error:
        print(f"[SettingsInterfaces] could not show the settings: {error}")
        return None
    return window


def component_manager(frame=None):
    """The running `ComponentManager`, wherever it is to be found.

    Titan keeps it on its main window, and a Titan started into Klango mode
    or a launcher keeps it on the settings window instead.  Either is fine;
    what matters is that one is found, because it is what puts the
    components' own settings categories into the settings.
    """
    import wx
    candidates = [frame]
    try:
        app = wx.GetApp()
        candidates.append(app.GetTopWindow() if app else None)
        candidates.extend(wx.GetTopLevelWindows())
    except Exception:
        pass
    for candidate in candidates:
        manager = getattr(candidate, 'component_manager', None)
        if manager is not None:
            return manager
    return None


def ensure_component_categories(window, frame=None):
    """Make sure the components' own settings are IN the settings window.

    A component registers its category by being handed the window
    (`ComponentManager.register_settings_category`), and normally that has
    happened at startup.  It has NOT happened when the window was built
    without a component manager - which is what a Titan whose settings have
    never been opened in the classic way can look like - and then an
    interface reading the window would show Titan's own categories and
    silently miss every add-on's.  So it is asked for here, once: a
    settings interface must show exactly what the classic window shows.
    """
    manager = getattr(window, 'component_manager', None) or         component_manager(frame)
    if manager is None:
        return False
    try:
        window.component_manager = manager
        if getattr(manager, 'settings_frame', None) is not window:
            manager.settings_frame = window
        manager.register_component_settings()
        window.rebuild_category_list()
        return True
    except Exception as error:
        print(f"[SettingsInterfaces] could not register component "
              f"categories: {error}")
        return False


def build_model(parent=None):
    """The settings as data, without showing anything.

    The window is built if it does not exist - it has to, because it IS the
    description - but it is not shown: an interface that renders the
    settings its own way must not make Titan's window flash up first.
    """
    window = settings_frame(parent)
    if window is None:
        return None
    # The components' categories before anything is read, so an interface
    # gets the same list the classic window has - the AI's, the screen
    # reader's, the macro manager's and everything else installed.
    ensure_component_categories(window, parent)
    try:
        # The categories that come and go (the Game controller, the Titan
        # shell) are decided when the window is shown, so an interface that
        # never shows it has to ask for that here or it would list a
        # category the user cannot have.
        window.force_rebuild_categories()
        window.load_settings_to_ui()
        window.load_component_settings()
    except Exception as error:
        print(f"[SettingsInterfaces] could not refresh the settings: {error}")
    from src.settings.ui_model import SettingsModel
    try:
        return SettingsModel(window)
    except Exception as error:
        print(f"[SettingsInterfaces] could not read the settings: {error}")
        import traceback
        traceback.print_exc()
        return None


def open_settings(parent=None):
    """Open the settings - through whichever interface the user chose.

    This is the one entry point: the menu bar, the Invisible UI, Klango
    mode, the Start menu, the desktop's menu and the `titan.open_settings`
    action all come here, which is what makes choosing an interface mean
    anything.  Anything that goes wrong ends in Titan's own window, said
    plainly rather than silently.
    """
    chosen = manager().chosen()
    if not chosen:
        return open_builtin_settings(parent)

    config = manager().config(chosen)
    if config is None:
        print(f"[SettingsInterfaces] '{chosen}' is not installed any more")
        return open_builtin_settings(parent)
    if not config.enabled:
        print(f"[SettingsInterfaces] '{chosen}' is switched off")
        return open_builtin_settings(parent)

    module = manager().module(chosen)
    entry = getattr(module, 'open_settings', None) if module else None
    if not callable(entry):
        print(f"[SettingsInterfaces] '{chosen}' has no open_settings()")
        return open_builtin_settings(parent)

    model = build_model(parent)
    if model is None:
        return open_builtin_settings(parent)

    api = SettingsUIAPI(config, model, parent)
    try:
        result = entry(api)
    except Exception as error:
        print(f"[SettingsInterfaces] '{chosen}' failed: {error}")
        import traceback
        traceback.print_exc()
        return open_builtin_settings(parent)
    if result is None:
        # An interface that opened nothing has not opened the settings, and
        # the user pressed Settings.  Titan's own window is what they get.
        print(f"[SettingsInterfaces] '{chosen}' opened nothing")
        return open_builtin_settings(parent)
    return result


# --------------------------------------------------------------------------
def _init_file(path):
    candidates = [os.path.join(path, 'init.py'),
                  os.path.join(path, 'init.pyc')]
    existing = [name for name in candidates if os.path.isfile(name)]
    if len(existing) == 2:
        source, compiled = existing
        return compiled if (os.path.getmtime(compiled)
                            >= os.path.getmtime(source)) else source
    return existing[0] if existing else None


def _load_module(init_path, config):
    folder = os.path.dirname(init_path)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    for name in (config.libs or ['lib']):
        library = os.path.join(folder, name)
        if os.path.isdir(library) and library not in sys.path:
            sys.path.insert(0, library)
    module_name = f'settings_ui_{config.id}'
    try:
        if _is_frozen() and init_path.endswith('.py'):
            with open(init_path, 'r', encoding='utf-8') as handle:
                code = handle.read()
            module = types.ModuleType(module_name)
            module.__file__ = init_path
            module.__name__ = module_name
            exec(compile(code, init_path, 'exec'), module.__dict__)
            sys.modules[module_name] = module
            return module
        spec = importlib.util.spec_from_file_location(module_name, init_path)
        if spec is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception as error:
        print(f"[SettingsInterfaces] {config.id} failed to load: {error}")
        import traceback
        traceback.print_exc()
        return None

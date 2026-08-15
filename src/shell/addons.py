# -*- coding: utf-8 -*-
"""
Shell add-ons: the parts of the Titan shell somebody else wrote.

Titan's shell is the desktop, the taskbar, the notification area, the Start
menu and the file browser.  All five are Titan's own code, and until now
that was the whole list of what could be in them: a user who wanted one more
button on the bar, a column of their own in the file browser, an entry in
the desktop's menu - or their own Start menu entirely - had to change Titan.

Every other part of Titan already answers that with an add-on directory, so
this is the tenth one: `data/shell addons/`.  It deliberately copies what is
already here rather than inventing a tenth way of doing things:

- discovery is `platform_utils.discover_data_entries`, so a shell add-on may
  ship as a directory OR as a packaged `.TCD` file, exactly like the rest;
- the manifest is `__shell_addon__.TCE`, an INI with a `[shell addon]`
  section, `status = 0` meaning enabled - the component convention, so the
  same words mean the same thing in both files;
- the code is `init.py` (or `init.pyc`), loaded the way a launcher is;
- what an add-on hands back is a list of `{'id', 'label', 'action'}` dicts,
  which is what `src/ui/program_menu.py` already established as the shape of
  "a thing a menu can offer".

**Two kinds of add-on, and the difference matters.**

- A **contributor** adds to what is already there: entries in the Start
  menu, a menu or a toolbar button or a column in the file browser, items in
  the desktop's and the taskbar's context menus, a control in the
  notification area.  Any number may be installed and they all apply.
- A **provider** REPLACES one part of the shell - `provides = start_menu`
  or `provides = explorer` - and then Titan opens theirs instead of its own.
  One provider per part wins (the first enabled one, and the user picks
  which in the shell settings); everything else about the shell carries on
  as it was, because a provider replaces a WINDOW, not the shell.

**Nothing an add-on does may take the shell down.**  The shell owns the
appbar and the shell hook, so this process is what every other program's
broadcasts pass through - an exception escaping into a paint handler or a
menu build is not a broken add-on, it is a machine that has stopped
answering.  So every call out to an add-on goes through `_safe`, which
reports and carries on, and a contribution that is not the right shape is
skipped rather than believed.
"""

import configparser
import importlib.util
import os
import sys
import types

from src.platform_utils import (discover_data_entries as _discover,
                                is_frozen as _is_frozen)

# The directory, and the manifest inside it.  The space in the name is
# deliberate: `data/` already has "downloaded packages", "statusbar_applets"
# and "titantts engines", and this is the name the user asked for.
ADDON_DIR = 'shell addons'
MANIFEST = '__shell_addon__.TCE'
SECTION = 'shell addon'

# The parts of the shell an add-on can reach.  A manifest names the ones it
# touches so that a shell surface can ask only the add-ons that care.
SURFACES = ('shell', 'start_menu', 'explorer', 'taskbar', 'desktop')

# The parts an add-on can REPLACE outright.
PROVIDABLE = ('start_menu', 'explorer')


def _truthy(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


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


class ShellAddonConfig:
    """One `__shell_addon__.TCE`, parsed."""

    def __init__(self, path, folder_name):
        self.path = path
        self.id = folder_name
        self.name = folder_name
        self.description = ''
        self.author = ''
        self.version = '1.0'
        self.status = 1          # 1 = disabled, 0 = enabled (as components)
        self.surfaces = ()
        self.provides = ''
        self.libs = []
        self.error = ''
        self._parse()

    def _parse(self):
        config = configparser.ConfigParser()
        try:
            config.read(os.path.join(self.path, MANIFEST), encoding='utf-8')
        except Exception as error:
            self.error = str(error)
            return
        if not config.has_section(SECTION):
            self.error = f"no [{SECTION}] section"
            return
        get = lambda key, fallback='': config.get(SECTION, key,
                                                  fallback=fallback)
        self.name = _localised(get, 'name', self.id)
        self.description = _localised(get, 'description')
        self.author = get('author')
        self.version = get('version', '1.0')
        try:
            self.status = int(get('status', '1'))
        except ValueError:
            self.status = 1
        # `surfaces` is a help, not a gate: an add-on that names none is
        # asked about everything, because getting this wrong should mean a
        # slightly slower menu rather than an add-on that silently does
        # nothing.
        self.surfaces = tuple(
            part.strip() for part in get('surfaces').split(',') if part.strip())
        self.provides = get('provides').strip().lower()
        self.libs = [part.strip() for part in get('libs').split(',')
                     if part.strip()]

    @property
    def enabled(self):
        return self.status == 0

    def touches(self, surface):
        return not self.surfaces or surface in self.surfaces

    def as_dict(self):
        return {'id': self.id, 'name': self.name,
                'description': self.description, 'author': self.author,
                'version': self.version, 'enabled': self.enabled,
                'surfaces': list(self.surfaces) or list(SURFACES),
                'provides': self.provides, 'path': self.path,
                'error': self.error}


class ShellAddon:
    """A loaded add-on: its manifest, its module, and its API object."""

    def __init__(self, config, module, api):
        self.config = config
        self.module = module
        self.api = api

    @property
    def id(self):
        return self.config.id

    def hook(self, name):
        function = getattr(self.module, name, None)
        return function if callable(function) else None


class ShellAddonAPI:
    """What an add-on is handed, and the only thing it needs to import.

    Deliberately small and stable: the add-on is given the shell it is part
    of, the way to ask Titan to do something, and the ways to say something
    to the user.  Everything else it wants, it reaches through the Titan
    Action API - which is how an add-on gets at the rest of Titan without
    this file growing a method per subsystem.
    """

    def __init__(self, config, manager):
        self.config = config
        self.id = config.id
        self.path = config.path
        self._manager = manager

    # -- where it lives ------------------------------------------------
    def file(self, *parts):
        """A path inside the add-on's own folder."""
        return os.path.join(self.path, *parts)

    def shell(self):
        """The running `TitanShell`, or None when the shell is not up."""
        try:
            from src.shell import shell_manager
            return shell_manager.get_shell()
        except Exception:
            return None

    def window(self, name):
        """One of the shell's windows ('desktop', 'taskbar', 'start_menu')."""
        shell = self.shell()
        return shell.window(name) if shell is not None else None

    # -- doing things ---------------------------------------------------
    def run_action(self, addon, action, **params):
        """Any Titan action, by the names `actions.list_addons()` gives."""
        from src.titan_core import actions
        return actions.run(addon, action, **params)

    def setting(self, key, default=None, section=None):
        """A setting of the add-on's own (its id is the section by default)."""
        from src.settings.settings import get_setting
        return get_setting(key, default, section or f'shell_addon_{self.id}')

    def set_setting(self, key, value, section=None):
        from src.settings.settings import set_setting
        set_setting(key, value, section or f'shell_addon_{self.id}')

    # -- saying things ---------------------------------------------------
    def speak(self, text, interrupt=True):
        """Say something through Titan's own speech.

        Note what the shell itself never does: the shell does not speak,
        because a screen reader is already reading it.  An add-on may - it
        is not the system interface, it is a program the user installed -
        but it should ask itself whether the reader has not said this
        already.
        """
        try:
            from src.titan_core.sound import speak
            speak(text, interrupt=interrupt)
            return True
        except Exception as error:
            print(f"[shell addon {self.id}] could not speak: {error}")
            return False

    def sound(self, name):
        """One of the shell's own sounds, by name (see `a11y.shell_sound`)."""
        try:
            from src.shell.a11y import shell_sound
            shell_sound(name)
            return True
        except Exception:
            return False

    def log(self, message):
        print(f"[shell addon {self.id}] {message}")


class ShellAddonManager:
    """Finds them, loads them, and asks them - safely."""

    def __init__(self):
        self._configs = {}     # id -> ShellAddonConfig
        self._loaded = {}      # id -> ShellAddon
        self._scanned = False

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def scan(self, force=False):
        """Read every manifest under `data/shell addons/` (both roots)."""
        if self._scanned and not force:
            return self._configs
        configs = {}
        try:
            entries = _discover(ADDON_DIR)
        except Exception as error:
            print(f"[ShellAddons] could not look for add-ons: {error}")
            entries = {}
        for folder_name, path in entries.items():
            if not os.path.isfile(os.path.join(path, MANIFEST)):
                continue
            config = ShellAddonConfig(path, folder_name)
            if config.error:
                print(f"[ShellAddons] {folder_name}: {config.error}")
            configs[folder_name] = config
        self._configs = configs
        self._scanned = True
        return configs

    def configs(self):
        return list(self.scan().values())

    def config(self, addon_id):
        return self.scan().get(addon_id)

    def describe(self):
        return [config.as_dict() for config in self.configs()]

    def set_enabled(self, addon_id, enabled):
        """Tick or untick one, in its own manifest, as a component does."""
        config = self.config(addon_id)
        if config is None:
            return False
        parser = configparser.ConfigParser()
        manifest = os.path.join(config.path, MANIFEST)
        try:
            parser.read(manifest, encoding='utf-8')
            if not parser.has_section(SECTION):
                parser.add_section(SECTION)
            parser.set(SECTION, 'status', '0' if enabled else '1')
            with open(manifest, 'w', encoding='utf-8') as handle:
                parser.write(handle)
        except Exception as error:
            print(f"[ShellAddons] could not write {manifest}: {error}")
            return False
        config.status = 0 if enabled else 1
        if not enabled:
            self._unload(addon_id)
        return True

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_all(self):
        """Load every enabled add-on.  Called when the shell starts."""
        loaded = []
        for config in self.configs():
            if not config.enabled:
                continue
            addon = self.load(config.id)
            if addon is not None:
                loaded.append(addon)
        return loaded

    def load(self, addon_id):
        """Load one, or hand back the one already loaded."""
        if addon_id in self._loaded:
            return self._loaded[addon_id]
        config = self.config(addon_id)
        if config is None or not config.enabled:
            return None
        init_path = self._init_file(config.path)
        if init_path is None:
            print(f"[ShellAddons] {addon_id}: no init.py")
            return None
        module = self._load_module(init_path, config)
        if module is None:
            return None
        api = ShellAddonAPI(config, self)
        addon = ShellAddon(config, module, api)
        self._loaded[addon_id] = addon
        # `setup` is the add-on's chance to do work once, before any surface
        # asks it for anything.
        setup = addon.hook('setup')
        if setup is not None:
            _safe(addon, 'setup', setup, api)
        print(f"[ShellAddons] loaded {config.name} ({addon_id})")
        return addon

    def _unload(self, addon_id):
        addon = self._loaded.pop(addon_id, None)
        if addon is None:
            return False
        teardown = addon.hook('teardown')
        if teardown is not None:
            _safe(addon, 'teardown', teardown, addon.api)
        return True

    def unload_all(self):
        for addon_id in list(self._loaded):
            self._unload(addon_id)

    @staticmethod
    def _init_file(path):
        candidates = [os.path.join(path, 'init.py'),
                      os.path.join(path, 'init.pyc')]
        existing = [name for name in candidates if os.path.isfile(name)]
        if len(existing) == 2:
            source, compiled = existing
            return compiled if (os.path.getmtime(compiled)
                                >= os.path.getmtime(source)) else source
        return existing[0] if existing else None

    @staticmethod
    def _load_module(init_path, config):
        """Load the add-on's code, the way a launcher's is loaded."""
        folder = os.path.dirname(init_path)
        if folder not in sys.path:
            sys.path.insert(0, folder)
        for name in (config.libs or ['lib']):
            library = os.path.join(folder, name)
            if os.path.isdir(library) and library not in sys.path:
                sys.path.insert(0, library)
        module_name = f'shell_addon_{config.id}'
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
            spec = importlib.util.spec_from_file_location(module_name,
                                                          init_path)
            if spec is None:
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception as error:
            print(f"[ShellAddons] {config.id} failed to load: {error}")
            import traceback
            traceback.print_exc()
            return None

    # ------------------------------------------------------------------
    # Asking them
    # ------------------------------------------------------------------
    def active(self, surface=None):
        """The loaded add-ons, in manifest order, that touch this surface."""
        addons = []
        for config in self.configs():
            if not config.enabled:
                continue
            if surface is not None and not config.touches(surface):
                continue
            addon = self.load(config.id)
            if addon is not None:
                addons.append(addon)
        return addons

    def collect(self, surface, hook, *args, **kwargs):
        """Every add-on's answer to one hook, flattened and checked.

        A hook that is missing, that fails, or that answers with something
        that is not a list of entries contributes nothing - the surface asks
        and carries on, which is the whole reason a shell can have add-ons
        at all.
        """
        entries = []
        for addon in self.active(surface):
            function = addon.hook(hook)
            if function is None:
                continue
            answer = _safe(addon, hook, function, addon.api, *args, **kwargs)
            for entry in _entries(answer, addon):
                entries.append(entry)
        return entries

    def notify(self, surface, hook, *args, **kwargs):
        """Tell every add-on something happened; keep no answer."""
        count = 0
        for addon in self.active(surface):
            function = addon.hook(hook)
            if function is None:
                continue
            _safe(addon, hook, function, addon.api, *args, **kwargs)
            count += 1
        return count

    def provider(self, part):
        """The add-on that replaces this part of the shell, if any.

        The user's choice wins (`titan_shell/provider_<part>`); with nothing
        chosen, the first enabled add-on that offers it - except where
        Titan has a chooser of its own, and the Start menu does: the
        taskbar properties sheet lists every installed one beside Titan's
        two, and `shell_manager` asks here only once the user has picked
        one there.  An add-on that says it provides something but has no
        function for it is not a provider - the manifest is a claim, the
        module is the evidence.
        """
        if part not in PROVIDABLE:
            return None
        from src.settings.settings import get_setting
        chosen = str(get_setting(f'provider_{part}', '', 'titan_shell') or '')
        hook = f'open_{part}'
        candidates = []
        for config in self.configs():
            if not config.enabled or config.provides != part:
                continue
            addon = self.load(config.id)
            if addon is None or addon.hook(hook) is None:
                continue
            candidates.append(addon)
        if chosen:
            for addon in candidates:
                if addon.id == chosen:
                    return addon
            # A chosen provider that is no longer installed means Titan's
            # own part, not somebody else's - silently promoting a different
            # add-on to "your Start menu" is not a decision to make for the
            # user.
            return None
        return candidates[0] if candidates else None

    def providers(self, part):
        """Every add-on offering to replace this part, for the settings UI."""
        return [addon.config for addon in self.active(part)
                if addon.config.provides == part
                and addon.hook(f'open_{part}') is not None]


def _safe(addon, what, function, *args, **kwargs):
    """Call into an add-on and never let it out."""
    try:
        return function(*args, **kwargs)
    except Exception as error:
        print(f"[ShellAddons] {addon.id}.{what} failed: {error}")
        import traceback
        traceback.print_exc()
        return None


def _entries(answer, addon):
    """Whatever an add-on answered, as entries this shell can use.

    An entry is `{'id', 'label', 'action'}` - the shape `program_menu` uses -
    plus whatever the surface itself understands (`where`, `column`,
    `control`).  Anything without a label or an action is dropped, because a
    menu item with no words is a menu item a screen reader cannot read and
    one with nothing to do is a lie.
    """
    if not answer:
        return []
    if isinstance(answer, dict):
        answer = [answer]
    if not isinstance(answer, (list, tuple)):
        print(f"[ShellAddons] {addon.id} answered {type(answer).__name__}, "
              f"which is not a list of entries")
        return []
    entries = []
    for item in answer:
        if not isinstance(item, dict):
            print(f"[ShellAddons] {addon.id} contributed a "
                  f"{type(item).__name__}, not an entry")
            continue
        label = item.get('label')
        # Three shapes are real, and each is its own evidence: something to
        # DO (an action), something to SHOW (a control - a taskbar band, an
        # Explorer column), or something to OPEN (children - a Start menu
        # branch, whose entries do the doing).  Anything else is a menu item
        # with no words or nothing behind it.
        substance = (callable(item.get('action')) or item.get('control')
                     or item.get('children') is not None
                     or callable(item.get('value')))
        if not item.get('control') and (not label or not substance):
            print(f"[ShellAddons] {addon.id} contributed an entry with "
                  f"no label or nothing behind it: {item!r}")
            continue
        entry = dict(item)
        entry.setdefault('id', f"{addon.id}_{len(entries)}")
        entry['addon'] = addon.id
        entry['addon_name'] = addon.config.name
        entries.append(entry)
    return entries


# --------------------------------------------------------------------------
# The one manager
# --------------------------------------------------------------------------
_manager = None


def manager():
    global _manager
    if _manager is None:
        _manager = ShellAddonManager()
    return _manager


def collect(surface, hook, *args, **kwargs):
    """Shorthand: every add-on's contribution to one surface."""
    try:
        return manager().collect(surface, hook, *args, **kwargs)
    except Exception as error:
        print(f"[ShellAddons] could not collect {hook}: {error}")
        return []


def notify(surface, hook, *args, **kwargs):
    try:
        return manager().notify(surface, hook, *args, **kwargs)
    except Exception as error:
        print(f"[ShellAddons] could not notify {hook}: {error}")
        return 0


def provider(part):
    try:
        return manager().provider(part)
    except Exception as error:
        print(f"[ShellAddons] could not resolve a {part} provider: {error}")
        return None


def add_to_menu(menu, entries, bind_to=None, separator=True):
    """Put contributed entries at the end of a `wx.Menu`.

    Every shell menu that can be added to goes through this, so the rule is
    written once: the add-ons' entries come after the shell's own, behind a
    separator, and a broken action cannot escape into wx's event loop.
    """
    import wx
    if not entries:
        return 0
    if separator and menu.GetMenuItemCount():
        menu.AppendSeparator()
    binder = bind_to if bind_to is not None else menu
    added = 0
    for entry in entries:
        item = menu.Append(wx.ID_ANY, str(entry.get('label', '')))
        action = entry.get('action')
        name = f"{entry.get('addon')}.{entry.get('id')}"

        def run(event, action=action, name=name):
            try:
                action()
            except Exception as error:
                print(f"[ShellAddons] {name} failed: {error}")
                import traceback
                traceback.print_exc()

        binder.Bind(wx.EVT_MENU, run, item)
        added += 1
    return added

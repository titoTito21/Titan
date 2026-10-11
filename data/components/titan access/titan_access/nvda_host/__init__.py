# -*- coding: utf-8 -*-
"""NVDA add-ons, installed in and run by Titan Access.

An NVDA add-on is a ``.nvda-addon`` file (a zip with a ``manifest.ini``)
whose code is written against NVDA's own modules. Titan Access installs it
into the user's own folder (``accessibility/nvda_addons/<name>``) and runs
it on stand-ins for those modules (`shims`), served only to the add-on's
code (`importer`). What an add-on can bring:

* **synthesizers** (``synthDrivers``) - EXTERNAL SYNTHESIS, a subsystem of
  the reader the user chooses in its speech system dialog. It never
  becomes one of Titan's own TTS engines: Titan is not changed by an
  add-on;
* **global plugins** (``globalPlugins``) - their scripts bound to their
  keys (``kb:NVDA+j`` is the reader modifier and J), their events
  (``event_gainFocus`` and friends, with ``nextHandler``);
* **app modules** (``appModules``) - the same, for one program, loaded
  when that program comes to the front;
* data-only add-ons (an RHVoice voice) - present, so the add-on that reads
  them finds them through ``addonHandler.getRunningAddons()``.

Braille display drivers and vision providers are listed and not loaded.
Nothing here is Windows-only except what an add-on itself ships (a DLL):
the host, the stand-ins and the scripts run wherever Titan Access runs.
"""

import configparser
import io
import json
import os
import shutil
import sys
import threading
import time
import types
import zipfile

_LOCK = threading.RLock()

#: NVDA's own add-on for Titan, which IS Titan Access's shared code: never
#: migrated or loaded, or the reader would run inside itself.
SKIP = frozenset({'titanEnhancements'})

#: The packages an add-on's code lives in, and which of them are loaded.
LOADED_KINDS = ('globalPlugins', 'appModules', 'synthDrivers')
LISTED_KINDS = ('brailleDisplayDrivers', 'visionEnhancementProviders')

_state = {'loaded': False, 'plugins': [], 'app_modules': {},
          'app_module_classes': {}, 'synths': None, 'errors': {},
          'synth': None, 'synth_name': '', 'events': 0, 'scripts': 0,
          'engine': None}


# --------------------------------------------------------------------------- #
# Where they live
# --------------------------------------------------------------------------- #
def _home():
    try:
        from titan_access.portable import readerHome
        return readerHome.folder()
    except Exception:                                # noqa: BLE001
        return os.path.join(os.getenv('APPDATA') or os.path.expanduser('~'),
                            'titosoft', 'Titan', 'accessibility')


def folder():
    where = os.path.join(_home(), 'nvda_addons')
    os.makedirs(where, exist_ok=True)
    return where


def config_folder():
    """What NVDA calls its configuration path, for an add-on in Titan
    Access: a folder of its own in the user's data."""
    where = os.path.join(_home(), 'nvda_config')
    os.makedirs(where, exist_ok=True)
    return where


def _state_path():
    return os.path.join(folder(), 'state.json')


def _read_state():
    try:
        with open(_state_path(), 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:                                # noqa: BLE001
        return {}


def _write_state(found):
    try:
        with open(_state_path(), 'w', encoding='utf-8') as handle:
            json.dump(found, handle, ensure_ascii=False, indent=1)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Manifests
# --------------------------------------------------------------------------- #
def parse_manifest(text):
    """An NVDA ``manifest.ini`` - key = value, values quoted with " or
    \"\"\" for several lines."""
    found = {}
    lines = str(text or '').splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if '=' not in line or line.strip().startswith(('#', '[')):
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if value.startswith('"""'):
            body = value[3:]
            while '"""' not in body and index < len(lines):
                body += '\n' + lines[index]
                index += 1
            value = body.split('"""', 1)[0]
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        found[key] = value
    return found


def _manifest_of(path):
    try:
        with open(os.path.join(path, 'manifest.ini'), 'r',
                  encoding='utf-8-sig') as handle:
            return parse_manifest(handle.read())
    except OSError:
        return None


def installed():
    """``[record]`` - every add-on installed in Titan Access."""
    disabled = set(_read_state().get('disabled', []))
    found = []
    root = folder()
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        manifest = _manifest_of(path)
        if manifest is None:
            continue
        kinds = [kind for kind in LOADED_KINDS + LISTED_KINDS
                 if os.path.isdir(os.path.join(path, kind))]
        found.append({'name': manifest.get('name', name), 'folder': name,
                      'path': path, 'manifest': manifest, 'kinds': kinds,
                      'summary': manifest.get('summary', name),
                      'version': manifest.get('version', ''),
                      'enabled': manifest.get('name', name) not in disabled})
    return found


def by_name(name):
    wanted = str(name or '').lower()
    for record in installed():
        if record['name'].lower() == wanted or \
                record['folder'].lower() == wanted:
            return record
    return None


# --------------------------------------------------------------------------- #
# Installing
# --------------------------------------------------------------------------- #
def install(path):
    """Install a ``.nvda-addon`` file (or an add-on folder) into Titan
    Access. ``(ok, sentence)``. An add-on of the same name is replaced."""
    path = str(path or '')
    try:
        if os.path.isdir(path):
            manifest = _manifest_of(path)
            if manifest is None:
                return False, 'there is no manifest.ini in that folder'
            name = manifest.get('name', os.path.basename(path))
            target = os.path.join(folder(), name)
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(path, target, ignore=shutil.ignore_patterns(
                '__pycache__', '*.pyc'))
            return True, name
        with zipfile.ZipFile(path) as archive:
            try:
                text = archive.read('manifest.ini').decode('utf-8-sig')
            except KeyError:
                return False, 'that file has no manifest.ini - not an NVDA ' \
                              'add-on'
            manifest = parse_manifest(text)
            name = manifest.get('name')
            if not name:
                return False, 'the manifest names no add-on'
            target = os.path.join(folder(), name)
            if os.path.isdir(target):
                shutil.rmtree(target)
            os.makedirs(target)
            for member in archive.infolist():
                destination = os.path.normpath(os.path.join(
                    target, member.filename))
                if not destination.startswith(os.path.normpath(target)):
                    continue                 # a path leaving the folder
                if member.is_dir():
                    os.makedirs(destination, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                with archive.open(member) as source, \
                        open(destination, 'wb') as out:
                    shutil.copyfileobj(source, out)
        _forget_synths()
        return True, name
    except (OSError, zipfile.BadZipFile) as error:
        return False, str(error)


def remove(name):
    record = by_name(name)
    if record is None:
        return False
    shutil.rmtree(record['path'], ignore_errors=True)
    _forget_synths()
    return True


def set_enabled(name, on):
    record = by_name(name)
    if record is None:
        return False
    state = _read_state()
    disabled = set(state.get('disabled', []))
    if on:
        disabled.discard(record['name'])
    else:
        disabled.add(record['name'])
    state['disabled'] = sorted(disabled)
    _write_state(state)
    _forget_synths()
    return True


# --------------------------------------------------------------------------- #
# NVDA's own add-ons, brought over
# --------------------------------------------------------------------------- #
def nvda_addons_folder():
    """Where an installed NVDA keeps the user's add-ons, or ''."""
    base = os.getenv('APPDATA')
    candidates = []
    if base:
        candidates.append(os.path.join(base, 'nvda', 'addons'))
    candidates.append(os.path.join(os.path.expanduser('~'), '.nvda',
                                   'addons'))
    for one in candidates:
        if os.path.isdir(one):
            return one
    return ''


def migratable():
    """The NVDA add-ons that could be brought over: ``[(name, path)]``."""
    root = nvda_addons_folder()
    if not root:
        return []
    found = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path) or name.endswith(('.pendingInstall',
                                                      '.delete')):
            continue
        manifest = _manifest_of(path)
        if manifest is None or manifest.get('name', name) in SKIP:
            continue
        found.append((manifest.get('name', name), path))
    return found


def _nvda_config_folder():
    root = nvda_addons_folder()
    return os.path.dirname(root) if root else ''


#: What NVDA keeps in its configuration folder for itself, never brought.
NVDA_OWN = frozenset({'addons', 'addonstore', 'profiles', 'speechdicts',
                      'updates', 'nvda.ini', 'guistate.ini',
                      'addonsstate.json', 'updatecheckstate.pickle',
                      'scratchpad', 'nvda.log', 'nvda-old.log'})


def _names_of(record):
    """The add-on's name and every synthesizer and plugin it brings - what
    its data in NVDA's configuration folder is named after."""
    names = {record['name']}
    for kind in LOADED_KINDS:
        path = os.path.join(record['path'], kind)
        if os.path.isdir(path):
            names.update(_modules_in([path]))
    return {name for name in names if name}


def _migrate_data(record):
    """NVDA's configuration folder holds what an add-on downloaded or
    configured - RHVoice-config, samsungGalaxyVoices' voices, CerenceTTS -
    named after it; brought to Titan Access's own configuration folder."""
    source_root = _nvda_config_folder()
    if not source_root:
        return []
    names = [name.lower() for name in _names_of(record)]
    copied = []
    for entry in os.listdir(source_root):
        lowered = entry.lower()
        if lowered in NVDA_OWN or not any(lowered.startswith(name)
                                          for name in names):
            continue
        source = os.path.join(source_root, entry)
        target = os.path.join(config_folder(), entry)
        try:
            if os.path.isdir(source):
                if os.path.isdir(target):
                    shutil.rmtree(target)
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            copied.append(entry)
        except OSError:
            continue
    return copied


def bring_missing_data(records=None):
    """What NVDA's configuration folder holds for an installed add-on and
    Titan Access's has not got, copied in - file by file, never over
    anything that is already here.

    Migration copies it once, at the moment it is asked; an add-on whose
    own code ran first (and made an empty folder of its own - Samsung
    Galaxy Voices writes its settings.json on import) or whose voices were
    downloaded in NVDA afterwards was left with a folder that has no
    voices, and its synthesizer then answered ``check()`` with False: "it
    cannot run here". Run at every load, it costs one directory walk."""
    source_root = _nvda_config_folder()
    if not source_root or not os.path.isdir(source_root):
        return []
    if records is None:
        records = [record for record in installed() if record['enabled']]
    names = set()
    for record in records:
        names.update(name.lower() for name in _names_of(record))
    brought = []
    try:
        entries = os.listdir(source_root)
    except OSError:
        return []
    for entry in entries:
        lowered = entry.lower()
        if lowered in NVDA_OWN or not any(lowered.startswith(name)
                                          for name in names):
            continue
        source = os.path.join(source_root, entry)
        target = os.path.join(config_folder(), entry)
        if os.path.isfile(source):
            if not os.path.exists(target):
                try:
                    shutil.copy2(source, target)
                    brought.append(entry)
                except OSError:
                    pass
            continue
        for here, _dirs, files in os.walk(source):
            relative = os.path.relpath(here, source)
            there = os.path.normpath(os.path.join(target, relative))
            for name in files:
                wanted = os.path.join(there, name)
                if os.path.exists(wanted):
                    continue
                try:
                    os.makedirs(there, exist_ok=True)
                    shutil.copy2(os.path.join(here, name), wanted)
                    brought.append(os.path.join(entry, relative, name))
                except OSError:
                    continue
    return brought


def _migrate_settings(records):
    """The add-ons' own sections of NVDA's nvda.ini - a synthesizer's
    under [speech], a plugin's at the top - into Titan Access's."""
    path = os.path.join(_nvda_config_folder(), 'nvda.ini')
    if not os.path.isfile(path):
        return []
    try:
        from titan_access import local_model
        local_model._use_own_libraries()
        from configobj import ConfigObj
        ini = ConfigObj(path, encoding='utf-8')
    except Exception:                                # noqa: BLE001
        return []
    from .shims import config
    names = set()
    for record in records:
        names.update(_names_of(record))
    brought = []
    for name in names:
        for parent, key in ((ini.get('speech', {}), name), (ini, name)):
            section = parent.get(key) if hasattr(parent, 'get') else None
            if not isinstance(section, dict):
                continue
            target = config.conf['speech'] if parent is not ini else config.conf
            target[key] = dict(section)
            brought.append(key)
    if brought:
        config.save()
    return brought


def migrate():
    """Copy every NVDA add-on into Titan Access - the add-on, what it keeps
    in NVDA's configuration folder, and its settings. ``[(name, ok, why)]``."""
    done = []
    records = []
    for name, path in migratable():
        ok, why = install(path)
        done.append((name, ok, '' if ok else why))
        record = by_name(name) if ok else None
        if record is not None:
            records.append(record)
            _migrate_data(record)
    _migrate_settings(records)
    state = _read_state()
    state['migration_asked'] = True
    _write_state(state)
    return done


def migration_wanted():
    """Whether the first-run question should be asked: NVDA has add-ons
    and the user has not been asked."""
    return bool(migratable()) and not _read_state().get('migration_asked')


def ask_about_migration():
    """The first time: "Migrate your NVDA add-ons into Titan Access?" -
    a real dialog, on the GUI thread; answered once, either way."""
    if not migration_wanted():
        return False
    names = [name for name, _path in migratable()]
    try:
        import wx
    except Exception:                                # noqa: BLE001
        return False
    from titan_access.localization import L

    def ask():
        text = L('nvdaHost.migrate.question').format(
            count=len(names), names=', '.join(names))
        answer = wx.MessageBox(text, L('nvdaHost.migrate.title'),
                               wx.YES_NO | wx.ICON_QUESTION)
        state = _read_state()
        state['migration_asked'] = True
        _write_state(state)
        if answer == wx.YES:
            done = migrate()
            good = [name for name, ok, _why in done if ok]
            _say(L('nvdaHost.migrate.done').format(count=len(good)))
            reload()
    wx.CallAfter(ask)
    return True


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _package(kind):
    """The add-on package ``kind`` (synthDrivers, ...) as one namespace
    across every enabled add-on."""
    paths = [os.path.join(record['path'], kind) for record in installed()
             if record['enabled'] and os.path.isdir(os.path.join(
                 record['path'], kind))]
    module = sys.modules.get(kind)
    if module is None or not hasattr(module, '__titan_nvda_host__'):
        module = types.ModuleType(kind)
        module.__titan_nvda_host__ = True
        sys.modules[kind] = module
    module.__path__ = paths
    return module, paths


def _modules_in(paths):
    names = []
    for path in paths:
        for entry in sorted(os.listdir(path)):
            if entry.startswith(('_', '.')):
                continue
            full = os.path.join(path, entry)
            if entry.endswith('.py'):
                names.append(entry[:-3])
            elif os.path.isdir(full) and os.path.isfile(
                    os.path.join(full, '__init__.py')):
                names.append(entry)
    return names


def _import(kind, name):
    import importlib
    try:
        return importlib.import_module('%s.%s' % (kind, name)), ''
    except BaseException as error:                   # noqa: BLE001
        why = '%s: %s' % (type(error).__name__, error)
        with _LOCK:
            _state['errors']['%s.%s' % (kind, name)] = why
        return None, why


def load(engine=None):
    """Install the import hook and start every enabled add-on's global
    plugins. Synthesizers and app modules are loaded when needed."""
    from . import importer
    with _LOCK:
        _state['engine'] = engine
        _state['errors'] = {}
    # NVDA ships libraries its add-ons import (configobj, for one); Titan
    # Access keeps its own copies in its folder (`lib/python/<platform>`).
    try:
        from titan_access import local_model
        local_model._use_own_libraries()
    except Exception:                                # noqa: BLE001
        pass
    try:
        bring_missing_data()
    except Exception:                                # noqa: BLE001
        pass
    importer.install([folder()])
    for kind in LOADED_KINDS:
        _package(kind)
    plugins = []
    _module, paths = _package('globalPlugins')
    for name in _modules_in(paths):
        module, _why = _import('globalPlugins', name)
        cls = getattr(module, 'GlobalPlugin', None) if module else None
        if cls is None:
            continue
        try:
            plugins.append(cls())
        except BaseException as error:               # noqa: BLE001
            with _LOCK:
                _state['errors']['globalPlugins.%s' % name] = \
                    '%s: %s' % (type(error).__name__, error)
    _module, paths = _package('appModules')
    classes = {name.lower(): name for name in _modules_in(paths)}
    with _LOCK:
        _state['plugins'] = plugins
        _state['app_module_classes'] = classes
        _state['app_modules'] = {}
        _state['loaded'] = True
    return plugins


def is_loaded():
    return bool(_state['loaded'])


def unload():
    with _LOCK:
        plugins, _state['plugins'] = _state['plugins'], []
        modules = list(_state['app_modules'].values())
        _state['app_modules'] = {}
        synth, _state['synth'] = _state['synth'], None
        running = list(_state.get('running', {}).values())
        _state['running'] = __import__('collections').OrderedDict()
        _state['loaded'] = False
    for one in plugins + [m for m in modules if m is not None]:
        try:
            one.terminate()
        except BaseException:                        # noqa: BLE001
            pass
    seen = set()
    for one in ([synth] if synth is not None else []) + running:
        if id(one) in seen:
            continue
        seen.add(id(one))
        try:
            one.terminate()
        except BaseException:                        # noqa: BLE001
            pass
    _cancel_addon_timers()


def _cancel_addon_timers():
    """Every `threading.Timer` an add-on started and did not cancel in its
    `terminate` - stopped. Measured: two `SignedWebUpdater._automaticCheck`
    timers (a day long, an add-on's own update check) were still waiting
    after the reader had been switched off. In NVDA they die with NVDA;
    here they would live as long as Titan does. Only a timer whose
    function's code is inside the add-ons folder is touched."""
    try:
        root = os.path.normcase(os.path.abspath(folder()))
    except Exception:                                # noqa: BLE001
        return 0
    cancelled = 0
    for thread in threading.enumerate():
        if not isinstance(thread, threading.Timer):
            continue
        function = getattr(thread, 'function', None)
        code = getattr(getattr(function, '__func__', function), '__code__', None)
        where = getattr(code, 'co_filename', '') or ''
        try:
            inside = os.path.normcase(os.path.abspath(where)).startswith(root)
        except Exception:                            # noqa: BLE001
            inside = False
        if inside:
            try:
                thread.cancel()
                cancelled += 1
            except Exception:                        # noqa: BLE001
                pass
    return cancelled


def reload():
    engine = _state.get('engine')
    unload()
    _forget_synths()
    return load(engine)


# --------------------------------------------------------------------------- #
# App modules
# --------------------------------------------------------------------------- #
def _program_of(obj):
    pid = int(getattr(obj, 'processID', 0) or getattr(obj, 'process_id', 0)
              or 0)
    if not pid:
        return 0, ''
    from .shims.appModuleHandler import getAppNameFromProcessID
    return pid, getAppNameFromProcessID(pid)


def app_module_for(obj):
    pid, name = _program_of(obj)
    if not name:
        return None
    with _LOCK:
        if pid in _state['app_modules']:
            return _state['app_modules'][pid]
        module_name = _state['app_module_classes'].get(name)
    instance = None
    if module_name:
        module, _why = _import('appModules', module_name)
        cls = getattr(module, 'AppModule', None) if module else None
        if cls is not None:
            try:
                instance = cls(pid, name)
            except BaseException as error:           # noqa: BLE001
                with _LOCK:
                    _state['errors']['appModules.%s' % module_name] = \
                        '%s: %s' % (type(error).__name__, error)
    with _LOCK:
        _state['app_modules'][pid] = instance
    return instance


# --------------------------------------------------------------------------- #
# Events: NVDA's chain, with nextHandler
# --------------------------------------------------------------------------- #
def fire_event(name, obj):
    """``event_<name>`` through the app module and every global plugin,
    each passing on with ``nextHandler``. True when the chain reached the
    end - the reader's own handling should go on."""
    if not _state['loaded']:
        return True
    try:
        from titan_access import nvda_shape
        adapted = obj if hasattr(obj, 'original') else nvda_shape.adapt(obj)
    except Exception:                                # noqa: BLE001
        adapted = obj
    handlers = []
    module = app_module_for(adapted)
    for owner in [module] + list(_state['plugins']):
        method = getattr(owner, 'event_' + name, None) if owner else None
        if callable(method):
            handlers.append(method)
    if not handlers:
        return True
    reached = {'end': False}

    def chain(index):
        if index >= len(handlers):
            reached['end'] = True
            return
        try:
            handlers[index](adapted, lambda: chain(index + 1))
        except BaseException as error:               # noqa: BLE001
            with _LOCK:
                _state['errors']['event_' + name] = \
                    '%s: %s' % (type(error).__name__, error)
            chain(index + 1)
    with _LOCK:
        _state['events'] += 1
    chain(0)
    return reached['end']


# --------------------------------------------------------------------------- #
# Keys: NVDA's gesture identifiers
# --------------------------------------------------------------------------- #
class _Gesture(object):
    def __init__(self, identifier, send):
        from .shims.inputCore import normalizeGestureIdentifier
        self.identifiers = (identifier,)
        self.normalizedIdentifiers = [normalizeGestureIdentifier(identifier)]
        self._send = send
        self.mainKeyName = identifier.rsplit('+', 1)[-1].split(':')[-1]
        self.modifierNames = identifier.split(':', 1)[-1].split('+')[:-1]
        self.displayName = identifier
        self.isModifier = False

    def send(self):
        if self._send is not None:
            self._send()


def identifier_of(key, ctrl=False, alt=False, shift=False, reader=False):
    parts = []
    if reader:
        parts.append('nvda')
    if ctrl:
        parts.append('control')
    if alt:
        parts.append('alt')
    if shift:
        parts.append('shift')
    key = {'return': 'enter', 'numpadenter': 'numpadEnter',
           'up': 'upArrow', 'down': 'downArrow', 'left': 'leftArrow',
           'right': 'rightArrow', 'pageup': 'pageUp',
           'pagedown': 'pageDown'}.get(str(key or ''), str(key or ''))
    parts.append(key)
    from .shims.inputCore import normalizeGestureIdentifier
    return normalizeGestureIdentifier('kb:' + '+'.join(parts))


def run_gesture(identifier, obj=None, send=None):
    """The script an add-on bound to this gesture, run on the GUI thread.
    True when there was one."""
    if not _state['loaded']:
        return False
    owners = [app_module_for(obj) if obj is not None else None] + \
        list(_state['plugins'])
    gesture = _Gesture(identifier, send)
    for owner in owners:
        if owner is None:
            continue
        try:
            script = owner.getScript(gesture)
        except BaseException:                        # noqa: BLE001
            script = None
        if script is None:
            continue
        from .shims import scriptHandler

        def run(script=script):
            try:
                scriptHandler.executeScript(script, gesture)
            except BaseException as error:           # noqa: BLE001
                with _LOCK:
                    _state['errors']['script'] = \
                        '%s: %s' % (type(error).__name__, error)
        with _LOCK:
            _state['scripts'] += 1
        try:
            import wx
            wx.CallAfter(run)
        except Exception:                            # noqa: BLE001
            threading.Thread(target=run, daemon=True).start()
        return True
    return False


def gestures():
    """``[(identifier, script, owner)]`` - every key an add-on bound."""
    found = []
    owners = list(_state['plugins']) + [one for one in
                                         _state['app_modules'].values()
                                         if one is not None]
    for owner in owners:
        for identifier, script in (getattr(owner, '_gestureMap', {})
                                   or {}).items():
            found.append((identifier, script, type(owner).__module__))
    return found


# --------------------------------------------------------------------------- #
# External synthesis
# --------------------------------------------------------------------------- #
def _forget_synths():
    with _LOCK:
        _state['synths'] = None


def synthesizers():
    """``[{'name', 'description', 'addon'}]`` - every synthesizer the
    enabled add-ons bring. Imported (to read its name), not started."""
    with _LOCK:
        if _state['synths'] is not None:
            return list(_state['synths'])
    if not _state['loaded']:
        load(_state.get('engine'))
    found = []
    for record in installed():
        if not record['enabled']:
            continue
        path = os.path.join(record['path'], 'synthDrivers')
        if not os.path.isdir(path):
            continue
        for name in _modules_in([path]):
            module, why = _import('synthDrivers', name)
            cls = getattr(module, 'SynthDriver', None) if module else None
            found.append({'name': getattr(cls, 'name', name) or name,
                          'module': name,
                          'description': str(getattr(cls, 'description', '')
                                             or name),
                          'addon': record['name'],
                          'error': why})
    with _LOCK:
        _state['synths'] = found
    return list(found)


#: One at a time is made: two threads asking for the same synthesizer at
#: the same moment (the speech pump and the voice list, measured in a
#: user's log: two "Using RHVoice" in one second) made TWO instances, and
#: the one that lost was terminated under whoever held it.
_CREATING = threading.RLock()

#: How many synthesizers are kept running at once. Asking the voices of
#: another synthesizer used to TERMINATE the one the reader speaks with,
#: and the next word made it again - RHVoice was started nineteen times in
#: one session. The reader's own and the one being looked at stay.
KEEP_RUNNING = 3


def synth_instance(name):
    """The running instance of one synthesizer, started on first use."""
    from collections import OrderedDict
    with _LOCK:
        running = _state.setdefault('running', OrderedDict())
        if name in running:
            running.move_to_end(name)
            _state['synth'], _state['synth_name'] = running[name], name
            return running[name]
    with _CREATING:
        with _LOCK:
            running = _state['running']
            if name in running:
                running.move_to_end(name)
                return running[name]
        instance, real_name = _make_synth(name)
        from .shims import synthDriverHandler
        retired = []
        with _LOCK:
            running = _state['running']
            running[name] = instance
            if real_name and real_name != name:
                running[real_name] = instance
            _state['synth'] = instance
            _state['synth_name'] = name
            while len(set(map(id, running.values()))) > KEEP_RUNNING:
                old_name, old = running.popitem(last=False)
                if old is not instance and \
                        all(old is not kept for kept in running.values()):
                    retired.append(old)
        synthDriverHandler._current[0] = instance
    for old in retired:
        try:
            old.terminate()
        except BaseException:                        # noqa: BLE001
            pass
    return instance


def retire_synth(name):
    """Stop one running synthesizer and forget it, so the next word makes
    it again - what is done with a synthesizer that has stopped answering
    (`external._stalled`)."""
    with _LOCK:
        running = _state.get('running') or {}
        found = running.get(name)
        if found is None:
            return False
        for key in [key for key, one in running.items() if one is found]:
            del running[key]
        if _state['synth'] is found:
            _state['synth'], _state['synth_name'] = None, ''
    try:
        from . import external
        external._warmed.discard('nvda:%s' % name)
    except Exception:                                # noqa: BLE001
        pass

    def end():
        try:
            found.terminate()
        except BaseException:                        # noqa: BLE001
            pass
    # Terminating a wedged synthesizer may itself hang: never on the
    # reader's thread.
    threading.Thread(target=end, name='TitanAccessRetireSynth',
                     daemon=True).start()
    return True


def _make_synth(name):
    for one in synthesizers():
        if one['name'] == name or one['module'] == name:
            module, why = _import('synthDrivers', one['module'])
            if module is None:
                raise RuntimeError(why)
            cls = module.SynthDriver
            try:
                checked = cls.check()
            except BaseException:                    # noqa: BLE001
                checked = True
            if checked is False:
                raise RuntimeError('%s says it cannot run here' % name)
            instance = cls()
            try:
                from . import external
                # A NEW instance is cold again: its warm-up is owed.
                external._warmed.discard('nvda:%s' % name)
                external._warmed.discard('nvda:%s' % one['name'])
            except Exception:                        # noqa: BLE001
                pass
            return instance, one['name']
    raise RuntimeError('there is no synthesizer called %s' % name)


def menu_items():
    """``[(menu, label, run)]`` - what the add-ons put in NVDA's Tools and
    Preferences menus, ready to be offered by Titan Access."""
    try:
        from .shims import gui
    except Exception:                                # noqa: BLE001
        return []
    found = []
    for menu, label, handler, item_id in gui.mainFrame.sysTrayIcon.items():
        def run(handler=handler, item_id=item_id):
            import wx
            event = wx.CommandEvent(wx.wxEVT_COMMAND_MENU_SELECTED, item_id)

            def call():
                try:
                    handler(event)
                except BaseException as error:       # noqa: BLE001
                    with _LOCK:
                        _state['errors']['menu'] = '%s: %s' % (
                            type(error).__name__, error)
            wx.CallAfter(call)
        found.append((menu, label, run))
    return found


# --------------------------------------------------------------------------- #
# Saying things
# --------------------------------------------------------------------------- #
def _say(text):
    engine = _state.get('engine')
    try:
        if engine is not None:
            engine.speak(str(text))
            return
    except Exception:                                # noqa: BLE001
        pass
    print('[NVDA host] %s' % text)


def report():
    from . import importer
    with _LOCK:
        return {'loaded': _state['loaded'],
                'plugins': [type(one).__module__ for one in _state['plugins']],
                'app_modules': sorted(_state['app_module_classes']),
                'synth': _state['synth_name'],
                'events': _state['events'], 'scripts': _state['scripts'],
                'errors': dict(_state['errors']),
                'importer': importer.report(),
                'folder': folder(),
                'installed': [(one['name'], one['enabled'], one['kinds'])
                              for one in installed()]}


_unused = (io, configparser, time)

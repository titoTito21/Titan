# -*- coding: utf-8 -*-
"""Every part of Titan that can be switched off, and whether it is.

Two families live here, because the Component Manager shows them side by
side:

* **add-ons** - the twelve kinds that live in ``data/<subdir>/`` (components,
  applications, games, launchers, Titan IM modules, gamepad modes, TTS
  engines, widgets, statusbar applets, shell add-ons, settings interfaces and
  macros), directories or packaged ``.TCA``/``.TCD`` files alike;
* **services** - what Titan brings itself and nobody installed: Telegram,
  Messenger, WhatsApp, Titan-Net, EltenLink, the AI features, TCE sounds, the
  system monitor, and the Steam and Battle.net game lists.

Where the switch is kept
------------------------
Seven of the add-on kinds have always carried ``status = 0|1`` in their own
manifest, and their own managers read it. That stays the switch for them
whenever the manifest can be written. Everything else - the kinds whose
manifest has no status (applications, games, widgets, statusbar applets,
macros), a packaged add-on (its manifest is in a runtime cache that is
re-extracted from the package), a folder that is read-only, and the built-in
services - is kept in ONE file of the user's,
``%APPDATA%/titosoft/Titan/modules.json``::

    {"disabled": {"applications": ["tNotes"], "services": ["telegram"]}}

``platform_utils.discover_data_entries`` asks :func:`is_disabled` for every
entry it finds, so an add-on switched off here is absent from every list,
loader and action in Titan without any of them having to know this module
exists. Two services (AI, TCE sounds) already have a switch of their own in
the settings; they are read and written there, so there is one answer.

What happens when something is switched
---------------------------------------
:func:`set_enabled` answers a :class:`Change`: ``live`` when the change is in
force at once (an application leaves the list, a shell add-on is unloaded),
``restart`` when the part is only read while Titan starts (a component, a TTS
engine). The Component Manager says which, and offers to restart Titan.
"""

import configparser
import json
import os
import threading

from src.titan_core.translation import set_language
from src.settings.settings import get_setting, set_setting

_ = set_language(get_setting('language', 'pl'))

STORE_NAME = 'modules.json'
SERVICES_KEY = 'services'

# Kinds, in the order the Component Manager shows them.
#   id: (subdir, manifest file(s), manifest section or None, status default
#        when the manifest has none (None = the kind has no status), how a
#        change applies: 'live' | 'restart')
KINDS = (
    ('component', 'components', ('__component__.TCE',), 'component', 1, 'restart'),
    ('app', 'applications', ('__app.TCE', '__app.tce'), None, None, 'live'),
    ('game', 'games', ('__game.TCE', '__game.tce'), None, None, 'live'),
    ('im_module', 'titanIM_modules', ('__im.TCE',), 'im_module', 0, 'restart'),
    ('tts_engine', 'titantts engines', ('__engine__.TCE',), 'engine', 0, 'restart'),
    ('gamepad_mode', 'gamepad/modes', ('__mode__.TCE',), 'mode', 0, 'restart'),
    ('widget', 'applets', ('applet.json',), None, None, 'restart'),
    ('statusbar_applet', 'statusbar_applets', ('applet.json',), None, None, 'restart'),
    ('shell_addon', 'shell addons', ('__shell_addon__.TCE',), 'shell addon', 1, 'live'),
    ('settings_interface', 'settings interfaces', ('__settings_ui__.TCE',),
     'settings interface', 1, 'live'),
    ('launcher', 'launchers', ('__launcher__.TCE',), 'launcher', 1, 'restart'),
    ('macro', 'macros', ('__macro__.TCE',), None, None, 'live'),
)

KIND_IDS = tuple(kind[0] for kind in KINDS)


def kind_label(kind):
    """The kind's name in the user's language (a tab of the manager)."""
    return {
        'service': _("Titan services"),
        'component': _("Components"),
        'app': _("Applications"),
        'game': _("Games"),
        'im_module': _("Titan IM modules"),
        'tts_engine': _("TTS engines"),
        'gamepad_mode': _("Gamepad modes"),
        'widget': _("Widgets"),
        'statusbar_applet': _("Statusbar applets"),
        'shell_addon': _("Shell add-ons"),
        'settings_interface': _("Settings interfaces"),
        'launcher': _("Launchers"),
        'macro': _("Macros"),
        'client': _("External clients"),
    }.get(kind, kind)


def _kind(kind_id):
    for kind in KINDS:
        if kind[0] == kind_id:
            return kind
    return None


def subdir_of(kind_id):
    kind = _kind(kind_id)
    return kind[1] if kind else None


def _norm(subdir):
    return (subdir or '').replace('\\', '/').strip('/')


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
_lock = threading.RLock()
_cache = {'stamp': None, 'data': None}


def store_path():
    from src.platform_utils import get_user_data_dir
    return os.path.join(get_user_data_dir(), STORE_NAME)


def _read_store():
    """{'disabled': {subdir: set(names)}} - parsed when the file changes."""
    path = store_path()
    try:
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    with _lock:
        if _cache['data'] is not None and _cache['stamp'] == stamp:
            return _cache['data']
        data = {'disabled': {}}
        if stamp is not None:
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    raw = json.load(handle)
                for subdir, names in (raw.get('disabled') or {}).items():
                    if isinstance(names, list):
                        data['disabled'][_norm(subdir)] = {str(n) for n in names}
            except Exception as error:
                print(f"[modules] could not read {path}: {error}")
        _cache['data'] = data
        _cache['stamp'] = stamp
        return data


def _write_store(data):
    path = store_path()
    raw = {'disabled': {subdir: sorted(names)
                        for subdir, names in data['disabled'].items() if names}}
    with _lock:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            temporary = path + '.tmp'
            with open(temporary, 'w', encoding='utf-8') as handle:
                json.dump(raw, handle, indent=2, ensure_ascii=False)
            os.replace(temporary, path)
        except Exception as error:
            print(f"[modules] could not write {path}: {error}")
            return False
        _cache['data'] = None
        return True


def disabled_names(subdir):
    """The names switched off in ``data/<subdir>/`` (a frozenset)."""
    try:
        return frozenset(_read_store()['disabled'].get(_norm(subdir), ()))
    except Exception:
        return frozenset()


def is_disabled(subdir, name):
    """Was ``name`` in ``data/<subdir>/`` switched off in the manager?

    Cheap: the file is parsed only when it changes. This is what
    ``discover_data_entries`` asks for every entry.
    """
    try:
        return name in _read_store()['disabled'].get(_norm(subdir), ())
    except Exception:
        return False


def _store_set(subdir, name, disabled):
    with _lock:
        data = _read_store()
        copy = {'disabled': {key: set(value)
                             for key, value in data['disabled'].items()}}
        names = copy['disabled'].setdefault(_norm(subdir), set())
        if disabled:
            names.add(name)
        else:
            names.discard(name)
        return _write_store(copy)


# --------------------------------------------------------------------------- #
# Built-in services
# --------------------------------------------------------------------------- #
# id: (label, description, (setting key, section, on value, off value) or None)
SERVICES = (
    ('telegram', lambda: "Telegram",
     lambda: _("The Telegram client in Titan IM."), None),
    ('messenger', lambda: "Facebook Messenger",
     lambda: _("The Messenger client in Titan IM."), None),
    ('whatsapp', lambda: "WhatsApp",
     lambda: _("The WhatsApp client in Titan IM."), None),
    ('titannet', lambda: "Titan-Net",
     lambda: _("Titan's own network: chat, forum, mail, repository. "
               "Switched off, Titan does not sign in to it at startup."), None),
    ('eltenlink', lambda: "EltenLink",
     lambda: _("The EltenLink client in Titan IM."), None),
    ('ai', lambda: _("AI features"),
     lambda: _("The AI assistant, the AI agent, AI OCR and the creation kit."),
     ('enabled', 'ai', '1', '0')),
    ('tce_sounds', lambda: _("TCE sounds"),
     lambda: _("Sounds for windows opening and closing outside Titan."),
     ('enable_tce_sounds', 'environment', 'True', 'False')),
    ('system_monitor', lambda: _("System monitor"),
     lambda: _("Announces battery, charger, network and volume changes."), None),
    ('steam', lambda: _("Steam games"),
     lambda: _("Installed Steam games in the game list."), None),
    ('battlenet', lambda: _("Battle.net games"),
     lambda: _("Installed Battle.net games in the game list."), None),
)

SERVICE_IDS = tuple(service[0] for service in SERVICES)
# Read only while Titan starts; everything else is asked for when it is used.
_SERVICES_AT_START = {'tce_sounds'}


# Titan IM's own services, as their rows are labelled in every list of
# Titan IM (the main window, the Invisible UI, Klango mode).
IM_SERVICES = ('telegram', 'messenger', 'whatsapp', 'titannet', 'eltenlink')


def im_row_labels():
    """{service id: the translated labels its Titan IM row starts with}."""
    return {
        'telegram': (_("Telegram"),),
        'messenger': (_("Facebook Messenger"), _("Messenger")),
        'whatsapp': (_("WhatsApp"),),
        'titannet': (_("Titan-Net (Beta)"), "Titan-Net"),
        'eltenlink': (_("EltenLink (Beta)"), "EltenLink"),
    }


def im_service_of(text):
    """Which built-in IM service a Titan IM row is, or None."""
    text = text or ''
    for service_id, labels in im_row_labels().items():
        for label in labels:
            if label and (text == label or text.startswith(label + ' ')
                          or text.startswith(label + ',')):
                return service_id
    return None


def im_row_shown(text):
    """False for the row of a built-in IM service that is switched off."""
    service_id = im_service_of(text)
    return service_id is None or service_enabled(service_id)


def _service(service_id):
    for service in SERVICES:
        if service[0] == service_id:
            return service
    return None


def service_enabled(service_id):
    """Is the built-in service ``service_id`` switched on? Unknown ids are."""
    service = _service(service_id)
    if service is None:
        return True
    backing = service[3]
    if backing:
        key, section, on, _off = backing
        default = 'False' if service_id == 'tce_sounds' else '0'
        value = str(get_setting(key, default, section=section)).strip().lower()
        return value in (str(on).lower(), 'true', '1')
    return not is_disabled(SERVICES_KEY, service_id)


# --------------------------------------------------------------------------- #
# Entries
# --------------------------------------------------------------------------- #
class Module:
    """One row of the Component Manager."""

    def __init__(self, kind, ident, name, description='', path='',
                 enabled=True, packaged=False):
        self.kind = kind
        self.id = ident
        self.name = name or ident
        self.description = description or ''
        self.path = path
        self.enabled = enabled
        self.packaged = packaged

    @property
    def key(self):
        return f"{self.kind}:{self.id}"

    def __repr__(self):
        return f"<Module {self.key} {'on' if self.enabled else 'off'}>"


class Change:
    """What :func:`set_enabled` did."""

    def __init__(self, ok, applies='live', message=''):
        self.ok = ok
        self.applies = applies      # 'live' | 'restart'
        self.message = message

    @property
    def needs_restart(self):
        return self.ok and self.applies == 'restart'


def _language():
    return str(get_setting('language', 'pl') or 'pl')


def _manifest_path(path, files):
    for name in files:
        candidate = os.path.join(path, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _read_manifest(manifest, section):
    """{key: value} of a manifest: JSON, an ini section, or plain key=value."""
    values = {}
    if not manifest:
        return values
    try:
        if manifest.lower().endswith('.json'):
            with open(manifest, 'r', encoding='utf-8') as handle:
                raw = json.load(handle)
            return {str(k): str(v) for k, v in raw.items()
                    if isinstance(v, (str, int, float))}
        with open(manifest, 'r', encoding='utf-8', errors='replace') as handle:
            text = handle.read()
        if '[' in text.split('\n', 1)[0] or (section and f"[{section}]" in text):
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            parser.read_string(text)
            wanted = section if section and parser.has_section(section) else (
                parser.sections()[0] if parser.sections() else None)
            if wanted:
                values = {k: v.strip().strip('"') for k, v in parser.items(wanted)}
            return values
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(('#', ';', '[')) or '=' not in line:
                continue
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"')
    except Exception as error:
        print(f"[modules] could not read {manifest}: {error}")
    return values


def _localised(values, key, language):
    for candidate in (f"{key}_{language}", key, f"{key}_en", f"{key}_pl"):
        value = values.get(candidate)
        if value:
            return value
    return ''


def _is_packaged(path):
    norm = os.path.normcase(os.path.abspath(path))
    return f"{os.sep}pkg_cache{os.sep}" in norm


def _manifest_status(values, default):
    if default is None:
        return None
    raw = str(values.get('status', '')).strip()
    if raw == '':
        return default
    try:
        return int(raw)
    except ValueError:
        return 1


def entries(kind_id):
    """Every add-on of ``kind_id``, switched on or not, as :class:`Module`."""
    kind = _kind(kind_id)
    if kind is None:
        return []
    _ident, subdir, files, section, default, _applies = kind
    try:
        from src.platform_utils import discover_data_entries
        found = discover_data_entries(subdir, include_disabled=True)
    except Exception as error:
        print(f"[modules] could not look in {subdir}: {error}")
        return []
    language = _language()
    result = []
    for name, path in found.items():
        manifest = _manifest_path(path, files)
        if manifest is None:
            # Not an add-on of this kind (a game folder holding only its
            # sounds, a README) - nothing Titan would load either.
            continue
        values = _read_manifest(manifest, section)
        status = _manifest_status(values, default)
        enabled = (status in (None, 0)) and not is_disabled(subdir, name)
        result.append(Module(
            kind_id, name,
            _localised(values, 'name', language) or name,
            _localised(values, 'description', language),
            path, enabled, _is_packaged(path)))
    result.sort(key=lambda module: module.name.lower())
    return result


def services():
    result = []
    for service_id, label, description, _backing in SERVICES:
        result.append(Module('service', service_id, label(), description(),
                             '', service_enabled(service_id)))
    return result


def all_kinds():
    """('service', ...KIND_IDS) - every tab the manager can show."""
    return ('service', 'client') + KIND_IDS


def modules(kind_id):
    if kind_id == 'service':
        return services()
    if kind_id == 'client':
        from src.titan_core import external_clients
        return external_clients.rows()
    return entries(kind_id)


def find(kind_id, ident):
    for module in modules(kind_id):
        if module.id == ident:
            return module
    return None


def find_by_name(text, kind_id=None):
    """Modules whose id or name matches ``text`` (exact first, then partial)."""
    needle = (text or '').strip().lower()
    if not needle:
        return []
    kinds = (kind_id,) if kind_id else all_kinds()
    everything = [module for kind in kinds for module in modules(kind)]
    exact = [m for m in everything
             if needle in (m.id.lower(), m.name.lower())]
    if exact:
        return exact
    return [m for m in everything
            if needle in m.id.lower() or needle in m.name.lower()]


# --------------------------------------------------------------------------- #
# Switching
# --------------------------------------------------------------------------- #
_session_changes = {}    # key -> state Titan started with


def pending_restart():
    """Modules changed in this session whose change waits for a restart."""
    return dict(_session_changes)


def _note_change(module, applies, enabled):
    if applies != 'restart':
        return
    started = _session_changes.get(module.key)
    if started is None:
        _session_changes[module.key] = not enabled
    elif started == enabled:
        # Switched back to how Titan started: nothing waits for a restart.
        del _session_changes[module.key]


def waits_for_restart(module):
    return module.key in _session_changes


def _write_status(manifest, section, enabled):
    """Set ``status`` in an ini manifest, keeping every other line as it is."""
    value = '0' if enabled else '1'
    with open(manifest, 'r', encoding='utf-8', errors='replace') as handle:
        lines = handle.read().splitlines()
    header = f"[{section}]".lower()
    in_section = False
    section_at = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            in_section = stripped.lower() == header
            if in_section:
                section_at = index
            continue
        if in_section and '=' in stripped:
            key = stripped.split('=', 1)[0].strip().lower()
            if key == 'status':
                lines[index] = f"status = {value}"
                break
    else:
        if section_at is None:
            lines = [f"[{section}]", f"status = {value}", ''] + lines
        else:
            lines.insert(section_at + 1, f"status = {value}")
    with open(manifest, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')


def _set_service(module, enabled):
    service = _service(module.id)
    if service is None:
        return Change(False, message=_("There is no such service."))
    backing = service[3]
    if backing:
        key, section, on, off = backing
        set_setting(key, on if enabled else off, section=section)
    elif not _store_set(SERVICES_KEY, module.id, not enabled):
        return Change(False, message=_("The change could not be saved."))
    if module.id == 'system_monitor':
        _switch_system_monitor(enabled)
    applies = 'restart' if module.id in _SERVICES_AT_START else 'live'
    if module.id == 'titannet' and not enabled:
        applies = 'restart'     # a session that is signed in stays signed in
    return Change(True, applies)


def _switch_system_monitor(enabled):
    """Start or stop it now, on a thread: stopping joins its workers."""
    def work():
        try:
            from src.system import system_monitor
            if enabled:
                system_monitor.initialize_system_monitor()
            else:
                system_monitor.stop_system_monitor()
        except Exception as error:
            print(f"[modules] system monitor: {error}")
    threading.Thread(target=work, daemon=True, name='ModulesMonitor').start()


def set_enabled(module, enabled):
    """Switch ``module`` on or off. Never raises; answers a :class:`Change`."""
    enabled = bool(enabled)
    try:
        if module.kind == 'service':
            change = _set_service(module, enabled)
        elif module.kind == 'client':
            from src.titan_core import external_clients
            change = external_clients.set_enabled(module, enabled)
        else:
            change = _set_addon(module, enabled)
    except Exception as error:
        print(f"[modules] {module.key}: {error}")
        change = Change(False, message=str(error))
    if change.ok:
        module.enabled = enabled
        _note_change(module, change.applies, enabled)
        _after_change(module)
    return change


def _set_addon(module, enabled):
    kind = _kind(module.kind)
    if kind is None:
        return Change(False, message=_("Unknown kind of module."))
    _ident, subdir, files, section, default, applies = kind
    manifest = _manifest_path(module.path, files) if module.path else None
    has_status = section is not None and default is not None and manifest

    if module.kind == 'shell_addon' and not module.packaged:
        try:
            from src.shell import addons
            if addons.manager().set_enabled(module.id, enabled):
                _store_set(subdir, module.id, False)
                return Change(True, applies)
        except Exception as error:
            print(f"[modules] shell add-on {module.id}: {error}")

    writable = bool(has_status and not module.packaged
                    and os.access(manifest, os.W_OK))
    if writable:
        _write_status(manifest, section, enabled)
        # The manifest is the switch; the store must not disagree with it.
        _store_set(subdir, module.id, False)
    elif enabled:
        if has_status and _manifest_status(_read_manifest(manifest, section),
                                           default) not in (None, 0):
            return Change(False, message=_(
                "This add-on is switched off in its own manifest, which "
                "cannot be written here."))
        if not _store_set(subdir, module.id, False):
            return Change(False, message=_("The change could not be saved."))
    elif not _store_set(subdir, module.id, True):
        return Change(False, message=_("The change could not be saved."))

    if module.kind == 'component':
        _component_state(module.id, enabled)
    return Change(True, applies)


def _component_state(folder, enabled):
    """Keep the running ComponentManager's idea of the state in step."""
    try:
        import wx
        for window in wx.GetTopLevelWindows():
            manager = getattr(window, 'component_manager', None)
            if manager is not None and hasattr(manager, 'component_states'):
                manager.component_states[folder] = 0 if enabled else 1
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Telling the rest of Titan
# --------------------------------------------------------------------------- #
_listeners = []


def add_listener(callback):
    """``callback(module)`` after every change. Runs on the caller's thread."""
    if callback not in _listeners:
        _listeners.append(callback)


def remove_listener(callback):
    if callback in _listeners:
        _listeners.remove(callback)


def _after_change(module):
    try:
        from src.titan_core import actions
        actions.invalidate()
    except Exception:
        pass
    if module.kind == 'settings_interface':
        try:
            from src.settings import interfaces
            interfaces.manager().scan(force=True)
        except Exception:
            pass
    if module.kind == 'macro':
        try:
            from src.titan_core import actions
            actions.run('macros', 'reload')
        except Exception:
            pass
    for callback in list(_listeners):
        try:
            callback(module)
        except Exception as error:
            print(f"[modules] listener: {error}")
    refresh_faces(module.kind)


def refresh_faces(kind):
    """Re-read the lists of whichever faces of Titan are running.

    Only the lists that are cheap and safe to rebuild: the applications, the
    games and Titan IM. Must run on the GUI thread; anywhere else it asks for
    it.
    """
    if kind not in ('app', 'game', 'service', 'im_module'):
        return
    try:
        import wx
        if wx.GetApp() is None:
            return
        if not wx.IsMainThread():
            wx.CallAfter(refresh_faces, kind)
            return
        for window in wx.GetTopLevelWindows():
            _refresh_window(window, kind)
    except Exception as error:
        print(f"[modules] refresh: {error}")


def _refresh_window(window, kind):
    def call(owner, name):
        method = getattr(owner, name, None)
        if callable(method):
            try:
                method()
            except Exception as error:
                print(f"[modules] {name}: {error}")

    if kind == 'app':
        call(window, 'populate_app_list')
        call(window, 'load_applications')
    elif kind == 'game':
        call(window, 'populate_game_list')
        call(window, 'load_games')
    elif kind in ('service', 'im_module'):
        if getattr(window, 'current_list', None) == 'network':
            call(window, 'populate_network_list')


# --------------------------------------------------------------------------- #
# Restart
# --------------------------------------------------------------------------- #
def restart_titan():
    """Start Titan again. The new instance announces the restart and ends
    this one (main.py's single-instance check), so nothing is lost: every
    setting here is already on disk."""
    import subprocess
    import sys
    from src.platform_utils import is_frozen, get_base_path
    if is_frozen():
        command = [sys.executable]
    else:
        command = [sys.executable, os.path.join(get_base_path(), 'main.py')]
    try:
        # No hidden-window startup info: on Titan.exe that would hide the
        # window the new Titan opens with.
        kwargs = {}
        if sys.platform == 'win32' and not is_frozen():
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        subprocess.Popen(command, cwd=get_base_path(), close_fds=True, **kwargs)
        return True
    except Exception as error:
        print(f"[modules] could not restart Titan: {error}")
        return False

"""Finding every action Titan can currently perform.

Three sources are merged, in this order of authority:

1. **``__actions.json`` on disk** - the add-on author's declaration. Richest:
   summaries, parameter types, risk levels, which actions deserve promoting.
2. **``TITAN_ACTIONS`` in Python** - an in-process add-on declaring actions
   with real callables. Merged into the manifest's list when both exist, so a
   component can ship a JSON manifest and still add actions at runtime.
3. **A running process on the Action Bus** - an application that joined without
   shipping a manifest at all still becomes controllable, because the client
   library derives a declaration from the handler table itself.

The disk scan is cached (it walks nine directories across two roots); the bus
is merged fresh on every lookup, because which applications are open changes by
the second.
"""

import configparser
import json
import os
import threading
import time

from src.titan_core.actions import bus
from src.titan_core.actions.kinds import (
    ACTIONABLE_KINDS, default_transport, discover_kind, kind_label,
)
from src.titan_core.actions.manifest import (
    AddonActions, parse_manifest, read_manifest, slug,
)

_CACHE_TTL = 30.0

_cache = None
_cache_built_at = 0.0
_lock = threading.RLock()


class Registry:
    """Everything reachable right now."""

    def __init__(self):
        self.addons = []
        self.built_at = time.time()

    def by_id(self, addon_id):
        wanted = slug(addon_id)
        for addon in self.addons:
            if addon.addon_id == wanted:
                return addon
        # Fall back to the human label, because that is what a user says.
        lowered = (addon_id or '').strip().lower()
        for addon in self.addons:
            if addon.label.lower() == lowered or addon.name.lower() == lowered:
                return addon
        return None

    def actions(self):
        for addon in self.addons:
            for action in addon.actions:
                yield addon, action

    def warnings(self):
        out = []
        for addon in self.addons:
            for warning in addon.warnings:
                out.append(f"{addon.addon_id}: {warning}")
        return out


# --------------------------------------------------------------------------- #
# Friendly names, read from whatever manifest the kind already uses
# --------------------------------------------------------------------------- #
def _tce_name(path, filenames, lang):
    for filename in filenames:
        for candidate in (filename, filename.lower(), filename.upper()):
            full = os.path.join(path, candidate)
            if not os.path.isfile(full):
                continue
            values = {}
            try:
                with open(full, 'r', encoding='utf-8') as handle:
                    for line in handle:
                        if '=' in line:
                            key, value = line.split('=', 1)
                            values[key.strip()] = value.strip().strip('"')
            except Exception:
                continue
            for key in (f'name_{lang}', 'name_en', 'name'):
                if values.get(key):
                    return values[key]
    return ''


def _ini_name(path, filename, section='component'):
    full = os.path.join(path, filename)
    if not os.path.isfile(full):
        return ''
    parser = configparser.ConfigParser()
    try:
        parser.read(full, encoding='utf-8')
        return parser.get(section, 'name', fallback='')
    except Exception:
        return ''


def _json_name(path, filename):
    full = os.path.join(path, filename)
    if not os.path.isfile(full):
        return ''
    try:
        with open(full, 'r', encoding='utf-8-sig') as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return str(data.get('name') or data.get('label') or '')
    except Exception:
        pass
    return ''


def _friendly_label(kind, path, name):
    try:
        from src.titan_core.translation import language_code as lang
    except Exception:
        lang = 'en'
    if kind in ('app', 'game'):
        return _tce_name(path, ('__app.TCE', '__game.TCE'), lang) or name
    if kind == 'component':
        return _ini_name(path, '__component__.TCE') or name
    if kind in ('widget', 'statusbar_applet'):
        return (_json_name(path, 'applet.json')
                or _json_name(path, 'statusbar_applet.json') or name)
    if kind == 'im_module':
        return _json_name(path, 'module.json') or name
    if kind == 'tts_engine':
        return _json_name(path, 'engine.json') or name
    return name


# --------------------------------------------------------------------------- #
# Building
# --------------------------------------------------------------------------- #
def _merge_python_declared(addon):
    """Pick up ``TITAN_ACTIONS`` from the add-on's loaded modules and add
    anything the JSON manifest did not already declare."""
    if addon.transport != 'inproc':
        return
    try:
        from src.titan_core.actions import inproc
    except Exception:
        return
    existing = {action.name for action in addon.actions}
    for owner in inproc.candidate_owners(addon):
        if not hasattr(owner, 'TITAN_ACTIONS'):
            continue
        for action in inproc.actions_from_module(owner, addon):
            if action.name in existing:
                # The JSON wins on description, but a live callable is better
                # than a name lookup, so keep it.
                current = addon.get(action.name)
                if current is not None and current.run is None:
                    current.run = action.run
                continue
            existing.add(action.name)
            addon.actions.append(action)
        if addon.source == 'json' and not addon.actions:
            addon.source = 'python'


def _merge_kind_standard(addon):
    """Add the actions every add-on of this kind offers.

    A TTS engine has voices and settings, a statusbar applet has text, an IM
    module opens - none of which its author should have to declare. These go on
    last, so an add-on that *did* declare an action of the same name keeps its
    own.
    """
    try:
        from src.titan_core.actions import generic
    except Exception:
        return
    for action in generic.standard_actions(addon):
        addon.actions.append(action)


def _scan_disk():
    addons = []
    for kind in ACTIONABLE_KINDS:
        for name, path in discover_kind(kind).items():
            try:
                label = _friendly_label(kind, path, name)
                addon = read_manifest(path, kind, name,
                                      default_transport=default_transport(kind),
                                      fallback_label=label)
                if addon is None:
                    # No manifest. In-process add-ons may still declare actions
                    # in Python, so give them a shell to be discovered through;
                    # out-of-process ones without a manifest have nothing to
                    # offer until they join the bus.
                    if default_transport(kind) != 'inproc':
                        continue
                    addon = AddonActions(kind=kind, addon_id=slug(name, 'addon'),
                                         name=name, path=path, label=label,
                                         transport='inproc')
                    addon.source = 'python'
                _merge_python_declared(addon)
                _merge_kind_standard(addon)
                if addon.actions:
                    addons.append(addon)
            except Exception as e:
                print(f"[actions] Skipped {kind} '{name}': {e}")
    return addons


def _merge_bus(registry):
    """Fold in the applications that are running right now."""
    for peer in bus.list_peers():
        addon = registry.by_id(peer.addon_id)
        if addon is not None:
            addon.running = True
            addon.pid = peer.pid
            # A running instance may offer more than its manifest promised.
            known = {action.name for action in addon.actions}
            extra = parse_manifest({'actions': peer.actions}, addon.kind,
                                   addon.name, addon.path,
                                   default_transport=addon.transport,
                                   fallback_label=addon.label)
            for action in extra.actions:
                if action.name not in known:
                    action.addon = addon
                    action.mode = 'live'
                    addon.actions.append(action)
            continue
        addon = parse_manifest(
            {'id': peer.addon_id, 'label': peer.label,
             'actions': peer.actions},
            peer.kind or 'app', peer.addon_id, peer.path or '',
            default_transport='process', fallback_label=peer.label)
        addon.source = 'bus'
        addon.running = True
        addon.pid = peer.pid
        for action in addon.actions:
            action.mode = 'live'
        if addon.actions:
            registry.addons.append(addon)


def _build():
    registry = Registry()
    try:
        from src.titan_core.actions import builtin
        registry.addons = builtin.build()
    except Exception as e:
        print(f"[actions] Built-in subsystems unavailable: {e}")
        registry.addons = []
    taken = {addon.addon_id for addon in registry.addons}

    builtin_ids = set(taken)
    for addon in _scan_disk():
        # Two add-ons may declare the same id - a package installed beside the
        # add-on it was built from, or one of Titan's own subsystem names. The
        # loser must not simply vanish: it keeps its actions under a
        # distinguishable id, and says so.
        if addon.addon_id in taken:
            original = addon.addon_id
            # The kind is what usually differs - an ElevenLabs application and
            # an ElevenLabs TTS engine both want to be 'elevenlabs' - and
            # 'elevenlabs_tts_engine' says which one this is, where repeating
            # the name would not.
            suffix = 'addon' if original in builtin_ids else (
                addon.kind if slug(addon.name) == original else slug(addon.name,
                                                                     'copy'))
            candidate = f"{original}_{suffix}"
            counter = 2
            while candidate in taken:
                candidate = f"{original}_{suffix}{counter}"
                counter += 1
            reason = ("one of Titan's built-in subsystems"
                      if original in builtin_ids
                      else "already used by another installed add-on")
            addon.warnings.append(
                f"'{original}' is {reason}, so this add-on is reachable as "
                f"'{candidate}'")
            addon.addon_id = candidate
        taken.add(addon.addon_id)
        registry.addons.append(addon)

    for addon in registry.addons:
        addon.running = False
        addon.pid = 0
    return registry


def get_registry(force=False):
    """The current registry. The disk scan is cached; the bus is always live."""
    global _cache, _cache_built_at
    with _lock:
        stale = (_cache is None or force
                 or time.time() - _cache_built_at > _CACHE_TTL)
        if stale:
            _cache = _build()
            _cache_built_at = time.time()
        else:
            for addon in _cache.addons:
                addon.running = False
                addon.pid = 0
            _cache.addons = [a for a in _cache.addons if a.source != 'bus']
        _merge_bus(_cache)
        return _cache


def invalidate():
    """Forget the disk scan. Call after installing, enabling or removing an
    add-on."""
    global _cache, _cache_built_at
    with _lock:
        _cache = None
        _cache_built_at = 0.0


def find_addon(addon_id):
    return get_registry().by_id(addon_id)


def find_action(addon_id, action_name=''):
    """Accepts ('tedit', 'open_file') or a single 'tedit.open_file'.
    Returns (addon, action) with either possibly None."""
    if not action_name and '.' in (addon_id or ''):
        addon_id, action_name = addon_id.split('.', 1)
    addon = find_addon(addon_id)
    if addon is None:
        return None, None
    return addon, addon.get(action_name)


def all_actions():
    return list(get_registry().actions())

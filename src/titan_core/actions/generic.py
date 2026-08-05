"""What every add-on of a kind can do, without its author writing anything.

An add-on declares what is *particular* to it - a manifest, or a
``TITAN_ACTIONS`` list. But most kinds share one Python interface with every
other add-on of that kind: a TTS engine has voices and configuration fields, a
statusbar applet has text, an IM module opens, a component is enabled or not.
Making each author restate that would mean the AI can only drive the handful of
add-ons somebody remembered to write a manifest for - and a user's own TTS
engine, installed yesterday, would be unreachable.

So the kind itself declares those. Every installed add-on appears in the
registry with the standard actions for its kind, and anything it declares on
top is merged in by ``registry._merge_python_declared`` (an add-on's own
declaration always wins - see ``standard_actions``).

This is also the answer to "the settings exist but the AI says there is no API
key": a TTS engine's configuration fields *are* its settings, so
``<engine>.list_settings`` / ``set_setting`` let the AI find the field named
``api_key``, say where it goes, and fill it in with the user's permission,
instead of reporting a dead end.

Nothing in here raises: a missing manager, a subsystem that failed to import
and an add-on that is installed but not loaded all come back as a sentence.
"""

import os
import threading

from src.titan_core.actions.manifest import ActionSpec

_STRING = {'type': 'string'}

_lock = threading.Lock()
_fallback_statusbar = None
_widget_modules = {}            # init.py path -> (mtime, module)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _main_frame():
    """The Titan window that owns the managers, or None.

    Titan's managers hang off whichever frame started them - the main GUI, the
    Invisible UI's host, a launcher's hidden frame - so the object is found by
    what it carries rather than by what class it is.
    """
    try:
        import wx
    except Exception:
        return None
    try:
        app = wx.GetApp()
        if app is None:
            return None
        candidates = [getattr(app, 'main_frame', None)]
        try:
            candidates.append(app.GetTopWindow())
        except Exception:
            pass
        candidates.extend(wx.GetTopLevelWindows())
        for candidate in candidates:
            if candidate is None:
                continue
            if (getattr(candidate, 'component_manager', None) is not None
                    or getattr(candidate, 'statusbar_applet_manager',
                               None) is not None):
                return candidate
    except Exception:
        return None
    return None


def _param(spec, description, required=False, enum=None):
    entry = {'type': spec.get('type', 'string'), 'description': description,
             'required': bool(required)}
    if enum:
        entry['enum'] = list(enum)
    return entry


def _match(query, candidates, key=lambda item: item):
    """The candidate a user meant, exact match first, then a substring."""
    wanted = str(query or '').strip().lower()
    if not wanted:
        return None
    for item in candidates:
        if str(key(item)).strip().lower() == wanted:
            return item
    for item in candidates:
        if wanted in str(key(item)).strip().lower():
            return item
    return None


def _mask(field, value):
    """How a configuration value may be shown.

    An API key or a password is never rendered - the AI is told it is set and
    how long it is, and nothing else. A tool result is sent to a model provider
    verbatim, so a secret that appears in one has left the machine.
    """
    from src.titan_core.secret_store import describe_value
    return describe_value(field.get('key', ''), value, field.get('type', ''))


# --------------------------------------------------------------------------- #
# TTS engines
# --------------------------------------------------------------------------- #
def _engine_registry():
    from src.tts.engine_registry import get_engine_registry
    return get_engine_registry()


def _engine_for(folder):
    """(engine, engine_id, error).

    ``folder`` is the add-on's directory name, bound in when the actions were
    built - never something a user typed. An engine declares its own id, which
    usually but not always matches the folder, so both are compared exactly.
    A fuzzy match has no place here: it could only ever bind a folder that did
    not load to a *different* engine, and then configure that one.
    """
    try:
        registry = _engine_registry()
    except Exception as e:
        return None, '', f"The TTS engines are not available: {e}"
    try:
        engines = list(registry.get_all_engines())
    except Exception as e:
        return None, '', f"Could not list the TTS engines: {e}"
    wanted = str(folder or '').strip().lower()
    for attribute in ('engine_id', 'engine_name'):
        for engine in engines:
            if str(getattr(engine, attribute, '')).strip().lower() == wanted:
                return engine, engine.engine_id, ''
    return None, '', (f"The TTS engine '{folder}' is installed but did not "
                      f"load, so it cannot be configured. Its folder may be "
                      f"disabled, or a dependency it needs is missing.")


def _engine_setting_key(engine_id, key):
    return f"engine.{engine_id}.{key}"


def _engine_fields(engine):
    try:
        fields = engine.get_config_fields()
    except Exception:
        fields = []
    return [f for f in (fields or []) if isinstance(f, dict) and f.get('key')]


def _active_engine_id():
    """The engine Titan is speaking with *now*.

    The saved setting is only what it will start with; an engine switched this
    session and not saved would otherwise be reported as unused while it is the
    one talking.
    """
    try:
        from src.titan_core.stereo_speech import get_stereo_speech
        speech = get_stereo_speech()
        current = str(getattr(speech, 'engine', '') or '')
        if current:
            return current
    except Exception:
        pass
    try:
        from src.settings.settings import get_setting
        return str(get_setting('engine', '', section='stereo_speech') or '')
    except Exception:
        return ''


def _tts_status(folder):
    engine, engine_id, error = _engine_for(folder)
    if engine is None:
        return error
    try:
        available = bool(engine.is_available())
    except Exception:
        available = False
    lines = [f"{getattr(engine, 'engine_name', engine_id)} (id {engine_id})",
             f"- {'ready to speak' if available else 'not ready'}",
             f"- {'the engine Titan speaks with' if _active_engine_id() == engine_id else 'not the engine Titan speaks with'}"]
    fields = _engine_fields(engine)
    if fields:
        unset = [f['key'] for f in fields
                 if f.get('required') and not engine.get_config(f['key'], '')]
        if unset:
            lines.append("- still needs: " + ", ".join(unset)
                         + " (set them with set_setting)")
    return "\n".join(lines)


def _tts_list_voices(folder):
    engine, engine_id, error = _engine_for(folder)
    if engine is None:
        return error
    try:
        voices = engine.get_voices() or []
    except Exception as e:
        return f"Could not list {engine_id}'s voices: {e}"
    if not voices:
        return (f"{engine_id} reports no voices. It may still need "
                f"configuring - try list_settings.")
    lines = []
    for voice in voices:
        if isinstance(voice, dict):
            lines.append(f"- {voice.get('display_name') or voice.get('name') or voice.get('id')}")
        else:
            lines.append(f"- {voice}")
    return f"{len(lines)} voices in {engine_id}:\n" + "\n".join(lines)


def _voice_id(voice):
    if isinstance(voice, dict):
        return voice.get('id') or voice.get('name') or ''
    return str(voice)


def _voice_label(voice):
    if isinstance(voice, dict):
        return voice.get('display_name') or voice.get('name') or voice.get('id') or ''
    return str(voice)


def _tts_set_voice(folder, voice):
    engine, engine_id, error = _engine_for(folder)
    if engine is None:
        return error
    if not str(voice or '').strip():
        return "Say which voice."
    try:
        voices = engine.get_voices() or []
    except Exception as e:
        return f"Could not list {engine_id}'s voices: {e}"
    found = _match(voice, voices, key=_voice_label)
    if found is None:
        found = _match(voice, voices, key=_voice_id)
    if found is None:
        return (f"{engine_id} has no voice called '{voice}'. "
                f"Available: " + ", ".join(_voice_label(v) for v in voices[:20]))
    try:
        engine.set_voice(_voice_id(found))
    except Exception as e:
        return f"Could not switch {engine_id} to {_voice_label(found)}: {e}"
    if _active_engine_id() == engine_id:
        try:
            from src.settings.settings import set_setting
            set_setting('voice', _voice_id(found), section='stereo_speech')
        except Exception:
            pass
    return f"{engine_id} now speaks with {_voice_label(found)}."


def _tts_list_settings(folder):
    engine, engine_id, error = _engine_for(folder)
    if engine is None:
        return error
    fields = _engine_fields(engine)
    if not fields:
        return f"{engine_id} has nothing to configure."
    lines = [f"{engine_id} settings (change one with set_setting):"]
    for field in fields:
        key = field['key']
        try:
            value = engine.get_config(key, '')
        except Exception:
            value = ''
        label = field.get('label') or key
        required = " [required]" if field.get('required') else ""
        lines.append(f"- {key}: {label}{required} = {_mask(field, value)}")
        options = field.get('options')
        if isinstance(options, (list, tuple)) and options:
            rendered = [o[0] if isinstance(o, (list, tuple)) else o
                        for o in options]
            lines.append(f"    one of: " + ", ".join(str(o) for o in rendered))
    return "\n".join(lines)


def _tts_get_setting(folder, key):
    engine, engine_id, error = _engine_for(folder)
    if engine is None:
        return error
    fields = _engine_fields(engine)
    field = _match(key, fields, key=lambda f: f.get('key', ''))
    if field is None:
        return (f"{engine_id} has no setting called '{key}'. "
                f"Available: " + ", ".join(f['key'] for f in fields))
    try:
        value = engine.get_config(field['key'], '')
    except Exception as e:
        return f"Could not read {engine_id}'s {field['key']}: {e}"
    return f"{engine_id}.{field['key']} = {_mask(field, value)}"


def _tts_set_setting(folder, key, value):
    engine, engine_id, error = _engine_for(folder)
    if engine is None:
        return error
    fields = _engine_fields(engine)
    field = _match(key, fields, key=lambda f: f.get('key', ''))
    if field is None:
        return (f"{engine_id} has no setting called '{key}'. "
                f"Available: " + ", ".join(f['key'] for f in fields))
    name = field['key']
    try:
        engine.configure(name, value)
    except Exception as e:
        return f"{engine_id} refused {name}: {e}"
    # The live engine now has the plain value; what goes on disk does not.
    # An API key written into bg5settings.ini in the clear is readable by
    # anything that can read the user's profile.
    try:
        from src.settings.settings import set_setting
        from src.titan_core.secret_store import store_value
        set_setting(_engine_setting_key(engine_id, name),
                    store_value(name, value, field.get('type', '')),
                    section='stereo_speech')
    except Exception as e:
        return (f"{engine_id}'s {name} was set for this session, but could not "
                f"be saved: {e}")
    from src.titan_core.secret_store import looks_secret
    if looks_secret(name, field.get('type', '')):
        return (f"{engine_id}'s {name} is set and saved, encrypted so it is "
                f"readable only by this Windows account.")
    return f"{engine_id}'s {name} is set and saved."


def _tts_use(folder):
    engine, engine_id, error = _engine_for(folder)
    if engine is None:
        return error
    try:
        if not engine.is_available():
            return (f"{engine_id} is not ready to speak yet - check "
                    f"list_settings for what it still needs.")
    except Exception:
        pass
    switched = False
    try:
        from src.titan_core.stereo_speech import get_stereo_speech
        speech = get_stereo_speech()
        if speech is not None:
            speech.set_engine(engine_id)
            switched = True
    except Exception as e:
        return f"Could not switch Titan to {engine_id}: {e}"
    try:
        from src.settings.settings import set_setting
        set_setting('engine', engine_id, section='stereo_speech')
    except Exception as e:
        return (f"Titan is speaking with {engine_id} now, but the choice "
                f"could not be saved: {e}")
    label = getattr(engine, 'engine_name', engine_id)
    if not switched:
        # Saying "Titan now speaks with X" when Titan's speech was never
        # reached would be a report of something that did not happen.
        return (f"{label} is saved as the engine to speak with, and will be "
                f"used the next time Titan starts - Titan's speech could not "
                f"be reached to switch it now.")
    return f"Titan now speaks with {label}."


def _tts_actions(folder):
    return (
        ('status', "Say whether this TTS engine is ready to speak, whether "
                   "Titan is using it, and what it still needs configuring.",
         {}, 'auto', lambda **_: _tts_status(folder)),
        ('list_voices', "List this TTS engine's voices.",
         {}, 'auto', lambda **_: _tts_list_voices(folder)),
        ('set_voice', "Choose which voice this TTS engine speaks with.",
         {'voice': _param(_STRING, "The voice's name.", required=True)},
         'confirm', lambda voice='', **_: _tts_set_voice(folder, voice)),
        ('list_settings', "List this TTS engine's own settings - API keys, "
                          "models, servers - and which of them are already "
                          "filled in.",
         {}, 'auto', lambda **_: _tts_list_settings(folder)),
        ('get_setting', "Read one of this TTS engine's settings. A key or "
                        "password is only ever reported as set or not set.",
         {'key': _param(_STRING, "The setting's key, e.g. 'api_key'.",
                        required=True)},
         'auto', lambda key='', **_: _tts_get_setting(folder, key)),
        ('set_setting', "Change one of this TTS engine's settings - this is "
                        "where an API key goes - and save it.",
         {'key': _param(_STRING, "The setting's key, e.g. 'api_key'.",
                        required=True),
          'value': _param(_STRING, "The new value.", required=True)},
         'always_confirm',
         lambda key='', value='', **_: _tts_set_setting(folder, key, value)),
        ('use', "Make this the engine Titan speaks with.",
         {}, 'confirm', lambda **_: _tts_use(folder)),
    )


# --------------------------------------------------------------------------- #
# Components
# --------------------------------------------------------------------------- #
def _component_manager():
    """The live ComponentManager, found without going through ``src.ai``.

    Enabling a component is a titan-core capability; routing it through the AI
    tool module would drag the whole AI stack in, and would fail outright on an
    install where one of the AI's optional dependencies is missing.
    """
    frame = _main_frame()
    return getattr(frame, 'component_manager', None) if frame else None


def _component_entry(manager, folder):
    try:
        for entry in manager.get_components():
            if entry.get('folder') == folder:
                return entry
        return _match(folder, manager.get_components(),
                      key=lambda e: e.get('name', ''))
    except Exception:
        return None


def _component_status(folder):
    manager = _component_manager()
    if manager is None:
        return "The component manager is not available."
    entry = _component_entry(manager, folder)
    if entry is None:
        return f"There is no component in the folder '{folder}'."
    loaded = any(getattr(module, '__name__', '') == folder
                 for module in getattr(manager, 'components', []))
    return (f"{entry.get('name', folder)} is "
            f"{'enabled' if entry.get('enabled') else 'disabled'} and "
            f"{'loaded' if loaded else 'not loaded in this session'}.")


def _component_set_enabled(folder, enabled):
    manager = _component_manager()
    if manager is None:
        return "The component manager is not available."
    entry = _component_entry(manager, folder)
    if entry is None:
        return f"There is no component in the folder '{folder}'."
    folder = entry.get('folder', folder)
    wanted = bool(enabled)
    if bool(entry.get('enabled')) == wanted:
        return (f"{entry.get('name', folder)} is already "
                f"{'enabled' if wanted else 'disabled'}.")
    # toggle_component_status flips, so it is only called when the state
    # actually differs - calling it to "set" a state it is already in would
    # turn the component off.
    try:
        manager.toggle_component_status(folder)
    except Exception as e:
        return f"Could not change {entry.get('name', folder)}: {e}"
    return (f"{'Enabled' if wanted else 'Disabled'} "
            f"{entry.get('name', folder)}. Restart Titan for it to take "
            f"effect.")


def _component_actions(folder):
    return (
        ('status', "Say whether this component is enabled and loaded.",
         {}, 'auto', lambda **_: _component_status(folder)),
        ('enable', "Turn this component on. It loads when Titan next starts.",
         {}, 'confirm', lambda **_: _component_set_enabled(folder, True)),
        ('disable', "Turn this component off.",
         {}, 'confirm', lambda **_: _component_set_enabled(folder, False)),
    )


# --------------------------------------------------------------------------- #
# Titan IM modules
# --------------------------------------------------------------------------- #
def _im_modules():
    from src.network.im_module_manager import im_module_manager
    return im_module_manager


def _im_entry(folder):
    try:
        manager = _im_modules()
    except Exception as e:
        return None, None, f"The Titan IM modules are not available: {e}"
    modules = list(getattr(manager, 'modules', []))
    for info in modules:
        if info.get('id') == folder or info.get('name') == folder:
            return manager, info, ''
    found = _match(folder, modules, key=lambda i: i.get('name', ''))
    if found is not None:
        return manager, found, ''
    return manager, None, (f"The Titan IM module '{folder}' is installed but "
                           f"was not loaded - it may be disabled.")


def _im_status(folder):
    _manager, info, error = _im_entry(folder)
    if info is None:
        return error
    detail = ''
    try:
        module = info.get('module')
        if hasattr(module, 'get_status_text'):
            detail = str(module.get_status_text() or '')
    except Exception:
        detail = ''
    return (f"{info.get('name')} is loaded and can be opened."
            + (f" It says: {detail}" if detail else ''))


def _im_open(folder):
    manager, info, error = _im_entry(folder)
    if info is None:
        return error
    try:
        opened = manager.open_module(info.get('id') or info.get('name'))
    except Exception as e:
        return f"Could not open {info.get('name')}: {e}"
    if not opened:
        return f"{info.get('name')} did not open."
    return f"{info.get('name')} is open."


def _im_actions(folder):
    return (
        ('status', "Say whether this Titan IM module is loaded, and what it "
                   "reports.",
         {}, 'auto', lambda **_: _im_status(folder)),
        ('open', "Open this Titan IM module's window.",
         {}, 'confirm', lambda **_: _im_open(folder)),
    )


# --------------------------------------------------------------------------- #
# Statusbar applets
# --------------------------------------------------------------------------- #
def _statusbar_manager():
    """The live statusbar manager, or a private one built once.

    Constructing a StatusbarAppletManager executes every installed applet's
    ``main.py``, so the fallback is built at most once per session - building
    one per action call would re-run all of that on every read.
    """
    global _fallback_statusbar
    frame = _main_frame()
    manager = getattr(frame, 'statusbar_applet_manager', None) if frame else None
    if manager is not None:
        return manager
    with _lock:
        if _fallback_statusbar is None:
            from src.titan_core.statusbar_applet_manager import (
                StatusbarAppletManager)
            _fallback_statusbar = StatusbarAppletManager()
        return _fallback_statusbar


def _statusbar_read(folder):
    try:
        manager = _statusbar_manager()
    except Exception as e:
        return f"The statusbar applets are not available: {e}"
    try:
        names = manager.get_applet_names()
    except Exception as e:
        return f"Could not list the statusbar applets: {e}"
    name = folder if folder in names else _match(folder, names)
    if name is None:
        return f"There is no statusbar applet called '{folder}'."
    try:
        return f"{name}: {manager.get_applet_text(name)}"
    except Exception as e:
        return f"Could not read {name}: {e}"


def _statusbar_activate(folder):
    try:
        manager = _statusbar_manager()
        names = manager.get_applet_names()
    except Exception as e:
        return f"The statusbar applets are not available: {e}"
    name = folder if folder in names else _match(folder, names)
    if name is None:
        return f"There is no statusbar applet called '{folder}'."
    try:
        manager.activate_applet(name)
    except Exception as e:
        return f"Could not activate {name}: {e}"
    return f"Activated the statusbar applet {name}."


def _statusbar_actions(folder):
    return (
        ('read', "Read what this statusbar applet currently shows.",
         {}, 'auto', lambda **_: _statusbar_read(folder)),
        ('activate', "Activate this statusbar applet, as pressing it in the "
                     "status bar would.",
         {}, 'confirm', lambda **_: _statusbar_activate(folder)),
    )


# --------------------------------------------------------------------------- #
# Widgets
# --------------------------------------------------------------------------- #
def _widget_module(folder, path):
    """(module, error). The widget Titan already loaded, or a cached import."""
    import importlib.util
    import sys

    init = os.path.join(path, 'init.py')
    if not os.path.isfile(init):
        return None, f"The widget '{folder}' has no init.py."
    wanted = os.path.normcase(os.path.abspath(init))
    for candidate in list(sys.modules.values()):
        filename = getattr(candidate, '__file__', None)
        if filename and os.path.normcase(os.path.abspath(filename)) == wanted:
            return candidate, ''
    # Not loaded, so import it - but keep it, because a widget's init.py is
    # real code and re-executing it on every call is both wasteful and a way
    # to end up with two of whatever it built.
    try:
        mtime = os.path.getmtime(init)
    except OSError as e:
        return None, f"Could not read the widget '{folder}': {e}"
    with _lock:
        cached = _widget_modules.get(wanted)
        if cached and cached[0] == mtime:
            return cached[1], ''
    try:
        spec = importlib.util.spec_from_file_location(
            f"titan_widget_{folder}", init)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        return None, f"Could not read the widget '{folder}': {e}"
    with _lock:
        _widget_modules[wanted] = (mtime, module)
    return module, ''


def _widget_info(folder, path):
    module, error = _widget_module(folder, path)
    if module is None:
        return error
    getter = getattr(module, 'get_widget_info', None)
    if not callable(getter):
        return f"The widget '{folder}' does not describe itself."
    try:
        info = getter() or {}
    except Exception as e:
        return f"The widget '{folder}' could not describe itself: {e}"
    if not isinstance(info, dict):
        return f"The widget '{folder}': {info}"
    return "\n".join(f"- {key}: {value}" for key, value in info.items())


def _widget_actions(folder, path):
    return (
        ('info', "What this widget is and what kind of control it puts on the "
                 "desktop.",
         {}, 'auto', lambda **_: _widget_info(folder, path)),
    )


# --------------------------------------------------------------------------- #
# Gamepad modes
# --------------------------------------------------------------------------- #
def _gamepad_activate(folder):
    from src.titan_core.actions import builtin
    return builtin.gamepad_set_mode(folder)


def _gamepad_status(folder):
    from src.titan_core.actions import builtin
    current = builtin.gamepad_get_mode()
    return (f"The gamepad mode '{folder}' is installed. {current}")


def _gamepad_actions(folder):
    return (
        ('status', "Say whether this gamepad mode is the active one.",
         {}, 'auto', lambda **_: _gamepad_status(folder)),
        ('activate', "Switch the gamepad to this mode.",
         {}, 'confirm', lambda **_: _gamepad_activate(folder)),
    )


# --------------------------------------------------------------------------- #
# Launchers
# --------------------------------------------------------------------------- #
def _launcher_setting():
    try:
        from src.settings.settings import get_setting
        return (str(get_setting('launcher', '', section='general') or ''),
                str(get_setting('startup_mode', '', section='general') or ''))
    except Exception:
        return '', ''


def _launcher_status(folder):
    launcher, mode = _launcher_setting()
    if launcher == folder and mode == 'launcher':
        return f"Titan starts in the launcher '{folder}'."
    if launcher == folder:
        return (f"'{folder}' is the chosen launcher, but Titan starts in "
                f"{mode or 'its normal interface'} rather than launcher mode.")
    return (f"The launcher '{folder}' is installed but is not the one Titan "
            f"starts with"
            + (f" ('{launcher}' is)." if launcher else "."))


def _launcher_use(folder):
    try:
        from src.settings.settings import set_setting
        set_setting('launcher', folder, section='general')
        set_setting('startup_mode', 'launcher', section='general')
    except Exception as e:
        return f"Could not choose the launcher '{folder}': {e}"
    return (f"Titan will start in the launcher '{folder}' from the next time "
            f"it runs.")


def _launcher_actions(folder):
    return (
        ('status', "Say whether Titan starts in this launcher.",
         {}, 'auto', lambda **_: _launcher_status(folder)),
        ('use', "Make Titan start in this launcher from the next run.",
         {}, 'always_confirm', lambda **_: _launcher_use(folder)),
    )


# --------------------------------------------------------------------------- #
# Building
# --------------------------------------------------------------------------- #
_BY_KIND = {
    'tts_engine': lambda name, path: _tts_actions(name),
    'component': lambda name, path: _component_actions(name),
    'im_module': lambda name, path: _im_actions(name),
    'statusbar_applet': lambda name, path: _statusbar_actions(name),
    'widget': _widget_actions,
    'gamepad_mode': lambda name, path: _gamepad_actions(name),
    'launcher': lambda name, path: _launcher_actions(name),
}

# What makes a directory an add-on of its kind rather than a folder that
# happens to live next to some. `data/titantts engines/espeak/` is the reason
# this exists: it is bundled binaries, not an engine, and offering to configure
# it would be offering something that cannot work.
_REQUIRED_FILE = {
    'tts_engine': ('__engine__.TCE',),
    'component': ('__component__.TCE',),
    'im_module': ('__im.TCE',),
    'launcher': ('__launcher__.TCE',),
    'statusbar_applet': ('applet.json',),
    'widget': ('init.py', 'init.pyc'),
}


def _is_real_addon(addon):
    required = _REQUIRED_FILE.get(addon.kind)
    if not required:
        return True
    return any(os.path.isfile(os.path.join(addon.path, name))
               for name in required)


def standard_actions(addon):
    """The actions every add-on of this kind offers, as ActionSpecs.

    Anything the add-on declared for itself keeps its own definition: the
    author knows better than the kind does.
    """
    factory = _BY_KIND.get(addon.kind)
    if factory is None or not _is_real_addon(addon):
        return []
    try:
        specs = factory(addon.name, addon.path)
    except Exception as e:
        print(f"[actions] Standard actions for {addon.kind} "
              f"'{addon.name}': {e}")
        return []
    declared = {action.name for action in addon.actions}
    out = []
    for name, summary, params, risk, run in specs:
        if name in declared:
            continue
        action = ActionSpec(name=name, summary=summary, params=params,
                            risk=risk, mode='any', addon=addon)
        action.run = run
        out.append(action)
    return out

"""Titan's own subsystems, as actions any add-on can call.

An add-on should never have to reimplement Titan. A component that wants to
change the volume, switch the gamepad mode, post to Titan-Net, read a setting
or have an inaccessible window read out should ask Titan, exactly as it asks
another add-on:

    from src.titan_core import actions

    actions.run('system', 'set_volume', percent=30)
    actions.run('gamepad', 'set_mode', mode='screen reader')
    actions.run('titannet', 'post_topic', title=..., content=...)
    actions.run('titan', 'set_setting', key='rate', value='60')

and from an application, in its own process, the same thing over the bus:

    from src.titan_core.titan_actions import call
    call('system', 'set_volume', percent=30)

Most of these providers are **adapted, not rewritten**: ``src/ai/tools/`` already
holds a careful implementation of each subsystem, so the tool tables there are
turned into actions here. One implementation, two audiences - the AI keeps
calling them as tools, everybody else calls them as actions, and a fix to
either is a fix to both.

``gamepad`` is the exception, written here directly, because switching modes
was previously only reachable by holding a trigger on the pad itself.
"""

from src.titan_core.actions.manifest import ActionSpec, AddonActions

# addon id -> (label, description, tool-module, factory, tool-name prefix)
_TOOL_PROVIDERS = (
    ('titan', "Titan",
     "Titan itself: its settings, components, add-ons, TTS engines and windows.",
     'src.ai.titan_tools', 'get_titan_tools', 'titan_'),
    ('settings', "Titan settings",
     "Finding and explaining Titan's settings by what they do.",
     'src.ai.tools.settings_tools', 'get_settings_tools', 'titan_'),
    ('system', "The computer",
     "The computer's own settings: volume, playback device, brightness, power "
     "plan, theme, Wi-Fi, whether Titan starts with Windows.",
     'src.ai.tools.system_tools', 'get_system_tools', 'system_'),
    ('titannet', "Titan-Net",
     "Titan-Net: forum topics and replies, mail, groups, rooms and private "
     "messages.",
     'src.ai.tools.titannet_tools', 'get_titannet_tools', 'titannet_'),
    ('elten', "Elten",
     "Elten: private messages, forums and blogs.",
     'src.ai.tools.elten_tools', 'get_elten_tools', 'elten_'),
    ('im', "Titan IM",
     "The web-backed messengers (WhatsApp, Messenger): conversations, "
     "messages, reactions and participants.",
     'src.ai.tools.im_tools', 'get_im_tools', 'im_'),
    ('ocr', "AI OCR",
     "Reading a window that has no accessibility, and pressing what it finds.",
     'src.ai.tools.ocr_tools', 'get_ocr_tools', 'ocr_'),
    ('memory', "AI memory",
     "What the AI remembers between conversations.",
     'src.ai.memory', 'get_memory_tools', 'ai_'),
)

BUILTIN_IDS = tuple(entry[0] for entry in _TOOL_PROVIDERS) + ('gamepad',)


# --------------------------------------------------------------------------- #
# Adapting a tool table into actions
# --------------------------------------------------------------------------- #
def _params_from_schema(schema):
    """An agent tool's JSON schema, as the manifest's parameter descriptors."""
    properties = (schema or {}).get('properties') or {}
    required = set((schema or {}).get('required') or [])
    params = {}
    for name, spec in properties.items():
        params[name] = {
            'type': spec.get('type', 'string'),
            'description': spec.get('description', ''),
            'required': name in required,
        }
        if spec.get('enum'):
            params[name]['enum'] = list(spec['enum'])
    return params


def _addon_from_tools(addon_id, label, description, tools, prefix):
    addon = AddonActions(kind='builtin', addon_id=addon_id, name=addon_id,
                         path='', label=label, description=description,
                         transport='inproc')
    addon.source = 'builtin'
    addon.builtin = True
    for tool in tools:
        name = tool.get('name', '')
        if not name:
            continue
        # 'system_set_volume' under the 'system' provider reads better as
        # system.set_volume - the provider already says which subsystem it is.
        short = name[len(prefix):] if prefix and name.startswith(prefix) else name
        action = ActionSpec(
            name=short,
            summary=tool.get('description', '') or short.replace('_', ' '),
            params=_params_from_schema(tool.get('parameters')),
            risk=('always_confirm' if tool.get('always_confirm')
                  else tool.get('risk', 'auto')),
            mode='any', promote=False, handler=short, addon=addon)
        action.run = tool['run']
        addon.actions.append(action)
    return addon


# --------------------------------------------------------------------------- #
# Gamepad modes
# --------------------------------------------------------------------------- #
def _mode_manager():
    from src.controller.controller_modes import get_mode_manager
    return get_mode_manager()


def _mode_entries(manager):
    """(label, entry) for everything in the mode cycle, built-in and custom."""
    return [(manager._mode_description(entry), entry)
            for entry in manager._mode_cycle()]


def gamepad_list_modes(**_):
    """List the gamepad modes, and say which one is active."""
    try:
        manager = _mode_manager()
        entries = _mode_entries(manager)
        current = manager._mode_description(manager._current_cycle_entry())
    except Exception as e:
        return f"Could not read the gamepad modes: {e}"
    if not entries:
        return "There are no gamepad modes."
    lines = [f"- {label}" + (" [active]" if label == current else "")
             for label, _entry in entries]
    return f"{len(entries)} gamepad modes:\n" + "\n".join(lines)


def gamepad_get_mode(**_):
    """Which gamepad mode is active."""
    try:
        manager = _mode_manager()
        return (f"The gamepad is in "
                f"{manager._mode_description(manager._current_cycle_entry())}.")
    except Exception as e:
        return f"Could not read the gamepad mode: {e}"


def gamepad_set_mode(mode, **_):
    """Switch the gamepad to a named mode."""
    wanted = str(mode or '').strip().lower()
    if not wanted:
        return "Say which mode."
    try:
        manager = _mode_manager()
        entries = _mode_entries(manager)
    except Exception as e:
        return f"Could not reach the gamepad modes: {e}"
    match = None
    for label, entry in entries:
        if label.lower() == wanted:
            match = (label, entry)
            break
    if match is None:
        for label, entry in entries:
            if wanted in label.lower():
                match = (label, entry)
                break
    if match is None:
        available = ", ".join(label for label, _e in entries)
        return f"There is no gamepad mode called '{mode}'. Available: {available}."
    try:
        manager.change_mode(match[1])
    except Exception as e:
        return f"Could not switch to {match[0]}: {e}"
    return f"The gamepad is now in {match[0]}."


def gamepad_cycle_mode(backward=False, **_):
    """Move to the next gamepad mode, as holding a trigger would."""
    try:
        manager = _mode_manager()
        if str(backward).strip().lower() in ('1', 'true', 'yes', 'on'):
            manager.cycle_mode_backward()
        else:
            manager.cycle_mode()
        return (f"The gamepad is now in "
                f"{manager._mode_description(manager._current_cycle_entry())}.")
    except Exception as e:
        return f"Could not change the gamepad mode: {e}"


def _gamepad_addon():
    addon = AddonActions(kind='builtin', addon_id='gamepad', name='gamepad',
                         path='', label="Gamepad",
                         description="The gamepad's operating modes - system, "
                                     "controller, screen reader, screen "
                                     "keyboard, and any custom mode installed.",
                         transport='inproc')
    addon.source = 'builtin'
    addon.builtin = True
    string = {'type': 'string'}
    boolean = {'type': 'boolean'}
    specs = (
        ('list_modes', "List the gamepad modes and say which one is active.",
         {}, 'auto', gamepad_list_modes),
        ('get_mode', "Say which gamepad mode is active.",
         {}, 'auto', gamepad_get_mode),
        ('set_mode', "Switch the gamepad to a named mode.",
         {'mode': dict(string, description="The mode's name, e.g. 'screen "
                       "reader mode'.", required=True)},
         'confirm', gamepad_set_mode),
        ('cycle_mode', "Move to the next gamepad mode, as holding a trigger "
                       "on the pad would.",
         {'backward': dict(boolean, description="Go to the previous mode "
                           "instead.")},
         'confirm', gamepad_cycle_mode),
    )
    for name, summary, params, risk, run in specs:
        prepared = {}
        for pname, pspec in params.items():
            prepared[pname] = {'type': pspec.get('type', 'string'),
                               'description': pspec.get('description', ''),
                               'required': bool(pspec.get('required'))}
        action = ActionSpec(name=name, summary=summary, params=prepared,
                            risk=risk, mode='any', addon=addon)
        action.run = run
        addon.actions.append(action)
    return addon


# --------------------------------------------------------------------------- #
# Building them all
# --------------------------------------------------------------------------- #
def build():
    """Every built-in provider that can be loaded right now.

    Each is imported separately: a subsystem whose optional dependency is
    missing must cost only itself, not the whole set.
    """
    addons = []
    for addon_id, label, description, module_name, factory, prefix in _TOOL_PROVIDERS:
        try:
            module = __import__(module_name, fromlist=[factory])
            tools = getattr(module, factory)()
        except Exception as e:
            print(f"[actions] Built-in '{addon_id}' unavailable: {e}")
            continue
        addon = _addon_from_tools(addon_id, label, description, tools, prefix)
        if addon.actions:
            addons.append(addon)
    try:
        addons.append(_gamepad_addon())
    except Exception as e:
        print(f"[actions] Built-in 'gamepad' unavailable: {e}")
    return addons

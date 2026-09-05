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
    # Driving the computer itself. Without these the Action API could reach
    # every add-on and every Titan subsystem but could not press a key, so
    # "automate anything" stopped at the edge of Titan - and a macro had to go
    # back to replaying keystrokes blindly to get any further.
    ('desktop', "The desktop",
     "Driving the computer: the windows that are open, the keyboard and mouse, "
     "files, and launching programs.",
     'src.ai.agent_tools', 'get_desktop_tools', ''),
    ('ui', "Controls on screen",
     "The controls of any window by name: listing them, pressing one, "
     "scrolling and dragging - Windows' own accessibility, so it works where "
     "there is no add-on to ask.",
     'src.ai.ui_tools', 'get_ui_tools', ''),
    ('web', "Web browser",
     "The user's own browser: opening pages, reading them, filling forms and "
     "pressing what is on them.",
     'src.ai.browser_tools', 'get_browser_tools', 'browser_'),
)

BUILTIN_IDS = (tuple(entry[0] for entry in _TOOL_PROVIDERS)
               + ('gamepad', 'shell', 'elten_client'))

# The actions that are actually DONE BY A MODEL - the ones that send something
# to an AI provider. Only these need Titan's AI features switched on, and
# `dispatch.run` says so plainly rather than letting them fail inside a provider
# with no key.
#
# The list is short on purpose, and it is per ACTION rather than per provider:
# living in `src/ai/` is not the same as calling a model. AI OCR *reads* a
# window with a vision request, but pressing, typing into and toggling what it
# already read are ordinary UI Automation, and the memory tools are a file of
# notes - all of which keep working with the AI switched off. Everything else
# in the Action API is ordinary Python, which is the point of it being a
# titan-core capability rather than an AI one.
_AI_ACTIONS = frozenset({
    'ocr.read_window',      # takes a picture of the window and asks a model
    'ocr.ask',              # the same, with a question about it
})


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
            mode='any', promote=False, handler=short, addon=addon,
            # A tool may also say so itself, which is how a new AI-backed one
            # gets this without anybody remembering to edit the list above.
            needs_ai=(f"{addon_id}.{short}" in _AI_ACTIONS
                      or bool(tool.get('needs_ai'))))
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


def _elten_client_addon():
    """The Elten client running on this machine, as it sees itself.

    Not the same thing as the `elten` provider, which signs in to EltenLink
    over the network and asks the SERVER. This one is answered from INSIDE
    the Elten process by the TCE bridge add-on, so it can say what Elten is
    actually showing - the notifications its own service is holding, who is
    signed in to it, and that it is running at all.
    """
    from src.titan_core.elten_client_actions import get_elten_client_actions
    addon = AddonActions(kind='builtin', addon_id='elten_client',
                         name='elten_client', path='',
                         label="The Elten client",
                         description="The Elten client running on this "
                                     "machine, answered from inside it by "
                                     "the TCE bridge: whether it is running, "
                                     "who is signed in, and the "
                                     "notifications Elten itself is holding.",
                         transport='inproc')
    addon.source = 'builtin'
    addon.builtin = True
    for name, summary, params, risk, run in get_elten_client_actions():
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


def _shell_addon():
    """The system shell: the desktop, taskbar, notification area and menu.

    Written here rather than adapted from a tool table because the shell is
    not an AI subsystem - it is what Titan puts on the screen when it
    replaces the system interface, and a macro asking "which windows are
    open" or "open this desktop icon" should not have to go near a model.
    """
    from src.shell.shell_actions import get_shell_actions

    addon = AddonActions(kind='builtin', addon_id='shell', name='shell',
                         path='', label="System shell",
                         description="Titan's own desktop, taskbar, "
                                     "notification area and Start menu, and "
                                     "the windows that are open on them.",
                         transport='inproc')
    addon.source = 'builtin'
    addon.builtin = True
    for name, summary, params, risk, run in get_shell_actions():
        prepared = {}
        for pname, pspec in params.items():
            prepared[pname] = {'type': pspec.get('type', 'string'),
                               'description': pspec.get('description', ''),
                               'required': bool(pspec.get('required'))}
            if pspec.get('enum'):
                prepared[pname]['enum'] = list(pspec['enum'])
        action = ActionSpec(name=name, summary=summary, params=prepared,
                            risk=risk, mode='any', addon=addon)
        action.run = run
        addon.actions.append(action)
    return addon


# --------------------------------------------------------------------------- #
# Building them all
# --------------------------------------------------------------------------- #



def _extend(addons, addon_id, specs):
    """Add hand-written actions to a provider that already exists.

    The provider is built from a tool table, which answers the questions a
    model asks; these answer the ones a WINDOW asks - give me the rows, give
    me the categories, give me the tab bar. They belong on the same provider
    because a caller looking for Titan-Net should not have to know which
    half of it they want.
    """
    target = next((a for a in addons if a.addon_id == addon_id), None)
    if target is None:
        return
    taken = {action.name for action in target.actions}
    for name, summary, params, risk, run in specs:
        if name in taken:
            continue
        prepared = {}
        for pname, pspec in params.items():
            prepared[pname] = {'type': pspec.get('type', 'string'),
                               'description': pspec.get('description', ''),
                               'required': bool(pspec.get('required'))}
        action = ActionSpec(name=name, summary=summary, params=prepared,
                            risk=risk, mode='any', addon=target)
        action.run = run
        target.actions.append(action)


def _add_titannet_data(addons):
    """Titan-Net as records rather than as sentences, for a client."""
    from src.network.titannet_actions import (get_titannet_data_actions,
                                              get_titannet_place_actions,
                                              get_titannet_hub_actions)
    _extend(addons, 'titannet', get_titannet_data_actions())
    _extend(addons, 'titannet', get_titannet_place_actions())
    _extend(addons, 'titannet', get_titannet_hub_actions())


def _add_main_window(addons):
    """Titan's own tab bar, status bar and Program menu."""
    from src.ui.main_window_actions import get_main_window_actions
    _extend(addons, 'titan', get_main_window_actions())




def _add_titan_face(addons):
    """The categories Titan's own non-visual interface has: the widgets, the
    components' menu, the buffers, the notifications."""
    from src.ui.main_window_actions import get_titan_face_actions
    _extend(addons, 'titan', get_titan_face_actions())



def _add_ai_questions(addons):
    """Asking Titan's AI from somewhere that has no window of its own."""
    from src.titan_core.reader_actions import (get_ai_actions,
                                               get_ai_history_actions)
    _extend(addons, 'titan', get_ai_actions())
    _extend(addons, 'titan', get_ai_history_actions())



def _add_bridge(addons):
    """The bridge's own doorway: one action for a whole typed surface.

    Everything else here is an action per thing, which is right for a model
    and for macros. A program that is rebuilding Titan's interface needs the
    opposite - one call, one shape, and a version it can compare with its
    own - so `src/titan_core/bridge_api.py` is offered as a single action
    rather than as forty.
    """
    from src.titan_core.bridge_api import get_bridge_actions
    _extend(addons, 'titan', get_bridge_actions())


def _add_reader(addons):
    """Titan's voice, as a reader living in another program needs it."""
    from src.titan_core.reader_actions import get_reader_actions
    _extend(addons, 'titan', get_reader_actions())


def _add_settings_ui(addons):
    """Titan's settings WINDOW, added to the `settings` provider.

    The tools that provider is built from answer "which setting does what";
    these answer "show me the settings", which is a different question and
    the one a program drawing its own settings screen asks. They live on the
    same provider because a caller looking for the settings should not have
    to know which half of them it wants.
    """
    from src.settings.settings_actions import get_settings_ui_actions

    target = next((a for a in addons if a.addon_id == 'settings'), None)
    if target is None:
        return
    taken = {action.name for action in target.actions}
    for name, summary, params, risk, run in get_settings_ui_actions():
        if name in taken:
            continue
        prepared = {}
        for pname, pspec in params.items():
            prepared[pname] = {'type': pspec.get('type', 'string'),
                               'description': pspec.get('description', ''),
                               'required': bool(pspec.get('required'))}
        action = ActionSpec(name=name, summary=summary, params=prepared,
                            risk=risk, mode='any', addon=target)
        action.run = run
        target.actions.append(action)



def _addon_actions_json(addon='', **_):
    """Every action of one add-on as JSON: name, summary, parameters, risk.

    `list_addons` carries the action NAMES, which is enough to navigate but
    not enough to draw a screen: a program showing somebody Titan's add-ons
    wants to say what an action does and to ask for its parameters properly,
    rather than offering a bare word and finding out afterwards. Written
    here rather than as a tool because a model already has `describe`, which
    is the same thing in prose.
    """
    import json

    from src.titan_core.actions import dispatch

    wanted = str(addon or '').strip()
    if not wanted:
        return "Say which add-on to describe."
    actions = dispatch.list_actions(wanted)
    if not actions:
        return f"No Titan add-on called '{wanted}' offers actions."
    described = []
    for action in actions:
        described.append({
            'name': action.name,
            'summary': action.summary,
            'risk': action.risk,
            'needs_ai': bool(action.needs_ai),
            'params': [{'name': name,
                        'type': spec.get('type', 'string'),
                        'description': spec.get('description', ''),
                        'required': bool(spec.get('required')),
                        'enum': list(spec.get('enum') or [])}
                       for name, spec in (action.params or {}).items()],
        })
    return json.dumps({'addon': wanted, 'actions': described},
                      ensure_ascii=False)



def _inventory_json(kind='', **_):
    """Every add-on INSTALLED, as JSON - not only those offering actions.

    `list_addons` answers "what can be driven", which is the right question
    for a macro and the wrong one for a screen: most applications declare no
    actions at all, so a window built from that list would show a user four
    applications out of forty. This walks the same directories Titan's own
    lists are built from, so an alternative interface shows what Titan's own
    window shows.
    """
    import json

    from src.ai import titan_tools

    wanted = str(kind or '').strip().lower()
    kinds = titan_tools._ADDON_KINDS
    if wanted and wanted not in kinds:
        return (f"Unknown add-on kind '{wanted}'. Known kinds: "
                + ", ".join(kinds.keys()))
    chosen = [wanted] if wanted else list(kinds.keys())

    # Applications, games and Titan IM modules are listed by the name Titan
    # itself shows AND accepts: `_discover_kind` answers with FOLDER names,
    # and `titan.launch` matches against the name in the manifest, so a
    # folder called `tcalc` holding an application called "Kalkulator" was
    # listed as tcalc and then could not be launched by that name. The other
    # kinds have no launcher and keep the directory listing.
    launchable = {}
    try:
        for kind, name, _run in titan_tools._all_launchable():
            launchable.setdefault(kind, []).append(name)
    except Exception:
        launchable = {}

    out = []
    for kid in chosen:
        label, subdir, is_resource = kinds[kid]
        names = launchable.get(kid)
        if names is None:
            try:
                names = titan_tools._discover_kind(subdir, is_resource)
            except Exception:
                names = []
        out.append({'kind': kid, 'label': label, 'entries': list(names)})
    return json.dumps({'kinds': out}, ensure_ascii=False)


def _add_inventory(addons):
    """`titan.inventory`, for a program drawing Titan's own lists."""
    target = next((a for a in addons if a.addon_id == 'titan'), None)
    if target is None:
        return
    if any(action.name == 'inventory' for action in target.actions):
        return
    action = ActionSpec(
        name='inventory',
        summary="Every add-on installed, as JSON, by kind - applications, "
                "games, components, Titan IM modules, statusbar applets and "
                "the rest. What a window listing them needs.",
        params={'kind': {'type': 'string', 'required': False,
                         'description': "One kind only, e.g. 'app'."}},
        risk='auto', mode='any', addon=target)
    action.run = _inventory_json
    target.actions.append(action)


def _add_addon_details(addons):
    """`titan.addon_actions`, for a program drawing Titan's own add-on list."""
    target = next((a for a in addons if a.addon_id == 'titan'), None)
    if target is None:
        return
    if any(action.name == 'addon_actions' for action in target.actions):
        return
    action = ActionSpec(
        name='addon_actions',
        summary="Every action one add-on offers, as JSON: name, summary, "
                "parameters and risk. What a screen needs to show them.",
        params={'addon': {'type': 'string', 'required': True,
                          'description': "The add-on's id, from list_addons."}},
        risk='auto', mode='any', addon=target)
    action.run = _addon_actions_json
    target.actions.append(action)

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
    try:
        addons.append(_shell_addon())
    except Exception as e:
        print(f"[actions] Built-in 'shell' unavailable: {e}")
    try:
        addons.append(_elten_client_addon())
    except Exception as e:
        print(f"[actions] Built-in 'elten_client' unavailable: {e}")
    try:
        _add_settings_ui(addons)
    except Exception as e:
        print(f"[actions] The settings window is not reachable: {e}")
    try:
        _add_addon_details(addons)
    except Exception as e:
        print(f"[actions] Add-on details unavailable: {e}")
    try:
        _add_inventory(addons)
    except Exception as e:
        print(f"[actions] The add-on inventory is unavailable: {e}")
    try:
        _add_titannet_data(addons)
    except Exception as e:
        print(f"[actions] Titan-Net records are unavailable: {e}")
    try:
        _add_main_window(addons)
    except Exception as e:
        print(f"[actions] Titan's main window is unreadable: {e}")
    try:
        _add_reader(addons)
    except Exception as e:
        print(f"[actions] The reader speech path is unavailable: {e}")
    try:
        _add_titan_face(addons)
    except Exception as e:
        print(f"[actions] Titan's other categories are unreadable: {e}")
    try:
        _add_ai_questions(addons)
    except Exception as e:
        print(f"[actions] Asking the AI is unavailable: {e}")
    try:
        _add_bridge(addons)
    except Exception as e:
        print(f"[actions] The bridge doorway is unavailable: {e}")
    return addons

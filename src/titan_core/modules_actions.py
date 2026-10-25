# -*- coding: utf-8 -*-
"""The Component Manager as actions: the ``modules`` provider.

Everything the window does is here too, so the AI, a macro, a Titan Script,
an external client (the NVDA add-on, the Elten bridge) and a component can
list Titan's modules, ask whether one is on, and switch it - without the
window. Answers are prose, like every action; they name the module the way
the user knows it, and say when a change waits for a restart.
"""

from src.titan_core import modules


def _kind_for(kind):
    """Accept a kind id ('app'), its subdir ('applications') or its label."""
    wanted = str(kind or '').strip().lower()
    if not wanted:
        return ''
    for kind_id in modules.all_kinds():
        if wanted in (kind_id, (modules.subdir_of(kind_id) or '').lower(),
                      modules.kind_label(kind_id).lower()):
            return kind_id
    if wanted in ('services', 'built-in', 'builtin'):
        return 'service'
    return None


def _state(module):
    text = "on" if module.enabled else "off"
    if modules.waits_for_restart(module):
        text += " (changed, takes effect after Titan restarts)"
    return text


def _one(name, kind):
    """(module, None) or (None, the sentence that explains why not)."""
    kind_id = _kind_for(kind)
    if kind_id is None:
        return None, (f"There is no kind of module called '{kind}'. Kinds: "
                      + ", ".join(modules.all_kinds()) + ".")
    found = modules.find_by_name(name, kind_id or None)
    if not found:
        return None, f"There is no module called '{name}'."
    if len(found) > 1:
        names = "; ".join(f"{m.name} ({m.kind}: {m.id})" for m in found[:12])
        return None, (f"'{name}' could be several modules: {names}. "
                      "Say which, or name the kind.")
    return found[0], None


def list_modules(kind='', **_):
    """Every module of one kind, or of all of them, with its state."""
    kind_id = _kind_for(kind)
    if kind_id is None:
        return (f"There is no kind of module called '{kind}'. Kinds: "
                + ", ".join(modules.all_kinds()) + ".")
    kinds = (kind_id,) if kind_id else modules.all_kinds()
    lines = []
    for kind_name in kinds:
        found = modules.modules(kind_name)
        if not found:
            continue
        lines.append(f"{modules.kind_label(kind_name)} ({kind_name}):")
        for module in found:
            lines.append(f"- {module.name} [{module.id}]: {_state(module)}")
    if not lines:
        return "There are no modules of that kind."
    return "\n".join(lines)


def module_status(name='', kind='', **_):
    module, problem = _one(name, kind)
    if problem:
        return problem
    text = f"{module.name} ({modules.kind_label(module.kind)}) is {_state(module)}."
    if module.description:
        text += f" {module.description}"
    return text


def _switch(name, kind, enabled):
    module, problem = _one(name, kind)
    if problem:
        return problem
    if module.enabled == enabled:
        return f"{module.name} is already {'on' if enabled else 'off'}."
    change = modules.set_enabled(module, enabled)
    if not change.ok:
        return f"{module.name} could not be switched: {change.message}"
    text = f"{module.name} is now {'on' if enabled else 'off'}."
    if change.needs_restart and modules.waits_for_restart(module):
        text += " It takes effect after Titan restarts (modules.restart_titan)."
    return text


def enable_module(name='', kind='', **_):
    return _switch(name, kind, True)


def disable_module(name='', kind='', **_):
    return _switch(name, kind, False)


def pending_changes(**_):
    pending = modules.pending_restart()
    if not pending:
        return "Nothing waits for a restart."
    return ("These changes take effect after Titan restarts: "
            + ", ".join(sorted(pending)) + ".")


def open_manager(**_):
    """Put the Component Manager window up."""
    try:
        import wx
        if wx.GetApp() is None:
            return "Titan has no window to open the TCE Environment Manager in."

        def show():
            from src.ui.componentmanagergui import show_component_manager
            manager = None
            for window in wx.GetTopLevelWindows():
                manager = getattr(window, 'component_manager', None)
                if manager is not None:
                    break
            show_component_manager(None, manager)

        wx.CallAfter(show)
        return "The TCE Environment Manager is open."
    except Exception as error:
        return f"The TCE Environment Manager could not be opened: {error}"


def restart_titan(**_):
    if modules.restart_titan():
        return "Titan is restarting."
    return "Titan could not be restarted."


def modules_addon():
    from src.titan_core.actions.manifest import ActionSpec, AddonActions
    addon = AddonActions(kind='builtin', addon_id='modules', name='modules',
                         path='', label="TCE Environment Manager",
                         description="Switch any part of Titan on or off: its "
                                     "built-in services (Telegram, Titan-Net, "
                                     "AI features, ...) and every installed "
                                     "add-on - components, applications, "
                                     "games, Titan IM modules, TTS engines, "
                                     "gamepad modes, widgets, statusbar "
                                     "applets, shell add-ons, settings "
                                     "interfaces, launchers and macros.",
                         transport='inproc')
    addon.source = 'builtin'
    addon.builtin = True
    name = {'type': 'string', 'required': True,
            'description': "The module's name or identifier, e.g. 'Telegram' "
                           "or 'tNotes'."}
    kind = {'type': 'string',
            'description': "Optional kind to narrow the search: service, "
                           "component, app, game, im_module, tts_engine, "
                           "gamepad_mode, widget, statusbar_applet, "
                           "shell_addon, settings_interface, launcher, macro."}
    specs = (
        ('list_modules', "List Titan's modules with whether each is on; "
                         "optionally of one kind.",
         {'kind': kind}, 'auto', list_modules),
        ('module_status', "Say whether one module is on, and what it is.",
         {'name': name, 'kind': kind}, 'auto', module_status),
        ('enable_module', "Switch a module on.",
         {'name': name, 'kind': kind}, 'confirm', enable_module),
        ('disable_module', "Switch a module off.",
         {'name': name, 'kind': kind}, 'confirm', disable_module),
        ('pending_changes', "Say which changes wait for Titan to restart.",
         {}, 'auto', pending_changes),
        ('open_manager', "Open the TCE Environment Manager window.",
         {}, 'auto', open_manager),
        ('restart_titan', "Restart Titan so waiting changes take effect.",
         {}, 'always_confirm', restart_titan),
    )
    for action_name, summary, params, risk, run in specs:
        prepared = {pname: {'type': spec.get('type', 'string'),
                            'description': spec.get('description', ''),
                            'required': bool(spec.get('required'))}
                    for pname, spec in params.items()}
        action = ActionSpec(name=action_name, summary=summary, params=prepared,
                            risk=risk, mode='any', addon=addon)
        action.run = run
        addon.actions.append(action)
    return addon

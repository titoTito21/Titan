"""Turning Titan's Action API into tools the AI can call.

``src.titan_core.actions`` is the general capability - any part of Titan uses
it. This module is the AI's view of it: it reads the registry and produces
agent tools, applies the user's permission settings, and keeps the tool list
from growing without bound.

**The tool budget.** A dozen add-ons offering half a dozen actions each is
several hundred tools; providers cap the list, and a long list measurably
degrades which tool a model picks. So the list is two-tier:

- an action marked ``"promote": true`` becomes a first-class tool named
  ``<addon>_<action>``, up to ``PROMOTED_BUDGET`` of them - this is where the
  everyday things go ("play something", "open a file"), and the model calls
  them directly with typed arguments;
- everything else stays reachable through ``titan_list_actions`` and
  ``titan_run_action``, which cost two tool slots no matter how many add-ons
  the user installs.
"""

import json

from src.settings.settings import get_setting
from src.titan_core import actions as core_actions
from src.titan_core.actions.kinds import kind_label

_SETTINGS_SECTION = 'ai'

PROMOTED_BUDGET = 60

# A promoted tool from an add-on is still add-on code doing something on the
# user's machine, so it can never be quieter than this.
_MIN_RISK = {'auto': 'auto', 'confirm': 'confirm', 'always_confirm': 'confirm'}


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
def actions_enabled():
    """Master switch: Settings -> AI features -> 'Let the AI use add-on
    functions'."""
    value = get_setting('addon_actions', True, section=_SETTINGS_SECTION)
    return str(value).strip().lower() not in ('0', 'false', 'no', 'off')


def blocked_addons():
    """Add-ons the user has excluded, by id."""
    raw = get_setting('addon_actions_blocked', '', section=_SETTINGS_SECTION)
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = str(raw or '').replace(';', ',').split(',')
    return {str(item).strip().lower() for item in items if str(item).strip()}


def allowed(addon):
    return addon.addon_id not in blocked_addons()


def _available_addons():
    """The *installed* add-ons the AI may drive.

    Titan's own subsystems are deliberately left out: the AI already has every
    one of them as a first-class tool (``system_set_volume``,
    ``titannet_post_topic``, ...), so listing them again here would repeat
    sixty tools inside a tool result and invite the model to reach them the
    long way round. They stay callable through titan_run_action for anyone who
    asks for them by name.
    """
    if not actions_enabled():
        return []
    return [addon for addon in core_actions.get_registry().addons
            if allowed(addon) and not getattr(addon, 'builtin', False)]


# --------------------------------------------------------------------------- #
# The generic pair - always present, however many add-ons there are
# --------------------------------------------------------------------------- #
def titan_list_actions(addon="", kind="", **_):
    """List what Titan's add-ons can be asked to do."""
    if not actions_enabled():
        return ("Add-on functions are switched off in Settings -> AI features "
                "('Let the AI use add-on functions').")
    wanted = (addon or '').strip()
    if wanted:
        found = core_actions.get_registry().by_id(wanted)
        if found is None or not allowed(found):
            return (f"No add-on called '{wanted}' offers actions. Call "
                    f"titan_list_actions with no arguments to see what does.")
        return core_actions.describe_addon(found.addon_id)

    addons = _available_addons()
    kind_filter = (kind or '').strip().lower()
    if kind_filter:
        addons = [a for a in addons if a.kind == kind_filter]
    if not addons:
        return ("No installed add-on declares any actions yet. Add-ons expose "
                "their functions with an __actions.json manifest.")
    lines = ["Titan add-ons you can drive, and what each one offers.",
             "Run one with titan_run_action(addon, action, args).", ""]
    for addon_info in addons:
        state = ''
        if addon_info.transport == 'process':
            state = " [running]" if getattr(addon_info, 'running', False) else ""
        lines.append(f"{addon_info.label} ({addon_info.addon_id}) - "
                     f"{kind_label(addon_info.kind)}{state}")
        if addon_info.description:
            lines.append(f"  {addon_info.description}")
        for action in addon_info.actions:
            lines.append(f"  {action.describe()}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _parse_args(raw):
    """``args`` arrives as a JSON object, or as a JSON string, because the
    three providers disagree about nested objects."""
    if raw in (None, ''):
        return {}, ''
    if isinstance(raw, dict):
        return raw, ''
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}, ''
        try:
            parsed = json.loads(text)
        except Exception as e:
            return {}, f"'args' is not valid JSON: {e}"
        if not isinstance(parsed, dict):
            return {}, "'args' must be a JSON object, e.g. {\"path\": \"C:/a.txt\"}"
        return parsed, ''
    return {}, "'args' must be a JSON object."


def titan_run_action(addon, action, args="", **_):
    """Run any action any add-on declares."""
    if not actions_enabled():
        return ("Add-on functions are switched off in Settings -> AI features "
                "('Let the AI use add-on functions').")
    found = core_actions.get_registry().by_id(addon or '')
    if found is not None and not allowed(found):
        return (f"The user has excluded '{found.label}' from AI control "
                f"(Settings -> AI features).")
    parsed, error = _parse_args(args)
    if error:
        return error
    result = core_actions.run(addon or '', action or '', **parsed)
    return result.text


# --------------------------------------------------------------------------- #
# Promoted actions - first-class tools
# --------------------------------------------------------------------------- #
def titan_run_actions(steps, stop_on_error=True, **_):
    """Run several add-on actions in order, as one composite command."""
    if not actions_enabled():
        return ("Add-on functions are switched off in Settings -> AI features "
                "('Let the AI use the functions add-ons offer').")
    parsed, error = _parse_args(steps) if isinstance(steps, str) else (steps, '')
    if isinstance(steps, str):
        # A list is what this tool wants, and _parse_args only accepts objects.
        try:
            parsed = json.loads(steps)
        except Exception as e:
            return (f"'steps' is not valid JSON: {e}. It should be a list like "
                    f'[{{"addon": "tnotes", "action": "create_note", '
                    f'"args": {{"title": "..."}}}}]')
    if not isinstance(parsed, list) or not parsed:
        return ("'steps' must be a non-empty list of "
                '{"addon": ..., "action": ..., "args": {...}} objects.')
    blocked = blocked_addons()
    for step in parsed:
        if isinstance(step, dict) and str(step.get('addon', '')).lower() in blocked:
            return (f"The user has excluded '{step.get('addon')}' from AI "
                    f"control (Settings -> AI features), so this sequence was "
                    f"not run.")
    stop = str(stop_on_error).strip().lower() not in ('0', 'false', 'no', 'off')
    try:
        outcome = core_actions.run_sequence(parsed, stop_on_error=stop)
    except Exception as e:
        return f"The sequence could not be run: {e}"
    text = outcome.text
    if outcome.pending and outcome.question is not None:
        text += ("\n" + outcome.question.as_text()
                 + " Then run the remaining steps.")
    return text


def _make_runner(addon_id, action_name):
    def run(**args):
        if not actions_enabled():
            return ("Add-on functions are switched off in Settings -> AI "
                    "features.")
        return core_actions.run(addon_id, action_name, **args).text
    return run


def _promoted_tools(_tool):
    tools = []
    seen = set()
    for addon in _available_addons():
        for action in addon.actions:
            if not action.promote:
                continue
            name = action.tool_name
            if name in seen:
                continue
            if len(tools) >= PROMOTED_BUDGET:
                return tools
            seen.add(name)
            schema = action.json_schema()
            description = (f"{action.summary} "
                           f"({addon.label}, a Titan {kind_label(addon.kind).lower()[:-1]})")
            tools.append(_tool(
                name, description.strip(),
                _make_runner(addon.addon_id, action.name),
                risk=_MIN_RISK.get(action.risk, 'confirm'),
                always_confirm=(action.risk == 'always_confirm'),
                properties=schema['properties'],
                required=schema['required']))
    return tools


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def get_action_tools():
    """Every tool that comes from the Action API."""
    from src.ai.agent_tools import _tool
    S = {'type': 'string'}

    tools = [
        _tool('titan_list_actions',
              "List the functions Titan's installed add-ons offer - "
              "applications, games, components, widgets, statusbar applets, "
              "TTS engines, gamepad modes, launchers and Titan IM modules. "
              "Use this whenever the user asks for something an add-on might "
              "do, before deciding it cannot be done. Pass 'addon' for one "
              "add-on's actions in detail.",
              titan_list_actions,
              properties={'addon': dict(S, description="One add-on's id (optional)."),
                          'kind': dict(S, description="Filter by kind: app, game, "
                                       "component, widget, statusbar_applet, "
                                       "tts_engine, gamepad_mode, launcher, "
                                       "im_module (optional).")}),
        _tool('titan_run_action',
              "Run one of the functions an add-on declares (see "
              "titan_list_actions). Titan delivers it to the running "
              "application when there is one, and starts it or runs the "
              "function on its own when there is not.",
              titan_run_action, risk='confirm',
              properties={'addon': dict(S, description="Add-on id, e.g. 'tedit'."),
                          'action': dict(S, description="Action name, e.g. 'open_file'."),
                          'args': dict(S, description="Arguments as a JSON object, "
                                       "e.g. {\"path\": \"C:/notes.txt\"}.")},
              required=['addon', 'action']),
        _tool('titan_run_actions',
              "Run several add-on actions in order, as one composite command - "
              "use this when the user asks for a chain of things ('write X, "
              "then save it, then remind me about it'). A later step can use "
              "what an earlier one returned by writing {{1}}, {{2}}... in a "
              "string argument. The run stops at the first step that fails or "
              "that needs an answer, and tells you which steps did happen.",
              titan_run_actions, risk='confirm',
              properties={'steps': dict(S, description=
                          'A JSON list of steps, e.g. [{"addon": "tnotes", '
                          '"action": "create_note", "args": {"title": "Shopping", '
                          '"text": "milk"}}, {"addon": "treminder", "action": '
                          '"create_reminder", "args": {"name": "Buy {{1}}", '
                          '"date": "tomorrow", "time": "17:00"}}]'),
                          'stop_on_error': {'type': 'boolean',
                                            'description': "Stop at the first "
                                            "failure (default true)."}},
              required=['steps']),
    ]
    try:
        tools.extend(_promoted_tools(_tool))
    except Exception as e:
        print(f"[action_tools] Could not build promoted action tools: {e}")
    return tools


def describe_action_tool(name, args):
    """A human sentence for a promoted add-on tool, so the transcript and the
    confirm dialog never show a raw ``tedit_open_file``. Returns None when the
    tool is not one of ours."""
    try:
        from src.titan_core.translation import _
    except Exception:
        def _(text):
            return text
    for addon in core_actions.get_registry().addons:
        for action in addon.actions:
            if action.tool_name != name:
                continue
            if name == 'titan_run_action':
                continue
            detail = ", ".join(f"{k}: {v}" for k, v in (args or {}).items()
                               if str(v).strip())[:80]
            sentence = _("{action} in {addon}").format(
                action=action.summary.rstrip('.'), addon=addon.label)
            return f"{sentence} ({detail})" if detail else sentence
    return None

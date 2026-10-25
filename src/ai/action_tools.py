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

# Characters of one titan_list_actions result before it collapses to names
# only. Roughly three thousand tokens - enough for every add-on a normal
# install has, small enough that the listing cannot swallow the conversation.
_LISTING_BUDGET = 12000

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
# What an add-on IS, told to the AI from the add-on as it stands now
# --------------------------------------------------------------------------- #
#: How to use the reader, which no listing of its actions can say. What it
#: CAN do is never written here: that is read out of the reader (below), so
#: the AI is never told about an older Titan Access than the one installed.
TITAN_ACCESS_GUIDANCE = (
    "TITAN ACCESS is Titan's own screen reader, reached through the add-on "
    "actions of 'titan_access' (titan_run_action addon='titan_access'). "
    "Reading the screen (read_screen, list_elements, page_summary, "
    "click_element) works even while the reader is switched off. Before "
    "telling the user what the reader can or cannot do, ask "
    "titan_access.about - it answers from the reader itself; never rely on "
    "what you remember about an earlier version. To write the user a "
    "reader script, read titan_access.script_language first and save it "
    "with titan_access.write_script, which refuses a script with a "
    "mistake. When the user says the reader is silent or wrong, start with "
    "titan_access.diagnostics and last_spoken. ")


def addon_briefing(addon_id):
    """What an installed add-on is and can do, from the add-on itself.

    An add-on that defines ``TITAN_AI_BRIEFING`` (a function answering a
    paragraph) is asked; otherwise its description and the names of its
    actions are used. Empty when it is not installed or the AI may not
    drive it - telling a model about actions it cannot call invites it to
    try."""
    try:
        addon = core_actions.find_addon(addon_id)
    except Exception:                                # noqa: BLE001
        return ''
    if addon is None or not actions_enabled() or not allowed(addon):
        return ''
    try:
        from src.titan_core.actions import inproc
        owners = inproc.candidate_owners(addon)
    except Exception:                                # noqa: BLE001
        owners = []
    for owner in owners:
        brief = getattr(owner, 'TITAN_AI_BRIEFING', None)
        if callable(brief):
            try:
                text = str(brief() or '').strip()
            except Exception:                        # noqa: BLE001
                text = ''
            if text:
                return text
    names = ', '.join(action.name for action in addon.actions)
    about = str(addon.description or '').strip()
    return (about + (' ' if about else '')
            + (f"Its actions: {names}." if names else '')).strip()


def titan_access_note():
    """The paragraph the agent's and the assistant's prompts carry about
    Titan Access: how to use it, and what it is now."""
    live = addon_briefing('titan_access')
    if not live:
        return ''
    return TITAN_ACCESS_GUIDANCE + "What it is now: " + live + " "


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

    def render(detailed):
        lines = ["Titan add-ons you can drive, and what each one offers.",
                 "Run one with titan_run_action(addon, action, args).", ""]
        for addon_info in addons:
            state = ''
            if addon_info.transport == 'process':
                state = (" [running]" if getattr(addon_info, 'running', False)
                         else "")
            lines.append(f"{addon_info.label} ({addon_info.addon_id}) - "
                         f"{kind_label(addon_info.kind)}{state}")
            if detailed:
                if addon_info.description:
                    lines.append(f"  {addon_info.description}")
                for action in addon_info.actions:
                    lines.append(f"  {action.describe()}")
                lines.append("")
            else:
                lines.append("  " + ", ".join(action.name
                                              for action in addon_info.actions))
        return "\n".join(lines).rstrip()

    full = render(True)
    if len(full) <= _LISTING_BUDGET:
        return full
    # Every add-on still appears - only the per-action detail is dropped, and
    # the model is told exactly how to get it back. A listing that grows with
    # the number of installed add-ons would eventually crowd out the
    # conversation it is meant to serve.
    return (render(False)
            + "\n\nOnly the names are shown because there are a lot of "
              "add-ons. Call titan_list_actions with 'addon' set to one id, or "
              "'kind' set to one kind, for what each action takes.")


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


def _declared_risk(addon_id, action_name):
    """What the action itself declares: 'auto', 'confirm' or
    'always_confirm'. An action that cannot be found is 'confirm' - the run
    will say it does not exist, and nothing unknown is waved through."""
    try:
        from src.titan_core.actions.registry import find_action
        addon, action = find_action(addon_id or '', action_name or '')
    except Exception:                                # noqa: BLE001
        return 'confirm'
    if addon is None or action is None:
        return 'confirm'
    return action.risk if action.risk in ('auto', 'confirm',
                                          'always_confirm') else 'confirm'


_RISK_ORDER = {'auto': 0, 'confirm': 1, 'always_confirm': 2}


def _run_action_risk(args):
    """``titan_run_action`` is one tool for every action of every add-on, so
    it asks only when the action it is about to run would. Marked 'confirm'
    whatever the action was, it asked before saying the time."""
    return _declared_risk(args.get('addon'), args.get('action'))


def _run_action_key(args):
    return f"{args.get('addon') or ''}.{args.get('action') or ''}".lower()


def _steps_of(args):
    steps = args.get('steps')
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except Exception:                            # noqa: BLE001
            return None
    return steps if isinstance(steps, list) else None


def _run_actions_risk(args):
    """The riskiest step decides for a sequence."""
    steps = _steps_of(args)
    if not steps:
        return 'confirm'
    worst = 'auto'
    for step in steps:
        if not isinstance(step, dict):
            return 'confirm'
        risk = _declared_risk(step.get('addon'), step.get('action'))
        if _RISK_ORDER[risk] > _RISK_ORDER[worst]:
            worst = risk
    return worst


def _run_actions_key(args):
    steps = _steps_of(args) or []
    return ','.join(sorted({
        f"{s.get('addon') or ''}.{s.get('action') or ''}".lower()
        for s in steps if isinstance(s, dict)}))


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
              risk_of=_run_action_risk, approval_key=_run_action_key,
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
              risk_of=_run_actions_risk, approval_key=_run_actions_key,
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

"""The public face of the Action API - what the rest of Titan calls.

    from src.titan_core import actions

    result = actions.run('tedit', 'open_file', path=r'C:\\notes.txt')
    if result:
        print(result.text)

``run`` never raises: an add-on that is missing, disabled, out of date, broken
or simply slow is an ordinary outcome here, not an exception, because the
callers are a screen-reader interface and an AI that both have to say something
sensible about it. ``result.ok`` says whether it worked and ``result.text`` is
always worth showing to a user. Code that prefers exceptions calls
``result.raised()``.
"""

import time

from src.titan_core.actions import bus, inproc, process
from src.titan_core.actions.interaction import Question, is_failure, is_question
from src.titan_core.actions.kinds import kind_label
from src.titan_core.actions.registry import find_action, get_registry


class ActionError(Exception):
    pass


class ActionResult:
    """The outcome of one action: truthy when it worked, printable always.

    Three outcomes, not two. Besides success and failure there is *pending* -
    the action needs something it was not given and has said what. A pending
    result is falsy, because nothing was done, but it is not a failure and
    ``question`` says how to turn it into one that is.
    """

    def __init__(self, ok, text, addon=None, action=None, elapsed=0.0,
                 question=None):
        self.ok = bool(ok)
        self.text = text or ''
        self.addon = addon
        self.action = action
        self.elapsed = elapsed
        self.question = question

    @property
    def pending(self):
        """The action asked for something instead of running."""
        return self.question is not None

    def __bool__(self):
        return self.ok

    def __str__(self):
        return self.text

    def __repr__(self):
        name = self.action.qualified if self.action else '?'
        return f"<ActionResult {name} ok={self.ok} {self.text[:60]!r}>"

    def raised(self):
        """Return the text, or raise ActionError - for callers that want the
        failure to travel up rather than be inspected."""
        if not self.ok:
            raise ActionError(self.text)
        return self.text


def start():
    """Bring the Action Bus up. Called once from Titan's startup; safe to call
    again."""
    return bus.start()


def is_available(addon_id, action_name=''):
    """True when the action is declared. Says nothing about whether the add-on
    is running - the transport handles that."""
    addon, action = find_action(addon_id, action_name)
    if action_name:
        return action is not None
    return addon is not None


def run(addon_id, action_name='', **args):
    """Perform one action. ``addon_id`` may be 'tedit' with an action name, or
    the single string 'tedit.open_file'."""
    started = time.time()
    addon, action = find_action(addon_id, action_name)
    if addon is None:
        known = ", ".join(sorted(a.addon_id for a in get_registry().addons))
        return ActionResult(
            False,
            f"No Titan add-on called '{addon_id}' offers actions."
            + (f" Available: {known}." if known else ""))
    if action is None:
        known = ", ".join(a.name for a in addon.actions)
        return ActionResult(
            False,
            f"'{addon.label}' has no action '{action_name}'. It offers: {known}.",
            addon=addon)

    # A required parameter that was not given is a question, not an error. The
    # manifest already describes what the parameter is for, so every action
    # becomes askable without its author writing a single needs() call - and a
    # half-specified request turns into one short question instead of a refusal.
    missing = action.missing_required(args)
    if missing:
        name = missing[0]
        spec = action.params.get(name) or {}
        prompt = spec.get('description') or (
            f"What should '{name}' be for {action.qualified}?")
        question = Question(name, prompt, options=spec.get('enum'),
                            kind=spec.get('type', 'string'))
        if len(missing) > 1:
            question.prompt += (f" (This action also still needs: "
                                f"{', '.join(missing[1:])}.)")
        return ActionResult(False, question.as_text(), addon=addon,
                            action=action, question=question)

    prepared = action.coerce(args)
    try:
        if addon.transport == 'inproc':
            ok, text = inproc.call(addon, action, prepared)
        else:
            ok, text = process.call(addon, action, prepared)
    except Exception as e:                        # noqa: BLE001 - reported
        ok, text = False, f"{type(e).__name__}: {e}"

    # The handler may have asked for something instead of doing the work. An
    # in-process handler returns the Question object itself; one in another
    # process can only send JSON, so it arrives as a dict.
    question = None
    if is_question(text):
        question = text
    elif isinstance(text, dict) and text.get('__titan_question__'):
        question = Question.from_dict(text.get('question') or text)
    if question is not None:
        return ActionResult(False, question.as_text(), addon=addon,
                            action=action, elapsed=time.time() - started,
                            question=question)

    # ...or said plainly that it could not do it.
    if is_failure(text):
        return ActionResult(False, text.reason, addon=addon, action=action,
                            elapsed=time.time() - started)
    if isinstance(text, dict) and text.get('__titan_failed__'):
        return ActionResult(False, str(text.get('reason') or 'it failed'),
                            addon=addon, action=action,
                            elapsed=time.time() - started)

    if not isinstance(text, str):
        text = '' if text is None else str(text)
    return ActionResult(ok, text, addon=addon, action=action,
                        elapsed=time.time() - started)


def run_qualified(qualified, args=None):
    """``run`` for callers holding a 'addon.action' string and a dict."""
    return run(qualified, '', **(args or {}))


# --------------------------------------------------------------------------- #
# Describing what is there
# --------------------------------------------------------------------------- #
def list_addons(kind=''):
    """[{id, label, kind, transport, running, actions, source}, ...]"""
    wanted = (kind or '').strip().lower()
    out = []
    for addon in get_registry().addons:
        if wanted and addon.kind != wanted:
            continue
        out.append({
            'id': addon.addon_id,
            'label': addon.label,
            'kind': addon.kind,
            'builtin': bool(getattr(addon, 'builtin', False)),
            'kind_label': kind_label(addon.kind),
            'transport': addon.transport,
            'running': bool(getattr(addon, 'running', False)),
            'source': addon.source,
            'description': addon.description,
            'actions': [action.name for action in addon.actions],
        })
    return out


def list_actions(addon_id=''):
    """Every action, or every action of one add-on, as ActionSpec objects."""
    registry = get_registry()
    if addon_id:
        addon = registry.by_id(addon_id)
        return list(addon.actions) if addon else []
    return [action for _addon, action in registry.actions()]


def describe_addon(addon_id):
    """A readable summary of one add-on - used by the AI's generic dispatcher
    and by anything that wants to show the user what an add-on can do."""
    addon = get_registry().by_id(addon_id)
    if addon is None:
        return f"No Titan add-on called '{addon_id}' offers actions."
    lines = [f"{addon.label} ({addon.addon_id}) - {kind_label(addon.kind)}"]
    if addon.description:
        lines.append(addon.description)
    if addon.transport == 'process':
        lines.append("Running." if getattr(addon, 'running', False)
                     else "Not running (Titan can start it if an action needs it).")
    lines.append("Actions:")
    lines.extend(f"  {action.describe()}" for action in addon.actions)
    if addon.warnings:
        lines.append("Problems in its declaration: " + "; ".join(addon.warnings))
    return "\n".join(lines)

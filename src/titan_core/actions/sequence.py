"""Composite commands: several actions, in order, with results feeding forward.

"Write me a summary, save it as a note, then remind me about it tomorrow" is
three actions, and the second and third need what the first produced. Running
them one at a time works but loses the two things that make a composite request
feel like one instruction: **the later steps can use the earlier results**, and
**the whole thing stops the moment something goes wrong** rather than carrying
on and making a mess.

    from src.titan_core import actions

    actions.run_sequence([
        {'addon': 'tnotes', 'action': 'create_note',
         'args': {'title': 'Shopping', 'text': 'milk, bread'}},
        {'addon': 'tnotes', 'action': 'read_note',
         'args': {'title': 'Shopping'}},
        {'addon': 'treminder', 'action': 'create_reminder',
         'args': {'name': 'Buy: {{2}}', 'date': 'tomorrow', 'time': '17:00'}},
    ])

``{{2}}`` is what step 2 returned. That is the whole substitution language, on
purpose: anything richer would be a scripting language, and an add-on that
needs one should expose an action that does the job properly.

A step that asks a question (see ``interaction.py``) suspends the sequence
rather than failing it: the transcript says which step is waiting and what it
needs, so the caller - the AI, or a component with a dialog - can answer and
run the rest.
"""

import re

from src.titan_core.actions.dispatch import run

MAX_STEPS = 20
_REFERENCE = re.compile(r'\{\{\s*(\d+)\s*\}\}')


class StepResult:
    """One step of a sequence."""

    def __init__(self, index, addon, action, result):
        self.index = index
        self.addon = addon
        self.action = action
        self.result = result

    # ``self.result`` is an ActionResult, and a failed one is falsy - so every
    # test here is against None, not truthiness. Getting this wrong swallows
    # the reason a step failed and reports 'not run' instead.
    @property
    def ok(self):
        return self.result is not None and self.result.ok

    @property
    def pending(self):
        return self.result is not None and self.result.pending

    def __str__(self):
        mark = 'ok' if self.ok else ('asks' if self.pending else 'failed')
        text = self.result.text if self.result is not None else 'not run'
        return f"Step {self.index} ({self.addon}.{self.action}) {mark}: {text}"


class SequenceResult:
    """The outcome of a whole composite command."""

    def __init__(self):
        self.steps = []
        self.stopped_at = None      # the step that failed or asked

    @property
    def ok(self):
        return self.stopped_at is None and bool(self.steps)

    @property
    def pending(self):
        return self.stopped_at is not None and self.stopped_at.pending

    @property
    def question(self):
        return self.stopped_at.result.question if self.pending else None

    def __bool__(self):
        return self.ok

    @property
    def text(self):
        """The transcript - what a user should be told happened.

        Every step is named, because on a composite command "done" is not an
        answer: the user needs to know which parts happened, especially when
        one did not.
        """
        lines = [str(step) for step in self.steps]
        if self.stopped_at is not None:
            if self.stopped_at.pending:
                lines.append(
                    f"Stopped at step {self.stopped_at.index} because it needs "
                    f"an answer. The remaining steps have not run.")
            else:
                lines.append(
                    f"Stopped at step {self.stopped_at.index} because it "
                    f"failed. The remaining steps have not run.")
        elif self.steps:
            lines.append(f"All {len(self.steps)} steps completed.")
        return "\n".join(lines) or "There were no steps to run."

    def __str__(self):
        return self.text


def _normalise(step):
    """Accept the shapes people actually write."""
    if not isinstance(step, dict):
        return None
    addon = step.get('addon') or step.get('add_on') or ''
    action = step.get('action') or ''
    args = step.get('args') or step.get('arguments') or {}
    if not addon and action and '.' in action:
        addon, action = action.split('.', 1)
    if not addon:
        # {'tnotes.create_note': {...}} - one key, the qualified name.
        for key, value in step.items():
            if '.' in str(key) and isinstance(value, dict):
                addon, action = str(key).split('.', 1)
                args = value
                break
    if not addon or not action:
        return None
    return str(addon), str(action), (args if isinstance(args, dict) else {})


def _substitute(args, outputs):
    """Replace {{n}} in string arguments with what step n returned."""
    def replace(text):
        def one(match):
            index = int(match.group(1))
            return outputs.get(index, match.group(0))
        return _REFERENCE.sub(one, text)

    resolved = {}
    for key, value in (args or {}).items():
        resolved[key] = replace(value) if isinstance(value, str) else value
    return resolved


def run_sequence(steps, stop_on_error=True, ask=None):
    """Run several actions in order.

    Args:
        steps: list of ``{'addon': ..., 'action': ..., 'args': {...}}``.
            ``{'addon.action': {...}}`` and ``{'action': 'addon.action'}`` work
            too.
        stop_on_error: stop at the first failure (the default - a later step
            usually assumes the earlier one worked). False runs them all and
            reports what happened to each.
        ask: optional ``question -> answer``. With it, a step that asks is
            answered and retried instead of suspending the sequence.
    """
    outcome = SequenceResult()
    if not isinstance(steps, (list, tuple)) or not steps:
        return outcome
    outputs = {}
    for index, raw in enumerate(steps[:MAX_STEPS], 1):
        parsed = _normalise(raw)
        if parsed is None:
            from src.titan_core.actions.dispatch import ActionResult
            step = StepResult(index, '?', '?', ActionResult(
                False, "This step does not name an add-on and an action."))
            outcome.steps.append(step)
            outcome.stopped_at = step
            if stop_on_error:
                break
            continue
        addon, action, args = parsed
        prepared = _substitute(args, outputs)
        if ask is not None:
            from src.titan_core.actions.interaction import run_interactive
            result = run_interactive(addon, action, ask=ask, **prepared)
        else:
            result = run(addon, action, **prepared)
        step = StepResult(index, addon, action, result)
        outcome.steps.append(step)
        if result.ok:
            outputs[index] = result.text
            continue
        # A question is not a failure, but it does stop the run: the steps
        # after it were written expecting this one to have happened.
        outcome.stopped_at = step
        if result.pending or stop_on_error:
            break
    return outcome

"""When an action cannot finish without asking.

An action often has everything it needs. Sometimes it does not: "copy those
photos" without saying where, "send it" without saying to whom. Until now the
only thing a handler could do was return a sentence that reads like a failure,
and the caller had to guess that it was really a question.

So asking is a **first-class outcome**, alongside success and failure:

    from src.titan_core.actions import needs

    def copy_photos(destination=''):
        if not destination:
            return needs('destination', "Where should I copy the photos?",
                         options=['the USB stick', 'Documents'])
        ...

What happens next depends on who called:

- **A component or another add-on** gets ``result.pending`` with
  ``result.question``, and either answers it from what it knows or shows the
  user a dialog. ``run_interactive()`` does the whole loop for it.
- **The AI** is told, in the result text, exactly which parameter is missing
  and what to ask. It asks the user (``ask_user``) and calls the action again
  with the answer - so a half-specified request becomes a conversation instead
  of a wrong guess.

The point is that the *add-on author* decides what is worth asking about. They
know that a destination cannot be invented and that an overwrite deserves a
question; Titan does not.
"""


class Question:
    """What an action still needs before it can run.

    Returned by a handler through :func:`needs`; never raised, because needing
    a detail is not an error.
    """

    def __init__(self, name, prompt, options=None, kind='string', default=''):
        self.name = str(name or 'answer')
        self.prompt = str(prompt or 'What should I do?')
        self.options = [str(o) for o in (options or [])]
        self.kind = kind if kind in ('string', 'number', 'boolean', 'choice') \
            else 'string'
        if self.options and self.kind == 'string':
            self.kind = 'choice'
        self.default = default

    def __repr__(self):
        return f"<Question {self.name}: {self.prompt[:50]!r}>"

    def as_text(self):
        """The question as the AI is shown it - phrased so the model knows it
        must ask the user rather than invent an answer."""
        parts = [f"QUESTION - this action needs '{self.name}' before it can "
                 f"run: {self.prompt}"]
        if self.options:
            parts.append("Options: " + "; ".join(self.options) + ".")
        if self.default:
            parts.append(f"If the user has no preference, {self.default} is "
                         f"a sensible default.")
        parts.append(f"Ask the user, then call the action again with "
                     f"{self.name} set to their answer. Do not guess it.")
        return " ".join(parts)

    def to_dict(self):
        return {'name': self.name, 'prompt': self.prompt,
                'options': self.options, 'kind': self.kind,
                'default': self.default}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or not data.get('prompt'):
            return None
        return cls(data.get('name', 'answer'), data['prompt'],
                   options=data.get('options'), kind=data.get('kind', 'string'),
                   default=data.get('default', ''))


class Failure:
    """An action that could not do what was asked.

    Without this a handler can only say so in prose, and prose is not something
    a caller can branch on: "There is no note called 'shopping'." comes back
    looking exactly like success, so a composite command carries on to the step
    that assumed the note was there. Raising works too and is caught properly,
    but an expected outcome - a missing file, a name that matches nothing - is
    not exceptional and reads badly as a traceback.
    """

    def __init__(self, reason):
        self.reason = str(reason or "the action did not succeed")

    def __repr__(self):
        return f"<Failure {self.reason[:60]!r}>"

    def to_dict(self):
        return {'reason': self.reason}


def fails(reason):
    """Say that this action could not do what was asked.

        note = _find(title)
        if note is None:
            return fails(f"There is no note called '{title}'.")

    The reason is what the user is told, so write it for them.
    """
    return Failure(reason)


def is_failure(value):
    return isinstance(value, Failure)


def needs(name, prompt, options=None, kind='string', default=''):
    """Say that this action needs ``name`` before it can run.

    Args:
        name: the parameter that is missing - the caller supplies it next time.
        prompt: the question, in words a user would understand.
        options: the acceptable answers, when there is a fixed set.
        kind: 'string', 'number', 'boolean' or 'choice'.
        default: what to do if the user has no preference.
    """
    return Question(name, prompt, options=options, kind=kind, default=default)


def is_question(value):
    return isinstance(value, Question)


# --------------------------------------------------------------------------- #
# Answering
# --------------------------------------------------------------------------- #
def wx_ask(question, parent=None):
    """Ask the user through a Titan dialog, on the interface thread.

    Returns the answer, or '' when they cancelled. This is the default for a
    caller inside Titan that has no better way of asking - a component acting
    on the user's behalf, say. Callers with their own interface (the AI, a
    service with its own screen) pass their own ``ask``.
    """
    from src.titan_core.actions.inproc import run_on_gui

    def show():
        import wx
        try:
            from src.titan_core.translation import _
        except Exception:
            def _(text):
                return text
        title = _("Titan needs to know")
        if question.options:
            dialog = wx.SingleChoiceDialog(parent, question.prompt, title,
                                           question.options)
            try:
                if dialog.ShowModal() != wx.ID_OK:
                    return ''
                return dialog.GetStringSelection()
            finally:
                dialog.Destroy()
        dialog = wx.TextEntryDialog(parent, question.prompt, title,
                                    value=str(question.default or ''))
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return ''
            return dialog.GetValue()
        finally:
            dialog.Destroy()

    answer, error = run_on_gui(show, timeout=300)
    if error:
        print(f"[actions] Could not ask the user: {error}")
        return ''
    return answer or ''


_MAX_ROUNDS = 6


def run_interactive(addon_id, action_name='', ask=None, parent=None, **args):
    """Run an action, answering whatever it asks for, until it is done.

        actions.run_interactive('tfm', 'copy_path', source=path)

    ``ask`` is a callable ``question -> answer``; without one, the user is
    asked through a Titan dialog. An unanswered question stops the loop and
    comes back as a pending result, so nothing is ever done on a guess.

    The round limit is not paranoia: a handler that keeps asking for the same
    thing would otherwise loop against the user forever.
    """
    from src.titan_core.actions.dispatch import run

    asker = ask or (lambda question: wx_ask(question, parent=parent))
    asked = set()
    result = None
    for _round in range(_MAX_ROUNDS):
        result = run(addon_id, action_name, **args)
        question = result.question
        if question is None:
            return result
        if question.name in asked:
            # It asked twice for the same thing - the answer was not accepted,
            # and asking a third time would just annoy the user.
            return result
        asked.add(question.name)
        answer = asker(question)
        if not str(answer or '').strip():
            return result
        args[question.name] = answer
    return result

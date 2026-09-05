"""Titan's voice, driven by a screen reader that lives in another program.

`titan.speak` is right for what it is: one line, said with a position, a
pitch and a rate borrowed for that line and given back afterwards. Giving
the rate back is only possible after the line has been spoken, so that
action speaks SYNCHRONOUSLY whenever a rate is passed - which on the action
bus means the answer does not come back until the sentence is finished.

For a reader that is fatal, and measurably so: Elten hands every line to the
output with `interrupt: true`, and an interruption that arrives after the
previous line has finished is not an interruption at all. Worse, an
in-process action runs on Titan's GUI thread, so a whole utterance spoken
synchronously holds Titan's own interface for its length.

So this is the reader's path: speech starts and the call returns. The rate
is not borrowed per line but SET, once, when the reader's rate changes, and
put back when it stops using the voice - which is what a reader means by a
rate anyway. Nothing here replaces `titan.speak`; both exist because they
answer different questions.
"""

from src.titan_core.actions.inproc import run_on_gui

RATE_SECTION = 'stereo_speech'
RATE_KEY = 'rate'


def _speech():
    from src.titan_core.stereo_speech import get_stereo_speech
    return get_stereo_speech()


def _number(value, low, high, default=None):
    try:
        if value is None or str(value).strip() == '':
            return default
        return max(low, min(high, float(str(value).strip())))
    except (TypeError, ValueError):
        return default


def _truth(value):
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _reader_speak(text='', interrupt=True, pitch=0, position=0,
                  spelling=False, **_):
    """Say one line and RETURN - the speech carries on without this call.

    Interrupting is the whole point of the `interrupt` flag: it stops what
    is being said before starting this, which is what a reader does on every
    keystroke.
    """
    line = str(text or '')
    if _truth(spelling):
        # A reader spells by naming the characters; Titan has no spelling
        # mode of its own, and pauses between them are what make it legible.
        line = ', '.join(list(line))
    tone = _number(pitch, -10, 10, 0) or 0
    pan = _number(position, -1.0, 1.0, 0) or 0.0

    def say():
        speech = _speech()
        if speech is None:
            return False
        if _truth(interrupt):
            speech.stop()
        if not line.strip():
            return True
        speech.speak_async(line, position=float(pan), pitch_offset=int(tone))
        return True

    started, error = run_on_gui(say)
    if error:
        return f"Could not speak: {error}"
    if not started:
        return "Titan's speech is not running."
    return "Speaking."


def _set_rate(rate='', **_):
    """Set the rate Titan speaks at, and answer with what it was.

    The caller is expected to keep that answer and set it back when it stops
    using the voice: a reader borrowing Titan's voice should not leave Titan
    talking to its own user at somebody else's speed for ever.
    """
    wanted = _number(rate, -10, 10)
    if wanted is None:
        return "Give a rate between -10 and 10."

    def apply():
        previous = 0
        try:
            from src.settings.settings import get_setting
            saved = str(get_setting(RATE_KEY, '', section=RATE_SECTION)).strip()
            previous = int(saved) if saved else 0
        except Exception:
            previous = 0
        speech = _speech()
        if speech is None:
            return None
        speech.set_rate(int(wanted))
        return previous

    previous, error = run_on_gui(apply)
    if error:
        return f"Could not set the rate: {error}"
    if previous is None:
        return "Titan's speech is not running."
    return str(previous)


def _get_rate(**_):
    """The rate Titan is speaking at now."""
    def read():
        from src.settings.settings import get_setting
        saved = str(get_setting(RATE_KEY, '', section=RATE_SECTION)).strip()
        return saved or '0'
    value, error = run_on_gui(read)
    if error:
        return f"Could not read the rate: {error}"
    return str(value)


def get_reader_actions():
    """(name, summary, params, risk, run) for each, as the shell's are."""
    string = {'type': 'string'}
    number = {'type': 'number'}
    boolean = {'type': 'boolean'}
    return (
        ('reader_speak',
         "Say one line through Titan's voice and return at once, without "
         "waiting for it to be spoken. For a screen reader in another "
         "program: `titan.speak` waits whenever a rate is given, and a "
         "reader cannot wait.",
         {'text': dict(string, description="What to say.", required=True),
          'interrupt': dict(boolean, description="Stop what is being said "
                            "first (default yes)."),
          'pitch': dict(number, description="Pitch for this line, -10 to 10."),
          'position': dict(number, description="Where the voice comes from, "
                           "-1 left to 1 right."),
          'spelling': dict(boolean, description="Spell it out character by "
                           "character.")},
         'auto', _reader_speak),
        ('set_speech_rate',
         "Set the rate Titan speaks at, and answer with the rate it was - so "
         "the caller can put it back.",
         {'rate': dict(number, description="-10 (slow) to 10 (fast).",
                       required=True)},
         'auto', _set_rate),
        ('get_speech_rate', "The rate Titan is speaking at now.", {},
         'auto', _get_rate),
    )


# --------------------------------------------------------------------------- #
# Asking Titan's AI from another program
# --------------------------------------------------------------------------- #
def _ai_enabled():
    try:
        from src.ai import ai_provider
        provider = ai_provider.get_ai_provider()
        return bool(provider and ai_provider.get_ai_key(provider))
    except Exception:
        return False


def _ask_ai(question='', act=False, **_):
    """Ask Titan's AI something and hand back what it said.

    Two modes, and the default is the safe one. Without ``act`` the model is
    given NO tools: it answers, and answering is all it can do. With ``act``
    it is given the agent's own toolset and may drive Titan - the same thing
    the AI Agent window does, which is why it has to be asked for.

    It runs on a worker rather than on Titan's interface thread: a model
    call is seconds, and this is a caller that has already been told not to
    hold that thread.
    """
    text = str(question or '').strip()
    if not text:
        return "Ask something."
    if not _ai_enabled():
        return ("Titan's AI features are off, or no provider key is set. "
                "Switch them on in Settings, AI features.")
    wants_tools = str(act).strip().lower() in ('1', 'true', 'yes', 'on')
    try:
        from src.ai.ai_agent import run_agent
        tools = []
        if wants_tools:
            from src.ai.agent_tools import get_tools
            tools = get_tools()
        answer = run_agent(text, tools, remember=True, memory_source='elten')
    except Exception as e:
        return f"The AI could not answer: {type(e).__name__}: {e}"
    return str(answer or '').strip() or "The AI said nothing."


def get_ai_actions():
    """(name, summary, params, risk, run) for each, as the shell's are."""
    string = {'type': 'string'}
    boolean = {'type': 'boolean'}
    return (
        ('ask_ai',
         "Ask Titan's AI a question and get its answer as text. Without "
         "'act' it only answers; with 'act' it may use Titan's own tools to "
         "do what was asked, as the AI Agent window does.",
         {'question': dict(string, description="What to ask.",
                           required=True),
          'act': dict(boolean, description="Let it DO things, not only "
                      "answer (default no).")},
         'confirm', _ask_ai),
        ('ai_available', "Whether Titan's AI features are switched on and "
                         "have a key: yes or no.", {}, 'auto',
         lambda **_: "yes" if _ai_enabled() else "no"),
    )


def _ai_history(limit=20, **_):
    """The conversation Titan's AI has been having, oldest first.

    The assistant and the agent share one memory - one person, one
    conversation - so a chat opened somewhere else is not a stranger: it
    carries on. A client that shows a chat has to be able to show what was
    already said, which is what this is for.
    """
    import json

    try:
        from src.ai import memory
        if not memory.enabled():
            return json.dumps({'exchanges': [], 'enabled': False},
                              ensure_ascii=False)
        count = max(1, min(int(limit or 20), 200))
        entries = memory.recent(count)
    except Exception as e:
        return f"Could not read the conversation: {type(e).__name__}: {e}"
    return json.dumps({'enabled': True,
                       'exchanges': [{'role': entry.get('role', ''),
                                      'text': entry.get('text', ''),
                                      'source': entry.get('source', ''),
                                      'at': entry.get('t', 0)}
                                     for entry in entries]},
                      ensure_ascii=False, default=str)


def _ai_forget_conversation(**_):
    """Start the conversation again from nothing."""
    try:
        from src.ai import memory
        memory.clear_conversation()
    except Exception as e:
        return f"Could not clear it: {type(e).__name__}: {e}"
    return "The conversation was cleared."


def get_ai_history_actions():
    """(name, summary, params, risk, run) for each, as the shell's are."""
    number = {'type': 'number'}
    return (
        ('ai_history',
         "The conversation Titan's AI has been having, as JSON - what a "
         "chat window shows when it opens.",
         {'limit': dict(number, description="How many exchanges "
                        "(default 20).")},
         'auto', _ai_history),
        ('ai_forget_conversation',
         "Clear the AI conversation and start again from nothing.", {},
         'always_confirm', _ai_forget_conversation),
    )

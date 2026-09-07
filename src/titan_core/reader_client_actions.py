# -*- coding: utf-8 -*-
"""The screen reader the user is actually using, as something Titan can call.

Titan has always been able to SPEAK - `titan.speak`, `stereo_speech`, its own
Titan Access. What it has never been able to do is ask the reader a question,
or change it. Those are different things and the difference is the whole of
this module:

* **Titan speaking** is Titan's own voice, out of Titan's own engine. It is
  right for Titan's own interface and wrong for everything else here: a user
  reading their mail with NVDA does not want an answer about that mail in a
  second voice over the top of the first.
* **The reader** knows what is on the screen. Not the foreground window -
  which on a machine being read is a menu, a tooltip, a dialog the reader
  has followed the user into - but the focused control, by name and role and
  state, where the review cursor is, what is selected, and whether the user
  is in browse mode. Titan cannot work any of that out, because Titan is not
  the reader.

So this provider is one half of a bridge whose other half is the reader's own
add-on (`nvda-addon/` is the first; the id list in
`src.accessibility.reader_channel` is what makes a second one work with no
change here). Everything below reaches whichever of them is on the Action
Bus.

Three rules, and each of them is one this repository has paid for already:

* **The table IS the boundary.** A call is in :data:`CALLS` or it does not
  exist. There is no path from a name the assistant produced to an attribute
  of the reader's process.
* **A refusal is an answer.** The reader's add-on has its own switches -
  reading it is always served, changing it is one switch, pressing its keys
  is another - and a refusal comes back as the sentence saying which, not as
  a call that failed. Answering "the reader did not respond" to somebody who
  needs to tick a box is the bug this repository fixed once in the Elten
  bridge and will not ship again.
* **No reader is an answer too.** Titan Access is Titan's own and is reached
  in-process, not over the bus; a machine with no reader at all is the
  ordinary case. Both are said plainly rather than reported as a failure.
"""

import json

#: How long a question to the reader may take. It is answered on the
#: reader's own thread - every property of a control is a call into UI
#: Automation - so this covers a tree that is being slow, and past it the
#: honest answer is that the reader is busy.
ASK_TIMEOUT = 6.0

#: Reading the screen is a question; changing the reader is an instruction.
#: The second is not waited on for as long, because nothing is coming back
#: but an acknowledgement.
ACT_TIMEOUT = 4.0


# --------------------------------------------------------------------------- #
# Finding the reader
# --------------------------------------------------------------------------- #
def _peer():
    """The reader add-on on the bus right now, or None."""
    try:
        from src.accessibility import reader_channel
        from src.titan_core.actions import bus
    except Exception:                                # noqa: BLE001
        return None
    for addon_id in reader_channel.READER_CLIENTS:
        peer = bus.get_peer(addon_id)
        if peer is not None and getattr(peer, 'alive', False):
            return peer
    return None


def _titan_access():
    try:
        from titan_access.host_bridge import is_active
        return bool(is_active())
    except Exception:                                # noqa: BLE001
        return False


def _no_reader():
    """The sentence for "there is nobody to ask", which is not a failure."""
    if _titan_access():
        return ("Titan Access is the reader, and it is Titan's own - it is "
                "reached in this process rather than over the bus, so these "
                "actions have nothing to talk to. Ask titan.read_screen and "
                "the titan_access actions instead.")
    return ("No screen reader add-on is connected. These actions need the "
            "reader's own Titan add-on running - the NVDA one is in "
            "nvda-addon/ - so that Titan can ask it what is on the screen.")


def _ask(call, timeout=ASK_TIMEOUT, **args):
    """One call into the reader. (ok, value_or_sentence)."""
    peer = _peer()
    if peer is None:
        return False, _no_reader()
    from src.titan_core.actions import bus
    ok, result = bus.invoke(peer.addon_id, call, args, timeout=timeout)
    if not ok:
        return False, (f"The reader did not answer: {result}")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            return True, result
    if isinstance(result, dict) and result.get('ok') is False:
        # The reader's own refusal, with the reason it gave. Handed back as
        # a failure so a caller acts on it, with the sentence intact so the
        # user is told which switch it was.
        return False, str(result.get('reason')
                          or 'the reader would not do that')
    return True, result


# --------------------------------------------------------------------------- #
# Saying what came back
# --------------------------------------------------------------------------- #
def _lines(state):
    """The reader's context as sentences, for the caller that is a model."""
    if not isinstance(state, dict):
        return str(state)
    if not state.get('available'):
        return ("The reader could not say what is on the screen: "
                + str(state.get('why') or 'it did not say why'))
    focus = state.get('focus') or {}
    out = []
    where = []
    if focus.get('app'):
        where.append(f"application {focus['app']}")
    if focus.get('window'):
        where.append(f"window '{focus['window']}'")
    if where:
        out.append("In " + ", ".join(where) + ".")
    named = focus.get('name') or ''
    role = focus.get('role') or ''
    if named or role:
        line = f"The focus is on '{named}'" if named else "The focus is on"
        if role:
            line += f", a {role}"
        if focus.get('states'):
            line += ", " + ", ".join(focus['states'])
        if focus.get('index') and focus.get('count'):
            line += f", {focus['index']} of {focus['count']}"
        out.append(line + ".")
    else:
        out.append("Nothing has the focus, or the reader could not name it.")
    if focus.get('value'):
        out.append(f"Its value is '{focus['value']}'.")
    if state.get('mode') == 'browse':
        out.append("The reader is in browse mode, so keys are the reader's "
                   "rather than the application's.")
    if state.get('selection'):
        out.append(f"The selected text is: {state['selection']}")
    if state.get('review'):
        out.append(f"The review cursor is on: {state['review']}")
    navigator = state.get('navigator') or {}
    if navigator.get('name'):
        out.append("The navigator object is '{}'{}.".format(
            navigator['name'],
            f", a {navigator['role']}" if navigator.get('role') else ''))
    if state.get('synth'):
        out.append(f"It is speaking through {state['synth']}.")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# The actions
# --------------------------------------------------------------------------- #
def reader_status(**_):
    """Which reader is listening, and what Titan may send it."""
    from src.accessibility import reader_channel
    report = reader_channel.report()
    lines = []
    names = {'titan_access': 'Titan Access, Titan\'s own reader',
             'addon': 'a screen reader whose Titan add-on is connected',
             'plain': 'a screen reader reached through accessible_output3',
             'none': 'nothing - no screen reader is running'}
    lines.append("Titan is talking to " + names.get(report['channel'],
                                                    report['channel']) + ".")
    able = report.get('capabilities') or {}
    can = sorted(name for name, yes in able.items() if yes)
    if can:
        lines.append("It can take: " + ", ".join(can) + ".")
    peer = _peer()
    if peer is None:
        lines.append(_no_reader())
        return "\n".join(lines)
    lines.append(f"The reader add-on '{peer.addon_id}' is on the bus, so "
                 f"Titan can ask it what is on the screen and - if its own "
                 f"switches allow - change it.")
    # What the reader itself says it can do, which is more than the channel
    # summary above: whether the voice can be MOVED on this machine, and
    # when it cannot, why. A capability that is quietly false is the same
    # as a feature that is quietly missing.
    ok, theirs = _ask('capabilities', timeout=ACT_TIMEOUT)
    if ok and isinstance(theirs, dict):
        if theirs.get('synth'):
            lines.append("It is speaking through {}, {} channel(s)."
                         .format(theirs['synth'], theirs.get('channels', 0)))
        if theirs.get('position'):
            lines.append("Its voice can be placed in the stereo image.")
        else:
            why = str(theirs.get('problem') or '')
            lines.append("Its voice cannot be placed"
                         + (": " + why if why else "")
                         + (". A tone marks the position instead."
                            if theirs.get('position_marker')
                            else ", and this NVDA cannot mark it with a tone "
                                 "either."))
    ok, settings = _ask('settings', timeout=ACT_TIMEOUT)
    if ok and isinstance(settings, dict):
        lines.append("Titan may change it: {}. Titan may press its keys: {}."
                     .format('yes' if settings.get('may_change') else 'no',
                             'yes' if settings.get('may_press_keys') else 'no'))
    return "\n".join(lines)


def reader_context(**_):
    """What the reader can see right now."""
    ok, state = _ask('context')
    return _lines(state) if ok else str(state)


def reader_window(**_):
    """The window the reader is in - the one Titan should act on."""
    ok, where = _ask('window', timeout=ACT_TIMEOUT)
    if not ok:
        return str(where)
    if not isinstance(where, dict) or not where.get('hwnd'):
        return "The reader could not say which window it is in."
    return ("The reader is in '{title}' ({app}), window handle {hwnd}. Pass "
            "that handle to ocr.read_window to read THAT window rather than "
            "whatever happens to be in front.".format(
                title=where.get('title') or '(no title)',
                app=where.get('app') or 'unknown',
                hwnd=where['hwnd']))


def reader_say(text='', interrupt=True, position=0, pitch=0, rate=0, **_):
    """Say something in the reader's own voice, not in Titan's."""
    if not str(text or '').strip():
        return "Say what to read out."
    ok, answer = _ask('speak', timeout=ACT_TIMEOUT, text=str(text),
                      interrupt=_truth(interrupt),
                      position=_number(position), pitch=_number(pitch),
                      rate=_number(rate))
    if not ok:
        return str(answer)
    if isinstance(answer, dict) and not answer.get('spoken', True):
        return str(answer.get('reason') or "The reader did not say it.")
    return "Said."


def reader_stop(**_):
    ok, answer = _ask('stop', timeout=ACT_TIMEOUT)
    return "Stopped." if ok else str(answer)


def reader_say_all(**_):
    """Read on from where the review cursor is."""
    ok, answer = _ask('say_all', timeout=ACT_TIMEOUT)
    return "Reading." if ok else str(answer)


def reader_read_focus(**_):
    ok, answer = _ask('read_focus', timeout=ACT_TIMEOUT)
    return "Said." if ok else str(answer)


def reader_review(unit='line', direction='next', **_):
    """Move the reader's review cursor and read what is there."""
    ok, answer = _ask('review', timeout=ACT_TIMEOUT, where=str(unit or 'line'),
                      direction=str(direction or 'next'))
    if not ok:
        return str(answer)
    return "Moved by {}.".format(unit) if isinstance(answer, dict) \
        and answer.get('moved') else "Read it again."


def reader_mode(mode='toggle', **_):
    """Browse mode or focus mode.

    Worth having as an action rather than only as a key: anything Titan is
    about to type into a web page needs focus mode first, or every keystroke
    is a browse command and the page is navigated instead of written in.
    """
    ok, answer = _ask('mode', timeout=ACT_TIMEOUT, name=str(mode or 'toggle'))
    return ("The reader is now in {} mode.".format(mode) if ok
            else str(answer))


def reader_settings(**_):
    """Every setting of the reader Titan may read or change."""
    ok, answer = _ask('settings', timeout=ACT_TIMEOUT)
    if not ok:
        return str(answer)
    if not isinstance(answer, dict):
        return str(answer)
    values = answer.get('settings') or {}
    if not values:
        return "The reader offered no settings."
    lines = ["The reader's settings Titan can read or change:"]
    for name in sorted(values):
        lines.append(f"- {name}: {values[name]}")
    if answer.get('synth'):
        lines.append(f"Speaking through {answer['synth']}.")
    if not answer.get('may_change'):
        lines.append("Titan may read these but not change them: the switch "
                     "is in the reader's own add-on settings.")
    return "\n".join(lines)


def reader_setting(name='', value=None, **_):
    """Read one of the reader's settings, or set it."""
    if not str(name or '').strip():
        return "Say which setting. reader.settings lists them."
    args = {'name': str(name)}
    if value is not None and str(value) != '':
        args['value'] = value
    ok, answer = _ask('setting', timeout=ACT_TIMEOUT, **args)
    if not ok:
        return str(answer)
    if not isinstance(answer, dict):
        return str(answer)
    if answer.get('set'):
        return "{} is now {}.".format(answer.get('name'), answer.get('value'))
    return "{} is {}.".format(answer.get('name'), answer.get('value'))


def reader_synths(**_):
    ok, answer = _ask('synths', timeout=ACT_TIMEOUT)
    if not ok:
        return str(answer)
    found = (answer or {}).get('synths') or []
    if not found:
        return "The reader offered no synthesizers."
    lines = ["The reader's synthesizers:"]
    for synth in found:
        mark = ' (in use)' if synth.get('name') == answer.get('current') else ''
        lines.append("- {} [{}]{}".format(synth.get('label'),
                                          synth.get('name'), mark))
    return "\n".join(lines)


def reader_use_synth(name='', **_):
    if not str(name or '').strip():
        return "Say which synthesizer. reader.synths lists them."
    ok, answer = _ask('use_synth', timeout=ACT_TIMEOUT, name=str(name))
    return ("The reader is now speaking through {}.".format(name) if ok
            else str(answer))


def reader_voices(**_):
    ok, answer = _ask('voices', timeout=ACT_TIMEOUT)
    if not ok:
        return str(answer)
    found = (answer or {}).get('voices') or []
    if not found:
        return "The reader offered no voices."
    lines = ["The voices of the reader's current synthesizer:"]
    for voice in found[:200]:
        mark = ' (in use)' if voice.get('id') == answer.get('current') else ''
        lines.append("- {} [{}]{}".format(voice.get('label'),
                                          voice.get('id'), mark))
    return "\n".join(lines)


def reader_use_voice(name='', **_):
    if not str(name or '').strip():
        return "Say which voice. reader.voices lists them."
    ok, answer = _ask('use_voice', timeout=ACT_TIMEOUT, name=str(name))
    return ("The reader is now using {}.".format(name) if ok else str(answer))


def reader_press(gesture='', **_):
    """Run one of the reader's own commands, written the way it writes them."""
    if not str(gesture or '').strip():
        return ("Say which command, the way the reader names it - "
                "'kb:NVDA+f7' for NVDA's elements list.")
    ok, answer = _ask('press', timeout=ACT_TIMEOUT, gesture=str(gesture))
    return ("Pressed {}.".format(gesture) if ok else str(answer))


def _number(value, low=-10.0, high=10.0):
    try:
        return max(low, min(high, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _truth(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


# --------------------------------------------------------------------------- #
def get_reader_client_actions():
    """(name, summary, params, risk, run) for each, as the shell's are."""
    text = {'type': 'string'}
    return (
        ('status',
         "Which screen reader Titan is talking to, what it can be sent, and "
         "whether its own add-on is connected - which is what decides "
         "whether any of the rest of these can be used at all.", {},
         'auto', reader_status),
        ('context',
         "What the screen reader can see RIGHT NOW: the focused control by "
         "name, role and state, where it is in its list, what is selected, "
         "where the review cursor is, and whether the reader is in browse "
         "mode. This is the one way to find out what the user is actually "
         "looking at - the foreground window is not the same question.", {},
         'auto', reader_context),
        ('window',
         "The window the reader is in, with its handle - to be passed to "
         "ocr.read_window so AI OCR reads THAT window rather than whatever "
         "Windows calls the foreground.", {},
         'auto', reader_window),
        ('say',
         "Read something out in the SCREEN READER's own voice rather than "
         "Titan's. Use this over titan.speak whenever the user is reading "
         "with a screen reader: one voice saying everything is what they "
         "set up, and a second one over the top of it is not.",
         {'text': dict(text, required=True,
                       description="What to read out."),
          'interrupt': {'type': 'boolean',
                        'description': "Cut off what the reader is saying "
                                       "(the default), or queue behind it."},
          'position': {'type': 'number',
                       'description': "Where to say it from: -1 left, 0 "
                                      "centre, 1 right. The reader places "
                                      "its own voice; where it cannot, a "
                                      "tone marks the place instead."},
          'pitch': {'type': 'number', 'description': "-10 to 10."},
          'rate': {'type': 'number', 'description': "-10 to 10."}},
         'auto', reader_say),
        ('stop', "Stop the screen reader speaking.", {}, 'auto', reader_stop),
        ('say_all',
         "Have the reader read on from where its review cursor is - its own "
         "say-all, so the user's own keys stop it.", {}, 'auto',
         reader_say_all),
        ('read_focus',
         "Have the reader say the focused control again, in its own words.",
         {}, 'auto', reader_read_focus),
        ('review',
         "Move the reader's review cursor and read what is there. The review "
         "cursor is where the user is READING, which is a different place "
         "from the focus and one Titan has no equivalent of.",
         {'unit': dict(text, description="line (default), word, character "
                                         "or paragraph.",
                       enum=['line', 'word', 'character', 'paragraph']),
          'direction': dict(text, description="next (default), previous or "
                                              "current.",
                            enum=['next', 'previous', 'current'])},
         'auto', reader_review),
        ('mode',
         "Put the reader into browse mode or focus mode. Anything about to "
         "type into a web page needs focus mode first, or every keystroke is "
         "a browse command.",
         {'mode': dict(text, description="browse, focus or toggle.",
                       enum=['browse', 'focus', 'toggle'])},
         'auto', reader_mode),
        ('settings',
         "Every setting of the screen reader that Titan may read or change - "
         "its rate, volume, pitch, punctuation level, keyboard echo - and "
         "whether the user has allowed changing them.", {},
         'auto', reader_settings),
        ('setting',
         "Read one of the reader's settings, or change it. Ask settings "
         "first for the names: they are the reader's, not Titan's.",
         {'name': dict(text, required=True,
                       description="The setting, as reader.settings names it."),
          'value': dict(text, description="Leave out to read it.")},
         'auto', reader_setting),
        ('synths', "The screen reader's synthesizers, and which is speaking.",
         {}, 'auto', reader_synths),
        ('use_synth', "Switch the screen reader to another synthesizer.",
         {'name': dict(text, required=True,
                       description="Its name, as reader.synths lists it.")},
         'confirm', reader_use_synth),
        ('voices', "The voices of the reader's current synthesizer.", {},
         'auto', reader_voices),
        ('use_voice', "Switch the screen reader to another voice.",
         {'name': dict(text, required=True,
                       description="Its id, as reader.voices lists it.")},
         'confirm', reader_use_voice),
        ('press',
         "Run one of the screen reader's OWN commands, written the way it "
         "writes them - 'kb:NVDA+f7'. The last resort: it is whatever the "
         "user has bound that key to, so it is off in the reader's add-on "
         "until they switch it on.",
         {'gesture': dict(text, required=True,
                          description="The command, e.g. kb:NVDA+f7.")},
         'always_confirm', reader_press),
    )

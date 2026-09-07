# -*- coding: utf-8 -*-
"""What the Elten client on this machine knows, from inside it.

Titan already has an `elten` provider, and it is a different thing: it signs
in to EltenLink over the network with the credentials in `titan.IM` and asks
the SERVER. It cannot answer "what is Elten showing right now", because it is
not Elten - it does not have that process's session, its notification
service, or the list of what has already been read.

The TCE bridge (`elten-tce-bridge/`) is inside that process. It joins Titan's
Action Bus as a client, and every few seconds it reports what Elten knows:
who is signed in, what Elten's own notification service is holding, and what
has arrived since. That report is kept here, and these actions are how Titan
- its AI included - reads it.

Two rules make this honest rather than a second, worse Elten client:

* **Elten is ASKED when it is there, and only remembered when it is not.**
  The bridge serves three actions back over the bus, so a question put to
  the assistant reaches the running Elten and is answered from it. When
  Elten has gone, the last report is what is left - and then the answer
  says HOW OLD it is, so a stale answer is visibly stale rather than
  quietly wrong.
* **Elten not running is an answer, not an error.** The bridge is on the bus
  only while Elten is open, so "Elten is not running" is what these say then,
  which is the true and useful thing to tell the user.
"""

import json
import time

#: The add-on id the bridge joins the bus with. Not `elten_bridge`: that is
#: the Titan COMPONENT that runs Elten's applications inside Titan, and the
#: two are opposite directions through the same wall.
CLIENT_ID = 'elten_tce_bridge'

#: A report older than this is not news about Elten any more - it is what
#: Elten was doing when the bridge last spoke, and it is said as such.
STALE_AFTER = 120.0

_report = {}


def report(state, source=CLIENT_ID):
    """Keep what a client just said about the program it is inside."""
    if not isinstance(state, dict):
        raise ValueError('the report must be an object')
    _report[str(source or CLIENT_ID)] = {'at': time.time(), 'state': state}
    return {'kept': True}


def _latest(source=CLIENT_ID):
    return _report.get(str(source or CLIENT_ID))


def _connected():
    """Whether the bridge is on the bus at this moment."""
    try:
        from src.titan_core.actions import bus
        return bus.get_peer(CLIENT_ID) is not None
    except Exception:
        return False


#: Asking the running Elten is a round trip to another process, made on the
#: thread of whoever asked - an assistant's tool call, usually. Elten answers
#: out of state its own service already holds, so the work itself is
#: instant; what this has to cover is WHEN the question is picked up. The
#: bridge's one thread reads the pipe while it is waiting for an answer of
#: its own, and otherwise every `IDLE_PROBE_SECONDS` (5), so a question that
#: arrives at the worst moment waits out that idle tick before it is seen.
#: Eight seconds is that, with room; past it the far side is wedged and
#: saying so beats hanging.
#: Long enough for a question that has to reach ELTEN'S OWN THREAD.
#: Reading the screen is marshalled onto it and answered on the add-on's
#: tick, so the wait is at least one tick plus whatever Elten is busy
#: with; eight seconds cut half of them off and reported the timeout as
#: "Elten has not given permission", which was neither true nor what
#: happened.
ASK_TIMEOUT = 20.0


#: Why the last question to Elten was not answered.
_LAST_PROBLEM = ['']


def _ask(action):
    return _ask_with(action, {})


def _ask_with(action, args):
    """Ask the running Elten. (answered, value) - `answered` is False when
    there is nothing on the other end, which is not a failure."""
    try:
        from src.titan_core.actions import bus
    except Exception:
        return False, None
    if bus.get_peer(CLIENT_ID) is None:
        return False, None
    ok, result = bus.invoke(CLIENT_ID, action, args or {}, timeout=ASK_TIMEOUT)
    if not ok:
        # **The reason is carried, not thrown away.** A question that
        # timed out and a bridge that refuses are different things, and
        # answering both with "Elten is not running, or has not been given
        # permission" told the user to go and check a setting that was
        # already on.
        _LAST_PROBLEM[0] = str(result or '')
        return False, None
    _LAST_PROBLEM[0] = ''
    if isinstance(result, str):
        # A handler answers with a shape; a plain sentence is the bridge
        # saying why it will not - permission taken back, most likely - and
        # that sentence is the answer.
        try:
            return True, json.loads(result)
        except ValueError:
            return True, str(result)
    return True, result


def _age_line(entry):
    age = time.time() - float(entry.get('at') or 0)
    if age < 5:
        return ''
    if age > STALE_AFTER:
        return f" (last heard {int(age)} seconds ago)"
    return f" ({int(age)} seconds ago)"


# --------------------------------------------------------------------------- #
# The actions
# --------------------------------------------------------------------------- #
def elten_client_status(**_):
    """Is Elten running, and who is signed in to it."""
    answered, live = _ask('status')
    if answered and isinstance(live, str):
        return live
    if answered and isinstance(live, dict):
        return _describe_status(live, '', live=True)
    entry = _latest()
    if not _connected() and entry is None:
        return ("Elten is not running, the TCE bridge add-on is not "
                "installed in it, or it has not been given permission to "
                "share Elten's data with Titan - it asks once, the first "
                "time the add-on is opened, and the answer is in its own "
                "settings ('Share Elten's data with TCE'). Nothing here can "
                "be read until then.")
    return _describe_status((entry or {}).get('state') or {},
                            _age_line(entry) if entry is not None else '')


#: What to say instead of "nothing is waiting".
#:
#: **The failure mode of a privacy switch is a lie.** With sharing off
#: the report carries an empty list, and every describer below reads an
#: empty list as "Elten has no notifications waiting" - which is not a
#: refusal, it is a false answer to the question that was asked, and the
#: user would act on it. A refusal is worse than an answer and infinitely
#: better than a wrong one.
NOT_SHARED = ("Elten is not sharing its notifications with Titan's AI. "
              "That is a switch of its own in the TCE bridge's settings, "
              "separate from the desktop notifications, which are "
              "unaffected. Nothing here says whether anything is waiting.")


def _not_shared(state):
    """Has the bridge said, in so many words, that it is not sharing?

    Only an explicit False. A bridge older than the switch does not send
    the field at all, and reading its silence as a refusal would replace
    every answer it CAN give with one it never made.
    """
    return isinstance(state, dict) and state.get('shared_with_ai') is False


def _describe_status(state, age, live=False):
    """`live` means Elten answered this itself, just now - so it must not
    be prefaced with "this is what it last said", which is what the
    remembered report is."""
    lines = []
    lines.append("The Elten client is connected to Titan."
                 if live or _connected() else
                 "The Elten client is not connected at the moment; this is "
                 "what it last said.")
    who = str(state.get('user') or '').strip()
    full = str(state.get('name') or '').strip()
    if who:
        lines.append(f"Signed in as {who}"
                     + (f" ({full})" if full and full != who else '') + '.')
    else:
        lines.append("Nobody is signed in to Elten.")
    if state.get('moderator'):
        lines.append("That account is a moderator there.")
    version = str(state.get('version') or '').strip()
    language = str(state.get('language') or '').strip()
    if version:
        lines.append(f"Elten {version}"
                     + (f", in {language}" if language else '') + '.')
    waiting = state.get('notifications')
    if _not_shared(state):
        lines.append(NOT_SHARED)
    elif isinstance(waiting, list):
        lines.append(f"{len(waiting)} notification(s) waiting in Elten.")
    elif isinstance(waiting, int):
        lines.append(f"{waiting} notification(s) waiting in Elten.")
    # **Why there were none is as much an answer as how many.** Nobody
    # signed in, a client with no notification service, and nothing
    # actually waiting are three different things that all arrive as an
    # empty list - and only one of them is Elten working correctly.
    why = str(state.get('why') or '').strip()
    if why and not waiting:
        lines.append(f'{why}.')
    if age:
        lines[-1] = lines[-1] + age
    return '\n'.join(lines)


def elten_client_notifications(**_):
    """What Elten's own notification service is holding right now."""
    answered, live = _ask('notifications')
    if answered and isinstance(live, str):
        return live
    if answered and isinstance(live, dict):
        return _describe_notifications(live.get('notifications'), '',
                                       live.get('why'))
    entry = _latest()
    if entry is None:
        return ("Elten has not reported anything yet. It reports a few "
                "seconds after it starts, and only while it is running.")
    state = entry.get('state') or {}
    if _not_shared(state):
        return NOT_SHARED
    return _describe_notifications(state.get('notifications'),
                                   _age_line(entry), state.get('why'))


def _describe_notifications(rows, age, why=''):
    if not isinstance(rows, list) or not rows:
        said = str(why or '').strip()
        return (f'{said}{age}.' if said
                else "Elten has no notifications waiting" + age + ".")
    lines = [f"{len(rows)} notification(s) in Elten{age}:"]
    for row in rows[:40]:
        if not isinstance(row, dict):
            continue
        kind = str(row.get('cat') or '').strip()
        text = str(row.get('text') or '').strip()
        lines.append(f"- {text}" + (f" [{kind}]" if kind else ''))
    return '\n'.join(lines)


def elten_client_news(**_):
    """What has arrived in Elten since it was started - the counts Elten's
    own interface shows."""
    answered, live = _ask('news')
    if answered and isinstance(live, str):
        return live
    if answered and isinstance(live, dict):
        return _describe_news(live.get('news'), '')
    entry = _latest()
    if entry is None:
        return "Elten has not reported anything yet."
    state = entry.get('state') or {}
    if _not_shared(state):
        return NOT_SHARED
    return _describe_news(state.get('news'), _age_line(entry))


def _describe_news(counts, age):
    if not isinstance(counts, dict) or not counts:
        return "Elten reports nothing new" + age + "."
    # Elten's own category names on the left, said in words on the right.
    # A category this build does not know keeps Elten's word for it: a
    # count with a name nobody recognises is still a count, and dropping
    # it would be hiding something that is waiting.
    known = {'notifications': 'waiting', 'message': 'private messages',
             'messages': 'private messages', 'mail': 'letters',
             'forum': 'forum replies', 'followedforum': 'forum replies',
             'followedforumpost': 'forum replies', 'post': 'forum replies',
             'friend': 'friend requests', 'friends': 'friend requests',
             'online': 'people who came online', 'blog': 'blog posts',
             'comment': 'comments', 'program': 'programs',
             'programs': 'programs', 'update': 'updates',
             'updates': 'updates'}
    lines = []
    # The total goes first and the kinds after it, which is the order
    # somebody asking "anything in Elten?" wants to hear them in.
    for key, value in sorted(counts.items(),
                             key=lambda pair: pair[0] != 'notifications'):
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number <= 0:
            continue
        lines.append(f"{number} {known.get(str(key), str(key))}")
    if not lines:
        return "Elten reports nothing new" + age + "."
    return f"In Elten{age}: " + ', '.join(lines) + '.'


# --------------------------------------------------------------------------- #
# What is on Elten's screen, and opening one of its programs
#
# These three have no remembered half. A screen is what is showing NOW - a
# minute-old one is not a worse answer, it is a wrong one - and opening a
# program is something that either happens in the running Elten or does not
# happen at all. So they are asked, and when Elten is not there they say so.
# --------------------------------------------------------------------------- #
def _needs_elten():
    """Why Elten could not be asked - the real reason where there is one.

    "It is not running, or it has not given permission" is one sentence
    covering three different things, and for the two it gets wrong it
    sends the user to check a setting that is already on. The bus says
    which it was: a peer that is not there, an add-on that refused, or a
    question that was not answered in time.
    """
    problem = _LAST_PROBLEM[0]
    if problem:
        return "Elten did not answer: %s" % problem
    try:
        from src.titan_core.actions import bus
        if bus.get_peer(CLIENT_ID) is None:
            return ("Elten is not running, or the TCE bridge add-on is not "
                    "open in it.")
    except Exception:
        pass
    return ("The TCE bridge in Elten has not been given permission to share "
            "Elten's data with Titan - it asks once, and the answer is in "
            "its own settings ('Share Elten's data with TCE').")


def elten_client_render_log(**_):
    """What the TCE-application renderer in Elten last saw.

    "The key does nothing" is a report with no evidence in it. The
    renderer's own loop is the only place that knows whether the key
    arrived at all, whether the control under the cursor kept it, and
    what was sent - so it is read rather than guessed at.
    """
    answered, live = _ask('render_log')
    if not answered:
        return _needs_elten()
    if isinstance(live, str):
        return live
    lines = (live or {}).get('log') or []
    if not lines:
        return ("The renderer has seen no keys yet - no TCE application is "
                "open in Elten, or none has been worked.")
    return '\n'.join(str(line) for line in lines)


def elten_client_screen(**_):
    """What is on Elten's screen at this moment."""
    answered, live = _ask('screen')
    if not answered:
        return _needs_elten()
    if isinstance(live, str):
        return live
    if not isinstance(live, dict):
        return _needs_elten()
    if live.get('error'):
        return f"Elten could not be read: {live['error']}"
    lines = []
    where = str(live.get('scene') or '').strip()
    if where:
        lines.append(f"Elten is on its {where} screen.")
    said = str(live.get('said') or '').strip()
    if said:
        # For a program that is not drawn, the sentence the user just heard
        # is the closest thing there is to "what is showing".
        lines.append(f"It last said: {said}")
    for control in (live.get('controls') or []):
        lines.extend(_describe_control(control, ''))
    if not lines:
        return "Elten is running, and there is nothing on its screen to read."
    return '\n'.join(lines)


def _describe_control(control, indent):
    """One control, in words. A form is opened out into its own fields with
    the focused one marked - a form reported as one thing called "form" says
    nothing about what the user is on."""
    if not isinstance(control, dict):
        return []
    kind = str(control.get('kind') or '')
    here = ' <- the keyboard is here' if control.get('focused') else ''
    if kind == 'form':
        out = [f"{indent}A form:"]
        for field in (control.get('controls') or []):
            out.extend(_describe_control(field, indent + '  '))
        return out
    if kind == 'list':
        header = str(control.get('header') or 'A list')
        return [f"{indent}{header}: {control.get('count', 0)} item(s), on "
                f"\"{control.get('current') or ''}\"{here}"]
    if kind == 'field':
        header = str(control.get('header') or 'A field')
        text = str(control.get('text') or '')
        return [f"{indent}{header}: \"{text}\"{here}"]
    if kind == 'button':
        return [f"{indent}Button: {control.get('label') or ''}{here}"]
    if kind == 'checkbox':
        state = 'ticked' if control.get('checked') else 'not ticked'
        return [f"{indent}{control.get('header') or 'A tick box'}: "
                f"{state}{here}"]
    return []


def elten_client_programs(**_):
    """The programs installed in Elten, as its own menu lists them."""
    answered, live = _ask('programs')
    if not answered:
        return _needs_elten()
    if isinstance(live, str):
        return live
    rows = (live or {}).get('programs')
    if not isinstance(rows, list) or not rows:
        return "Elten has no programs installed."
    names = [str(row.get('name') or '') for row in rows
             if isinstance(row, dict)]
    return ("Programs in Elten:\n"
            + '\n'.join(f"- {name}" for name in names if name))


def elten_client_run_program(name='', **_):
    """Open one of Elten's own programs, in Elten."""
    wanted = str(name or '').strip()
    if not wanted:
        from src.titan_core.actions.interaction import needs
        return needs('name', "Which of Elten's programs should be opened?")
    answered, live = _ask_with('run_program', {'name': wanted})
    if not answered:
        return _needs_elten()
    if isinstance(live, str):
        return live
    if isinstance(live, dict) and live.get('error'):
        from src.titan_core.actions.interaction import fails
        return fails(str(live['error']))
    opened = (live or {}).get('opened') if isinstance(live, dict) else None
    return f"Opened {opened} in Elten." if opened else f"Opened {wanted} in Elten."


def elten_client_press(keys='', **_):
    """Press a key in Elten, as the person sitting there would.

    The one thing here that DRIVES Elten rather than reading it, and the
    reason it is confirmed twice: Enter in a messenger sends the message.
    Elten's side is off by default and says so.
    """
    wanted = str(keys or '').strip()
    if not wanted:
        from src.titan_core.actions.interaction import needs
        return needs('keys', "Which key should be pressed in Elten? "
                             "For example 'down', 'enter' or 'ctrl+s'.")
    answered, live = _ask_with('press_key', {'keys': wanted})
    if not answered:
        return _needs_elten()
    if isinstance(live, str):
        return live
    if isinstance(live, dict) and live.get('error'):
        from src.titan_core.actions.interaction import fails
        return fails(str(live['error']))
    pressed = (live or {}).get('pressed') if isinstance(live, dict) else None
    if not pressed:
        return f"Pressed {wanted} in Elten."
    return "Pressed " + ', '.join(str(key) for key in pressed) + " in Elten."


def elten_client_api_batch(names):
    """Many names in one round trip. {name: description} or None.

    A checker comparing a whole port against the real Elten asks about
    hundreds of names, and one round trip each - through a pipe, through a
    worker, through Elten's own tick - is a checker nobody runs.
    """
    wanted = list(names or [])
    if not wanted:
        return {}
    answered, live = _ask_with('api', {'names': ','.join(wanted)})
    if not answered or not isinstance(live, dict):
        return None
    table = live.get('api')
    return table if isinstance(table, dict) else None


def elten_client_api(name='', **_):
    """What the REAL Elten's API is for one name.

    The other half of the Elten work in this repository is a PORT - Elten's
    API re-implemented on top of Titan so an `.eltenapp` runs inside Titan -
    and everything that has ever gone wrong with it went wrong the same way:
    a signature guessed from call sites instead of read from Elten. This
    asks the client that is running, which is the right authority when a
    checkout and the user's own Elten differ.
    """
    wanted = str(name or '').strip()
    if not wanted:
        from src.titan_core.actions.interaction import needs
        return needs('name', "Which name? A function ('player'), a class "
                             "('ListBox') or a method ('ListBox#set_text').")
    answered, live = _ask_with('api', {'name': wanted})
    if not answered:
        return _needs_elten()
    if isinstance(live, str):
        return live
    if not isinstance(live, dict):
        return _needs_elten()
    if live.get('error'):
        return f"Elten could not answer: {live['error']}"
    if not live.get('defined'):
        return f"The Elten running here has no {wanted}."
    lines = [f"{live.get('name') or wanted} is "
             f"{'a ' + str(live.get('kind')) if live.get('kind') else 'there'}."]
    if live.get('parent'):
        lines.append(f"It inherits {live['parent']}.")
    if live.get('owner') and live['owner'] != live.get('name'):
        lines.append(f"Defined on {live['owner']}.")
    parameters = live.get('parameters')
    if isinstance(parameters, list):
        lines.append("It takes: " + (_signature(parameters) or "nothing"))
    for key, label in (('methods', 'Methods'),
                       ('class_methods', 'Class methods')):
        names = live.get(key)
        if isinstance(names, list) and names:
            lines.append(f"{label}: " + ', '.join(str(n) for n in names))
    if live.get('source'):
        lines.append(f"Written at {live['source']}.")
    return '\n'.join(lines)


def _signature(parameters):
    """Ruby's own parameter shapes, said the way a signature is written -
    which is the whole point: positional, optional and keyword are three
    different things, and getting one wrong is an ArgumentError inside
    somebody else's program."""
    written = []
    for entry in parameters:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        kind, name = str(entry[0]), str(entry[1])
        if kind == 'req':
            written.append(name)
        elif kind == 'opt':
            written.append(f"{name} (optional)")
        elif kind == 'rest':
            written.append(f"*{name}")
        elif kind == 'keyreq':
            written.append(f"{name}: (required)")
        elif kind == 'key':
            written.append(f"{name}:")
        elif kind == 'keyrest':
            written.append(f"**{name}")
        elif kind == 'block':
            written.append(f"&{name}")
    return ', '.join(written)


def elten_client_eapi_calls(**_):
    """What of Elten's own API is reachable from here."""
    answered, value = _ask('eapi_calls')
    if not answered:
        return _needs_elten()
    if isinstance(value, str):
        return value
    rows = (value or {}).get('calls') or []
    if not rows:
        return "Elten's API is not reachable from here."
    lines = ["Elten's own API, as this bridge offers it:"]
    for row in rows:
        note = ''
        if row.get('writes'):
            note = (' - acts in your name'
                    if row.get('allowed')
                    else ' - acts in your name, and is switched off')
        lines.append('- %s%s' % (row.get('name', ''), note))
    return '\n'.join(lines)


def elten_client_eapi(call='', args='', **_):
    """One call into the API of the Elten the user is sitting in front of.

    **A different question from `elten_*`**, which asks the EltenLink
    SERVER with the credentials Titan saved: this asks the running
    CLIENT, so it answers about the program in front of the user and
    costs no network at all. What it may reach is a table inside the
    bridge and never a name resolved from this side - a caller cannot
    name a Ruby method by spelling it.
    """
    wanted = str(call or '').strip()
    if not wanted:
        return "Say which call. 'elten_client eapi_calls' lists them."
    payload = {'call': wanted}
    if args not in (None, '', {}):
        payload['args'] = args if isinstance(args, str) else json.dumps(args)
    answered, value = _ask_with('eapi', payload)
    if not answered:
        return _needs_elten()
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return "Elten answered nothing."
    if value.get('error'):
        return str(value['error'])
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def elten_client_report(**_):
    """Everything the bridge last said, as JSON - for a caller that wants
    the numbers rather than the sentence."""
    entry = _latest()
    if entry is None:
        return json.dumps({'connected': _connected(), 'state': None},
                          ensure_ascii=False)
    return json.dumps({'connected': _connected(),
                       'age': round(time.time() - float(entry.get('at') or 0), 1),
                       'state': entry.get('state') or {}},
                      ensure_ascii=False, default=str)


def get_elten_client_actions():
    """(name, summary, params, risk, run) for each, as the shell's are."""
    return (
        ('status',
         "Whether the Elten client is running on this machine and who is "
         "signed in to it. Answered from inside Elten, by the TCE bridge "
         "add-on, so it knows what Elten is actually showing.", {},
         'auto', elten_client_status),
        ('notifications',
         "The notifications Elten itself is holding right now - a private "
         "message, a forum reply, somebody coming online. These are ELTEN's "
         "own, not Titan's; Titan's are titan.notifications.", {},
         'auto', elten_client_notifications),
        ('news',
         "What has arrived in Elten since it started, as counts: unread "
         "messages, letters, forum topics.", {},
         'auto', elten_client_news),
        ('report',
         "Everything the Elten client last reported, as JSON, with how many "
         "seconds ago it said it.", {},
         'auto', elten_client_report),
        ('screen',
         "What is on Elten's screen at this moment: what it last said, "
         "which screen it is on, and the controls that screen is holding. "
         "Elten is self-voicing, so the sentence it last said is the "
         "closest thing there is to what is showing.", {},
         'auto', elten_client_screen),
        ('programs',
         "The programs installed in Elten, as its own menu lists them.", {},
         'auto', elten_client_programs),
        ('render_log',
         "What the renderer showing a TCE application in Elten last saw: "
         "which keys arrived, which the control under the cursor kept for "
         "itself, and what was sent to the application. Read this when a "
         "key 'does nothing' - it says which of those it was.", {},
         'auto', elten_client_render_log),
        ('run_program',
         "Open one of Elten's own programs. It appears in Elten, in front "
         "of whoever is sitting there - so it is confirmed first.",
         {'name': {'type': 'string', 'required': True,
                   'description': "The program's name, as Elten lists it."}},
         'confirm', elten_client_run_program),
        ('api',
         "What the REAL Elten's API is for one name - whether it exists, "
         "what arguments it takes and where it is written. 'player', "
         "'ListBox', 'ListBox#set_text'. This is how the Elten API port in "
         "data/components/elten_bridge is checked against the client the "
         "user actually has, instead of against a guess.",
         {'name': {'type': 'string', 'required': True,
                   'description': "A function, a class, or Class#method."}},
         'auto', elten_client_api),
        ('eapi_calls',
         "What of ELTEN's own API this bridge offers, and which of those "
         "act in the user's name rather than only reading. Ask this "
         "before eapi rather than guessing a call name.", {},
         'auto', elten_client_eapi_calls),
        ('eapi',
         "Call Elten's own API in the client the user is sitting in front "
         "of: their account, the client's own state, one of its settings, "
         "what is installed in it, what it says out loud. A DIFFERENT "
         "question from the elten_* actions, which ask the EltenLink "
         "server - this asks the running program, so it is true offline "
         "and about the Elten actually in front of them. It needs the "
         "user's wider consent in the bridge, asked separately from the "
         "one that shares notifications.",
         {'call': {'type': 'string', 'required': True,
                   'description': "The call, as eapi_calls lists it."},
          'args': {'type': 'string',
                   'description': "Its arguments as a JSON object, when "
                                  "it takes any."}},
         'confirm', elten_client_eapi),
        ('press_key',
         "Press a key in Elten, as the person sitting there would - "
         "'down', 'enter', 'ctrl+s'. Several are separated by commas and "
         "pressed in order. It is off by default in the bridge's own "
         "settings, because pressing a key in Elten is not the same as "
         "reading it: Enter in a messenger sends the message. Read the "
         "screen first (elten_client screen) and again afterwards.",
         {'keys': {'type': 'string', 'required': True,
                   'description': "The key, or a combination like "
                                  "'ctrl+s', or several separated by "
                                  "commas."}},
         'confirm', elten_client_press),
    )

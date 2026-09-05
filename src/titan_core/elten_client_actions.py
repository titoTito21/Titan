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
ASK_TIMEOUT = 8.0


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
        return False, None
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
    if isinstance(waiting, list):
        lines.append(f"{len(waiting)} notification(s) waiting in Elten.")
    elif isinstance(waiting, int):
        lines.append(f"{waiting} notification(s) waiting in Elten.")
    if age:
        lines[-1] = lines[-1] + age
    return '\n'.join(lines)


def elten_client_notifications(**_):
    """What Elten's own notification service is holding right now."""
    answered, live = _ask('notifications')
    if answered and isinstance(live, str):
        return live
    if answered and isinstance(live, dict):
        return _describe_notifications(live.get('notifications'), '')
    entry = _latest()
    if entry is None:
        return ("Elten has not reported anything yet. It reports a few "
                "seconds after it starts, and only while it is running.")
    state = entry.get('state') or {}
    return _describe_notifications(state.get('notifications'), _age_line(entry))


def _describe_notifications(rows, age):
    if not isinstance(rows, list) or not rows:
        return "Elten has no notifications waiting" + age + "."
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
    return ("Elten is not running, or the TCE bridge in it has not been "
            "given permission to share Elten's data with Titan.")


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
        ('run_program',
         "Open one of Elten's own programs. It appears in Elten, in front "
         "of whoever is sitting there - so it is confirmed first.",
         {'name': {'type': 'string', 'required': True,
                   'description': "The program's name, as Elten lists it."}},
         'confirm', elten_client_run_program),
    )

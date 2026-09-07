"""The Elten client on this machine, for the AI.

Titan already has `elten_tools.py`, and it is a different thing: it signs in
to EltenLink over the network with the credentials in `titan.IM` and asks the
SERVER. What it cannot answer is "what is Elten showing right now" - whether
it is even running, who is signed in to that process, what its own
notification service is holding - because it is not Elten.

The TCE bridge (`elten-tce-bridge/`) is. It runs as an Elten application, joins
Titan's Action Bus as a client, and reports what Elten knows every few
seconds; `src/titan_core/elten_client_actions.py` keeps the last report. These
are the tools over it, so "have I anything waiting in Elten?" is a question the
assistant can answer, and so is "is Elten open?".

Nothing here asks Elten anything: every answer is what the bridge last said,
with how long ago it said it, so a stale answer is visibly stale. Elten not
running is an answer rather than an error - it is the true and useful thing to
tell the user.
"""

from src.titan_core import elten_client_actions as client


def elten_client_status(**_):
    """Whether Elten is running, and who is signed in to it."""
    return client.elten_client_status()


def elten_client_notifications(**_):
    """What Elten's own notification service is holding right now."""
    return client.elten_client_notifications()


def elten_client_news(**_):
    """What has arrived in Elten since it started."""
    return client.elten_client_news()


def elten_client_screen(**_):
    """What is on Elten's screen at this moment."""
    return client.elten_client_screen()


def elten_client_programs(**_):
    """The programs installed in Elten."""
    return client.elten_client_programs()


def elten_client_run_program(name="", **_):
    """Open one of Elten's own programs, in Elten."""
    return client.elten_client_run_program(name=name)


def elten_client_press(keys="", **_):
    """Press a key in Elten."""
    return client.elten_client_press(keys=keys)


def elten_client_api(name="", **_):
    """What the real Elten's API is for one name."""
    return client.elten_client_api(name=name)


def elten_client_eapi_calls(**_):
    """What of Elten's own API is reachable from here."""
    return client.elten_client_eapi_calls()


def elten_client_eapi(call="", args="", **_):
    """One call into the API of the Elten in front of the user."""
    return client.elten_client_eapi(call=call, args=args)


def get_elten_client_tools():
    from src.ai.agent_tools import _tool
    return [
        _tool('elten_client_status',
              "Whether the Elten desktop client is running on this machine "
              "and who is signed in to it. Answered from INSIDE Elten by the "
              "TCE bridge add-on, so it knows what Elten is actually showing "
              "- unlike elten_* , which asks the EltenLink server.",
              elten_client_status),
        _tool('elten_client_notifications',
              "The notifications ELTEN itself is holding right now - a "
              "private message, a forum reply, somebody coming online. Use "
              "this for 'have I anything waiting in Elten'. Titan's own "
              "notifications are a different list.",
              elten_client_notifications),
        _tool('elten_client_news',
              "What has arrived in Elten since it started, as counts.",
              elten_client_news),
        _tool('elten_client_screen',
              "What is on Elten's screen right now: which screen it is on, "
              "the sentence it last said, and the controls that screen is "
              "holding with the focused one marked. Elten is self-voicing, "
              "so what it last said is the closest thing there is to what "
              "is showing. Use this for 'what am I looking at in Elten'.",
              elten_client_screen),
        _tool('elten_client_programs',
              "The programs installed in Elten, as its own menu lists them.",
              elten_client_programs),
        _tool('elten_client_run_program',
              "Open one of Elten's own programs. It appears in Elten, in "
              "front of whoever is sitting there, so it is confirmed first.",
              elten_client_run_program, risk='confirm', always_confirm=True,
              properties={'name': {'type': 'string',
                                   'description': "The program's name, as "
                                                  "Elten lists it."}},
              required=['name']),
        _tool('elten_client_api',
              "What the REAL Elten's API is for one name: whether it "
              "exists, what arguments it takes and where it is written. "
              "'player', 'ListBox', 'ListBox#set_text'. Use it when working "
              "on the Elten API port in data/components/elten_bridge - it "
              "asks the client the user actually has, rather than guessing "
              "a signature from how an application calls it, which is how "
              "every bug in that port has been made.",
              elten_client_api,
              properties={'name': {'type': 'string',
                                   'description': "A function, a class, or "
                                                  "Class#method."}},
              required=['name']),
        _tool('elten_client_eapi_calls',
              "What of ELTEN's own API the TCE bridge offers, and which of "
              "those act in the user's name rather than only reading. Ask "
              "this before elten_client_eapi rather than guessing a call "
              "name - a name that is not in the bridge's table does not "
              "exist and cannot be reached by spelling it differently.",
              elten_client_eapi_calls),
        _tool('elten_client_eapi',
              "Call Elten's own API inside the client the user is sitting "
              "in front of: their account, what the client itself is doing, "
              "one of its settings, what is installed in it, or say "
              "something out loud in it. A DIFFERENT question from elten_* , "
              "which asks the EltenLink server - this asks the running "
              "program, so it is true with the network gone and it is about "
              "the Elten actually in front of them. It needs the user's "
              "wider consent in the bridge, which is asked separately from "
              "the one that shares notifications, so a refusal here is an "
              "answer and not an error.",
              elten_client_eapi, risk='confirm', always_confirm=True,
              properties={'call': {'type': 'string',
                                   'description': "The call, as "
                                                  "elten_client_eapi_calls "
                                                  "lists it."},
                          'args': {'type': 'string',
                                   'description': "Its arguments as a JSON "
                                                  "object, when it takes "
                                                  "any."}},
              required=['call']),
        _tool('elten_client_press',
              "Press a key in Elten, as the person sitting there would - "
              "'down', 'enter', 'ctrl+s'; several separated by commas are "
              "pressed in order. Use elten_client_screen first to see what "
              "is there, and again afterwards to see what happened. It is "
              "off by default in the bridge's settings, because pressing a "
              "key in Elten is not the same as reading it: Enter in a "
              "messenger sends the message.",
              elten_client_press, risk='confirm', always_confirm=True,
              properties={'keys': {'type': 'string',
                                   'description': "The key, a combination "
                                                  "like 'ctrl+s', or "
                                                  "several separated by "
                                                  "commas."}},
              required=['keys']),
    ]

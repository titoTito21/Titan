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
    ]

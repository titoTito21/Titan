# Writing a Titan client

## What this is for

Titan has eleven kinds of add-on, and every one of them lives inside Titan:
in its `data/` directory, discovered at startup, running in Titan's own
process or launched by it. This guide is about the twelfth thing, which is
not an add-on at all - **a program of your own, that Titan did not start and
does not manage, joining Titan as an equal.**

Two of them exist already and neither is special:

- **The NVDA add-on** (`nvda-addon/`) lives inside NVDA. Titan announces
  into it with a position, a pitch and a role; it answers what is on the
  screen right now, and offers Titan's own actions as NVDA commands.
- **The Elten bridge** (`elten-tce-bridge/`) lives inside EltenLink's
  client. It reports what Elten is holding, renders Titan's applications
  inside Elten's own interface, and lets Titan's AI reach Elten's API.

Everything either of those does, your program can do, with **no code added
to Titan**. That is the point of this guide: the two that exist are worked
examples, not privileged cases.

## The shape of it

There is one pipe, `\\.\pipe\TitanActions`, and it is bidirectional. Over it:

- **you call Titan** - one typed JSON surface (`titan.bridge`) plus every
  action of every add-on Titan has;
- **Titan calls you** - the handlers you declared when you joined.

You need one file: `src/titan_core/titan_actions.py`. Copy it next to your
own code. It imports nothing from Titan and nothing outside the standard
library, precisely so that it can be vendored into a wx application, a Tk
launcher, a console script or somebody else's program.

```python
from titan_actions import serve, call, call_sequence, list_addons, is_connected
```

## Joining

```python
def weather(city='Warsaw', **_):
    """What the weather is doing."""
    return f"It is raining in {city}."


serve({'weather': weather},
      id='myprogram',                 # stable: it is how Titan names you
      label='My program',             # what a person is shown
      kind='client')                  # see "Add-on or client?" below
```

`serve` returns **at once**, whether or not Titan is running, and a daemon
thread keeps trying quietly. A program that waits for Titan to be there is a
program that will not start on a machine where Titan is not installed.

### Add-on or client?

`kind='client'` says *this is another program taking hold of Titan*, and it
changes two things:

- **Titan says so out loud** when you join and when you leave. Nothing else
  on the desktop would tell a blind user that another program had connected
  to it.
- **Anything that would CHANGE Titan is behind the user's consent**, asked
  once, remembered under your id, and revocable
  (`titan.external_clients`, `titan.allow_client`, `titan.forget_client`).
  Reading Titan is always served, so a client that only shows Titan works
  before any question is answered.

Use one of the add-on kinds (`app`, `game`, `component`, ...) only when your
program really is a Titan add-on that Titan launched.

## Being called: what you declare, and what you merely serve

The handlers you pass to `serve` are what Titan **can** call. The `actions`
list is what Titan is **told** you offer:

```python
serve(handlers,
      id='myprogram', label='My program', kind='client',
      actions=[
          {'name': 'weather',
           'summary': 'What the weather is doing.',
           'params': {'city': {'type': 'string', 'required': True,
                               'description': 'Which city.'}}},
          {'name': 'send_report',
           'summary': 'Send today\'s report to the team.',
           'params': {}, 'risk': 'always_confirm'},
      ])
```

Leave `actions` out and it is derived from your handlers' signatures and
docstrings, which is enough to work. Write it out and you get three things
that matter:

- **A summary a person reads.** It is what the assistant is shown, what a
  macro author browses, and what appears beside the action everywhere.
- **Typed parameters**, so Titan can ask for a missing one properly instead
  of your handler receiving nothing and failing.
- **A risk level** - `auto`, `confirm`, `always_confirm` - so something that
  cannot be taken back is confirmed before an AI does it on its own
  initiative.

**Declare less than you serve.** Only what you declare becomes visible, and
only what you declare can be reached through the action layer
(`titan.list_actions`, the assistant, a macro, another add-on). An
undeclared handler is still SERVED - Titan's own subsystems call one by name
over the bus - but a caller going through the public action layer is told
the action does not exist. That is the right way round, and it is what lets
the NVDA add-on serve `announce`, `attach` and `stand_down` - the channel's
own plumbing, which Titan's reader layer calls directly - while offering
none of them to anybody as things to do.

### What you get for declaring

Titan builds a **real add-on** out of your declaration
(`src/titan_core/actions/registry.py`, `_merge_bus`). From that moment your
actions are:

- in `titan.list_actions` and in the Action API for every other add-on;
- offered to the AI assistant and the agent as things they can do;
- callable from a **Titan Script** (`myprogram.weather city="Krakow"`);
- runnable from the macro manager, the shell, and any other client.

None of that needed a line of code in Titan. Your add-on appears while your
program is running and disappears when it exits, with `source` reported as
`bus`.

### Answering

Return a string and it is what the caller is told. Return anything else and
it is serialised as JSON, which is what a program on the other end wants.
Three outcomes exist, not two - see "Asking for what you need" below.

Your handler is called with the named arguments Titan sends, and **arguments
it does not declare are dropped**, so adding a parameter later never breaks
an older handler.

## Calling Titan

### The typed surface

```python
import json
answer = call('titan', 'bridge', request=json.dumps(
    {'call': 'macros.list', 'args': {}}))
data = json.loads(str(answer))['data']
```

`titan.bridge` answers **JSON in one shape** - `{"ok": ..., "data": ...}` -
and it is what a program should use. There is a second way to reach the same
things: actions answer prose, in the user's own language, because they are
written for a model and for macros. Do not parse that. Every live bug the
Elten bridge hit was exactly that: the whole line `- Voice demo (ctrl+alt+v)
[tcs]` handed back as a macro's *name*.

The surface covers what a client showing Titan needs: `apps.list`,
`apps.open`, `games.*`, `im.*`, `macros.list`, `cling.list`, `settings.*`,
`widgets.*`, `buffers.*`, `notifications.*`, `speech.*`, `ai.ask`,
`sounds.play`, `window.state`, `app.*` (Titan's applications with their
interface as data), and `addons.list` / `addons.actions` / `addons.run` for
everything nobody has written a call for. Ask `capabilities` for the list
this Titan really has, rather than guessing.

### Somebody else's action

```python
call('tedit', 'open_file', path=r'C:\notes\today.txt')
call_sequence([{'addon': 'tnotes', 'action': 'create_note',
                'args': {'title': 'Ideas'}},
               {'addon': 'titan', 'action': 'speak',
                'args': {'text': 'Written: {{1}}'}}])
```

`list_addons()` is what there is. There is deliberately **no permission wall
between add-ons**: a client that has been allowed to drive Titan reaches
everything, because the whole point is that nothing has to ship its own
editor, browser, file manager or downloader.

## Asking for what you need

An action has three outcomes, not two. Besides "done" and "could not", it
can say **it needs to know something first**:

```python
from titan_actions import needs, fails

def send_report(recipient='', **_):
    if not recipient:
        return needs('recipient', 'Who should get the report?',
                     options=['the team', 'just me'])
    ...
    return f"Sent to {recipient}."
```

A caller then asks the user and calls again with the answer. Without this, a
key bound to "send the report" is a key bound to a refusal. A **required
parameter that was not supplied becomes a question automatically**, built
from its `description`, so declaring your parameters properly gets you most
of this for free.

## Telling Titan about your own program

Two calls exist for the direction nobody else can serve - news from inside
the program you are in:

- `notifications.add` puts something where Titan's own notifications go: the
  notification centre, the Titan buffer, the notification sound. Name your
  program in it; the user should know where it came from.
- `client.report` parks a snapshot of your program's state, which Titan
  keeps and can answer questions from when you are no longer running - and
  it says *how old* the answer is, so a stale one is visibly stale.

Both are served without the drive consent, because a program reporting about
itself is not a program driving Titan. Do not use them for anything else.

## Rules that are not negotiable

These are not style. Every one of them is something this repository got
wrong once and fixed.

**Never make Titan wait.** Your handler is called with Titan on the other
end of a pipe, often from a focus handler or an interface thread. Do the
work on a thread of your own and return; answer with what you know, not with
what you are about to find out. If you must marshal onto your own interface
thread, pass `marshal=`; if your handlers already do that themselves, pass a
`marshal` that just calls the function, or every call waits for your
message loop.

**A table is the boundary.** If Titan can name something and you resolve it
with `getattr`, whatever is on the other end of that pipe can reach anything
in your process. Write the calls down in a dict. A name that is not in it
does not exist.

**A refusal is an answer.** When you will not do something - a switch is
off, the user said no, the feature is missing - say so in a sentence the
user could act on. A refusal that arrives as a transport error is reported
as "the program did not respond", which is neither true nor actionable.

**Say which of the reasons it was.** "Not running", "refused", "did not
answer in time" and "this version does not have that call" are four
different things and the user does something different about each. Telling
somebody to check a setting that is already on is worse than saying nothing.

**Degrade, never disappear.** Ask what the other side can do rather than
assuming; skip what it has not got and say why. A feature that is quietly
absent is indistinguishable from one that is broken - and for a user who
cannot see the screen, that distinction is the whole difference between
"try something else" and "this is faulty".

**Nothing an emoji, nothing invented.** Titan's user-facing text is English,
translated with gettext, and never carries emoji. A control that has no name
has no name: say so rather than inventing one.

## Two worked examples

- `nvda-addon/addon/globalPlugins/titanEnhancements/link.py` - joining,
  declaring less than you serve, and a bidirectional channel where Titan
  calls you far more often than you call Titan.
- `elten-tce-bridge/titan_bus.rb` - the same protocol in Ruby, in a program
  written by somebody else, with the user's consent asked on that side too.

Neither of them is reached by anything in Titan that knows its name.

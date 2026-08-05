# Titan Action API - letting Titan call your add-on

## What this is for

Your add-on can do things. A text editor opens and saves files, a media player
plays them, a file manager copies them, a component watches something. Until
you declare those things, nothing outside your add-on can ask for them: not the
user through another add-on, not a component, and not Titan's AI agent or voice
assistant.

The Action API is one file that says what your add-on can do, and one module
that does it. Once both exist, this works from anywhere in Titan:

```python
from src.titan_core import actions

actions.run('tedit', 'open_file', path=r'C:\notes.txt')
```

and the AI can do the same thing because the user asked it to in words.

This is optional. An add-on without a manifest keeps working exactly as before.

## The two files

Put them in your add-on's own directory, next to its existing manifest
(`__app.TCE`, `__component__.TCE`, `applet.json`, ...):

```
data/applications/tEdit/
    __app.TCE           <- your existing manifest, unchanged
    __actions.json      <- what you can do
    tedit_actions.py    <- how you do it
    tedit.py
```

Both are picked up identically when your add-on ships as a packaged `.TCA` or
`.TCD` file, so packaging changes nothing here.

## `__actions.json`

```json
{
  "version": 1,
  "id": "tedit",
  "label": "Text Editor",
  "description": "Opens, edits and saves text files.",
  "transport": "process",
  "entry": "tedit_actions.py",
  "launch_if_needed": true,
  "actions": [
    {
      "name": "open_file",
      "summary": "Open a text file in the editor.",
      "params": {
        "path": {"type": "string", "required": true,
                 "description": "Full path of the file to open."}
      },
      "risk": "confirm",
      "mode": "live",
      "promote": true
    }
  ]
}
```

| Key | Meaning |
| --- | --- |
| `id` | Stable identifier. This is what callers type. Lowercase, letters, digits, underscores. Defaults to the folder name. |
| `label` | Human name, used when Titan or the AI talks about your add-on. |
| `description` | One sentence on what the add-on is for. The AI reads this when deciding whether you are the right add-on for a request. |
| `transport` | `process` for applications and games, `inproc` for everything else. You rarely need to set it - the default is right for your kind. |
| `entry` | The module holding your handlers, relative to your directory. It must be inside your directory. |
| `launch_if_needed` | May Titan start your application to deliver an action? Default `true`. |

Each action:

| Key | Meaning |
| --- | --- |
| `name` | What the action is called. Lowercase with underscores. |
| `summary` | One sentence, in the imperative: "Open a text file in the editor." This is what the AI is shown, so write it for a reader who has never seen your add-on. |
| `params` | Named parameters. Types: `string`, `number`, `integer`, `boolean`. Mark the ones you cannot work without as `"required": true`. Give every one a `description`. |
| `risk` | `auto` (just do it), `confirm` (the user is asked first), `always_confirm` (asked every time, whatever their settings say). Anything that writes, sends, deletes or spends money is at least `confirm`. |
| `mode` | `live`, `headless` or `any`. See below. |
| `timeout` | Seconds a headless run may take, when the default 45 is not enough. |
| `launch_if_needed` | May Titan start the add-on to deliver *this* action? Overrides the add-on's setting. Set it `true` only where showing the user something is the point ("open this file"); an action that reports on the open window ("what have you got open") must leave it false, or Titan opens a fresh window to answer a question about nothing. |
| `promote` | `true` makes it a first-class AI tool instead of one reached through a generic dispatcher. Promote the two or three things users actually ask for; leave the rest alone. |

## The three modes - and why `live` is the last resort

Applications and games run in their own process, which is why `mode` exists.

- **`headless`** - the action stands alone. Titan runs your action module as a
  short-lived process. Nothing appears on screen.
- **`any`** (the default) - the open instance when there is one, headless
  otherwise. **This is what almost everything should be.**
- **`live`** - the action *cannot work* without the running window.

**Do not make an action `live` because your window happens to be where you
wrote the code.** A user who asks for "a note, then read it out in my
ElevenLabs voice" is not going to open two applications first, and should not
have to. Ask whether the action really needs the window, or only your data:

| Really needs the window | Only needs your data |
| --- | --- |
| "save the document I have open" | "read this file", "write this file" |
| "what is selected right now" | "copy this to there", "find files called X" |
| "go back a page" | "what are my bookmarks" |
| "show me this page" | "download this file", "say this out loud" |

Everything in the right column belongs in a module that reads your settings
file and does the work - your API key, your download folder and your saved data
are all on disk, and the window is not what owns them. Titan's own ElevenLabs
and Download Manager actions are written exactly that way: they prefer the open
window when there is one, so the result joins its history and its list, and
work perfectly well without it.

Two practical notes for headless work:

- A long job gets `"timeout": 180` (seconds) in its manifest rather than being
  killed at the default 45.
- Anything that keeps going after the answer - playing audio, fetching a large
  file - is started **detached**, so the action can return at once and the work
  is not cut off when the short-lived process ends.

In-process add-ons (components, widgets, statusbar applets, TTS engines,
gamepad modes, launchers, Titan IM modules) ignore `mode` entirely: they are
already inside Titan, they are simply called, and they never need a window.

To have something read out, call `actions.run('titan', 'speak', text=...)` -
Titan's speech engines are in Titan's own process, so no window is involved and
no add-on needs a voice of its own.

## The handler module

A handler is an ordinary function. It gets the parameters it declares as
keyword arguments - parameters it does not declare are dropped, so adding one
later never breaks an old handler.

**Return a sentence.** The caller may be a screen reader reading it out or an AI
telling the user what it just did. `"Saved notes.txt."` is a good return value;
`True` is not.

```python
import os, sys

# Titan's root is on the path for every application it launches.
_TITAN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                           '..', '..', '..'))
if _TITAN_ROOT not in sys.path:
    sys.path.insert(0, _TITAN_ROOT)

_frame = None


def open_file(path):
    """Open a text file in the editor."""
    if not os.path.isfile(path):
        return f"There is no file at {path}."
    _frame.LoadFile(path)
    return f"Opened {os.path.basename(path)} in the text editor."


def read_file(path):
    """Read a text file without opening a window."""
    with open(path, encoding='utf-8', errors='replace') as handle:
        return handle.read()


LIVE_HANDLERS = {'open_file': open_file, 'read_file': read_file}
HEADLESS_HANDLERS = {'read_file': read_file}


def attach(frame):
    """Called once the window exists: from here on Titan can drive us."""
    global _frame
    _frame = frame
    try:
        from src.titan_core.titan_actions import serve
    except Exception as e:
        print(f"[tEdit] Titan actions unavailable: {e}")
        return False
    return serve(LIVE_HANDLERS, id='tedit', label='Text Editor', kind='app')


if __name__ == '__main__':
    from src.titan_core.titan_actions import run_cli
    sys.exit(run_cli(HEADLESS_HANDLERS))
```

And one call in your application's startup:

```python
if __name__ == "__main__":
    app = wx.App()
    frame = TextEditor(None)
    frame.Show()
    try:
        import tedit_actions
        tedit_actions.attach(frame)
    except Exception as e:
        print(f"[tEdit] Titan actions unavailable: {e}")
    app.MainLoop()
```

**Joining must never be fatal.** Your add-on has to run exactly as before when
Titan is not there, so wrap it and carry on.

### Threads

`serve()` answers Titan on a background thread. If your handler touches a
window, it must not run there. wxPython is detected and handled for you. A Tk
add-on passes its own marshaller:

```python
from src.titan_core.titan_actions import serve, tk_marshal
serve(HANDLERS, marshal=tk_marshal(root))
```

## Three outcomes, not two

A handler can end in three ways, and saying which one in prose is not enough -
a caller chaining several actions cannot tell "there is no such note" from
success, and carries on to the step that assumed otherwise.

```python
from src.titan_core.actions import fails, needs      # inside Titan
from src.titan_core.titan_actions import fails, needs  # in your own process
```

**It worked** - return a sentence.

```python
return f"Saved {os.path.basename(path)}."
```

**It could not** - return `fails(reason)`. The reason is what the user is
told, so write it for them.

```python
if not os.path.isfile(path):
    return fails(f"There is no file at {path}.")
```

**It needs to ask** - return `needs(name, prompt, options=...)`. Asking is an
outcome, not a failure: Titan hands the question to whoever called. The AI puts
it to the user and calls again with the answer; a component shows a dialog. The
action then runs once, with a real answer, instead of running now on a guess.

```python
if len(matches) > 1:
    return needs('which', f"'{name}' matches {len(matches)} macros. "
                 f"Which one should run?",
                 options=[m['name'] for m in matches])
```

Use `needs` where guessing would be **harmful or annoying**: a destination that
cannot be invented, an ambiguous name, something about to be overwritten. Do
not use it for a detail you can reasonably default - ask once, not three times.

You get some of this free: **a required parameter that was not supplied
becomes a question automatically**, built from the `description` in your
manifest. So write those descriptions as if a user will hear them, because
they will.

Answering, from a caller's side:

```python
result = actions.run('tfm', 'copy_path', source=path)
if result.pending:
    print(result.question.prompt, result.question.options)

# or let Titan do the whole loop, asking through a dialog:
actions.run_interactive('tfm', 'copy_path', source=path)
```

## Composite commands

"Write me a summary, save it as a note, then remind me about it tomorrow" is
three actions where the later ones need what the earlier one produced.

```python
actions.run_sequence([
    {'addon': 'tnotes', 'action': 'create_note',
     'args': {'title': 'Shopping', 'text': 'milk, bread'}},
    {'addon': 'tnotes', 'action': 'read_note', 'args': {'title': 'Shopping'}},
    {'addon': 'treminder', 'action': 'create_reminder',
     'args': {'name': 'Buy: {{2}}', 'date': 'tomorrow', 'time': '17:00'}},
])
```

`{{2}}` is what step 2 returned - the whole substitution language, on purpose.
The run stops at the first step that fails or asks, and `result.text` names
every step either way, so the user hears which parts happened.

From an application, in its own process, the same thing:
`titan_actions.call_sequence([...])`. The AI has it as `titan_run_actions`.

This is also why `fails()` matters: a step that reports trouble in prose looks
like success, and the sequence carries on regardless.

## In-process add-ons: no JSON needed

A component, widget, statusbar applet, TTS engine, gamepad mode, launcher or
Titan IM module can skip `__actions.json` entirely and declare actions in
Python, with real callables:

```python
def say_time():
    """Speak the current time."""
    import time
    return time.strftime("It is %H:%M.")


TITAN_ACTIONS = [
    {'name': 'say_time', 'summary': 'Speak the current time.',
     'run': say_time},
    {'name': 'set_alarm', 'summary': 'Set an alarm.',
     'params': {'time': {'type': 'string', 'required': True,
                         'description': 'When, as HH:MM.'}},
     'risk': 'confirm', 'run': set_alarm},
]
```

Titan finds this on the module it already loaded, so your handlers see your
add-on's live state. You can also ship both: the JSON describes the actions
well and `TITAN_ACTIONS` adds ones that only exist at runtime.

## Calling other add-ons

Your add-on is also a caller. Anything Titan can do, you can do:

```python
from src.titan_core import actions

for addon in actions.list_addons():
    print(addon['id'], addon['label'], addon['actions'])

result = actions.run('tmedia', 'play', query='the news')
if result:
    print(result.text)
else:
    print("could not:", result.text)
```

`run()` never raises. `result.ok` says whether it worked, `result.text` is
always worth showing to a user, and `result.raised()` turns a failure into an
exception if you would rather handle it that way.

That import works for anything running **inside** Titan: a component calling
another component, a widget calling a statusbar applet, a gamepad mode calling
a launcher. An **application or game** is a separate process, so importing the
registry there would build a second, blind copy that cannot see Titan's loaded
components or the other applications. From a separate process, ask Titan over
the connection you already have:

```python
from src.titan_core.titan_actions import call, list_addons

for addon in list_addons():
    print(addon['id'], addon['label'], addon['actions'])

result = call('tmedia', 'play', query='the news')
if result:
    print(result.text)
```

`call()` needs a connection, and the same one carries both directions. An
add-on that offers nothing and only wants to call others uses `connect()`
instead of `serve()`:

```python
from src.titan_core.titan_actions import connect, call

connect(id='myapp', label='My App')
call('tweb', 'open_url', url='https://example.org')
```

Neither raises, and both return the same truthy result object.

### Do not rewrite what Titan already has

There is no permission wall between add-ons: whatever another add-on declares,
you can call. That is deliberate, and it is the point of the whole contract -
nobody should ship their own editor, browser, file manager or downloader.

```python
actions.run('tedit', 'open_file', path=path)        # show text to the user
actions.run('tweb', 'open_url', url=url)            # show a web page
actions.run('tfm', 'copy_path', source=a, destination=b)
actions.run('tdownloader', 'download', url=url)     # fetch a file
actions.run('tnotes', 'create_note', title=t, text=body)
actions.run('treminder', 'create_reminder', name=n, date='tomorrow', time='09:00')
```

Each of those gets the user their own settings, their own download folder,
their own history and their own announcements - which a private copy inside
your add-on never would.

### Titan itself is callable too

Titan's own subsystems answer to the same three calls, so an add-on never has
to reach into `src/` to change something Titan owns:

| Provider | What it covers |
| --- | --- |
| `titan` | Titan's settings, components, add-ons, TTS engines, launching things |
| `settings` | finding and explaining a setting by what it does |
| `system` | volume, playback device, brightness, power plan, theme, Wi-Fi, autostart |
| `gamepad` | the gamepad's modes - list, read, set, cycle |
| `titannet` | forum topics and replies, mail, groups, rooms, private messages |
| `elten` | Elten messages, forums, blogs |
| `im` | WhatsApp and Messenger conversations |
| `ocr` | reading an inaccessible window, and pressing what it finds |
| `memory` | what the AI remembers between conversations |

```python
actions.run('system', 'set_volume', percent=30)
actions.run('gamepad', 'set_mode', mode='screen reader')
actions.run('titan', 'set_setting', key='rate', value='60')
```

`actions.list_addons()` and `actions.describe_addon(id)` enumerate everything -
built-in providers and installed add-ons alike - so nothing has to be
hard-coded. An installed add-on can never take one of these ids: if it declares
`id: "system"`, Titan keeps its own and makes the add-on reachable as
`system_addon`.

## Writing actions the AI can actually use

The AI has your `summary` and your parameter descriptions and nothing else.

- **Name the action after the user's intent**, not your internal method:
  `play_audiobook`, not `set_playlist_mode_2`.
- **Write the summary as an instruction**: "Play a whole folder as one
  audiobook, continuing from where the user stopped."
- **Say what a parameter accepts** in its description, including the formats:
  "'50%', '49 minutes' or '1:23:45'".
- **Return what actually happened**, including the parts that did not: "Played
  episode 6. Three other episodes matched - say which if this was the wrong
  one."
- **Offer a way to look before leaping.** An action that searches and returns
  identifiers pairs well with an action that acts on one of them, and stops the
  AI guessing.
- **Be honest about risk.** Getting `risk` wrong is the one mistake the user
  cannot undo.

## Checklist

- [ ] `__actions.json` sits in the add-on's own directory
- [ ] every action has a `summary` written for a stranger
- [ ] every parameter has a `description` and the right `type`
- [ ] anything that writes, sends or deletes is at least `risk: confirm`
- [ ] handlers return a sentence, not a boolean
- [ ] `serve()` is wrapped so a missing Titan never breaks the add-on
- [ ] GUI work is marshalled onto the interface thread
- [ ] at most two or three actions are `promote: true`

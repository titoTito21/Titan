# TCE bridge - Titan inside Elten

An Elten 3 application that makes TCE (Titan) reachable from Elten: its main
window, its settings, Titan-Net, the Titan shell, the computer's own
settings, the media library, the speech engines and every add-on it has -
plus **Titan's voices as an Elten speech output**.

It needs Titan running on the same machine. On its own it does nothing and
says so: *"This add-on needs TCE. Start Titan, then open this again."*

Verified against the Elten it runs on - **ELTEN 3.0.2, Ruby 4.0.6** - by
reading that client's own bundled sources through its MCP server, not
against the GitHub branch. `SpeechOutput.speak_text(_text, method:,
spelling:, interrupt:, pitch:)`, `Tasks.run(title:)`, `ListBox.new(options,
header:, index:, flags:, quiet:, empty_label:)` and its `:select` /
`:expand` / `:collapse` events, `EditBox` and its flags, `Form#update` and
`#focus`, `selector` / `select_action` / `display_text` / `input_text` are
each what this code calls them.

## Installing

```
ruby install.rb            # into %APPDATA%\elten\apps\src\tce_bridge
ruby install.rb --remove
```

Elten loads an **unpacked** application - a folder with `__app.rb` carrying
the `Elten3AppInfo` manifest is complete - so there is no packaging step, no
zstd and no signing key. An installed application is the folder *and* a line
in `apps/apps.json`; the installer writes both, replacing that file
atomically because Elten reads it at every start. **Restart Elten** after
installing: `Programs.load_all` runs once, while Elten is starting.

It speaks Polish and English. The catalogue is `locale/pl.mo`, read straight
off the folder (`Programs::Runtime#language_data`), so an unpacked
application ships translations exactly as a packaged one does.

## What is in it

**Titan's main window** (`titan_console.rb`), laid out the way
`src/ui/gui.py` lays it out, because it is that window: the tab bar is
Titan's own view registry - Applications, Games, Titan IM and any view a
component registered - plus the two categories Titan's non-visual face has
that its tab bar does not, **Widgets** and **Components**
(`src/ui/invisibleui.py` is the authority for "everything a Titan user can
reach without a screen"). The status bar underneath is what Titan's applets
are saying at this moment, and the menu is `src/ui/program_menu.py`, the
module every face of Titan builds its menu from. Enter launches an
application, presses a widget or runs a component's menu entry; the
context-menu key gives a row everything else it can do.

Applications and games are listed by the name Titan **shows and accepts**.
That is not a detail: `_discover_kind` answers with folder names, and
`titan.launch` matches the name in the manifest, so the list used to read
"tEdit, tNotes, tWeb" while Titan wanted "Edytor Tekstowy, Notatki,
Przegladarka internetowa" - and nothing opened. Games were worse: the
folders are `AI Dungeon game engine` and `smashathon` while the games Titan
actually lists are Cult of the Lamb, Battle.net and Hearthstone.

**The settings** (`titan_settings.rb`) - the window from `settingsgui.py`,
made out of Elten's controls and built from `src/settings/ui_model.py`, the
model Titan's own alternative settings interfaces are built on. **A control
appears as ITSELF**: a yes/no is a tick box, a choice is a choice with its
own options, a tick LIST is a multi-selection list (Space ticks a row and
the reader says Ticked), a number is a field that takes numbers, a password
is a password field, a button is a button. That is what a screen reader can
announce; one list holding a hundred settings would read as one control.
A secret is never displayed and an empty password field means "leave it
alone". Saving is Titan's own save, with everything that hangs off it.

**Titan-Net** (`titan_net.rb`) as a client, not a page of text: a row per
room, per person, per message, per topic, per letter, per package. Rooms,
who is online, private messages, the forum, Titan Mail, groups, the
**Feedback Hub** (what people asked for, with voting and writing), the
**application repository** (browse, read, download) and the
**announcements** - and the account itself: its address, who is blocked,
making a room or a group, and a message to everybody. Rooms and private
conversations have a field to write in and Enter reads a message in full; a
forum topic arrives with its replies; mail can be read, answered and
deleted. **You do not sign in again** - it speaks as whoever Titan is signed
in as, from the credentials Titan already saved, which is why the title
names that account.

**Titan IM** (`titan_im.rb`) as a client, not a launcher: the services
Titan's own Titan IM view lists - Telegram, Messenger, WhatsApp, Titan-Net,
EltenLink - and the installed Titan IM modules under them. Messenger and
WhatsApp open their conversations, with the messages in a list, Enter to
read one in full and a line to write in; Telegram opens who you can write
to and sends (reading a Telegram conversation belongs to its window in
Titan, and this says so rather than showing an empty list); Titan-Net and
EltenLink open their own. The context-menu key searches a conversation,
says who is in it and marks it read.

**The Titan shell** (`titan_shell.rb`), offered when Titan really is the
Windows shell - and then it is a **view of the main window**, called System
desktop, because that is what the user is sitting at. The desktop icons, the
taskbar's window buttons, the notification area, the drives, the shell's own
menu (properties, rename, delete, arrange, power, stopping the shell), and a
**Start menu** with Titan's own branches: Applications, Games, Titan IM,
Macros, Settings, All Programs and the ways out.

**The Macro Manager** (`titan_macros.rb`): the macros with their shortcuts,
Enter runs one, and the context-menu key reads, changes, checks, mends,
gives a shortcut or deletes. A script is written in a real editing field and
checked before it is saved. The Titan Script reference and the list of what
a script may call are read from the Macro Manager itself, so a statement
added to the language appears here with nothing changed.

**Cling** (`titan_cling.rb`): the Klango applications Titan has found, what
each one is, its scores and the account. Running one starts it in TITAN,
where the sound is - a Klango application is heard, not read.

**Titan AI** (`titan_ai.rb`), and only when Titan really has it
(`titan.ai_available`). A question is asked and answered HERE, in a page a
reader can move through; asking without tools is the default, and letting it
DO things is a separate entry that confirms first. AI OCR reads the window
in front and answers questions about it, the notes it keeps can be read and
forgotten, and the AI windows that are conversations open in Titan, where
they live.

**Everything else** (`titan_areas.rb`): the computer (volume, playback
device, brightness, power plan, theme, Wi-Fi, autostart), the open windows,
the media library and radio, and which voice Titan speaks with. Then macros,
the screen reader, AI OCR, what the AI remembers, gamepad modes, files and
programs, the browser, WhatsApp and Messenger, Cling - each opening its own
add-on's actions, with summaries and parameters asked for properly
(`titan_actions.rb`). That last path is why nothing Titan can do is
unreachable from here, **including an add-on installed after this was
written**.

**Titan's voices, as an Elten voice** (`titan_speech_output.rb`). Elten
registers a speech output by INHERITANCE - `SpeechOutput.inherited` collects
every subclass and `SpeechOutput.voices` is recomputed whenever it is asked
- so defining the class *is* the registration, and Titan appears in Elten's
ordinary voice list in Settings with nothing in Elten patched.

**Elten's main menu is left alone.** The manifest already puts the add-on in
the programs menu, and everything TCE has is inside its own window -
applications and games are the first two tabs there. An earlier version put
four entries at the top level of Elten's menu; that was clutter, and Elten's
menu belongs to Elten.

**A list shows things, never functions.** A view a component registers -
Cling, the macros - opens that component's own screen, or lists what the
component lists; what it can be *told to do* is on the context-menu key, one
row at a time. "list applications, run, details, scores" is a list written
for a programmer.

It offers **one** voice, called Titan, exactly as Elten's own NVDA output
offers one called NVDA: Titan's per-utterance API has no "say this in that
engine", so a voice per engine could only be honoured by switching Titan's
own engine - changing the whole desktop because somebody picked a voice in
Elten. Which engine speaks is Titan's setting, and this bridge has a screen
for it.

## A shape, not a sentence

Titan's ACTIONS answer in prose, in the user's own language, because they
are written for a model and for macros. Reading a list out of one is what
this add-on kept getting wrong, and every instance of it was a live bug the
user hit:

| what was read | what went back to Titan | what the user saw |
| --- | --- | --- |
| `macros.list_macros` | `- Voice demo (ctrl+alt+v) [tcs]` | *There is no macro called...* |
| `cling.list_applications` | `- Mole No More (mole, grid_hunt): ...` | *There is no Cling application called...* |
| `shell.power_options` | `logoff:` | *This computer can do: logoff, shutdown...* |
| `shell.list_drives` | `Windows` | a folder that does not exist |
| `shell.list_folder` | `1. appcompat - File folder` | a folder that does not exist |
| `im.list_chats` | `- Ala [3 unread]` | no conversation opened |
| `titan.list_im_contacts` | the whole sentence, as one contact | one row, nobody in it |

So the two lists whose rows are ACTED on by name come from the typed surface
instead - `macros.list` and `cling.list` in
`src/titan_core/bridge_api.py`, which give the name to hand back apart from
everything that is only there to be read - and the rest name what they are
parsing and are checked against Titan's own wording in
`tests/fake_titan.py`. A stand-in that invents an easier shape is how every
one of these passed the tests and failed in front of the user.

`tests/check_titan_actions.py` is the other half: it reads every action this
add-on names out of the Ruby and checks it against Titan's OWN registry, so
"'Cling' has no action 'list_apps'" is a failed test rather than a message
to the user.

## Titan's menu, and Titan's news

**The menu is the one every face of Titan has.** `src/ui/program_menu.py`
is the module Titan's window, its Invisible UI and Klango mode all build
their menu from, and all three present it as GROUPS you enter - Program,
AI, Programmer. This flattened them into one list of "Program: Settings",
"AI: AI Agent", which is neither Titan's menu nor a menu. The group is
chosen first and its entries second, and Escape at the second level is one
level back.

**Minimize and Bring Titan back are one entry, not two.** Which one applies
is a question about where Titan is - hidden with a tray icon and the
Invisible UI answering the keyboard, or in front of the user - and
`window.state` on the typed surface answers it. Offering both means
offering one that does nothing.

**Elten's own notifications go into Titan** (`elten_news.rb`). This is the
one thing that goes the other way through the wall: the bridge is the only
thing on the machine that is inside both, so a notification Elten raises -
a private message, a forum reply - is put into Titan's notification centre
as Titan's own are, with Titan's sound and Titan's reader, and is then in
the buffer system and in front of Titan's AI. It reads the list Elten's own
background service already keeps in memory, so it costs nothing and reaches
no network; the first look is what there IS and is never announced.

It also reports a snapshot of Elten - who is signed in, what is waiting -
which Titan keeps (`src/titan_core/elten_client_actions.py`). That is what
gives Titan's assistant `elten_client_status`,
`elten_client_notifications` and `elten_client_news`: "is Elten open?" and
"have I anything waiting in Elten?" are now questions it can answer, which
Titan's own `elten_*` tools cannot - those ask the EltenLink SERVER, and
this is asked from inside the running client. Switched off in Settings ->
"Show Elten's notifications in Titan too".

## Titan can ask Elten, not only be told

The bridge calls Titan constantly; the wire goes the other way too, and now
it is used. `TitanBus#serve` registers what TITAN may ask of US - `status`,
`notifications`, `news` - and the names travel in the hello, so Titan lists
them like any add-on's and its AI is told what they are for. That is what
makes "have I anything waiting in Elten?" a question answered by the running
Elten rather than by whatever was last pushed at Titan.

**The invoke is answered inside `read_answer`**, while this side is waiting
for an answer of its own, and that is not an optimisation: Titan may be
asking us something *because of* the very call we are waiting on, and a
reader that stepped over an invoke until its own answer arrived would be two
sides each waiting for the other. `tests/ui_test.rb` drives exactly that
interleaving - the stand-in Titan sends an invoke while answering a call -
because it is the one shape that would deadlock.

**One thread still owns the pipe.** A handler runs on the bus worker, so
every one of them is a cheap READ of state Elten's own service already holds
- no network, no waiting, and nothing that touches Elten's screen, which
belongs to Elten's own thread. A question that arrives while the worker is
idle waits out the idle tick (5 s at worst) before it is seen; Titan allows
eight.

**Consent is checked in every handler, not once at the door.** It can be
taken back at any moment, and an answer that was allowed a minute ago is not
an answer that is allowed now. A refused handler answers a SENTENCE rather
than a shape, and Titan passes that sentence through unchanged - so "no" is
read as no, not as an empty Elten. An action nobody wrote is refused by name
and the connection stays up.

On Titan's side `src/titan_core/elten_client_actions.py` asks when Elten is
there and falls back to the last report when it is not - and then says how
old it is, so a stale answer is visibly stale.

## Elten's own thread, and what only it can answer

The two directions above are answered wherever they land: the bus worker
reads a notification list Elten's background service keeps, or pushes a line
into Titan. Reading what is ON Elten's screen, and putting something on it,
cannot be - `insert_scene` runs Elten's own pump, and a scene's controls are
being changed by the thread that draws them.

So `elten_main.rb` is the marshaller, the same shape as Titan's own
`run_on_gui`: a job is posted, **the extension tick runs it**, and the caller
waits with a deadline. Three rules stop it becoming the thing that makes
Elten stutter - a job is short (a read of what is already in memory, or
`insert_scene`), a tick spends a BUDGET rather than the queue, and nobody
waits for ever: a tick that is not coming is a refusal after six seconds, not
a hang.

`elten_screen.rb` is what that buys:

* **`screen`** - what is on Elten at this moment. Elten is self-voicing, so
  the sentence it last said (`$speech_lasttext`, the same global its own "say
  that again" shortcut reads) is the closest thing there is to what is
  showing; beside it are the scene's name and the controls it is holding,
  read off the scene by SHAPE - anything answering like one of Elten's
  controls - rather than by a list of variable names that would go stale at
  the next Elten. A Form is opened out into its own fields with the focused
  one marked, because a form reported as one thing called "form" says nothing
  about what the user is on.
* **`programs`** and **`run_program`** - Elten's own programs as its main
  menu lists them (`Programs.list`), and opening one the way that menu opens
  it. This one ACTS, in front of whoever is sitting at Elten, so Titan marks
  it `confirm` and the assistant's tool always confirms.

All three check the consent for themselves, and a screen is as much Elten's
data as a notification is.

## Asked before Elten's data leaves Elten

Everything else here carries TITAN into Elten and needs nobody's permission
for it: it is the user's own desktop, reached from the program they are
sitting in. One thing goes the other way - what ELTEN knows about them, which
is data held in the Elten portal, and Titan's AI assistant is one of the
things that would then read it.

So it is asked for, once, in plain words, the first time the add-on is
opened:

> The AI assistant will use data stored on the Elten portal. Do you agree to
> share the necessary data with TCE?

* **Nothing is shared until it is answered.** Not the notifications, not the
  account name, not the fact that Elten is running. Somebody who never opens
  this add-on is never asked and nothing ever leaves.
* **No is a real answer.** Titan's window, its settings, Titan-Net, the
  shell and the AI itself all go on working, because none of that is Elten's
  data; only the Elten -> Titan direction stops.
* **It is asked where the user is**, at the top of the add-on's own window -
  never on the extension tick. A consent question that appears while
  somebody is reading their messages is one they answer to get rid of.
* **It can be taken back**, in this add-on's settings ("Share Elten's data
  with TCE"), and revoking it stops the sharing at the next tick.

`titan_consent.rb`. The wording is in the catalogue in both languages, and
`tests/check_translations.py` fails if it is not - a consent question that
arrives in English on a Polish Elten is not one the user can be said to have
agreed to.

**TCE's own settings are in this add-on's settings**, as an action button
next to the switches, because that is where somebody looks for "the settings
of the thing I am configuring" - and TCE's settings are this add-on's other
half. It opens Titan's settings window rebuilt in Elten's controls, so it is
Titan's own save with everything that hangs off it.

## It sounds like TCE, because it is TCE

Every screen here is one of Titan's, so it makes Titan's noises: the theme
the user chose, played through Titan's own mixer (`sounds.play` on the
bus), and switched off in one place - Settings -> "Use TCE sounds" - for
somebody who would rather hear Elten's own.

**Three of those sounds mean one thing each and are spent on nothing else.**
They are the only ones every TCE theme carries, which is what makes them the
vocabulary rather than decoration:

| | |
| --- | --- |
| `core/FOCUS.ogg` | the cursor moved from one row to the next |
| `ui/applist.ogg` | the keyboard ARRIVED on the list |
| `ui/statusbar.ogg` | the keyboard ARRIVED on the status bar |

So arriving on the main list of Titan's window plays `applist` and arriving
on the status bar under it plays `statusbar` - which is exactly what TCE's
own main window plays for those two movements (`play_applist_sound` from
`_focus_current_view_control`, `play_statusbar_sound` from the status bar).

**One sound per key, not one from each side.** Elten's controls are
self-voicing and play their own cue as the cursor moves, so a screen that
added Titan's on top made two noises for one arrow key - one from Elten's
theme and one from Titan's. `TitanSounds.cued` is the pair that belongs
together: it sets `silent` on the control (every one of Elten's own
`play_sound` calls for `:move`, `:border`, `:select` and the focus
marker is behind `@silent == false`, and its SPEECH is not, so the
announcement is untouched) and then binds the four cues itself. Quieting a
control without the second half is a silent list, which is how three screens
here ended up making no sound at all.

`:focus` is debounced by 0.3 s, because Elten focuses field 0 when a form is
BUILT and the screen then asks for the keyboard itself - one arrival,
announced twice.

**Titan's own events are here by name** (`TitanSounds::EVENTS`,
`TitanSounds.event(:error)`): the AI's set for the AI asking, answering and
failing; `macro/` around a macro run from here; `system/volume.ogg` when
the volume moves; the error, the tab bar, a window opening and closing, a
message sent. An action of Titan's that happens in Elten sounds the way it
sounds in Titan. Every name is checked against `sfx/default/` by
`tests/sounds_test.rb` - a mapping to a file that is not there is silence,
which is the one failure a user cannot tell from "this add-on makes no
sound".

**Titan says when this connects and when it goes.** The hello carries
`"client": true` - this side drives Titan and serves no actions of its own -
and Titan answers a client joining with "External client initialized" and a
client leaving with "External client closed", spoken in Titan's own voice
with `system/sysprocess_open.ogg` / `sysprocess_close.ogg` under it. An
ADD-ON joining says nothing: opening tEdit is something the user just did,
and a program somewhere else on the machine taking hold of Titan is not.

## How it reaches Titan

One named pipe - `\\.\pipe\TitanActions`, Titan's action bus - speaking JSON
lines, with the shared token from
`%APPDATA%\titosoft\Titan\actions\bus.token`. `titan_bus.rb` is that
protocol in Ruby; Titan's own `src/titan_core/titan_actions.py` is the
authority for the wire.

**One thread owns the pipe, and that is not tidiness.** Measured against a
stand-in Titan: with a reader thread parked in `gets` on the `File` and
another thread writing to it, every write waited for the parked read - a
fire-and-forget "say this" took **993 ms** to hand over, and afterwards
exactly as long as the previous answer took. Ruby serialises operations on
one IO object, which is the same trap Titan documents on its own side. With
the worker owning the pipe: **0.0 ms**, and `speaking?` - which Elten asks
every frame - is answered from a local estimate in **15 microseconds**,
corrected in the background by Titan's own answer and never on Elten's
thread.

Nothing waits on Elten's thread anywhere else either: every call goes
through `Tasks.run`, which runs it on a worker while the owner thread keeps
pumping the interface.

**The voice can be interrupted, and that took its own action.** Elten hands
every line to the output with `interrupt: true`, and `titan.speak` borrows a
rate for one line and can only give it back after the line has been spoken -
so it speaks SYNCHRONOUSLY and its answer does not come back until the
sentence is finished. Reading through it meant the next keystroke's "stop"
arrived after the line it was meant to interrupt, and Titan's own interface
was held for the length of every sentence. `titan.reader_speak` starts the
speech and returns; the rate is SET when Elten's rate changes and put back
when the output stops being used. Two checks in `tests/ui_test.rb` keep the
reader off the other path.

**Nothing polls.** Every in-process Titan action runs on Titan's GUI thread
(`inproc.call` -> `run_on_gui`), so a client refreshing itself every few
seconds would make Titan's own interface stutter for as long as it was open.
F5 reads a screen again.

## What it needs on the Titan side

All additive - nothing in Titan was changed or removed:

| Action | Why |
| --- | --- |
| `titan.stop_speech`, `titan.speaking` | An interruption in a reader means the VOICE, not the whole mixer; `speaking` answers from the reserved TTS channel, the only signal that means what it says. |
| `titan.views`, `titan.status_bar`, `titan.menu`, `titan.menu_run` | Titan's own tab bar, status bar and Program menu, read from `gui.py` and `program_menu.py` rather than copied - so a view a component registers, or a new menu entry, appears here with nothing changed. |
| `titan.inventory` | `list_addons` answers "what can be driven"; a window needs "what is installed". Most applications declare no actions, so a list built from the first would show four applications out of forty. Applications, games and IM modules come back under the names `titan.launch` accepts. |
| `titan.components`, `titan.widgets`, `titan.activate_widget` | The two categories Titan's non-visual interface has and its tab bar does not. |
| `titan.buffers`, `titan.buffer`, `titan.notifications`, `titan.clear_notifications` | The Buffer System and the notification centre - everything that arrived while its window was closed. |
| `titan.open_help`, `titan.window` | The Program menu's own Help, and minimising Titan to the tray or bringing it back. |
| `titan.reader_speak`, `titan.set_speech_rate`, `titan.get_speech_rate` | See below: this is what makes the voice interruptible. |
| `titan.ask_ai`, `titan.ai_available` | Asking Titan's AI from a program with no window of its own. Without `act` the model is given no tools at all: it answers, and answering is all it can do. |
| `shell.state` | Whether the shell is running, as JSON. `shell.status` says it in the user's own language ("Powloka Titana nie jest uruchomiona"), and a check written against the English answered the exact opposite on a Polish Titan. |
| `titan.addon_actions` | An add-on's actions with their summaries and parameters - what a screen needs to show them and ask for them. |
| `settings.screen` / `set_value` / `press` / `save` / `cancel` / `refresh` / `find` | Titan's settings window as data, over `ui_model.py`. |
| `titannet.whoami` / `rooms` / `online` / `people` / `room_messages` / `conversation` / `topics` / `topic` / `groups` / `mailbox` / `mail` / `news` | Titan-Net as records rather than sentences, over the same `src/network/titan_net.py` client and the same session. |
| `titannet.create_room` / `join_room` / `leave_room` / `delete_room` / `block` / `unblock` / `blocked` / `account_email` / `create_group` / `join_group_by_id` / `broadcast` | What Titan-Net's own window does to the PLACE rather than in it. Voice and push-to-talk are deliberately absent: they are a live stream captured and played in Titan's process, and an action that started one would take the microphone with nobody in front of it. |
| `titannet.feedback` / `feedback_item` / `feedback_new` / `feedback_upvote` / `repository` / `repository_item` / `repository_download` / `announcements` / `announcement` | The Feedback Hub, the application repository and the announcements. |
| `shell.windows` | The open windows as records: `list_windows` says the state in words, and those words are translated, so a client parsing them works in English and silently stops working in Polish. |

## Testing it without Elten

`tests/` runs every screen with no Elten and no Titan:

```
python tests/fake_titan.py          # a stand-in Titan on a test pipe
ruby tests/ui_test.rb               # 42 checks
ruby tests/live_probe.rb            # against the REAL Titan, read-only
```

**Stop the stand-in with `tests/stop_fake_titan.bat`, never by image name.**
Titan itself runs as `python.exe`, so `taskkill /IM python.exe` closes the
user's whole desktop along with the stand-in - which is exactly what
happened here before that script existed. It matches on the command line and
kills only `fake_titan.py`.

`tests/elten_stub.rb` is just enough of Elten's controls to run the screens,
and every control records what it was given - so a check can assert what the
user would have HEARD. The stand-in Titan answers the real action names with
the real shapes, including the ones that are JSON. What the checks cover:
the tab bar cycling Titan's own views, launching an application, the status
bar, a component view falling through to its actions, the settings
categories and their control kinds, Titan-Net's account, rooms with their
type and password, a room's messages attributed and readable in full, a
forum topic with its replies in a read-only field, the mailbox marking
unread, the shell being detected and its taskbar/desktop/tray listed,
opening a desktop icon, the areas menu offering the shell as a view, the
computer's readings, an add-on's actions with summaries, and the voice
registering, speaking and stopping.

## Known limits

- **Indexed speech is off** (`indexed_supported?` is false): Elten's
  bookmarks need index events from the engine and Titan does not give them
  out. Say-all still works; it is paced by the estimate.
- **No braille**, and volume is Titan's own - a slider here would move
  nothing, so it is not offered.
- A blocking read on a Windows named pipe cannot be interrupted from Ruby,
  so a Titan that accepts a call and never answers leaves the worker
  waiting. Elten stays responsive; the bridge notices at the next
  reconnection.
- `SpeechOutput` and the control set are Elten internals rather than the
  documented `.eltenapp` API, which does not cover speech outputs. Elten's
  own docs say the application system is experimental until 3.1.
- A native Ruby Titan-Net client - talking to the server directly rather
  than through Titan - would give live events and no GUI-thread hop, but it
  would have to hold the user's credentials. This design deliberately does
  not.

## The files

| File | What it is |
| --- | --- |
| `__app.rb` | The manifest, and the entry class that starts the bus and registers the voice |
| `titan_bus.rb` | Titan's action bus in Ruby - the worker that owns the pipe |
| `titan_speech_output.rb` | Titan's voices, as an Elten `SpeechOutput` |
| `titan_ui.rb` | The TCE-style screen: tab bar, list, Enter, Escape, F5 |
| `titan_console.rb` | Titan's main window - views, status bar, Program menu |
| `titan_settings.rb` | Titan's settings, category by category |
| `titan_net.rb` | The Titan-Net client |
| `titan_im.rb` | Titan IM: the services and their conversations |
| `titan_macros.rb` | The Macro Manager, and the Titan Script reference |
| `titan_cling.rb` | Cling: the Klango applications |
| `titan_ai.rb` | Titan AI: asking, reading the screen, what it remembers |
| `titan_shell.rb` | The Titan desktop, taskbar, notification area and Start menu |
| `titan_areas.rb` | The computer, the windows, the media, the voices, everything else |
| `titan_actions.rb` | One add-on's own actions, behind the context-menu key |
| `locale/pl.mo` | The Polish catalogue |
| `tests/` | The stand-in Elten, the stand-in Titan, and the checks |

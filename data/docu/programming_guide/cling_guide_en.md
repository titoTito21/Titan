# Writing a Cling application

Cling is Titan's Klango subsystem. A Cling application is a folder - or a single
`.pag` file - that Titan speaks, plays and keeps a score for. It is deliberately
the same folder a Klango application already is, so an application written for
Klango is a Cling application with nothing changed.

Applications live in `data/cling/`: bundled beside Titan, or - far more usually -
in the user's own overlay, which is where **Settings -> Cling -> Install a
Klango application** puts them.

## The shape of an application

```
mole/
  kni.txt                       what it is
  __cling__.TCE                 optional: what Titan should call it
  lang/default                  the locale everything else falls back to
  lang/en-us/default/*.txt      everything it says
  skin/default/levels/*.lev     levels, and the topologies they name
  skin/default/themes/*/*.ogg   its sounds
  main.lua                      optional: its own logic
```

### `kni.txt`

Klango's own manifest, read unchanged:

```
appid=18
appname=mole
summary=Mole No More - whack a mole audio game with 13 levels
version=1.0
minklango=20260803
platform=any
```

Cling also reads `category` (`games`, `edu`, `soundscape`, `network`, `tools`),
`engine` and `entry`. A key that is none of these is reported rather than
ignored, so a line nobody reads is never mistaken for one that works.

### `__cling__.TCE`

Only for an application written for Titan, and only for what `kni.txt` cannot
say - a name in two languages, and being switched off:

```ini
[cling app]
name = Cling Demo
name_pl = Demo Clinga
description = A small audio game.
description_pl = Mala gra dzwiekowa.
category = games
engine = script
entry = main.lua
status = 0
```

### What it says

One file per thing the application can say, under
`lang/<locale>/default/`, with `%d` and `%s` where a number or a name goes:

```
welcome.txt           Welcome to Mole No More.
instructions.txt      Whack as many moles as you can in %d seconds.
current_status.txt    PTS: %d
help.txt              <b>Arrows</b> - move on the gameboard.
klangomenu.txt        Mole No More
```

`klangomenu.txt` is what the application is CALLED, in that language, and Cling
prefers it over any name a manifest repeats in English. Markup (`<b>`, `<u>`) is
for the eye and is never spoken.

`lang/default` holds one line - the locale to fall back to. Cling resolves, in
order: the user's language, that fallback, `en-us`, then whatever is there.

## The five engines

Cling works out which engine drives an application from what its folder really
holds. Nothing is written and no file is edited.

| Engine | Chosen when | What it is |
| --- | --- | --- |
| `script` | `main.lua`, `main.py`, or Cling ships logic for it | the application is a program |
| `grid_hunt` | `skin/*/levels/*.lev` | a board, a cursor, a clock, things that come and go |
| `soundscape` | `spec.txt`, or `data/*.ogg` | a place, walked through |
| `instrument` | a folder of samples named after keys | the keyboard as an instrument |
| `typing` | KTouch lesson files under `trainings/` | a typing course |
| `reader` | anything else with words | everything the application says, as a list |

A manifest may name an engine outright; a name Cling does not have is refused
and reported rather than silently becoming something else.

### `grid_hunt` - the level file is the rules

```lua
Level = {
  text = "level5_info",     -- what the level says before it starts
  topology = "3x3",         -- which board, and therefore where every field IS
  fields = 9,
  hit_target = 30,          -- how many must be hit to finish
  nmole_time = 3,           -- how long an ordinary one stays up (0 = for ever)
  smole_time = 2.5,
  max_nmoles = 2,           -- how many may be up at once
  max_smoles = 1,
  smole_time_bonus = 2,     -- seconds a special one adds to the clock
  time = 60,                -- Cling's own: how long a level lasts
}
```

A topology gives every field a place in the sound field, and that is what makes
a board aimable without a screen:

```lua
Topology = {
  size = { x = 3, y = 3, z = 1 },
  coords = { [1] = { [1] = { [1] = { x=-0.800, y=0.250, z=0.000, f=0 } } } }
}
```

`x` is across, `y` is away, `z` is up, `f` is a pitch shift in cents. Cling
converts them once: a field knows its own `pan` (-1..1), `azimuth`, `elevation`,
`gain` and `pitch`. A level with no `.top` file gets an even grid.

### `soundscape` - `spec.txt` is the place

```
start : glowny
Location : glowny
    BkgVolume : 0.9
    links : burta, rufa
    fx : g1
        fxangle     : 300, 60
        fxdist      : 1, 1
        fxtimestart : 1, 120
        fxtimedelta : 120, 240
        fxvol       : 0.3, 0.8
```

A location's background recording is `data/<name>_bkg.ogg`, its name and
description are `lang/<locale>/default/<name>_name.txt` and `<name>_comment.txt`.

### `instrument` - the file name is the key

`sounds/<set>/z.wav` is played by `z`. A name ending `_l` (`q_l.wav`) loops, and
its key is a switch rather than a note. `.info.txt` beside them is read out as
the set's description.

## An application with its own logic

Ship `main.lua`. Cling carries its own Lua interpreter - inside the component,
in `cling/lua/` - so nothing has to be installed; if a native `lupa` is dropped
into `data/components/cling/lib/` it is used instead, and an application cannot
tell the difference.

Five functions, all optional:

```lua
function on_start()        -- opened
function on_key(key)       -- 'up' 'down' 'left' 'right' 'space' 'enter'
                           -- 'escape' 'a'..'z' '0'..'9' 'f1'..; true when used
function on_tick(now)      -- called often; `now` is seconds, monotonic
function on_stop()         -- being left
function status()          -- one line for the status bar
function help()            -- what the keys do
```

`main.py` works identically, with the same object under the name `cling`.

### The host

```lua
-- words
cling.say(text, position, pitch)     position -1 (left) .. 1 (right)
cling.say_at(text, field)            said from a place on the board
cling.text(name, ...)                one of the application's own texts
cling.show(text)                     said AND written into the window

-- sound
cling.play(name, position, gain)     the skin first, then Titan's sound theme
                                     always placed, whatever Titan's own
                                     stereo setting says - a board is aimed
                                     at by ear
cling.play_at(name, field, gain)     pan, height and distance at once
cling.loop(name, position, gain)     returns a handle
cling.stop_sound(handle)  cling.stop_sounds()

-- the board
cling.board(topology, columns, rows) build it; returns how many fields
cling.field(index)                   { index, column, row, pan, elevation,
                                       gain, pitch }
-- saving
cling.get(key, default)  cling.set(key, value)
cling.record_score(points)  cling.scores()  cling.best()

-- the player
cling.account()      their Titan-Net name
cling.signed_in()    whether Titan-Net is really connected
cling.sign_in()      sign in with what the user already saved; '' if they cannot
cling.publish_score(points, level)   the shared Titan-Net table; best effort
cling.leaderboard(limit)

-- the world
cling.fetch(url, timeout)   a GET over http or https, up to 2 MB
cling.ask(prompt, default)  a line of text from the player

-- the rest
cling.now()  cling.set_status(text)  cling.close()
cling.language()  cling.app_name()  cling.log(text)
```

There is no file system, no way to start a program and no `require` outside the
application's own folder: an application came from wherever the user found it.

## The account

A Klango application that wanted an account for its scores or its chat is given
the user's **Titan-Net** account, and never asks for one of its own. The saves
and the scores are kept per Titan-Net user name, so two people sharing a machine
keep their own. Nobody signed in plays under `local`, which works offline and
loses nothing.

## Packaging

An application ships as one file, the way a Klango application does:

```bash
python src/scripts/pack_cling.py "data/components/cling/apps/clingdemo" -o clingdemo.pag
python src/scripts/pack_cling.py --unpack clingdemo.pag -o /tmp/look
```

Put the `.pag` in `data/cling/` and it is discovered exactly like a folder. A
folder of the same name wins, so an application being worked on overrides the
package it shipped as. Titan's own `.TCD` packaging works too, because discovery
is Titan's own.

Klango's own `.pag` packages are read too - concealment and container both -
and every file is checked against the MD5 the package carries for it. Drop one
into `data/cling/` and it is an application.

## Actions

Cling declares actions like any other add-on, so the AI, a macro or another
add-on can drive it: `cling.list_applications`, `cling.run`, `cling.details`,
`cling.scores`, `cling.install`, `cling.account`, `cling.status`.

## Adding a genre

An engine is a genre, and the set is open:

```python
from cling import engines

class DartsEngine(engines.Engine):
    def start(self):
        self.running = True
        self.host.show(self.host.text('welcome'))

engines.register('darts', DartsEngine)
```

An application then names `engine = darts` in its manifest.

## Tests

`tests/test_cling.py` - run it directly. Nothing in it opens a window, plays a
sound, speaks or reaches the network, and the engines are given a clock the test
moves by hand, so a whole game is played through in a millisecond.

## Running Klango's own applications

**This is what an application gets by default.** Cling loads its OWN Lua, out
of its own `.pag`, on the interpreter Cling carries, and runs Klango's own
`main()`; the engines above are the fallback, for an application with no code
of its own and for a machine where Klango's platform library is not installed.
`cling.emulate <name>` reports how far one gets and which primitives it asked
for that Cling has not written.

The native surface underneath is 310 functions - the families (`_Sys_`,
`_Snd_`, `_Inp_`, `_Voice_`, `_Dir_`, `_Gfx_`, `_Res_`, `_Net_`) and the 120
the engine exposes with no prefix at all (`k_*`, `urlencode`) - and sound, keys
and speech go to the same places everything else in Cling uses, so an emulated
application is heard in the user's own voice, through their own sound theme,
positioned the way Cling positions everything.

**The sound is Klango's, placed the way Klango places it.** `pos3d` is where a
sound is (x across, y depth, z height) and `freq` is how high it is, in
hundredths of a semitone; `dmin` and `dmax` belong to the SAMPLE and are
OpenAL's clamped inverse-distance model, so a board really has depth rather
than everything being at full volume; `pos3dSlide` is a sound that travels
while it plays, which is what a clay pigeon crossing in front of you is; a
sequence carries its own delays, worked out from `sampleTime`; and speech can
be placed too, which is how a game says each of five dice where the die is.

Three details of that are worth knowing because they are easy to get wrong:

* **A place is written either way.** `pos3d = {-20, 2, 0}` and
  `pos3d = {x = -1, y = 0.5, z = 0}` are the same thing, and both work. The
  platform library itself uses the second, which is what puts a menu's items
  across the listener from -60 to +60 degrees.
* **A sample name may be relative and may have no extension.**
  `k_DirectoryRead` gives you a `name` with the extension taken off, and a
  name built from it - `sounds/piano/c` - is looked for in your own files
  with each of the sound extensions in turn.
* **Sound groups are a tree.** `k_SoundPlay` makes a group of its own inside
  whichever one is active, so an action on a group - `volMul`,
  `volMulSlide`, `pause`, `resume`, `stop` - reaches everything played under
  it. That is how the ambience ducks and the game pauses while a dialog is
  up, and you get it for free by using the platform's own dialogs.

Things worth knowing before you write an application that will be emulated:

* **It runs on a thread of its own.** `app:loop()` does not return - it IS the
  game - so the window feeds it keys and reads what it has said. The frames
  are paced at 60 a second, which is the rate `_Sys_GetFPS` reports.
* **The keyboard is Klango's, in all four of its shapes**: the DirectInput
  scan codes of the raw buffer and the held set, and the Windows virtual keys
  of the key messages. Left Alt opens the application's menu because it
  arrives as a real WM_SYSKEYUP; Left and Right move inside that menu, Down
  enters a submenu and Enter chooses, which is Klango's own interaction and
  not Titan's.
* **Klango's Settings and Help are Titan's.** The language, voice and audio
  theme an emulated application offers are Titan's - so the menu opens Titan's
  settings rather than a picker that would change nothing - and Help opens
  Titan's help. What belongs to the APPLICATION is left alone: its own help
  text, readme, changelog, version and exit.
* **Closing the window closes the application.** What is playing stops at
  once, and nothing the application asks for afterwards is answered - it is on
  its own thread and may be a frame behind.

* **An application may be in two places at once.** Its code is in its `.pag`;
  the folder beside it can hold whatever the package does not - lessons, extra
  skins, the user's own additions. Both are mounted as one tree, the package
  first.
* **There is a real text control.** `_Gfx_TxtEdit_*` is a buffer with a caret
  and a selection; a line ends with `\r`, as Klango's does, and `SetText2` is
  handed RTF and stores the words.
* **`k_NewHttp` really fetches** - `http` and `https`, capped and timed out,
  on a thread of its own so the frame loop keeps running. `GetStatusCode` is
  0 for a connection that never happened and -1 for one you cancelled.
* **A primitive Cling has not written answers nothing** rather than being nil,
  and `cling.emulate` names it. Your application carries on instead of
  stopping on `attempt to call a nil value`.

klango.net has been gone for years, so the calls that went there are answered
by Cling: the account is the Titan-Net one, the scoreboard is Cling's own
Titan-Net table, and everything Klango-only answers "finished, nothing" -
never nil, because the caller asks the answer whether it is `done()` on the
next line.

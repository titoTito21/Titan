# Programs in Other Languages (Polyglot)

A Titan application, game or component does not have to be Python. With the
**Polyglot** component installed (`data/components/polyglot/`, also available
from the Titan-Net repository), the file named by `openfile=` - or a
component's `init.<ext>` - may be written in another language, and Titan
opens it the way it opens a Python program: from the main window, the
Invisible UI, Klango mode, the Start menu, the AI and the Action API.

Nothing has to be installed. Polyglot carries its interpreters:

| Language | File | Where it runs |
|---|---|---|
| Lua 5.1 | `.lua` | Polyglot's own interpreter, inside the process |
| JavaScript | `.js`, `.mjs` | QuickJS-ng 0.17, carried in `interpreters/quickjs` |
| Ruby 4.0 | `.rb` | carried in `interpreters/ruby` (Windows) |
| C# 5 | `.cs` | compiled by `csc.exe`, the .NET Framework 4 compiler that is part of Windows |
| PowerShell | `.ps1` | part of Windows |

Other languages are used when their tools are on the computer: Node.js
(`.cjs`), TypeScript through Deno (`.ts`), Go, C, C++, Rust, Perl, PHP. Any
other language with a command line can be added in **Settings -> Polyglot**:
Add a language asks for its name, extensions, interpreter or compiler (with
Browse), run and compile commands, output file, environment variables and
whether Titan's SDK goes on its search paths. A built-in language can be
changed there too (for example given another interpreter), switched off, and
put back with Restore default; Check says whether the program is found and
what version it reports. Everything is kept in
`%APPDATA%/titosoft/Titan/polyglot/runtimes.json`, written when the settings
are saved, and the file can still be edited by hand.

Nothing in Titan is changed by Polyglot: it reaches Titan's application and
game managers from outside, so it works in a Titan built before it existed.

## An application in Lua

```
data/applications/my_app/
    __app.TCE
    main.lua
```

`__app.TCE` is an ordinary application manifest:

```
name_en="My application"
name_pl="Moja aplikacja"
openfile="main.lua"
shortname="my_app"
```

`main.lua`:

```lua
local name = titan.ask("What is your name?")
if name then
  titan.speak("Hello, " .. name)
  local i = titan.choose("Pick one", {"Tea", "Coffee"})   -- 1-based, or nil
  if i then titan.message("You chose option " .. i) end
end
```

Every Lua program gets the global `titan`. A function called `main`, if the
script defines one, is called after the script has run. An error in a Lua
program ends it and Titan says where; a call Titan refuses is a Lua error too,
so `pcall` catches it.

## A game

A game opens a window that takes the keyboard, and reads its keys as events:

```lua
titan.open_window("My game")
while true do
  local e = titan.next_event(0.05)      -- seconds; nil when nothing came
  if e then
    if e.type == "close" then break end
    if e.type == "key" and e.down then
      if e.key == "escape" then break end
      if e.key == "left" then titan.speak("left", true, -1) end
    end
  end
end
```

Events:

| type | fields |
|---|---|
| `key` | `key` (`left`, `a`, `5`, `f1`, `space`, `enter`...), `down`, `repeat`, `shift`, `ctrl`, `alt` |
| `char` | `char` - the character the layout typed (Polish letters included) |
| `focus` | `active` - the window gained or lost the keyboard; held keys are released on leaving |
| `menu` | `label` - a component's menu entry was chosen |
| `close` | the window was closed, or Titan is stopping the program |

A game's manifest is `__game.TCE` with `openfile="game.lua"`.

## The calls

The same calls exist in every language.

| Call | Arguments | Answer |
|---|---|---|
| `info` | | `{protocol, title, kind, runtime, app_dir, data_dir, language, calls}` |
| `speak` | `text, interrupt=true, position, rate, pitch, wait` | in the user's own Titan voice; `position` -1 left .. 1 right |
| `stop_speech` | | |
| `play` | `file, position=0, wait, to, duration` | a sound from the program's folder (also `sounds/`, `sfx/`) or the user's theme (`ui/notify.ogg`); `to` makes it travel |
| `stop_sounds` | | |
| `message` | `text, title` | |
| `ask` | `prompt, default, title, multiline, password` | the text, or nothing when cancelled |
| `confirm` | `text, title` | true or false |
| `choose` | `prompt, options, title, selected` | the index (from 0; from 1 in Lua), or nothing |
| `text` | `text, title` | a page to read, in a read-only field |
| `open_window` / `close_window` | `title` | the game window |
| `next_event` | `timeout` (seconds; omitted or negative waits) | an event, or nothing |
| `wait` | `seconds` | |
| `action` | `addon, action, args` | any Titan add-on's action: `{ok, text}` (in Lua: `ok, text`) |
| `data_dir` | | a folder for the program's own files |
| `log` | `text` | written to `%APPDATA%/titosoft/Titan/polyglot/logs/<program>.log` |
| `title` | `text` | renames the program (and its window) |
| `exit` | `code` | |
| `add_menu` | `label` (Lua: and a function) | components only: a Components-menu entry |

Dialogs are Titan's native windows, so a screen reader reads them. Speech and
sound go through Titan itself, with the user's voice, mixer and theme volume.

## JavaScript, Ruby, C#, PowerShell

JavaScript (QuickJS) - `titan` is a global:

```js
const name = titan.ask('What is your name?');
if (name !== null) titan.speak('Hello, ' + name);
```

Ruby:

```ruby
require 'titan'
name = Titan.ask('What is your name?')
Titan.speak("Hello, #{name}") unless name.nil?
```

C# - the program and every `.cs` file in its folder are compiled together
with the SDK's `Titan` class, the first time it is opened and again only when
a file changes. C# 5 (what Windows' own compiler accepts):

```csharp
static class Program
{
    static void Main()
    {
        string name = Titan.Ask("What is your name?");
        if (name != null) Titan.Speak("Hello, " + name);
    }
}
```

PowerShell - save the script as UTF-8 **with a BOM**, or Windows PowerShell
5.1 reads it in the ANSI code page:

```powershell
Import-Module Titan
$name = Invoke-Titan ask 'What is your name?'
if ($null -ne $name) { Invoke-Titan speak "Hello, $name" | Out-Null }
```

`print`, `puts`, `console.log` and `Write-Host` go to the program's log, never
to Titan.

## Any other language: the protocol

A program in any language talks to Titan on its standard input and output,
one JSON object per line, UTF-8:

```
program -> Titan   {"id": 1, "call": "speak", "args": {"text": "Hello"}}
Titan -> program   {"id": 1, "ok": true, "value": true}
                   {"id": 1, "ok": false, "error": "a sentence"}
```

`args` may be an object (named) or an array (positional). A call without an
`id` is not answered. A line that is not a JSON object is the program's own
output and goes to the log. The protocol is synchronous: write a call, read its
answer - a client in a new language is a dozen lines, with no threads.

Settings -> Polyglot writes entries like these into `runtimes.json`:

```json
{"runtimes": [
  {"id": "nim", "name": "Nim", "extensions": [".nim"],
   "compile": ["{exe}", "c", "-o:{out}", "{file}"], "find": ["nim"]},
  {"id": "javascript", "find": ["C:/Program Files/nodejs/node.exe"],
   "command": ["{exe}", "{file}"]}
]}
```

Placeholders: `{file}` the source, `{dir}` its folder, `{name}` the file name
without extension, `{out}` what the compile step wrote (cached until a source
in the folder changes), `{exe}` the first of `find` that exists, `{sdk}`
Polyglot's SDK folder, `{python}` Titan's own Python. An entry with the id of a
built-in language changes only what it names; `"disabled": true` switches a
language off. A language the user added wins an extension it shares with a
built-in one.

## A component

A component folder with `init.lua` (or `init.rb`, `init.js`...) instead of
`init.py` is started by Polyglot and runs as long as Titan runs.

```
data/components/my_clock/
    __component__.TCE
    init.lua
```

```lua
titan.add_menu("My clock: say the time", function()
  titan.speak(os.date("%H:%M"))
end)

function initialize() titan.log("ready") end   -- optional
function shutdown() end                        -- optional
```

A component in another language runs as a child process and reads its menu
entries as events:

```ruby
require 'titan'
loop do
  e = Titan.next_event(nil)
  break if e.nil? || e['type'] == 'close'
  Titan.speak('It is ' + Time.now.strftime('%H:%M')) if e['type'] == 'menu'
end
```

Its entries are declared in the manifest, which is the only way to be sure
they exist before Titan builds its menu bar:

```
[component]
name = My clock
status = 0
menu = My clock: say the time
menu_pl = Mój zegar: powiedz godzinę
```

## Every other kind of add-on

An application, a game and a component are things Titan STARTS. Every other
kind of add-on is something Titan CALLS - a statusbar applet is asked for its
text, a widget is told to move, a TTS engine is handed a sentence - and every
one of them may be written in another language too:

| Kind | Folder | Manifest | The functions Titan calls |
|---|---|---|---|
| Titan IM module | `data/titanIM_modules/` | `__im.TCE` | `open(parent)`, `get_status_text()` |
| Widget | `data/applets/` | `applet.json` | `get_widget_info()`, `create()`, `navigate(direction)`, `get_current_element()`, `activate_current_element()` |
| Statusbar applet | `data/statusbar_applets/` | `applet.json` | `get_statusbar_item_text()`, `get_statusbar_item_info()`, `on_statusbar_item_activate(parent)` |
| Launcher | `data/launchers/` | `__launcher__.TCE` | `start(api)` |
| Settings interface | `data/settings interfaces/` | `__settings_ui__.TCE` | `open_settings(api)` |
| Shell add-on | `data/shell addons/` | `__shell_addon__.TCE` | the hooks of a Python shell add-on: `start_menu_items(api, menu)`, `explorer_columns(...)`... |
| Gamepad mode | `data/gamepad/modes/` | `__mode__.TCE` with `main = mode.py` | `on_activate(manager)`, `handle_button(id)`, `handle_axis(id, value)`, `handle_hat(x, y)`, `handle_bumper(is_left)`, `get_display_name()` |
| TTS engine | `data/titantts engines/` | `__engine__.TCE` | `generate(text, pitch)` answering the path of a WAV file, `get_voices()`, `set_voice(id)`, `set_rate(n)`, `is_available()` |

A **macro** is a program that runs once, like an application: in
`__macro__.TCE`, `openfile = main.lua` (or `.rb`, `.js`...), and the Macro
Manager runs it through Polyglot from its list, its shortcut and the
`macros.run_macro` action. Lua runs `main()` if the file defines one.

The functions are the ones a Python add-on of that kind defines, under the
same names, so the guide for each kind applies unchanged. A function the
program does not define is simply not asked for.

The program is `main.<extension>` (or the manifest says `polyglot = file`).
Titan's loader for each kind looks for a Python file, so Polyglot writes one
beside the program - a few lines marked `# Polyglot entry` that hand the folder
to Polyglot. It is written when Polyglot starts, when the examples are
installed, and by Components -> Polyglot -> Prepare add-ons in
other languages, which is what to run before packing such an add-on. An add-on
with a Python file of its own is a Python add-on and is never touched.

### In Lua

Define the functions. A function you return (a menu entry's `action`) is kept
by Titan and called later:

```lua
function get_statusbar_item_text()
  return "Session: " .. math.floor((os.time() - started) / 60) .. " min"
end

function start_menu_items(api, menu)
  return {{id = "hello", label = "Hello",
           action = function() titan.speak("Hello") end}}
end
```

### In any other language: serve

The program ends with `serve`, which tells Titan which functions exist and
answers Titan's calls until Titan is done with it:

```ruby
require 'titan'
Titan.serve('get_statusbar_item_text' => -> { Time.now.strftime('%H:%M') })
```

```javascript
titan.serve({ get_statusbar_item_text: () => new Date().toTimeString() });
```

```powershell
Import-Module Titan
Start-TitanServe @{ get_statusbar_item_text = { (Get-Date).ToString('HH:mm') } }
```

```csharp
var h = new Dictionary<string, Func<object[], object>>();
h["get_statusbar_item_text"] = a => DateTime.Now.ToString("HH:mm");
Titan.Serve(h);
```

On the wire a call from Titan is an event from `next_event`,
`{"type": "call", "id": 7, "name": "...", "args": [...]}`, answered with
`reply(7, value)` (or `reply(7, null, "what went wrong")`); `provide([names])`
says which functions exist. A function Titan should keep is answered as
`{"__function": "name"}` (`Titan.fn("name")`, `titan.fn`, `New-TitanFunction`,
`Titan.Fn`).

### Titan's objects: host

What Titan hands an add-on - a launcher's API, a settings interface's API, a
shell add-on's API, the parent window - arrives as a handle,
`{"__handle": 3, "__type": "LauncherAPI"}`, and its methods are called with
`host`:

```lua
local apps = titan.host(api, "get_applications")
titan.host(api, "open_application", {apps[1]})
```

The objects every add-on of a kind has are also there by name: a Titan IM
module's `sounds`, `config`, `ui` and `buffers` (`titan.host("sounds",
"new_message")`), and a gamepad mode's `gamepad` helpers
(`titan.host("gamepad", "tap", {"ctrl+c"})`).

### Launchers and settings interfaces

A launcher's `start(api)` runs for as long as the launcher does; when it
returns, Titan closes. A settings interface's `open_settings(api)` may keep
asking questions for as long as it likes - Titan does not wait for it.

### TTS engines

`generate(text, pitch)` writes the speech to a WAV file and answers its path
(relative to the engine's folder, or absolute); an answer of
`{"base64": "...", "format": "wav"}` works too. `Titan.data_dir` is a good place
to write it.

## Examples

Components -> Polyglot -> Install the examples copies into the
user's own folders (`examples/` in the component): a Lua application, game and
component; applications in JavaScript, Ruby, C# and PowerShell; and one add-on
of every other kind - a Titan IM module, a widget, a statusbar applet, a
macro, a launcher, a settings interface, a shell add-on and a gamepad mode in Lua, a
statusbar applet in JavaScript, a widget in Ruby and a TTS engine in Ruby.

## Action API

`polyglot.list_languages`, `polyglot.run_file` (`path`, `kind`),
`polyglot.install_examples`, `polyglot.prepare_addons` (write the Python
entries), `polyglot.addons` (every add-on in another language and whether it
runs), `polyglot.components`.

# Programy w innych językach (Polyglot)

Aplikacja, gra albo komponent Titana nie muszą być napisane w Pythonie. Gdy
zainstalowany jest komponent **Polyglot** (`data/components/polyglot/`,
dostępny też w repozytorium Titan-Netu), plik wskazany w `openfile=` - albo
plik `init.<rozszerzenie>` komponentu - może być w innym języku, a Titan
otwiera go tak samo jak program w Pythonie: z okna głównego, z niewidzialnego
interfejsu, z trybu Klango, z menu Start, przez SI i przez Action API.

Niczego nie trzeba instalować. Polyglot ma własne interpretery:

| Język | Plik | Gdzie działa |
|---|---|---|
| Lua 5.1 | `.lua` | własny interpreter Polyglota, w tym samym procesie |
| JavaScript | `.js`, `.mjs` | QuickJS-ng 0.17, w `interpreters/quickjs` |
| Ruby 4.0 | `.rb` | w `interpreters/ruby` (Windows) |
| C# 5 | `.cs` | kompilowany przez `csc.exe`, kompilator .NET Framework 4 będący częścią Windowsa |
| PowerShell | `.ps1` | część Windowsa |

Inne języki są używane, gdy ich narzędzia są na komputerze: Node.js (`.cjs`),
TypeScript przez Deno (`.ts`), Go, C, C++, Rust, Perl, PHP. Każdy inny język
z wierszem poleceń można dodać w **Ustawienia -> Polyglot**: Dodaj język pyta
o nazwę, rozszerzenia, interpreter lub kompilator (z przyciskiem Wskaż
program), polecenia uruchomienia i kompilacji, plik wynikowy, zmienne
środowiskowe i o to, czy dodać SDK Titana do ścieżek wyszukiwania. Tam też
można zmienić język wbudowany (na przykład wskazać mu inny interpreter),
wyłączyć go i przywrócić przyciskiem Przywróć domyślne; Sprawdź mówi, czy
program został znaleziony i jaką wersję podaje. Wszystko jest trzymane
w `%APPDATA%/titosoft/Titan/polyglot/runtimes.json`, zapisywane razem
z ustawieniami, a plik nadal można edytować ręcznie.

Polyglot niczego w Titanie nie zmienia: dociera do menedżera aplikacji i gier
z zewnątrz, więc działa też w Titanie zbudowanym, zanim powstał.

## Aplikacja w Lua

```
data/applications/moja_aplikacja/
    __app.TCE
    main.lua
```

`__app.TCE` to zwykły manifest aplikacji:

```
name_en="My application"
name_pl="Moja aplikacja"
openfile="main.lua"
shortname="moja_aplikacja"
```

`main.lua`:

```lua
local imie = titan.ask("Jak masz na imię?")
if imie then
  titan.speak("Cześć, " .. imie)
  local i = titan.choose("Wybierz", {"Herbata", "Kawa"})   -- od 1 albo nil
  if i then titan.message("Wybrano pozycję " .. i) end
end
```

Każdy program w Lua dostaje globalną tabelę `titan`. Jeśli skrypt definiuje
funkcję `main`, zostanie ona wywołana po wykonaniu skryptu. Błąd w programie
kończy go, a Titan mówi, gdzie wystąpił; odmowa Titana też jest błędem Lua,
więc łapie ją `pcall`.

## Gra

Gra otwiera okno, które przejmuje klawiaturę, i czyta klawisze jako zdarzenia:

```lua
titan.open_window("Moja gra")
while true do
  local e = titan.next_event(0.05)      -- sekundy; nil, gdy nic nie przyszło
  if e then
    if e.type == "close" then break end
    if e.type == "key" and e.down then
      if e.key == "escape" then break end
      if e.key == "left" then titan.speak("w lewo", true, -1) end
    end
  end
end
```

Zdarzenia:

| type | pola |
|---|---|
| `key` | `key` (`left`, `a`, `5`, `f1`, `space`, `enter`...), `down`, `repeat`, `shift`, `ctrl`, `alt` |
| `char` | `char` - znak wpisany według układu klawiatury (także polskie litery) |
| `focus` | `active` - okno dostało albo straciło klawiaturę; przy opuszczeniu wciśnięte klawisze są zwalniane |
| `menu` | `label` - wybrano pozycję menu komponentu |
| `close` | okno zamknięto albo Titan kończy program |

Manifest gry to `__game.TCE` z `openfile="gra.lua"`.

## Wywołania

Te same wywołania istnieją w każdym języku.

| Wywołanie | Argumenty | Odpowiedź |
|---|---|---|
| `info` | | `{protocol, title, kind, runtime, app_dir, data_dir, language, calls}` |
| `speak` | `text, interrupt=true, position, rate, pitch, wait` | głosem Titana wybranym przez użytkownika; `position` od -1 (lewo) do 1 (prawo) |
| `stop_speech` | | |
| `play` | `file, position=0, wait, to, duration` | dźwięk z folderu programu (także `sounds/`, `sfx/`) albo z motywu użytkownika (`ui/notify.ogg`); `to` sprawia, że dźwięk się przesuwa |
| `stop_sounds` | | |
| `message` | `text, title` | |
| `ask` | `prompt, default, title, multiline, password` | wpisany tekst albo nic po anulowaniu |
| `confirm` | `text, title` | prawda albo fałsz |
| `choose` | `prompt, options, title, selected` | indeks (od 0; w Lua od 1) albo nic |
| `text` | `text, title` | strona do czytania w polu tylko do odczytu |
| `open_window` / `close_window` | `title` | okno gry |
| `next_event` | `timeout` (sekundy; brak albo ujemny - czeka) | zdarzenie albo nic |
| `wait` | `seconds` | |
| `action` | `addon, action, args` | akcja dowolnego dodatku Titana: `{ok, text}` (w Lua: `ok, text`) |
| `data_dir` | | folder na własne pliki programu |
| `log` | `text` | zapis do `%APPDATA%/titosoft/Titan/polyglot/logs/<program>.log` |
| `title` | `text` | zmienia nazwę programu (i jego okna) |
| `exit` | `code` | |
| `add_menu` | `label` (w Lua także funkcja) | tylko komponenty: pozycja w menu Komponenty |

Okna dialogowe to natywne okna Titana, więc czytnik ekranu je czyta. Mowa
i dźwięk idą przez Titana - głosem, mikserem i głośnością motywu użytkownika.

## JavaScript, Ruby, C#, PowerShell

JavaScript (QuickJS) - `titan` jest globalny:

```js
const imie = titan.ask('Jak masz na imię?');
if (imie !== null) titan.speak('Cześć, ' + imie);
```

Ruby:

```ruby
require 'titan'
imie = Titan.ask('Jak masz na imię?')
Titan.speak("Cześć, #{imie}") unless imie.nil?
```

C# - program i wszystkie pliki `.cs` z jego folderu są kompilowane razem
z klasą `Titan` z SDK: przy pierwszym otwarciu i ponownie tylko po zmianie
pliku. C# 5 (to, co przyjmuje kompilator Windowsa):

```csharp
static class Program
{
    static void Main()
    {
        string imie = Titan.Ask("Jak masz na imię?");
        if (imie != null) Titan.Speak("Cześć, " + imie);
    }
}
```

PowerShell - skrypt zapisz w UTF-8 **ze znacznikiem BOM**, bo inaczej
Windows PowerShell 5.1 odczyta go w stronie kodowej ANSI:

```powershell
Import-Module Titan
$imie = Invoke-Titan ask 'Jak masz na imię?'
if ($null -ne $imie) { Invoke-Titan speak "Cześć, $imie" | Out-Null }
```

`print`, `puts`, `console.log` i `Write-Host` trafiają do dziennika programu,
nigdy do Titana.

## Dowolny inny język: protokół

Program w dowolnym języku rozmawia z Titanem przez standardowe wejście
i wyjście, jeden obiekt JSON w wierszu, UTF-8:

```
program -> Titan   {"id": 1, "call": "speak", "args": {"text": "Cześć"}}
Titan -> program   {"id": 1, "ok": true, "value": true}
                   {"id": 1, "ok": false, "error": "zdanie"}
```

`args` może być obiektem (nazwane) albo tablicą (pozycyjne). Wywołanie bez
`id` nie dostaje odpowiedzi. Wiersz, który nie jest obiektem JSON, to własne
wyjście programu i trafia do dziennika. Protokół jest synchroniczny: wpisz
wywołanie, przeczytaj odpowiedź - klient w nowym języku to kilkanaście linii
bez wątków.

Ustawienia -> Polyglot zapisują do `runtimes.json` wpisy takie jak te:

```json
{"runtimes": [
  {"id": "nim", "name": "Nim", "extensions": [".nim"],
   "compile": ["{exe}", "c", "-o:{out}", "{file}"], "find": ["nim"]},
  {"id": "javascript", "find": ["C:/Program Files/nodejs/node.exe"],
   "command": ["{exe}", "{file}"]}
]}
```

Symbole: `{file}` plik źródłowy, `{dir}` jego folder, `{name}` nazwa pliku bez
rozszerzenia, `{out}` wynik kompilacji (zapamiętywany, dopóki żaden plik
w folderze się nie zmieni), `{exe}` pierwszy istniejący z `find`, `{sdk}`
folder SDK Polyglota, `{python}` własny Python Titana. Wpis z identyfikatorem
języka wbudowanego zmienia tylko to, co w nim podano; `"disabled": true`
wyłącza język. Język dodany przez użytkownika wygrywa rozszerzenie, które
dzieli z językiem wbudowanym.

## Komponent

Folder komponentu z `init.lua` (albo `init.rb`, `init.js`...) zamiast
`init.py` uruchamia Polyglot; komponent działa tak długo jak Titan.

```
data/components/moj_zegar/
    __component__.TCE
    init.lua
```

```lua
titan.add_menu("Mój zegar: powiedz godzinę", function()
  titan.speak(os.date("%H:%M"))
end)

function initialize() titan.log("gotowy") end   -- nieobowiązkowe
function shutdown() end                         -- nieobowiązkowe
```

Komponent w innym języku działa jako proces potomny i dostaje swoje pozycje
menu jako zdarzenia:

```ruby
require 'titan'
loop do
  e = Titan.next_event(nil)
  break if e.nil? || e['type'] == 'close'
  Titan.speak('Jest ' + Time.now.strftime('%H:%M')) if e['type'] == 'menu'
end
```

Jego pozycje menu deklaruje się w manifeście - tylko tak jest pewne, że
istnieją, zanim Titan zbuduje pasek menu:

```
[component]
name = Mój zegar
status = 0
menu = My clock: say the time
menu_pl = Mój zegar: powiedz godzinę
```

## Każdy inny rodzaj dodatku

Aplikację, grę i komponent Titan URUCHAMIA. Każdy inny rodzaj dodatku Titan
WYWOŁUJE - aplet paska stanu jest pytany o swój tekst, widżet dostaje polecenie
ruchu, silnik mowy dostaje zdanie - i każdy z nich też może być napisany w
innym języku:

| Rodzaj | Folder | Manifest | Funkcje, które Titan wywołuje |
|---|---|---|---|
| Moduł Titan IM | `data/titanIM_modules/` | `__im.TCE` | `open(parent)`, `get_status_text()` |
| Widżet | `data/applets/` | `applet.json` | `get_widget_info()`, `create()`, `navigate(direction)`, `get_current_element()`, `activate_current_element()` |
| Aplet paska stanu | `data/statusbar_applets/` | `applet.json` | `get_statusbar_item_text()`, `get_statusbar_item_info()`, `on_statusbar_item_activate(parent)` |
| Launcher | `data/launchers/` | `__launcher__.TCE` | `start(api)` |
| Interfejs ustawień | `data/settings interfaces/` | `__settings_ui__.TCE` | `open_settings(api)` |
| Dodatek powłoki | `data/shell addons/` | `__shell_addon__.TCE` | haki dodatku powłoki w Pythonie: `start_menu_items(api, menu)`, `explorer_columns(...)`... |
| Tryb pada | `data/gamepad/modes/` | `__mode__.TCE` z `main = mode.py` | `on_activate(manager)`, `handle_button(id)`, `handle_axis(id, value)`, `handle_hat(x, y)`, `handle_bumper(is_left)`, `get_display_name()` |
| Silnik mowy | `data/titantts engines/` | `__engine__.TCE` | `generate(text, pitch)` zwracające ścieżkę pliku WAV, `get_voices()`, `set_voice(id)`, `set_rate(n)`, `is_available()` |

**Makro** to program uruchamiany raz, jak aplikacja: w `__macro__.TCE`
`openfile = main.lua` (albo `.rb`, `.js`...), a Menedżer makr uruchamia je
przez Polyglota z listy, skrótem i akcją `macros.run_macro`. Lua wywołuje
`main()`, jeśli plik ją definiuje.

To te same funkcje, pod tymi samymi nazwami, co w dodatku danego rodzaju w
Pythonie, więc przewodnik każdego rodzaju obowiązuje bez zmian. O funkcję,
której program nie definiuje, Titan po prostu nie pyta.

Programem jest `main.<rozszerzenie>` (albo manifest mówi `polyglot = plik`).
Loader każdego rodzaju szuka pliku w Pythonie, więc Polyglot pisze go obok
programu - kilka wierszy oznaczonych `# Polyglot entry`, które przekazują
folder Polyglotowi. Plik powstaje przy starcie Polyglota, przy instalowaniu
przykładów i przez Komponenty -> Polyglot -> Przygotuj dodatki w
innych językach - to trzeba uruchomić przed spakowaniem takiego dodatku.
Dodatek z własnym plikiem w Pythonie jest dodatkiem w Pythonie i nie jest
ruszany.

### W Lua

Zdefiniuj funkcje. Funkcję, którą zwrócisz (`action` pozycji menu), Titan
zachowuje i wywołuje później:

```lua
function get_statusbar_item_text()
  return "Sesja: " .. math.floor((os.time() - started) / 60) .. " min"
end

function start_menu_items(api, menu)
  return {{id = "hello", label = "Witaj",
           action = function() titan.speak("Witaj") end}}
end
```

### W każdym innym języku: serve

Program kończy się wywołaniem `serve`, które mówi Titanowi, jakie funkcje
istnieją, i odpowiada na wywołania Titana, dopóki Titan go potrzebuje:

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

W protokole wywołanie od Titana to zdarzenie z `next_event`,
`{"type": "call", "id": 7, "name": "...", "args": [...]}`, na które program
odpowiada `reply(7, wartość)` (albo `reply(7, null, "co poszło źle")`);
`provide([nazwy])` mówi, jakie funkcje istnieją. Funkcję, którą Titan ma
zachować, zwraca się jako `{"__function": "nazwa"}` (`Titan.fn("nazwa")`,
`titan.fn`, `New-TitanFunction`, `Titan.Fn`).

### Obiekty Titana: host

To, co Titan przekazuje dodatkowi - API launchera, API interfejsu ustawień,
API dodatku powłoki, okno nadrzędne - przychodzi jako uchwyt,
`{"__handle": 3, "__type": "LauncherAPI"}`, a jego metody wywołuje się przez
`host`:

```lua
local apps = titan.host(api, "get_applications")
titan.host(api, "open_application", {apps[1]})
```

Obiekty, które ma każdy dodatek danego rodzaju, są też dostępne po nazwie:
`sounds`, `config`, `ui` i `buffers` modułu Titan IM (`titan.host("sounds",
"new_message")`) oraz pomocniki `gamepad` trybu pada
(`titan.host("gamepad", "tap", {"ctrl+c"})`).

### Launchery i interfejsy ustawień

`start(api)` launchera trwa tak długo jak launcher; gdy się skończy, Titan się
zamyka. `open_settings(api)` interfejsu ustawień może zadawać pytania tak
długo, jak chce - Titan na niego nie czeka.

### Silniki mowy

`generate(text, pitch)` zapisuje mowę do pliku WAV i zwraca jego ścieżkę
(względną wobec folderu silnika albo bezwzględną); odpowiedź
`{"base64": "...", "format": "wav"}` też działa. Dobrym miejscem na plik jest
`Titan.data_dir`.

## Przykłady

Komponenty -> Polyglot -> Zainstaluj przykłady kopiuje do folderów
użytkownika (folder `examples/` komponentu): aplikację, grę i komponent w Lua;
aplikacje w JavaScripcie, Ruby, C# i PowerShellu; oraz po jednym dodatku
każdego innego rodzaju - moduł Titan IM, widżet, aplet paska stanu, makro,
launcher,
interfejs ustawień, dodatek powłoki i tryb pada w Lua, aplet paska stanu w
JavaScripcie, widżet w Ruby i silnik mowy w Ruby.

## Action API

`polyglot.list_languages`, `polyglot.run_file` (`path`, `kind`),
`polyglot.install_examples`, `polyglot.prepare_addons` (pisze wejścia w
Pythonie), `polyglot.addons` (każdy dodatek w innym języku i czy działa),
`polyglot.components`.

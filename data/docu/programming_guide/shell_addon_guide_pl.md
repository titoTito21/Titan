# Przewodnik tworzenia dodatków powłoki TCE

## Wprowadzenie

**Powłoka Titana** to pulpit, pasek zadań, zasobnik systemowy, menu Start i przeglądarka plików, które Titan stawia, gdy włączone są *Ustawienia -> Środowisko -> "Modyfikuj interfejs systemowy"* oraz *Ustawienia -> Powłoka Titana -> "Zastąp pulpit, pasek zadań i menu Start"*. Wszystkie pięć to kod samego Titana — a **dodatek powłoki** jest sposobem, żeby ktoś inny mógł do nich wejść, nie zmieniając Titana.

Są dwa rodzaje i to od tej różnicy zależy wszystko:

| Rodzaj | Co robi | Ile działa naraz |
|--------|---------|------------------|
| **Współtwórca** (contributor) | Dodaje do tego, co już jest: pozycje w menu Start, menu/przycisk/kolumnę w przeglądarce plików, pozycje w menu kontekstowym pulpitu i paska zadań, kontrolkę w zasobniku | Dowolnie wiele, wszystkie naraz |
| **Dostawca** (provider) | **Zastępuje** jedną część powłoki w całości — `provides = start_menu` albo `provides = explorer` | Jeden, wybrany przez użytkownika |

Dostawca zastępuje **okno**, a nie powłokę: gdy wybierzesz cudze menu Start, pulpit, pasek zadań, zasobnik i przeglądarka plików działają dokładnie tak jak wcześniej.

Dodatki mieszkają w `data/shell addons/`. To dziesiąty rodzaj dodatku i celowo powtarza konwencje pozostałych dziewięciu — ten sam styl manifestu, to samo `status = 0` znaczące „włączony", ten sam `init.py`, to samo pakowanie.

## Architektura

```
data/shell addons/moj_dodatek/
├── __shell_addon__.TCE   # Manifest (WYMAGANY, .TCE wielkimi literami)
├── init.py               # Kod (WYMAGANY; init.pyc też jest akceptowany)
└── lib/                  # Dołączone biblioteki (opcjonalnie)
```

Wykrywanie idzie przez `platform_utils.discover_data_entries()`, więc ten sam dodatek może być **katalogiem** albo jednym spakowanym plikiem **`.TCD`** — patrz „Pakowanie" niżej. Oba są znajdowane tak samo, w `data/` programu i w nakładce użytkownika.

Ładowanie to `src/shell/addons.py`:

1. Każdy `__shell_addon__.TCE` jest czytany przy starcie (`ShellAddonManager.scan`).
2. Dodatek ze `status = 0` jest **ładowany na żądanie** — przy pierwszym pytaniu którejś powierzchni albo gdy startuje powłoka.
3. `setup(api)` uruchamia się raz, zaraz po zaimportowaniu modułu.
4. Potem każda powierzchnia woła te funkcje, które istnieją.

**Nic, co robi dodatek, nie może położyć powłoki.** Każde wyjście do dodatku jest osłonięte: funkcja, której nie ma, która rzuci wyjątek albo odpowie czymś, co nie jest listą pozycji, nie wnosi nic, a powierzchnia działa dalej. To ważniejsze niż gdziekolwiek indziej — z zarejestrowanym appbarem i zainstalowanym shell hookiem proces Titana jest tym, przez co przechodzą komunikaty wszystkich innych programów, więc wyjątek, który ucieknie do obsługi rysowania, to nie zepsuty dodatek, tylko maszyna, która przestała odpowiadać.

## Manifest `__shell_addon__.TCE`

Format INI, jedna sekcja:

```ini
[shell addon]
name = My shell add-on
name_pl = Mój dodatek powłoki
description = What it adds, in one sentence.
description_pl = Co dodaje, jednym zdaniem.
author = Twoje imię
version = 1.0
status = 1
surfaces = start_menu, explorer
provides =
libs = lib
```

| Pole | Wymagane | Opis |
|------|----------|------|
| name | nie | Nazwa wyświetlana (domyślnie nazwa katalogu) |
| name_pl, name_en, ... | nie | Nazwa w danym języku; `name_<kod>` wygrywa z `name` |
| description | nie | Jedno zdanie — pokazywane pod przyciskiem wyboru dostawcy |
| description_pl, ... | nie | To samo, przetłumaczone |
| author | nie | Autor |
| version | nie | Wersja (domyślnie `1.0`) |
| status | tak | **`0` = włączony, `1` = wyłączony** (konwencja komponentów) |
| surfaces | nie | Po przecinku: `shell`, `start_menu`, `explorer`, `taskbar`, `desktop` |
| provides | nie | `start_menu` albo `explorer` — czyni dodatek **dostawcą** |
| libs | nie | Podkatalogi dopisywane do `sys.path` (domyślnie `lib`) |

Uwagi:

- **`surfaces` to pomoc, nie bramka.** Dodatek, który nie wymieni żadnej, jest pytany o wszystko — bo pomyłka tutaj ma znaczyć trochę wolniejsze menu, a nie dodatek, który po cichu nic nie robi. Mimo to je wypisz: to dzięki temu menu Start jest szybkie przy dwudziestu zainstalowanych dodatkach.
- **Rozprowadzaj ze `status = 1`.** Dodatek powłoki zaczyna działać w chwili włączenia, więc włącza go użytkownik — Ustawienia -> Powłoka Titana -> Dodatki powłoki. (Odwrotnie niż interfejs ustawień, który ma `status = 0`, bo samo zainstalowanie czyni go tylko jedną z możliwości.)
- Nazwa i opis to **Twoje** słowa, a nie tłumaczone teksty Titana — dlatego istnieją `name_pl` / `description_pl`.

## `init.py`: wszystkie funkcje

Każda jest opcjonalna. Titan pyta o to, co jest, i pomija to, czego nie ma — dodatek, który chce jednej pozycji w menu pulpitu, pisze `desktop_menu_items` i nic więcej.

Każda dostaje najpierw `api` (obiekt `ShellAddonAPI`), potem to, o czym jest dana powierzchnia.

| Powierzchnia | Funkcja | Sygnatura | Odpowiada |
|--------------|---------|-----------|-----------|
| shell | `setup` | `(api)` | — (raz, przy ładowaniu) |
| shell | `teardown` | `(api)` | — (przy wyłączeniu) |
| shell | `on_shell_start` | `(api, shell)` | — (**wątek roboczy**) |
| shell | `on_shell_stop` | `(api, shell)` | — (**wątek roboczy**) |
| start_menu | `start_menu_items` | `(api, menu)` | listę pozycji |
| explorer | `explorer_menu_items` | `(api, browser)` | listę pozycji (menu Narzędzia) |
| explorer | `explorer_toolbar_items` | `(api, browser)` | listę pozycji (pasek) |
| explorer | `explorer_context_items` | `(api, browser, where, selection)` | listę pozycji |
| explorer | `explorer_columns` | `(api, browser, location)` | listę kolumn |
| taskbar | `taskbar_bands` | `(api, taskbar)` | listę kontrolek |
| taskbar | `taskbar_menu_items` | `(api, taskbar)` | listę pozycji |
| desktop | `desktop_menu_items` | `(api, desktop, where, entry)` | listę pozycji |
| dostawca | `open_start_menu` | `(api, parent)` | okno |
| dostawca | `open_explorer` | `(api, location, parent, new_window)` | okno |

Wszystko poza dwoma dostawcami i czterema funkcjami cyklu życia działa na **wątku GUI**, bo tam żyją menu, paski i listy. Cokolwiek wolnego — na własny wątek.

## Pozycja (entry)

Wkład to zwykły słownik — ten sam kształt, który ustalił `src/ui/program_menu.py` dla „rzeczy, którą menu może zaproponować":

```python
{'id': 'copy_path', 'label': "Kopiuj pełną ścieżkę", 'action': copy_path}
```

| Klucz | Znaczenie |
|-------|-----------|
| `id` | Twój, unikalny w obrębie dodatku (jeśli go nie ma, zostanie nadany) |
| `label` | Co pisze. **Wymagane** — pozycja menu bez słów to pozycja, której czytnik ekranu nie przeczyta |
| `action` | Wywoływalny obiekt bez argumentów, uruchamiany na wątku GUI |
| `children` | Lista pozycji — robi z tego gałąź menu Start zamiast pojedynczej linii |
| `control` | Wywoływalne `(parent) -> wx.Window` — kontrolka na pasku zadań |
| `value` | Wywoływalne `(entry) -> str` — kolumna w przeglądarce plików |
| `help` | Podpowiedź / tekst na pasku stanu (pozycje paska narzędzi) |
| `art` | Identyfikator `wx.ART_*` — obrazek pozycji paska |
| `width` | Piksele (kontrolka paska, kolumna przeglądarki) |

Pozycja jest prawdziwa, jeśli ma coś do **zrobienia** (`action`), coś do **pokazania** (`control`, `value`) albo coś do **otwarcia** (`children`). Wszystko inne jest odrzucane, z podaniem powodu na konsoli — pozycja menu, za którą nic nie stoi, jest kłamstwem.

Do każdej przyjętej pozycji Titan dopisuje `addon` i `addon_name` — dzięki temu menu Start potrafi powiedzieć, skąd wzięła się pozycja.

## Obiekt API

```python
def start_menu_items(api, menu):
    api.log("zapytano o moje pozycje w menu Start")
    ...
```

| Metoda | Co daje |
|--------|---------|
| `api.id`, `api.path` | Identyfikator i katalog dodatku |
| `api.file(*parts)` | Ścieżka wewnątrz Twojego katalogu — ikony, dźwięki, dane |
| `api.shell()` | Działający `TitanShell` albo `None`, gdy powłoki nie ma |
| `api.window(name)` | `'desktop'`, `'taskbar'` albo `'start_menu'` |
| `api.run_action(addon, action, **params)` | **Dowolna akcja Titana** — patrz przewodnik po Action API |
| `api.setting(key, default)` | Twoje własne ustawienie (sekcja `shell_addon_<id>`) |
| `api.set_setting(key, value)` | To samo, zapisane |
| `api.speak(text)` | Mowa Titana |
| `api.sound(name)` | Jeden z własnych dźwięków powłoki |
| `api.log(message)` | Linia na konsoli z Twoim prefiksem |

`api.run_action` jest tu najważniejsze: to dzięki niemu dodatek sięga do reszty Titana bez rozrastania się tego obiektu o metodę na podsystem. `api.run_action('titan', 'open_settings')`, `api.run_action('tedit', 'open_file', path=...)`, `api.run_action('shell', 'list_windows')` — te same wywołania, które robi AI, makro i Action Bus. Sięgnij po nie, zanim sięgniesz po wnętrzności Titana.

## Pięć powierzchni

### 1. Sama powłoka

```python
def setup(api):
    """Raz, przy ładowaniu dodatku."""
    api.log("załadowany")


def on_shell_start(api, shell):
    """Pulpit, pasek i menu Start już istnieją.

    Wołane na WĄTKU ROBOCZYM - `start_shell()` kosztuje około 200 ms, a ten
    proces posiada appbar i shell hook, więc dodatki są ładowane i
    powiadamiane poza wątkiem GUI.  Cokolwiek dotyka okna, idzie przez
    `wx.CallAfter`.
    """
    import wx
    wx.CallAfter(lambda: api.log(str(api.window('taskbar'))))


def on_shell_stop(api, shell):
    """Powłoka znika - posprzątaj po sobie."""
```

### 2. Menu Start

Jedna funkcja zasila **oba** wbudowane menu — dwukolumnowe XP i klasyczne — **oraz wyszukiwarkę**, bo oba są budowane z `src/ui/start_menu_content.py`. Piszesz to raz.

```python
def start_menu_items(api, menu):
    def open_home():
        from src.shell import explorer
        explorer.open_explorer(os.path.expanduser('~'))

    return [
        {'id': 'home', 'label': _("Mój katalog domowy"), 'action': open_home},
        {'id': 'more', 'label': _("Mój dodatek"), 'children': [
            {'id': 'hello', 'label': _("Przywitaj się"),
             'action': lambda: api.speak(_("Cześć"))},
        ]},
    ]
```

Pozycja z `children` staje się **gałęzią**, która otwiera się w miejscu (lewa kolumna to drzewo, a nie łańcuch wysuwanych menu, za którymi klawiatura nie nadąża). Nie wpisuj słowa „podmenu" do etykiety: kontrolka drzewa sama zgłasza „zwinięte" / „rozwinięte", więc czytnik powiedziałby to dwa razy.

### 3. Przeglądarka plików

Cztery funkcje — odbudowane punkty rozszerzeń samego Explorera.

```python
def explorer_menu_items(api, browser):
    """Menu Narzędzia przeglądarki - istnieje tylko wtedy, gdy coś w nim jest."""
    return [{'id': 'where', 'label': _("Gdzie jestem?"),
             'action': lambda: wx.MessageBox(str(browser.location))}]


def explorer_toolbar_items(api, browser):
    return [{'id': 'up_twice', 'label': _("Dwa w górę"),
             'help': _("Przejdź dwa katalogi wyżej naraz"),
             'art': wx.ART_GO_DIR_UP,
             'action': lambda: (browser.go_up(), browser.go_up())}]


def explorer_context_items(api, browser, where, selection):
    """`where` to 'item' albo 'background'; `selection` to to, czego menu
    dotyczy - więc polecenie może dotyczyć TEGO pliku."""
    if where != 'item' or not selection:
        return []
    path = selection[0].get('path') or ''

    def copy_path():
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(path))
            finally:
                wx.TheClipboard.Close()

    return [{'id': 'copy', 'label': _("Kopiuj pełną ścieżkę"),
             'action': copy_path}]


def explorer_columns(api, browser, location):
    """Własna kolumna w widoku szczegółów."""
    def extension(entry):
        if entry.get('directory'):
            return ''
        return os.path.splitext(entry.get('name') or '')[1].lstrip('.').upper()

    return [{'id': 'extension', 'label': _("Rozszerzenie"), 'width': 90,
             'value': extension}]
```

**Regułę o kolumnach trzeba zapamiętać.** `explorer_columns` jest pytane **raz na katalog**, a `value` wołane potem dla każdego wiersza, z pozycji, którą przeglądarka już ma w ręku. Widok jest listą wirtualną — to dzięki temu katalog z trzema tysiącami plików otwiera się w około 30 ms zamiast sześciu sekund — więc `value`, które pyta Windows o cokolwiek per wiersz (wywołanie powłoki, odczyt pliku, zapytanie sieciowe), niszczy to. Zwykle wszystko, czego potrzebujesz, jest już w pozycji: `name`, `path`, `directory`, `size`, `modified`.

### 4. Pasek zadań

```python
def taskbar_bands(api, taskbar):
    """Własna kontrolka na pasku - Windows nazywa to deskbandem."""
    def make(parent):
        from src.shell.controls import TextControl
        return TextControl(parent, _("Przykład"))

    return [{'id': 'band', 'label': _("Przykładowa kontrolka"), 'width': 70,
             'control': make}]


def taskbar_menu_items(api, taskbar):
    return [{'id': 'refresh', 'label': _("Odśwież pasek"),
             'action': taskbar.refresh_windows}]
```

Kontrolka jest budowana **w zasobniku systemowym**, więc jest prawdziwym oknem potomnym paska: osiągalna Tabem i strzałkami jak wszystko inne tam, i nazwana, więc czytnik ekranu mówi, czym jest. Budowana jest **raz, razem z paskiem**, i nigdy przy odświeżaniu zasobnika — zasobnik jest odczytywany co trzydzieści sekund, a przebudowywanie czyjejś kontrolki tak często wyrzucałoby z niej klawiaturę.

Kontrolka, która nie jest `wx.Window`, jest odrzucana, z linijką na konsoli.

### 5. Pulpit

```python
def desktop_menu_items(api, desktop, where, entry):
    """`where` to 'item' (kliknięto ikonę) albo 'background'."""
    if where == 'background':
        return [{'id': 'count', 'label': _("Ile ikon?"),
                 'action': lambda: api.speak(str(len(desktop.entries)))}]
    name = (entry or {}).get('name') or ''
    return [{'id': 'say', 'label': _("Powiedz nazwę"),
             'action': lambda: api.speak(name)}] if name else []
```

## Dostawcy: zastępowanie części powłoki

### Własne menu Start

```ini
provides = start_menu
surfaces = start_menu
```

```python
def open_start_menu(api, parent):
    """Odpowiedz oknem.  To cała umowa."""
    return MyStartMenu(api, parent)
```

Okno musi mieć `Show`, `Hide` i `IsShown`. Cała reszta — gdzie się pojawia, co na nim jest, jak się po nim chodzi — jest Twoja. `data/shell addons/simple_start_menu/` to kompletne, działające menu w około 200 liniach: pole wyszukiwania, lista i każde polecenie przez `api.run_action`.

**Samo zainstalowanie nie zabiera klawisza Windows.** Titan pyta o menu Start dodatku dopiero wtedy, gdy użytkownik wybrał Twoje — w jednym z dwóch miejsc, które o to pytają:

- **Właściwości paska zadań -> Menu Start**, gdzie każdy zainstalowany dostawca jest przyciskiem wyboru obok dwóch menu Titana, z opisem z manifestu jako linijką pod spodem;
- **Ustawienia -> Powłoka Titana -> Menu Start**, ta sama lista jako lista rozwijana.

Oba zapisują `start_menu_style = addon` i `provider_start_menu = <twój id>` w sekcji `titan_shell`. Dodatek wybrany, a potem odinstalowany lub wyłączony, oznacza **własne menu Titana** — nigdy po cichu awansowany inny dodatek.

### Własna przeglądarka plików

```ini
provides = explorer
surfaces = explorer
```

```python
def open_explorer(api, location, parent, new_window):
    """`location` to katalog do pokazania (albo nazwa wirtualna, jak Mój
    komputer), `new_window` mówi, czy użytkownik prosił o drugie okno."""
    return MyBrowser(api, location, parent)
```

Wszystko, co w Titanie otwiera katalog, trafia tutaj: pulpit, Menedżer plików z menu Start, Mój komputer, Windows+E przy włączonej powłoce.

## Dostępność: reguły, które nie są opcjonalne

Powłoka zastępuje interfejs systemowy, więc jej użytkownicy czytają ją czytnikiem ekranu. Cztery reguły, każda okupiona błędem:

1. **Nigdy nie mów tego, co czytnik już mówi.** Sama powłoka nie mówi nic przez TTS: jest interfejsem systemowym, a komunikat Titana na wierzchu powtarzałby każdy przycisk dwa razy. `api.speak` istnieje, bo dodatek jest programem zainstalowanym przez użytkownika, a nie interfejsem systemowym — ale najpierw zapytaj siebie, czy czytnik już tego nie powiedział.
2. **Każda kontrolka, którą zbudujesz, musi być prawdziwym, fokusowalnym, nazwanym oknem.** Narysowany prostokąt jest dla czytnika niczym. Używaj kontrolek powłoki (`src/shell/controls.py` — odpowiadają MSAA nazwą, rolą i stanem przez `a11y.AccessibleMixin`), albo nazwij kontrolkę natywną „na twardo":

   ```python
   from src.shell.a11y import name_control
   name_control(self.list, _("Menu Start"))
   ```

   Samo `wx.Window.SetName` nigdy nie dociera do MSAA na kontrolce natywnej (lista odpowiada własnym IAccessible, którego nazwa bierze się z tekstu okna, a tego te kontrolki nie mają). Po to jest `name_control`.
3. **Lista z polami wyboru musi być polami wyboru dla systemu.** `wx.CheckListBox` jest na Windows rysowany samodzielnie: jego wiersze zgłaszają rolę „element listy" bez stanu zaznaczenia, więc czytnik mówi nazwę i nic o tym, czy jest włączona. Użyj `src.ui.check_list.CheckList` — listy w trybie raportu z `EnableCheckBoxes()`, której wiersze zgłaszają rolę „pole wyboru", stan CHECKED i wzorzec toggle w UIA.
4. **Żaden znak nie zastępuje obrazka ani słowa.** Tekst pozycji listy *jest* jej nazwą dla czytnika, więc strzałka po nazwie katalogu zostanie przeczytana jako strzałka. Powiedz „podmenu" słowami — albo lepiej, użyj kontrolki, która sama zgłasza stan.

## Własne ustawienia

```python
value = api.setting('greeting', 'Cześć')
api.set_setting('greeting', "Dzień dobry")
```

Trafiają do sekcji `shell_addon_<twój id>` w pliku ustawień Titana. `get_setting` jest buforowane względem znacznika czasu pliku, więc odczyt w obsłudze rysowania jest tani (około mikrosekundy) — zapis nie, więc nie zapisuj w pętli.

## Tłumaczenia

```python
try:
    from src.titan_core.translation import _
except Exception:
    def _(text):
        return text
```

Katalogi samego Titana są już załadowane, więc wszystko, co Titan mówi, dostajesz w języku użytkownika za darmo. Na słowa, których Titan nie ma, dołóż własny `.mo` obok dodatku i załaduj go przez `gettext`. **Nazwa i opis** dodatku nie są w ogóle tłumaczonymi tekstami — to `name_pl` / `description_pl` w manifeście.

## Włączanie i sterowanie

- **Ustawienia -> Powłoka Titana -> Dodatki powłoki** to lista z polami wyboru. Zaznaczenie zapisuje `status` w manifeście danego dodatku od razu, dokładnie jak robi to menedżer komponentów — dodatek powłoki włącza się po to, żeby go wypróbować.
- **Action API** ma to samo dla makra, AI albo innego dodatku:

| Akcja | Co robi |
|-------|---------|
| `shell.list_addons` | Wszystko zainstalowane, z `enabled`, `provides` i `surfaces` |
| `<id dodatku>.status` | Czy jest włączony? |
| `<id dodatku>.enable` / `<id dodatku>.disable` | Przełącza |

## Jak zlecić to AI

**Programista -> AI -> Utwórz dodatek powłoki...** generuje taki dodatek z
opisu. Model dostaje w całości ten przewodnik i dodatek wzorcowy, a to, co
napisze, jest przed zapisaniem sprawdzane względem samego Titana: funkcje
muszą być tymi, które Titan naprawdę woła (z właściwą liczbą argumentów),
klucze manifestu i powierzchnie muszą być tymi, które Titan czyta, dodatek z
`provides = start_menu` musi definiować `open_start_menu`, a każde
`api.cokolwiek` musi istnieć w prawdziwym `ShellAddonAPI`. Problem jest
zgłaszany z nazwy i model jest proszony o poprawkę - bo błąd, przed którym to
chroni, jest inaczej niewidoczny: dodatek, który się ładuje, jest na liście,
da się go zaznaczyć - i nic nie wnosi, bo jego funkcje nazywają się tak, jak
Titan nigdy nie pyta.

Sprawdzenie to `ai_creation_kit.check_shell_addon`; czyta
`shell.addons.HOOKS`, `HOOK_SIGNATURES`, `SURFACES`, `PROVIDABLE`,
`MANIFEST_KEYS` i samą klasę API - nigdy kopii - więc nie potrafi opisać
Titana, którego nie ma.

## Pakowanie

Każdy katalog dodatku można zamienić w jeden skompresowany plik:

```bash
python src/scripts/pack_addon.py "data/shell addons/moj_dodatek" --kind shell_addon -o moj_dodatek.tcd
python src/scripts/pack_addon.py --unpack moj_dodatek.tcd -o /tmp/podglad
```

- Dodatki powłoki pakuje się jako **`.TCD`** (`.TCA` to aplikacje i gry).
- Spakowany plik jest znajdowany i używany dokładnie jak katalog — bez osobnego manifestu, bez konwersji, bez ręcznej instalacji. Dwuklik w Eksploratorze instaluje go do `data/shell addons/` użytkownika.
- Można go wysłać do repozytorium aplikacji Titan-Net i pobrać stamtąd jak każdy inny dodatek.

## Diagnostyka

- Uruchom Titana ze źródeł (`python main.py`) i patrz na konsolę: wszystko, co warstwa dodatków odrzuci, mówi dlaczego — `[ShellAddons] moj_dodatek.start_menu_items failed: ...`, `contributed an entry with no label or nothing behind it`, `answered str, which is not a list of entries`.
- `api.log(...)` poprzedza Twoje własne linie tak samo.
- Testy powłoki to `tests/test_shell_addons.py` (26 testów) i `tests/test_shell.py`; uruchamiaj je bezpośrednio (`python tests/test_shell_addons.py`) — katalog `tests/` nie ma `__init__.py`. Jeśli dokładasz powierzchnię, dołóż tam test.
- Titan skompilowany (zamrożony) ładuje `init.py`, czytając go i wykonując, więc dodatek działa w kompilacie tak samo jak ze źródeł. Wszystko, co importujesz, a czego Titan nie ma, musi leżeć w Twoim `lib/`.

## Kompletny minimalny dodatek

`data/shell addons/hello_shell/__shell_addon__.TCE`:

```ini
[shell addon]
name = Hello shell
name_pl = Witaj powłoko
description = One entry on the Start menu and one on the desktop's menu.
description_pl = Jedna pozycja w menu Start i jedna w menu pulpitu.
author = Ja
version = 1.0
status = 1
surfaces = start_menu, desktop
```

`data/shell addons/hello_shell/init.py`:

```python
# -*- coding: utf-8 -*-
try:
    from src.titan_core.translation import _
except Exception:
    def _(text):
        return text


def setup(api):
    api.log("cześć")


def start_menu_items(api, menu):
    return [{'id': 'hello', 'label': _("Przywitaj się"),
             'action': lambda: api.speak(_("Cześć z mojego dodatku"))}]


def desktop_menu_items(api, desktop, where, entry):
    if where != 'background':
        return []
    return [{'id': 'count', 'label': _("Ile ikon?"),
             'action': lambda: api.speak(str(len(desktop.entries)))}]
```

Potem: Ustawienia -> Powłoka Titana -> Dodatki powłoki -> zaznacz, i naciśnij klawisz Windows.

## Lista kontrolna

- [ ] `__shell_addon__.TCE` z `[shell addon]`, `status = 1` i faktycznie dotykanymi `surfaces`
- [ ] `name_pl` / `description_pl`, jeśli Twoi użytkownicy są Polakami
- [ ] Tylko te funkcje, których potrzebujesz — każda jest opcjonalna
- [ ] Każda pozycja ma `label` i coś za sobą
- [ ] Nic wolnego na wątku GUI; `value` kolumny czyta pozycję, a nie Windows
- [ ] Każda zbudowana kontrolka jest fokusowalna i nazwana (`name_control` albo kontrolki powłoki)
- [ ] Nie mówisz tego, co czytnik ekranu już powiedział
- [ ] Do reszty Titana sięgasz przez `api.run_action`, a nie przez wnętrzności Titana
- [ ] Sprawdzone także wyłączone — powłoka nie może zauważyć Twojej nieobecności
- [ ] Spakowane do `.TCD` do rozpowszechniania

## Zobacz też

- `data/shell addons/example_shell_addon/` — jedna funkcja na powierzchnię, wzorzec
- `data/shell addons/simple_start_menu/` — kompletny dostawca menu Start
- `action_api_guide_pl.md` — wszystko, do czego sięga `api.run_action`
- `settings_interface_guide_pl.md` — ta sama idea dla okna ustawień
- `component_creation_guide_pl.md` — dla wszystkiego, co nie jest częścią powłoki

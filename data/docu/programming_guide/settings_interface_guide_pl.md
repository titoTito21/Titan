# Przewodnik tworzenia interfejsów ustawień TCE

## Wprowadzenie

Titan ma jedno okno ustawień, napisane w wxPython. **Interfejs ustawień** je zastępuje — stroną internetową, oknem w Qt, konsolą, kreatorem zadającym sześć pytań, dialogiem głosowym, czymkolwiek da się napisać w Pythonie.

Jest celowo zbudowany jak `data/launchers/`, bo to ta sama idea o poziom niżej: launcher zastępuje główne okno Titana, interfejs ustawień zastępuje jego okno ustawień. Naraz działa jeden, wybrany w **Ustawienia -> Interfejs -> „Interfejs ustawień"**, gdzie własne okno Titana nazywa się **Klasyczny**.

**To, co czyni całą rzecz możliwą: Twój interfejs nigdy nie dowiaduje się, czym jest ustawienie.**

`src/settings/ui_model.py` czyta opis z **własnego okna ustawień Titana** — jego kategorie są kategoriami, jego kontrolki są ustawieniami, ich etykiety są etykietami, już przetłumaczonymi. Dlatego:

- **Ustawienie dodaje się do Titana raz.** Nowy checkbox w `settingsgui.py` pojawia się w każdym zainstalowanym interfejsie, w języku użytkownika, bez zmiany w żadnym z nich.
- **Kategorie komponentów też tam są** — czterdzieści ustawień czytnika ekranu, menedżera makr, AI — bo komponent rejestruje swoją kategorię, dostając to okno, a to właśnie to okno jest czytane. Zmierzone na normalnej instalacji: 14 kategorii, około 147 ustawień.
- **Wartości są żywe.** Głosy, skórki, motywy dźwiękowe i silniki TTS to listy, które Titan wypełnia w trakcie działania; odczyt modelu to odczyt tego, co zobaczyłby użytkownik.
- **Zapis to własny zapis Titana**, ze wszystkim, co za nim idzie: rejestracją SAPI, restartem monitora systemu, przepięciem powłoki, przebudową paska menu. Interfejs, który sam zapisałby plik ini, ustawiłby wartość i nic by nie zmienił.

Nigdzie celowo **nie ma drugiej tabeli ustawień**. Jeśli zaczynasz taką pisać, źle zrozumiałeś projekt.

## Architektura

```
data/settings interfaces/moj_interfejs/
├── __settings_ui__.TCE   # Manifest (WYMAGANY, .TCE wielkimi literami)
├── init.py               # open_settings(api) (WYMAGANY; init.pyc też)
└── lib/                  # Dołączone biblioteki (opcjonalnie)
```

Wykrywanie to `platform_utils.discover_data_entries()`, więc interfejs może też być jednym spakowanym plikiem **`.TCD`**. Wszystko jest w `src/settings/interfaces.py`.

**Każde wejście do ustawień w całym programie idzie przez `interfaces.open_settings()`** — pasek menu, Niewidzialny interfejs, obie klasy trybu Klango, oba menu Start, menu pulpitu, powłoka i akcja `titan.open_settings`. To dlatego wybór czegokolwiek tutaj cokolwiek znaczy.

## Manifest `__settings_ui__.TCE`

```ini
[settings interface]
name = Settings as a web page
name_pl = Ustawienia jako strona internetowa
description = Every Titan setting as one HTML page in a Titan window.
description_pl = Wszystkie ustawienia Titana jako jedna strona HTML.
author = Twoje imię
version = 1.0
status = 0
libs = lib
```

| Pole | Wymagane | Opis |
|------|----------|------|
| name | nie | Nazwa wyświetlana (domyślnie nazwa katalogu) |
| name_pl, name_en, ... | nie | Nazwa w danym języku; `name_<kod>` wygrywa z `name` |
| description | nie | Jedno zdanie, pokazywane obok nazwy przy wyborze |
| description_pl, ... | nie | To samo, przetłumaczone |
| author | nie | Autor |
| version | nie | Wersja (domyślnie `1.0`) |
| status | tak | **`0` = oferowany, `1` = nieoferowany** |
| libs | nie | Podkatalogi dopisywane do `sys.path` (domyślnie `lib`) |

**Rozprowadzaj ze `status = 0`.** Inaczej niż dodatek powłoki, interfejs ustawień nie zmienia niczego przez samo zainstalowanie — jest jedną z możliwości w Ustawieniach -> Interfejs, dopóki ktoś go nie wybierze.

## `init.py`

Jedna funkcja:

```python
def open_settings(api):
    """Otwórz ustawienia.  Odpowiedz oknem, albo True, albo None."""
```

| Odpowiedź | Znaczenie |
|-----------|-----------|
| okno | Titan je pokazuje i wysuwa (`wx.Frame`, `wx.Dialog` albo cokolwiek z `Show`/`Raise`) |
| `True` | Otworzyłeś coś, co nie jest oknem — konsolę, przeglądarkę, dialog głosowy |
| `None` / wyjątek | Nie udało się: **otwiera się własne okno ustawień Titana**, z komunikatem |

Ten ostatni wiersz to reguła, a nie zabezpieczenie: ustawienia są miejscem, do którego użytkownik idzie coś naprawić — łącznie z „wyłącz ten interfejs" — więc nigdy nie mogą być tym, co dodatek zabiera. Interfejs odinstalowany, wyłączony, bez `open_settings`, rzucający wyjątek albo nieotwierający niczego oznacza własne okno Titana, powiedziane wprost.

## Obiekt API

`api` to `SettingsUIAPI`. Część od ustawień:

| Metoda | Odpowiada |
|--------|-----------|
| `api.categories()` | `[{'name': str, 'items': [pozycja, ...]}, ...]` — wszystko, bezpieczne dla JSON-a |
| `api.items()` | Wszystkie ustawienia płasko, dla interfejsu bez kategorii |
| `api.find(text)` | Ustawienia, których etykieta lub kategoria pasuje |
| `api.get(item_id)` | Jedna wartość |
| `api.set(item_id, value)` | Zmiana jednej — nic nie jest zapisane do `save` |
| `api.press(item_id)` | Naciśnięcie ustawienia będącego przyciskiem (okno, kreator) |
| `api.refresh()` | Ponowny odczyt okna, po zapisie albo pojawieniu się kategorii |
| `api.save()` | **Własny zapis Titana**, ze wszystkimi skutkami ubocznymi |
| `api.cancel()` | Schowanie okna ustawień bez zapisu |

Część od bycia oknem:

| Metoda | Co daje |
|--------|---------|
| `api.call(function, *args)` | Uruchamia coś **na wątku GUI** i czeka na wynik |
| `api.parent()` | Okno, do którego podpiąć swoje |
| `api.file(*parts)` | Ścieżka wewnątrz Twojego katalogu |
| `api.translate(text)`, `api.language()` | Gettext Titana i kod bieżącego języka |
| `api.speak(text)` | Mowa Titana |
| `api.open_builtin()` | Własne okno ustawień Titana — droga powrotna, zawsze dostępna |
| `api.log(message)` | Linia na konsoli z Twoim prefiksem |

## Dane, które renderuje interfejs

`api.categories()`:

```python
[{'name': "Ogólne",
  'items': [
      {'id': 'quick_start_cb', 'category': "Ogólne",
       'label': "Szybki start", 'kind': 'bool', 'value': True,
       'options': [], 'minimum': None, 'maximum': None,
       'enabled': True, 'description': ''},
      ...]},
 ...]
```

| Pole | Znaczenie |
|------|-----------|
| `id` | Uchwyt, który podajesz do `get` / `set` / `press` |
| `category` | Do której kategorii należy |
| `label` | Nazwa w języku użytkownika |
| `kind` | Czym **jest** kontrolka — tabela niżej |
| `value` | Co jest ustawione teraz |
| `options` | Możliwości (`choice`, `list`, `multi`) |
| `minimum`, `maximum` | Zakres (`number`) |
| `enabled` | Czy Titan pozwala tego teraz zmieniać |

### Rodzaje (`kind`)

| Rodzaj | Kontrolka w Titanie | Renderuj jako | `set` przyjmuje |
|--------|---------------------|---------------|-----------------|
| `bool` | `wx.CheckBox` | pole wyboru | `True` / `False` (albo `"tak"`, `"1"`, `"yes"`) |
| `choice` | `wx.Choice`, `wx.ComboBox`, `wx.RadioBox` | listę rozwijaną albo grupę przycisków | jedną z `options` |
| `number` | `wx.Slider`, `wx.SpinCtrl` | suwak albo pole liczbowe, z `minimum`/`maximum` | liczbę całkowitą |
| `text` | `wx.TextCtrl` | pole tekstowe | tekst |
| `secret` | `wx.TextCtrl` z `TE_PASSWORD` | pole hasła — **nigdy nie pokazuj wartości** | tekst |
| `list` | `wx.ListBox` | listę jednokrotnego wyboru | jedną z `options` |
| `multi` | lista z polami wyboru | **pola wyboru**, po jednym na opcję | listę tekstów |
| `command` | `wx.Button` | przycisk; `api.press(id)` | — |
| `info` | `wx.TextCtrl` tylko do odczytu | tekst do przeczytania, nie ustawienie | — |

`kind` mówi, czym jest **kontrolka**, a nie jak nazywa się klucz — dzięki temu interfejs renderuje to, co renderuje Titan, zamiast zgadywać z nazwy.

Dwie rzeczy wynikają z tego, jak model jest budowany, i warto je znać:

- **Kontrolka, której nikt nie nazwał, nie jest oferowana.** `wx.Choice` jest opisany napisem stojącym przed nim — tak buduje się każdy program w wx — a kontrolka bez podpisu jest pomijana, zamiast być pokazana jako bezimienne pole. Nadal da się ją zmienić we własnym oknie Titana.
- **Ustawienie wartości wyzwala zdarzenie kontrolki**, bo to tam Titan stosuje rzeczy na żywo (tempo mowy, motyw dźwiękowy, przełącznik, który powoduje pojawienie się kategorii Powłoka Titana). Ciche ustawienie zostawiłoby okno i program w niezgodzie.

## Wątki

Ustawienia to kontrolki wx. Odczyt lub zapis poza wątkiem GUI to zachowanie niezdefiniowane, a nie błąd, który byś zobaczył.

- Interfejs, który **jest oknem** (wx i wszystko, co Titan otwiera na wątku GUI), może wołać API wprost.
- Interfejs z **własną pętlą** — konsola zadająca pytania, serwer WWW odpowiadający na żądania, dialog głosowy — trzyma ją na własnym wątku i sięga do ustawień przez `api.call(...)`, które przerzuca wywołanie na wątek GUI i czeka (limit 20 s). Wołane *z* wątku GUI po prostu woła, więc nigdy nie musisz pytać, na którym wątku jesteś.

```python
categories = api.call(api.categories)
api.call(api.set, 'quick_start_cb', True)
api.call(api.save)
```

## Dostępność

Użytkownicy Titana czytają to okno czytnikiem ekranu, a ustawienia są ostatnim miejscem, które może być nieczytelne.

- **Używaj prawdziwych kontrolek.** Natywne `wx.CheckBox`, `wx.Choice`, `wx.Slider` i `wx.TextCtrl` czyta każdy czytnik ekranu bez Twojej pomocy. Cokolwiek narysujesz sam, jest pustym prostokątem.
- **`multi` to pola wyboru — i muszą być polami wyboru dla systemu.** Nie używaj `wx.CheckListBox`: na Windows jest rysowany samodzielnie, jego wiersze zgłaszają rolę „element listy" bez stanu zaznaczenia, a czytnik mówi nazwę pozycji i nic o tym, czy jest włączona. Użyj `src.ui.check_list.CheckList` — listy w trybie raportu z `EnableCheckBoxes()`, której wiersze zgłaszają rolę „pole wyboru", stan CHECKED i wzorzec toggle w UIA.
- **Nazwij swoje listy dla MSAA.** `wx.Window.SetName` nigdy nie dociera do czytnika na natywnej liście czy drzewie; robi to `src.shell.a11y.name_control(control, "Kategorie")`.
- **Postaw podpis przed każdym polem**, tak jak robi to okno Titana — tam czytnik ekranu (i `ui_model`) szuka nazwy kontrolki.
- **Nie buduj własnego głosu.** Jeśli chcesz coś powiedzieć — `api.speak`; jeśli czytnik działa, już czyta Twoje kontrolki, a druga kopia wszystkiego jest gorsza niż cisza.

## Włączanie i sterowanie

- **Ustawienia -> Interfejs -> „Interfejs ustawień"** wymienia Klasyczny (własne okno Titana) i każdy zainstalowany interfejs pod nazwą z manifestu.
- Action API ma to samo:

| Akcja | Co robi |
|-------|---------|
| `settings.settings_interfaces` | Co jest zainstalowane i który jest używany |
| `settings.use_settings_interface` | Wybiera jeden (pusty = Klasyczny) |
| `<id interfejsu>.status` / `<id interfejsu>.use` | To samo, dla konkretnego |

## Dwa przykłady

Oba są dołączone do Titana, oba zainstalowane i żaden nie jest używany, dopóki nie zostanie wybrany.

- **`data/settings interfaces/html_settings/`** — całe ustawienia jako jedna strona HTML w oknie `wx.html2`, z wyszukiwarką i odnośnikiem do każdej kategorii. Strona odzywa się z powrotem, ustawiając `location.href` na adres `titan:`, który Python blokuje w `EVT_WEBVIEW_NAVIGATING` i obsługuje — najstarsza sztuczka świata i jedyna, która działa na każdym silniku WebView bez mostka i bez lokalnego serwera.
- **`data/settings interfaces/console_settings/`** — `AllocConsole`, numerowana lista kategorii, numerowana lista ustawień, jedno pytanie naraz. To także interfejs, który działa wtedy, gdy graficznego nie da się użyć w ogóle.

## Kompletny minimalny interfejs

`data/settings interfaces/quick_settings/__settings_ui__.TCE`:

```ini
[settings interface]
name = Quick settings
name_pl = Szybkie ustawienia
description = One category at a time, in a plain Titan dialog.
description_pl = Jedna kategoria naraz, w zwykłym oknie Titana.
author = Ja
version = 1.0
status = 0
```

`data/settings interfaces/quick_settings/init.py`:

```python
# -*- coding: utf-8 -*-
import wx

try:
    from src.titan_core.translation import _
except Exception:
    def _(text):
        return text


class QuickSettings(wx.Frame):
    def __init__(self, api, parent=None):
        super().__init__(parent, title=_("Ustawienia"), size=(640, 520))
        self.api = api
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.categories = api.categories()
        sizer.Add(wx.StaticText(panel, label=_("Kategoria:")), 0, wx.ALL, 6)
        self.choice = wx.Choice(
            panel, choices=[c['name'] for c in self.categories])
        self.choice.SetSelection(0)
        self.choice.Bind(wx.EVT_CHOICE, lambda event: self.fill())
        sizer.Add(self.choice, 0, wx.EXPAND | wx.ALL, 6)

        self.box = wx.BoxSizer(wx.VERTICAL)
        self.host = wx.ScrolledWindow(panel)
        self.host.SetScrollRate(0, 10)
        self.host.SetSizer(self.box)
        sizer.Add(self.host, 1, wx.EXPAND | wx.ALL, 6)

        save = wx.Button(panel, wx.ID_SAVE, _("&Zapisz"))
        save.Bind(wx.EVT_BUTTON, self.on_save)
        sizer.Add(save, 0, wx.ALL, 6)
        panel.SetSizer(sizer)
        self.fill()

    def fill(self):
        """Tylko pola wyboru, żeby przykład był krótki."""
        self.box.Clear(True)
        self.controls = {}
        category = self.categories[self.choice.GetSelection()]
        for item in category['items']:
            if item['kind'] != 'bool':
                continue
            check = wx.CheckBox(self.host, label=item['label'])
            check.SetValue(bool(item['value']))
            check.Enable(item['enabled'])
            self.box.Add(check, 0, wx.ALL, 4)
            self.controls[item['id']] = check
        self.host.Layout()
        self.host.FitInside()

    def on_save(self, event):
        for item_id, check in self.controls.items():
            self.api.set(item_id, check.GetValue())
        self.api.save()
        self.Close()


def open_settings(api):
    frame = QuickSettings(api, api.parent())
    frame.Show()
    frame.Raise()
    return frame
```

Potem: Ustawienia -> Interfejs -> Interfejs ustawień -> Szybkie ustawienia. Od tej chwili każde wejście do ustawień otwiera Twój interfejs.

## Jak zlecić to AI

**Programista -> AI -> Utwórz interfejs ustawień...** generuje go z opisu, z
tym przewodnikiem w zapytaniu. To, co powstanie, jest przed zapisaniem
sprawdzane względem Titana: `open_settings(api)` musi być i brać jeden
argument, klucze manifestu muszą być tymi, które Titan czyta, każde
`api.cokolwiek` musi istnieć w prawdziwym `SettingsUIAPI`, a interfejs, który
importuje `set_setting` / `save_settings`, żeby samemu zapisać plik ini, jest
odrzucany z podaniem powodu - to ustawia wartość i nic nie zmienia.

Sprawdzenie to `ai_creation_kit.check_settings_interface`; czyta
`interfaces.ENTRY_POINT`, `interfaces.MANIFEST_KEYS` i samą klasę API, więc
zawsze opisuje tego Titana, którego masz.

## Diagnostyka

- Uruchom Titana ze źródeł i patrz na konsolę: `[SettingsInterfaces] ...` mówi, dlaczego interfejs nie został użyty, a `api.log` poprzedza Twoje własne linie.
- `python tests/test_settings_interfaces.py` (36 testów) to zestaw testów samego modelu — uruchamiaj bezpośrednio, katalog `tests/` nie ma `__init__.py`. Buduje sztuczne okno ustawień o znanej zawartości, więc jest też najszybszym sposobem zobaczenia, co `ui_model` robi z daną kontrolką.
- Żeby zobaczyć same dane, bez żadnego interfejsu:

  ```python
  from src.settings import interfaces
  model = interfaces.build_model()
  for category in model.categories():
      print(category['name'], len(category['items']))
  ```

- Titan skompilowany (zamrożony) wykonuje `init.py`, czytając go, więc interfejs zachowuje się w kompilacie tak samo jak ze źródeł. Wszystko, co importujesz ponad to, co Titan już ma, musi leżeć w Twoim `lib/`.

## Pakowanie

```bash
python src/scripts/pack_addon.py "data/settings interfaces/moj_interfejs" --kind settings_interface -o moj_interfejs.tcd
```

`.TCD`, znajdowany i używany dokładnie jak katalog, instalowalny dwuklikiem i możliwy do wysłania do repozytorium Titan-Net.

## Lista kontrolna

- [ ] `__settings_ui__.TCE` z `[settings interface]` i `status = 0`
- [ ] `open_settings(api)` odpowiadające oknem albo `True` i nigdy nierzucające wyjątku
- [ ] Renderujesz z `api.categories()` — bez własnej tabeli ustawień
- [ ] Każdy `kind` obsłużony albo świadomie pominięty (a `secret` nigdy niepokazywany)
- [ ] Zapis przez `api.save()`, nigdy przez zapis pliku ini
- [ ] Własna pętla na własnym wątku, sięgająca do ustawień przez `api.call`
- [ ] Prawdziwe, nazwane, fokusowalne kontrolki; `CheckList` dla `multi`
- [ ] Droga powrotna: `api.open_builtin()` w menu albo na przycisku
- [ ] Sprawdzone z zainstalowanym AI, czytnikiem ekranu i menedżerem makr — ich kategorie też muszą się pojawić

## Zobacz też

- `data/settings interfaces/html_settings/`, `console_settings/` — dwa działające przykłady
- `shell_addon_guide_pl.md` — ta sama idea dla pulpitu, paska zadań i menu Start
- `action_api_guide_pl.md` — akcje `settings.*` i wszystko inne, co Titan udostępnia
- `launcher_creation_guide_pl.md` — zastąpienie głównego okna Titana zamiast ustawień

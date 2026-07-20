# Przewodnik tworzenia trybów gamepada Titan

## Wprowadzenie

Własne tryby gamepada to foldery pod `data/gamepad/modes/`, dokładnie tak
samo jak komponent, które podłączają się do cyklu trybów kontrolera Titana.
Przy podłączonym gamepadzie, **przytrzymanie zderzaka (bumpera) przez
około sekundę** przełącza tryby (LB = poprzedni, RB = następny) —
wbudowane tryby (System, Kontroler, Czytnik ekranu, Klawiatura ekranowa)
są pierwsze, potem każdy własny tryb znaleziony tutaj. Gdy własny tryb
jest aktywny, otrzymuje zdarzenia przycisków / gałek analogowych / krzyżaka
/ zderzaków przez hooki `handle_*` i może mówić, odtwarzać dźwięki albo
symulować naciśnięcia klawiszy w odpowiedzi.

Kanoniczna dokumentacja API znajduje się w
`src/controller/gamepad_mode_api.py` (przeczytaj docstring modułu), a
`data/gamepad/modes/README.md` dokumentuje to dla autorów zewnętrznych.
`data/gamepad/modes/document_reader/` to kompletny, działający przykład.

## Architektura systemu trybów gamepada

### Lokalizacja trybów

Wszystkie własne tryby znajdują się w `data/gamepad/modes/` (wbudowane) i w
nakładce użytkownika `%APPDATA%/titosoft/Titan/data/gamepad/modes/`. Każdy
tryb to osobny katalog zawierający:
- `__mode__.TCE` — plik konfiguracyjny trybu (format INI)
- plik Python z podklasą `GamepadMode` (wskazany przez `main=` w
  konfiguracji, albo jedyny plik `*.py` w folderze jeśli `main=` pominięto)
- opcjonalnie folder `languages/` z własną domeną gettext trybu
- opcjonalnie folder `lib/` z dołączonymi zależnościami zewnętrznymi

### Cykl życia trybu

1. **Wykrywanie** — `load_custom_modes()` skanuje oba katalogi trybów przy
   starcie, czyta `__mode__.TCE`, pomija wyłączone/uszkodzone foldery
2. **Tworzenie instancji** — podklasa `GamepadMode` znaleziona w głównym
   module jest tworzona raz i dodawana do cyklu trybów
3. **Aktywacja** — `on_activate(manager)` jest wywoływana gdy użytkownik
   przełączy się na ten tryb (przytrzymanie zderzaka przez ~1s)
4. **Obsługa wejścia** — `handle_button`/`handle_axis`/`handle_hat`/
   `handle_bumper` są wywoływane dla każdego dyskretnego zdarzenia wejścia
   dopóki tryb jest aktywny
5. **Dezaktywacja** — `on_deactivate(manager)` jest wywoływana przy
   przełączeniu na inny tryb

## Struktura pliku konfiguracyjnego

### `__mode__.TCE`

Plik INI z sekcją `[mode]`:

```ini
[mode]
name = Mój tryb
name_pl = Mój tryb
name_en = My Mode
main = moj_tryb.py
description = Co robi ten tryb
libs = lib
status = 0
```

**Parametry:**
- `status` — **`0` = włączony (załadowany), inna wartość = wyłączony**
  (ta sama konwencja co komponenty)
- `name` / `name_<lang>` — etykieta ogłaszana przy wybraniu trybu. Loader
  wybiera `name_<aktualny_język>`, potem `name_en`, potem `name`, a na
  końcu spada do nazwy folderu.
- `main` — plik Python zawierający podklasę `GamepadMode`. Jeśli pominięty,
  loader wybiera alfabetycznie pierwszy plik `*.py` w folderze.
- `libs` (opcjonalnie) — rozdzielone przecinkami katalogi wewnątrz folderu
  trybu dodawane do `sys.path` przed załadowaniem (domyślnie `lib`), dzięki
  czemu tryb może dołączyć własne zależności bez zaśmiecania środowiska
  hosta. Zobacz `data/gamepad/modes/titan_talk/lib/` po prawdziwy przykład
  (dołącza `uiautomation` i `Pillow`).
- **Nie istnieje klucz konfiguracyjny `domain=`.** Domena gettext jest
  ustalana wyłącznie przez literał tekstowy przekazany do
  `setup_mode_translations(__file__, 'moj_tryb')` we własnym pliku `.py`
  trybu — to wywołanie jest jedynym miejscem, gdzie domena jest faktycznie
  ustalana.
- **WAŻNE**: Dodaj pustą linię na końcu pliku

## Klasa trybu

```python
from src.controller.gamepad_mode_api import (
    GamepadMode, setup_mode_translations, speak, play_mode_sound,
    tap, tap_combo,
)

# Ładuje własny folder languages/ tego trybu (domena gettext "moj_tryb")
_ = setup_mode_translations(__file__, 'moj_tryb')


class MojTryb(GamepadMode):
    name = "Mój tryb"  # etykieta zapasowa; name(_lang) z __mode__.TCE wygrywa

    def on_activate(self, manager):
        """Wywoływana gdy ten tryb staje się aktywny."""
        speak(_("Mój tryb aktywowany."))

    def on_deactivate(self, manager):
        """Wywoływana przy przełączeniu na inny tryb. Opcjonalne sprzątanie."""
        pass

    def handle_button(self, button_id):
        """Naciśnięcie przycisku (0=A, 1=B, 2=X, 3=Y, 6=Back, 7=Start, 8=LS, 9=RS, 10=Guide)."""
        if button_id == 0:  # A
            play_mode_sound('joystick/ui1.ogg')
            speak(_("Naciśnięto A"))
            return True
        return False

    def handle_axis(self, axis_id, value):
        """Wychylenie gałki analogowej, z debounce (0=lewa X, 1=lewa Y, 2=prawa X, 3=prawa Y).
        value jest ujemne dla góra/lewo, dodatnie dla dół/prawo."""
        return False

    def handle_hat(self, x, y):
        """Ruch krzyżaka, wykrywany na zboczu. x: -1/0/1 lewo/środek/prawo,
        y: 1/0/-1 góra/środek/dół."""
        return False

    def handle_bumper(self, is_left):
        """Tylko TAP zderzaka (przytrzymanie nadal przełącza tryby).
        is_left True = LB, False = RB."""
        return False
```

Loader tworzy instancję dowolnej podklasy `GamepadMode` zdefiniowanej w
głównym module — nadpisz tylko te hooki, których potrzebujesz; wszystkie
mają bezpieczne domyślne implementacje "nic nie rób".

## Przegląd hooków

| Metoda | Wywoływana gdy | Zwraca |
|--------|----------------|--------|
| `on_activate(manager)` | tryb staje się aktywny | — |
| `on_deactivate(manager)` | przełączenie na inny tryb | — |
| `handle_button(button_id)` | naciśnięcie przycisku (raz na naciśnięcie, nie na puszczenie) | `True` jeśli obsłużono |
| `handle_axis(axis_id, value)` | gałka analogowa wychyla się poza strefę martwą (z debounce — jedno wywołanie na dyskretne wychylenie) | `True` jeśli obsłużono |
| `handle_hat(x, y)` | krzyżak zmienia kierunek (wykrywanie na zboczu) | `True` jeśli obsłużono |
| `handle_bumper(is_left)` | zderzak jest **stuknięty** (krótkie naciśnięcie+puszczenie, nie przytrzymanie) | `True` jeśli obsłużono |

Zderzaki (przyciski 4/5) nigdy nie trafiają do `handle_button` —
zarezerwowane są do przełączania trybów. **Stuknięcie** (naciśnięcie i
puszczenie poniżej progu przytrzymania) trafia zamiast tego do
`handle_bumper`; **przytrzymanie** zderzaka przez ~1s nadal zmienia tryb
kontrolera niezależnie od tego, co zwróci aktywny tryb.

## Numeracja przycisków / osi / krzyżaka

Standardowy układ Xbox / XInput:

- **Przyciski**: `0`=A, `1`=B, `2`=X, `3`=Y, `6`=Back/View, `7`=Start/Menu,
  `8`=naciśnięcie lewej gałki, `9`=naciśnięcie prawej gałki, `10`=Guide.
  `4`/`5` (zderzaki) nigdy nie trafiają do `handle_button`.
- **Osie**: `0`=lewa X, `1`=lewa Y, `2`=prawa X, `3`=prawa Y. Ujemne =
  góra/lewo, dodatnie = dół/prawo.
- **Krzyżak**: `x` to `-1`/`0`/`1` (lewo/środek/prawo), `y` to `1`/`0`/`-1`
  (góra/środek/dół) — konwencja pygame dla hat.

## Funkcje pomocnicze

Wszystkie importowalne z `src.controller.gamepad_mode_api`:

- `setup_mode_translations(__file__, domain)` — ładuje własną domenę
  gettext trybu z jego folderu `languages/`; spada do funkcji tożsamościowej
  jeśli brak
- `speak(text, position=0.0, interrupt=True, pitch_offset=0)` — wysyła
  tekst do aktywnego czytnika ekranu / Titan TTS (świadome panoramowania
  stereo i wysokości głosu)
- `play_mode_sound(path='joystick/ui2.ogg', pan=None, elevation=0.0)` —
  odtwarza efekt dźwiękowy TCE z aktualnego motywu sfx
- `tap(key, hold=0.04)` / `press(key)` / `release(key)` — symuluje
  pojedyncze naciśnięcie klawisza (oparte na pynput, spada do pakietu
  `keyboard` w Windows) — wieloplatformowe
- `tap_combo(*keys, hold=0.04)` — symuluje akord, np.
  `tap_combo('ctrl', 'c')`
- `type_text(text)` — wpisuje tekst znak po znaku
- `get_clipboard_text()` — czyta bieżący tekst schowka (**tylko Windows**,
  `''` na innych platformach)
- `get_focused_window_text()` — czyta pełny tekst kontrolki z fokusem przez
  `WM_GETTEXT`, tylko do odczytu — bez naciśnięć klawiszy, bez ruchu
  karetki (**tylko Windows**, `''` gdzie indziej); dobre do wciągnięcia
  dokumentu do wirtualnego bufora
- `is_edit_field_focused()` — `True` gdy widoczna jest karetka tekstowa
  (**tylko Windows**; na innych platformach zwraca `True`, żeby tryby
  pozostały użyteczne)

Nazwy klawiszy dla `tap`/`press`/`release`: pojedyncze znaki plus `enter`,
`escape`, `backspace`, `tab`, `space`, `shift`, `ctrl`, `alt`, `win`,
`insert`, `delete`, `home`, `end`, `pageup`, `pagedown`, `up`, `down`,
`left`, `right`, `capslock`, `num0`..`num9`.

## Zasady projektowania

1. **Nigdy nie steruj po cichu aktywną aplikacją** — preferuj inspekcję
   tylko do odczytu (`get_focused_window_text`, `get_clipboard_text`) nad
   wstrzykiwaniem klawiszy, chyba że całym celem trybu jest bycie pilotem
   zdalnego sterowania
2. **Zawsze dawaj informację zwrotną dźwiękiem** — każde obsłużone
   zdarzenie powinno coś `speak()` albo `play_mode_sound()`; cichy tryb
   gamepada jest bezużyteczny dla niewidomego użytkownika
3. **Przedstaw się przy aktywacji** — `on_activate` powinno krótko
   wyjaśnić sterowanie, żeby użytkownik nie musiał niczego sprawdzać
4. **Zwracaj `True` tylko gdy faktycznie obsłużyłeś zdarzenie**
5. **Trzymaj `handle_*` szybkie** — działają w wątku odpytywania
   kontrolera; nie blokuj na I/O sieciowym/dyskowym w środku

## Kompletny przykład: Tryb sterowania mediami

Prosty tryb mapujący przyciski przednie na sterowanie odtwarzaniem, z
informacją zwrotną dźwiękiem przy każdej akcji.

**Plik: `data/gamepad/modes/media_control/__mode__.TCE`**
```ini
[mode]
name = Sterowanie mediami
name_pl = Sterowanie mediami
name_en = Media Control
main = media_control.py
description = Steruj odtwarzaniem mediów przyciskami: A play/pause, B następny, X poprzedni, Y wycisz.
status = 0
```

**Plik: `data/gamepad/modes/media_control/media_control.py`**
```python
"""
Sterowanie mediami - własny tryb gamepada dla TCE.

Sterowanie:
  * A (0) - Play / Pauza
  * B (1) - Następny utwór
  * X (2) - Poprzedni utwór
  * Y (3) - Wycisz / Odcisz
"""

from src.controller.gamepad_mode_api import (
    GamepadMode, setup_mode_translations, speak, play_mode_sound,
)

_ = setup_mode_translations(__file__, 'media_control')


class MediaControlMode(GamepadMode):
    name = "Sterowanie mediami"

    def on_activate(self, manager):
        speak(_("Sterowanie mediami. A play pauza, B następny, X poprzedni, Y wycisz."))

    def handle_button(self, button_id):
        if button_id == 0:  # A
            play_mode_sound('joystick/ui1.ogg')
            speak(_("Play / Pauza"))
            return True
        if button_id == 1:  # B
            play_mode_sound('joystick/ui1.ogg')
            speak(_("Następny utwór"))
            return True
        if button_id == 2:  # X
            play_mode_sound('joystick/ui1.ogg')
            speak(_("Poprzedni utwór"))
            return True
        if button_id == 3:  # Y
            play_mode_sound('joystick/ui1.ogg')
            speak(_("Wycisz"))
            return True
        return False
```

## Przykłady referencyjne

- **document_reader** (`data/gamepad/modes/document_reader/`): Czytnik
  wirtualnego bufora tylko do odczytu — przechwytuje pole tekstowe z
  fokusem albo schowek do własnego bufora i nawiguje po nim linia po
  linii / znak po znaku, nigdy nie dotykając prawdziwej karetki. Pełne
  wsparcie tłumaczeń (`languages/`).
- **titan_talk** (`data/gamepad/modes/titan_talk/`): Cięższy przykład
  dołączający zewnętrzne zależności (`uiautomation`, `Pillow`) przez
  `lib/` — czytnik ekranu sterowany joystickiem.

## Konfiguracja tłumaczeń

```bash
# 1. Utwórz katalog languages/ wewnątrz folderu trybu
mkdir data/gamepad/modes/moj_tryb/languages

# 2. Wyodrębnij tłumaczalne teksty
pybabel extract -o languages/moj_tryb.pot --no-default-keywords --keyword=_ \
    data/gamepad/modes/moj_tryb/moj_tryb.py

# 3. Zainicjuj języki
pybabel init -l pl -d data/gamepad/modes/moj_tryb/languages \
    -i data/gamepad/modes/moj_tryb/languages/moj_tryb.pot -D moj_tryb
pybabel init -l en -d data/gamepad/modes/moj_tryb/languages \
    -i data/gamepad/modes/moj_tryb/languages/moj_tryb.pot -D moj_tryb

# 4. Skompiluj
pybabel compile -d data/gamepad/modes/moj_tryb/languages
```

## Pakowanie jako `.TCD` (opcjonalnie)

Zamiast katalogu, tryb gamepada można rozpowszechniać jako pojedynczy plik
`.tcd` — z całą zawartością, łącznie z ewentualnym `lib/` zawierającym
zależności zewnętrzne. W pełni opcjonalne i dodatkowe.

```bash
python src/scripts/pack_addon.py data/gamepad/modes/moj_tryb --kind gamepad_mode -o moj_tryb.tcd
```

- `.tcd` to własny skompresowany kontener (nagłówek magiczny + strumień
  LZMA), celowo nie jest to prawdziwy zip/7z — 7-Zip i Eksplorator Windows
  odmawiają otwarcia go jako archiwum.
- Nie są potrzebne zmiany w kodzie: zawartość jest identyczna bajt-w-bajt z
  katalogiem, więc `__mode__.TCE` i główny plik `.py` nadal działają tak
  samo po rozpakowaniu, a dołączone zależności w `lib/` działają bez zmian.
- Plik `.tcd` wystarczy umieścić w `data/gamepad/modes/` (wbudowanym lub w
  nakładce użytkownika) — zostanie wykryty dokładnie tak samo jak tryb
  oparty na katalogu.

Zobacz `src/titan_core/titan_package.py` po implementację formatu.

## Wymagania wieloplatformowości

Tryby gamepada działają wewnątrz pętli odpytywania kontrolera TCE na
**Windows, macOS i Linux**.

- `speak()`, `play_mode_sound()`, `tap()`/`press()`/`release()`/
  `tap_combo()` są już wieloplatformowe (oparte na pynput) — używaj ich
  swobodnie
- `get_clipboard_text()`, `get_focused_window_text()`,
  `is_edit_field_focused()` są **tylko dla Windows** — zwracają bezpieczne
  wartości domyślne (`''` / `True`) na macOS i Linux; tryb zależny od nich
  powinien reagować łagodnie na pustą wartość zamiast zakładać Windows
- Nie importuj `win32com`, `winreg` ani innych modułów tylko dla Windows na
  poziomie modułu bez zabezpieczenia `try/except` albo
  `sys.platform == 'win32'`

## Testowanie trybu

1. Utwórz folder trybu pod `data/gamepad/modes/`
2. Dodaj `__mode__.TCE` i główny plik `.py` z podklasą `GamepadMode`
3. Zrestartuj TCE z podłączonym gamepadem
4. Przytrzymaj LB/RB przez ~1 sekundę żeby przełączyć się na nowy tryb;
   potwierdź że ogłasza się przy aktywacji
5. Przetestuj każdy przycisk/gałkę/krzyżak/stuknięcie zderzaka który
   zaimplementowałeś
6. Sprawdź logi konsoli pod kątem `[GamepadMode] loaded mode '...'` — jeśli
   go brak, sprawdź `status = 0` i czy główny plik zawiera podklasę
   `GamepadMode`

## Najważniejsze wskazówki

1. **Zawsze dawaj informację zwrotną dźwiękiem** — dźwięki i/lub TTS dla
   każdego obsłużonego zdarzenia
2. **Ogłaszaj sterowanie przy aktywacji** — nie każ użytkownikowi zgadywać
3. **Nigdy nie zakładaj Windows** — używaj zabezpieczeń wieloplatformowości
   opisanych powyżej
4. **Trzymaj handlery wejścia szybkie** — działają w wątku odpytywania
   kontrolera
5. **Preferuj inspekcję tylko do odczytu nad wstrzykiwaniem klawiszy**,
   chyba że tryb jest jawnie pilotem zdalnego sterowania

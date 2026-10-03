# Plan rozbudowy ustawień Titan Access (2026-10-02) - WYKONANY

Stan: wszystkie etapy wdrożone tego samego dnia (fundament, klawiatura,
symbole, tryb przeglądania, mysz, profile, pierścień i pomoc). Odstępstwa
od planu niżej: `Keyboard/TypingErrorSound` zastąpiono
`Keyboard/SpeakModifierKeys` (błędu pisania nie da się stwierdzić bez
zgadywania); `Browse/LineLength` pominięto (dzielenie akapitów to osobna
praca w buforze); `Navigation/AdvancedNavigation` - ustawienie z portu C#,
którego nic nie czytało - zniknęło z opisu; klucze echa zostały w sekcji
INI `TextEditing`, a w interfejsie są pod Klawiaturą (schemat rozdziela
sekcję INI od sekcji interfejsu, więc nie było migracji). Profile edytuje
się w liście przeglądanej (wiersz "Ustawienia tylko dla programu"), strona
wx je wymienia i usuwa. Testy: `tests/test_titan_access_settings.py`.

Odpowiedzi projektowe: zakres = wszystkie cztery obszary (klawiatura i echo,
mysz, interpunkcja/wielkie litery/liczby, tryb przeglądania i dokumenty).
Założenia przyjęte bez odpowiedzi (do potwierdzenia): jeden schemat napędza
stronę wx i listę przeglądaną; profile per program w pełnym zakresie;
pierścień szybkich ustawień plus zdanie pomocy do każdej pozycji.

Reguła nadrzędna: **ustawienie, którego nic nie czyta, nie istnieje.** Każdy
klucz z listy niżej wchodzi razem z miejscem w silniku, które go czyta, i z
testem, który to miejsce wskazuje (grep po `settings.get*`/właściwości).

## 0. Fundament: jeden schemat (`titan_access/settings_schema.py`)

Jedna krotka na ustawienie: `(sekcja INI, klucz, rodzaj, klucz etykiety,
klucz pomocy, domyślna, zakres/wybory, 'czyta': nazwa modułu)`. Z tego:
- `settings_store.DEFAULTS` (generowane, nie przepisywane),
- `settings_panel` (strona wx: bool -> CheckBox, choice -> Choice,
  range -> SpinCtrl, text -> TextCtrl; sekcja Mowa zostaje ręczna, bo ma
  listy głosów zależne od silnika),
- `settings_walk.SCHEMA` (lista przeglądana Insert+Ctrl+G),
- `ui_model` Titana widzi stronę jak dotąd (interfejsy ustawień bez zmian).
Test: każdy klucz schematu jest czytany w `titan_access/` (nie licząc
panelu i walkera) i każdy klucz czytany w silniku jest w schemacie.

## 1. Klawiatura i echo (sekcja `Keyboard`)

| klucz | rodzaj | domyślnie | czyta |
|---|---|---|---|
| SpeakCommandKeys | bool | false | keyboard_hook._echo (klawisze bez znaku: F5, Ctrl+S jako nazwa) |
| TypingInterruptsSpeech | bool | true | keyboard_hook (key-down znaku -> speech.stop) |
| PasswordEcho | choice: none/star | star | keyboard_hook._echo gdy rola `password` |
| CapsLockWarning | bool | true | keyboard_hook._echo (litera z CapsLock -> prefiks "wielka") |
| TypingErrorSound | bool | false | editable_text (klawisz bez efektu w polu tylko do odczytu -> dźwięk) |
| KeyboardEcho, PhoneticLetters | (istnieją w TextEditing) | | przenieść do `Keyboard`, migracja kluczy przy odczycie |

## 2. Mysz (sekcja `Mouse`)

| klucz | rodzaj | domyślnie | czyta |
|---|---|---|---|
| TrackMouse | bool | false | nowy `mouse_tracker.py`: wątek 50 ms, `GetCursorPos` -> `engine._object_at_point` |
| SpeakUnderMouse | choice: object/char/word/line | object | mouse_tracker (tekst przez `editable_text`/TextPattern RangeFromPoint) |
| AudioCoordinates | bool | false | mouse_tracker -> sound_manager.play_tone (pan = x, ton = y) |
| AudioCoordinatesByBrightness | bool | false | mouse_tracker (jasność piksela -> głośność) |
| MouseDelayMs | range 0-500 | 100 | mouse_tracker |
| IgnoreMouseInsideTitan | bool | true | mouse_tracker (`engine._is_tce_foreground`) |
Bez nowego DLL: odpytywanie zamiast WH_MOUSE_LL; ten sam obiekt pod
wskaźnikiem nie jest czytany dwa razy (klucz rola+nazwa+prostokąt).

## 3. Interpunkcja, wielkie litery, liczby (sekcja `Symbols`)

| klucz | rodzaj | domyślnie | czyta |
|---|---|---|---|
| PunctuationLevel | choice: none/some/most/all | some | nowy `symbols.py` (słownik symboli pl/en z poziomem), stosowany w echo, czytaniu kursora, say-all, nazwach elementów |
| CapitalLetters | choice: none/word/beep/pitch | pitch | symbols + speech_adapter (segment z pitch +N lub dźwięk `cap`) |
| CapitalPitchOffset | range 1-10 | 3 | speech_adapter |
| NumbersAs | choice: whole/digits/pairs | whole | symbols (tylko w czytaniu kursora i echo, nie w nazwach kontrolek) |
| TrimLeadingWhitespace | bool | true | editable_text (linia czytana bez wiodących spacji, z informacją o wcięciu) |
Słownik użytkownika: `%APPDATA%/titosoft/Titan/accessibility/symbols/<lang>.json`,
edytowany w menedżerze (nowa strona "Symbole"), wspólny z dodatkiem NVDA.

## 4. Tryb przeglądania i dokumenty (sekcja `Browse`)

| klucz | rodzaj | domyślnie | czyta |
|---|---|---|---|
| AutoFocusMode | bool | true | browse_mode.update_for_focus |
| FocusModeOnCaretMove | bool | false | browse_mode (strzałki w polu formularza) |
| QuickNavKeys | bool | true | browse_mode.handle_key / quick_nav |
| SayAllOnPageLoad | bool | false | browse_mode._announce_web_entry |
| SayAllRate | range -10..10 | 0 | engine.action_say_all (tymczasowy rate jak `voice` w Titan Script) |
| ReportLinks / ReportHeadings / ReportLists / ReportTables / ReportLandmarks | bool | true | virtual_buffer (filtr węzłów przy budowie dokumentu) |
| LayoutTables | bool | false | virtual_buffer (tabela bez nagłówków = układ, pomijana) |
| LineLength | range 40-200 | 100 | virtual_buffer (podział długiego akapitu na wiersze) |

## 5. Profile per program (założenie: pełne)

Profil = nadpisania kluczy schematu dla jednego programu, w sklepie
`readerHome` (`profiles/<exe>.json`), wybierany po oknie na pierwszym planie
(ten sam mechanizm co `perProgram`/moduły czytnika). `settings_store.get*`
pyta najpierw profil aktywnego programu. Wiersz "Tylko w tym programie" w
liście przeglądanej zapisuje bieżącą wartość do profilu; strona wx ma
wybór profilu u góry. Test: profil nigdy nie zmienia `General/Enabled`.

## 6. Pierścień i pomoc (założenie: oba)

Insert+Ctrl+Lewo/Prawo wybiera pozycję pierścienia (głośność, prędkość,
wysokość, głos, syntezator, schemat mowy, poziom interpunkcji, echo),
Góra/Dół zmienia; to te same wpisy schematu. Każdy wpis ma klucz pomocy
(`settings.help.<klucz>`, pl/en), czytany w liście przeglądanej na
Insert+F1 i pokazywany jako podpowiedź kontrolki na stronie wx.

## Kolejność i rozmiar

1. Fundament (0) z migracją dotychczasowych kluczy - jeden dzień.
2. Symbole (3) i klawiatura (1) - największy efekt słyszalny.
3. Tryb przeglądania (4).
4. Mysz (2).
5. Profile (5), pierścień i pomoc (6).
Każdy etap: testy jednostkowe + scenariusz w `tests/check_titan_access_live.py`.

(walk section added 2026-10-03)

# Jak napisać klienta Titana

## Po co to jest

Titan ma jedenaście rodzajów dodatków i każdy z nich mieszka wewnątrz
Titana: w katalogu `data/`, znajdowany przy starcie, uruchamiany w procesie
Titana albo przez niego. Ten przewodnik jest o dwunastej rzeczy, która
dodatkiem w ogóle nie jest - **o Twoim własnym programie, którego Titan nie
uruchomił i którym nie zarządza, dołączającym do Titana jak równy z
równym.**

Dwa takie już istnieją i żaden z nich nie jest wyjątkiem:

- **Dodatek do NVDA** (`nvda-addon/`) mieszka wewnątrz NVDA. Titan mówi do
  niego z pozycją, wysokością głosu i rolą; ten odpowiada, co jest teraz na
  ekranie, i udostępnia akcje Titana jako polecenia NVDA.
- **Most eltenowy** (`elten-tce-bridge/`) mieszka wewnątrz klienta
  EltenLink. Zgłasza, co Elten trzyma, renderuje aplikacje Titana w
  interfejsie Eltena i pozwala AI Titana sięgnąć do API Eltena.

Wszystko, co robi którykolwiek z nich, może zrobić Twój program - **bez ani
jednej linijki dopisanej do Titana**. O to właśnie tu chodzi: te dwa to
przykłady, nie przypadki uprzywilejowane.

## Kształt całości

Jest jedna rura, `\\.\pipe\TitanActions`, i jest dwukierunkowa. Przez nią:

- **Ty wołasz Titana** - jedna typowana powierzchnia JSON (`titan.bridge`)
  plus każda akcja każdego dodatku, jaki Titan ma;
- **Titan woła Ciebie** - te handlery, które zadeklarowałeś przy dołączaniu.

Potrzebujesz jednego pliku: `src/titan_core/titan_actions.py`. Skopiuj go
obok swojego kodu. Nie importuje nic z Titana ani nic spoza biblioteki
standardowej - dokładnie po to, żeby dało się go wstawić do aplikacji wx, do
launchera w Tk, do skryptu konsolowego albo do cudzego programu.

```python
from titan_actions import serve, call, call_sequence, list_addons, is_connected
```

## Dołączanie

```python
def pogoda(miasto='Warszawa', **_):
    """Jaka jest pogoda."""
    return f"W mieście {miasto} pada."


serve({'pogoda': pogoda},
      id='mojprogram',                # stałe: tak Titan Cię nazywa
      label='Mój program',            # to widzi człowiek
      kind='client')                  # patrz "Dodatek czy klient?" niżej
```

`serve` wraca **natychmiast**, niezależnie od tego, czy Titan działa, a
wątek demona po cichu próbuje dalej. Program, który czeka, aż Titan się
pojawi, to program, który nie wystartuje na maszynie bez Titana.

### Dodatek czy klient?

`kind='client'` mówi: *to inny program przejmuje kontrolę nad Titanem* - i
zmienia dwie rzeczy:

- **Titan powie o tym na głos**, gdy dołączasz i gdy wychodzisz. Nic innego
  na tym pulpicie nie powiadomiłoby niewidomego użytkownika, że podłączył
  się do niego jakiś program.
- **Wszystko, co ZMIENIA Titana, jest za zgodą użytkownika** - pytaną raz,
  zapamiętaną pod Twoim id i odwoływalną (`titan.external_clients`,
  `titan.allow_client`, `titan.forget_client`). Czytanie Titana jest
  serwowane zawsze, więc klient, który tylko pokazuje Titana, działa, zanim
  na cokolwiek padnie odpowiedź.

Któregoś z rodzajów dodatku (`app`, `game`, `component`, ...) użyj tylko
wtedy, gdy Twój program naprawdę jest dodatkiem Titana, uruchomionym przez
Titana.

## Bycie wołanym: co deklarujesz, a co tylko serwujesz

Handlery przekazane do `serve` to jest to, co Titan **może** zawołać. Lista
`actions` to jest to, co Titanowi **powiedziano**, że oferujesz:

```python
serve(handlers,
      id='mojprogram', label='Mój program', kind='client',
      actions=[
          {'name': 'pogoda',
           'summary': 'Jaka jest pogoda.',
           'params': {'miasto': {'type': 'string', 'required': True,
                                 'description': 'Które miasto.'}}},
          {'name': 'wyslij_raport',
           'summary': 'Wysyła dzisiejszy raport do zespołu.',
           'params': {}, 'risk': 'always_confirm'},
      ])
```

Pomiń `actions`, a zostanie wywnioskowana z sygnatur i docstringów Twoich
handlerów - to wystarczy, żeby działało. Wypisz ją, a dostaniesz trzy
rzeczy, które mają znaczenie:

- **Opis, który czyta człowiek.** To on jest pokazywany asystentowi, to go
  przegląda autor makra i to on stoi obok akcji wszędzie.
- **Typowane parametry**, żeby Titan mógł porządnie dopytać o brakujący,
  zamiast żeby Twój handler dostał nic i się wywrócił.
- **Poziom ryzyka** - `auto`, `confirm`, `always_confirm` - żeby coś, czego
  nie da się cofnąć, było potwierdzone, zanim AI zrobi to z własnej
  inicjatywy.

**Deklaruj mniej, niż serwujesz.** Widoczne staje się tylko to, co
zadeklarowane - i tylko to da się osiągnąć przez warstwę akcji
(`titan.list_actions`, asystent, makro, inny dodatek). Handler
niezadeklarowany nadal jest SERWOWANY - własne podsystemy Titana wołają go
po nazwie przez szynę - ale wołający idący publiczną warstwą akcji usłyszy,
że takiej akcji nie ma. I dobrze: właśnie dzięki temu dodatek do NVDA
serwuje `announce`, `attach` i `stand_down` - własną hydraulikę kanału,
którą warstwa czytnika w Titanie woła wprost - nie pokazując ich nikomu
jako rzeczy do zrobienia.

### Co daje deklaracja

Titan buduje z niej **prawdziwy dodatek**
(`src/titan_core/actions/registry.py`, `_merge_bus`). Od tej chwili Twoje
akcje są:

- w `titan.list_actions` i w Action API dla każdego innego dodatku;
- oferowane asystentowi AI i agentowi jako rzeczy, które mogą zrobić;
- wołalne ze **Skryptu Titana** (`mojprogram.pogoda miasto="Kraków"`);
- uruchamialne z menedżera makr, z powłoki i z każdego innego klienta.

Nic z tego nie wymagało linijki kodu w Titanie. Twój dodatek pojawia się,
gdy Twój program działa, i znika, gdy się kończy, a jego `source` to `bus`.

### Odpowiadanie

Zwróć napis, a to właśnie usłyszy wołający. Zwróć cokolwiek innego, a
zostanie to zserializowane do JSON-a - czyli tego, czego chce program po
drugiej stronie. Wyjścia są trzy, nie dwa - patrz "Dopytywanie o to, czego
potrzebujesz".

Twój handler jest wołany nazwanymi argumentami, które Titan przysyła, a
**argumenty, których nie deklaruje, są odrzucane** - więc dodanie parametru
później nigdy nie psuje starszego handlera.

## Wołanie Titana

### Powierzchnia typowana

```python
import json
answer = call('titan', 'bridge', request=json.dumps(
    {'call': 'macros.list', 'args': {}}))
data = json.loads(str(answer))['data']
```

`titan.bridge` odpowiada **JSON-em w jednym kształcie** - `{"ok": ...,
"data": ...}` - i to jest to, czego powinien używać program. Jest druga
droga do tych samych rzeczy: akcje odpowiadają prozą, w języku
użytkownika, bo są pisane dla modelu i dla makr. Nie parsuj jej. Każdy
prawdziwy błąd, na jaki wpadł most eltenowy, był dokładnie tym: cała linia
`- Voice demo (ctrl+alt+v) [tcs]` oddana jako *nazwa* makra.

Powierzchnia pokrywa to, czego potrzebuje klient pokazujący Titana:
`apps.list`, `apps.open`, `games.*`, `im.*`, `macros.list`, `cling.list`,
`settings.*`, `widgets.*`, `buffers.*`, `notifications.*`, `speech.*`,
`ai.ask`, `sounds.play`, `window.state`, `app.*` (aplikacje Titana z
interfejsem jako danymi) oraz `addons.list` / `addons.actions` /
`addons.run` na wszystko, na co nikt nie napisał osobnego wywołania. Zapytaj
o `capabilities`, żeby dostać listę, którą ten Titan naprawdę ma, zamiast
zgadywać.

### Cudza akcja

```python
call('tedit', 'open_file', path=r'C:\notatki\dzis.txt')
call_sequence([{'addon': 'tnotes', 'action': 'create_note',
                'args': {'title': 'Pomysły'}},
               {'addon': 'titan', 'action': 'speak',
                'args': {'text': 'Zapisane: {{1}}'}}])
```

`list_addons()` mówi, co jest. Między dodatkami celowo **nie ma ściany
uprawnień**: klient, któremu pozwolono sterować Titanem, sięga do
wszystkiego - bo o to właśnie chodzi, żeby nic nie musiało wozić ze sobą
własnego edytora, przeglądarki, menedżera plików ani pobieraczki.

## Dopytywanie o to, czego potrzebujesz

Akcja ma trzy wyjścia, nie dwa. Poza "zrobione" i "nie dało się" może
powiedzieć, że **najpierw musi się czegoś dowiedzieć**:

```python
from titan_actions import needs, fails

def wyslij_raport(odbiorca='', **_):
    if not odbiorca:
        return needs('odbiorca', 'Kto ma dostać raport?',
                     options=['zespół', 'tylko ja'])
    ...
    return f"Wysłane do: {odbiorca}."
```

Wołający pyta wtedy użytkownika i woła jeszcze raz z odpowiedzią. Bez tego
klawisz przypisany do "wyślij raport" jest klawiszem przypisanym do
odmowy. **Wymagany parametr, którego nie podano, sam staje się pytaniem**,
zbudowanym z jego `description` - więc porządne zadeklarowanie parametrów
daje Ci większość tego za darmo.

## Mówienie Titanowi o własnym programie

Istnieją dwa wywołania na kierunek, którego nikt inny nie obsłuży - wieści z
wnętrza programu, w którym jesteś:

- `notifications.add` wkłada coś tam, gdzie trafiają własne powiadomienia
  Titana: do centrum powiadomień, do bufora Titana, z dźwiękiem
  powiadomienia. Nazwij w nim swój program; użytkownik ma wiedzieć, skąd to
  jest.
- `client.report` parkuje migawkę stanu Twojego programu, którą Titan
  trzyma i z której potrafi odpowiadać, gdy Ciebie już nie ma - mówiąc przy
  tym, *ile ma lat*, żeby nieświeża odpowiedź była widocznie nieświeża.

Oba są serwowane bez zgody na sterowanie, bo program zgłaszający coś o sobie
nie jest programem sterującym Titanem. Nie używaj ich do niczego innego.

## Zasady nie do negocjacji

To nie jest kwestia stylu. Każda z nich to coś, co w tym repozytorium raz
zrobiono źle i naprawiono.

**Nigdy nie każ Titanowi czekać.** Twój handler jest wołany, gdy Titan wisi
na drugim końcu rury, często z obsługi fokusu albo z wątku interfejsu. Zrób
robotę na własnym wątku i wróć; odpowiedz tym, co wiesz, a nie tym, czego za
chwilę się dowiesz. Jeśli musisz przejść na własny wątek interfejsu, podaj
`marshal=`; jeśli Twoje handlery już to robią same, podaj `marshal`, który
po prostu woła funkcję - inaczej każde wywołanie czeka na Twoją pętlę
komunikatów.

**Granicą jest tablica.** Jeśli Titan może nazwać coś, a Ty rozwiązujesz to
przez `getattr`, to cokolwiek jest po drugiej stronie tej rury, sięgnie
wszędzie w Twoim procesie. Wypisz wywołania w słowniku. Nazwa, której tam
nie ma, nie istnieje.

**Odmowa jest odpowiedzią.** Kiedy czegoś nie zrobisz - przełącznik
wyłączony, użytkownik odmówił, funkcji nie ma - powiedz to zdaniem, na które
użytkownik może zareagować. Odmowa, która przychodzi jako błąd transportu,
jest raportowana jako "program nie odpowiedział", co nie jest ani prawdą,
ani czymś, co da się naprawić.

**Powiedz, który z powodów to był.** "Nie działa", "odmówił", "nie
odpowiedział na czas" i "ta wersja nie ma tego wywołania" to cztery różne
rzeczy i z każdą użytkownik robi co innego. Wysłanie kogoś do sprawdzenia
ustawienia, które już jest włączone, jest gorsze niż nic.

**Degraduj, nie znikaj.** Pytaj, co druga strona potrafi, zamiast zakładać;
pomijaj to, czego nie ma, i mów dlaczego. Funkcja po cichu nieobecna jest
nie do odróżnienia od zepsutej - a dla użytkownika, który nie widzi ekranu,
ta różnica to cała różnica między "spróbuję inaczej" a "to jest zepsute".

**Żadnych emoji, niczego wymyślonego.** Tekst Titana widziany przez
użytkownika jest po angielsku, tłumaczony przez gettext i nigdy nie zawiera
emoji. Kontrolka, która nie ma nazwy, nie ma nazwy: powiedz to, zamiast
zmyślać.

## Dwa gotowe przykłady

- `nvda-addon/addon/globalPlugins/titanEnhancements/link.py` - dołączanie,
  deklarowanie mniej, niż się serwuje, i kanał dwukierunkowy, w którym Titan
  woła Ciebie znacznie częściej niż Ty jego.
- `elten-tce-bridge/titan_bus.rb` - ten sam protokół w Rubym, w programie
  napisanym przez kogoś innego, ze zgodą użytkownika pytaną również po tamtej
  stronie.

Do żadnego z nich nie sięga nic w Titanie, co znałoby jego nazwę.

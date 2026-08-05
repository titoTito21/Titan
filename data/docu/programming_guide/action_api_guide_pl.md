# Titan Action API - jak pozwolić Titanowi wywoływać twój dodatek

## Po co to jest

Twój dodatek coś potrafi. Edytor otwiera i zapisuje pliki, odtwarzacz je gra,
menedżer plików je kopiuje, komponent czegoś pilnuje. Dopóki tego nie
zadeklarujesz, nikt spoza twojego dodatku nie może o to poprosić: ani
użytkownik z poziomu innego dodatku, ani komponent, ani agent AI czy asystent
głosowy Titana.

Action API to jeden plik mówiący, co twój dodatek potrafi, i jeden moduł, który
to robi. Gdy oba istnieją, z dowolnego miejsca w Titanie działa to:

```python
from src.titan_core import actions

actions.run('tedit', 'open_file', path=r'C:\notatki.txt')
```

a AI potrafi to samo, bo użytkownik poprosił o to słowami.

To jest opcjonalne. Dodatek bez manifestu działa dokładnie tak jak dotąd.

## Dwa pliki

Umieść je w katalogu swojego dodatku, obok istniejącego manifestu
(`__app.TCE`, `__component__.TCE`, `applet.json`, ...):

```
data/applications/tEdit/
    __app.TCE           <- twój dotychczasowy manifest, bez zmian
    __actions.json      <- co potrafisz
    tedit_actions.py    <- jak to robisz
    tedit.py
```

Oba są wykrywane tak samo, gdy dodatek jest spakowany do `.TCA` lub `.TCD`,
więc pakowanie niczego tu nie zmienia.

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

Uwaga: opisy w manifeście pisz po angielsku - to je czyta model, a Titan
tłumaczy interfejs osobno.

| Klucz | Znaczenie |
| --- | --- |
| `id` | Stały identyfikator. To wpisują wywołujący. Małe litery, cyfry, podkreślenia. Domyślnie nazwa katalogu. |
| `label` | Nazwa dla człowieka, używana gdy Titan lub AI mówi o twoim dodatku. |
| `description` | Jedno zdanie o tym, do czego dodatek służy. AI czyta to, decydując, czy to ciebie szuka. |
| `transport` | `process` dla aplikacji i gier, `inproc` dla reszty. Rzadko trzeba ustawiać - domyślna wartość dla twojego rodzaju jest właściwa. |
| `entry` | Moduł z twoimi obsługami, względem twojego katalogu. Musi być w twoim katalogu. |
| `launch_if_needed` | Czy Titan może uruchomić twoją aplikację, żeby dostarczyć akcję? Domyślnie `true`. |

Każda akcja:

| Klucz | Znaczenie |
| --- | --- |
| `name` | Nazwa akcji. Małe litery z podkreśleniami. |
| `summary` | Jedno zdanie w trybie rozkazującym: "Open a text file in the editor." To widzi AI, więc pisz dla kogoś, kto nigdy nie widział twojego dodatku. |
| `params` | Nazwane parametry. Typy: `string`, `number`, `integer`, `boolean`. Te, bez których nie zadziałasz, oznacz `"required": true`. Każdemu daj `description`. |
| `risk` | `auto` (po prostu zrób), `confirm` (użytkownik jest pytany), `always_confirm` (pytany zawsze, niezależnie od jego ustawień). Wszystko, co zapisuje, wysyła, usuwa lub kosztuje, to co najmniej `confirm`. |
| `mode` | `live`, `headless` albo `any`. Patrz niżej. |
| `timeout` | Sekundy, ile może trwać bieg bezokienkowy, gdy domyślne 45 nie wystarcza. |
| `launch_if_needed` | Czy Titan może uruchomić dodatek, żeby dostarczyć *tę* akcję? Nadpisuje ustawienie dodatku. Ustaw `true` tylko tam, gdzie sensem jest pokazanie czegoś użytkownikowi („otwórz ten plik"); akcja raportująca o otwartym oknie („co masz otwarte") musi zostać na false, inaczej Titan otworzy świeże okno, żeby odpowiedzieć na pytanie o nic. |
| `promote` | `true` czyni z akcji pełnoprawne narzędzie AI zamiast osiągalnego przez ogólny dyspozytor. Promuj dwie-trzy rzeczy, o które użytkownicy naprawdę proszą; resztę zostaw. |

## Trzy tryby - i dlaczego `live` to ostateczność

Aplikacje i gry działają we własnym procesie - dlatego istnieje `mode`.

- **`headless`** - akcja jest samodzielna. Titan uruchomi twój moduł akcji jako
  krótkotrwały proces. Nic nie pojawia się na ekranie.
- **`any`** (domyślnie) - otwarta instancja, gdy jest, bezokienkowo gdy jej
  nie ma. **Tak powinno być prawie wszystko.**
- **`live`** - akcja **nie da się wykonać** bez działającego okna.

**Nie oznaczaj akcji jako `live` tylko dlatego, że akurat w oknie napisałeś
kod.** Użytkownik, który prosi o „notatkę, a potem przeczytaj ją moim głosem z
ElevenLabs", nie będzie najpierw otwierał dwóch aplikacji - i nie powinien
musieć. Zapytaj, czy akcja naprawdę potrzebuje okna, czy tylko twoich danych:

| Naprawdę potrzebuje okna | Potrzebuje tylko danych |
| --- | --- |
| „zapisz dokument, który mam otwarty" | „przeczytaj ten plik", „zapisz ten plik" |
| „co jest teraz zaznaczone" | „skopiuj to tam", „znajdź pliki o nazwie X" |
| „cofnij stronę" | „jakie mam zakładki" |
| „pokaż mi tę stronę" | „pobierz ten plik", „przeczytaj to na głos" |

Wszystko z prawej kolumny należy do modułu, który czyta twój plik ustawień i
robi robotę - klucz API, katalog pobierania i zapisane dane leżą na dysku, a
okno wcale ich nie posiada. Akcje ElevenLabs i menedżera pobierania w Titanie
są napisane dokładnie tak: wolą otwarte okno, gdy jest (wynik trafia wtedy do
historii i do listy), a bez niego działają równie dobrze.

Dwie praktyczne uwagi do pracy bezokienkowej:

- Długie zadanie dostaje w manifeście `"timeout": 180` (sekundy), zamiast być
  ubite po domyślnych 45.
- Cokolwiek trwa dalej po zwróceniu odpowiedzi - odtwarzanie dźwięku, pobieranie
  dużego pliku - uruchamiaj **odczepione**, żeby akcja mogła wrócić od razu, a
  praca nie została ucięta wraz z końcem krótkotrwałego procesu.

Dodatki działające w procesie Titana (komponenty, widżety, aplety paska stanu,
silniki TTS, tryby gamepada, launchery, moduły Titan IM) ignorują `mode`
całkowicie: są już w środku, są po prostu wywoływane i nigdy nie potrzebują
okna.

Żeby coś zostało przeczytane, wywołaj `actions.run('titan', 'speak', text=...)`
- silniki mowy Titana są w jego własnym procesie, więc żadne okno nie jest w to
zamieszane i żaden dodatek nie potrzebuje własnego głosu.

## Moduł obsług

Obsługa to zwykła funkcja. Dostaje zadeklarowane parametry jako argumenty
nazwane - parametry, których nie deklaruje, są pomijane, więc dodanie nowego
nigdy nie psuje starej obsługi.

**Zwracaj zdanie.** Wywołującym może być czytnik ekranu czytający to na głos
albo AI mówiące użytkownikowi, co właśnie zrobiło. `"Saved notes.txt."` to dobra
wartość zwracana; `True` nie.

```python
import os, sys

# Korzeń Titana jest na ścieżce każdej aplikacji, którą on uruchamia.
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


LIVE_HANDLERS = {'open_file': open_file}
HEADLESS_HANDLERS = {}


def attach(frame):
    """Wywoływane, gdy okno już istnieje: od tej chwili Titan może nas sterować."""
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

I jedno wywołanie w starcie twojej aplikacji:

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

**Dołączenie nigdy nie może być krytyczne.** Twój dodatek musi działać dokładnie
tak jak wcześniej, gdy Titana nie ma - więc obuduj to i jedź dalej.

### Wątki

`serve()` odpowiada Titanowi w wątku w tle. Jeśli twoja obsługa dotyka okna, nie
wolno jej tam działać. wxPython jest wykrywany i obsłużony za ciebie. Dodatek
na Tk podaje własny przekaźnik:

```python
from src.titan_core.titan_actions import serve, tk_marshal
serve(HANDLERS, marshal=tk_marshal(root))
```

## Trzy zakończenia, nie dwa

Obsługa może skończyć na trzy sposoby, a powiedzenie tego samą prozą nie
wystarcza - wywołujący, który łańcuchuje kilka akcji, nie odróżni „nie ma takiej
notatki" od sukcesu i pojedzie dalej do kroku, który zakładał, że jest.

```python
from src.titan_core.actions import fails, needs        # wewnątrz Titana
from src.titan_core.titan_actions import fails, needs  # we własnym procesie
```

**Udało się** - zwróć zdanie.

```python
return f"Saved {os.path.basename(path)}."
```

**Nie udało się** - zwróć `fails(powód)`. Powód usłyszy użytkownik, więc pisz go
dla niego.

```python
if not os.path.isfile(path):
    return fails(f"There is no file at {path}.")
```

**Trzeba dopytać** - zwróć `needs(nazwa, pytanie, options=...)`. Pytanie to
zakończenie, nie porażka: Titan przekazuje je temu, kto wywołał. AI zadaje je
użytkownikowi i woła ponownie z odpowiedzią, komponent pokazuje okienko. Akcja
wykonuje się wtedy raz, na prawdziwej odpowiedzi, zamiast teraz na zgadywance.

```python
if len(matches) > 1:
    return needs('which', f"'{name}' matches {len(matches)} macros. "
                 f"Which one should run?",
                 options=[m['name'] for m in matches])
```

Używaj `needs` tam, gdzie zgadywanie byłoby **szkodliwe albo irytujące**: cel,
którego nie da się wymyślić, niejednoznaczna nazwa, coś, co zaraz zostanie
nadpisane. Nie używaj do szczegółu, który da się sensownie domyślnie ustawić -
pytaj raz, nie trzy razy.

Część dostajesz za darmo: **brakujący parametr wymagany sam staje się
pytaniem**, zbudowanym z `description` w twoim manifeście. Pisz więc te opisy
tak, jakby użytkownik miał je usłyszeć - bo usłyszy.

Od strony wywołującego:

```python
result = actions.run('tfm', 'copy_path', source=path)
if result.pending:
    print(result.question.prompt, result.question.options)

# albo niech Titan przeprowadzi całą pętlę, pytając w okienku:
actions.run_interactive('tfm', 'copy_path', source=path)
```

## Polecenia złożone

„Napisz mi podsumowanie, zapisz jako notatkę, a potem przypomnij mi o tym jutro"
to trzy akcje, gdzie późniejsze potrzebują tego, co wyprodukowała wcześniejsza.

```python
actions.run_sequence([
    {'addon': 'tnotes', 'action': 'create_note',
     'args': {'title': 'Zakupy', 'text': 'mleko, chleb'}},
    {'addon': 'tnotes', 'action': 'read_note', 'args': {'title': 'Zakupy'}},
    {'addon': 'treminder', 'action': 'create_reminder',
     'args': {'name': 'Kup: {{2}}', 'date': 'tomorrow', 'time': '17:00'}},
])
```

`{{2}}` to wynik kroku 2 - i to cały język podstawień, celowo. Bieg zatrzymuje
się na pierwszym kroku, który zawiódł albo zapytał, a `result.text` nazywa każdy
krok tak czy inaczej, żeby użytkownik usłyszał, co się wykonało.

Z aplikacji, w jej własnym procesie, to samo: `titan_actions.call_sequence([...])`.
AI ma to jako `titan_run_actions`.

To także powód, dla którego `fails()` ma znaczenie: krok zgłaszający kłopot samą
prozą wygląda jak sukces, a sekwencja jedzie dalej.

## Dodatki w procesie: JSON niepotrzebny

Komponent, widżet, aplet paska stanu, silnik TTS, tryb gamepada, launcher lub
moduł Titan IM może całkiem pominąć `__actions.json` i zadeklarować akcje w
Pythonie, z prawdziwymi funkcjami:

```python
def say_time():
    """Speak the current time."""
    import time
    return time.strftime("It is %H:%M.")


TITAN_ACTIONS = [
    {'name': 'say_time', 'summary': 'Speak the current time.',
     'run': say_time},
]
```

Titan znajdzie to na module, który już załadował, więc twoje obsługi widzą żywy
stan dodatku. Możesz też dostarczyć oba: JSON dobrze opisuje akcje, a
`TITAN_ACTIONS` dokłada te, które istnieją dopiero w czasie działania.

## Wywoływanie innych dodatków

Twój dodatek jest też wywołującym. Co potrafi Titan, potrafisz i ty:

```python
from src.titan_core import actions

for addon in actions.list_addons():
    print(addon['id'], addon['label'], addon['actions'])

result = actions.run('tmedia', 'play', query='wiadomości')
if result:
    print(result.text)
else:
    print("nie udało się:", result.text)
```

`run()` nigdy nie rzuca wyjątkiem. `result.ok` mówi, czy się udało,
`result.text` zawsze nadaje się do pokazania użytkownikowi, a `result.raised()`
zamienia niepowodzenie w wyjątek, jeśli wolisz tak to obsłużyć.

Ten import działa dla wszystkiego, co żyje **wewnątrz** Titana: komponent
wołający inny komponent, widżet wołający aplet paska stanu, tryb gamepada
wołający launcher. **Aplikacja lub gra** to osobny proces, więc zaimportowanie
tam rejestru zbudowałoby drugą, ślepą kopię - nie widzącą ani komponentów
załadowanych przez Titana, ani innych aplikacji. Z osobnego procesu poproś
Titana przez połączenie, które już masz:

```python
from src.titan_core.titan_actions import call, list_addons

for addon in list_addons():
    print(addon['id'], addon['label'], addon['actions'])

result = call('tmedia', 'play', query='wiadomości')
if result:
    print(result.text)
```

`call()` wymaga połączenia, a to samo połączenie niesie oba kierunki. Dodatek,
który nic nie udostępnia i chce tylko wołać innych, używa `connect()` zamiast
`serve()`:

```python
from src.titan_core.titan_actions import connect, call

connect(id='myapp', label='My App')
call('tweb', 'open_url', url='https://example.org')
```

Żadne z nich nie rzuca wyjątkiem i oba zwracają ten sam obiekt wyniku.

### Nie przepisuj tego, co Titan już ma

Między dodatkami nie ma muru uprawnień: co inny dodatek zadeklaruje, to możesz
wywołać. To celowe i o to w całym kontrakcie chodzi - nikt nie powinien
dostarczać własnego edytora, przeglądarki, menedżera plików ani pobieraczki.

```python
actions.run('tedit', 'open_file', path=path)        # pokaż użytkownikowi tekst
actions.run('tweb', 'open_url', url=url)            # pokaż stronę
actions.run('tfm', 'copy_path', source=a, destination=b)
actions.run('tdownloader', 'download', url=url)     # pobierz plik
actions.run('tnotes', 'create_note', title=t, text=body)
actions.run('treminder', 'create_reminder', name=n, date='tomorrow', time='09:00')
```

Każde z nich daje użytkownikowi jego własne ustawienia, jego katalog pobierania,
jego historię i jego komunikaty - czego prywatna kopia w twoim dodatku nigdy nie
da.

### Sam Titan też jest wywoływalny

Podsystemy Titana odpowiadają na te same wywołania, więc dodatek nigdy nie musi
sięgać do `src/`, żeby zmienić coś, co należy do Titana:

| Dostawca | Co obejmuje |
| --- | --- |
| `titan` | ustawienia Titana, komponenty, dodatki, silniki TTS, uruchamianie |
| `settings` | znajdowanie i wyjaśnianie ustawienia po tym, co robi |
| `system` | głośność, urządzenie odtwarzania, jasność, plan zasilania, motyw, Wi-Fi, autostart |
| `gamepad` | tryby gamepada - lista, odczyt, ustawienie, przełączanie |
| `titannet` | wątki i odpowiedzi na forum, poczta, grupy, pokoje, prywatne wiadomości |
| `elten` | wiadomości, fora i blogi Eltena |
| `im` | rozmowy WhatsApp i Messenger |
| `ocr` | odczyt niedostępnego okna i naciskanie tego, co znajdzie |
| `memory` | co AI pamięta między rozmowami |

```python
actions.run('system', 'set_volume', percent=30)
actions.run('gamepad', 'set_mode', mode='czytnik ekranu')
actions.run('titan', 'set_setting', key='rate', value='60')
```

`actions.list_addons()` i `actions.describe_addon(id)` wyliczają wszystko -
dostawców wbudowanych i zainstalowane dodatki - więc niczego nie trzeba wpisywać
na sztywno. Zainstalowany dodatek nigdy nie przejmie tych identyfikatorów: gdy
zadeklaruje `id: "system"`, Titan zachowa swój, a dodatek będzie osiągalny jako
`system_addon`.

## Jak pisać akcje, z których AI naprawdę skorzysta

AI ma twoje `summary` i opisy parametrów - i nic więcej.

- **Nazwij akcję zamiarem użytkownika**, nie swoją metodą wewnętrzną:
  `play_audiobook`, nie `set_playlist_mode_2`.
- **Pisz podsumowanie jak polecenie**: "Play a whole folder as one audiobook,
  continuing from where the user stopped."
- **Powiedz, co parametr przyjmuje**, razem z formatami: "'50%', '49 minutes'
  albo '1:23:45'".
- **Zwracaj, co się faktycznie stało**, łącznie z tym, co się nie udało:
  "Played episode 6. Three other episodes matched - say which if this was the
  wrong one."
- **Daj sposób, by najpierw spojrzeć.** Akcja wyszukująca i zwracająca
  identyfikatory dobrze łączy się z akcją działającą na jednym z nich - i
  odbiera AI potrzebę zgadywania.
- **Bądź uczciwy co do ryzyka.** Zły `risk` to jedyny błąd, którego użytkownik
  nie cofnie.

## Lista kontrolna

- [ ] `__actions.json` leży w katalogu dodatku
- [ ] każda akcja ma `summary` napisane dla obcego
- [ ] każdy parametr ma `description` i właściwy `type`
- [ ] wszystko, co zapisuje, wysyła lub usuwa, ma co najmniej `risk: confirm`
- [ ] obsługi zwracają zdanie, nie wartość logiczną
- [ ] `serve()` jest obudowane, więc brak Titana nigdy nie psuje dodatku
- [ ] praca na GUI jest przekazana do wątku interfejsu
- [ ] najwyżej dwie-trzy akcje mają `promote: true`

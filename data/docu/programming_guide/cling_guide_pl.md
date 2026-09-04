# Pisanie aplikacji Cling

Cling to podsystem Klango w Titanie. Aplikacja Cling to katalog - albo jeden
plik `.pag` - który Titan czyta, odtwarza i któremu prowadzi wyniki. Celowo ma
dokładnie taki kształt, jaki ma aplikacja Klango, więc aplikacja napisana dla
Klango jest aplikacją Cling bez żadnej zmiany.

Aplikacje mieszkają w `data/cling/`: obok Titana albo - znacznie częściej - w
nakładce użytkownika, czyli tam, gdzie kładzie je **Ustawienia -> Cling ->
Zainstaluj aplikację Klango**.

## Kształt aplikacji

```
mole/
  kni.txt                       czym jest
  __cling__.TCE                 opcjonalnie: jak ma się nazywać w Titanie
  lang/default                  język, na który wszystko się cofa
  lang/pl-pl/default/*.txt      wszystko, co mówi
  skin/default/levels/*.lev     poziomy i topologie, które nazywają
  skin/default/themes/*/*.ogg   jej dźwięki
  main.lua                      opcjonalnie: jej własna logika
```

### `kni.txt`

Manifest Klango, czytany bez zmian:

```
appid=18
appname=mole
summary=Mole No More - whack a mole audio game with 13 levels
version=1.0
minklango=20260803
platform=any
```

Cling czyta dodatkowo `category` (`games`, `edu`, `soundscape`, `network`,
`tools`), `engine` i `entry`. Klucz spoza tej listy jest zgłaszany, a nie
pomijany - żeby linia, której nikt nie czyta, nigdy nie uchodziła za działającą.

### `__cling__.TCE`

Tylko dla aplikacji pisanej pod Titana i tylko na to, czego `kni.txt` powiedzieć
nie umie - nazwa w dwóch językach i wyłączenie:

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

### Co mówi

Jeden plik na jedną rzecz, którą aplikacja może powiedzieć, w
`lang/<język>/default/`, z `%d` i `%s` tam, gdzie wchodzi liczba albo nazwa:

```
welcome.txt           Witaj w Mole No More.
instructions.txt      Ubij tyle kretow, ile zdolasz, w %d sekund.
current_status.txt    PKT: %d
help.txt              <b>Strzalki</b> - ruch po planszy.
klangomenu.txt        Mole No More
```

`klangomenu.txt` to nazwa aplikacji w tym języku i Cling woli ją od każdej
nazwy, którą manifest powtarza po angielsku. Znaczniki (`<b>`, `<u>`) są dla
oka i nigdy nie są wymawiane.

`lang/default` zawiera jedną linię - język zapasowy. Cling rozstrzyga po kolei:
język użytkownika, ten zapasowy, `en-us`, a potem cokolwiek tam jest.

## Pięć silników

Cling sam ustala, który silnik prowadzi aplikację, na podstawie tego, co
naprawdę jest w jej katalogu. Nic nie jest zapisywane i żaden plik nie jest
zmieniany.

| Silnik | Wybierany, gdy | Czym jest |
| --- | --- | --- |
| `script` | `main.lua`, `main.py` albo Cling ma dla niej logikę | aplikacja jest programem |
| `grid_hunt` | `skin/*/levels/*.lev` | plansza, kursor, zegar, coś, co się pojawia i znika |
| `soundscape` | `spec.txt` albo `data/*.ogg` | miejsce, po którym się chodzi |
| `instrument` | katalog próbek nazwanych klawiszami | klawiatura jako instrument |
| `typing` | lekcje KTouch w `trainings/` | kurs pisania |
| `reader` | cokolwiek innego, co ma słowa | wszystko, co aplikacja mówi, jako lista |

Manifest może nazwać silnik wprost; nazwa, której Cling nie ma, jest odrzucana i
zgłaszana, a nie po cichu zamieniana na inną.

### `grid_hunt` - plik poziomu JEST regułami

```lua
Level = {
  text = "level5_info",     -- co poziom mówi, zanim się zacznie
  topology = "3x3",         -- która plansza, czyli gdzie każde pole JEST
  fields = 9,
  hit_target = 30,          -- ile trzeba trafić, żeby skończyć
  nmole_time = 3,           -- jak długo zwykły czeka (0 = w nieskończoność)
  smole_time = 2.5,
  max_nmoles = 2,           -- ile może być naraz
  max_smoles = 1,
  smole_time_bonus = 2,     -- sekundy, które dokłada specjalny
  time = 60,                -- własne Clinga: ile trwa poziom
}
```

Topologia daje każdemu polu miejsce w obrazie dźwiękowym i to właśnie pozwala
celować bez ekranu:

```lua
Topology = {
  size = { x = 3, y = 3, z = 1 },
  coords = { [1] = { [1] = { [1] = { x=-0.800, y=0.250, z=0.000, f=0 } } } }
}
```

`x` to w poprzek, `y` w głąb, `z` w górę, `f` to przesunięcie wysokości w
centach. Cling przelicza to raz: pole zna swój `pan` (-1..1), `azimuth`,
`elevation`, `gain` i `pitch`. Poziom bez pliku `.top` dostaje równą siatkę.

### `soundscape` - `spec.txt` JEST miejscem

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

Tło lokacji to `data/<nazwa>_bkg.ogg`, a jej nazwa i opis to
`lang/<język>/default/<nazwa>_name.txt` i `<nazwa>_comment.txt`.

### `instrument` - nazwa pliku jest klawiszem

`sounds/<zestaw>/z.wav` gra klawisz `z`. Nazwa kończąca się na `_l` (`q_l.wav`)
zapętla się, a jej klawisz jest przełącznikiem, nie dźwiękiem. Leżący obok
`.info.txt` jest czytany jako opis zestawu.

## Aplikacja z własną logiką

Dołóż `main.lua`. Cling niesie własny interpreter Lua - w samym komponencie, w
`cling/lua/` - więc nic nie trzeba instalować; jeśli w
`data/components/cling/lib/` znajdzie się natywna `lupa`, będzie użyta, a
aplikacja nie ma jak tego odróżnić.

Pięć funkcji, wszystkie opcjonalne:

```lua
function on_start()        -- otwarta
function on_key(key)       -- 'up' 'down' 'left' 'right' 'space' 'enter'
                           -- 'escape' 'a'..'z' '0'..'9' 'f1'..; true gdy użyty
function on_tick(now)      -- wołane często; `now` to sekundy, monotonicznie
function on_stop()         -- zamykana
function status()          -- jedna linia na pasek stanu
function help()            -- co robią klawisze
```

`main.py` działa identycznie, z tym samym obiektem pod nazwą `cling`.

### Host

```lua
-- słowa
cling.say(tekst, pozycja, wysokosc)  pozycja -1 (lewo) .. 1 (prawo)
cling.say_at(tekst, pole)            powiedziane z miejsca na planszy
cling.text(nazwa, ...)               jeden z własnych tekstów aplikacji
cling.show(tekst)                    powiedziane I wpisane do okna

-- dźwięk
cling.play(nazwa, pozycja, glosnosc) najpierw skin, potem motyw Titana;
                                     zawsze pozycjonowane, niezaleznie od
                                     ustawienia stereo Titana - planszy sie
                                     sluchа, zeby celowac
cling.play_at(nazwa, pole, glosnosc) pan, wysokość i odległość naraz
cling.loop(nazwa, pozycja, glosnosc) zwraca uchwyt
cling.stop_sound(uchwyt)  cling.stop_sounds()

-- plansza
cling.board(topologia, kolumny, wiersze)  zbuduj; zwraca liczbę pól
cling.field(numer)                        { index, column, row, pan,
                                            elevation, gain, pitch }
-- zapis
cling.get(klucz, domyslne)  cling.set(klucz, wartosc)
cling.record_score(punkty)  cling.scores()  cling.best()

-- gracz
cling.account()      jego nazwa w Titan-Net
cling.signed_in()    czy Titan-Net jest naprawdę połączony
cling.sign_in()      zaloguj tym, co użytkownik już zapisał; '' gdy się nie da
cling.publish_score(punkty, poziom)  wspólna tabela Titan-Net; bez gwarancji
cling.leaderboard(ile)

-- świat
cling.fetch(url, timeout)   GET po http lub https, do 2 MB
cling.ask(pytanie, domyslne) linia tekstu od gracza

-- reszta
cling.now()  cling.set_status(tekst)  cling.close()
cling.language()  cling.app_name()  cling.log(tekst)
```

Nie ma systemu plików, nie ma jak uruchomić programu i nie ma `require` poza
własnym katalogiem aplikacji: aplikacja przyszła stamtąd, skąd wziął ją
użytkownik.

## Konto

Aplikacja Klango, która chciała konta na wyniki albo na czat, dostaje konto
**Titan-Net** użytkownika i nigdy nie prosi o własne. Zapisy i wyniki są
trzymane na nazwę użytkownika Titan-Net, więc dwie osoby na jednej maszynie mają
swoje. Kto nie jest zalogowany, gra na profilu `local`, który działa bez sieci i
niczego nie traci.

## Pakowanie

Aplikacja wysyłana jest jako jeden plik, tak jak aplikacja Klango:

```bash
python src/scripts/pack_cling.py "data/components/cling/apps/clingdemo" -o clingdemo.pag
python src/scripts/pack_cling.py --unpack clingdemo.pag -o /tmp/podglad
```

Połóż `.pag` w `data/cling/`, a zostanie znaleziony dokładnie jak katalog.
Katalog o tej samej nazwie wygrywa, więc aplikacja, przy której się pracuje,
przykrywa paczkę, którą wysłano. Pakowanie `.TCD` Titana też działa, bo
wyszukiwanie jest Titana.

Własne paczki `.pag` Klango też są czytane - i utajnienie, i kontener - a każdy
plik jest sprawdzany z sumą MD5, którą paczka dla niego niesie. Wystarczy
wrzucić taką paczkę do `data/cling/` i jest aplikacją.

## Akcje

Cling deklaruje akcje jak każdy inny dodatek, więc AI, makro albo inny dodatek
może go prowadzić: `cling.list_applications`, `cling.run`, `cling.details`,
`cling.scores`, `cling.install`, `cling.account`, `cling.status`.

## Dokładanie gatunku

Silnik to gatunek, a zbiór jest otwarty:

```python
from cling import engines

class DartsEngine(engines.Engine):
    def start(self):
        self.running = True
        self.host.show(self.host.text('welcome'))

engines.register('darts', DartsEngine)
```

Aplikacja wpisuje wtedy w manifeście `engine = darts`.

## Testy

`tests/test_cling.py` - uruchamiany wprost. Nic w nich nie otwiera okna, nie gra
dźwiękiem, nie mówi i nie sięga do sieci, a silniki dostają zegar, który test
przesuwa ręcznie, więc cała gra jest rozgrywana w milisekundę.

## Uruchamianie oryginalnych aplikacji Klango

**To jest to, co aplikacja dostaje domyślnie.** Cling ładuje jej WŁASNY kod Lua,
z jej własnego `.pag`, na interpreterze, który sam ze sobą niesie, i uruchamia
oryginalne `main()` Klango; silniki opisane wyżej są awaryjne - dla aplikacji
bez własnego kodu i dla komputera, na którym nie ma biblioteki platformy
Klango. `cling.emulate <nazwa>` mówi, jak daleko doszła i o które funkcje
pytała, a Cling ich nie napisał.

Powierzchnia natywna pod spodem to 310 funkcji - rodziny (`_Sys_`, `_Snd_`,
`_Inp_`, `_Voice_`, `_Dir_`, `_Gfx_`, `_Res_`, `_Net_`) i 120 tych, które
silnik udostępnia zupełnie bez przedrostka (`k_*`, `urlencode`) - a dźwięk,
klawisze i mowa trafiają tam, gdzie wszystko inne w Clingu, więc emulowana
aplikacja jest słyszana głosem wybranym przez użytkownika, w jego motywie
dźwiękowym i umieszczona w przestrzeni tak, jak Cling umieszcza wszystko.

**Dźwięk jest Klango i jest umieszczany tak, jak umieszcza go Klango.**
`pos3d` mówi, gdzie dźwięk jest (x w poprzek, y w głąb, z w pionie), a `freq` -
jak wysoko, w setnych półtonu; `dmin` i `dmax` należą do PRÓBKI i są
przyciętym modelem odwrotnej odległości OpenAL, więc plansza naprawdę ma
głębię, zamiast brzmieć cała na pełnej głośności; `pos3dSlide` to dźwięk, który
wędruje w trakcie odtwarzania - tym jest rzutek przelatujący przed słuchaczem;
sekwencja niesie własne opóźnienia, wyliczone z `sampleTime`; a mowę też można
umieścić w przestrzeni - tak gra mówi każdą z pięciu kości tam, gdzie ta kość
leży.

Trzy szczegóły warto znać, bo łatwo je przeoczyć:

* **Miejsce zapisuje się na dwa sposoby.** `pos3d = {-20, 2, 0}` i
  `pos3d = {x = -1, y = 0.5, z = 0}` znaczą to samo i oba działają. Sama
  biblioteka platformy używa drugiego - i to właśnie ono rozkłada elementy
  menu przed słuchaczem od -60 do +60 stopni.
* **Nazwa próbki bywa względna i bez rozszerzenia.** `k_DirectoryRead` daje
  `name` z obciętym rozszerzeniem, a nazwa zbudowana z niego -
  `sounds/piano/c` - jest szukana w plikach twojej aplikacji po kolei z
  każdym rozszerzeniem dźwiękowym.
* **Grupy dźwięków są drzewem.** `k_SoundPlay` tworzy własną grupę wewnątrz
  aktualnej, więc akcja na grupie - `volMul`, `volMulSlide`, `pause`,
  `resume`, `stop` - obejmuje wszystko, co gra pod nią. Tak ścisza się tło i
  zatrzymuje gra, kiedy otwarty jest dialog, i dostajesz to za darmo,
  używając dialogów samej platformy.

Warto wiedzieć to, zanim napiszesz aplikację, która będzie emulowana:

* **Działa we własnym wątku.** `app:loop()` nie wraca - to JEST gra - więc okno
  podaje jej klawisze i czyta to, co powiedziała. Klatki idą w tempie 60 na
  sekundę, czyli tyle, ile zgłasza `_Sys_GetFPS`.
* **Klawiatura jest ta z Klango, we wszystkich czterech postaciach**: kody skanu
  DirectInput w buforze i w zbiorze wciśniętych oraz wirtualne kody Windows w
  komunikatach klawiszowych. Lewy Alt otwiera menu aplikacji, bo dociera jako
  prawdziwy WM_SYSKEYUP; w menu strzałki w lewo i w prawo przechodzą między
  pozycjami, strzałka w dół wchodzi do podmenu, a Enter wybiera - to interakcja
  Klango, nie Titana.
* **Ustawienia i pomoc Klango to ustawienia i pomoc Titana.** Język, głos i
  motyw dźwiękowy, które proponuje emulowana aplikacja, są Titana - więc menu
  otwiera ustawienia Titana zamiast okna wyboru, które i tak nic by nie
  zmieniło - a Pomoc otwiera pomoc Titana. To, co należy do APLIKACJI, zostaje
  nietknięte: jej własny tekst pomocy, readme, lista zmian, wersja i wyjście.
* **Zamknięcie okna zamyka aplikację.** To, co gra, milknie natychmiast, a to,
  o co aplikacja poprosi później, nie zostanie spełnione - działa we własnym
  wątku i może być o klatkę z tyłu.

* **Aplikacja może być w dwóch miejscach naraz.** Jej kod jest w `.pag`;
  folder obok może mieć to, czego nie ma w pakiecie - lekcje, dodatkowe skiny,
  własne dodatki użytkownika. Oba są montowane jako jedno drzewo, pakiet
  pierwszy.
* **Jest prawdziwa kontrolka tekstowa.** `_Gfx_TxtEdit_*` to bufor z kursorem
  i zaznaczeniem; linia kończy się `\r`, tak jak w Klango, a `SetText2`
  dostaje RTF i zapisuje same słowa.
* **`k_NewHttp` naprawdę pobiera** - `http` i `https`, z limitem i czasem
  oczekiwania, we własnym wątku, więc pętla klatek działa dalej.
  `GetStatusCode` to 0, gdy połączenie w ogóle nie doszło, i -1, gdy zostało
  przerwane.
* **Funkcja natywna, której Cling nie napisał, odpowiada niczym** zamiast być
  nil, a `cling.emulate` ją nazywa. Aplikacja idzie dalej, zamiast zatrzymać
  się na `attempt to call a nil value`.

Serwera klango.net nie ma od lat, więc na wywołania, które tam szły, odpowiada
Cling: kontem jest konto Titan-Net, tabela wyników to własna tabela Clinga w
Titan-Necie, a wszystko, co było tylko w Klango, odpowiada "skończone, nic" -
nigdy nil, bo w następnej linii wołający pyta odpowiedź, czy jest `done()`.

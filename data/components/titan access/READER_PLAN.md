# Plan rozbudowy i stabilizacji Titan Access (2026-10-02)

Pytania projektowe i odpowiedzi: stabilizacja najpierw przez **nadzór i
samonaprawę** (odpowiedź użytkownika). Pozostałe przyjęte jako zalecane:
każda nowa funkcja na Windows i Linuksie od razu; weryfikacja sondami na
żywo na maszynie użytkownika (silnik bez hooka, NVDA nie traci klawiszy);
obszary rozbudowy według wartości: dokumenty, edycja tekstu, kursor
przeglądu, moduły aplikacji.

## Wykonane w tej rundzie

Stabilizacja:
- `log.py` - dziennik `titosoft/Titan/logs/titan_access.log` (rotacja 2 MB),
  także w buildzie skompilowanym, gdzie `print` trafiał donikąd; wszystkie
  komunikaty silnika i hooka idą przez niego; `log.stacks()` zrzuca stosy
  wątków Pythona.
- `supervisor.py` - ping wątku roboczego co 3 s z 4 s cierpliwości; wątek
  martwy = natychmiastowy restart silnika; milczący 3 razy z rzędu = zrzut
  stosu do dziennika i restart; wątek tła stawiany ponownie; liczniki hooka
  natywnego logowane co 2 minuty; po restarcie czytnik mówi, że wrócił.
  Na Linuksie (silnik na wątku głównym) tylko zapis do dziennika.
- `engine.diagnostics()` + Insert+Shift+F1: stan wątków, hooka, nadzorcy,
  ostatnie wypowiedzi, profil - zdanie na głos, całość do dziennika.
- Konsola zgłasza powiadomienie UIA na każdy fragment wyjścia, oznaczone
  jako ważne: zmierzone 47 w sześć sekund, każde czytane z przerwaniem
  („?”, „4”, „*”). `uia_notifications` odrzuca powiadomienia i obszary
  na żywo z procesów terminala (moduł terminala czyta wyjście sam, jako
  wiersze), ogranicza każdego nadawcę do jednego powiadomienia na 0,5 s i
  jednego przerwania na 2 s. Po poprawce: 47 odrzuconych, 0 wypowiedzianych.
- Wcześniej tego dnia: martwa pętla komunikatów (`msg.hwnd`),
  `prePopup` na ramce, pole 0 jako „nie ustawiono”.

Rozbudowa:
- Dokumenty: lista elementów (Insert+F7: łącza, nagłówki, pola, punkty
  orientacyjne, tabele, listy; Enter przenosi kursor), szukanie
  (Insert+Ctrl+F, F3 / Shift+F3), ruch po komórkach tabeli
  (Ctrl+Alt+strzałki przez UIA GridItem/Grid, AT-SPI TableCell/Table).
- Edycja tekstu: zaznaczenie czytane przy Shift+strzałce (co doszło, co
  ubyło), słowo z błędem pisowni (adnotacja UIA), formatowanie w miejscu
  kursora (Insert+F: czcionka, rozmiar, pogrubienie, kursywa,
  podkreślenie; AT-SPI atrybuty tekstu na Linuksie).
- Ustawienia: patrz `SETTINGS_PLAN.md` (jeden schemat, nowe sekcje,
  profile, pierścień, pomoc).

## Następne kroki (nie wykonane)

1. Kursor przeglądu niezależny od fokusu: przegląd płaski ekranu (okno
   wirtualne już jest), kopiowanie przeglądanego tekstu, kliknięcie w
   miejscu kursora przeglądu, zapamiętanie pozycji per okno.
2. Moduły aplikacji: Office/LibreOffice (komentarze, śledzenie zmian),
   terminale (bufor konsoli przez ConPTY/UIA), komunikatory (nowa
   wiadomość jako obszar na żywo), Eksplorator (kolumny szczegółów).
3. Dokumenty: nagłówki kolumn i wierszy tabeli mówione przy ruchu,
   „lista elementów” z filtrem tekstowym, zakładki (ARIA) i role
   niestandardowe.
4. Pomiar opóźnień fokusu (czas od zdarzenia do mowy w dzienniku) i
   przegląd na żywo dublowania i ciszy w popularnych oknach.
5. Diagnostyka hooka pythonowego (gdy DLL nieobecny): licznik klawiszy
   kontra `GetLastInputInfo`, ponowna instalacja hooka.

Testy: `tests/test_titan_access_stability.py`, sondy
`tests/check_titan_access_live.py document|worker`.

UWAGA!!!
Program jest w stadium eksperymentalnym i może nie działać.
Wszelkie uwagi proszę kierować na adres ethanak@polip.com.

I. INSTALACJA

Rozpakuj plik m4win.zip gdziekolwiek, aplikacje będą wewnątrz
utworzonego katalogu. Program nie wymaga żadnych zewnętrznych
komponentów, biblioteki mbrola i lame są dołączone.

II. ODINSTALOWANIE

Usuń katalog który powstał po rozpakowaniu pliku m4win.zip.

III. KILKA UWAG

Milena NIE JEST absolutnie "darmowym zamiennikiem Ivony". Oba systemy
mają swoje wady i zalety, nikt nikogo nie zmusza do używania jednego
czy drugiego. Jeśli komuś Milena nie odpowiada - proszę wrócić do
punktu II i zapomnieć o istnieniu programu.

IV. Aplikacje

1) milena.exe

dokładny odpowiednik programu "milena" dla Linuksa.
Służy do konwersji tekstu na fonemy rozumiane przez Mbrolę
lub ortograficzny tekst dla Ivony (w ISO-2). Przeznaczony przede
wszystkim do eksperymentów.

2) milena4w.exe

kompletny konwerter tekstu na mp3. Jest to aplikacja
konsolowa, ale zachowująca się w sposób w miarę przyjazny również
dla użytkownika który na temat konsoli nie ma pojęcia.

Program przyjmuje następujące opcje:

-h	wyświetlenie krótkiej pomocy

-o      pozwala na nadpisywanie istniejących plikow MP3

-I      pomija akcenty i separatory w tekście. Ponieważ konwersja
        z UTF-8 może spowodować wygenerowanie separatorów,
        lepiej nie stosować tej opcji.

-L xx   dodaje reguły dla wyrazów obcych w danym języku.
        Dopuszczalne są: en (angielski), fr (francuski),
        de (niemiecki), ru (rosyjski), se (szwedzki),
        pt (portugalski), ro (rumuński), it (włoski),
        es (hiszpański) i hu (węgierski).
        
-t xx   dodaje reguły związane z danym tematem. Dopuszczalne są:
        manhtt - reguły uwzględniające numerowane ulice
                 (np. na Manhattanie)
        scifi  - reguły uwzględniające popularne słowa science-fiction
        wojsko - reguły uwzględniające terminologię wojskową
                 oraz rozszerzające rozpoznawanie skrótów
                 stopni wojskowych "gen." i "por.".
                 

-U      nie próbuje wczytywać domyślnego słownika. Domyślny słownik
        w przypadku pojedynczego pliku to plik z identyczną nazwą
        lecz rozszerzeniem .dic, w przypadku katalogu powinien to być
        jedyny występujący w tym katalogu plik z rozszerzeniem .dic
        
-u      wczytuje dodatkowy plik slownika
        
-f      wczytuje dodatkowy plik frazera (tylko do eksperymentów)

-z      alternatywna interpretacja wielokropka (rzadko potrzebna)

-c dd   kontrast audio (0..100)
-r dd   tempo wymowy (0.5..1.0, domyslnie 0.8)
-p dd   wysokosc glosu (0.5..2.0, domyslnie 0.9)

-b nn   bitrate dla konera mp3 (dopuszczalne 32, 48 i 64)

-d      operacja na wszystkich plikach txt w danym katalogu.

Włączenie kontrastu audio spowoduje zwiększenie głośności (bez
zmiany amplitudy!) oraz wyrówna częściowo wahania głośności
spowodowane niezbyt dobrą jakością polskiego głosu. Jednocześnie
zwiększą się jednak zniekształcenia. Ogólnie - odtwarzając
nagrania na niskiej jakości sprzęcie (netbook z piszczykami
udającymi głośniki) lub w warunkach wysokiego natężenia poziomu
tła (słuchawkowy odtwarzacz mp3 używany na ruchliwej ulicy)
należy zmaksymalizować kontrast do 100. W innych warunkach
stopień kontrastu należy ustalić indywidualnie.

Wartość "tempo" oznacza mnożnik czasu trwania wypowiedzi, czyli
tempo 0.5 będzie dwukrotnie szybsze od tempa 1.0.

Włączenie nadpisywania spowoduje, że istniejące pliki MP3 zostaną
utworzone jeszcze raz. Jeśli nadpisywanie nie zostanie włączone,
przy konwersji pojedynczego pliku zostanie zadane pytanie o naspisanie.
Przy konwersji całego katalogu istniejące już pliki MP3 zostaną
pozostawione bez zmian.

W trybie katalogu program może przyjąć dodatkowy parametr, oznaczający
nazwę katalogu z plikami txt. Brak parametru spowoduje wyświetlenie
okna dialogowego wyboru katalogu. Pliki MP3 będa utworzone w tym samym
katalogu, z rozszerzeniem .mp3 zamiast .txt.

W trybie pojedynczego pliku program może przyjąć jeden lub dwa parametry,
oznaczające nazwę pliku wejściowego txt oraz wynikowego mp3.
Jeśli nie podano nazwy pliku wynikowego, zostanie przyjęta nazwa pliku
wejściowego z rozszerzeniem zmienionym na mp3. Jeśli nie podano
żadnej nazwy, zostaną wyświetlone okna dialogowe wyboru pliku
wejściowego i wynikowego.

Jeśli nie podano żadnych parametrów sterujących wymową (-L, -t, -u, -f),
a wczytywany jest domyślny słownik, parametry -L i -t będą odtworzone
na podstawie pierwszych linii słownika.

Teksty wejściowe mogą być w kodowaniu ISO-8859-2, CP-1250 lub UTF-8, jednak
wewnętrznie program operuje na ISO-8859-2, stąd niektóre litery nie występujące
w ISO-2 mogą być zamienione na ich odpowiedniki fonetyczne (np. "æ" na "ae",
"ø" na "ö") lub wizualne (np. "å" na "ă", "ñ" na "ň").

Załączony plik "_config.cfg" jest przykładowym plikiem konfiguracji.
Program wczytuje plik konfiguracji (o ile istnieje) przy starcie i ustawia
domyślne wartości tempa, wysokości, kontrastu i bitrate  oraz domyślny
edytor dla programów dykcjon i antidash. Aby to zadziałało, należy zmienić
nazwę pliku na "config.cfg".

3) dykcjon.exe

Program służy do tworzenia słowników wymowy dla danego pliku tekstowego.
Przyjmuje następujące parametry:

-h	wyświetlenie krótkiej pomocy

-o      nadpisuje plik słownika .dic bez pytania

-L xx   dodaje reguły dla wyrazów obcych w danym języku.
        Dopuszczalne są: en (angielski), fr (francuski),
        de (niemiecki), ru (rosyjski), se (szwedzki),
        pt (portugalski), ro (rumuński), it (włoski),
        es (hiszpański) i hu (węgierski).
        
-t xx   dodaje reguły związane z danym tematem. Dopuszczalne są:
        manhtt - reguły uwzględniające numerowane ulice
                 (np. na Manhattanie)
        scifi  - reguły uwzględniające popularne słowa science-fiction
        wojsko - reguły uwzględniające terminologię wojskową
                 oraz rozszerzające rozpoznawanie skrótów
                 stopni wojskowych "gen." i "por.".
        
-u      wczytuje dodatkowy plik slownika
        
-f      wczytuje dodatkowy plik frazera (tylko do eksperymentów)


Jeśli nie zostanie podana nazwa pliku wejściowego, zostanie wyświetlone
odpowiednie okno dialogowe. Nazwa pliku wynikowego to zawsze nazwa
taka sama jak pliku wejściowego z rozszerzeniem zmienionym na .dic.
Wynikowy plik zawiera:
- informacje o językach i tematach jakich użył program
- dwie listy słów: słowa o nieznanej wymowie oraz słowa, które
  co prawda są zpisane jako "znane", lecz ich wymowa może być
  inna. Przy każdym słowie podana jest ilośc wystąpień oraz
  wymowa w EPN-PL.
Program automatycznie uruchamia edytor (domyślinie jest to notepad,
można to zmienić w pliku config.cfg).

Wszystkich reguł słownika nie będę tutaj zamieszczać, podam jedynie najważniejsze:

a) każda linia stanowi opis pojedynczego słowa (w rezeczywistości grupy słów,
   lecz dla uproszczenia taką możliwość pominę)
b) ciąg "//" (dwa znaki slash) rozpoczynają komentarz
c) każda linia składa się ze słowa oraz wymowy.
d) Dopasowanie słowa zależy częściowo od wielkości liter. Jeśli w słowniku
   występuje wielka litera, będzie ona pasować wyłącznie do wielkiej
   litery w treści. Mała litera w słowniku pasuje do wielkiej lub małej
   litery w treści.
e) wymowa zawiera ortograficzny tekst składający się wyłącznie z małych
   liter polskiego alfabetu, znaku '@' oznaczającego schwa, kilku liter
   ujednoznaczniających zapis (š, č) oraz modyfikatorów. Dodatkowo
   po spacji może być dodany ciąg $1, $2 lub $3 (oznaczający położenie
   akcentu głównego na n-tej sylabie od końca).
   Modyfikatory to:
   ~! - akcent główny na najbliższej samogłosce
   ~, - akcent pomocniczy na najbliższej samogłosce
   ~' - separator wymuszający wymowę poprzedniej litery niezależną
        od następnej
   
   Dopuszczalny jest też skrót $S (wtedy nie należy podawać wymowy)
   
Przykładowe linie:

Jimmie dżimi   // tylko wymowa
Bateau bato $1 // akcent będzie na pierwszej sylabie od końca
Psi ps~'i      // "s" nie będzie zmiękczone
Nba $S // zostanie potraktowany jako skrótowiec

Opis pełnego formatu w pliku README_dic.txt

4) antidash.exe

Prosty program pozwalający na łatwe operowanie błędnymi myślnikami w treści
(opis w przygotowaniu)

Przyjemnego słuchania :)

ethanak@polip.com

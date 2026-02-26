FORMAT PLIKU SŁOWNIKA UŻYTKOWNIKA

W czasie wczytywania pliku (lub plików) zawsze najważniejsza jest ostatnia
pasująca linia (tzn. wzorce dopasowania pobierane są od ostatniego). Pozwala
to na łatwe nadpisywanie już wczytanych wzorców poprzez wpisanie pasującego
do istniejącej już konstrukcji wzorca w następnym pliku.

Linie słownika mają postać:

wzorzec wymowa

gdzie wymowa może zawierać:
	tekst na który ma być przetłumaczony wzorzec
	flagi

Flagi rozpoczynają się znakiem $ i powinny być stosowane wyłacznie
w przypadku, gdy przetłumaczony tekst jest pojedynczym słowem
W przeciwnym przypadku należy stosować sekwencje informacyjne
w tłumaczeniu.

Komentarze rozpoczynają się ciągiem znaków // i kończą się wraz z końcem
linii.

POSTAĆ WZORCA

Wzorzec stanowi ciąg znaków nie zawierający spacji, który będzie dopasowany
do wejściowego tekstu. Dopasowywany jest na początku słowa, dopasowany
tekst musi kończyć się na granicy słowa.

We wzorcu mogą występować następujące znaki:

a) mała litera - dopasowanie do małej lub dużej litery
b) duża litera - dopasowanie do dużej litery
c) cyfra lub znak przestankowy - dopasowanie do konkretnego znaku
d) znak "_" (podkreślenie) - oznaczający opcjonalne wystąpienie spacji
d) znak "+" (plus) - oznaczający wystąpienie co najmniej jednej spacji
e) znak "`" (odwrotny apostrof) - oznaczający opcjonalne wystąpienie apostrofu
f) znak "~" (tylda) - oznaczający opcjonalne wystąpienie myślnika i/lub spacji
g) ciąg liter w nawiasach kwadratowych - oznaczający dopasowanie do dowolnej
   litery z ciągu
   
   Przykład: ren[eé] pasuje do "rene" i "rené"
   
h) ciąg możliwości zawarty w nawiasach okrągłych oddzielony znakiem "|",
   oznaczający dopasowanie do najdłuższej pasującej możliwości.
   
   Przykład: john(a|owi|) pasuje do "johna", "johnowi" i "john"

i) "*" (gwiazdka) - oznaczający dopasowanie do reszty liter aż do końca wyrazu.
   Nie należy stosować w słowniku głównym.
   
Wzorzec musi rozpoczynać się literą lub cyfrą. Po znaku "*" nie może wystąpić
litera. Kończącym znakiem nie może być "_" ani "+".

FLAGI

Aktualnie rozpoznawane są następujące flagi:

<cyfra> - ustalenie akcentu na n-tej sylabie od końca
+<cyfra> - ustalenie akcentu pomocniczego na n-tej sylabie od początku
S - wyraz jest skrótowcem i ma być przeliterowany
u - wyraz nie jest akcentowany
v - wyraz jest czasownikiem
o - wyraz jest czasownikiem posiłkowym (nieakcentowanym)

We flagach można podać co najwyżej jedną literę!

Przykłady:

// Słowo "DNA" będzie odczytane jako "de~'en~!a", ale "Dna" nie
DNA $S

// "waszyngton" będzie akcentowany na trzeciej sylabie od końca
waszyngton $3

// słowo "znoł" będzie potraktowane jako czasownik i w połączeniu
// z poprzedzającym "nie" będzie wymawiane jako "ni~!e znoł"
znoł $v

TEKST WYNIKOWY

Tekst wynikowy jest tekstem, który zastąpi dopasowany wzorzec. Może
zawierać znaki akceptowane przez następną fazę, czyli:

małe litery języka polskiego oraz spacje
znak '@' oznaczający "schwa" (przydatny w translacji anglojęzycznych
	słów, np: merp@l, bit@ls)
znak %, oznaczający wynik korespondującego we wzorcu dopasowania
	do możliwości w nawiasach lub gwiazdki. Jeśli po znaku % nastąpi
	cyfra, brany będzie pod uwagę n-ty wynik.

Tekst może zawierać również sekwencje sterujące wymową:

~! - oznaczający akcent główny na następnej samogłosce
~, - oznaczający akcent pomocniczy na następnej samogłosce
~' - oznaczający zmianę wymowy głoski (dawniej separator)
~+ - oznaczający przedłużenie poprzedzającej samogłoski

Przykłady:

s~'ingapur (brak zmiękczenia 's')
w~!aszyngton (akcent na podanej sylabie)

Każdy wyraz tekstu może być poprzedzony informacjami o wymowie zawartymi
w nawiasach klamrowych oraz informacjami o akcentowaniu, zawartymi
w nawiasach kwadratowych. Z informacji o wymowie powinno się stosować
wyłącznie "{v}" oznaczające czasownik, chociaż stosowanie nawet tego
nie jest zalecane.

Przykład:

po+raz [n]poraz

Plik data/pl_udict.dat może stanowić źródło przykładów.

# Przewodnik tworzenia widgetów Titan

## Wprowadzenie

Widgety Titan to interaktywne komponenty dostępne w niewidzialnym interfejsie, które umożliwiają programistom tworzenie własnych funkcjonalności. System obsługuje dwa typy widgetów: **button** (przycisk) i **grid** (siatka).

## Architektura systemu widgetów

### Lokalizacja widgetów
Wszystkie widgety znajdują się w katalogu `data/applets/`. Każdy widget to osobny katalog zawierający:
- `main.py` lub `init.py` - główny plik z kodem widgetu
- `applet.json` (opcjonalnie) - metadane widgetu w nowym systemie

### Klasa bazowa BaseWidget

Titan udostępnia klasę bazową `BaseWidget` w `invisibleui.py`:

```python
class BaseWidget:
    def __init__(self, speak_func):
        self.speak = speak_func
        self.view = None
    
    def speak_with_position(self, text, position=0.0, pitch_offset=0):
        """Wypowiada tekst z pozycjonowaniem stereo"""
        self.speak(text, position=position, pitch_offset=pitch_offset)
    
    def set_border(self):
        """Ustawia obramowanie widgetu (dla GUI)"""
        pass
    
    def get_current_element(self):
        """Zwraca opis aktualnego elementu - WYMAGANE"""
        raise NotImplementedError
    
    def navigate(self, direction):
        """Nawigacja w widgecie - WYMAGANE dla typu 'grid'"""
        raise NotImplementedError
    
    def activate_current_element(self):
        """Aktywuje aktualny element - WYMAGANE"""
        raise NotImplementedError
```

## Typy widgetów

### 1. Widget typu "button"

Prosty widget jednokrotnego użycia, który wykonuje akcję po aktywacji.

**Przykład implementacji:**
```python
class WidgetButton:
    def __init__(self, speak_func, view=None):
        self.speak = speak_func
        self.view = view

    def activate_current_element(self):
        """Aktywuje widget"""
        self.speak("Przykładowy przycisk aktywowany!")
        # Wykonaj akcję
        
    def get_current_element(self):
        """Zwraca nazwę przycisku"""
        return "Przykładowy przycisk"

def get_widget_info():
    return {
        "name": "Mój przycisk",
        "type": "button",
    }

def get_widget_instance(speak_func, view=None):
    return WidgetButton(speak_func, view)
```

### 2. Widget typu "grid"

Interaktywny widget umożliwiający nawigację w różnych kierunkach.

**Przykład implementacji:**
```python
from invisibleui import BaseWidget

class WidgetGrid(BaseWidget):
    def __init__(self, speak_func, view=None):
        super().__init__(speak_func)
        self.view = view
        self.grid = [
            ["Góra-Lewo", "Góra-Prawo"],
            ["Dół-Lewo", "Dół-Prawo"]
        ]
        self.current_pos = [0, 0]  # [wiersz, kolumna]

    def navigate(self, direction):
        """Nawigacja po siatce"""
        rows = len(self.grid)
        cols = len(self.grid[0]) if self.grid else 1
        old_pos = self.current_pos[:]
        
        if direction == 'up' and self.current_pos[0] > 0:
            self.current_pos[0] -= 1
        elif direction == 'down' and self.current_pos[0] < rows - 1:
            self.current_pos[0] += 1
        elif direction == 'left' and self.current_pos[1] > 0:
            self.current_pos[1] -= 1
        elif direction == 'right' and self.current_pos[1] < cols - 1:
            self.current_pos[1] += 1
        else:
            return False, self.current_pos[1], cols  # Osiągnięto krawędź
        
        # Zwróć sukces i pozycję dla stereo pozycjonowania
        return True, self.current_pos[1], cols

    def activate_current_element(self):
        """Aktywuje aktualny element"""
        element = self.get_current_element()
        
        # Użyj pozycjonowania stereo
        cols = len(self.grid[0]) if self.grid else 1
        position = (self.current_pos[1] / (cols - 1) * 2.0) - 1.0 if cols > 1 else 0.0
        
        self.speak_with_position(f"Aktywowano: {element}", position=position)
        
    def get_current_element(self):
        """Zwraca aktualny element"""
        return self.grid[self.current_pos[0]][self.current_pos[1]]

def get_widget_info():
    return {
        "name": "Przykładowa siatka",
        "type": "grid",
    }

def get_widget_instance(speak_func, view=None):
    return WidgetGrid(speak_func, view)
```

## Metadane widgetu (applet.json)

Nowy system pozwala na definiowanie metadanych w pliku `applet.json`:

```json
{
    "name_pl": "Mój widget",
    "name_en": "My Widget", 
    "description_pl": "Opis widgetu po polsku",
    "description_en": "Widget description in English",
    "version": "1.0.0",
    "author": "Twoje imię",
    "type": "grid"
}
```

## Funkcje stereo pozycjonowania

### speak_with_position()
Dziedzicząc z `BaseWidget`, masz dostęp do metody `speak_with_position()`:

```python
self.speak_with_position(text, position=0.0, pitch_offset=0)
```

**Parametry:**
- `text` - tekst do wypowiedzenia
- `position` - pozycja stereo: -1.0 (lewo) do 1.0 (prawo), 0.0 = środek  
- `pitch_offset` - zmiana wysokości głosu: -10 do +10

### Automatyczne pozycjonowanie

System automatycznie pozycjonuje mowę na podstawie zwracanych wartości z `navigate()`:
- Nawigacja lewo/prawo używa pozycjonowania stereo
- Nawigacja góra/dół używa zmiany wysokości głosu

## Wymagane metody

### get_widget_info()
**Wymagana funkcja** na poziomie modułu:
```python
def get_widget_info():
    return {
        "name": "Nazwa widgetu",
        "type": "button" # lub "grid"
    }
```

### get_widget_instance()
**Wymagana funkcja** na poziomie modułu:
```python
def get_widget_instance(speak_func, view=None):
    return MojWidget(speak_func, view)
```

### get_current_element()
**Wymagana metoda** klasy widgetu - zwraca opis aktualnego elementu.

### activate_current_element()
**Wymagana metoda** klasy widgetu - wykonuje akcję aktywacji.

### navigate() (tylko dla typu "grid")
**Wymagana metoda** dla widgetów typu "grid":
```python
def navigate(self, direction):
    # direction: 'up', 'down', 'left', 'right'
    # Zwróć: (success, horizontal_index, total_horizontal_items)
    return True, current_column, total_columns
```

## Struktura katalogów

### System legacy (init.py)
```
data/applets/moj_widget/
├── init.py              # Główny plik widgetu
```

### System nowy (main.py + applet.json)
```
data/applets/moj_widget/
├── main.py              # Główny plik widgetu
├── applet.json          # Metadane widgetu
├── babel.cfg            # Konfiguracja tłumaczeń (opcjonalnie)
└── languages/           # Tłumaczenia (opcjonalnie)
    ├── messages.pot
    ├── pl/
    └── en/
```

## Internacjonalizacja

### Dodawanie tłumaczeń

1. Utwórz `babel.cfg`:
```ini
[python: **.py]
```

2. W kodzie używaj funkcji `_()`:
```python
import gettext
import os

# Setup translations
domain = 'moj_widget'
localedir = os.path.join(os.path.dirname(__file__), 'languages')
try:
    translation = gettext.translation(domain, localedir, fallback=True)
    _ = translation.gettext
except Exception:
    _ = lambda x: x

# W kodzie
self.speak(_("Text to translate"))
```

3. Wyciągnij teksty do tłumaczenia:
```bash
pybabel extract -o messages.pot --input-dirs=.
```

4. Utwórz pliki tłumaczeń:
```bash
pybabel init -l pl -d languages -i messages.pot
pybabel init -l en -d languages -i messages.pot
```

5. Skompiluj tłumaczenia:
```bash
pybabel compile -d languages
```

## Praktyczne przykłady

### Przykład 1: Widget zegara
```python
import datetime
from invisibleui import BaseWidget

class ClockWidget(BaseWidget):
    def __init__(self, speak_func, view=None):
        super().__init__(speak_func)
        self.view = view
        
    def get_current_element(self):
        now = datetime.datetime.now()
        return f"Godzina: {now.strftime('%H:%M:%S')}"
        
    def activate_current_element(self):
        self.speak(self.get_current_element())

def get_widget_info():
    return {"name": "Zegar", "type": "button"}

def get_widget_instance(speak_func, view=None):
    return ClockWidget(speak_func, view)
```

### Przykład 2: Widget kalkulatora prostego
```python
from invisibleui import BaseWidget

class SimpleCalculator(BaseWidget):
    def __init__(self, speak_func, view=None):
        super().__init__(speak_func)
        self.view = view
        self.operations = [
            ["1 + 1 = 2", "2 + 2 = 4", "3 + 3 = 6"],
            ["5 * 5 = 25", "10 / 2 = 5", "2^3 = 8"]
        ]
        self.current_pos = [0, 0]
        
    def navigate(self, direction):
        rows = len(self.operations)
        cols = len(self.operations[0])
        
        if direction == 'up' and self.current_pos[0] > 0:
            self.current_pos[0] -= 1
        elif direction == 'down' and self.current_pos[0] < rows - 1:
            self.current_pos[0] += 1
        elif direction == 'left' and self.current_pos[1] > 0:
            self.current_pos[1] -= 1
        elif direction == 'right' and self.current_pos[1] < cols - 1:
            self.current_pos[1] += 1
        else:
            return False, self.current_pos[1], cols
        
        return True, self.current_pos[1], cols
        
    def get_current_element(self):
        return self.operations[self.current_pos[0]][self.current_pos[1]]
        
    def activate_current_element(self):
        element = self.get_current_element()
        self.speak(f"Wybrany przykład: {element}")

def get_widget_info():
    return {"name": "Prosty kalkulator", "type": "grid"}

def get_widget_instance(speak_func, view=None):
    return SimpleCalculator(speak_func, view)
```

## Testowanie widgetów

1. Umieść widget w katalogu `data/applets/nazwa_widgetu/`
2. Uruchom Titan
3. Przejdź do niewidzialnego interfejsu (Ctrl+Shift+strzałki)
4. Nawiguj do kategorii "Widgets"
5. Wybierz swój widget i przetestuj funkcjonalność

## Najważniejsze wskazówki

1. **NIE** używaj `self.speak()` w metodzie `navigate()` - system automatycznie obsługuje mowę z pozycjonowaniem
2. Wykorzystuj `speak_with_position()` w `activate_current_element()` dla lepszego doświadczenia
3. Zawsze implementuj wszystkie wymagane metody
4. Testuj nawigację we wszystkich kierunkach
5. Dodaj obsługę błędów w przypadku nieprawidłowych danych
6. Używaj internacjonalizacji dla lepszej dostępności

## Dostępne narzędzia

- `self.speak()` - podstawowa mowa TTS
- `self.speak_with_position()` - mowa z pozycjonowaniem stereo
- `play_sound()` - odtwarzanie dźwięków (importuj z `sound`)
- System ustawień (importuj z `settings`)
- Dostęp do głównej ramki aplikacji przez `self.view`

Titan zapewnia bogate API do tworzenia własnych, dostępnych widgetów z pełnym wsparciem dla użytkowników czytników ekranu.
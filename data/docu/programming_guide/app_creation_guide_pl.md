# Przewodnik tworzenia aplikacji Titan

## Wprowadzenie

Aplikacje Titan to samodzielne programy uruchamiane z poziomu launchera. Mogą to być aplikacje w Pythonie, skompilowane pliki wykonywalne (.exe) lub inne typy plików wykonywalnych. Aplikacje są wyświetlane w kategorii "Aplikacje" w niewidzialnym interfejsie.

## Architektura systemu aplikacji

### Lokalizacja aplikacji
Wszystkie aplikacje znajdują się w katalogu `data/applications/`. Każda aplikacja to osobny katalog zawierający:
- `__app.tce` - plik konfiguracyjny aplikacji (wymagany)
- `main.py` - główny plik aplikacji (lub inny plik określony w openfile)
- dodatkowe pliki i zasoby aplikacji

### Proces uruchamiania aplikacji

1. **Kompilacja** - pliki .py są automatycznie kompilowane do .pyc
2. **Środowisko** - ustawiane są ścieżki PYTHONPATH i zmienne środowiskowe
3. **Uruchomienie** - aplikacja uruchamiana w osobnym procesie
4. **Izolacja** - każda aplikacja działa w swoim katalogu roboczym

## Struktura pliku konfiguracyjnego

### __app.tce
Plik w formacie klucz=wartość:

```
name_pl=Nazwa aplikacji po polsku
name_en=Application name in English
openfile=main.py
shortname=myapp
hidden=false
```

**Wymagane parametry:**
- `openfile` - nazwa pliku do uruchomienia

**Opcjonalne parametry:**
- `name_pl` - nazwa po polsku
- `name_en` - nazwa po angielsku  
- `name` - nazwa domyślna (jeśli brak tłumaczeń)
- `shortname` - krótka nazwa dla wywołań programowych
- `hidden` - czy ukryć aplikację w liście (true/false)

## Implementacja aplikacji Python

### Podstawowa struktura main.py

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import wx
import sys
import os

class MyAppFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Moja aplikacja")
        self.InitUI()
        self.Center()
        
    def InitUI(self):
        """Inicjalizacja interfejsu użytkownika"""
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Dodaj kontrolki
        self.text_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE)
        vbox.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        # Przycisk
        btn = wx.Button(panel, label="Kliknij mnie")
        btn.Bind(wx.EVT_BUTTON, self.OnButtonClick)
        vbox.Add(btn, 0, wx.ALL | wx.CENTER, 5)
        
        panel.SetSizer(vbox)
        
    def OnButtonClick(self, event):
        """Obsługa kliknięcia przycisku"""
        self.text_ctrl.AppendText("Przycisk został kliknięty!\n")

class MyApp(wx.App):
    def OnInit(self):
        frame = MyAppFrame()
        frame.Show()
        return True

if __name__ == '__main__':
    app = MyApp()
    app.MainLoop()
```

### Dostęp do modułów Titan

Aplikacje mają automatyczny dostęp do modułów Titan:

```python
# Import modułów Titan
from sound import play_sound, play_error_sound
from settings import get_setting, set_setting
from translation import get_available_languages

# Użycie w aplikacji
def on_action(self):
    play_sound("focus.ogg")
    
    # Zapisz ustawienie aplikacji
    set_setting('my_app_setting', 'value', section='my_app')
    
    # Odczytaj ustawienie
    value = get_setting('my_app_setting', 'default', section='my_app')
```

## Obsługa argumentów wiersza poleceń

Aplikacje mogą otrzymywać argumenty podczas uruchamiania:

```python
import sys

def main():
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        print(f"Otrzymano ścieżkę pliku: {file_path}")
        # Otwórz plik w aplikacji
        open_file(file_path)
    else:
        # Uruchom normalnie bez argumentów
        start_normal_mode()

if __name__ == '__main__':
    main()
```

## Internacjonalizacja aplikacji

### Konfiguracja babel.cfg
```ini
[python: **.py]
```

### Struktura tłumaczeń
```
data/applications/moja_aplikacja/
├── main.py
├── __app.tce
├── babel.cfg
├── languages/
│   ├── messages.pot
│   ├── pl/
│   │   └── LC_MESSAGES/
│   │       ├── messages.po
│   │       └── messages.mo
│   └── en/
│       └── LC_MESSAGES/
│           ├── messages.po
│           └── messages.mo
└── translation.py
```

### Plik translation.py
```python
import gettext
import os

def setup_translation():
    """Konfiguruje tłumaczenia dla aplikacji"""
    # Pobierz język z zmiennej środowiskowej ustawionej przez Titan
    lang = os.environ.get('LANG', 'pl')
    
    domain = 'messages'
    localedir = os.path.join(os.path.dirname(__file__), 'languages')
    
    try:
        translation = gettext.translation(domain, localedir, languages=[lang], fallback=True)
        translation.install()
        return translation.gettext
    except Exception as e:
        print(f"Błąd konfiguracji tłumaczeń: {e}")
        return lambda x: x

# Użycie w aplikacji
_ = setup_translation()

# W kodzie aplikacji
title = _("My Application")
message = _("Hello, world!")
```

### Polecenia babel
```bash
# Wyciągnij teksty do tłumaczenia
pybabel extract -o languages/messages.pot --input-dirs=.

# Utwórz pliki tłumaczeń
pybabel init -l pl -d languages -i languages/messages.pot
pybabel init -l en -d languages -i languages/messages.pot

# Aktualizuj istniejące tłumaczenia
pybabel update -l pl -d languages -i languages/messages.pot
pybabel update -l en -d languages -i languages/messages.pot

# Skompiluj tłumaczenia
pybabel compile -d languages
```

## Przykłady aplikacji

### Przykład 1: Prosty edytor tekstu
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import wx
import os

class TextEditorFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Edytor tekstu", size=(600, 400))
        self.current_file = None
        self.InitUI()
        self.Center()
        
    def InitUI(self):
        # Menu
        menubar = wx.MenuBar()
        
        file_menu = wx.Menu()
        file_menu.Append(wx.ID_NEW, "&Nowy\tCtrl+N")
        file_menu.Append(wx.ID_OPEN, "&Otwórz\tCtrl+O")
        file_menu.Append(wx.ID_SAVE, "&Zapisz\tCtrl+S")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "&Wyjście\tCtrl+Q")
        
        menubar.Append(file_menu, "&Plik")
        self.SetMenuBar(menubar)
        
        # Obszar tekstu
        self.text_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        
        # Pasek stanu
        self.statusbar = self.CreateStatusBar()
        self.statusbar.SetStatusText("Gotowy")
        
        # Zdarzenia
        self.Bind(wx.EVT_MENU, self.OnNew, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.OnOpen, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self.OnSave, id=wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self.OnExit, id=wx.ID_EXIT)
        
    def OnNew(self, event):
        self.text_ctrl.Clear()
        self.current_file = None
        self.SetTitle("Edytor tekstu - Nowy dokument")
        
    def OnOpen(self, event):
        dlg = wx.FileDialog(self, "Otwórz plik", wildcard="Pliki tekstowe (*.txt)|*.txt")
        if dlg.ShowModal() == wx.ID_OK:
            self.current_file = dlg.GetPath()
            with open(self.current_file, 'r', encoding='utf-8') as f:
                self.text_ctrl.SetValue(f.read())
            self.SetTitle(f"Edytor tekstu - {os.path.basename(self.current_file)}")
        dlg.Destroy()
        
    def OnSave(self, event):
        if self.current_file:
            with open(self.current_file, 'w', encoding='utf-8') as f:
                f.write(self.text_ctrl.GetValue())
            self.statusbar.SetStatusText("Plik zapisany")
        else:
            self.OnSaveAs(event)
            
    def OnSaveAs(self, event):
        dlg = wx.FileDialog(self, "Zapisz plik", wildcard="Pliki tekstowe (*.txt)|*.txt", 
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() == wx.ID_OK:
            self.current_file = dlg.GetPath()
            self.OnSave(event)
        dlg.Destroy()
        
    def OnExit(self, event):
        self.Close()

class TextEditorApp(wx.App):
    def OnInit(self):
        frame = TextEditorFrame()
        frame.Show()
        
        # Sprawdź czy przekazano plik do otwarcia
        if len(sys.argv) > 1:
            file_path = sys.argv[1]
            if os.path.exists(file_path):
                frame.current_file = file_path
                with open(file_path, 'r', encoding='utf-8') as f:
                    frame.text_ctrl.SetValue(f.read())
                frame.SetTitle(f"Edytor tekstu - {os.path.basename(file_path)}")
        
        return True

if __name__ == '__main__':
    app = TextEditorApp()
    app.MainLoop()
```

### Przykład 2: Kalkulator
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import wx
import math

class CalculatorFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Kalkulator", style=wx.DEFAULT_FRAME_STYLE & ~wx.RESIZE_BORDER)
        self.InitUI()
        self.Center()
        self.current_value = "0"
        self.previous_value = None
        self.operation = None
        
    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Wyświetlacz
        self.display = wx.TextCtrl(panel, value="0", style=wx.TE_RIGHT | wx.TE_READONLY)
        self.display.SetFont(wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        vbox.Add(self.display, 0, wx.EXPAND | wx.ALL, 5)
        
        # Przyciski
        button_data = [
            ['C', 'CE', '←', '/'],
            ['7', '8', '9', '*'],
            ['4', '5', '6', '-'],
            ['1', '2', '3', '+'],
            ['±', '0', '.', '=']
        ]
        
        for row in button_data:
            hbox = wx.BoxSizer(wx.HORIZONTAL)
            for label in row:
                btn = wx.Button(panel, label=label, size=(50, 40))
                btn.Bind(wx.EVT_BUTTON, self.OnButtonClick)
                hbox.Add(btn, 0, wx.ALL, 2)
            vbox.Add(hbox, 0, wx.CENTER)
            
        panel.SetSizer(vbox)
        self.Fit()
        
    def OnButtonClick(self, event):
        label = event.GetEventObject().GetLabel()
        
        if label.isdigit():
            self.OnNumber(label)
        elif label == '.':
            self.OnDecimal()
        elif label in ['+', '-', '*', '/']:
            self.OnOperation(label)
        elif label == '=':
            self.OnEquals()
        elif label == 'C':
            self.OnClear()
        elif label == 'CE':
            self.OnClearEntry()
        elif label == '←':
            self.OnBackspace()
        elif label == '±':
            self.OnPlusMinus()
            
    def OnNumber(self, digit):
        if self.current_value == "0":
            self.current_value = digit
        else:
            self.current_value += digit
        self.UpdateDisplay()
        
    def OnDecimal(self):
        if '.' not in self.current_value:
            self.current_value += '.'
        self.UpdateDisplay()
        
    def OnOperation(self, op):
        if self.operation and self.previous_value:
            self.OnEquals()
        self.previous_value = float(self.current_value)
        self.operation = op
        self.current_value = "0"
        
    def OnEquals(self):
        if self.operation and self.previous_value is not None:
            current = float(self.current_value)
            try:
                if self.operation == '+':
                    result = self.previous_value + current
                elif self.operation == '-':
                    result = self.previous_value - current
                elif self.operation == '*':
                    result = self.previous_value * current
                elif self.operation == '/':
                    if current != 0:
                        result = self.previous_value / current
                    else:
                        wx.MessageBox("Nie można dzielić przez zero!", "Błąd", wx.OK | wx.ICON_ERROR)
                        return
                        
                self.current_value = str(result)
                self.UpdateDisplay()
                self.operation = None
                self.previous_value = None
            except Exception as e:
                wx.MessageBox(f"Błąd obliczeń: {e}", "Błąd", wx.OK | wx.ICON_ERROR)
                
    def OnClear(self):
        self.current_value = "0"
        self.previous_value = None
        self.operation = None
        self.UpdateDisplay()
        
    def OnClearEntry(self):
        self.current_value = "0"
        self.UpdateDisplay()
        
    def OnBackspace(self):
        if len(self.current_value) > 1:
            self.current_value = self.current_value[:-1]
        else:
            self.current_value = "0"
        self.UpdateDisplay()
        
    def OnPlusMinus(self):
        if self.current_value != "0":
            if self.current_value.startswith("-"):
                self.current_value = self.current_value[1:]
            else:
                self.current_value = "-" + self.current_value
        self.UpdateDisplay()
        
    def UpdateDisplay(self):
        # Formatuj wyświetlanie liczb
        try:
            val = float(self.current_value)
            if val.is_integer():
                display_text = str(int(val))
            else:
                display_text = self.current_value
        except:
            display_text = self.current_value
            
        self.display.SetValue(display_text)

class CalculatorApp(wx.App):
    def OnInit(self):
        frame = CalculatorFrame()
        frame.Show()
        return True

if __name__ == '__main__':
    app = CalculatorApp()
    app.MainLoop()
```

## Aplikacje konsolowe

Możesz też tworzyć aplikacje konsolowe:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os

def main():
    print("=== Moja aplikacja konsolowa ===")
    
    if len(sys.argv) > 1:
        print(f"Otrzymane argumenty: {sys.argv[1:]}")
    
    while True:
        command = input("Wpisz polecenie (help/exit): ").strip().lower()
        
        if command == "exit":
            break
        elif command == "help":
            print("Dostępne polecenia:")
            print("- help: pokazuje tę pomoc")
            print("- exit: kończy program")
        else:
            print(f"Nieznane polecenie: {command}")
    
    print("Koniec programu")

if __name__ == '__main__':
    main()
```

## Aplikacje wykonywalne (.exe)

Możesz także używać skompilowanych aplikacji:

**__app.tce:**
```
name_pl=Moja aplikacja
name_en=My Application
openfile=myapp.exe
```

## Testowanie aplikacji

1. Utwórz katalog w `data/applications/nazwa_aplikacji/`
2. Dodaj `__app.tce` i główny plik aplikacji
3. Uruchom Titan
4. Sprawdź czy aplikacja pojawia się w kategorii "Aplikacje"
5. Przetestuj uruchamianie i funkcjonalność

## Najważniejsze wskazówki

1. **Zawsze dodaj plik __app.tce** - bez niego aplikacja nie będzie widoczna
2. **Testuj z argumentami** - aplikacje mogą otrzymywać pliki do otwarcia
3. **Używaj tłumaczeń** - dodaj wielojęzyczność dla lepszej dostępności
4. **Obsługuj błędy** - dodaj try/catch dla stabilności
5. **Optymalizuj rozmiar** - usuń niepotrzebne pliki z katalogu aplikacji
6. **Dokumentuj ustawienia** - jeśli używasz settings, opisz opcje
7. **Testuj kompilację** - pliki .py są automatycznie kompilowane do .pyc

## Struktura katalogów

```
data/applications/moja_aplikacja/
├── __app.tce           # Konfiguracja aplikacji (wymagane)
├── main.py             # Główny plik aplikacji
├── babel.cfg           # Konfiguracja tłumaczeń (opcjonalnie)
├── languages/          # Tłumaczenia (opcjonalnie)
│   ├── messages.pot
│   ├── pl/
│   └── en/
├── resources/          # Zasoby (opcjonalnie)
│   ├── images/
│   ├── sounds/
│   └── data/
├── modules/            # Dodatkowe moduły (opcjonalnie)
│   └── helpers.py
└── translation.py      # Obsługa tłumaczeń (opcjonalnie)
```

Aplikacje Titan zapewniają prostą platformę do tworzenia niezależnych programów z dostępem do funkcjonalności launchera i pełnym wsparciem dla internacjonalizacji.
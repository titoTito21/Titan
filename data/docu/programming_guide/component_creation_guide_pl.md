# Przewodnik tworzenia komponentów Titan

## Wprowadzenie

Komponenty Titan to rozszerzenia systemu, które działają w tle i mogą dodawać funkcjonalności do głównej aplikacji. Komponenty mogą być włączane i wyłączane przez użytkownika oraz integrować się z menu systemowym.

## Architektura systemu komponentów

### Lokalizacja komponentów
Wszystkie komponenty znajdują się w katalogu `data/components/`. Każdy komponent to osobny katalog zawierający:
- `init.py` - główny plik z kodem komponentu
- `__component__.TCE` - plik konfiguracyjny komponentu

### Cykl życia komponentu

1. **Ładowanie** - komponenty są ładowane przy starcie Titan
2. **Inicjalizacja** - wywoływana metoda `initialize(app)`
3. **Działanie** - komponent działa w tle
4. **Zamykanie** - wywoływana metoda `shutdown()`

## Struktura pliku konfiguracyjnego

### __component__.TCE
Plik INI z sekcją `[component]`:

```ini
[component]
name = Nazwa komponentu
status = 0
```

**Parametry:**
- `name` - nazwa wyświetlana w menedżerze komponentów
- `status` - `0` = włączony, `1` = wyłączony

## Implementacja komponentu

### Podstawowa struktura init.py

```python
# -*- coding: utf-8 -*-
import wx
import threading
import time

class MojKomponent:
    def __init__(self):
        self.running = False
        self.thread = None
    
    def start(self):
        """Uruchamia komponent"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
    
    def stop(self):
        """Zatrzymuje komponent"""
        self.running = False
    
    def _run(self):
        """Główna pętla komponentu"""
        while self.running:
            # Tutaj logika komponentu
            time.sleep(1)

# Globalna instancja komponentu
komponent_instance = None

def initialize(app=None):
    """
    Wywoływane przy inicjalizacji Titan.
    app - instancja głównej aplikacji (opcjonalne)
    """
    global komponent_instance
    komponent_instance = MojKomponent()
    komponent_instance.start()
    print("Komponent zainicjalizowany")

def shutdown():
    """Wywoływane przy zamykaniu Titan"""
    global komponent_instance
    if komponent_instance:
        komponent_instance.stop()
    print("Komponent zamknięty")

def add_menu(component_manager):
    """
    Dodaje pozycje do menu komponentów.
    component_manager - instancja ComponentManager
    """
    component_manager.register_menu_function("Opcja komponentu", moja_funkcja_menu)

def add_settings(settings_frame):
    """
    Dodaje ustawienia do okna konfiguracji.
    settings_frame - ramka ustawień Titan
    """
    # Tutaj można dodać kontrolki do ustawień
    pass

def moja_funkcja_menu():
    """Funkcja wywoływana z menu komponentów"""
    wx.MessageBox("Akcja komponentu wykonana!", "Komponent", wx.OK | wx.ICON_INFORMATION)
```

## Wymagane funkcje

### initialize(app=None)
**Wymagana funkcja** wywoływana przy starcie Titan:
- `app` - instancja głównej aplikacji wxPython (może być None)
- Użyj do inicjalizacji zasobów, uruchamiania wątków

### shutdown() (opcjonalna)
Wywoływana przy zamykaniu Titan:
- Zatrzymaj wątki, zwolnij zasoby
- Zapisz stan komponentu jeśli potrzeba

### add_menu(component_manager) (opcjonalna)
Dodaje pozycje do menu komponentów:
- `component_manager.register_menu_function(nazwa, funkcja)`
- Menu dostępne w niewidzialnym interfejsie

### add_settings(settings_frame) (opcjonalna)
Dodaje kontrolki do okna ustawień:
- `settings_frame` - główne okno ustawień
- Dodaj panele, checkboxy, suwaki itp.

## Przykłady komponentów

### Przykład 1: Monitor systemu
```python
# -*- coding: utf-8 -*-
import psutil
import threading
import time
import wx

class SystemMonitor:
    def __init__(self):
        self.running = False
        self.thread = None
        self.cpu_threshold = 80.0
    
    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._monitor, daemon=True)
            self.thread.start()
    
    def stop(self):
        self.running = False
    
    def _monitor(self):
        while self.running:
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > self.cpu_threshold:
                wx.CallAfter(self._show_warning, cpu_percent)
            time.sleep(5)
    
    def _show_warning(self, cpu_percent):
        message = f"Wysokie użycie CPU: {cpu_percent:.1f}%"
        wx.MessageBox(message, "Ostrzeżenie systemu", wx.OK | wx.ICON_WARNING)

monitor_instance = None

def initialize(app=None):
    global monitor_instance
    monitor_instance = SystemMonitor()
    monitor_instance.start()

def shutdown():
    global monitor_instance
    if monitor_instance:
        monitor_instance.stop()

def add_menu(component_manager):
    component_manager.register_menu_function("Pokaż użycie systemu", show_system_info)

def show_system_info():
    cpu = psutil.cpu_percent()
    memory = psutil.virtual_memory().percent
    message = f"CPU: {cpu}%\nPamięć: {memory}%"
    wx.MessageBox(message, "Informacje systemowe", wx.OK | wx.ICON_INFORMATION)
```

### Przykład 2: Powiadomienia czasowe
```python
# -*- coding: utf-8 -*-
import wx
import threading
import time
from datetime import datetime, timedelta

class TimeNotifier:
    def __init__(self):
        self.running = False
        self.thread = None
        self.notifications = []  # Lista (czas, wiadomość)
    
    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._check_notifications, daemon=True)
            self.thread.start()
    
    def stop(self):
        self.running = False
    
    def add_notification(self, minutes_from_now, message):
        """Dodaje powiadomienie za X minut"""
        notification_time = datetime.now() + timedelta(minutes=minutes_from_now)
        self.notifications.append((notification_time, message))
    
    def _check_notifications(self):
        while self.running:
            now = datetime.now()
            # Sprawdź powiadomienia do pokazania
            to_show = [msg for time, msg in self.notifications if time <= now]
            # Usuń pokazane powiadomienia
            self.notifications = [(t, m) for t, m in self.notifications if t > now]
            
            for message in to_show:
                wx.CallAfter(self._show_notification, message)
            
            time.sleep(10)  # Sprawdzaj co 10 sekund
    
    def _show_notification(self, message):
        wx.MessageBox(message, "Powiadomienie", wx.OK | wx.ICON_INFORMATION)

notifier_instance = None

def initialize(app=None):
    global notifier_instance
    notifier_instance = TimeNotifier()
    notifier_instance.start()
    # Przykładowe powiadomienie za 1 minutę
    notifier_instance.add_notification(1, "To jest testowe powiadomienie!")

def shutdown():
    global notifier_instance
    if notifier_instance:
        notifier_instance.stop()

def add_menu(component_manager):
    component_manager.register_menu_function("Dodaj powiadomienie", add_notification_dialog)

def add_notification_dialog():
    dlg = wx.TextEntryDialog(None, "Wpisz wiadomość powiadomienia:", "Nowe powiadomienie")
    if dlg.ShowModal() == wx.ID_OK:
        message = dlg.GetValue()
        if notifier_instance and message:
            notifier_instance.add_notification(5, message)  # Za 5 minut
            wx.MessageBox("Powiadomienie zostanie pokazane za 5 minut", "Dodano", wx.OK)
    dlg.Destroy()
```

## Integracja z systemem

### Dostęp do głównej aplikacji
```python
def initialize(app=None):
    if app:
        # Dostęp do głównego okna
        main_frame = app.GetTopWindow()
        # Dostęp do menu
        menubar = main_frame.GetMenuBar()
        # Dostęp do statusbar
        statusbar = main_frame.GetStatusBar()
```

### Wywołania bezpieczne dla wątków
```python
# Użyj wx.CallAfter dla operacji GUI z wątków
wx.CallAfter(self._update_ui, data)

def _update_ui(self, data):
    # Kod modyfikujący GUI
    pass
```

### Korzystanie z dźwięków systemu
```python
from sound import play_sound, play_error_sound, play_dialog_sound

def moja_funkcja():
    play_sound("focus.ogg")  # Odtwórz dźwięk z motywu
    play_error_sound()       # Dźwięk błędu
```

### Dostęp do ustawień
```python
from settings import get_setting, set_setting

def initialize(app=None):
    # Odczytaj ustawienie
    enabled = get_setting('my_component_enabled', 'True', section='components')
    
    # Zapisz ustawienie
    set_setting('my_component_value', '42', section='components')
```

## Zarządzanie stanem komponentu

### Włączanie/wyłączanie
Użytkownicy mogą włączać/wyłączać komponenty przez:
1. Menedżer komponentów w GUI
2. Niewidzialny interfejs → Menu → Komponenty

### Trwałość stanu
Stan włączony/wyłączony jest zapisywany w `__component__.TCE`:
```ini
[component]
name = Mój komponent
status = 0  # 0 = włączony, 1 = wyłączony
```

## Struktura katalogów

```
data/components/moj_komponent/
├── init.py              # Główny plik komponentu
├── __component__.TCE    # Konfiguracja komponentu
├── resources/           # Zasoby (opcjonalnie)
│   ├── sounds/
│   └── images/
└── config/              # Pliki konfiguracyjne (opcjonalnie)
    └── settings.ini
```

## Testowanie komponentów

1. Umieść komponent w `data/components/nazwa_komponentu/`
2. Uruchom Titan
3. Sprawdź w menedżerze komponentów czy komponent jest załadowany
4. Testuj funkcjonalność przez menu komponentów

## Najważniejsze wskazówki

1. **Zawsze używaj wątków daemon** - `threading.Thread(daemon=True)`
2. **Obsługuj shutdown()** - zatrzymaj wszystkie wątki
3. **Używaj wx.CallAfter** dla operacji GUI z wątków
4. **Testuj włączanie/wyłączanie** komponentu
5. **Dodaj obsługę błędów** - komponenty nie powinny crashować Titan
6. **Oszczędzaj zasoby** - nie wykonuj ciężkich operacji za często
7. **Dokumentuj funkcje menu** - wyjaśnij co robią

## Debugowanie

### Logi komponentów
```python
import logging

# Skonfiguruj logger
logger = logging.getLogger(__name__)

def initialize(app=None):
    logger.info("Komponent inicjalizowany")
    
def shutdown():
    logger.info("Komponent zamykany")
```

### Obsługa błędów
```python
def initialize(app=None):
    try:
        # Kod inicjalizacji
        pass
    except Exception as e:
        print(f"Błąd inicjalizacji komponentu: {e}")
        # Opcjonalnie pokaż dialog błędu
        wx.MessageBox(f"Błąd komponentu: {e}", "Błąd", wx.OK | wx.ICON_ERROR)
```

Komponenty Titan umożliwiają rozszerzanie funkcjonalności systemu w sposób modularny i bezpieczny. Dzięki prostemu API można łatwo dodawać nowe możliwości bez modyfikowania głównego kodu aplikacji.
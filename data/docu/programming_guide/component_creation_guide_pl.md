# Przewodnik tworzenia komponentów Titan

## Wprowadzenie

Komponenty Titan to rozszerzenia systemu, które działają w tle i mogą dodawać funkcjonalności do głównej aplikacji. Komponenty mogą być włączane i wyłączane przez użytkownika, integrować się z menu systemowym, dodawać własne widoki do głównego interfejsu oraz rozszerzać niewidzialny interfejs i tryb Klango.

## Architektura systemu komponentów

### Lokalizacja komponentów
Wszystkie komponenty znajdują się w katalogu `data/components/`. Każdy komponent to osobny katalog zawierający:
- `init.py` - główny plik z kodem komponentu (NIE `__init__.py`!)
- `__component__.TCE` - plik konfiguracyjny komponentu (format INI)

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
status = 1

```

**Parametry:**
- `name` - nazwa wyświetlana w menedżerze komponentów
- **`status = 1` oznacza WYŁĄCZONY, `status = 0` oznacza WŁĄCZONY** (odwrotnie!)
- **WAŻNE**: Nazwa pliku to `__component__.TCE` (wielkie litery .TCE)
- **WAŻNE**: Główny plik to `init.py` (małe litery, NIE `__init__.py`)
- **WAŻNE**: Dodaj pustą linię na końcu pliku

## Implementacja komponentu

### Podstawowa struktura init.py

```python
# -*- coding: utf-8 -*-
"""
Nazwa komponentu - opis
"""

import os
import sys
import wx
import gettext

# Dodaj katalog komponentu do ścieżki
COMPONENT_DIR = os.path.dirname(__file__)
if COMPONENT_DIR not in sys.path:
    sys.path.insert(0, COMPONENT_DIR)

# Dodaj katalog główny TCE do ścieżki
TCE_ROOT = os.path.abspath(os.path.join(COMPONENT_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

# Importuj moduły TCE
try:
    from src.titan_core.sound import play_sound
    SOUND_AVAILABLE = True
except ImportError as e:
    SOUND_AVAILABLE = False
    print(f"[component_id] Warning: sound module not available: {e}")

try:
    from src.settings.settings import get_setting
    SETTINGS_AVAILABLE = True
except ImportError as e:
    SETTINGS_AVAILABLE = False
    print(f"[component_id] Warning: settings module not available: {e}")
    def get_setting(key, default='', section='general'):
        return default

# Wsparcie tłumaczeń
LANGUAGES_DIR = os.path.join(COMPONENT_DIR, 'languages')

try:
    if SETTINGS_AVAILABLE:
        lang = get_setting('language', 'pl')
    else:
        lang = 'pl'

    translation = gettext.translation('component_id', localedir=LANGUAGES_DIR, languages=[lang], fallback=True)
    translation.install()
    _ = translation.gettext
except Exception as e:
    print(f"[component_id] Translation loading failed: {e}")
    def _(text):
        return text


class MyComponent:
    """Główna klasa komponentu"""

    def __init__(self):
        """Inicjalizacja komponentu"""
        self._ = _
        print(f"[component_id] Component initialized")

    def enable(self):
        """Włącz funkcjonalność komponentu"""
        try:
            # Dodaj logikę komponentu tutaj
            if SOUND_AVAILABLE:
                play_sound('ui/dialog.ogg')
            print(f"[component_id] Component enabled")
            return True
        except Exception as e:
            print(f"[component_id] Error enabling component: {e}")
            return False

    def disable(self):
        """Wyłącz funkcjonalność komponentu"""
        try:
            # Dodaj logikę czyszczenia tutaj
            if SOUND_AVAILABLE:
                play_sound('ui/dialogclose.ogg')
            print(f"[component_id] Component disabled")
        except Exception as e:
            print(f"[component_id] Error disabling component: {e}")


# Globalna instancja komponentu
_component_instance = None


def get_component():
    """Pobierz globalną instancję komponentu"""
    global _component_instance
    if _component_instance is None:
        _component_instance = MyComponent()
    return _component_instance


def initialize(app=None):
    """Inicjalizacja komponentu - wywoływana przez ComponentManager"""
    try:
        print(f"[component_id] Initializing component...")
        component = get_component()
        # Dodaj logikę inicjalizacji tutaj
        print(f"[component_id] Component initialized successfully")
    except Exception as e:
        print(f"[component_id] Error during initialization: {e}")
        import traceback
        traceback.print_exc()


def shutdown():
    """Zamknięcie komponentu - wywoływana przez ComponentManager"""
    global _component_instance
    try:
        print(f"[component_id] Shutting down component...")
        if _component_instance:
            _component_instance.disable()
            _component_instance = None
        print(f"[component_id] Component shutdown complete")
    except Exception as e:
        print(f"[component_id] Error during shutdown: {e}")
        import traceback
        traceback.print_exc()
```

## Interfejs komponentu

### Wymagane funkcje

#### initialize(app=None)
**Wymagana funkcja** wywoływana przy starcie Titan:
- `app` - instancja głównej aplikacji wxPython (może być None)
- Użyj do inicjalizacji zasobów, uruchamiania wątków

### Opcjonalne funkcje

#### shutdown()
Wywoływana przy zamykaniu Titan:
- Zatrzymaj wątki, zwolnij zasoby
- Zapisz stan komponentu jeśli potrzeba

#### add_menu(component_manager)
Dodaje pozycje do menu komponentów:
- `component_manager.register_menu_function(nazwa, funkcja)`
- Menu dostępne w niewidzialnym interfejsie i menu GUI

#### add_settings(settings_frame)
**Legacy**: Dodaje kontrolki do okna ustawień:
- `settings_frame` - główne okno ustawień
- **UWAGA**: Preferuj `add_settings_category()` dla nowych komponentów

#### add_settings_category(component_manager)
**Zalecane**: Rejestruje kategorię ustawień w modularnym systemie ustawień:
```python
def add_settings_category(component_manager):
    def build_panel(parent):
        panel = wx.Panel(parent)
        # ... dodaj kontrolki ...
        return panel

    def save_settings(panel):
        # Zapisz ustawienia
        pass

    def load_settings(panel):
        # Wczytaj ustawienia
        pass

    component_manager.register_settings_category(
        _("Mój komponent"),
        build_panel,
        save_settings,
        load_settings
    )
```

## System hooków

### GUI Hooks (get_gui_hooks)

Komponent może zarejestrować hooki do głównego interfejsu GUI:

```python
def get_gui_hooks():
    """Zwróć słownik GUI hooks (opcjonalnie)

    Dostępne hooki:
        'on_gui_init': wywoływana z gui_app (TitanApp wx.Frame) gdy GUI jest inicjalizowane
    """
    return {
        'on_gui_init': on_gui_init
    }

def on_gui_init(gui_app):
    """Hook wywoływany gdy GUI jest zainicjalizowane"""
    # Tutaj możesz np. zarejestrować widok w głównym panelu
    pass
```

### Invisible UI Hooks (get_iui_hooks)

Komponent może dodawać własne kategorie do niewidzialnego interfejsu:

```python
def get_iui_hooks():
    """Zwróć słownik Invisible UI hooks (opcjonalnie)

    Dostępne hooki:
        'on_iui_init': wywoływana z iui (InvisibleUI) po build_structure()

    Przykład - dodanie własnej kategorii:
        def on_iui_init(iui):
            iui.categories.append({
                "name": "Mój komponent",
                "sound": "core/focus.ogg",
                "elements": ["Opcja 1", "Opcja 2"],
                "action": lambda name: my_action(name)
            })
    """
    return {
        'on_iui_init': on_iui_init
    }

def on_iui_init(iui):
    """Hook wywoływany gdy Invisible UI jest zainicjalizowany"""
    iui.categories.append({
        "name": _("Mój komponent"),
        "sound": "core/focus.ogg",
        "elements": [_("Akcja 1"), _("Akcja 2")],
        "action": lambda name: handle_action(name)
    })
```

### Klango Mode Hooks (get_klango_hooks)

Komponent może integrować się z trybem Klango:

```python
def get_klango_hooks():
    """Zwróć słownik Klango mode hooks (opcjonalnie)

    Dostępne hooki:
        'on_klango_init': wywoływana z klango_mode (KlangoMode) gdy Klango mode startuje
    """
    return {
        'on_klango_init': on_klango_init
    }

def on_klango_init(klango_mode):
    """Hook wywoływany gdy Klango mode jest zainicjalizowany"""
    # Dodaj własne pozycje menu do Klango
    pass
```

## API rejestracji widoków (Component View Registration)

**NOWOŚĆ!** Komponenty mogą dodawać własne zakładki/widoki do lewego panelu głównego GUI. Zarejestrowane widoki pojawiają się w cyklu Ctrl+Tab obok wbudowanych widoków (Lista aplikacji, Lista gier, Titan IM).

### Parametry register_view()

| Parametr | Typ | Wymagany | Opis |
|----------|-----|----------|------|
| `view_id` | str | Tak | Unikalny identyfikator, np. `'my_notes'` |
| `label` | str | Tak | Tekst nagłówka pokazywany nad kontrolką, np. `'Moje notatki:'` |
| `control` | wx.Window | Tak | Dowolna kontrolka wx (ListBox, TreeCtrl, itp.), rodzic: `gui_app.main_panel` |
| `on_show` | callable | Nie | Wywoływana za każdym razem gdy widok staje się widoczny (odświeżanie danych) |
| `on_activate` | callable | Nie | Wywoływana gdy użytkownik naciśnie Enter na kontrolce |
| `position` | str/int | Nie | Pozycja w cyklu: `'after_apps'`, `'after_games'`, `'after_network'` (domyślnie), lub indeks liczbowy |

### Jak to działa

- Zarejestrowana kontrolka jest dodawana do sizer'a lewego panelu (domyślnie ukryta)
- Użytkownik naciska Ctrl+Tab aby przełączać widoki: Aplikacje → Gry → [twój widok] → Titan IM → ...
- Tab/Shift+Tab nawiguje między kontrolką widoku a paskiem statusu
- Enter na kontrolce widoku wywołuje `on_activate` (jeśli podano)
- TTS ogłasza etykietę widoku i pozycję, np. "Moje notatki, 3 z 4"

### Dostępne atrybuty gui_app

| Atrybut | Typ | Opis |
|---------|-----|------|
| `gui_app.main_panel` | wx.Panel | Panel rodzica dla tworzenia nowych kontrolek |
| `gui_app.list_sizer` | wx.BoxSizer | Sizer zawierający wszystkie kontrolki lewego panelu |
| `gui_app.registered_views` | list | Wszystkie zarejestrowane widoki (wbudowane + komponentowe) |
| `gui_app.register_view()` | method | Zarejestruj nowy widok do cyklu Ctrl+Tab |
| `gui_app.component_manager` | ComponentManager | Referencja do menedżera komponentów |
| `gui_app.settings` | dict | Ustawienia aplikacji |
| `gui_app.titan_client` | TitanNetClient | Instancja klienta Titan-Net |

## Przykłady komponentów

### Przykład 1: Prosty widok listy (Menedżer zakładek)

Komponent dodający zakładkę "Zakładki" do lewego panelu z listą zapisanych zakładek.

**Plik: `data/components/bookmarks/init.py`**
```python
# -*- coding: utf-8 -*-
"""Komponent zakładek - dodaje listę zakładek do głównego panelu."""

import os
import sys
import wx
import json

COMPONENT_DIR = os.path.dirname(__file__)
TCE_ROOT = os.path.abspath(os.path.join(COMPONENT_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

try:
    from src.titan_core.sound import play_sound
except ImportError:
    def play_sound(name): pass

try:
    from src.settings.settings import get_setting
except ImportError:
    def get_setting(key, default='', section='general'): return default

def _(text):
    return text

# --- Dane zakładek ---
BOOKMARKS_FILE = os.path.join(COMPONENT_DIR, 'bookmarks.json')
_bookmarks = []
_listbox = None


def load_bookmarks():
    """Wczytaj zakładki z pliku JSON."""
    global _bookmarks
    try:
        if os.path.exists(BOOKMARKS_FILE):
            with open(BOOKMARKS_FILE, 'r', encoding='utf-8') as f:
                _bookmarks = json.load(f)
        else:
            _bookmarks = [
                {"name": "Google", "url": "https://google.com"},
                {"name": "YouTube", "url": "https://youtube.com"},
            ]
            save_bookmarks()
    except Exception as e:
        print(f"[bookmarks] Error loading bookmarks: {e}")
        _bookmarks = []


def save_bookmarks():
    """Zapisz zakładki do pliku JSON."""
    try:
        with open(BOOKMARKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(_bookmarks, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[bookmarks] Error saving bookmarks: {e}")


def refresh_list():
    """Odśwież listbox z aktualnymi zakładkami (wywoływane przez on_show)."""
    if _listbox is None:
        return
    _listbox.Clear()
    for bm in _bookmarks:
        _listbox.Append(bm['name'])
    if _listbox.GetCount() > 0:
        _listbox.SetSelection(0)


def on_bookmark_activate(event):
    """Otwórz wybraną zakładkę w przeglądarce (wywoływane przez Enter)."""
    if _listbox is None:
        return
    sel = _listbox.GetSelection()
    if sel == wx.NOT_FOUND or sel >= len(_bookmarks):
        return
    url = _bookmarks[sel]['url']
    play_sound('ui/dialog.ogg')
    import webbrowser
    webbrowser.open(url)


def on_gui_init(gui_app):
    """Zarejestruj widok zakładek w głównym lewym panelu."""
    global _listbox
    _listbox = wx.ListBox(gui_app.main_panel)

    gui_app.register_view(
        view_id='bookmarks',
        label=_("Zakładki:"),
        control=_listbox,
        on_show=refresh_list,
        on_activate=on_bookmark_activate,
        position='after_network'
    )
    print("[bookmarks] View registered in main panel")


# --- Interfejs komponentu ---

def get_gui_hooks():
    return {'on_gui_init': on_gui_init}


def add_menu(component_manager):
    def add_bookmark(event):
        dlg = wx.TextEntryDialog(None, _("Wprowadź nazwę zakładki:"), _("Dodaj zakładkę"))
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                url_dlg = wx.TextEntryDialog(None, _("Wprowadź URL:"), _("Dodaj zakładkę"), "https://")
                if url_dlg.ShowModal() == wx.ID_OK:
                    url = url_dlg.GetValue().strip()
                    if url:
                        _bookmarks.append({"name": name, "url": url})
                        save_bookmarks()
                        refresh_list()
                        play_sound('ui/dialog.ogg')
                url_dlg.Destroy()
        dlg.Destroy()

    component_manager.register_menu_function(_("Dodaj zakładkę..."), add_bookmark)


def initialize(app=None):
    load_bookmarks()
    print("[bookmarks] Component initialized")


def shutdown():
    save_bookmarks()
    print("[bookmarks] Component shutdown")
```

**Plik: `data/components/bookmarks/__component__.TCE`**
```ini
[component]
name = Bookmarks
status = 0

```

---

### Przykład 2: Widok drzewa (Przeglądarka plików)

Komponent dodający widok drzewa pokazujący pliki z katalogu.

**Plik: `data/components/filebrowser/init.py`**
```python
# -*- coding: utf-8 -*-
"""Komponent przeglądarki plików - dodaje drzewo plików do głównego panelu."""

import os
import sys
import wx

COMPONENT_DIR = os.path.dirname(__file__)
TCE_ROOT = os.path.abspath(os.path.join(COMPONENT_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

try:
    from src.titan_core.sound import play_sound
except ImportError:
    def play_sound(name): pass

def _(text):
    return text

_tree = None
_browse_path = os.path.expanduser("~\\Documents")


def populate_tree():
    """Wypełnij drzewo plikami z browse_path (wywoływane przez on_show)."""
    if _tree is None:
        return

    _tree.DeleteAllItems()
    root = _tree.AddRoot(_browse_path)

    try:
        for item_name in sorted(os.listdir(_browse_path)):
            full_path = os.path.join(_browse_path, item_name)
            if os.path.isdir(full_path):
                _tree.AppendItem(root, f"[KATALOG] {item_name}")
            else:
                _tree.AppendItem(root, item_name)
    except PermissionError:
        _tree.AppendItem(root, _("Odmowa dostępu"))
    except Exception as e:
        _tree.AppendItem(root, f"Błąd: {e}")

    _tree.Expand(root)

    # Wybierz pierwsze dziecko
    child, cookie = _tree.GetFirstChild(root)
    if child.IsOk():
        _tree.SelectItem(child)


def on_file_activate(event):
    """Otwórz wybrany plik (wywoływane przez Enter)."""
    if _tree is None:
        return
    item = _tree.GetSelection()
    if not item.IsOk():
        return
    text = _tree.GetItemText(item)
    if text.startswith("[KATALOG] "):
        # Wejdź do katalogu
        global _browse_path
        dir_name = text[10:]  # Usuń prefiks "[KATALOG] "
        _browse_path = os.path.join(_browse_path, dir_name)
        populate_tree()
        play_sound('core/focus.ogg')
    elif text == _("Odmowa dostępu"):
        return
    else:
        # Otwórz plik
        file_path = os.path.join(_browse_path, text)
        if os.path.exists(file_path):
            os.startfile(file_path)
            play_sound('ui/dialog.ogg')


def on_gui_init(gui_app):
    """Zarejestruj widok przeglądarki plików."""
    global _tree
    _tree = wx.TreeCtrl(
        gui_app.main_panel,
        style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_SINGLE
    )

    gui_app.register_view(
        view_id='filebrowser',
        label=_("Przeglądarka plików:"),
        control=_tree,
        on_show=populate_tree,
        on_activate=on_file_activate,
        position='after_games'  # Między Grami a Titan IM
    )
    print("[filebrowser] View registered in main panel")


# --- Interfejs komponentu ---

def get_gui_hooks():
    return {'on_gui_init': on_gui_init}


def initialize(app=None):
    print("[filebrowser] Component initialized")


def shutdown():
    print("[filebrowser] Component shutdown")
```

**Plik: `data/components/filebrowser/__component__.TCE`**
```ini
[component]
name = File Browser
status = 0

```

---

### Przykład 3: Monitor systemu (tylko tło, bez widoku)

Komponent działający w tle, który monitoruje użycie CPU i pokazuje ostrzeżenie przy wysokim obciążeniu.

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

def show_system_info(event=None):
    cpu = psutil.cpu_percent()
    memory = psutil.virtual_memory().percent
    message = f"CPU: {cpu}%\nPamięć: {memory}%"
    wx.MessageBox(message, "Informacje systemowe", wx.OK | wx.ICON_INFORMATION)
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
from src.titan_core.sound import play_sound, play_error_sound, play_dialog_sound

def moja_funkcja():
    play_sound("focus.ogg")  # Odtwórz dźwięk z motywu
    play_error_sound()       # Dźwięk błędu
```

### Dostęp do ustawień
```python
from src.settings.settings import get_setting, set_setting

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
├── init.py              # Główny plik komponentu (NIE __init__.py!)
├── __component__.TCE    # Konfiguracja komponentu
├── bookmarks.json       # Dane komponentu (przykład)
├── resources/           # Zasoby (opcjonalnie)
│   ├── sounds/
│   └── images/
├── data/                # Pliki danych (opcjonalnie)
└── languages/           # Tłumaczenia (opcjonalnie)
    ├── component_id.pot
    ├── pl/
    │   └── LC_MESSAGES/
    │       └── component_id.mo
    └── en/
        └── LC_MESSAGES/
            └── component_id.mo
```

## Testowanie komponentów

1. Umieść komponent w `data/components/nazwa_komponentu/`
2. Upewnij się że plik to `init.py` a nie `__init__.py`
3. Sprawdź format `__component__.TCE` (INI, wielkie litery .TCE)
4. Uruchom Titan
5. Sprawdź w menedżerze komponentów czy komponent jest załadowany
6. Testuj funkcjonalność przez menu komponentów
7. Jeśli komponent rejestruje widok, sprawdź cykl Ctrl+Tab

## Typy komponentów

- **Service**: Usługi działające w tle (np. integracja z czytnikiem ekranu, monitoring systemu)
- **Integration**: Integracje z usługami zewnętrznymi (np. słownik, przeglądarka artykułów)
- **Feature**: Dodatkowe funkcje (np. terminal, system porad, launchery)
- **View**: Komponenty dodające zakładkę/widok do głównego lewego panelu (użyj `register_view()`)

## Najważniejsze wskazówki

1. **Zawsze używaj wątków daemon** - `threading.Thread(daemon=True)`
2. **Obsługuj shutdown()** - zatrzymaj wszystkie wątki
3. **Używaj wx.CallAfter** dla operacji GUI z wątków
4. **Testuj włączanie/wyłączanie** komponentu
5. **Dodaj obsługę błędów** - komponenty nie powinny crashować Titan
6. **Oszczędzaj zasoby** - nie wykonuj ciężkich operacji za często
7. **Dokumentuj funkcje menu** - wyjaśnij co robią
8. **Używaj get_gui_hooks()** dla widoków zamiast bezpośredniej modyfikacji GUI
9. **Odśwież dane w on_show** gdy widok staje się widoczny (Ctrl+Tab)
10. **Dodawaj menu kontekstowe** dla lepszego UX (prawy klik na ListBox/TreeCtrl)

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
        import traceback
        traceback.print_exc()
```

## Przykłady referencyjne

- **TitanScreenReader** (`data/components/TitanScreenReader/`): Złożony czytnik ekranu
  - Komponent typu Service z monitoringiem w tle
  - Wiele podmodułów (uia_handler, speech_manager, keyboard_handler)
  - Dialog ustawień z wxPython
  - Wsparcie tłumaczeń

- **tips** (`data/components/tips/`): System porad
  - Prosty komponent typu Feature
  - Wątek w tle dla okresowych porad
  - Dialog ustawień

- **tDict** (`data/components/tDict/`): Komponent słownika
  - Podkatalog `data/` dla plików słownika
  - Wsparcie tłumaczeń

Komponenty Titan umożliwiają rozszerzanie funkcjonalności systemu w sposób modularny i bezpieczny. Dzięki prostemu API można łatwo dodawać nowe możliwości bez modyfikowania głównego kodu aplikacji.

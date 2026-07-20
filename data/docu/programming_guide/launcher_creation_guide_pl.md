# Przewodnik tworzenia launcherów TCE

## Wprowadzenie

**Launchery** to alternatywne interfejsy graficzne dla TCE. Zastępują one standardowe GUI własnym oknem napisanym w **dowolnej bibliotece GUI Pythona** (wxPython, PyQt5, tkinter, pygame, kivy, ...). TCE nadal działa w tle i udostępnia wszystkie usługi (aplikacje, gry, dźwięk, ustawienia, Titan IM, statusbar, komponenty) przez obiekt `LauncherAPI` przekazany do funkcji `start()` launchera.

**W danym momencie może być uruchomiony tylko jeden launcher.**

### Uruchomienie

Z linii poleceń:
```bash
python main.py --startup-mode launcher --launcher nazwa_folderu
```

Lub z `settings.json`:
```ini
[general]
startup_mode = launcher
launcher = nazwa_folderu
```

## Architektura

```
data/launchers/moj_launcher/
├── __launcher__.TCE     # Konfiguracja (WYMAGANE, .TCE wielkimi literami)
├── init.py              # Punkt wejścia z funkcją start(api) (WYMAGANE)
├── languages/           # Tłumaczenia własne launchera (opcjonalne)
│   ├── pl/LC_MESSAGES/launcher.po/.mo
│   └── en/LC_MESSAGES/launcher.po/.mo
└── lib/                 # Biblioteki dołączone z launcherem (opcjonalne)
```

`LauncherManager` skanuje `data/launchers/` przy starcie TCE, znajduje katalogi z plikiem `__launcher__.TCE`, parsuje konfigurację i uruchamia wybrany launcher.

## Plik konfiguracyjny `__launcher__.TCE`

Plik w formacie INI z dwiema sekcjami: `[launcher]` i `[features]`.

```ini
[launcher]
name = Mój Launcher
description = Krótki opis launchera
author = Twoje Imię
version = 1.0
status = 0
libs = lib, vendor

[features]
applications = true
games = true
titan_im = true
help = true
components = true
system_hooks = true
notifications = true
sound = true
invisible_ui = false
```

### Pola sekcji `[launcher]`

| Pole | Wymagane | Opis |
|------|----------|------|
| name | nie | Nazwa wyświetlana (domyślnie nazwa folderu) |
| description | nie | Krótki opis |
| author | nie | Autor |
| version | nie | Wersja (domyślnie `1.0`) |
| status | tak | **`0` = włączony, `1` = wyłączony** (taka sama konwencja jak komponenty) |
| libs | nie | Lista podkatalogów z bibliotekami oddzielona przecinkami (domyślnie `lib`) |

### Pola sekcji `[features]`

Wszystkie wartości to `true` lub `false`. Jeśli pole nie istnieje, użyta zostanie wartość domyślna.

| Funkcja | Domyślnie | Co odblokowuje |
|---------|-----------|----------------|
| applications | true | `api.get_applications()`, `api.open_application()` |
| games | true | `api.get_games()`, `api.open_game()` |
| titan_im | true | `api.titan_net_client`, `api.open_telegram()`, `api.open_messenger()`, ... |
| help | true | `api.show_help()` |
| components | true | `api.get_components()`, `api.get_component_menu_functions()` |
| system_hooks | true | Parsowane, ale **obecnie nie steruje niczym** w `LauncherAPI.__init__` — zachowane na przyszłość, nie polegaj na ustawieniu `false` żeby cokolwiek wyłączyć |
| notifications | true | `api.notifications` |
| sound | true | Pełny system dźwięków TCE (zawsze dostępny) |
| invisible_ui | false | `api.start_invisible_ui()` (przełączanie tyldą) |

## Implementacja `init.py`

Plik MUSI nazywać się dokładnie `init.py` (lub `init.pyc`).

Launcher MUSI zdefiniować:
- `start(api)` — punkt wejścia, wywoływany raz przy starcie TCE. **Musi szybko wrócić.**

Launcher MOŻE zdefiniować:
- `shutdown()` — wywoływane przy zamykaniu TCE.

### Podstawowy szkielet

```python
# -*- coding: utf-8 -*-
def start(api):
    """Punkt wejścia. Musi szybko wrócić."""
    # wxPython: utwórz wx.Frame i wróć (wx.MainLoop już działa)
    # PyQt5/tkinter/pygame: uruchom własną pętlę zdarzeń w wątku daemon

def shutdown():
    """Opcjonalne: wywołane przy zamykaniu TCE."""
    pass
```

**WAŻNE:**
- Dla **wxPython** wystarczy stworzyć `wx.Frame` i wrócić — `wx.MainLoop()` już działa w `main.py`.
- Dla **innych bibliotek** (tkinter, PyQt5, pygame) MUSISZ uruchomić własną pętlę zdarzeń w wątku daemon, inaczej zablokujesz TCE.
- **Nigdy** nie twórz nowego `wx.App()` — użyj `api.wx_app` jeśli potrzebujesz okien dialogowych wx.

## LauncherAPI

Obiekt `api` przekazany do `start(api)` to interfejs do wszystkich usług TCE.

### Zawsze dostępne (niezależnie od `[features]`)

#### Ustawienia
```python
api.get_setting(key, default='', section='general')
api.set_setting(key, value, section='general')
api.load_settings()           # zwraca pełny słownik ustawień
api.save_settings()
```

#### Tłumaczenia
```python
_ = api._                              # wbudowana funkcja tłumaczeń TCE
api.language_code                      # bieżący kod języka, np. 'pl'
_ = api.load_translations()            # załaduj własne tłumaczenia (domena 'launcher')
_ = api.load_translations('moja_nazwa')  # własna domena
api.set_language(lang_code)
api.get_available_languages()
```

#### Dźwięk (pełny system dźwięków TCE)
```python
api.play_sound('ui/dialog.ogg')       # dowolny plik z bieżącego motywu sfx
api.play_startup_sound()
api.play_focus_sound()                 # zmiana fokusa na liście
api.play_select_sound()                # wybór elementu
api.play_applist_sound()               # wejście w listę aplikacji/gier
api.play_endoflist_sound()             # koniec listy
api.play_error_sound()
api.play_dialog_sound()                # otwarcie dialogu
api.play_dialogclose_sound()           # zamknięcie dialogu
api.play_statusbar_sound()             # fokus na pasku statusu
api.play_loop_sound()                  # rozpocznij dźwięk w pętli
api.stop_loop_sound()
api.play_ai_tts(text)                  # AI text-to-speech
api.stop_ai_tts()
api.is_ai_tts_playing()                # bool
api.resource_path('sfx/sound.ogg')    # ścieżka bezwzględna do zasobu TCE
api.get_sfx_directory()                # katalog bieżącego motywu sfx
```

#### Speaker (TTS)
```python
api.speaker.speak("Cześć")
api.speaker.speak(text, interrupt=True)
# api.speaker to gotowy accessible_output3 Auto()
```

#### Stereo speech (czytanie z panoramą i pitchem)
```python
api.speak_stereo(text, position=0.0, interrupt=True, pitch_offset=0)
api.stop_stereo_speech()
api.get_stereo_speech()                # instancja StereoSpeech lub None
```

#### Wibracje kontrolera
```python
api.vibrate_cursor_move()
api.vibrate_menu_open()
api.vibrate_menu_close()
api.vibrate_selection()
api.vibrate_focus_change()
api.vibrate_error()
api.vibrate_notification()
api.vibrate_startup()
api.set_vibration_enabled(True)
api.set_vibration_strength(0.7)
api.get_controller_info()              # informacje o statusie kontrolera lub None
api.refresh_controllers()
api.test_vibration()
```

#### Statusbar (pasek statusu)
```python
api.statusbar_applet_manager.get_statusbar_items()    # lista wszystkich tekstów [str]
api.statusbar_applet_manager.get_builtin_items()      # tylko wbudowane (Zegar, Bateria, ...)
api.statusbar_applet_manager.get_applet_names()       # nazwy załadowanych appletów
api.statusbar_applet_manager.get_all_applet_texts()   # tylko teksty appletów
api.statusbar_applet_manager.activate_applet(nazwa)   # otwórz okno szczegółów appletu
api.statusbar_applet_manager.start_auto_update()
api.statusbar_applet_manager.stop_auto_update()
```

#### Moduły IM (komunikatory)
```python
for mod in api.im_module_manager.modules:
    print(mod['id'], mod['name'])
    status = api.im_module_manager.get_status_text(mod['id'])
    api.im_module_manager.open_module(mod['id'], parent_window)
```

#### Sterowanie launcherem
```python
api.show_settings()                        # otwórz okno Ustawień TCE
api.request_exit()                         # zamknięcie pętli wx (graceful)
api.force_exit()                           # twardy shutdown TCE + os._exit(0)
api.register_shutdown_callback(callback)   # zarejestruj callback przy zamykaniu
api.has_feature('applications')            # czy funkcja jest włączona (bool)
api.check_for_updates()                    # sprawdź aktualizacje TCE, pokazuje okno jeśli dostępna → bool
api.show_shutdown_dialog()                 # pokaż okno potwierdzenia zamknięcia TCE

# Minimalizacja do tray:
api.register_minimize_handler(callback)    # callback ukrywa twoje okno
api.register_restore_handler(callback)     # callback przywraca twoje okno
api.minimize_launcher()                    # ukryj okno + pokaż ikonę w tray → bool
api.restore_launcher()                     # pokaż okno + ukryj ikonę z tray → bool
api.is_minimized                           # bool
api.supports_minimize                      # bool

# Niewidzialny interfejs (przełączanie tyldą):
api.start_invisible_ui()                   # wymaga invisible_ui=true w configu
api.stop_invisible_ui()
```

#### Window switcher
```python
api.show_window_switcher(parent=None)
api.register_window(window, name)
api.unregister_window(window)
```

#### Metadane
```python
api.version           # wersja TCE, np. "2.1.0"
api.launcher_path     # ścieżka bezwzględna do katalogu launchera
api.wx_app            # instancja wx.App (do dialogów wx z launcherów nie-wx)
```

### Warunkowe (zależnie od `[features]`)

#### Aplikacje (`features.applications = true`)
```python
apps = api.get_applications()             # [{'name': str, 'name_en': str, 'shortname': str, ...}]
api.open_application(app_dict)            # uruchom aplikację
api.find_application_by_shortname('tedit')
```

#### Gry (`features.games = true`)
```python
games = api.get_games()                   # [{'name': str, 'platform': str, ...}]
api.get_games_by_platform('Titan')
api.open_game(game_dict)
```

#### Titan IM (`features.titan_im = true`)
```python
api.titan_net_client                      # TitanNetClient lub None
api.open_telegram()                       # dialog logowania Telegrama
api.open_messenger()                      # Facebook Messenger
api.open_whatsapp()                       # WhatsApp
api.open_titannet()                       # Titan-Net (login + okno główne po sukcesie)
api.open_eltenlink()                      # EltenLink
api.open_im_module('nazwa_lub_id')        # otwiera moduł IM po nazwie/id
```

#### Pomoc (`features.help = true`)
```python
api.show_help()
```

#### Komponenty (`features.components = true`)
```python
api.get_components()
api.get_component_menu_functions()        # [(label, callback), ...]
```

#### Powiadomienia (`features.notifications = true`)
```python
api.notifications                         # menedżer powiadomień
```

#### Niewidzialny interfejs (`features.invisible_ui = true`)
```python
api.invisible_ui                          # instancja InvisibleUI
```

## Hooki komponentów dla launcherów

Komponenty mogą reagować na uruchomienie launchera, definiując `get_launcher_hooks()` w swoim `init.py`:

```python
# W init.py komponentu:
def get_launcher_hooks():
    def on_launcher_init(launcher_manager, launcher_name):
        print(f"Launcher '{launcher_name}' wystartował, można dostosować")
    return {'on_launcher_init': on_launcher_init}
```

## Tłumaczenia launchera

```bash
# 1. Utwórz katalog languages/ w katalogu launchera
mkdir data/launchers/moj_launcher/languages

# 2. Wyciągnij teksty z init.py
pybabel extract -o languages/launcher.pot --no-default-keywords --keyword=_ \
    data/launchers/moj_launcher/init.py

# 3. Zainicjuj języki
pybabel init -l pl -d data/launchers/moj_launcher/languages \
    -i data/launchers/moj_launcher/languages/launcher.pot -D launcher
pybabel init -l en -d data/launchers/moj_launcher/languages \
    -i data/launchers/moj_launcher/languages/launcher.pot -D launcher

# 4. Skompiluj
pybabel compile -d data/launchers/moj_launcher/languages
```

W `init.py`:
```python
def start(api):
    _ = api.load_translations()           # ładuje launcher.mo z languages/
    print(_("Witaj"))
```

## Wymagania wieloplatformowości

Każdy launcher MUSI działać na **Windowsie, macOS i Linuksie**.

### Wybór biblioteki GUI

| Biblioteka | Dodatkowe zależności | Pętla zdarzeń |
|-----------|----------------------|----------------|
| **wxPython** | brak (już wymagane przez TCE) | Współdzielona — utwórz wx.Frame i wróć z `start()` |
| **tkinter** | brak (stdlib) | Własna — `root.mainloop()` w wątku daemon |
| **PyQt5** | `pip install PyQt5` | Własna — `app.exec_()` w wątku daemon |
| **pygame** | `pip install pygame` | Własna — pętla gry w wątku daemon |

### Otwieranie plików/URL (wieloplatformowo)
```python
import sys, subprocess, os
if sys.platform == 'win32':
    os.startfile(path)
elif sys.platform == 'darwin':
    subprocess.Popen(['open', path])
else:
    subprocess.Popen(['xdg-open', path])

# URL: zawsze webbrowser.open(url)
```

### Biblioteka `keyboard` — guard na macOS
```python
import sys
KEYBOARD_AVAILABLE = False
if sys.platform != 'darwin':
    try:
        import keyboard
        KEYBOARD_AVAILABLE = True
    except ImportError:
        pass
```

### Częste pomyłki
- Tworzenie nowego `wx.App()` — **NIE**, użyj `api.wx_app`.
- Blokowanie w `start()` — własne pętle zdarzeń MUSZĄ działać w wątku daemon (oprócz wxPython).
- `os.environ['APPDATA']` → `os.getenv('APPDATA') or os.path.expanduser('~')`.
- `os.startfile(path)` → tylko Windows, użyj sprawdzenia platformy.
- `os.sys.platform` → **AttributeError!** Poprawnie: `sys.platform` (po `import sys`).

## Przykład 1: Launcher wxPython

Pełny launcher wxPython z listami aplikacji, gier, Titan IM, statusbar, dźwiękami i obsługą tray. Używa współdzielonej pętli wx — bez wątku daemon.

**Plik: `data/launchers/simple_wx/__launcher__.TCE`**
```ini
[launcher]
name = Simple WX Launcher
description = Minimalny dostępny launcher wxPython dla TCE
author = TCE Team
version = 1.0
status = 0

[features]
applications = true
games = true
titan_im = true
help = true
components = false
system_hooks = true
notifications = true
sound = true
invisible_ui = false
```

**Plik: `data/launchers/simple_wx/init.py`**
```python
# -*- coding: utf-8 -*-
import wx

_api = None
_frame = None


def start(api):
    """Punkt wejścia — tworzy okno i wraca natychmiast."""
    global _api, _frame
    _api = api

    frame = SimpleLauncherFrame(None, api)
    _frame = frame

    api.register_minimize_handler(lambda: wx.CallAfter(frame.Hide))
    api.register_restore_handler(lambda: (wx.CallAfter(frame.Show),
                                           wx.CallAfter(frame.Raise)))

    wx.CallAfter(frame.Show)
    wx.CallAfter(api.play_startup_sound)
    api.start_invisible_ui()


class SimpleLauncherFrame(wx.Frame):
    def __init__(self, parent, api):
        _ = api._
        super().__init__(parent, title=f"TCE {api.version}", size=(720, 620))
        self.api = api
        self._apps = []
        self._games = []
        self._build_ui()
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _build_ui(self):
        api = self.api
        _ = api._
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        if api.get_applications:
            self._apps = api.get_applications() or []
            if self._apps:
                sizer.Add(wx.StaticText(panel, label=_("Aplikacje")), 0, wx.LEFT | wx.TOP, 8)
                self.app_list = wx.ListBox(panel)
                for app in self._apps:
                    self.app_list.Append(app.get('name', app.get('name_en', '?')))
                self.app_list.Bind(wx.EVT_LISTBOX, lambda e: api.play_focus_sound())
                self.app_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_app_activate)
                sizer.Add(self.app_list, 2, wx.EXPAND | wx.ALL, 5)

        if api.get_games:
            self._games = api.get_games() or []
            if self._games:
                sizer.Add(wx.StaticText(panel, label=_("Gry")), 0, wx.LEFT | wx.TOP, 8)
                self.game_list = wx.ListBox(panel)
                for g in self._games:
                    name = g.get('name', '?')
                    plat = g.get('platform', '')
                    self.game_list.Append(f"{name} ({plat})" if plat else name)
                self.game_list.Bind(wx.EVT_LISTBOX, lambda e: api.play_focus_sound())
                self.game_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_game_activate)
                sizer.Add(self.game_list, 2, wx.EXPAND | wx.ALL, 5)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        s = wx.Button(panel, label=_("Ustawienia"))
        s.Bind(wx.EVT_BUTTON, lambda e: (api.play_dialog_sound(), api.show_settings()))
        btns.Add(s, 0, wx.ALL, 5)
        x = wx.Button(panel, label=_("Wyjście"))
        x.Bind(wx.EVT_BUTTON, self._on_close)
        btns.Add(x, 0, wx.ALL, 5)
        sizer.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        panel.SetSizer(sizer)

        for attr in ('app_list', 'game_list'):
            ctrl = getattr(self, attr, None)
            if ctrl and ctrl.GetCount() > 0:
                ctrl.SetFocus()
                ctrl.SetSelection(0)
                break

    def _on_app_activate(self, event):
        idx = self.app_list.GetSelection()
        if 0 <= idx < len(self._apps):
            self.api.play_select_sound()
            self.api.open_application(self._apps[idx])

    def _on_game_activate(self, event):
        idx = self.game_list.GetSelection()
        if 0 <= idx < len(self._games):
            self.api.play_select_sound()
            self.api.open_game(self._games[idx])

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.api.minimize_launcher()
        else:
            event.Skip()

    def _on_close(self, event=None):
        self.api.play_dialogclose_sound()
        self.api.force_exit()


def shutdown():
    global _frame
    try:
        if _api:
            _api.stop_invisible_ui()
    except Exception:
        pass
    try:
        if _frame:
            wx.CallAfter(_frame.Destroy)
    except Exception:
        pass
    _frame = None
```

## Przykład 2: Launcher tkinter

Wieloplatformowy launcher bez dodatkowych zależności (tkinter jest w stdlib). Działa we własnym wątku daemon z `mainloop()`.

**Plik: `data/launchers/simple_tk/__launcher__.TCE`**
```ini
[launcher]
name = Simple Tkinter Launcher
description = Lekki launcher tkinter dla TCE bez dodatkowych zależności
author = TCE Team
version = 1.0
status = 0

[features]
applications = true
games = false
titan_im = false
help = true
components = false
system_hooks = true
notifications = false
sound = true
invisible_ui = false
```

**Plik: `data/launchers/simple_tk/init.py`**
```python
# -*- coding: utf-8 -*-
import threading

_api = None
_root = None


def start(api):
    """Uruchom UI tkinter w wątku daemon i wróć natychmiast."""
    global _api
    _api = api
    threading.Thread(target=_run_ui, args=(api,), daemon=True).start()


def _run_ui(api):
    global _root
    import tkinter as tk
    from tkinter import font as tkfont

    _ = api._
    root = tk.Tk()
    _root = root
    root.title(f"TCE {api.version}")
    root.geometry("640x520")

    bold_font = tkfont.Font(weight="bold", size=11)

    apps = api.get_applications() if api.get_applications else []

    if apps:
        tk.Label(root, text=_("Aplikacje"), font=bold_font).pack(
            anchor="w", padx=10, pady=(10, 0))
        listbox = tk.Listbox(root, height=14)
        listbox.pack(fill="both", expand=True, padx=10, pady=5)

        for app in apps:
            listbox.insert(tk.END, app.get('name', app.get('name_en', '?')))

        def on_select(event):
            api.play_focus_sound()

        def on_activate(event):
            sel = listbox.curselection()
            if sel and 0 <= sel[0] < len(apps):
                api.play_select_sound()
                api.open_application(apps[sel[0]])

        listbox.bind("<<ListboxSelect>>", on_select)
        listbox.bind("<Return>", on_activate)
        listbox.bind("<Double-Button-1>", on_activate)
        listbox.selection_set(0)
        listbox.focus_set()

    btn_frame = tk.Frame(root)
    btn_frame.pack(fill="x", padx=10, pady=10)

    tk.Button(btn_frame, text=_("Ustawienia"),
              command=lambda: (api.play_dialog_sound(), api.show_settings())
              ).pack(side="left", padx=5)

    def on_exit():
        api.play_dialogclose_sound()
        api.force_exit()

    tk.Button(btn_frame, text=_("Wyjście"), command=on_exit).pack(side="right", padx=5)

    api.register_minimize_handler(lambda: root.after(0, root.withdraw))
    api.register_restore_handler(lambda: (root.after(0, root.deiconify),
                                           root.after(10, root.lift)))
    root.bind('<Escape>', lambda e: api.minimize_launcher())
    root.protocol("WM_DELETE_WINDOW", on_exit)

    api.play_startup_sound()
    root.mainloop()


def shutdown():
    global _root
    try:
        if _root:
            _root.after(0, _root.destroy)
    except Exception:
        pass
    _root = None
```

## Przykład 3: Launcher PyQt5

Pełny launcher z `data/launchers/example_launcher/init.py` — listy aplikacji, gier, Titan IM, statusbar z aktualizacją co 2 sekundy, obsługa tray, Invisible UI, i pełna informacja zwrotna dźwiękowa.

**Plik: `data/launchers/example_launcher/__launcher__.TCE`** — patrz [example_launcher](../../launchers/example_launcher/__launcher__.TCE) w repozytorium.

**Plik: `data/launchers/example_launcher/init.py`** — pełna implementacja PyQt5 (ok. 340 linii) jest dostępna w repo. Najważniejsze fragmenty:

```python
import sys
import threading
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                              QListWidget, QPushButton, QShortcut)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence

_api = None
_qt_app = None
_window = None


def start(api):
    """Uruchom PyQt5 w wątku daemon — Qt ma własną pętlę zdarzeń."""
    global _api
    _api = api
    threading.Thread(target=_run_pyqt_ui, daemon=True).start()


def _run_pyqt_ui():
    global _window, _qt_app
    _ = _api._

    _qt_app = QApplication(sys.argv)
    _qt_app.setQuitOnLastWindowClosed(False)
    window = QMainWindow()
    _window = window
    window.setWindowTitle(f"TCE v{_api.version}")
    window.resize(700, 600)

    central = QWidget()
    layout = QVBoxLayout(central)
    window.setCentralWidget(central)

    apps = _api.get_applications() or [] if _api.get_applications else []
    if apps:
        listw = QListWidget()
        for app in apps:
            listw.addItem(app.get('name', app.get('name_en', '?')))
        listw.currentItemChanged.connect(lambda *a: _api.play_focus_sound())
        listw.itemActivated.connect(
            lambda item: (_api.play_select_sound(),
                          _api.open_application(apps[listw.row(item)])))
        layout.addWidget(listw)

    # Statusbar z aktualizacją co 2 sekundy
    if _api.statusbar_applet_manager:
        sb = QListWidget()
        for text in _api.statusbar_applet_manager.get_statusbar_items():
            sb.addItem(text)
        layout.addWidget(sb)

        timer = QTimer(window)
        def update_sb():
            items = _api.statusbar_applet_manager.get_statusbar_items()
            for i, text in enumerate(items):
                if i < sb.count():
                    sb.item(i).setText(text)
        timer.timeout.connect(update_sb)
        timer.start(2000)

    # Minimalizacja: Esc -> tray
    _api.register_minimize_handler(lambda: window.hide())
    _api.register_restore_handler(lambda: (window.show(), window.raise_()))
    QShortcut(QKeySequence(Qt.Key_Escape), window).activated.connect(
        _api.minimize_launcher)

    # Zamknięcie okna -> wyjście z TCE
    def closeEvent(event):
        event.ignore()
        _api.play_dialogclose_sound()
        _qt_app.quit()
        _api.force_exit()
    window.closeEvent = closeEvent

    window.show()
    _api.start_invisible_ui()
    _api.play_startup_sound()
    _qt_app.exec_()


def shutdown():
    global _window, _qt_app
    try:
        if _qt_app:
            _qt_app.quit()
    except Exception:
        pass
    _window = None
    _qt_app = None
```

## Pakowanie jako `.TCD` (opcjonalnie)

Zamiast katalogu, launcher można rozpowszechniać jako pojedynczy plik
`.tcd`. W pełni opcjonalne i dodatkowe.

```bash
python src/scripts/pack_addon.py data/launchers/moj_launcher --kind launcher -o moj_launcher.tcd
```

- `.tcd` to własny skompresowany kontener (nagłówek magiczny + strumień
  LZMA), celowo nie jest to prawdziwy zip/7z — 7-Zip i Eksplorator Windows
  odmawiają otwarcia go jako archiwum.
- Nie są potrzebne zmiany w kodzie: zawartość jest identyczna bajt-w-bajt z
  katalogiem, więc `init.py` i `__launcher__.TCE` nadal działają tak samo
  po rozpakowaniu.
- Plik `.tcd` wystarczy umieścić w `data/launchers/` (wbudowanym lub w
  nakładce użytkownika) — zostanie wykryty tak samo jak launcher oparty na
  katalogu. Uwaga: samo zainstalowanie paczki launchera nie sprawia, że
  staje się on aktywnym launcherem — trzeba go dodatkowo wybrać (Ustawienia
  albo `--launcher <nazwa>`), tak samo jak przy ręcznie zainstalowanym
  katalogu.

Zobacz `src/titan_core/titan_package.py` po implementację formatu.

## Weryfikacja instalacji

1. Uruchom: `python main.py --startup-mode launcher --launcher nazwa_folderu`
2. W konsoli sprawdź: `[LauncherManager] Starting launcher: NAZWA`
3. Twoje okno powinno się pojawić, listy powinny zawierać aplikacje/gry.
4. Przetestuj Escape → minimalizacja do tray.
5. Przetestuj zamknięcie okna / przycisk Wyjście → TCE kończy działanie.
6. Sprawdź dźwięki: focus, select, startup, dialog.
7. Jeśli `invisible_ui = true` — naciśnij tyldę, powinien pokazać się niewidzialny interfejs.

## Najważniejsze wskazówki

1. **Zawsze ustaw `status = 0`** — inaczej launcher będzie wyłączony.
2. **`init.py` — dokładna nazwa**, nie `main.py`, nie `__init__.py`.
3. **`__launcher__.TCE` — wielkie litery `.TCE`**, parser ich wymaga.
4. **Nigdy nie blokuj `start(api)`** dla bibliotek z własną pętlą zdarzeń.
5. **Nie twórz nowego `wx.App()`** — używaj `api.wx_app` jeśli potrzebujesz dialogów wx.
6. **Rejestruj minimize/restore handlers** — bez tego `api.minimize_launcher()` nic nie zrobi.
7. **Wywołuj `api.force_exit()` przy wyjściu** — inaczej TCE zostanie z osieroconym procesem.
8. **Używaj `api.has_feature(name)` przed wywołaniem warunkowego API** — chroni przed `None`.
9. **Testuj na wszystkich platformach** — Windows, macOS, Linux.
10. **Dodaj dźwięki** — TCE jest aplikacją dla osób niewidomych, dźwięki są kluczowe.

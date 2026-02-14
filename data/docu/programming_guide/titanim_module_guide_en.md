# Przewodnik tworzenia modułów Titan IM

## Wprowadzenie

Moduły Titan IM to zewnętrzne wtyczki komunikatorów dla systemu Titan IM w TCE Launcher. Moduły znajdują się w katalogu `data/titanIM_modules/` i mogą dodawać własne komunikatory, czytniki RSS, narzędzia społecznościowe i wiele innych.

## Architektura modułów Titan IM

### Lokalizacja modułów
Wszystkie moduły znajdują się w katalogu `data/titanIM_modules/`. Każdy moduł to osobny katalog zawierający:
- `init.py` - główny plik z kodem modułu (NIE `__init__.py`!)
- `__im.TCE` - plik konfiguracyjny modułu (format INI)

### Cykl życia modułu

1. **Ładowanie** - moduły są ładowane przy starcie Titan IM
2. **Otwarcie** - funkcja `open(parent_frame)` wywoływana gdy użytkownik wybierze moduł
3. **Status** - opcjonalna funkcja `get_status_text()` zwraca tekst statusu

## Struktura pliku konfiguracyjnego

### __im.TCE

Plik INI z sekcją `[im_module]`:

```ini
[im_module]
name = Nazwa modułu
status = 0
description = Opis modułu

```

**Parametry:**
- `name` - nazwa wyświetlana w liście Titan IM
- **`status = 0` oznacza WŁĄCZONY, inna wartość oznacza WYŁĄCZONY**
- `description` - opis modułu (opcjonalny)
- **WAŻNE**: Nazwa pliku to `__im.TCE` (wielkie litery .TCE)
- **WAŻNE**: Główny plik to `init.py` (małe litery, NIE `__init__.py`)
- **WAŻNE**: Dodaj pustą linię na końcu pliku

## Implementacja modułu

### Podstawowa struktura init.py

```python
# -*- coding: utf-8 -*-
"""
Nazwa modułu - Titan IM external module for TCE Launcher
Opis modułu
"""

import os
import sys

# Dodaj katalog główny TCE do ścieżki
_MODULE_DIR = os.path.dirname(__file__)
_TCE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, '..', '..', '..'))
if _TCE_ROOT not in sys.path:
    sys.path.insert(0, _TCE_ROOT)

# Sound API - automatycznie wstrzykiwane przez menedżer modułów
# Zapewnia ujednolicone dźwięki TitanNet/Titan IM (takie same jak Telegram, EltenLink, Titan-Net)
_module = sys.modules[__name__]


def open(parent_frame):
    """Otwórz okno komunikatora.

    Wywoływane gdy użytkownik wybierze ten moduł z listy Titan IM.
    parent_frame: wx.Frame lub None - referencja okna rodzica
    """
    try:
        import wx
        sounds = _module.sounds

        # Odtwórz dźwięk powitania (ujednolicony ze wszystkimi integracjami Titan IM)
        sounds.welcome()

        # TODO: Implementuj tutaj okno swojego komunikatora
        # Przykład:
        # frame = MyIMFrame(parent_frame)
        # frame.Show()

        sounds.dialog_open()
        wx.MessageBox("Moduł otwarty!", "Nazwa modułu", wx.OK | wx.ICON_INFORMATION, parent_frame)
    except Exception as e:
        print(f"[module_id] Error opening: {e}")


def get_status_text():
    """Zwróć sufiks statusu połączenia pokazywany po nazwie modułu w liście Titan IM.

    Zwróć pusty string jeśli nie połączono / brak statusu do pokazania.
    Przykłady: "- connected as jan", "- 3 nieprzeczytane"
    """
    return ""
```

## Wymagane funkcje

### open(parent_frame)
**Wymagana funkcja** wywoływana gdy użytkownik otwiera moduł:
```python
def open(parent_frame):
    """
    parent_frame: wx.Frame lub None dla trybu konsoli
    """
    sounds = _module.sounds  # Dostęp do Sound API
    sounds.welcome()  # Odtwórz dźwięk powitania

    # Utwórz i pokaż okno swojego komunikatora
    # ...
```

## Opcjonalne funkcje

### get_status_text()
Zwraca tekst statusu pokazywany po nazwie modułu:
```python
def get_status_text():
    """
    Returns:
        str: Sufiks statusu, np. "- connected as użytkownik" lub ""
    """
    if connected and username:
        return f"- connected as {username}"
    return ""
```

## Sound API (automatycznie wstrzykiwane)

Każdy moduł otrzymuje obiekt `sounds` przez `_module.sounds` z ujednoliconymi dźwiękami TitanNet/Titan IM.

### Główne kategorie dźwięków

#### Wiadomości
```python
sounds.new_message()        # Nowa wiadomość otrzymana
sounds.message_sent()       # Wiadomość wysłana
sounds.chat_message()       # Wiadomość czatu (w aktywnym czacie)
sounds.typing()             # Wskaźnik pisania
```

#### Obecność użytkowników
```python
sounds.user_online()        # Użytkownik zalogowany
sounds.user_offline()       # Użytkownik wylogowany
sounds.status_changed()     # Status użytkownika zmieniony
sounds.account_created()    # Nowe konto utworzone
```

#### Czaty/pokoje
```python
sounds.new_chat()           # Nowy czat lub pokój otwarty
sounds.new_replies()        # Nowe odpowiedzi (forum, wątek)
```

#### Połączenia głosowe
```python
sounds.call_connected()     # Połączenie głosowe nawiązane
sounds.ring_incoming()      # Dzwonek przychodzący
sounds.ring_outgoing()      # Dzwonek wychodzący
sounds.walkie_talkie_start()    # Push-to-talk aktywowany
sounds.walkie_talkie_end()      # Push-to-talk dezaktywowany
sounds.recording_start()    # Nagrywanie głosu rozpoczęte
sounds.recording_stop()     # Nagrywanie głosu zatrzymane
```

#### Pliki
```python
sounds.file_received()      # Nowy plik otrzymany
sounds.file_success()       # Operacja na pliku udana
sounds.file_error()         # Operacja na pliku nieudana
```

#### Ogólne powiadomienia
```python
sounds.notification()       # Ogólne powiadomienie
sounds.success()            # Powiadomienie sukcesu
sounds.error()              # Powiadomienie błędu
sounds.welcome()            # Moduł otwarty
sounds.goodbye()            # Moduł zamknięty / rozłączony
sounds.birthday()           # Powiadomienie urodzinowe
sounds.new_feed_post()      # Nowy post na kanale
sounds.moderation()         # Alert moderacji / broadcast
sounds.motd()               # Wiadomość dnia
sounds.app_update()         # Aktualizacja aplikacji/pakietu
```

#### Dźwięki UI - rdzenne
```python
sounds.focus(pan=0.5)       # Zmiana fokusu (stereo pan 0.0-1.0)
sounds.select()             # Wybór / akcja potwierdzona
sounds.click()              # Prosty klik
```

#### Dźwięki UI - okna dialogowe
```python
sounds.dialog_open()        # Okno dialogowe otwarte
sounds.dialog_close()       # Okno dialogowe zamknięte
sounds.window_open()        # Okno otwarte
sounds.window_close()       # Okno zamknięte
sounds.popup()              # Popup otwarty
sounds.popup_close()        # Popup zamknięty
sounds.msg_box()            # Message box otwarty
sounds.msg_box_close()      # Message box zamknięty
```

#### Dźwięki UI - menu kontekstowe
```python
sounds.context_menu()       # Menu kontekstowe otwarte
sounds.context_menu_close() # Menu kontekstowe zamknięte
```

#### Dźwięki UI - listy i nawigacja
```python
sounds.end_of_list()        # Koniec listy osiągnięty
sounds.section_change()     # Sekcja/zakładka zmieniona
sounds.switch_category()    # Kategoria przełączona
sounds.switch_list()        # Lista przełączona
sounds.focus_collapsed()    # Węzeł drzewa zwinięty
sounds.focus_expanded()     # Węzeł drzewa rozwinięty
```

#### Dźwięki UI - powiadomienia i stan okna
```python
sounds.notify_sound()       # Dźwięk powiadomienia (bez TTS)
sounds.tip()                # Podpowiedź / wskazówka
sounds.minimize()           # Okno zminimalizowane
sounds.restore()            # Okno przywrócone
```

#### Dźwięki systemowe
```python
sounds.connecting()         # Łączenie w toku
```

### TTS (Text-to-Speech) powiadomienia

```python
# Proste TTS z pozycjonowaniem stereo
sounds.speak("Połączony!", position=0.0, pitch_offset=0)

# Powiadomienie z automatycznym dźwiękiem + TTS (respektuje ustawienia TCE)
# Typy: 'error', 'success', 'info', 'warning', 'banned'
sounds.notify("Logowanie udane", 'success')
sounds.notify("Połączenie nieudane", 'error')
sounds.notify("Dostępna nowa aktualizacja", 'info')
sounds.notify("Przekroczony limit", 'warning')

# Powiadomienie tylko z TTS (bez efektu dźwiękowego)
sounds.notify("Odpowiedź opublikowana", 'success', play_sound_effect=False)
```

### Bezpośredni dostęp do dźwięków

```python
# Odtwórz dowolny plik dźwiękowy z katalogu sfx/
sounds.play('titannet/new_message.ogg')
sounds.play('core/FOCUS.ogg', pan=0.3)  # pan: 0.0 (lewo) do 1.0 (prawo)
```

Pełna dokumentacja API: `data/titanIM_modules/README.md`

## Kompletne przykłady kodu

### Przykład 1: Prosty klient czatu

Kompletny moduł IM otwierający okno czatu z listą kontaktów, wyświetlaniem wiadomości, polem wprowadzania wiadomości i pełną integracją Sound API.

**Plik: `data/titanIM_modules/SimpleChat/__im.TCE`**
```ini
[im_module]
name = Simple Chat
status = 0
description = Prosty klient czatu z kontaktami, wiadomościami i powiadomieniami dźwiękowymi

```

**Plik: `data/titanIM_modules/SimpleChat/init.py`**

```python
# -*- coding: utf-8 -*-
"""
Simple Chat - Titan IM external module for TCE Launcher
Prosty klient czatu demonstrujący kontakty, wiadomości i Sound API.
"""

import os
import sys
import threading
import time

# Dodaj katalog główny TCE do ścieżki
_MODULE_DIR = os.path.dirname(__file__)
_TCE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, '..', '..', '..'))
if _TCE_ROOT not in sys.path:
    sys.path.insert(0, _TCE_ROOT)

# Sound API - automatycznie wstrzykiwane przez menedżer modułów
_module = sys.modules[__name__]

# Stan połączenia dla tekstu statusu
_state = {
    "connected": False,
    "username": "",
    "unread": 0
}


# ---------------------------------------------------------------------------
# Okno czatu
# ---------------------------------------------------------------------------

class SimpleChatFrame:
    """Główne okno czatu z listą kontaktów, wyświetlaniem wiadomości i polem wprowadzania."""

    def __init__(self, parent_frame, sounds):
        import wx

        self.sounds = sounds
        self.frame = wx.Frame(parent_frame, title="Simple Chat", size=(700, 500))
        self.frame.Bind(wx.EVT_CLOSE, self._on_close)

        # --- Dane demo ---
        self.contacts = ["Alice", "Bob", "Charlie", "Diana", "Eve"]
        self.online = {"Alice", "Charlie", "Eve"}
        self.messages = {name: [] for name in self.contacts}
        self.current_contact = None

        # --- Layout ---
        main_panel = wx.Panel(self.frame)
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Lewo: lista kontaktów
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        left_sizer.Add(wx.StaticText(main_panel, label="Kontakty"), 0, wx.ALL, 5)

        self.contact_list = wx.ListBox(main_panel, style=wx.LB_SINGLE)
        self._refresh_contacts()
        self.contact_list.Bind(wx.EVT_LISTBOX, self._on_contact_select)
        self.contact_list.Bind(wx.EVT_RIGHT_DOWN, self._on_contact_right_click)
        left_sizer.Add(self.contact_list, 1, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(left_sizer, 1, wx.EXPAND)

        # Prawo: wiadomości + wprowadzanie
        right_sizer = wx.BoxSizer(wx.VERTICAL)
        right_sizer.Add(wx.StaticText(main_panel, label="Wiadomości"), 0, wx.ALL, 5)

        self.message_display = wx.TextCtrl(
            main_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2
        )
        right_sizer.Add(self.message_display, 1, wx.EXPAND | wx.ALL, 5)

        # Wiersz wprowadzania
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.message_input = wx.TextCtrl(main_panel, style=wx.TE_PROCESS_ENTER)
        self.message_input.Bind(wx.EVT_TEXT_ENTER, self._on_send)
        input_sizer.Add(self.message_input, 1, wx.EXPAND | wx.ALL, 5)

        send_btn = wx.Button(main_panel, label="Wyślij")
        send_btn.Bind(wx.EVT_BUTTON, self._on_send)
        input_sizer.Add(send_btn, 0, wx.ALL, 5)

        right_sizer.Add(input_sizer, 0, wx.EXPAND)
        main_sizer.Add(right_sizer, 2, wx.EXPAND)

        main_panel.SetSizer(main_sizer)

        # Symuluj połączenie
        self._connect()

    # --- Połączenie ---

    def _connect(self):
        """Symuluj łączenie się z serwerem czatu."""
        self.sounds.connecting()
        _state["connected"] = True
        _state["username"] = "You"
        self.sounds.notify("Połączono jako You", 'success')

        # Symuluj przychodzące wiadomości w tle
        self._sim_thread = threading.Thread(target=self._simulate_incoming, daemon=True)
        self._sim_thread.start()

    def _simulate_incoming(self):
        """Symuluj otrzymywanie wiadomości od kontaktów po opóźnieniu."""
        import wx
        time.sleep(3)
        greetings = [
            ("Alice", "Hej! Jak się masz?"),
            ("Charlie", "Widziałeś najnowszą aktualizację?"),
        ]
        for sender, text in greetings:
            self.messages[sender].append(f"{sender}: {text}")
            _state["unread"] += 1
            wx.CallAfter(self._on_incoming_message, sender)
            time.sleep(2)

    def _on_incoming_message(self, sender):
        """Obsłuż nowo otrzymaną wiadomość w wątku GUI."""
        self.sounds.new_message()
        self._refresh_contacts()
        if self.current_contact == sender:
            self._show_messages(sender)

    # --- Lista kontaktów ---

    def _refresh_contacts(self):
        self.contact_list.Clear()
        for name in self.contacts:
            status = " (online)" if name in self.online else ""
            unread = len([m for m in self.messages[name] if m.startswith(name)])
            tag = f" [{unread} nowych]" if unread else ""
            self.contact_list.Append(f"{name}{status}{tag}")

    def _on_contact_select(self, event):
        idx = self.contact_list.GetSelection()
        if idx == -1:
            return
        self.current_contact = self.contacts[idx]
        self.sounds.select()
        self._show_messages(self.current_contact)

    def _on_contact_right_click(self, event):
        import wx
        idx = self.contact_list.HitTest(event.GetPosition())
        if idx == -1:
            return
        self.contact_list.SetSelection(idx)
        self.current_contact = self.contacts[idx]

        menu = wx.Menu()
        item_info = menu.Append(wx.ID_ANY, "Pokaż info")
        item_clear = menu.Append(wx.ID_ANY, "Wyczyść historię")

        self.frame.Bind(wx.EVT_MENU, self._on_view_info, item_info)
        self.frame.Bind(wx.EVT_MENU, self._on_clear_history, item_clear)

        self.sounds.context_menu()
        self.frame.PopupMenu(menu)
        menu.Destroy()
        self.sounds.context_menu_close()

    def _on_view_info(self, event):
        import wx
        name = self.current_contact
        if not name:
            return
        status = "Online" if name in self.online else "Offline"
        self.sounds.dialog_open()
        wx.MessageBox(f"Kontakt: {name}\nStatus: {status}", "Info kontaktu",
                      wx.OK | wx.ICON_INFORMATION, self.frame)
        self.sounds.dialog_close()

    def _on_clear_history(self, event):
        if self.current_contact:
            self.messages[self.current_contact].clear()
            self._show_messages(self.current_contact)
            self.sounds.notify("Historia wyczyszczona", 'info')

    # --- Wiadomości ---

    def _show_messages(self, contact):
        self.message_display.SetValue("\n".join(self.messages[contact]))

    def _on_send(self, event):
        text = self.message_input.GetValue().strip()
        if not text or not self.current_contact:
            self.sounds.error()
            return
        self.messages[self.current_contact].append(f"You: {text}")
        self.message_input.SetValue("")
        self._show_messages(self.current_contact)
        self.sounds.message_sent()

    # --- Zamknięcie ---

    def _on_close(self, event):
        _state["connected"] = False
        _state["username"] = ""
        _state["unread"] = 0
        self.sounds.goodbye()
        self.frame.Destroy()

    def show(self):
        self.frame.Show()


# ---------------------------------------------------------------------------
# Interfejs modułu
# ---------------------------------------------------------------------------

def open(parent_frame):
    """Otwórz okno czatu.

    Wywoływane gdy użytkownik wybierze ten moduł z listy Titan IM.
    parent_frame: wx.Frame lub None - referencja okna rodzica
    """
    try:
        sounds = _module.sounds
        sounds.welcome()
        chat = SimpleChatFrame(parent_frame, sounds)
        chat.show()
        sounds.window_open()
    except Exception as e:
        print(f"[SimpleChat] Error opening: {e}")
        try:
            _module.sounds.notify(f"Nie udało się otworzyć: {e}", 'error')
        except Exception:
            pass


def get_status_text():
    """Zwróć sufiks statusu połączenia pokazywany po nazwie modułu w liście Titan IM.

    Przykłady: "- connected as You", "- 2 nieprzeczytane"
    """
    if _state["connected"] and _state["username"]:
        parts = [f"- connected as {_state['username']}"]
        if _state["unread"] > 0:
            parts.append(f", {_state['unread']} nieprzeczytane")
        return "".join(parts)
    return ""
```

---

### Przykład 2: Czytnik RSS

Prostszy moduł IM który pobiera i wyświetla elementy kanału RSS, otwierając je w domyślnej przeglądarce.

**Plik: `data/titanIM_modules/RSSReader/__im.TCE`**
```ini
[im_module]
name = RSS Feed Reader
status = 0
description = Czytnik kanałów RSS z integracją przeglądarki i powiadomieniami dźwiękowymi

```

**Plik: `data/titanIM_modules/RSSReader/init.py`**

```python
# -*- coding: utf-8 -*-
"""
RSS Feed Reader - Titan IM external module for TCE Launcher
Pobiera kanały RSS i wyświetla elementy w dostępnej liście.
"""

import os
import sys
import threading
import webbrowser

# Dodaj katalog główny TCE do ścieżki
_MODULE_DIR = os.path.dirname(__file__)
_TCE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, '..', '..', '..'))
if _TCE_ROOT not in sys.path:
    sys.path.insert(0, _TCE_ROOT)

# Sound API - automatycznie wstrzykiwane przez menedżer modułów
_module = sys.modules[__name__]

# Stan dla tekstu statusu
_state = {
    "unread": 0
}

# Domyślny URL kanału (można zmienić w oknie czytnika)
DEFAULT_FEED_URL = "https://feeds.bbci.co.uk/news/rss.xml"


# ---------------------------------------------------------------------------
# Pomocniki parsowania RSS
# ---------------------------------------------------------------------------

def _fetch_feed(url):
    """Pobierz i sparsuj kanał RSS. Zwraca listę dict z title, link, description."""
    import urllib.request
    import xml.etree.ElementTree as ET

    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TCE-RSSReader/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        root = ET.fromstring(data)

        # Obsługa RSS 2.0 (<channel><item>) i Atom (<entry>)
        # RSS 2.0
        for item in root.iter("item"):
            title = item.findtext("title", "Brak tytułu")
            link = item.findtext("link", "")
            desc = item.findtext("description", "")
            items.append({"title": title, "link": link, "description": desc})

        # Fallback Atom
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title = entry.findtext("atom:title", "Brak tytułu", ns)
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                desc = entry.findtext("atom:summary", "", ns)
                items.append({"title": title, "link": link, "description": desc})
    except Exception as e:
        raise RuntimeError(f"Nie udało się pobrać kanału: {e}")

    return items


# ---------------------------------------------------------------------------
# Okno czytnika
# ---------------------------------------------------------------------------

class RSSReaderFrame:
    """Okno czytnika kanałów RSS z listą kanałów i integracją przeglądarki."""

    def __init__(self, parent_frame, sounds):
        import wx

        self.sounds = sounds
        self.items = []
        self.feed_url = DEFAULT_FEED_URL

        self.frame = wx.Frame(parent_frame, title="RSS Feed Reader", size=(600, 450))
        self.frame.Bind(wx.EVT_CLOSE, self._on_close)

        panel = wx.Panel(self.frame)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Wprowadzanie URL kanału
        url_sizer = wx.BoxSizer(wx.HORIZONTAL)
        url_sizer.Add(wx.StaticText(panel, label="URL kanału:"), 0,
                       wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.url_input = wx.TextCtrl(panel, value=self.feed_url)
        url_sizer.Add(self.url_input, 1, wx.EXPAND | wx.ALL, 5)
        refresh_btn = wx.Button(panel, label="Odśwież")
        refresh_btn.Bind(wx.EVT_BUTTON, self._on_refresh)
        url_sizer.Add(refresh_btn, 0, wx.ALL, 5)
        sizer.Add(url_sizer, 0, wx.EXPAND)

        # Etykieta statusu
        self.status_label = wx.StaticText(panel, label="Naciśnij Odśwież aby załadować kanał.")
        sizer.Add(self.status_label, 0, wx.ALL, 5)

        # Lista elementów kanału
        self.item_list = wx.ListBox(panel)
        self.item_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_item_activate)
        self.item_list.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        sizer.Add(self.item_list, 1, wx.EXPAND | wx.ALL, 5)

        # Wyświetlanie opisu
        self.desc_display = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2
        )
        sizer.Add(self.desc_display, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Pokaż opis przy wyborze
        self.item_list.Bind(wx.EVT_LISTBOX, self._on_item_select)

        panel.SetSizer(sizer)

        # Auto-załaduj kanał
        self._on_refresh(None)

    # --- Ładowanie kanału ---

    def _on_refresh(self, event):
        """Załaduj kanał w wątku w tle."""
        import wx
        self.feed_url = self.url_input.GetValue().strip()
        if not self.feed_url:
            self.sounds.error()
            return
        self.status_label.SetLabel("Ładowanie...")
        self.sounds.connecting()
        threading.Thread(target=self._load_feed, daemon=True).start()

    def _load_feed(self):
        """Wątek w tle: pobierz kanał i zaktualizuj UI."""
        import wx
        try:
            items = _fetch_feed(self.feed_url)
            wx.CallAfter(self._on_feed_loaded, items)
        except Exception as e:
            wx.CallAfter(self._on_feed_error, str(e))

    def _on_feed_loaded(self, items):
        self.items = items
        _state["unread"] = len(items)

        self.item_list.Clear()
        for item in items:
            self.item_list.Append(item["title"])

        self.status_label.SetLabel(f"Załadowano {len(items)} elementów.")
        self.desc_display.SetValue("")

        if items:
            self.sounds.new_feed_post()
            self.sounds.notify(f"Załadowano {len(items)} elementów kanału", 'success')
        else:
            self.sounds.notify("Kanał jest pusty", 'info')

    def _on_feed_error(self, error_msg):
        self.status_label.SetLabel(f"Błąd: {error_msg}")
        self.sounds.notify(f"Błąd kanału: {error_msg}", 'error')

    # --- Interakcja z elementami ---

    def _on_item_select(self, event):
        idx = self.item_list.GetSelection()
        if idx == -1 or idx >= len(self.items):
            return
        self.sounds.select()
        desc = self.items[idx].get("description", "Brak opisu.")
        self.desc_display.SetValue(desc)

    def _on_item_activate(self, event):
        """Otwórz wybrany element kanału w domyślnej przeglądarce."""
        self._open_selected_item()

    def _on_key_down(self, event):
        if event.GetKeyCode() == 13:  # Enter
            self._open_selected_item()
        else:
            event.Skip()

    def _open_selected_item(self):
        idx = self.item_list.GetSelection()
        if idx == -1 or idx >= len(self.items):
            self.sounds.error()
            return
        link = self.items[idx].get("link", "")
        if link:
            webbrowser.open(link)
            self.sounds.notify("Otwarto w przeglądarce", 'info')
            if _state["unread"] > 0:
                _state["unread"] -= 1
        else:
            self.sounds.notify("Brak linku dla tego elementu", 'warning')

    # --- Zamknięcie ---

    def _on_close(self, event):
        _state["unread"] = 0
        self.sounds.goodbye()
        self.frame.Destroy()

    def show(self):
        self.frame.Show()


# ---------------------------------------------------------------------------
# Interfejs modułu
# ---------------------------------------------------------------------------

def open(parent_frame):
    """Otwórz okno czytnika kanałów RSS.

    Wywoływane gdy użytkownik wybierze ten moduł z listy Titan IM.
    parent_frame: wx.Frame lub None - referencja okna rodzica
    """
    try:
        sounds = _module.sounds
        sounds.welcome()
        reader = RSSReaderFrame(parent_frame, sounds)
        reader.show()
        sounds.window_open()
    except Exception as e:
        print(f"[RSSReader] Error opening: {e}")
        try:
            _module.sounds.notify(f"Nie udało się otworzyć: {e}", 'error')
        except Exception:
            pass


def get_status_text():
    """Zwróć sufiks statusu pokazywany po nazwie modułu w liście Titan IM.

    Przykład: "- 5 nieprzeczytanych"
    """
    if _state["unread"] > 0:
        return f"- {_state['unread']} nieprzeczytanych"
    return ""
```

## Struktura katalogów

```
data/titanIM_modules/nazwa_modułu/
├── init.py              # Główny plik modułu (NIE __init__.py!)
└── __im.TCE             # Konfiguracja modułu
```

## Testowanie modułów

1. Umieść moduł w `data/titanIM_modules/nazwa_modułu/`
2. Upewnij się że plik to `init.py` a nie `__init__.py`
3. Sprawdź format `__im.TCE` (INI, wielkie litery .TCE)
4. Uruchom Titan
5. Otwórz Titan IM (w GUI, IUI lub trybie Klango)
6. Sprawdź czy moduł pojawia się w liście komunikatorów
7. Kliknij/wybierz moduł — powinna wywołać się funkcja `open(parent_frame)`
8. Jeśli `get_status_text()` jest zaimplementowane, sprawdź czy pokazuje się po nazwie modułu

## Jak moduły pojawiają się w każdym interfejsie

- **GUI** (`src/ui/gui.py`): Wymienione w listbox sieci, status pokazywany inline
- **Invisible UI** (`src/ui/invisibleui.py`): Wymienione w elementach kategorii Titan IM
- **Tryb Klango** (`src/system/klangomode.py`): Wymienione w podmenu Titan IM

## Przykład referencyjny

- **ExampleIM** (`data/titanIM_modules/ExampleIM/`): Pokazuje Sound API z przyciskami demo
  - Domyślnie wyłączony (`status = 1`)
  - Demonstruje `sounds.welcome()`, `sounds.notify()`, dźwięki obecności, itp.

## Najważniejsze wskazówki

1. **Zawsze implementuj `open(parent_frame)`** — wymagane
2. **Używaj `_module.sounds` dla ujednoliconych dźwięków** — takich samych jak Telegram, Titan-Net
3. **Implementuj `get_status_text()` dla informacji o połączeniu** — użytkownicy lubią widzieć status
4. **Gracefully obsługuj `parent_frame=None`** — obsługuj tryb konsoli
5. **Testuj we wszystkich trybach** — GUI, Invisible UI i Klango
6. **Używaj wx.CallAfter dla aktualizacji GUI z wątków** — bezpieczne dla wątków
7. **Dodawaj dźwięki dla lepszego UX** — `new_message()`, `message_sent()`, `user_online()`, itp.
8. **Obsługuj zamknięcie gracefully** — wywołaj `sounds.goodbye()`, wyczyść stan

Moduły Titan IM umożliwiają dodawanie własnych komunikatorów, kanałów społecznościowych i narzędzi do TCE Launcher bez modyfikowania kodu głównego. Dzięki ujednoliconemu Sound API wszystkie moduły mają spójne doświadczenie dźwiękowe, takie same jak wbudowane integracje (Telegram, EltenLink, Titan-Net).

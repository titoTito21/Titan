import wx
import os
from sound import play_sound
from settings import get_setting
from translation import _

class TitanHelp(wx.Frame):
    def __init__(self, *args, **kw):
        super(TitanHelp, self).__init__(*args, **kw)
        self.InitUI()

    def InitUI(self):
        self.SetTitle(_("Titan Help"))
        self.SetSize((600, 400))
        self.Centre()

        self.panel = wx.Panel(self)
        self.vbox = wx.BoxSizer(wx.VERTICAL)
        self.panel.SetSizer(self.vbox)

        self.Bind(wx.EVT_CLOSE, self.on_close)

        # Lista nagłówków
        self.header_list = wx.ListBox(self.panel, style=wx.LB_SINGLE)
        self.header_list.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.header_list.Bind(wx.EVT_LISTBOX, self.on_header_selected)
        self.vbox.Add(self.header_list, 0, wx.EXPAND | wx.ALL, 10)

        # Pole tekstowe dla treści
        self.content_area = wx.TextCtrl(
            self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY
        )
        self.vbox.Add(self.content_area, 1, wx.EXPAND | wx.ALL, 10)

        # Załaduj dane pomocy
        self.load_help_data()

        self.Layout()

    def get_help_file_path(self):
        """Zwraca ścieżkę do pliku pomocy w odpowiednim języku."""
        language = get_setting('language', 'pl')
        
        # Sprawdź plik specyficzny dla języka
        if language != 'pl':
            help_file_name = f"Titan_help_{language}.tdoc"
            help_file_path = os.path.join("data", "docu", help_file_name)
            if os.path.exists(help_file_path):
                return help_file_path
        
        # Fallback do domyślnego pliku
        return os.path.join("data", "docu", "Titan_help.tdoc")

    def load_help_data(self):
        """Wczytaj dane pomocy z pliku."""
        help_file_path = self.get_help_file_path()
        
        if not os.path.exists(help_file_path):
            self.content_area.SetValue(_("Help file not found."))
            return

        try:
            # Use a timeout-safe file reading approach
            with open(help_file_path, "r", encoding="utf-8") as f:
                # Read in chunks to prevent hanging on large files
                help_data = ""
                chunk_size = 8192
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    help_data += chunk
                    # Process events to prevent UI freezing
                    wx.GetApp().Yield()
        except (IOError, OSError, UnicodeDecodeError) as e:
            self.content_area.SetValue(_("Error reading help file: {}").format(str(e)))
            return
        except Exception as e:
            self.content_area.SetValue(_("Unexpected error: {}").format(str(e)))
            return

        # Parsuj dane pomocy
        try:
            self.headers, self.content_map = self.parse_help_data(help_data)
            if self.headers:
                self.header_list.Set(self.headers)
                self.header_list.SetSelection(0)
                self.display_content(self.headers[0])
            else:
                self.content_area.SetValue(_("No help content found."))
        except Exception as e:
            self.content_area.SetValue(_("Error parsing help data: {}").format(str(e)))

    def parse_help_data(self, help_data):
        """Parsuje dane pomocy do nagłówków i treści."""
        headers = []
        content_map = {}
        current_header = None
        content_lines = []

        for line in help_data.splitlines():
            if line.startswith("#"):
                if current_header:
                    content_map[current_header] = "\n".join(content_lines)
                current_header = line[1:].strip()
                headers.append(current_header)
                content_lines = []
            else:
                content_lines.append(line)

        if current_header:
            content_map[current_header] = "\n".join(content_lines)

        return headers, content_map

    def display_content(self, header):
        """Wyświetla treść wybranego nagłówka."""
        if not hasattr(self, 'content_map') or not self.content_map:
            return
        content = self.content_map.get(header, _("No content available for this section."))
        self.content_area.SetValue(content)

    def on_header_selected(self, event):
        """Obsługuje wybór nagłówka."""
        try:
            selected_header = self.header_list.GetStringSelection()
            if selected_header:
                self.display_content(selected_header)
                play_sound("focus.ogg")
        except Exception as e:
            print(f"Error in header selection: {e}")

    def on_key_down(self, event):
        """Obsługa klawiszy nawigacji."""
        try:
            keycode = event.GetKeyCode()
            if keycode == wx.WXK_ESCAPE:
                self.hide_help()
            elif keycode in [wx.WXK_RETURN, wx.WXK_SPACE]:
                # Allow Enter/Space to select items
                selected_header = self.header_list.GetStringSelection()
                if selected_header:
                    self.display_content(selected_header)
                    play_sound("focus.ogg")
            else:
                event.Skip()
        except Exception as e:
            print(f"Error in key handling: {e}")
            event.Skip()

    def show_help(self):
        """Pokaż okno pomocy."""
        try:
            self.Show()
            play_sound("uiopen.ogg")
            # Ensure focus is set properly with a small delay
            wx.CallAfter(self.header_list.SetFocus)
        except Exception as e:
            print(f"Error showing help window: {e}")

    def hide_help(self):
        """Ukryj okno pomocy."""
        try:
            self.Hide()
            play_sound("uiclose.ogg")
        except Exception as e:
            print(f"Error hiding help window: {e}")

    def on_close(self, event):
        """Obsługuje zamykanie okna."""
        try:
            self.hide_help()
            # Only veto if we want to keep the window alive
            # Check if the app is shutting down
            if wx.GetApp() and not wx.GetApp().IsMainLoopRunning():
                event.Skip()  # Allow actual closing during app shutdown
            else:
                event.Veto()  # Just hide the window normally
        except Exception as e:
            print(f"Error in close handler: {e}")
            event.Skip()

# Globalna instancja pomocy
_help_instance = None

def get_help_instance(parent=None):
    """Zwraca globalną instancję pomocy."""
    global _help_instance
    if _help_instance is None:
        _help_instance = TitanHelp(parent)
    return _help_instance

def show_help():
    """Pokaż okno pomocy."""
    try:
        help_instance = get_help_instance()
        if help_instance and help_instance.IsShown():
            help_instance.hide_help()
        elif help_instance:
            help_instance.show_help()
    except Exception as e:
        print(f"Error in show_help: {e}")

def toggle_help():
    """Przełącz widoczność okna pomocy."""
    show_help()
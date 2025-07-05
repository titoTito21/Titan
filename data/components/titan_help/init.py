import wx
import os
from sound import play_sound

class TitanHelp(wx.Frame):
    def __init__(self, *args, **kw):
        super(TitanHelp, self).__init__(*args, **kw)
        self.InitUI()

    def InitUI(self):
        self.SetTitle("Pomoc Titana")
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

    def load_help_data(self):
        """Wczytaj dane pomocy z pliku."""
        help_file_path = os.path.join("data", "docu", "Titan_help.tdoc")
        if not os.path.exists(help_file_path):
            self.content_area.SetValue("Nie znaleziono pliku pomocy.")
            return

        try:
            with open(help_file_path, "r", encoding="utf-8") as f:
                help_data = f.read()
        except Exception as e:
            self.content_area.SetValue(f"Błąd podczas odczytu pliku pomocy: {e}")
            return

        # Parsuj dane pomocy
        self.headers, self.content_map = self.parse_help_data(help_data)
        self.header_list.Set(self.headers)
        if self.headers:
            self.header_list.SetSelection(0)
            self.display_content(self.headers[0])

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
        self.content_area.SetValue(self.content_map.get(header, ""))

    def on_header_selected(self, event):
        """Obsługuje wybór nagłówka."""
        selected_header = self.header_list.GetStringSelection()
        self.display_content(selected_header)
        play_sound("focus.ogg")  # Dźwięk przy zmianie nagłówka

    def on_key_down(self, event):
        """Obsługa klawiszy nawigacji."""
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_ESCAPE:  # Zamknij okno pomocy
            self.hide_help()
        else:
            event.Skip()

    def show_help(self):
        """Pokaż okno pomocy."""
        self.Show()
        play_sound("uiopen.ogg")  # Dźwięk otwierania
        self.header_list.SetFocus()

    def hide_help(self):
        """Ukryj okno pomocy."""
        self.Hide()
        play_sound("uiclose.ogg")  # Dźwięk zamykania

    def on_close(self, event):
        """Obsługuje zamykanie okna."""
        self.hide_help()
        event.Veto()  # Zapobiega trwałemu zamknięciu okna


def initialize(app):
    titan_help = TitanHelp(None)

    def toggle_help():
        if titan_help.IsShown():
            titan_help.hide_help()
        else:
            titan_help.show_help()

    # Powiąż klawisz F1 do przełączania pomocy
    app.Bind(wx.EVT_CHAR_HOOK, lambda evt: toggle_help() if evt.GetKeyCode() == wx.WXK_F1 else evt.Skip())

    return titan_help

def add_menu(menubar):
    pass  # Opcjonalnie dodaj pozycje menu, jeśli wymagane.
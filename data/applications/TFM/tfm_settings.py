# tfm_settings.py
import configparser
import os
import wx

class SettingsManager:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config_path = os.path.join(os.getenv('APPDATA'), 'titosoft', 'Titan', 'appsettings', 'tfm.ini')
        if not os.path.exists(self.config_path):
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            self.create_default_settings()
        self.load_settings()
        self.ensure_new_settings()

    def create_default_settings(self):
        self.config['View'] = {
            'view': 'name, date, type',
            'show_hidden': 'false',
            'show_extensions': 'true'
        }
        self.config['Sort'] = {
            'sort_mode': 'name'
        }
        # Nowe sekcje i ustawienia domyślne
        self.config['Interface'] = {
            'confirm_delete': 'true',  # potwierdzenie przed usunięciem
            'explorer_view_mode': 'klasyczny', # inne: lista, commander, wiele kart
            'window_title_mode': 'nazwa aplikacji', # inne: nazwa katalogu, ścieżka
            'copy_dialog_mode': 'klasyczny' # inne: systemowy
        }

        self.save_settings()

    def load_settings(self):
        self.config.read(self.config_path)

    def ensure_new_settings(self):
        # Sprawdź czy istnieją nowe ustawienia, jeśli nie to ustaw je domyślnie
        changed = False
        if 'Interface' not in self.config:
            self.config['Interface'] = {}
            changed = True
        if 'confirm_delete' not in self.config['Interface']:
            self.config['Interface']['confirm_delete'] = 'true'
            changed = True
        if 'explorer_view_mode' not in self.config['Interface']:
            self.config['Interface']['explorer_view_mode'] = 'klasyczny'
            changed = True
        if 'window_title_mode' not in self.config['Interface']:
            self.config['Interface']['window_title_mode'] = 'nazwa aplikacji'
            changed = True
        if 'copy_dialog_mode' not in self.config['Interface']:
            self.config['Interface']['copy_dialog_mode'] = 'klasyczny'
            changed = True

        if changed:
            self.save_settings()

    def save_settings(self):
        with open(self.config_path, 'w') as configfile:
            self.config.write(configfile)

    # Metody pobierające i ustawiające poszczególne opcje:
    def get_view_settings(self):
        return self.config['View']['view'].split(', ')

    def get_show_hidden(self):
        return self.config['View'].getboolean('show_hidden')

    def get_show_extensions(self):
        return self.config['View'].getboolean('show_extensions')

    def set_view_settings(self, view_settings):
        self.config['View']['view'] = ', '.join(view_settings)
        self.save_settings()

    def set_show_hidden(self, show_hidden):
        self.config['View']['show_hidden'] = str(show_hidden).lower()
        self.save_settings()

    def set_show_extensions(self, show_extensions):
        self.config['View']['show_extensions'] = str(show_extensions).lower()
        self.save_settings()

    def get_sort_mode(self):
        return self.config['Sort']['sort_mode']

    def set_sort_mode(self, sort_mode):
        self.config['Sort']['sort_mode'] = sort_mode
        self.save_settings()

    # Nowe getters i setters dla interfejsu
    def get_confirm_delete(self):
        return self.config['Interface'].getboolean('confirm_delete')

    def set_confirm_delete(self, value):
        self.config['Interface']['confirm_delete'] = str(value).lower()
        self.save_settings()

    def get_explorer_view_mode(self):
        return self.config['Interface']['explorer_view_mode']

    def set_explorer_view_mode(self, mode):
        self.config['Interface']['explorer_view_mode'] = mode
        self.save_settings()

    def get_window_title_mode(self):
        return self.config['Interface']['window_title_mode']

    def set_window_title_mode(self, mode):
        self.config['Interface']['window_title_mode'] = mode
        self.save_settings()

    def get_copy_dialog_mode(self):
        return self.config['Interface']['copy_dialog_mode']

    def set_copy_dialog_mode(self, mode):
        self.config['Interface']['copy_dialog_mode'] = mode
        self.save_settings()

class SettingsDialog(wx.Dialog):
    def __init__(self, parent, settings):
        wx.Dialog.__init__(self, parent, title="Ustawienia Eksploratora", size=(500, 400))
        self.settings = settings

        panel = wx.Panel(self)
        notebook = wx.Notebook(panel)

        # Panel Ogólne
        general_panel = wx.Panel(notebook)
        self.show_hidden_checkbox = wx.CheckBox(general_panel, label="Pokaż ukryte pliki")
        self.show_hidden_checkbox.SetValue(self.settings.get_show_hidden())

        self.show_extensions_checkbox = wx.CheckBox(general_panel, label="Pokaż rozszerzenia plików")
        self.show_extensions_checkbox.SetValue(self.settings.get_show_extensions())

        self.confirm_delete_checkbox = wx.CheckBox(general_panel, label="Potwierdzenie przed usunięciem")
        self.confirm_delete_checkbox.SetValue(self.settings.get_confirm_delete())

        view_box = wx.StaticBox(general_panel, label="Wyświetlanie danych pliku")
        view_sizer = wx.StaticBoxSizer(view_box, wx.VERTICAL)

        self.view_name = wx.CheckBox(general_panel, label="Nazwa")
        self.view_date = wx.CheckBox(general_panel, label="Data modyfikacji")
        self.view_type = wx.CheckBox(general_panel, label="Typ")

        current_view = self.settings.get_view_settings()
        self.view_name.SetValue('name' in current_view)
        self.view_date.SetValue('date' in current_view)
        self.view_type.SetValue('type' in current_view)

        view_sizer.Add(self.view_name, 0, wx.ALL, 5)
        view_sizer.Add(self.view_date, 0, wx.ALL, 5)
        view_sizer.Add(self.view_type, 0, wx.ALL, 5)

        general_sizer = wx.BoxSizer(wx.VERTICAL)
        general_sizer.Add(self.show_hidden_checkbox, 0, wx.ALL, 10)
        general_sizer.Add(self.show_extensions_checkbox, 0, wx.ALL, 10)
        general_sizer.Add(self.confirm_delete_checkbox, 0, wx.ALL, 10)
        general_sizer.Add(view_sizer, 0, wx.ALL | wx.EXPAND, 10)
        general_panel.SetSizer(general_sizer)

        # Panel Wygląd
        appearance_panel = wx.Panel(notebook)

        # Widok eksploratora
        self.explorer_view_choice = wx.Choice(appearance_panel, choices=["lista", "commander", "klasyczny", "wiele kart"])
        self.explorer_view_choice.SetStringSelection(self.settings.get_explorer_view_mode())

        # Tytuł okna
        self.window_title_choice = wx.Choice(appearance_panel, choices=["nazwa aplikacji", "nazwa katalogu", "ścieżka"])
        self.window_title_choice.SetStringSelection(self.settings.get_window_title_mode())

        # Dialog kopiowania
        self.copy_dialog_choice = wx.Choice(appearance_panel, choices=["klasyczny", "systemowy"])
        self.copy_dialog_choice.SetStringSelection(self.settings.get_copy_dialog_mode())

        appearance_sizer = wx.BoxSizer(wx.VERTICAL)

        explorer_view_box = wx.StaticBox(appearance_panel, label="Widok Eksploratora")
        explorer_view_sizer = wx.StaticBoxSizer(explorer_view_box, wx.VERTICAL)
        explorer_view_sizer.Add(wx.StaticText(appearance_panel, label="Tryb widoku eksploratora:"), 0, wx.ALL, 5)
        explorer_view_sizer.Add(self.explorer_view_choice, 0, wx.ALL, 5)

        window_title_box = wx.StaticBox(appearance_panel, label="Tytuł okna")
        window_title_sizer = wx.StaticBoxSizer(window_title_box, wx.VERTICAL)
        window_title_sizer.Add(wx.StaticText(appearance_panel, label="Tryb tytułu okna:"), 0, wx.ALL, 5)
        window_title_sizer.Add(self.window_title_choice, 0, wx.ALL, 5)

        copy_dialog_box = wx.StaticBox(appearance_panel, label="Dialog kopiowania plików")
        copy_dialog_sizer = wx.StaticBoxSizer(copy_dialog_box, wx.VERTICAL)
        copy_dialog_sizer.Add(wx.StaticText(appearance_panel, label="Tryb dialogu kopiowania:"), 0, wx.ALL, 5)
        copy_dialog_sizer.Add(self.copy_dialog_choice, 0, wx.ALL, 5)

        appearance_sizer.Add(explorer_view_sizer, 0, wx.ALL | wx.EXPAND, 10)
        appearance_sizer.Add(window_title_sizer, 0, wx.ALL | wx.EXPAND, 10)
        appearance_sizer.Add(copy_dialog_sizer, 0, wx.ALL | wx.EXPAND, 10)

        appearance_panel.SetSizer(appearance_sizer)

        notebook.AddPage(general_panel, "Ogólne")
        notebook.AddPage(appearance_panel, "Wygląd")

        save_button = wx.Button(panel, label="Zatwierdź")
        cancel_button = wx.Button(panel, label="Anuluj")

        self.Bind(wx.EVT_BUTTON, self.on_save, save_button)
        self.Bind(wx.EVT_BUTTON, self.on_cancel, cancel_button)

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(notebook, 1, wx.ALL | wx.EXPAND, 10)
        main_sizer.Add(save_button, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        main_sizer.Add(cancel_button, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        panel.SetSizer(main_sizer)

    def on_save(self, event):
        self.settings.set_show_hidden(self.show_hidden_checkbox.GetValue())
        self.settings.set_show_extensions(self.show_extensions_checkbox.GetValue())
        self.settings.set_confirm_delete(self.confirm_delete_checkbox.GetValue())

        selected_view = []
        if self.view_name.GetValue():
            selected_view.append('name')
        if self.view_date.GetValue():
            selected_view.append('date')
        if self.view_type.GetValue():
            selected_view.append('type')
        self.settings.set_view_settings(selected_view)

        # Zapis ustawień z zakładki Wygląd
        self.settings.set_explorer_view_mode(self.explorer_view_choice.GetStringSelection())
        self.settings.set_window_title_mode(self.window_title_choice.GetStringSelection())
        self.settings.set_copy_dialog_mode(self.copy_dialog_choice.GetStringSelection())

        self.EndModal(wx.ID_OK)

    def on_cancel(self, event):
        self.EndModal(wx.ID_CANCEL)

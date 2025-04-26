# tfm_settings.py
import configparser
import os
import wx
import platform # Import platform to check OS

class SettingsManager:
    def __init__(self):
        self.config = configparser.ConfigParser()

        # Using wx.StandardPaths for a more standard and cross-platform approach
        # This requires a wx.App instance to be created before SettingsManager is initialized
        # If SettingsManager can be initialized before wx.App, the old method might be needed first,
        # or pass the config path to the constructor.
        try:
            # Ensure a wx.App instance exists before using wx.StandardPaths
            # This check helps prevent errors if the manager is initialized too early
            if wx.App.GetInstance() is None:
                # Fallback to environment variables/home directory if wx.App is not available yet
                print("Warning: wx.App instance not found for config path. Using fallback logic.")
                self.config_path = self._get_fallback_config_path()
            else:
                 app_name = "Titan" # Or get this from a central application constant
                 vendor_name = "Titosoft" # Or get this from a central application constant
                 standard_paths = wx.StandardPaths.Get()
                 config_dir = standard_paths.GetUserConfigDir()
                 # Construct the path similar to the original structure but within the standard config dir
                 self.config_path = os.path.join(config_dir, vendor_name, app_name, 'appsettings', 'tfm.ini')

        except Exception as e:
             print(f"Error using wx.StandardPaths for config path: {e}. Falling back to environment variables/home directory.")
             self.config_path = self._get_fallback_config_path()


        if not os.path.exists(self.config_path):
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            self.create_default_settings()
        self.load_settings()
        self.ensure_new_settings()

    def _get_fallback_config_path(self):
        """Provides a fallback configuration path if wx.StandardPaths is not usable."""
        system = platform.system()
        if system == 'Windows':
            # Use APPDATA on Windows as before
            return os.path.join(os.getenv('APPDATA'), 'Titosoft', 'Titan', 'appsettings', 'tfm.ini')
        elif system == 'Darwin':  # macOS
            # Use hidden directory in home for macOS
             return os.path.join(os.path.expanduser('~'), '.titosoft', 'titan', 'appsettings', 'tfm.ini')
        else:  # Assume Linux
            # Use hidden directory in home for Linux (following XDG Base Directory Specification loosely)
             return os.path.join(os.path.expanduser('~'), '.config', 'titosoft', 'titan', 'appsettings', 'tfm.ini')


    def create_default_settings(self):
        self.config['View'] = {
            'view': 'name, date, type',
            'show_hidden': 'false',
            'show_extensions': 'true'
        }
        self.config['Sort'] = {
            'sort_mode': 'name'
        }
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
        # Ensure the directory exists before saving
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        try:
            with open(self.config_path, 'w') as configfile:
                self.config.write(configfile)
        except Exception as e:
             print(f"Error saving settings to {self.config_path}: {e}")


    # Metody pobierające i ustawiające poszczególne opcje:
    def get_view_settings(self):
        return self.config.get('View', 'view', fallback='name, date, type').split(', ')

    def get_show_hidden(self):
        return self.config.getboolean('View', 'show_hidden', fallback=False)

    def get_show_extensions(self):
        return self.config.getboolean('View', 'show_extensions', fallback=True)

    def set_view_settings(self, view_settings):
        if 'View' not in self.config: self.config['View'] = {}
        self.config['View']['view'] = ', '.join(view_settings)
        self.save_settings()

    def set_show_hidden(self, show_hidden):
        if 'View' not in self.config: self.config['View'] = {}
        self.config['View']['show_hidden'] = str(show_hidden).lower()
        self.save_settings()

    def set_show_extensions(self, show_extensions):
        if 'View' not in self.config: self.config['View'] = {}
        self.config['View']['show_extensions'] = str(show_extensions).lower()
        self.save_settings()

    def get_sort_mode(self):
        return self.config.get('Sort', 'sort_mode', fallback='name')

    def set_sort_mode(self, sort_mode):
        if 'Sort' not in self.config: self.config['Sort'] = {}
        self.config['Sort']['sort_mode'] = sort_mode
        self.save_settings()

    # Nowe getters i setters dla interfejsu
    def get_confirm_delete(self):
        return self.config.getboolean('Interface', 'confirm_delete', fallback=True)

    def set_confirm_delete(self, value):
        if 'Interface' not in self.config: self.config['Interface'] = {}
        self.config['Interface']['confirm_delete'] = str(value).lower()
        self.save_settings()

    def get_explorer_view_mode(self):
        return self.config.get('Interface', 'explorer_view_mode', fallback='klasyczny')

    def set_explorer_view_mode(self, mode):
        if 'Interface' not in self.config: self.config['Interface'] = {}
        valid_modes = ["lista", "commander", "klasyczny", "wiele kart"]
        if mode in valid_modes:
            self.config['Interface']['explorer_view_mode'] = mode
            self.save_settings()
        else:
            print(f"Warning: Invalid explorer view mode '{mode}'. Not saving.")


    def get_window_title_mode(self):
        return self.config.get('Interface', 'window_title_mode', fallback='nazwa aplikacji')

    def set_window_title_mode(self, mode):
        if 'Interface' not in self.config: self.config['Interface'] = {}
        valid_modes = ["nazwa aplikacji", "nazwa katalogu", "ścieżka"]
        if mode in valid_modes:
            self.config['Interface']['window_title_mode'] = mode
            self.save_settings()
        else:
             print(f"Warning: Invalid window title mode '{mode}'. Not saving.")


    def get_copy_dialog_mode(self):
        return self.config.get('Interface', 'copy_dialog_mode', fallback='klasyczny')

    def set_copy_dialog_mode(self, mode):
        if 'Interface' not in self.config: self.config['Interface'] = {}
        valid_modes = ["klasyczny", "systemowy"]
        if mode in valid_modes:
            self.config['Interface']['copy_dialog_mode'] = mode
            self.save_settings()
        else:
             print(f"Warning: Invalid copy dialog mode '{mode}'. Not saving.")


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, settings):
        # Pass parent to the wx.Dialog constructor
        wx.Dialog.__init__(self, parent, title="Ustawienia Eksploratora", size=(500, 400))
        self.settings = settings

        panel = wx.Panel(self)
        notebook = wx.Notebook(panel)

        # Panel Ogólne
        general_panel = wx.Panel(notebook)
        # Add StaticText labels before controls for better accessibility
        general_sizer = wx.BoxSizer(wx.VERTICAL)

        # Pokaż ukryte pliki
        self.show_hidden_checkbox = wx.CheckBox(general_panel, label="Pokaż ukryte pliki")
        self.show_hidden_checkbox.SetValue(self.settings.get_show_hidden())
        general_sizer.Add(self.show_hidden_checkbox, 0, wx.ALL, 10) # Add checkbox directly to sizer

        # Pokaż rozszerzenia plików
        self.show_extensions_checkbox = wx.CheckBox(general_panel, label="Pokaż rozszerzenia plików")
        self.show_extensions_checkbox.SetValue(self.settings.get_show_extensions())
        general_sizer.Add(self.show_extensions_checkbox, 0, wx.ALL, 10) # Add checkbox directly to sizer

        # Potwierdzenie przed usunięciem
        self.confirm_delete_checkbox = wx.CheckBox(general_panel, label="Potwierdzenie przed usunięciem")
        self.confirm_delete_checkbox.SetValue(self.settings.get_confirm_delete())
        general_sizer.Add(self.confirm_delete_checkbox, 0, wx.ALL, 10) # Add checkbox directly to sizer


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

        # general_sizer = wx.BoxSizer(wx.VERTICAL) # This was defined earlier, reuse it
        # general_sizer.Add(self.show_hidden_checkbox, 0, wx.ALL, 10) # Moved above
        # general_sizer.Add(self.show_extensions_checkbox, 0, wx.ALL, 10) # Moved above
        # general_sizer.Add(self.confirm_delete_checkbox, 0, wx.ALL, 10) # Moved above
        general_sizer.Add(view_sizer, 0, wx.ALL | wx.EXPAND, 10)
        general_panel.SetSizer(general_sizer)


        # Panel Wygląd
        appearance_panel = wx.Panel(notebook)
        appearance_sizer = wx.BoxSizer(wx.VERTICAL)

        # Widok eksploratora
        explorer_view_box = wx.StaticBox(appearance_panel, label="Widok Eksploratora")
        explorer_view_sizer = wx.StaticBoxSizer(explorer_view_box, wx.VERTICAL)
        # Add a StaticText label for the choice control
        explorer_view_label = wx.StaticText(appearance_panel, label="Tryb widoku eksploratora:")
        explorer_view_sizer.Add(explorer_view_label, 0, wx.ALL, 5)
        self.explorer_view_choice = wx.Choice(appearance_panel, choices=["lista", "commander", "klasyczny", "wiele kart"])
        self.explorer_view_choice.SetStringSelection(self.settings.get_explorer_view_mode())
        explorer_view_sizer.Add(self.explorer_view_choice, 0, wx.ALL | wx.EXPAND, 5) # Expand the choice control

        # Tytuł okna
        window_title_box = wx.StaticBox(appearance_panel, label="Tytuł okna")
        window_title_sizer = wx.StaticBoxSizer(window_title_box, wx.VERTICAL)
        # Add a StaticText label for the choice control
        window_title_label = wx.StaticText(appearance_panel, label="Tryb tytułu okna:")
        window_title_sizer.Add(window_title_label, 0, wx.ALL, 5)
        self.window_title_choice = wx.Choice(appearance_panel, choices=["nazwa aplikacji", "nazwa katalogu", "ścieżka"])
        self.window_title_choice.SetStringSelection(self.settings.get_window_title_mode())
        window_title_sizer.Add(self.window_title_choice, 0, wx.ALL | wx.EXPAND, 5) # Expand the choice control


        # Dialog kopiowania
        copy_dialog_box = wx.StaticBox(appearance_panel, label="Dialog kopiowania plików")
        copy_dialog_sizer = wx.StaticBoxSizer(copy_dialog_box, wx.VERTICAL)
        # Add a StaticText label for the choice control
        copy_dialog_label = wx.StaticText(appearance_panel, label="Tryb dialogu kopiowania:")
        copy_dialog_sizer.Add(copy_dialog_label, 0, wx.ALL, 5)
        self.copy_dialog_choice = wx.Choice(appearance_panel, choices=["klasyczny", "systemowy"])
        self.copy_dialog_choice.SetStringSelection(self.settings.get_copy_dialog_mode())
        copy_dialog_sizer.Add(self.copy_dialog_choice, 0, wx.ALL | wx.EXPAND, 5) # Expand the choice control

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
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        button_sizer.Add(save_button, 0, wx.ALL, 5)
        button_sizer.Add(cancel_button, 0, wx.ALL, 5)
        main_sizer.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        panel.SetSizer(main_sizer)
        self.Layout() # Adjust layout after adding buttons

        # Set accessibility help texts for controls (optional but good practice)
        self.show_hidden_checkbox.SetHelpText("Zaznacz, aby wyświetlić ukryte pliki w liście.")
        self.show_extensions_checkbox.SetHelpText("Zaznacz, aby wyświetlić rozszerzenia plików w liście.")
        self.confirm_delete_checkbox.SetHelpText("Zaznacz, aby program pytał o potwierdzenie przed usunięciem plików.")
        self.view_name.SetHelpText("Zaznacz, aby wyświetlić nazwę pliku w liście.")
        self.view_date.SetHelpText("Zaznacz, aby wyświetlić datę modyfikacji pliku w liście.")
        self.view_type.SetHelpText("Zaznacz, aby wyświetlić typ pliku (folder/plik) w liście.")
        self.explorer_view_choice.SetHelpText("Wybierz tryb wyświetlania plików: lista, commander (dwa panele), klasyczny, wiele kart.")
        self.window_title_choice.SetHelpText("Wybierz co będzie wyświetlane w tytule okna: nazwa aplikacji, nazwa bieżącego folderu, pełna ścieżka.")
        self.copy_dialog_choice.SetHelpText("Wybierz tryb dialogu kopiowania/przenoszenia: klasyczny (z paskiem postępu) lub systemowy.")
        save_button.SetHelpText("Zapisz zmiany ustawień.")
        cancel_button.SetHelpText("Anuluj zmiany ustawień.")


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
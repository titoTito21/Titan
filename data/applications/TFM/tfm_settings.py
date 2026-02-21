# tfm_settings.py
import configparser
import os
import wx
import platform # Import platform to check OS
from translation import _

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
            'confirm_delete': 'true',
            'explorer_view_mode': 'classic',  # list, commander, classic, multi-tab
            'window_title_mode': 'app-name',  # app-name, folder-name, path
            'copy_dialog_mode': 'classic'     # classic, system
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
            self.config['Interface']['explorer_view_mode'] = 'classic'
            changed = True
        if 'window_title_mode' not in self.config['Interface']:
            self.config['Interface']['window_title_mode'] = 'app-name'
            changed = True
        if 'copy_dialog_mode' not in self.config['Interface']:
            self.config['Interface']['copy_dialog_mode'] = 'classic'
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
        return self.config.get('Interface', 'explorer_view_mode', fallback='classic')

    def set_explorer_view_mode(self, mode):
        if 'Interface' not in self.config: self.config['Interface'] = {}
        valid_modes = ["list", "commander", "classic", "multi-tab"]
        if mode in valid_modes:
            self.config['Interface']['explorer_view_mode'] = mode
            self.save_settings()
        else:
            print(f"Warning: Invalid explorer view mode '{mode}'. Not saving.")


    def get_window_title_mode(self):
        return self.config.get('Interface', 'window_title_mode', fallback='app-name')

    def set_window_title_mode(self, mode):
        if 'Interface' not in self.config: self.config['Interface'] = {}
        valid_modes = ["app-name", "folder-name", "path"]
        if mode in valid_modes:
            self.config['Interface']['window_title_mode'] = mode
            self.save_settings()
        else:
             print(f"Warning: Invalid window title mode '{mode}'. Not saving.")


    def get_copy_dialog_mode(self):
        return self.config.get('Interface', 'copy_dialog_mode', fallback='classic')

    def set_copy_dialog_mode(self, mode):
        if 'Interface' not in self.config: self.config['Interface'] = {}
        valid_modes = ["classic", "system"]
        if mode in valid_modes:
            self.config['Interface']['copy_dialog_mode'] = mode
            self.save_settings()
        else:
             print(f"Warning: Invalid copy dialog mode '{mode}'. Not saving.")


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, settings):
        # Pass parent to the wx.Dialog constructor
        wx.Dialog.__init__(self, parent, title=_("File Manager Settings"), size=(500, 400))
        self.settings = settings

        panel = wx.Panel(self)
        notebook = wx.Notebook(panel)

        # Panel Ogólne
        general_panel = wx.Panel(notebook)
        # Add StaticText labels before controls for better accessibility
        general_sizer = wx.BoxSizer(wx.VERTICAL)

        # Pokaż ukryte pliki
        self.show_hidden_checkbox = wx.CheckBox(general_panel, label=_("Show hidden files"))
        self.show_hidden_checkbox.SetValue(self.settings.get_show_hidden())
        general_sizer.Add(self.show_hidden_checkbox, 0, wx.ALL, 10)

        self.show_extensions_checkbox = wx.CheckBox(general_panel, label=_("Show file extensions"))
        self.show_extensions_checkbox.SetValue(self.settings.get_show_extensions())
        general_sizer.Add(self.show_extensions_checkbox, 0, wx.ALL, 10)

        self.confirm_delete_checkbox = wx.CheckBox(general_panel, label=_("Confirm before deleting"))
        self.confirm_delete_checkbox.SetValue(self.settings.get_confirm_delete())
        general_sizer.Add(self.confirm_delete_checkbox, 0, wx.ALL, 10)


        view_box = wx.StaticBox(general_panel, label=_("File info columns"))
        view_sizer = wx.StaticBoxSizer(view_box, wx.VERTICAL)

        self.view_name = wx.CheckBox(general_panel, label=_("Name"))
        self.view_date = wx.CheckBox(general_panel, label=_("Date modified"))
        self.view_type = wx.CheckBox(general_panel, label=_("Type"))

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

        # Explorer view
        self._explorer_keys = ["list", "commander", "classic", "multi-tab"]
        explorer_view_box = wx.StaticBox(appearance_panel, label=_("Explorer view"))
        explorer_view_sizer = wx.StaticBoxSizer(explorer_view_box, wx.VERTICAL)
        explorer_view_label = wx.StaticText(appearance_panel, label=_("Explorer view mode:"))
        explorer_view_sizer.Add(explorer_view_label, 0, wx.ALL, 5)
        explorer_labels = [_("List"), _("Commander"), _("Classic"), _("Multi-tab")]
        self.explorer_view_choice = wx.Choice(appearance_panel, choices=explorer_labels)
        cur_key = self.settings.get_explorer_view_mode()
        self.explorer_view_choice.SetSelection(
            self._explorer_keys.index(cur_key) if cur_key in self._explorer_keys else 2)
        explorer_view_sizer.Add(self.explorer_view_choice, 0, wx.ALL | wx.EXPAND, 5)

        # Window title
        self._window_title_keys = ["app-name", "folder-name", "path"]
        window_title_box = wx.StaticBox(appearance_panel, label=_("Window title"))
        window_title_sizer = wx.StaticBoxSizer(window_title_box, wx.VERTICAL)
        window_title_label = wx.StaticText(appearance_panel, label=_("Window title mode:"))
        window_title_sizer.Add(window_title_label, 0, wx.ALL, 5)
        window_title_labels = [_("App name"), _("Folder name"), _("Path")]
        self.window_title_choice = wx.Choice(appearance_panel, choices=window_title_labels)
        cur_key = self.settings.get_window_title_mode()
        self.window_title_choice.SetSelection(
            self._window_title_keys.index(cur_key) if cur_key in self._window_title_keys else 0)
        window_title_sizer.Add(self.window_title_choice, 0, wx.ALL | wx.EXPAND, 5)

        # Copy dialog
        self._copy_dialog_keys = ["classic", "system"]
        copy_dialog_box = wx.StaticBox(appearance_panel, label=_("Copy dialog"))
        copy_dialog_sizer = wx.StaticBoxSizer(copy_dialog_box, wx.VERTICAL)
        copy_dialog_label = wx.StaticText(appearance_panel, label=_("Copy dialog mode:"))
        copy_dialog_sizer.Add(copy_dialog_label, 0, wx.ALL, 5)
        copy_dialog_labels = [_("Classic"), _("System")]
        self.copy_dialog_choice = wx.Choice(appearance_panel, choices=copy_dialog_labels)
        cur_key = self.settings.get_copy_dialog_mode()
        self.copy_dialog_choice.SetSelection(
            self._copy_dialog_keys.index(cur_key) if cur_key in self._copy_dialog_keys else 0)
        copy_dialog_sizer.Add(self.copy_dialog_choice, 0, wx.ALL | wx.EXPAND, 5)

        appearance_sizer.Add(explorer_view_sizer, 0, wx.ALL | wx.EXPAND, 10)
        appearance_sizer.Add(window_title_sizer, 0, wx.ALL | wx.EXPAND, 10)
        appearance_sizer.Add(copy_dialog_sizer, 0, wx.ALL | wx.EXPAND, 10)

        appearance_panel.SetSizer(appearance_sizer)

        notebook.AddPage(general_panel, _("General"))
        notebook.AddPage(appearance_panel, _("Appearance"))

        save_button = wx.Button(panel, label=_("Save"))
        cancel_button = wx.Button(panel, label=_("Cancel"))

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
        self.show_hidden_checkbox.SetHelpText(_("Check to show hidden files in the list."))
        self.show_extensions_checkbox.SetHelpText(_("Check to show file extensions in the list."))
        self.confirm_delete_checkbox.SetHelpText(_("Check to ask for confirmation before deleting files."))
        self.view_name.SetHelpText(_("Check to show the file name column."))
        self.view_date.SetHelpText(_("Check to show the date modified column."))
        self.view_type.SetHelpText(_("Check to show the file type column."))
        self.explorer_view_choice.SetHelpText(_("Select view mode: list, commander (two panels), classic, multi-tab."))
        self.window_title_choice.SetHelpText(_("Select what is shown in the window title: app name, folder name, or full path."))
        self.copy_dialog_choice.SetHelpText(_("Select copy/move dialog mode: classic (with progress bar) or system."))
        save_button.SetHelpText(_("Save settings."))
        cancel_button.SetHelpText(_("Cancel settings."))


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

        # Save Appearance tab settings using internal English keys
        idx = self.explorer_view_choice.GetSelection()
        if idx >= 0:
            self.settings.set_explorer_view_mode(self._explorer_keys[idx])
        idx = self.window_title_choice.GetSelection()
        if idx >= 0:
            self.settings.set_window_title_mode(self._window_title_keys[idx])
        idx = self.copy_dialog_choice.GetSelection()
        if idx >= 0:
            self.settings.set_copy_dialog_mode(self._copy_dialog_keys[idx])

        self.EndModal(wx.ID_OK)

    def on_cancel(self, event):
        self.EndModal(wx.ID_CANCEL)

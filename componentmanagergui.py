# Filename: componentmanagergui.py
import wx
import os
from accessible_output3.outputs.auto import Auto
from sound import play_sound, play_focus_sound, play_endoflist_sound
from translation import set_language
from settings import get_setting

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

class ComponentManagerDialog(wx.Dialog):
    def __init__(self, parent, title, component_manager=None):
        super().__init__(parent, title=title, size=(400, 400))

        self.component_manager = component_manager
        self.tts = Auto()

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(panel, label=_("Installed components:"))
        vbox.Add(lbl, 0, wx.ALL | wx.EXPAND, 5)

        self.component_listbox = wx.ListBox(panel, wx.ID_ANY)
        vbox.Add(self.component_listbox, 1, wx.ALL | wx.EXPAND, 5)

        self.actions_button = wx.Button(panel, label=_("&Actions"))
        vbox.Add(self.actions_button, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        self.actions_button.Enable(False)

        # --- Bindowanie zdarzeń ---
        self.component_listbox.Bind(wx.EVT_KEY_DOWN, self.on_list_key_down)
        self.component_listbox.Bind(wx.EVT_LISTBOX, self.on_selection_change)
        self.actions_button.Bind(wx.EVT_BUTTON, self.on_actions_button_press)

        panel.SetSizer(vbox)
        self.Centre()
        self.populate_component_list()
        self.component_listbox.SetFocus()

    def populate_component_list(self):
        self.component_listbox.Clear()
        if not self.component_manager:
            self.component_listbox.Append(_("Component manager not available."))
            return

        components_dir = os.path.join(os.path.dirname(__file__), 'data', 'components')
        for component_folder in sorted(os.listdir(components_dir)):
            if os.path.isdir(os.path.join(components_dir, component_folder)):
                display_name = self.component_manager.get_component_display_name(component_folder)
                status = self.component_manager.component_states.get(component_folder, 1)
                status_str = _("Enabled") if status == 0 else _("Disabled")
                self.component_listbox.Append(f"{display_name} - {status_str}", clientData=component_folder)
        
        if self.component_listbox.GetCount() > 0:
            self.component_listbox.SetSelection(0)
            self.on_selection_change(None) # Ręczne wywołanie dla pierwszego elementu

    def on_list_key_down(self, event):
        key_code = event.GetKeyCode()
        listbox = self.component_listbox
        selected_index = listbox.GetSelection()
        count = listbox.GetCount()

        if count == 0:
            event.Skip()
            return

        if key_code == wx.WXK_UP:
            if selected_index == 0:
                play_endoflist_sound()
            else:
                new_index = selected_index - 1
                listbox.SetSelection(new_index)
                play_focus_sound()
                self.tts.output(listbox.GetString(new_index))
        elif key_code == wx.WXK_DOWN:
            if selected_index == count - 1:
                play_endoflist_sound()
            else:
                new_index = selected_index + 1
                listbox.SetSelection(new_index)
                play_focus_sound()
                self.tts.output(listbox.GetString(new_index))
        elif key_code == wx.WXK_SPACE:
            if selected_index != wx.NOT_FOUND:
                component_folder = listbox.GetClientData(selected_index)
                self.toggle_component(component_folder, selected_index)
        elif key_code == wx.WXK_RETURN:
            if selected_index != wx.NOT_FOUND:
                self.on_actions_button_press(event)
        else:
            event.Skip()

    def on_selection_change(self, event):
        # Aktywuj przycisk akcji, jeśli coś jest zaznaczone
        is_anything_selected = self.component_listbox.GetSelection() != wx.NOT_FOUND
        self.actions_button.Enable(is_anything_selected)
        if event: # Unikaj błędu przy ręcznym wywołaniu
            event.Skip()

    def on_actions_button_press(self, event):
        selected_index = self.component_listbox.GetSelection()
        if selected_index == wx.NOT_FOUND:
            return
        
        component_folder = self.component_listbox.GetClientData(selected_index)
        self.show_context_menu(component_folder)

    def on_menu_close(self, event):
        play_sound('contextmenuclose.ogg')
        self.actions_button.SetFocus()
        if event:
            event.Skip()

    def show_context_menu(self, component_folder):
        component_module = next((c for c in self.component_manager.components if c.__name__ == component_folder), None)
        display_name = self.component_manager.get_component_display_name(component_folder)

        if not component_module:
            wx.MessageBox(_("Component '{}' is not loaded.").format(display_name), _("Information"), wx.OK | wx.ICON_INFORMATION)
            return

        menu = wx.Menu()
        has_open_action = hasattr(component_module, 'add_menu')
        has_settings_action = hasattr(component_module, 'show_settings_dialog')

        if not has_open_action and not has_settings_action:
            wx.MessageBox(_("No available actions for component '{}'.").format(display_name), _("Information"), wx.OK | wx.ICON_INFORMATION)
            return

        play_sound('contextmenu.ogg')
        self.tts.output(_("Context menu"))

        if has_open_action:
            open_item = menu.Append(wx.ID_ANY, _("Run"))
            self.Bind(wx.EVT_MENU, lambda event, cf=component_folder: self.on_run_action(cf), open_item)

        if has_settings_action:
            settings_item = menu.Append(wx.ID_ANY, _("Settings"))
            self.Bind(wx.EVT_MENU, lambda event, cf=component_folder: self.on_settings_action(cf), settings_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def on_run_action(self, component_folder):
        display_name = self.component_manager.get_component_display_name(component_folder)
        self.tts.output(_("Running component {}").format(display_name))
        
        component_module = next((c for c in self.component_manager.components if c.__name__ == component_folder), None)
        if not component_module: return

        menu_funcs = self.component_manager.get_component_menu_functions()
        func_to_run = next((func for name, func in menu_funcs.items() if component_folder.lower() in name.lower()), None)
        
        if func_to_run:
            try:
                func_to_run(self)
            except Exception as e:
                wx.MessageBox(_("Error running component '{}':\n{}").format(display_name, e), _("Error"), wx.OK | wx.ICON_ERROR)

    def on_settings_action(self, component_folder):
        display_name = self.component_manager.get_component_display_name(component_folder)
        self.tts.output(_("Opening settings for component {}").format(display_name))

        component_module = next((c for c in self.component_manager.components if c.__name__ == component_folder), None)
        if component_module and hasattr(component_module, 'show_settings_dialog'):
            try:
                component_module.show_settings_dialog(self)
            except Exception as e:
                wx.MessageBox(_("Error opening settings for '{}':\n{}").format(display_name, e), _("Error"), wx.OK | wx.ICON_ERROR)

    def toggle_component(self, component_folder, index):
        new_status = self.component_manager.toggle_component_status(component_folder)
        display_name = self.component_manager.get_component_display_name(component_folder)
        status_str = _("Enabled") if new_status == 0 else _("Disabled")
        
        self.component_listbox.SetString(index, f"{display_name} - {status_str}")
        self.tts.output(_("Component {} {}").format(display_name, status_str.lower()))

if __name__ == '__main__':
    # Dummy classes for testing
    class DummyComponentManager:
        def __init__(self):
            self.components = []
            self.component_states = {"TTerm": 0, "Tips": 1, "titan_help": 0}
            self.component_friendly_names = {
                "TTerm": "Terminal",
                "Tips": "Porady",
                "titan_help": "Pomoc Titana (F1)"
            }
        def get_component_display_name(self, folder_name):
            return self.component_friendly_names.get(folder_name, folder_name)
        def toggle_component_status(self, folder_name):
            self.component_states[folder_name] = 1 if self.component_states[folder_name] == 0 else 0
            return self.component_states[folder_name]
        def get_component_menu_functions(self):
            return {}

    app = wx.App(False)
    dummy_manager = DummyComponentManager()
    dialog = ComponentManagerDialog(None, "Menedżer komponentów - Test", component_manager=dummy_manager)
    dialog.ShowModal()
    dialog.Destroy()

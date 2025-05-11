# Filename: componentmanagergui.py
import wx
# Assuming component_manager is available in the Python path
# import component_manager # We will receive the manager instance directly


class ComponentManagerFrame(wx.Frame):
    def __init__(self, parent, title, component_manager=None):
        super().__init__(parent, title=title, size=(400, 400))

        self.component_manager = component_manager
        self.components_list = [] # To store component modules

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(panel, label="Zainstalowane komponenty:")
        vbox.Add(lbl, 0, wx.ALL | wx.EXPAND, 5)

        self.component_listbox = wx.ListBox(panel, wx.ID_ANY)
        vbox.Add(self.component_listbox, 1, wx.ALL | wx.EXPAND, 5)

        self.settings_button = wx.Button(panel, label="Otwórz ustawienia komponentu")
        vbox.Add(self.settings_button, 0, wx.ALL | wx.CENTER, 5)

        self.Bind(wx.EVT_BUTTON, self.on_open_component_settings, self.settings_button)
        self.Bind(wx.EVT_LISTBOX_DCLICK, self.on_open_component_settings, self.component_listbox)

        panel.SetSizer(vbox)
        self.Centre()

        self.populate_component_list()

    def populate_component_list(self):
        self.component_listbox.Clear()
        self.components_list = []

        if self.component_manager and hasattr(self.component_manager, 'components'):
            for component_module in self.component_manager.components:
                # Assuming component module has a __name__ or we can use the folder name
                # The component_manager loads them using the folder name as module name
                component_name = getattr(component_module, '__name__', 'Nieznany komponent')
                self.component_listbox.Append(component_name)
                self.components_list.append(component_module)
        else:
            self.component_listbox.Append("Menedżer komponentów niedostępny.")
            self.settings_button.Enable(False)


    def on_open_component_settings(self, event):
        selected_index = self.component_listbox.GetSelection()
        if selected_index == wx.NOT_FOUND:
            wx.MessageBox("Proszę wybrać komponent z listy.", "Informacja", wx.OK | wx.ICON_INFORMATION)
            return

        selected_component_module = self.components_list[selected_index]
        component_name = self.component_listbox.GetString(selected_index)

        # --- KONWENCJA DLA OTWIERANIA USTAWIEN KOMPONENTU ---
        # Przyjmujemy, że moduł komponentu ma funkcję np. 'show_settings_dialog(parent)'
        # lub zwraca klasę okna ustawień np. przez atrybut 'SettingsFrameClass'
        # Musisz zaimplementować to w plikach init.py swoich komponentów.

        settings_opened = False
        # Try calling a method on the component module
        if hasattr(selected_component_module, 'show_settings_dialog'):
            try:
                selected_component_module.show_settings_dialog(self) # Pass this frame as parent
                settings_opened = True
            except Exception as e:
                wx.MessageBox(f"Błąd podczas otwierania ustawień dla '{component_name}':\n{e}", "Błąd ustawień komponentu", wx.OK | wx.ICON_ERROR)
                settings_opened = True # Indicate attempt was made


        # Alternatively, if component exposes a settings frame class
        if not settings_opened and hasattr(selected_component_module, 'SettingsFrameClass'):
             try:
                 settings_frame_class = selected_component_module.SettingsFrameClass
                 settings_frame = settings_frame_class(self, title=f"Ustawienia: {component_name}")
                 settings_frame.ShowModal() # Use ShowModal if it's a dialog, Show if it's a frame
                 settings_frame.Destroy()
                 settings_opened = True
             except Exception as e:
                 wx.MessageBox(f"Błąd podczas tworzenia/otwierania okna ustawień dla '{component_name}':\n{e}", "Błąd ustawień komponentu", wx.OK | wx.ICON_ERROR)
                 settings_opened = True # Indicate attempt was made


        if not settings_opened:
            wx.MessageBox(f"Ustawienia dla '{component_name}' nie są dostępne lub nie zaimplementowano mechanizmu ich otwierania.", "Informacja", wx.OK | wx.ICON_INFORMATION)


if __name__ == '__main__':
    # This block allows testing the GUI file independently with dummy data
    class DummyComponentManager:
        def __init__(self):
            # Create dummy component modules
            class DummyTDictate:
                __name__ = "TDictate"
                def show_settings_dialog(self, parent):
                    wx.MessageBox("Dummy TDictate Settings", f"Ustawienia: {self.__name__}", wx.OK | wx.ICON_INFORMATION)

            class DummyTitanMenu:
                 __name__ = "TitanMenu"
                 # This one doesn't have a settings method/class
                 pass

            class DummyTSounds:
                 __name__ = "tSounds"
                 # Example of exposing a frame class
                 class SettingsFrameClass(wx.Frame):
                     def __init__(self, parent, title):
                         super().__init__(parent, title=title, size=(200, 100))
                         panel = wx.Panel(self)
                         wx.StaticText(panel, label="Dummy tSounds Settings Frame", pos=(10, 10))
                         self.Centre()

            self.components = [DummyTDictate(), DummyTitanMenu(), DummyTSounds()]

    app = wx.App(False)
    dummy_manager = DummyComponentManager()
    frame = ComponentManagerFrame(None, "Menedżer komponentów - Test", component_manager=dummy_manager)
    frame.Show()
    app.MainLoop()
import wx
import os
import datetime
import json
import platform
from translation import _

class tNotesApp(wx.Frame):
    def __init__(self, *args, **kw):
        super(tNotesApp, self).__init__(*args, **kw)
        
        self.notes_dir = os.path.join(os.path.expanduser('~'), 'Documents', 'Titan', 'notes')
        self.current_dir = self.notes_dir

        if not os.path.exists(self.notes_dir):
            os.makedirs(self.notes_dir)

        self.settings_file = os.path.join(self.get_appdata_dir(), 'tNotes_settings.json')
        self.load_settings()

        self.init_ui()
        self.load_notes_list()

        self.init_tts()

    def get_appdata_dir(self):
        if os.name == 'nt':  # Windows
            return os.path.join(os.getenv('APPDATA'), 'Titosoft', 'Titan', 'appsettings')
        else:
            return os.path.join(os.path.expanduser('~'), '.titosoft', 'titan', 'appsettings')

    def load_settings(self):
        if os.path.exists(self.settings_file):
            with open(self.settings_file, 'r') as f:
                self.settings = json.load(f)
        else:
            self.settings = {
                'announce_folders': False,
                'announce_shortcuts': False
            }
            self.save_settings()

    def save_settings(self):
        settings_dir = os.path.dirname(self.settings_file)
        if not os.path.exists(settings_dir):
            os.makedirs(settings_dir)
        with open(self.settings_file, 'w') as f:
            json.dump(self.settings, f)

    def init_ui(self):
        self.SetSize((800, 600))
        self.SetTitle(_('tNotes'))

        self.panel = wx.Panel(self)

        self.notebook = wx.ListCtrl(self.panel, style=wx.LC_REPORT)
        self.notebook.InsertColumn(0, _('Tytuł notatki'), width=200)
        self.notebook.InsertColumn(1, _('Data utworzenia'), width=150)
        self.notebook.InsertColumn(2, _('Data edytowania'), width=150)
        self.notebook.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open_note)
        self.notebook.Bind(wx.EVT_KEY_DOWN, self.on_list_key_down)

        self.new_note_btn = wx.Button(self.panel, label=_('Nowa notatka'))
        self.new_note_btn.Bind(wx.EVT_BUTTON, self.on_new_note)

        self.new_folder_btn = wx.Button(self.panel, label=_('Nowy katalog'))
        self.new_folder_btn.Bind(wx.EVT_BUTTON, self.on_new_folder)

        self.delete_btn = wx.Button(self.panel, label=_('Usuń'))
        self.delete_btn.Bind(wx.EVT_BUTTON, self.on_delete)

        self.back_btn = wx.Button(self.panel, label=_('Powrót'))
        self.back_btn.Bind(wx.EVT_BUTTON, self.on_back)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self.notebook, proportion=1, flag=wx.ALL | wx.EXPAND, border=10)
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(self.new_note_btn, flag=wx.RIGHT, border=10)
        hbox.Add(self.new_folder_btn, flag=wx.RIGHT, border=10)
        hbox.Add(self.delete_btn, flag=wx.RIGHT, border=10)
        hbox.Add(self.back_btn, flag=wx.RIGHT, border=10)
        vbox.Add(hbox, flag=wx.ALL | wx.ALIGN_CENTER, border=10)

        self.panel.SetSizer(vbox)

        self.create_menu_bar()

        self.Centre()
        self.Show(True)

    def create_menu_bar(self):
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        new_note_item = file_menu.Append(wx.ID_NEW, _('&Nowa notatka\tCtrl+N'))
        new_folder_item = file_menu.Append(wx.ID_ANY, _('Nowy &katalog\tCtrl+Shift+N'))
        file_menu.AppendSeparator()
        settings_item = file_menu.Append(wx.ID_ANY, _('Ustawienia tNotes...'))
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, _('&Zamknij tNotes\tCtrl+W'))

        self.Bind(wx.EVT_MENU, self.on_new_note, new_note_item)
        self.Bind(wx.EVT_MENU, self.on_new_folder, new_folder_item)
        self.Bind(wx.EVT_MENU, self.on_settings, settings_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)

        menubar.Append(file_menu, _('&Plik'))
        self.SetMenuBar(menubar)

    def load_notes_list(self):
        if not os.path.exists(self.current_dir):
            self.speak(_('Katalog {} nie istnieje.').format(self.current_dir))
            self.current_dir = self.notes_dir

        self.notebook.DeleteAllItems()
        for item in os.listdir(self.current_dir):
            item_path = os.path.join(self.current_dir, item)
            if os.path.isdir(item_path):
                note_count = len([f for f in os.listdir(item_path) if f.endswith('.tnote')])
                display_text = _("[Katalog] {}").format(item) if not self.settings['announce_folders'] else _("Katalog {}, zawiera {} notatek").format(item, note_count)
                self.notebook.Append([display_text, "", ""])
            else:
                if item.endswith('.tnote'):
                    with open(item_path, 'r') as f:
                        first_line = f.readline().strip()
                    created = datetime.datetime.fromtimestamp(os.path.getctime(item_path)).strftime('%Y-%m-%d %H:%M:%S')
                    edited = datetime.datetime.fromtimestamp(os.path.getmtime(item_path)).strftime('%Y-%m-%d %H:%M:%S')
                    self.notebook.Append([first_line, created, edited])

    def init_tts(self):
        system = platform.system()
        if system == 'Windows':
            self.speak = self.speak_windows
        elif system == 'Darwin':  # macOS
            self.speak = self.speak_mac
        else:  # Assume Linux
            self.speak = self.speak_linux

    def speak_windows(self, text):
        import win32com.client
        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        speaker.Speak(text)

    def speak_mac(self, text):
        os.system(f"say {text}")

    def speak_linux(self, text):
        os.system(f"spd-say {text}")

    def on_new_note(self, event):
        dialog = wx.TextEntryDialog(self, _('Wprowadź tytuł notatki:'), _('Nowa notatka'))
        if dialog.ShowModal() == wx.ID_OK:
            title = dialog.GetValue()
            self.create_note_dialog(title)
        dialog.Destroy()

    def create_note_dialog(self, title):
        self.note_dialog = wx.Dialog(self, title=_('Nowa notatka'), size=(400, 300))
        panel = wx.Panel(self.note_dialog)
        vbox = wx.BoxSizer(wx.VERTICAL)

        title_label = wx.StaticText(panel, label=_('Tytuł:'))
        self.note_title = wx.TextCtrl(panel, value=title)
        content_label = wx.StaticText(panel, label=_('Treść:'))
        self.note_content = wx.TextCtrl(panel, style=wx.TE_MULTILINE)

        save_button = wx.Button(panel, label=_('Zapisz'))
        save_button.Bind(wx.EVT_BUTTON, self.on_save_note)

        cancel_button = wx.Button(panel, label=_('Anuluj'))
        cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(save_button, flag=wx.RIGHT, border=10)
        hbox.Add(cancel_button, flag=wx.RIGHT, border=10)

        vbox.Add(title_label, flag=wx.ALL, border=5)
        vbox.Add(self.note_title, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(content_label, flag=wx.ALL, border=5)
        vbox.Add(self.note_content, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(hbox, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        panel.SetSizer(vbox)
        self.note_dialog.ShowModal()

    def on_save_note(self, event):
        title = self.note_title.GetValue()
        content = self.note_content.GetValue()
        note_path = os.path.join(self.current_dir, f"{title}.tnote")
        with open(note_path, 'w') as f:
            f.write(title + '\n' + content)
        self.note_dialog.Destroy()
        self.load_notes_list()
        self.speak(_('Notatka została zapisana!'))

    def on_cancel(self, event):
        self.note_dialog.Destroy()

    def on_new_folder(self, event):
        dialog = wx.TextEntryDialog(self, _('Wprowadź nazwę katalogu:'), _('Nowy katalog'))
        if dialog.ShowModal() == wx.ID_OK:
            folder_name = dialog.GetValue()
            folder_path = os.path.join(self.current_dir, folder_name)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
                self.load_notes_list()
                self.speak(_('Katalog został utworzony!'))
            else:
                self.speak(_('Katalog {} już istnieje.').format(folder_path))
        dialog.Destroy()

    def on_open_note(self, event):
        index = event.GetIndex()
        item = self.notebook.GetItemText(index)
        if item.startswith(_('[Katalog]')):
            folder_name = item.split(' ', 1)[1]
            if self.settings['announce_folders']:
                folder_name = folder_name.split(', zawiera')[0]
            self.current_dir = os.path.join(self.current_dir, folder_name)
            self.load_notes_list()
        elif item.startswith(_('Katalog')):
            folder_name = item.split(' ', 1)[1]
            if self.settings['announce_folders']:
                folder_name = folder_name.split(', zawiera')[0]
            self.current_dir = os.path.join(self.current_dir, folder_name)
            self.load_notes_list()
        else:
            note_path = os.path.join(self.current_dir, f"{item}.tnote")
            if os.path.exists(note_path):
                with open(note_path, 'r') as f:
                    title = f.readline().strip()
                    content = f.read().strip()
                self.edit_note_dialog(title, content)
            else:
                self.speak(_('Plik {} nie istnieje.').format(note_path))

    def edit_note_dialog(self, title, content):
        self.note_dialog = wx.Dialog(self, title=_('Edytuj notatkę'), size=(400, 300))
        panel = wx.Panel(self.note_dialog)
        vbox = wx.BoxSizer(wx.VERTICAL)

        title_label = wx.StaticText(panel, label=_('Tytuł:'))
        self.note_title = wx.TextCtrl(panel, value=title)
        content_label = wx.StaticText(panel, label=_('Treść:'))
        self.note_content = wx.TextCtrl(panel, style=wx.TE_MULTILINE, value=content)

        save_button = wx.Button(panel, label=_('Zapisz'))
        save_button.Bind(wx.EVT_BUTTON, self.on_save_note)

        cancel_button = wx.Button(panel, label=_('Anuluj'))
        cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(save_button, flag=wx.RIGHT, border=10)
        hbox.Add(cancel_button, flag=wx.RIGHT, border=10)

        vbox.Add(title_label, flag=wx.ALL, border=5)
        vbox.Add(self.note_title, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(content_label, flag=wx.ALL, border=5)
        vbox.Add(self.note_content, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(hbox, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        panel.SetSizer(vbox)
        self.note_dialog.ShowModal()

    def on_delete(self, event):
        index = self.notebook.GetFirstSelected()
        if index != -1:
            item = self.notebook.GetItemText(index)
            if item.startswith(_('[Katalog]')):
                folder_name = item.split(' ', 1)[1]
                if self.settings['announce_folders']:
                    folder_name = folder_name.split(', zawiera')[0]
                folder_path = os.path.join(self.current_dir, folder_name)
                try:
                    os.rmdir(folder_path)
                    self.speak(_('Katalog został usunięty!'))
                except OSError:
                    self.speak(_('Katalog {} nie jest pusty.').format(folder_path))
            elif item.startswith(_('Katalog')):
                folder_name = item.split(' ', 1)[1]
                if self.settings['announce_folders']:
                    folder_name = folder_name.split(', zawiera')[0]
                folder_path = os.path.join(self.current_dir, folder_name)
                try:
                    os.rmdir(folder_path)
                    self.speak(_('Katalog został usunięty!'))
                except OSError:
                    self.speak(_('Katalog {} nie jest pusty.').format(folder_path))
            else:
                note_path = os.path.join(self.current_dir, f"{item}.tnote")
                if os.path.exists(note_path):
                    os.remove(note_path)
                    self.speak(_('Notatka została usunięta!'))
            self.load_notes_list()

    def on_back(self, event):
        if self.current_dir != self.notes_dir:
            self.current_dir = os.path.abspath(os.path.join(self.current_dir, os.pardir))
            self.load_notes_list()

    def on_settings(self, event):
        self.settings_dialog = wx.Dialog(self, title=_('Ustawienia tNotes'), size=(300, 200))
        panel = wx.Panel(self.settings_dialog)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.announce_folders_cb = wx.CheckBox(panel, label=_('Oznajmij katalogi'))
        self.announce_folders_cb.SetValue(self.settings['announce_folders'])
        self.announce_shortcuts_cb = wx.CheckBox(panel, label=_('Oznajmij skróty klawiszowe'))
        self.announce_shortcuts_cb.SetValue(self.settings['announce_shortcuts'])

        save_button = wx.Button(panel, label=_('Zapisz'))
        save_button.Bind(wx.EVT_BUTTON, self.on_save_settings)

        cancel_button = wx.Button(panel, label=_('Anuluj'))
        cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel_settings)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(save_button, flag=wx.RIGHT, border=10)
        hbox.Add(cancel_button, flag=wx.RIGHT, border=10)

        vbox.Add(self.announce_folders_cb, flag=wx.ALL, border=5)
        vbox.Add(self.announce_shortcuts_cb, flag=wx.ALL, border=5)
        vbox.Add(hbox, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        panel.SetSizer(vbox)
        self.settings_dialog.ShowModal()

    def on_save_settings(self, event):
        self.settings['announce_folders'] = self.announce_folders_cb.GetValue()
        self.settings['announce_shortcuts'] = self.announce_shortcuts_cb.GetValue()
        self.save_settings()
        self.speak(_('Ustawienia zostały zapisane!'))
        self.settings_dialog.Destroy()
        self.load_notes_list()

    def on_cancel_settings(self, event):
        self.settings_dialog.Destroy()

    def on_exit(self, event):
        self.Close()

    def on_list_key_down(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_BACK:
            self.on_back(event)
        elif keycode == wx.WXK_DELETE:
            self.on_delete(event)
        elif keycode == wx.WXK_RETURN or keycode == wx.WXK_NUMPAD_ENTER:
            selected = self.notebook.GetFirstSelected()
            if selected != -1:
                evt = wx.ListEvent()
                evt.SetIndex(selected)
                self.on_open_note(evt)
        elif event.ControlDown() and keycode == ord('A'):
            for i in range(self.notebook.GetItemCount()):
                self.notebook.Select(i)
        else:
            event.Skip()

if __name__ == '__main__':
    app = wx.App()
    frame = tNotesApp(None)
    frame.Show()
    app.MainLoop()

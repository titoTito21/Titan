import wx
import os
import shutil
import datetime
import json
import platform
from translation import _

# Screen reader output: accessible_output3 with platform fallback.
try:
    import accessible_output3.outputs.auto as _ao3
    _speaker = _ao3.Auto()
except Exception:
    _speaker = None

def _speak(text):
    if _speaker:
        try:
            _speaker.speak(text, interrupt=True)
            return
        except Exception:
            pass
    try:
        _sys = platform.system()
        if _sys == 'Windows':
            import win32com.client
            win32com.client.Dispatch("SAPI.SpVoice").Speak(text)
        elif _sys == 'Darwin':
            import subprocess
            subprocess.Popen(['say', text])
        else:
            import subprocess
            subprocess.Popen(['spd-say', text])
    except Exception:
        pass


class tNotesApp(wx.Frame):
    def __init__(self, *args, **kw):
        super(tNotesApp, self).__init__(*args, **kw)

        self.notes_dir = os.path.join(os.path.expanduser('~'), 'Documents', 'Titan', 'notes')
        self.current_dir = self.notes_dir
        # Parallel list to wx.ListCtrl: each entry is {'type': 'folder'|'note', 'path': str, 'name': str}
        self.items_data = []
        # Path of note being edited (None when creating a new note)
        self._edit_original_path = None

        if not os.path.exists(self.notes_dir):
            os.makedirs(self.notes_dir)

        self.settings_file = os.path.join(self.get_appdata_dir(), 'tNotes_settings.json')
        self.load_settings()

        self.init_ui()
        self.load_notes_list()
        self.init_tts()

    def get_appdata_dir(self):
        if os.name == 'nt':
            return os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), 'Titosoft', 'Titan', 'appsettings')
        else:
            return os.path.join(os.path.expanduser('~'), '.titosoft', 'titan', 'appsettings')

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    self.settings = json.load(f)
            except Exception:
                self.settings = {'announce_folders': False, 'announce_shortcuts': False}
        else:
            self.settings = {'announce_folders': False, 'announce_shortcuts': False}
            self.save_settings()

    def save_settings(self):
        settings_dir = os.path.dirname(self.settings_file)
        if not os.path.exists(settings_dir):
            os.makedirs(settings_dir)
        with open(self.settings_file, 'w', encoding='utf-8') as f:
            json.dump(self.settings, f)

    @staticmethod
    def _sanitize_filename(name):
        """Remove characters that are invalid in filenames on any platform."""
        for ch in r'\/:*?"<>|':
            name = name.replace(ch, '_')
        return name.strip() or 'untitled'

    def init_ui(self):
        self.SetSize((800, 600))
        self.SetTitle(_('tNotes'))

        self.panel = wx.Panel(self)

        self.notebook = wx.ListCtrl(self.panel, style=wx.LC_REPORT)
        self.notebook.InsertColumn(0, _('Note title'), width=200)
        self.notebook.InsertColumn(1, _('Date created'), width=150)
        self.notebook.InsertColumn(2, _('Date modified'), width=150)
        self.notebook.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open_note)
        self.notebook.Bind(wx.EVT_KEY_DOWN, self.on_list_key_down)

        self.new_note_btn = wx.Button(self.panel, label=_('New note'))
        self.new_note_btn.Bind(wx.EVT_BUTTON, self.on_new_note)

        self.new_folder_btn = wx.Button(self.panel, label=_('New folder'))
        self.new_folder_btn.Bind(wx.EVT_BUTTON, self.on_new_folder)

        self.delete_btn = wx.Button(self.panel, label=_('Delete'))
        self.delete_btn.Bind(wx.EVT_BUTTON, self.on_delete)

        self.back_btn = wx.Button(self.panel, label=_('Back'))
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

        self.notebook.SetName(_('Notes list'))
        self.new_note_btn.SetName(_('New note'))
        self.new_folder_btn.SetName(_('New folder'))
        self.delete_btn.SetName(_('Delete'))
        self.back_btn.SetName(_('Back'))

        self.create_menu_bar()
        self.Centre()
        self.Show(True)

    def create_menu_bar(self):
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        new_note_item = file_menu.Append(wx.ID_NEW, _('&New note\tCtrl+N'))
        new_folder_item = file_menu.Append(wx.ID_ANY, _('New &folder\tCtrl+Shift+N'))
        file_menu.AppendSeparator()
        settings_item = file_menu.Append(wx.ID_ANY, _('tNotes settings...'))
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, _('&Close tNotes\tCtrl+W'))

        self.Bind(wx.EVT_MENU, self.on_new_note, new_note_item)
        self.Bind(wx.EVT_MENU, self.on_new_folder, new_folder_item)
        self.Bind(wx.EVT_MENU, self.on_settings, settings_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)

        menubar.Append(file_menu, _('&File'))
        self.SetMenuBar(menubar)

    def load_notes_list(self):
        if not os.path.exists(self.current_dir):
            self.current_dir = self.notes_dir
            if not os.path.exists(self.current_dir):
                os.makedirs(self.current_dir)

        self.items_data = []
        self.notebook.DeleteAllItems()

        try:
            entries = sorted(os.listdir(self.current_dir))
        except OSError:
            return

        # Folders first, then notes
        folders = [e for e in entries if os.path.isdir(os.path.join(self.current_dir, e))]
        notes = [e for e in entries
                 if not os.path.isdir(os.path.join(self.current_dir, e)) and e.endswith('.tnote')]

        for folder in folders:
            folder_path = os.path.join(self.current_dir, folder)
            try:
                note_count = len([f for f in os.listdir(folder_path) if f.endswith('.tnote')])
            except OSError:
                note_count = 0
            if self.settings.get('announce_folders'):
                display_text = _('[Folder] {} ({} notes)').format(folder, note_count)
            else:
                display_text = _('[Folder] {}').format(folder)
            self.notebook.Append([display_text, '', ''])
            self.items_data.append({'type': 'folder', 'path': folder_path, 'name': folder})

        for note_file in notes:
            note_path = os.path.join(self.current_dir, note_file)
            try:
                with open(note_path, 'r', encoding='utf-8') as f:
                    first_line = f.readline().strip()
                if not first_line:
                    first_line = note_file[:-6]
            except Exception:
                first_line = note_file[:-6]
            try:
                created = datetime.datetime.fromtimestamp(
                    os.path.getctime(note_path)).strftime('%Y-%m-%d %H:%M')
                edited = datetime.datetime.fromtimestamp(
                    os.path.getmtime(note_path)).strftime('%Y-%m-%d %H:%M')
            except Exception:
                created = edited = ''
            self.notebook.Append([first_line, created, edited])
            self.items_data.append({'type': 'note', 'path': note_path, 'name': note_file})

    def init_tts(self):
        self.speak = _speak

    # ------------------------------------------------------------------
    # Core navigation / open helper
    # ------------------------------------------------------------------

    def _open_item(self, index):
        """Navigate into a folder or open a note for editing."""
        if index < 0 or index >= len(self.items_data):
            return
        item_data = self.items_data[index]
        if item_data['type'] == 'folder':
            self.current_dir = item_data['path']
            self.load_notes_list()
        else:
            note_path = item_data['path']
            if os.path.exists(note_path):
                try:
                    with open(note_path, 'r', encoding='utf-8') as f:
                        title = f.readline().strip()
                        content = f.read().strip()
                except Exception:
                    title = item_data['name'][:-6]
                    content = ''
                self._edit_original_path = note_path
                self.edit_note_dialog(title, content)
            else:
                self.speak(_('Note file not found.'))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_new_note(self, event):
        dialog = wx.TextEntryDialog(self, _('Enter note title:'), _('New note'))
        if dialog.ShowModal() == wx.ID_OK:
            title = dialog.GetValue().strip()
            if title:
                self._edit_original_path = None
                self.create_note_dialog(title)
        dialog.Destroy()

    def create_note_dialog(self, title):
        self.note_dialog = wx.Dialog(self, title=_('New note'), size=(500, 400))
        panel = wx.Panel(self.note_dialog)
        vbox = wx.BoxSizer(wx.VERTICAL)

        title_label = wx.StaticText(panel, label=_('Title:'))
        self.note_title = wx.TextCtrl(panel, value=title)
        content_label = wx.StaticText(panel, label=_('Content:'))
        self.note_content = wx.TextCtrl(panel, style=wx.TE_MULTILINE)

        save_button = wx.Button(panel, label=_('Save'))
        save_button.Bind(wx.EVT_BUTTON, self.on_save_note)
        cancel_button = wx.Button(panel, label=_('Cancel'))
        cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(save_button, flag=wx.RIGHT, border=10)
        hbox.Add(cancel_button)

        vbox.Add(title_label, flag=wx.ALL, border=5)
        vbox.Add(self.note_title, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(content_label, flag=wx.ALL, border=5)
        vbox.Add(self.note_content, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(hbox, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        panel.SetSizer(vbox)
        self.note_title.SetFocus()
        self.note_dialog.ShowModal()
        self.note_dialog.Destroy()

    def edit_note_dialog(self, title, content):
        self.note_dialog = wx.Dialog(self, title=_('Edit note'), size=(500, 400))
        panel = wx.Panel(self.note_dialog)
        vbox = wx.BoxSizer(wx.VERTICAL)

        title_label = wx.StaticText(panel, label=_('Title:'))
        self.note_title = wx.TextCtrl(panel, value=title)
        content_label = wx.StaticText(panel, label=_('Content:'))
        self.note_content = wx.TextCtrl(panel, style=wx.TE_MULTILINE, value=content)

        save_button = wx.Button(panel, label=_('Save'))
        save_button.Bind(wx.EVT_BUTTON, self.on_save_note)
        cancel_button = wx.Button(panel, label=_('Cancel'))
        cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(save_button, flag=wx.RIGHT, border=10)
        hbox.Add(cancel_button)

        vbox.Add(title_label, flag=wx.ALL, border=5)
        vbox.Add(self.note_title, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(content_label, flag=wx.ALL, border=5)
        vbox.Add(self.note_content, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(hbox, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        panel.SetSizer(vbox)
        self.note_content.SetFocus()
        self.note_dialog.ShowModal()
        self.note_dialog.Destroy()

    def on_save_note(self, event):
        title = self.note_title.GetValue().strip()
        content = self.note_content.GetValue()
        if not title:
            self.speak(_('Please enter a title.'))
            return

        safe_title = self._sanitize_filename(title)
        new_path = os.path.join(self.current_dir, f'{safe_title}.tnote')

        # If editing and the title changed, delete the old file
        if self._edit_original_path and \
                os.path.abspath(self._edit_original_path) != os.path.abspath(new_path):
            if os.path.exists(self._edit_original_path):
                try:
                    os.remove(self._edit_original_path)
                except OSError:
                    pass

        try:
            with open(new_path, 'w', encoding='utf-8') as f:
                f.write(title + '\n' + content)
        except Exception:
            self.speak(_('Failed to save note.'))
            return

        self._edit_original_path = None
        self.note_dialog.EndModal(wx.ID_OK)
        self.load_notes_list()
        self.speak(_('Note saved!'))

    def on_cancel(self, event):
        self._edit_original_path = None
        self.note_dialog.EndModal(wx.ID_CANCEL)

    def on_new_folder(self, event):
        dialog = wx.TextEntryDialog(self, _('Enter folder name:'), _('New folder'))
        if dialog.ShowModal() == wx.ID_OK:
            folder_name = dialog.GetValue().strip()
            if folder_name:
                safe_name = self._sanitize_filename(folder_name)
                folder_path = os.path.join(self.current_dir, safe_name)
                if os.path.exists(folder_path):
                    self.speak(_('Folder already exists.'))
                else:
                    os.makedirs(folder_path)
                    self.load_notes_list()
                    self.speak(_('Folder created!'))
        dialog.Destroy()

    def on_open_note(self, event):
        self._open_item(event.GetIndex())

    def on_delete(self, event):
        index = self.notebook.GetFirstSelected()
        if index == -1:
            self.speak(_('No item selected.'))
            return
        if index >= len(self.items_data):
            return
        item_data = self.items_data[index]

        if item_data['type'] == 'folder':
            folder_path = item_data['path']
            folder_name = item_data['name']
            try:
                contents = os.listdir(folder_path)
            except OSError:
                contents = []
            if contents:
                dlg = wx.MessageDialog(
                    self,
                    _('Folder "{}" is not empty. Delete it and all its contents?').format(folder_name),
                    _('Confirm Delete'),
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
                )
                result = dlg.ShowModal()
                dlg.Destroy()
                if result != wx.ID_YES:
                    return
                try:
                    shutil.rmtree(folder_path)
                except Exception:
                    self.speak(_('Failed to delete folder.'))
                    return
            else:
                try:
                    os.rmdir(folder_path)
                except OSError:
                    self.speak(_('Failed to delete folder.'))
                    return
            self.speak(_('Folder deleted!'))
        else:
            note_path = item_data['path']
            if os.path.exists(note_path):
                try:
                    os.remove(note_path)
                    self.speak(_('Note deleted!'))
                except OSError:
                    self.speak(_('Failed to delete note.'))
                    return
            else:
                self.speak(_('Note not found.'))
                return

        self.load_notes_list()

    def on_back(self, event):
        if self.current_dir != self.notes_dir:
            self.current_dir = os.path.abspath(os.path.join(self.current_dir, os.pardir))
            self.load_notes_list()

    def on_settings(self, event):
        self.settings_dialog = wx.Dialog(self, title=_('tNotes Settings'), size=(300, 200))
        panel = wx.Panel(self.settings_dialog)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.announce_folders_cb = wx.CheckBox(panel, label=_('Announce folder note count'))
        self.announce_folders_cb.SetValue(self.settings.get('announce_folders', False))
        self.announce_shortcuts_cb = wx.CheckBox(panel, label=_('Announce keyboard shortcuts'))
        self.announce_shortcuts_cb.SetValue(self.settings.get('announce_shortcuts', False))

        save_button = wx.Button(panel, label=_('Save'))
        save_button.Bind(wx.EVT_BUTTON, self.on_save_settings)
        cancel_button = wx.Button(panel, label=_('Cancel'))
        cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel_settings)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(save_button, flag=wx.RIGHT, border=10)
        hbox.Add(cancel_button)

        vbox.Add(self.announce_folders_cb, flag=wx.ALL, border=5)
        vbox.Add(self.announce_shortcuts_cb, flag=wx.ALL, border=5)
        vbox.Add(hbox, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        panel.SetSizer(vbox)
        self.settings_dialog.ShowModal()
        self.settings_dialog.Destroy()

    def on_save_settings(self, event):
        self.settings['announce_folders'] = self.announce_folders_cb.GetValue()
        self.settings['announce_shortcuts'] = self.announce_shortcuts_cb.GetValue()
        self.save_settings()
        self.speak(_('Settings saved!'))
        self.settings_dialog.EndModal(wx.ID_OK)
        self.load_notes_list()

    def on_cancel_settings(self, event):
        self.settings_dialog.EndModal(wx.ID_CANCEL)

    def on_exit(self, event):
        self.Close()

    def on_list_key_down(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_BACK:
            self.on_back(event)
        elif keycode == wx.WXK_DELETE:
            self.on_delete(event)
        elif keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            selected = self.notebook.GetFirstSelected()
            if selected != -1:
                self._open_item(selected)
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

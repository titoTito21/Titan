import wx
import wx.adv
import os
import sys
import datetime
import threading
import time
import json

# Importowanie modułu do odtwarzania dźwięków
try:
    import pygame
except ImportError:
    pygame = None

# Importowanie modułu do TTS
import subprocess

# Ścieżki do katalogów i plików
if sys.platform == 'win32':
    APP_SETTINGS_DIR = os.path.join(
        os.environ['APPDATA'],
        'Titosoft', 'Titan', 'appsettings'
    )
else:
    APP_SETTINGS_DIR = os.path.join(
        os.path.expanduser('~'),
        '.titosoft', 'titan', 'appsettings'
    )

if not os.path.exists(APP_SETTINGS_DIR):
    os.makedirs(APP_SETTINGS_DIR)

CALENDAR_FILE = os.path.join(APP_SETTINGS_DIR, 'calendar.tcal')
SETTINGS_FILE = os.path.join(APP_SETTINGS_DIR, 'settings.ini')

SFX_DIR = 'sfx'

APP_TITLE = "Titan Organizer"

class Settings:
    def __init__(self):
        self.sounds_enabled = True
        self.sound_theme = 'default'
        self.tts_enabled = True
        self.view_mode = 'list'  # 'list' lub 'calendar'

    def load(self):
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                data = json.load(f)
                self.sounds_enabled = data.get('sounds_enabled', True)
                self.sound_theme = data.get('sound_theme', 'default')
                self.tts_enabled = data.get('tts_enabled', True)
                self.view_mode = data.get('view_mode', 'list')
        else:
            self.save()

    def save(self):
        data = {
            'sounds_enabled': self.sounds_enabled,
            'sound_theme': self.sound_theme,
            'tts_enabled': self.tts_enabled,
            'view_mode': self.view_mode,
        }
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(data, f)

class Reminder:
    def __init__(self, name, description, date, time, priority, repeat, done=False):
        self.name = name
        self.description = description
        self.date = date  # datetime.date
        self.time = time  # datetime.time
        self.priority = priority
        self.repeat = repeat
        self.done = done

    def to_dict(self):
        return {
            'name': self.name,
            'description': self.description,
            'date': self.date.isoformat(),
            'time': self.time.strftime('%H:%M'),
            'priority': self.priority,
            'repeat': self.repeat,
            'done': self.done,
        }

    @staticmethod
    def from_dict(data):
        name = data['name']
        description = data['description']
        date = datetime.date.fromisoformat(data['date'])
        time = datetime.datetime.strptime(data['time'], '%H:%M').time()
        priority = data['priority']
        repeat = data['repeat']
        done = data.get('done', False)
        return Reminder(name, description, date, time, priority, repeat, done)

class TitanOrganizer(wx.Frame):
    def __init__(self, parent, title):
        super(TitanOrganizer, self).__init__(parent, title=title, size=(800, 600))

        self.settings = Settings()
        self.settings.load()

        self.reminders = []
        self.load_reminders()

        self.init_ui()
        self.Centre()
        self.Show()

        # Odtworzenie dźwięku startowego
        self.play_sound('reminderstarted.ogg')

        # Uruchomienie wątku sprawdzającego przypomnienia
        self.check_reminders_thread = threading.Thread(target=self.check_reminders)
        self.check_reminders_thread.daemon = True
        self.check_reminders_thread.start()

    def init_ui(self):
        # Menu
        menubar = wx.MenuBar()

        fileMenu = wx.Menu()
        newItem = fileMenu.Append(wx.ID_NEW, '&Nowe przypomnienie\tCtrl+N')
        settingsItem = fileMenu.Append(wx.ID_PREFERENCES, '&Ustawienia programu')
        deleteItem = fileMenu.Append(wx.ID_DELETE, '&Usuń przypomnienie\tDelete')
        minimizeItem = fileMenu.Append(wx.ID_ANY, '&Zminimalizuj do zasobnika')
        exitItem = fileMenu.Append(wx.ID_EXIT, '&Wyjdź\tAlt+F4')
        menubar.Append(fileMenu, '&Plik')

        viewMenu = wx.Menu()
        sortMenu = wx.Menu()
        sortByName = sortMenu.AppendRadioItem(wx.ID_ANY, 'Nazwa &1')
        sortByPriority = sortMenu.AppendRadioItem(wx.ID_ANY, 'Priorytet &2')
        sortByDate = sortMenu.AppendRadioItem(wx.ID_ANY, 'Data &3')
        viewMenu.AppendSubMenu(sortMenu, 'Sortuj według')
        menubar.Append(viewMenu, '&Widok')

        self.SetMenuBar(menubar)

        # Powiązania zdarzeń
        self.Bind(wx.EVT_MENU, self.on_new_reminder, newItem)
        self.Bind(wx.EVT_MENU, self.on_settings, settingsItem)
        self.Bind(wx.EVT_MENU, self.on_delete_reminder, deleteItem)
        self.Bind(wx.EVT_MENU, self.on_minimize_to_tray, minimizeItem)
        self.Bind(wx.EVT_MENU, self.on_exit, exitItem)
        self.Bind(wx.EVT_MENU, self.on_sort_by_name, sortByName)
        self.Bind(wx.EVT_MENU, self.on_sort_by_priority, sortByPriority)
        self.Bind(wx.EVT_MENU, self.on_sort_by_date, sortByDate)

        # Skróty klawiszowe
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('N'), newItem.GetId()),
            (wx.ACCEL_NORMAL, wx.WXK_DELETE, deleteItem.GetId()),
            (wx.ACCEL_ALT, wx.WXK_F4, exitItem.GetId())
        ])
        self.SetAcceleratorTable(accel_tbl)

        # Widok listy przypomnień lub kalendarza
        if self.settings.view_mode == 'list':
            self.reminder_list = wx.ListCtrl(self, style=wx.LC_REPORT)
            self.reminder_list.InsertColumn(0, 'Nazwa', width=200)
            self.reminder_list.InsertColumn(1, 'Opis', width=200)
            self.reminder_list.InsertColumn(2, 'Data', width=100)
            self.reminder_list.InsertColumn(3, 'Godzina', width=100)
            self.reminder_list.InsertColumn(4, 'Priorytet', width=100)
            self.update_reminder_list()
            self.sizer = wx.BoxSizer(wx.VERTICAL)
            self.sizer.Add(self.reminder_list, 1, wx.EXPAND)
            self.SetSizer(self.sizer)
        else:
            # Implementacja widoku kalendarza
            pass  # Do uzupełnienia

        # Ikona zasobnika systemowego
        self.taskbar_icon = None
        self.create_taskbar_icon()

        # Timer do aktualizacji opisu ikony zasobnika
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_taskbar_icon_tooltip)
        self.timer.Start(60000)  # Co minutę

    def on_new_reminder(self, event):
        dlg = NewReminderDialog(self, self.settings.view_mode)
        if dlg.ShowModal() == wx.ID_OK:
            reminder = dlg.get_reminder()
            self.reminders.append(reminder)
            self.save_reminders()
            self.update_reminder_list()
            self.play_sound('reminderadded.ogg')
        dlg.Destroy()

    def on_settings(self, event):
        dlg = SettingsDialog(self, self.settings)
        if dlg.ShowModal() == wx.ID_OK:
            self.settings = dlg.get_settings()
            self.settings.save()
            # Aktualizacja widoku, jeśli to konieczne
            if self.settings.view_mode != 'list':
                # Implementacja aktualizacji widoku kalendarza
                pass
        dlg.Destroy()

    def on_delete_reminder(self, event):
        if self.settings.view_mode == 'list':
            index = self.reminder_list.GetFirstSelected()
            if index >= 0:
                del self.reminders[index]
                self.save_reminders()
                self.update_reminder_list()
                self.play_sound('reminderdeleted.ogg')
        else:
            # Implementacja usuwania w widoku kalendarza
            pass

    def on_minimize_to_tray(self, event):
        self.Hide()
        self.taskbar_icon.Show()

    def on_exit(self, event):
        self.Close()

    def on_sort_by_name(self, event):
        self.reminders.sort(key=lambda r: r.name)
        self.update_reminder_list()

    def on_sort_by_priority(self, event):
        self.reminders.sort(key=lambda r: r.priority)
        self.update_reminder_list()

    def on_sort_by_date(self, event):
        self.reminders.sort(key=lambda r: datetime.datetime.combine(r.date, r.time))
        self.update_reminder_list()

    def update_reminder_list(self):
        if self.settings.view_mode == 'list':
            self.reminder_list.DeleteAllItems()
            for rem in self.reminders:
                index = self.reminder_list.InsertItem(self.reminder_list.GetItemCount(), rem.name)
                self.reminder_list.SetItem(index, 1, rem.description)
                self.reminder_list.SetItem(index, 2, rem.date.strftime('%Y-%m-%d'))
                self.reminder_list.SetItem(index, 3, rem.time.strftime('%H:%M'))
                self.reminder_list.SetItem(index, 4, ["Niski", "Średni", "Wysoki"][rem.priority])
        else:
            # Implementacja aktualizacji w widoku kalendarza
            pass

    def load_reminders(self):
        if os.path.exists(CALENDAR_FILE):
            with open(CALENDAR_FILE, 'r') as f:
                data = json.load(f)
                self.reminders = [Reminder.from_dict(r) for r in data]
        else:
            self.save_reminders()

    def save_reminders(self):
        data = [r.to_dict() for r in self.reminders]
        with open(CALENDAR_FILE, 'w') as f:
            json.dump(data, f)

    def check_reminders(self):
        while True:
            now = datetime.datetime.now()
            for rem in self.reminders:
                if not rem.done:
                    rem_datetime = datetime.datetime.combine(rem.date, rem.time)
                    if now >= rem_datetime:
                        wx.CallAfter(self.show_reminder_dialog, rem)
            time.sleep(60)

    def show_reminder_dialog(self, reminder):
        if self.settings.sounds_enabled:
            self.play_sound('reminder.ogg')
        if self.settings.tts_enabled:
            self.speak_text(reminder.description)
        dlg = ReminderDialog(self, reminder)
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            reminder.done = True
            self.play_sound('reminderdone.ogg')
            # Usunięcie przypomnienia po 1 dniu
            threading.Timer(86400, self.remove_reminder, args=[reminder]).start()
        else:
            # Przypomnij ponownie za 5 minut
            threading.Timer(300, self.show_reminder_dialog, args=[reminder]).start()
        dlg.Destroy()
        self.save_reminders()
        self.update_reminder_list()

    def remove_reminder(self, reminder):
        if reminder in self.reminders:
            self.reminders.remove(reminder)
            self.save_reminders()
            wx.CallAfter(self.update_reminder_list)

    def play_sound(self, sound_file):
        if not self.settings.sounds_enabled:
            return
        if pygame is None:
            return  # Moduł pygame jest wymagany do odtwarzania dźwięków
        theme_dir = os.path.join(SFX_DIR, self.settings.sound_theme)
        sound_path = os.path.join(theme_dir, sound_file)
        if os.path.exists(sound_path):
            pygame.mixer.init()
            pygame.mixer.music.load(sound_path)
            pygame.mixer.music.play()
        else:
            print(f"Plik dźwiękowy {sound_path} nie został znaleziony.")

    def speak_text(self, text):
        if not self.settings.tts_enabled:
            return
        if sys.platform == 'win32':
            # Użycie SAPI.SpVoice przez COM
            import win32com.client
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Speak(text)
        elif sys.platform == 'darwin':
            # Użycie polecenia 'say'
            subprocess.call(['say', text])
        else:
            # Użycie 'espeak' lub 'festival' na Linuxie
            try:
                subprocess.call(['espeak', text])
            except FileNotFoundError:
                try:
                    subprocess.call(['festival', '--tts'], input=text.encode())
                except FileNotFoundError:
                    print("Nie znaleziono silnika TTS.")

    def create_taskbar_icon(self):
        if not self.taskbar_icon:
            icon = wx.Icon('icon.ico', wx.BITMAP_TYPE_ICO) if os.path.exists('icon.ico') else wx.NullIcon
            self.taskbar_icon = TaskBarIcon(self, icon)
        self.update_taskbar_icon_tooltip()

    def update_taskbar_icon_tooltip(self, event=None):
        total = len(self.reminders)
        done = sum(1 for r in self.reminders if r.done)
        not_done = total - done
        tooltip = f"Titan reminder - {total} przypomnień, {done} - wykonano, {not_done} - niewykonano"
        if self.taskbar_icon:
            self.taskbar_icon.SetIcon(self.taskbar_icon.icon, tooltip)

class TaskBarIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame, icon):
        super(TaskBarIcon, self).__init__()
        self.frame = frame
        self.icon = icon
        self.SetIcon(icon, "Titan Organizer")

        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_taskbar_left_dclick)
        self.Bind(wx.adv.EVT_TASKBAR_RIGHT_UP, self.on_taskbar_right_click)

    def on_taskbar_left_dclick(self, event):
        if not self.frame.IsShown():
            self.frame.Show()
        else:
            self.frame.Hide()

    def on_taskbar_right_click(self, event):
        menu = wx.Menu()
        restore_item = menu.Append(wx.ID_ANY, 'Przywróć')
        exit_item = menu.Append(wx.ID_EXIT, 'Wyjdź')
        self.Bind(wx.EVT_MENU, self.on_restore, restore_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_restore(self, event):
        if not self.frame.IsShown():
            self.frame.Show()

    def on_exit(self, event):
        wx.CallAfter(self.frame.Close)

class NewReminderDialog(wx.Dialog):
    def __init__(self, parent, view_mode):
        super(NewReminderDialog, self).__init__(parent, title="Nowe przypomnienie")

        self.view_mode = view_mode
        self.init_ui()
        self.SetSize((400, 400))
        self.Centre()

    def init_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Nazwa przypomnienia
        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        lbl1 = wx.StaticText(panel, label="Nazwa przypomnienia:")
        hbox1.Add(lbl1, flag=wx.RIGHT, border=8)
        self.name_txt = wx.TextCtrl(panel)
        hbox1.Add(self.name_txt, proportion=1)
        vbox.Add(hbox1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Opis przypomnienia
        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        lbl2 = wx.StaticText(panel, label="Opis:")
        hbox2.Add(lbl2, flag=wx.RIGHT, border=8)
        self.desc_txt = wx.TextCtrl(panel)
        hbox2.Add(self.desc_txt, proportion=1)
        vbox.Add(hbox2, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Data
        hbox3 = wx.BoxSizer(wx.HORIZONTAL)
        lbl3 = wx.StaticText(panel, label="Data:")
        hbox3.Add(lbl3, flag=wx.RIGHT, border=8)
        if self.view_mode == 'calendar':
            self.date_picker = wx.adv.CalendarCtrl(panel)
            hbox3.Add(self.date_picker, proportion=1)
        else:
            self.day_choice = wx.Choice(panel, choices=[str(i) for i in range(1, 32)])
            self.month_choice = wx.Choice(panel, choices=[str(i) for i in range(1, 13)])
            self.year_choice = wx.Choice(panel, choices=[str(i) for i in range(datetime.datetime.now().year, datetime.datetime.now().year + 10)])
            hbox3.Add(wx.StaticText(panel, label="Dzień:"), flag=wx.RIGHT, border=5)
            hbox3.Add(self.day_choice)
            hbox3.Add(wx.StaticText(panel, label="Miesiąc:"), flag=wx.LEFT|wx.RIGHT, border=5)
            hbox3.Add(self.month_choice)
            hbox3.Add(wx.StaticText(panel, label="Rok:"), flag=wx.LEFT|wx.RIGHT, border=5)
            hbox3.Add(self.year_choice)
        vbox.Add(hbox3, flag=wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Czas
        hbox4 = wx.BoxSizer(wx.HORIZONTAL)
        lbl4 = wx.StaticText(panel, label="Czas:")
        hbox4.Add(lbl4, flag=wx.RIGHT, border=8)
        if self.view_mode == 'calendar':
            self.time_picker = wx.adv.TimePickerCtrl(panel)
            hbox4.Add(self.time_picker)
        else:
            self.hour_choice = wx.Choice(panel, choices=[str(i) for i in range(0, 24)])
            self.minute_choice = wx.Choice(panel, choices=[str(i) for i in range(0, 60)])
            hbox4.Add(wx.StaticText(panel, label="Godzina:"), flag=wx.RIGHT, border=5)
            hbox4.Add(self.hour_choice)
            hbox4.Add(wx.StaticText(panel, label="Minuta:"), flag=wx.LEFT|wx.RIGHT, border=5)
            hbox4.Add(self.minute_choice)
        vbox.Add(hbox4, flag=wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Priorytet
        hbox5 = wx.BoxSizer(wx.HORIZONTAL)
        lbl5 = wx.StaticText(panel, label="Priorytet:")
        hbox5.Add(lbl5, flag=wx.RIGHT, border=8)
        self.priority_choice = wx.Choice(panel, choices=["Niski", "Średni", "Wysoki"])
        self.priority_choice.SetSelection(1)
        hbox5.Add(self.priority_choice)
        vbox.Add(hbox5, flag=wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Powtórz przypomnienie
        hbox6 = wx.BoxSizer(wx.HORIZONTAL)
        lbl6 = wx.StaticText(panel, label="Powtórz:")
        hbox6.Add(lbl6, flag=wx.RIGHT, border=8)
        self.repeat_choice = wx.Choice(panel, choices=[
            "2 razy co 3 minuty",
            "4 razy co minutę",
            "Co 15 minut",
            "Tylko raz"
        ])
        self.repeat_choice.SetSelection(3)
        hbox6.Add(self.repeat_choice)
        vbox.Add(hbox6, flag=wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Przyciski
        hbox7 = wx.BoxSizer(wx.HORIZONTAL)
        okButton = wx.Button(panel, wx.ID_OK, label='OK')
        closeButton = wx.Button(panel, wx.ID_CANCEL, label='Anuluj')
        hbox7.Add(okButton)
        hbox7.Add(closeButton, flag=wx.LEFT|wx.BOTTOM, border=5)
        vbox.Add(hbox7, flag=wx.ALIGN_CENTER|wx.TOP|wx.BOTTOM, border=10)

        panel.SetSizer(vbox)

    def get_reminder(self):
        name = self.name_txt.GetValue()
        description = self.desc_txt.GetValue()
        if self.view_mode == 'calendar':
            date = self.date_picker.GetDate()
            date_py = datetime.date(date.GetYear(), date.GetMonth() + 1, date.GetDay())
            time = self.time_picker.GetValue()
            time_py = datetime.time(time.GetHour(), time.GetMinute())
        else:
            day = int(self.day_choice.GetStringSelection())
            month = int(self.month_choice.GetStringSelection())
            year = int(self.year_choice.GetStringSelection())
            date_py = datetime.date(year, month, day)
            hour = int(self.hour_choice.GetStringSelection())
            minute = int(self.minute_choice.GetStringSelection())
            time_py = datetime.time(hour, minute)
        priority = self.priority_choice.GetSelection()
        repeat = self.repeat_choice.GetSelection()
        reminder = Reminder(name, description, date_py, time_py, priority, repeat)
        return reminder

class ReminderDialog(wx.Dialog):
    def __init__(self, parent, reminder):
        super(ReminderDialog, self).__init__(parent, title="Przypomnienie")

        self.reminder = reminder
        self.init_ui()
        self.SetSize((300, 200))
        self.Centre()

    def init_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(panel, label=self.reminder.description)
        vbox.Add(lbl, flag=wx.ALL|wx.EXPAND, border=10)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        doneButton = wx.Button(panel, wx.ID_OK, label='Wykonano')
        snoozeButton = wx.Button(panel, wx.ID_CANCEL, label='Moment')
        hbox.Add(doneButton)
        hbox.Add(snoozeButton, flag=wx.LEFT, border=5)
        vbox.Add(hbox, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=10)

        panel.SetSizer(vbox)

class SettingsDialog(wx.Dialog):
    def __init__(self, parent, settings):
        super(SettingsDialog, self).__init__(parent, title="Ustawienia programu")

        self.settings = settings
        self.init_ui()
        self.SetSize((400, 300))
        self.Centre()

    def init_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Dźwięki
        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        self.sounds_checkbox = wx.CheckBox(panel, label="Dźwięki")
        self.sounds_checkbox.SetValue(self.settings.sounds_enabled)
        hbox1.Add(self.sounds_checkbox)
        vbox.Add(hbox1, flag=wx.LEFT|wx.TOP, border=10)

        # Temat dźwiękowy
        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        lbl1 = wx.StaticText(panel, label="Temat dźwiękowy:")
        hbox2.Add(lbl1, flag=wx.RIGHT, border=8)
        self.theme_choice = wx.Choice(panel, choices=self.get_sound_themes())
        if self.settings.sound_theme in self.get_sound_themes():
            index = self.get_sound_themes().index(self.settings.sound_theme)
            self.theme_choice.SetSelection(index)
        else:
            self.theme_choice.SetSelection(0)
        hbox2.Add(self.theme_choice)
        vbox.Add(hbox2, flag=wx.LEFT|wx.TOP, border=10)
        self.theme_choice.Bind(wx.EVT_CHOICE, self.on_theme_selected)

        # Tekst na mowę
        hbox3 = wx.BoxSizer(wx.HORIZONTAL)
        self.tts_checkbox = wx.CheckBox(panel, label="Tekst na mowę")
        self.tts_checkbox.SetValue(self.settings.tts_enabled)
        hbox3.Add(self.tts_checkbox)
        vbox.Add(hbox3, flag=wx.LEFT|wx.TOP, border=10)

        # Widok listy przypomnień
        hbox4 = wx.BoxSizer(wx.HORIZONTAL)
        lbl2 = wx.StaticText(panel, label="Widok listy przypomnień:")
        hbox4.Add(lbl2, flag=wx.RIGHT, border=8)
        self.view_choice = wx.Choice(panel, choices=["Lista (zalecane dla osób z niepełnosprawnością wzroku)", "Widok kalendarza"])
        if self.settings.view_mode == 'list':
            self.view_choice.SetSelection(0)
        else:
            self.view_choice.SetSelection(1)
        hbox4.Add(self.view_choice)
        vbox.Add(hbox4, flag=wx.LEFT|wx.TOP, border=10)

        # Przyciski
        hbox5 = wx.BoxSizer(wx.HORIZONTAL)
        okButton = wx.Button(panel, wx.ID_OK, label='OK')
        cancelButton = wx.Button(panel, wx.ID_CANCEL, label='Anuluj')
        hbox5.Add(okButton)
        hbox5.Add(cancelButton, flag=wx.LEFT|wx.BOTTOM, border=5)
        vbox.Add(hbox5, flag=wx.ALIGN_CENTER|wx.TOP|wx.BOTTOM, border=10)

        panel.SetSizer(vbox)

    def on_theme_selected(self, event):
        theme = self.theme_choice.GetStringSelection()
        # Odtworzenie dźwięku prezentacji dla wybranego tematu
        theme_dir = os.path.join(SFX_DIR, theme)
        intro_sound = os.path.join(theme_dir, 'intro.ogg')
        if os.path.exists(intro_sound):
            if pygame:
                pygame.mixer.init()
                pygame.mixer.music.load(intro_sound)
                pygame.mixer.music.play()
            else:
                print("Moduł pygame nie jest dostępny.")

    def get_sound_themes(self):
        themes = []
        if os.path.exists(SFX_DIR):
            for name in os.listdir(SFX_DIR):
                if os.path.isdir(os.path.join(SFX_DIR, name)):
                    themes.append(name)
        return themes

    def get_settings(self):
        self.settings.sounds_enabled = self.sounds_checkbox.GetValue()
        self.settings.sound_theme = self.theme_choice.GetStringSelection()
        self.settings.tts_enabled = self.tts_checkbox.GetValue()
        self.settings.view_mode = 'list' if self.view_choice.GetSelection() == 0 else 'calendar'
        return self.settings

if __name__ == '__main__':
    app = wx.App()
    TitanOrganizer(None, title=APP_TITLE)
    app.MainLoop()

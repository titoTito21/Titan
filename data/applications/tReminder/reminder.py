import wx
import wx.adv
import os
import sys
import platform
import datetime
import threading
import time
import json
import subprocess
from translation import _

# Importowanie modułu do odtwarzania dźwięków
try:
    import pygame
except ImportError:
    pygame = None

# TCE Speech: use Titan TTS engine (stereo speech) when available
try:
    from src.titan_core.tce_speech import speak as _tce_speak
except ImportError:
    _tce_speak = None

if _tce_speak is None:
    # Standalone fallback (outside Titan environment)
    try:
        import accessible_output3.outputs.auto as _ao3
        _ao3_speaker = _ao3.Auto()
    except Exception:
        _ao3_speaker = None

# Ścieżki do katalogów i plików
def _get_app_settings_dir():
    _plat = platform.system()
    if _plat == 'Windows':
        appdata = os.getenv('APPDATA') or os.path.expanduser('~')
        return os.path.join(appdata, 'Titosoft', 'Titan', 'appsettings')
    elif _plat == 'Darwin':
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'Titosoft', 'Titan', 'appsettings')
    else:
        return os.path.join(os.path.expanduser('~'), '.config', 'Titosoft', 'Titan', 'appsettings')

APP_SETTINGS_DIR = _get_app_settings_dir()

if not os.path.exists(APP_SETTINGS_DIR):
    os.makedirs(APP_SETTINGS_DIR)

CALENDAR_FILE = os.path.join(APP_SETTINGS_DIR, 'calendar.tcal')
SETTINGS_FILE = os.path.join(APP_SETTINGS_DIR, 'settings.ini')

SFX_DIR = 'sfx'

APP_TITLE = _("Titan Organizer")

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
        self.check_reminders_thread = threading.Thread(target=self.check_reminders, daemon=True)
        self.check_reminders_thread.start()

    def init_ui(self):
        # Menu
        menubar = wx.MenuBar()

        fileMenu = wx.Menu()
        newItem = fileMenu.Append(wx.ID_NEW, _('&Nowe przypomnienie\tCtrl+N'))
        settingsItem = fileMenu.Append(wx.ID_PREFERENCES, _('&Ustawienia programu'))
        deleteItem = fileMenu.Append(wx.ID_DELETE, _('&Usuń przypomnienie\tDelete'))
        minimizeItem = fileMenu.Append(wx.ID_ANY, _('&Zminimalizuj do zasobnika'))
        exitItem = fileMenu.Append(wx.ID_EXIT, _('&Wyjdź\tAlt+F4'))
        menubar.Append(fileMenu, _('&Plik'))

        viewMenu = wx.Menu()
        sortMenu = wx.Menu()
        sortByName = sortMenu.AppendRadioItem(wx.ID_ANY, _('Nazwa &1'))
        sortByPriority = sortMenu.AppendRadioItem(wx.ID_ANY, _('Priorytet &2'))
        sortByDate = sortMenu.AppendRadioItem(wx.ID_ANY, _('Data &3'))
        viewMenu.AppendSubMenu(sortMenu, _('Sortuj według'))
        menubar.Append(viewMenu, _('&Widok'))

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
            self.reminder_list.InsertColumn(0, _('Nazwa'), width=200)
            self.reminder_list.InsertColumn(1, _('Opis'), width=200)
            self.reminder_list.InsertColumn(2, _('Data'), width=100)
            self.reminder_list.InsertColumn(3, _('Godzina'), width=100)
            self.reminder_list.InsertColumn(4, _('Priorytet'), width=100)
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
                self.reminder_list.SetItem(index, 4, [_("Niski"), _("Średni"), _("Wysoki")][rem.priority])
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
            print(_("Plik dźwiękowy {} nie został znaleziony.").format(sound_path))

    def speak_text(self, text):
        if not self.settings.tts_enabled:
            return
        if _tce_speak is not None:
            _tce_speak(text)
            return
        # Standalone fallback
        if _ao3_speaker:
            try:
                _ao3_speaker.speak(text, interrupt=True)
                return
            except Exception:
                pass
        try:
            _plat = platform.system()
            if _plat == 'Windows':
                import win32com.client
                win32com.client.Dispatch("SAPI.SpVoice").Speak(text)
            elif _plat == 'Darwin':
                subprocess.Popen(['say', text])
            else:
                subprocess.Popen(['spd-say', text])
        except Exception:
            pass

    def create_taskbar_icon(self):
        if not self.taskbar_icon:
            icon = wx.Icon('icon.ico', wx.BITMAP_TYPE_ICO) if os.path.exists('icon.ico') else wx.NullIcon
            self.taskbar_icon = TaskBarIcon(self, icon)
        self.update_taskbar_icon_tooltip()

    def update_taskbar_icon_tooltip(self, event=None):
        total = len(self.reminders)
        done = sum(1 for r in self.reminders if r.done)
        not_done = total - done
        tooltip = _("Titan reminder - {} przypomnień, {} - wykonano, {} - niewykonano").format(total, done, not_done)
        if self.taskbar_icon:
            self.taskbar_icon.SetIcon(self.taskbar_icon.icon, tooltip)

class TaskBarIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame, icon):
        super(TaskBarIcon, self).__init__()
        self.frame = frame
        self.icon = icon
        self.SetIcon(icon, _("Titan Organizer"))

        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_taskbar_left_dclick)
        self.Bind(wx.adv.EVT_TASKBAR_RIGHT_UP, self.on_taskbar_right_click)

    def on_taskbar_left_dclick(self, event):
        if not self.frame.IsShown():
            self.frame.Show()
        else:
            self.frame.Hide()

    def on_taskbar_right_click(self, event):
        menu = wx.Menu()
        restore_item = menu.Append(wx.ID_ANY, _('Przywróć'))
        exit_item = menu.Append(wx.ID_EXIT, _('Wyjdź'))
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
        super(NewReminderDialog, self).__init__(parent, title=_("Nowe przypomnienie"))

        self.view_mode = view_mode
        self.init_ui()
        self.SetSize((400, 400))
        self.Centre()

    def init_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Nazwa przypomnienia
        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        lbl1 = wx.StaticText(panel, label=_("Nazwa przypomnienia:"))
        hbox1.Add(lbl1, flag=wx.RIGHT, border=8)
        self.name_txt = wx.TextCtrl(panel)
        hbox1.Add(self.name_txt, proportion=1)
        vbox.Add(hbox1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Opis przypomnienia
        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        lbl2 = wx.StaticText(panel, label=_("Opis:"))
        hbox2.Add(lbl2, flag=wx.RIGHT, border=8)
        self.desc_txt = wx.TextCtrl(panel)
        hbox2.Add(self.desc_txt, proportion=1)
        vbox.Add(hbox2, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Data
        hbox3 = wx.BoxSizer(wx.HORIZONTAL)
        lbl3 = wx.StaticText(panel, label=_("Data:"))
        hbox3.Add(lbl3, flag=wx.RIGHT, border=8)
        if self.view_mode == 'calendar':
            self.date_picker = wx.adv.CalendarCtrl(panel)
            hbox3.Add(self.date_picker, proportion=1)
        else:
            self.day_choice = wx.Choice(panel, choices=[str(i) for i in range(1, 32)])
            self.month_choice = wx.Choice(panel, choices=[str(i) for i in range(1, 13)])
            self.year_choice = wx.Choice(panel, choices=[str(i) for i in range(datetime.datetime.now().year, datetime.datetime.now().year + 10)])
            hbox3.Add(wx.StaticText(panel, label=_("Dzień:")), flag=wx.RIGHT, border=5)
            hbox3.Add(self.day_choice)
            hbox3.Add(wx.StaticText(panel, label=_("Miesiąc:")), flag=wx.LEFT|wx.RIGHT, border=5)
            hbox3.Add(self.month_choice)
            hbox3.Add(wx.StaticText(panel, label=_("Rok:")), flag=wx.LEFT|wx.RIGHT, border=5)
            hbox3.Add(self.year_choice)
        vbox.Add(hbox3, flag=wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Czas
        hbox4 = wx.BoxSizer(wx.HORIZONTAL)
        lbl4 = wx.StaticText(panel, label=_("Czas:"))
        hbox4.Add(lbl4, flag=wx.RIGHT, border=8)
        if self.view_mode == 'calendar':
            self.time_picker = wx.adv.TimePickerCtrl(panel)
            hbox4.Add(self.time_picker)
        else:
            self.hour_choice = wx.Choice(panel, choices=[str(i) for i in range(0, 24)])
            self.minute_choice = wx.Choice(panel, choices=[str(i) for i in range(0, 60)])
            hbox4.Add(wx.StaticText(panel, label=_("Godzina:")), flag=wx.RIGHT, border=5)
            hbox4.Add(self.hour_choice)
            hbox4.Add(wx.StaticText(panel, label=_("Minuta:")), flag=wx.LEFT|wx.RIGHT, border=5)
            hbox4.Add(self.minute_choice)
        vbox.Add(hbox4, flag=wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Priorytet
        hbox5 = wx.BoxSizer(wx.HORIZONTAL)
        lbl5 = wx.StaticText(panel, label=_("Priorytet:"))
        hbox5.Add(lbl5, flag=wx.RIGHT, border=8)
        self.priority_choice = wx.Choice(panel, choices=[_("Niski"), _("Średni"), _("Wysoki")])
        self.priority_choice.SetSelection(1)
        hbox5.Add(self.priority_choice)
        vbox.Add(hbox5, flag=wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Powtórz przypomnienie
        hbox6 = wx.BoxSizer(wx.HORIZONTAL)
        lbl6 = wx.StaticText(panel, label=_("Powtórz:"))
        hbox6.Add(lbl6, flag=wx.RIGHT, border=8)
        self.repeat_choice = wx.Choice(panel, choices=[
            _("2 razy co 3 minuty"),
            _("4 razy co minutę"),
            _("Co 15 minut"),
            _("Tylko raz")
        ])
        self.repeat_choice.SetSelection(3)
        hbox6.Add(self.repeat_choice)
        vbox.Add(hbox6, flag=wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Przyciski
        hbox7 = wx.BoxSizer(wx.HORIZONTAL)
        okButton = wx.Button(panel, wx.ID_OK, label=_('OK'))
        closeButton = wx.Button(panel, wx.ID_CANCEL, label=_('Anuluj'))
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
        super(ReminderDialog, self).__init__(parent, title=_("Przypomnienie"))

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
        doneButton = wx.Button(panel, wx.ID_OK, label=_('Wykonano'))
        snoozeButton = wx.Button(panel, wx.ID_CANCEL, label=_('Moment'))
        hbox.Add(doneButton)
        hbox.Add(snoozeButton, flag=wx.LEFT, border=5)
        vbox.Add(hbox, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=10)

        panel.SetSizer(vbox)

class SettingsDialog(wx.Dialog):
    def __init__(self, parent, settings):
        super(SettingsDialog, self).__init__(parent, title=_("Ustawienia programu"))

        self.settings = settings
        self.init_ui()
        self.SetSize((400, 300))
        self.Centre()

    def init_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Dźwięki
        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        self.sounds_checkbox = wx.CheckBox(panel, label=_("Dźwięki"))
        self.sounds_checkbox.SetValue(self.settings.sounds_enabled)
        hbox1.Add(self.sounds_checkbox)
        vbox.Add(hbox1, flag=wx.LEFT|wx.TOP, border=10)

        # Temat dźwiękowy
        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        lbl1 = wx.StaticText(panel, label=_("Temat dźwiękowy:"))
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
        self.tts_checkbox = wx.CheckBox(panel, label=_("Tekst na mowę"))
        self.tts_checkbox.SetValue(self.settings.tts_enabled)
        hbox3.Add(self.tts_checkbox)
        vbox.Add(hbox3, flag=wx.LEFT|wx.TOP, border=10)

        # Widok listy przypomnień
        hbox4 = wx.BoxSizer(wx.HORIZONTAL)
        lbl2 = wx.StaticText(panel, label=_("Widok listy przypomnień:"))
        hbox4.Add(lbl2, flag=wx.RIGHT, border=8)
        self.view_choice = wx.Choice(panel, choices=[_("Lista (zalecane dla osób z niepełnosprawnością wzroku)"), _("Widok kalendarza")])
        if self.settings.view_mode == 'list':
            self.view_choice.SetSelection(0)
        else:
            self.view_choice.SetSelection(1)
        hbox4.Add(self.view_choice)
        vbox.Add(hbox4, flag=wx.LEFT|wx.TOP, border=10)

        # Przyciski
        hbox5 = wx.BoxSizer(wx.HORIZONTAL)
        okButton = wx.Button(panel, wx.ID_OK, label=_('OK'))
        cancelButton = wx.Button(panel, wx.ID_CANCEL, label=_('Anuluj'))
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
                print(_("Moduł pygame nie jest dostępny."))

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

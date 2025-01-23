import wx
import os
import sys
import datetime
import platform
import configparser
import re

# Identyfikatory dla nowych pozycji menu
ID_FIND = wx.NewIdRef()
ID_REPLACE = wx.NewIdRef()
ID_INSERT_DATETIME = wx.NewIdRef()
ID_INSERT_UNICODE = wx.NewIdRef()
ID_SETTINGS = wx.NewIdRef()

class FindDialog(wx.Dialog):
    def __init__(self, parent):
        super(FindDialog, self).__init__(parent, title="Znajdź", size=(300, 150))
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        label_find = wx.StaticText(panel, label="Szukaj:")
        hbox1.Add(label_find, flag=wx.ALL|wx.CENTER, border=5)
        self.text_find = wx.TextCtrl(panel)
        hbox1.Add(self.text_find, proportion=1, flag=wx.ALL|wx.EXPAND, border=5)
        vbox.Add(hbox1, flag=wx.EXPAND|wx.ALL, border=5)

        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        btn_find = wx.Button(panel, label="Znajdź dalej")
        btn_find.Bind(wx.EVT_BUTTON, self.OnFind)
        hbox2.Add(btn_find, flag=wx.ALL, border=5)

        btn_cancel = wx.Button(panel, label="Anuluj")
        btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
        hbox2.Add(btn_cancel, flag=wx.ALL, border=5)

        vbox.Add(hbox2, flag=wx.ALIGN_RIGHT|wx.ALL, border=5)
        panel.SetSizer(vbox)

        self.found_pos = -1

    def OnFind(self, event):
        self.EndModal(wx.ID_OK)

    def OnCancel(self, event):
        self.EndModal(wx.ID_CANCEL)

    def GetFindText(self):
        return self.text_find.GetValue()


class ReplaceDialog(wx.Dialog):
    def __init__(self, parent):
        super(ReplaceDialog, self).__init__(parent, title="Zamień tekst", size=(300, 200))
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        label_find = wx.StaticText(panel, label="Szukaj:")
        hbox1.Add(label_find, flag=wx.ALL|wx.CENTER, border=5)
        self.text_find = wx.TextCtrl(panel)
        hbox1.Add(self.text_find, proportion=1, flag=wx.ALL|wx.EXPAND, border=5)
        vbox.Add(hbox1, flag=wx.EXPAND|wx.ALL, border=5)

        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        label_replace = wx.StaticText(panel, label="Zamień na:")
        hbox2.Add(label_replace, flag=wx.ALL|wx.CENTER, border=5)
        self.text_replace = wx.TextCtrl(panel)
        hbox2.Add(self.text_replace, proportion=1, flag=wx.ALL|wx.EXPAND, border=5)
        vbox.Add(hbox2, flag=wx.EXPAND|wx.ALL, border=5)

        hbox3 = wx.BoxSizer(wx.HORIZONTAL)
        btn_replace = wx.Button(panel, label="Zamień")
        btn_replace.Bind(wx.EVT_BUTTON, self.OnReplace)
        hbox3.Add(btn_replace, flag=wx.ALL, border=5)

        btn_cancel = wx.Button(panel, label="Anuluj")
        btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
        hbox3.Add(btn_cancel, flag=wx.ALL, border=5)

        vbox.Add(hbox3, flag=wx.ALIGN_RIGHT|wx.ALL, border=5)
        panel.SetSizer(vbox)

    def OnReplace(self, event):
        self.EndModal(wx.ID_OK)

    def OnCancel(self, event):
        self.EndModal(wx.ID_CANCEL)

    def GetFindText(self):
        return self.text_find.GetValue()

    def GetReplaceText(self):
        return self.text_replace.GetValue()


class UnicodeDialog(wx.Dialog):
    def __init__(self, parent):
        super(UnicodeDialog, self).__init__(parent, title="Wstaw znak Unicode", size=(300, 150))
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(panel, label="Podaj kod punktu kodowego (np. U+00A9):")
        vbox.Add(label, flag=wx.ALL, border=5)

        self.unicode_input = wx.TextCtrl(panel)
        vbox.Add(self.unicode_input, flag=wx.ALL|wx.EXPAND, border=5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(panel, label="OK")
        btn_ok.Bind(wx.EVT_BUTTON, self.OnOK)
        hbox.Add(btn_ok, flag=wx.ALL, border=5)

        btn_cancel = wx.Button(panel, label="Anuluj")
        btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
        hbox.Add(btn_cancel, flag=wx.ALL, border=5)

        vbox.Add(hbox, flag=wx.ALIGN_RIGHT|wx.ALL, border=5)
        panel.SetSizer(vbox)

    def OnOK(self, event):
        self.EndModal(wx.ID_OK)

    def OnCancel(self, event):
        self.EndModal(wx.ID_CANCEL)

    def GetUnicodeChar(self):
        val = self.unicode_input.GetValue().strip().upper()
        # Spróbujmy parsować np. U+00A9
        if val.startswith("U+"):
            val = val[2:]
        try:
            code_point = int(val, 16)
            return chr(code_point)
        except:
            return ""


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, ini_path):
        super(SettingsDialog, self).__init__(parent, title="Ustawienia programu", size=(400, 300))
        self.ini_path = ini_path
        self.config = configparser.ConfigParser()

        if os.path.exists(self.ini_path):
            self.config.read(self.ini_path)
        else:
            self.config['Ogólne'] = {}
            self.config['Tekst'] = {}

        # Domyślne wartości
        if 'auto_save' not in self.config['Ogólne']:
            self.config['Ogólne']['auto_save'] = 'wyłączone'
        if 'line_ending' not in self.config['Tekst']:
            self.config['Tekst']['line_ending'] = 'windows'
        if 'custom_line_ending' not in self.config['Tekst']:
            self.config['Tekst']['custom_line_ending'] = ''

        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        notebook = wx.Notebook(panel)

        # -------- Zakładka Ogólne --------
        ogolne_panel = wx.Panel(notebook)
        ogolne_sizer = wx.BoxSizer(wx.VERTICAL)

        ogolne_label = wx.StaticText(ogolne_panel, label="Ogólne")
        ogolne_sizer.Add(ogolne_label, flag=wx.ALL, border=5)

        autosave_label = wx.StaticText(ogolne_panel, label="Automatyczny zapis co:")
        ogolne_sizer.Add(autosave_label, flag=wx.ALL, border=5)

        self.autosave_choices = ["5 minut", "10 minut", "wyłączone"]
        self.autosave_choice = wx.Choice(ogolne_panel, choices=self.autosave_choices)
        current_auto = self.config['Ogólne'].get('auto_save', 'wyłączone')
        if current_auto in self.autosave_choices:
            self.autosave_choice.SetSelection(self.autosave_choices.index(current_auto))
        else:
            self.autosave_choice.SetSelection(self.autosave_choices.index('wyłączone'))
        ogolne_sizer.Add(self.autosave_choice, flag=wx.ALL|wx.EXPAND, border=5)

        ogolne_panel.SetSizer(ogolne_sizer)

        # -------- Zakładka Tekst --------
        tekst_panel = wx.Panel(notebook)
        tekst_sizer = wx.BoxSizer(wx.VERTICAL)

        tekst_label = wx.StaticText(tekst_panel, label="Tekst")
        tekst_sizer.Add(tekst_label, flag=wx.ALL, border=5)

        line_ending_label = wx.StaticText(tekst_panel, label="Symbol końca linii:")
        tekst_sizer.Add(line_ending_label, flag=wx.ALL, border=5)

        self.line_ending_choices = ["windows", "MAC OS/linux/unix", "inny symbol..."]
        self.line_ending_choice = wx.Choice(tekst_panel, choices=self.line_ending_choices)
        current_le = self.config['Tekst'].get('line_ending', 'windows')
        if current_le in self.line_ending_choices:
            self.line_ending_choice.SetSelection(self.line_ending_choices.index(current_le))
        else:
            # Jeśli brak w standardowych, to inny symbol
            self.line_ending_choice.SetSelection(self.line_ending_choices.index("inny symbol..."))

        tekst_sizer.Add(self.line_ending_choice, flag=wx.ALL|wx.EXPAND, border=5)

        self.custom_line_ending_label = wx.StaticText(tekst_panel, label="Napisz symbol końca linii:")
        self.custom_line_ending_text = wx.TextCtrl(tekst_panel)
        self.custom_line_ending_text.SetValue(self.config['Tekst'].get('custom_line_ending', ''))

        # Pokazuj/ukrywaj pole w zależności od wyboru
        if current_le == "inny symbol...":
            self.custom_line_ending_label.Show(True)
            self.custom_line_ending_text.Show(True)
        else:
            self.custom_line_ending_label.Show(False)
            self.custom_line_ending_text.Show(False)

        tekst_sizer.Add(self.custom_line_ending_label, flag=wx.ALL, border=5)
        tekst_sizer.Add(self.custom_line_ending_text, flag=wx.ALL|wx.EXPAND, border=5)

        self.line_ending_choice.Bind(wx.EVT_CHOICE, self.OnLineEndingChoice)

        tekst_panel.SetSizer(tekst_sizer)

        notebook.AddPage(ogolne_panel, "Ogólne")
        notebook.AddPage(tekst_panel, "Tekst")

        main_sizer.Add(notebook, proportion=1, flag=wx.ALL|wx.EXPAND, border=5)

        # Przyciski OK/Anuluj
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(panel, label="OK")
        btn_cancel = wx.Button(panel, label="Anuluj")
        btn_ok.Bind(wx.EVT_BUTTON, self.OnOK)
        btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
        btn_sizer.Add(btn_ok, flag=wx.ALL, border=5)
        btn_sizer.Add(btn_cancel, flag=wx.ALL, border=5)

        main_sizer.Add(btn_sizer, flag=wx.ALIGN_RIGHT|wx.ALL, border=5)

        panel.SetSizer(main_sizer)

    def OnLineEndingChoice(self, event):
        choice = self.line_ending_choice.GetStringSelection()
        if choice == "inny symbol...":
            self.custom_line_ending_label.Show(True)
            self.custom_line_ending_text.Show(True)
        else:
            self.custom_line_ending_label.Show(False)
            self.custom_line_ending_text.Show(False)
        self.Layout()

    def OnOK(self, event):
        # Zapisz ustawienia
        auto_val = self.autosave_choice.GetStringSelection()
        self.config['Ogólne']['auto_save'] = auto_val

        line_ending_val = self.line_ending_choice.GetStringSelection()
        self.config['Tekst']['line_ending'] = line_ending_val
        if line_ending_val == 'inny symbol...':
            self.config['Tekst']['custom_line_ending'] = self.custom_line_ending_text.GetValue()
        else:
            self.config['Tekst']['custom_line_ending'] = ''

        # Zapis do pliku
        os.makedirs(os.path.dirname(self.ini_path), exist_ok=True)
        with open(self.ini_path, 'w', encoding='utf-8') as f:
            self.config.write(f)
        self.EndModal(wx.ID_OK)

    def OnCancel(self, event):
        self.EndModal(wx.ID_CANCEL)


class TextEditor(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(TextEditor, self).__init__(*args, **kwargs)
        
        self.current_file = None
        self.config = configparser.ConfigParser()
        
        # Ścieżka do pliku ustawień w zależności od systemu
        if platform.system().lower().startswith('win'):
            appdata = os.environ.get('APPDATA', os.path.expanduser("~"))
            self.ini_path = os.path.join(appdata, "Titosoft", "Titan", "appsettings", "tedit.ini")
        else:
            # Na systemach Unixowych np. w katalogu domowym
            self.ini_path = os.path.join(os.path.expanduser("~"), ".tedit.ini")

        self.LoadSettings()

        # Ustawienie tytułu
        self.SetTitle("Edytor tekstowy TEdit")
        
        # Tworzenie panelu i pola tekstowego
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        label = wx.StaticText(panel, label="Treść dokumentu:")
        vbox.Add(label, flag=wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, border=10)
        
        self.text_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE)
        vbox.Add(self.text_ctrl, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        
        panel.SetSizer(vbox)
        
        # Tworzenie menu
        self.CreateMenuBar()
        
        # Ustawienie skrótów klawiaturowych
        self.Bind(wx.EVT_MENU, self.OnNew, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.OnOpen, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self.OnSave, id=wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self.OnSaveAs, id=wx.ID_SAVEAS)
        self.Bind(wx.EVT_MENU, self.OnClose, id=wx.ID_EXIT)
        
        self.Bind(wx.EVT_MENU, self.OnUndo, id=wx.ID_UNDO)
        self.Bind(wx.EVT_MENU, self.OnRedo, id=wx.ID_REDO)
        self.Bind(wx.EVT_MENU, self.OnCut, id=wx.ID_CUT)
        self.Bind(wx.EVT_MENU, self.OnCopy, id=wx.ID_COPY)
        self.Bind(wx.EVT_MENU, self.OnPaste, id=wx.ID_PASTE)
        self.Bind(wx.EVT_MENU, self.OnSelectAll, id=wx.ID_SELECTALL)
        
        self.Bind(wx.EVT_MENU, self.OnAbout, id=wx.ID_ABOUT)

        self.Bind(wx.EVT_MENU, self.OnFind, id=ID_FIND)
        self.Bind(wx.EVT_MENU, self.OnReplace, id=ID_REPLACE)
        
        self.Bind(wx.EVT_MENU, self.OnInsertDateTime, id=ID_INSERT_DATETIME)
        self.Bind(wx.EVT_MENU, self.OnInsertUnicode, id=ID_INSERT_UNICODE)

        self.Bind(wx.EVT_MENU, self.OnSettings, id=ID_SETTINGS)
        
        self.Bind(wx.EVT_CLOSE, self.OnCloseWindow)
        
        self.Show()

        # Timer do automatycznego zapisu
        self.auto_save_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnAutoSave, self.auto_save_timer)
        self.SetupAutoSave()

        # Otwieranie pliku przekazanego jako argument przy uruchomieniu
        if len(sys.argv) > 1:
            wx.CallAfter(self.LoadFile, sys.argv[1])

    def LoadSettings(self):
        if os.path.exists(self.ini_path):
            self.config.read(self.ini_path)
        else:
            self.config['Ogólne'] = {}
            self.config['Ogólne']['auto_save'] = 'wyłączone'
            self.config['Tekst'] = {}
            self.config['Tekst']['line_ending'] = 'windows'
            self.config['Tekst']['custom_line_ending'] = ''

    def SetupAutoSave(self):
        auto_val = self.config['Ogólne'].get('auto_save', 'wyłączone')
        interval = 0
        if auto_val == "5 minut":
            interval = 5 * 60 * 1000
        elif auto_val == "10 minut":
            interval = 10 * 60 * 1000

        if interval > 0:
            self.auto_save_timer.Start(interval)
        else:
            self.auto_save_timer.Stop()

    def CreateMenuBar(self):
        menubar = wx.MenuBar()
        
        file_menu = wx.Menu()
        file_menu.Append(wx.ID_NEW, "&Nowy dokument\tCtrl+N")
        file_menu.Append(wx.ID_OPEN, "&Otwórz dokument...\tCtrl+O")
        file_menu.Append(wx.ID_SAVE, "&Zapisz plik\tCtrl+S")
        file_menu.Append(wx.ID_SAVEAS, "Zapisz jako...\tCtrl+Shift+S")
        file_menu.AppendSeparator()
        file_menu.Append(ID_SETTINGS, "Ustawienia programu...")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "&Zamknij TEdit")
        
        edit_menu = wx.Menu()
        edit_menu.Append(wx.ID_UNDO, "Cofnij...\tCtrl+Z")
        edit_menu.Append(wx.ID_SELECTALL, "Zaznacz wszystko...\tCtrl+A")
        edit_menu.Append(wx.ID_COPY, "Kopiuj...\tCtrl+C")
        edit_menu.Append(wx.ID_CUT, "Wytnij...\tCtrl+X")
        edit_menu.Append(wx.ID_PASTE, "Wklej...\tCtrl+V")
        edit_menu.AppendSeparator()
        edit_menu.Append(ID_FIND, "Znajdź...\tCtrl+F")
        edit_menu.Append(ID_REPLACE, "Zamień tekst...\tCtrl+H")

        insert_menu = wx.Menu()
        insert_menu.Append(ID_INSERT_DATETIME, "Wstaw datę i godzinę...")
        insert_menu.Append(ID_INSERT_UNICODE, "Wstaw znak Unicode...")

        help_menu = wx.Menu()
        help_menu.Append(wx.ID_ABOUT, "O Programie...")
        
        menubar.Append(file_menu, "&Plik")
        menubar.Append(edit_menu, "&Edycja")
        menubar.Append(insert_menu, "&Wstaw")
        menubar.Append(help_menu, "Pomoc")
        
        self.SetMenuBar(menubar)
    
    def OnNew(self, event):
        if self.text_ctrl.IsModified():
            if wx.MessageBox("Dokument został zmodyfikowany. Zapisać przed utworzeniem nowego?", "Potwierdzenie",
                             wx.ICON_QUESTION | wx.YES_NO, self) == wx.YES:
                self.OnSave(event)
        self.text_ctrl.Clear()
        self.current_file = None
        self.SetTitle("Edytor tekstowy TEdit")
    
    def OnOpen(self, event):
        if self.text_ctrl.IsModified():
            if wx.MessageBox("Dokument został zmodyfikowany. Zapisać przed otwarciem nowego?", "Potwierdzenie",
                             wx.ICON_QUESTION | wx.YES_NO, self) == wx.YES:
                self.OnSave(event)
        with wx.FileDialog(self, "Otwórz plik", wildcard="Pliki tekstowe (*.txt)|*.txt|Wszystkie pliki (*.*)|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            pathname = fileDialog.GetPath()
            self.LoadFile(pathname)
    
    def LoadFile(self, path):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as file:
                self.text_ctrl.SetValue(file.read())
            self.text_ctrl.SetModified(False)
            self.current_file = path
            self.SetTitle(f"{os.path.basename(path)} - TEdit")
        except IOError:
            wx.LogError(f"Nie można otworzyć pliku '{path}'")
    
    def OnSave(self, event):
        if self.current_file:
            self.SaveFile(self.current_file)
        else:
            self.OnSaveAs(event)
    
    def OnSaveAs(self, event):
        with wx.FileDialog(self, "Zapisz plik jako", wildcard="Pliki tekstowe (*.txt)|*.txt|Wszystkie pliki (*.*)|*.*",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            pathname = fileDialog.GetPath()
            self.SaveFile(pathname)
    
    def SaveFile(self, path):
        text = self.text_ctrl.GetValue()
        # Zastosuj symbol końca linii z ustawień
        line_ending = self.config['Tekst'].get('line_ending', 'windows')
        custom_le = self.config['Tekst'].get('custom_line_ending', '')
        if line_ending == 'windows':
            le = '\r\n'
        elif line_ending == 'MAC OS/linux/unix':
            le = '\n'
        elif line_ending == 'inny symbol...':
            le = custom_le if custom_le else '\n'
        else:
            le = '\n'

        # Konwersja linii
        text = re.sub(r'\r\n|\r|\n', le, text)

        try:
            with open(path, 'w', encoding='utf-8') as file:
                file.write(text)
            self.text_ctrl.SetModified(False)
            self.current_file = path
            self.SetTitle(f"{os.path.basename(path)} - TEdit")
        except IOError:
            wx.LogError(f"Nie można zapisać pliku '{path}'")

    def OnUndo(self, event):
        self.text_ctrl.Undo()
    
    def OnRedo(self, event):
        self.text_ctrl.Redo()
    
    def OnCut(self, event):
        self.text_ctrl.Cut()
    
    def OnCopy(self, event):
        self.text_ctrl.Copy()
    
    def OnPaste(self, event):
        self.text_ctrl.Paste()
    
    def OnSelectAll(self, event):
        self.text_ctrl.SelectAll()
    
    def OnAbout(self, event):
        wx.MessageBox("TEdit\nwersja 0.1\n\nTEdit jest edytorem tekstowym,\naplikacja jest jednym z podstawowych składników tSuite\n\nCopyright (c) 2024 TitoSoft", "O Programie", wx.OK | wx.ICON_INFORMATION)
    
    def OnClose(self, event):
        self.Close(True)
    
    def OnCloseWindow(self, event):
        if self.text_ctrl.IsModified():
            res = wx.MessageBox("Dokument został zmodyfikowany. Czy chcesz zapisać zmiany?", "Potwierdzenie",
                                wx.ICON_QUESTION | wx.YES_NO | wx.CANCEL, self)
            if res == wx.YES:
                self.OnSave(event)
            elif res == wx.CANCEL:
                event.Veto()
                return
        self.Destroy()

    def OnFind(self, event):
        dlg = FindDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            find_text = dlg.GetFindText()
            if find_text:
                content = self.text_ctrl.GetValue()
                start = self.text_ctrl.GetInsertionPoint()
                pos = content.find(find_text, start)
                if pos == -1:
                    # Szukaj od początku
                    pos = content.find(find_text, 0)
                if pos != -1:
                    self.text_ctrl.SetInsertionPoint(pos)
                    self.text_ctrl.SetSelection(pos, pos+len(find_text))
                else:
                    wx.MessageBox("Nie znaleziono szukanego tekstu.", "Informacja", wx.OK|wx.ICON_INFORMATION)
        dlg.Destroy()

    def OnReplace(self, event):
        dlg = ReplaceDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            find_text = dlg.GetFindText()
            replace_text = dlg.GetReplaceText()
            if find_text:
                content = self.text_ctrl.GetValue()
                new_content = content.replace(find_text, replace_text)
                if new_content != content:
                    self.text_ctrl.SetValue(new_content)
                else:
                    wx.MessageBox("Nie znaleziono tekstu do zamiany.", "Informacja", wx.OK|wx.ICON_INFORMATION)
        dlg.Destroy()

    def OnInsertDateTime(self, event):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.text_ctrl.WriteText(now)

    def OnInsertUnicode(self, event):
        dlg = UnicodeDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            uch = dlg.GetUnicodeChar()
            if uch:
                self.text_ctrl.WriteText(uch)
            else:
                wx.MessageBox("Nieprawidłowy kod Unicode.", "Błąd", wx.OK|wx.ICON_ERROR)
        dlg.Destroy()

    def OnSettings(self, event):
        dlg = SettingsDialog(self, self.ini_path)
        if dlg.ShowModal() == wx.ID_OK:
            # Ponownie wczytaj ustawienia i dostosuj timer
            self.LoadSettings()
            self.SetupAutoSave()
        dlg.Destroy()

    def OnAutoSave(self, event):
        if self.current_file and self.text_ctrl.IsModified():
            self.SaveFile(self.current_file)


if __name__ == "__main__":
    app = wx.App(False)
    frame = TextEditor(None)
    app.MainLoop()

import wx
import os
import sys
import datetime
import platform
import configparser
import re
from translation import _


# Dodaj importy dla pobierania
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("Biblioteka 'requests' nie jest zainstalowana. Automatyczne pobieranie słownika będzie niedostępne.")
    print("Aby zainstalować, użyj: pip install requests")

# Dodaj import dla enchant z obsługą braku biblioteki
try:
    import enchant
    # Spróbuj zaimportować backend Hunspell, aby móc dodać ścieżkę
    try:
        # W nowszych wersjach enchant, Hunspell jest bezpośrednio w enchant.backends
        # W starszych może być w enchant.checker.backends
        # Spróbujmy obydwu opcji
        from enchant.backends import Hunspell
        HUNSPELL_BACKEND_AVAILABLE = True
    except ImportError:
         HUNSPELL_BACKEND_AVAILABLE = False
         try:
             # Próba importu ze starszej ścieżki
             from enchant.checker.backends import Hunspell
             HUNSPELL_BACKEND_AVAILABLE = True
         except ImportError:
             HUNSPELL_BACKEND_AVAILABLE = False
             print("Backend Hunspell dla 'enchant' nie jest dostępny.")
             print("Może to uniemożliwić automatyczne znajdowanie słowników w niestandardowych ścieżkach.")


    ENCHANT_AVAILABLE = True
except ImportError:
    ENCHANT_AVAILABLE = False
    HUNSPELL_BACKEND_AVAILABLE = False
    print("Biblioteka 'enchant' nie jest zainstalowana. Sprawdzanie pisowni będzie wyłączone.")
    print("Aby zainstalować, użyj: pip install pyenchant")


# Identyfikatory dla nowych pozycji menu
ID_FIND = wx.NewIdRef()
ID_REPLACE = wx.NewIdRef()
ID_INSERT_DATETIME = wx.NewIdRef()
ID_INSERT_UNICODE = wx.NewIdRef()
ID_SETTINGS = wx.NewIdRef()
ID_SPELL_CHECK = wx.NewIdRef() # Nowy identyfikator dla sprawdzania pisowni

class FindDialog(wx.Dialog):
    def __init__(self, parent):
        super(FindDialog, self).__init__(parent, title=_("Znajdź"), size=(300, 150))
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        label_find = wx.StaticText(panel, label=_("Szukaj:"))
        hbox1.Add(label_find, flag=wx.ALL|wx.CENTER, border=5)
        self.text_find = wx.TextCtrl(panel)
        hbox1.Add(self.text_find, proportion=1, flag=wx.ALL|wx.EXPAND, border=5)
        vbox.Add(hbox1, flag=wx.EXPAND|wx.ALL, border=5)

        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        btn_find = wx.Button(panel, label=_("Znajdź dalej"))
        btn_find.Bind(wx.EVT_BUTTON, self.OnFind)
        hbox2.Add(btn_find, flag=wx.ALL, border=5)

        btn_cancel = wx.Button(panel, label=_("Anuluj"))
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
        super(ReplaceDialog, self).__init__(parent, title=_("Zamień tekst"), size=(300, 200))
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        label_find = wx.StaticText(panel, label=_("Szukaj:"))
        hbox1.Add(label_find, flag=wx.ALL|wx.CENTER, border=5)
        self.text_find = wx.TextCtrl(panel)
        hbox1.Add(self.text_find, proportion=1, flag=wx.ALL|wx.EXPAND, border=5)
        vbox.Add(hbox1, flag=wx.EXPAND|wx.ALL, border=5)

        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        label_replace = wx.StaticText(panel, label=_("Zamień na:"))
        hbox2.Add(label_replace, flag=wx.ALL|wx.CENTER, border=5)
        self.text_replace = wx.TextCtrl(panel)
        hbox2.Add(self.text_replace, proportion=1, flag=wx.ALL|wx.EXPAND, border=5)
        vbox.Add(hbox2, flag=wx.EXPAND|wx.ALL, border=5)

        hbox3 = wx.BoxSizer(wx.HORIZONTAL)
        btn_replace = wx.Button(panel, label=_("Zamień"))
        btn_replace.Bind(wx.EVT_BUTTON, self.OnReplace)
        hbox3.Add(btn_replace, flag=wx.ALL, border=5)

        btn_cancel = wx.Button(panel, label=_("Anuluj"))
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
        super(UnicodeDialog, self).__init__(parent, title=_("Wstaw znak Unicode"), size=(300, 150))
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(panel, label=_("Podaj kod punktu kodowego (np. U+00A9):"))
        vbox.Add(label, flag=wx.ALL, border=5)

        self.unicode_input = wx.TextCtrl(panel)
        vbox.Add(self.unicode_input, flag=wx.ALL|wx.EXPAND, border=5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(panel, label=_("OK"))
        btn_ok.Bind(wx.EVT_BUTTON, self.OnOK)
        hbox.Add(btn_ok, flag=wx.ALL, border=5)

        btn_cancel = wx.Button(panel, label=_("Anuluj"))
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
        # Spróbujmy parsować np. U+00A9 lub tylko hex 00A9
        val = val.replace("U+", "")
        try:
            code_point = int(val, 16)
            return chr(code_point)
        except ValueError:
            return ""


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, ini_path):
        super(SettingsDialog, self).__init__(parent, title=_("Ustawienia programu"), size=(400, 350)) # Zwiększono wysokość
        self.ini_path = ini_path
        self.config = configparser.ConfigParser()

        if os.path.exists(self.ini_path):
            try:
                 self.config.read(self.ini_path, encoding='utf-8')
            except configparser.Error as e:
                 wx.LogError(f"Błąd podczas czytania pliku ustawień: {e}")
                 self.config = configparser.ConfigParser() # Zainicjuj od nowa w przypadku błędu
                 self.config['Ogólne'] = {}
                 self.config['Tekst'] = {}

        # Upewnij się, że sekcje istnieją przed dostępem i ustaw domyślne
        if 'Ogólne' not in self.config: self.config['Ogólne'] = {}
        if 'Tekst' not in self.config: self.config['Tekst'] = {}

        # Domyślne wartości
        self.config['Ogólne'].setdefault('auto_save', 'wyłączone')
        self.config['Tekst'].setdefault('line_ending', 'windows')
        self.config['Tekst'].setdefault('custom_line_ending', '')
        # Domyślna wartość dla sprawdzania pisowni (domyślnie wyłączone jeśli enchant niedostępny)
        self.config['Ogólne'].setdefault('spell_check_enabled', 'false')


        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        notebook = wx.Notebook(panel);

        # -------- Zakładka Ogólne --------
        ogolne_panel = wx.Panel(notebook)
        ogolne_sizer = wx.BoxSizer(wx.VERTICAL)

        # Ustawienia Autozapisu
        autosave_box = wx.StaticBoxSizer(wx.StaticBox(ogolne_panel, label=_("Automatyczny zapis")), wx.VERTICAL)
        autosave_label = wx.StaticText(ogolne_panel, label=_("Zapis co:"))
        autosave_box.Add(autosave_label, flag=wx.LEFT|wx.TOP|wx.RIGHT, border=5)

        self.autosave_choices_map = {'5 minut': _("5 minut"), '10 minut': _("10 minut"), 'wyłączone': _("wyłączone")}
        self.autosave_choices = list(self.autosave_choices_map.keys())
        self.autosave_choice = wx.Choice(ogolne_panel, choices=list(self.autosave_choices_map.values()))
        current_auto = self.config['Ogólne'].get('auto_save', 'wyłączone')
        if current_auto in self.autosave_choices:
            self.autosave_choice.SetSelection(self.autosave_choices.index(current_auto))
        else:
            self.autosave_choice.SetSelection(self.autosave_choices.index('wyłączone')) # Domyślnie wybierz "wyłączone"
        autosave_box.Add(self.autosave_choice, flag=wx.ALL|wx.EXPAND, border=5)
        ogolne_sizer.Add(autosave_box, flag=wx.EXPAND|wx.ALL, border=5)

        # Ustawienia Sprawdzania Pisowni
        spell_check_box = wx.StaticBoxSizer(wx.StaticBox(ogolne_panel, label=_("Sprawdzanie pisowni")), wx.VERTICAL)
        if ENCHANT_AVAILABLE:
            self.spell_check_checkbox = wx.CheckBox(ogolne_panel, label=_("Włącz sprawdzanie pisowni (wymaga słownika)"))
            current_spell = self.config['Ogólne'].getboolean('spell_check_enabled', False) # Read boolean
            self.spell_check_checkbox.SetValue(current_spell)
            spell_check_box.Add(self.spell_check_checkbox, flag=wx.ALL|wx.EXPAND, border=5)

            # Informacja o słowniku
            spell_info_label = wx.StaticText(ogolne_panel, label=_("Program spróbuje pobrać słownik pl_PL do podkatalogu data/dicts\njeśli nie będzie dostępny systemowo."))
            spell_check_box.Add(spell_info_label, flag=wx.ALL|wx.EXPAND, border=5)

        else:
             no_enchant_label = wx.StaticText(ogolne_panel, label=_("Biblioteka 'enchant' jest niedostępna.\nFunkcja sprawdzania pisowni jest wyłączona."))
             spell_check_box.Add(no_enchant_label, flag=wx.ALL|wx.EXPAND, border=5)


        ogolne_sizer.Add(spell_check_box, flag=wx.EXPAND|wx.ALL, border=5)


        ogolne_panel.SetSizer(ogolne_sizer)

        # -------- Zakładka Tekst --------
        tekst_panel = wx.Panel(notebook)
        tekst_sizer = wx.BoxSizer(wx.VERTICAL)

        # Ustawienia Znaków Końca Linii
        line_ending_box = wx.StaticBoxSizer(wx.StaticBox(tekst_panel, label=_("Znaki końca linii")), wx.VERTICAL)
        line_ending_label = wx.StaticText(tekst_panel, label=_("Symbol końca linii:"))
        line_ending_box.Add(line_ending_label, flag=wx.LEFT|wx.TOP|wx.RIGHT, border=5)

        self.line_ending_choices_map = {"windows": _("windows"), "MAC OS/linux/unix": _("MAC OS/linux/unix"), "inny symbol...": _("inny symbol...")}
        self.line_ending_choices = list(self.line_ending_choices_map.keys())
        self.line_ending_choice = wx.Choice(tekst_panel, choices=list(self.line_ending_choices_map.values()))
        current_le = self.config['Tekst'].get('line_ending', 'windows')
        if current_le in self.line_ending_choices:
            self.line_ending_choice.SetSelection(self.line_ending_choices.index(current_le))
        else:
            # Jeśli brak w standardowych, to inny symbol
            self.line_ending_choice.SetSelection(self.line_ending_choices.index("inny symbol..."))

        line_ending_box.Add(self.line_ending_choice, flag=wx.ALL|wx.EXPAND, border=5)

        self.custom_line_ending_label = wx.StaticText(tekst_panel, label=_("Napisz symbol końca linii:"))
        self.custom_line_ending_text = wx.TextCtrl(tekst_panel)
        self.custom_line_ending_text.SetValue(self.config['Tekst'].get('custom_line_ending', ''))

        # Pokazuj/ukrywaj pole w zależności od wyboru
        if self.line_ending_choices[self.line_ending_choice.GetSelection()] == "inny symbol...":
             self.custom_line_ending_label.Show(True)
             self.custom_line_ending_text.Show(True)
        else:
             self.custom_line_ending_label.Show(False)
             self.custom_line_ending_text.Show(False)


        line_ending_box.Add(self.custom_line_ending_label, flag=wx.LEFT|wx.TOP|wx.RIGHT, border=5)
        line_ending_box.Add(self.custom_line_ending_text, flag=wx.ALL|wx.EXPAND, border=5)

        self.line_ending_choice.Bind(wx.EVT_CHOICE, self.OnLineEndingChoice)
        tekst_sizer.Add(line_ending_box, flag=wx.EXPAND|wx.ALL, border=5)


        tekst_panel.SetSizer(tekst_sizer)

        notebook.AddPage(ogolne_panel, _("Ogólne"))
        notebook.AddPage(tekst_panel, _("Tekst"))

        main_sizer.Add(notebook, proportion=1, flag=wx.ALL|wx.EXPAND, border=5)

        # Przyciski OK/Anuluj
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(panel, label=_("OK"))
        btn_cancel = wx.Button(panel, label=_("Anuluj"))
        btn_ok.Bind(wx.EVT_BUTTON, self.OnOK)
        btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
        btn_sizer.Add(btn_ok, flag=wx.ALL, border=5)
        btn_sizer.Add(btn_cancel, flag=wx.ALL, border=5)

        main_sizer.Add(btn_sizer, flag=wx.ALIGN_RIGHT|wx.ALL, border=5)

        panel.SetSizer(main_sizer)
        self.Layout() # Przelicz layout po ukryciu/pokazaniu pól

    def OnLineEndingChoice(self, event):
        choice = self.line_ending_choices[self.line_ending_choice.GetSelection()]
        if choice == "inny symbol...":
            self.custom_line_ending_label.Show(True)
            self.custom_line_ending_text.Show(True)
        else:
            self.custom_line_ending_label.Show(False)
            self.custom_line_ending_text.Show(False)
        self.Layout() # Przelicz layout po ukryciu/pokazaniu pól

    def OnOK(self, event):
        # Zapisz ustawienia
        auto_val = self.autosave_choices[self.autosave_choice.GetSelection()]
        self.config['Ogólne']['auto_save'] = auto_val

        # Zapisz stan sprawdzania pisowni
        if ENCHANT_AVAILABLE:
             self.config['Ogólne']['spell_check_enabled'] = str(self.spell_check_checkbox.GetValue()).lower()

        line_ending_val = self.line_ending_choices[self.line_ending_choice.GetSelection()]
        self.config['Tekst']['line_ending'] = line_ending_val
        if line_ending_val == 'inny symbol...':
            self.config['Tekst']['custom_line_ending'] = self.custom_line_ending_text.GetValue()
        else:
            self.config['Tekst']['custom_line_ending'] = ''

        # Zapis do pliku
        os.makedirs(os.path.dirname(self.ini_path), exist_ok=True)
        try:
            with open(self.ini_path, 'w', encoding='utf-8') as f:
                self.config.write(f)
        except IOError as e:
             wx.LogError(f"Nie można zapisać pliku ustawień: {e}")

        self.EndModal(wx.ID_OK)

    def OnCancel(self, event):
        self.EndModal(wx.ID_CANCEL)


class TextEditor(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(TextEditor, self).__init__(*args, **kwargs)

        self.current_file = None
        self.config = configparser.ConfigParser()

        # Ścieżka do katalogu aplikacji
        if getattr(sys, 'frozen', False):
            # Jesteśmy w spakowanej aplikacji (np. PyInstaller)
            app_dir = os.path.dirname(sys.executable)
        else:
            # Jesteśmy w zwykłym skrypcie Python
            app_dir = os.path.dirname(os.path.abspath(__file__))

        # Ścieżka do pliku ustawień w zależności od systemu
        if platform.system().lower().startswith('win'):
            appdata = os.environ.get('APPDATA', os.path.expanduser("~"))
            config_dir = os.path.join(appdata, "Titosoft", "Titan", "appsettings")
        else:
            config_dir = os.path.join(os.path.expanduser("~"), ".config", "titosoft", "titan", "tedit")
        self.ini_path = os.path.join(config_dir, "tedit.ini")

        # Ścieżka do katalogu na słowniki w ramach aplikacji
        self.app_dict_dir = os.path.join(app_dir, "data", "dicts")
        # URL do plików słownika sjp-pl na GitHubie
        self.dic_url = "https://raw.githubusercontent.com/sjp-pl/polski-slownik-ortograficzny/master/sjp-pl.dic"
        self.aff_url = "https://raw.githubusercontent.com/sjp-pl/polski-slownik-ortograficzny/master/sjp-pl.aff"
        self.expected_dic_name = "pl_PL.dic"
        self.expected_aff_name = "pl_PL.aff"


        # Sprawdzanie pisowni
        self.spell_check_enabled = False
        self.spell_dict = None
        self.using_underline_highlight = False # Flaga informująca o używanym sposobie podkreślenia (domyślnie tło)

        # Styl dla wyróżniania błędów pisowni (domyślnie jasno-czerwone tło)
        self.spell_error_style = wx.TextAttr()
        self.spell_error_style.SetBackgroundColour(wx.Colour(255, 230, 230)) # Jasno-czerwone tło

        # Spróbujmy ustawić flagę dla tła - może działać nawet jeśli underline nie działa
        try:
             self.spell_error_style.SetFlags(wx.TEXT_ATTR_BACKGROUND_COLOUR)
        except AttributeError:
             print("Flaga koloru tła (TEXT_ATTR_BACKGROUND_COLOUR) niedostępna.")
             # Flagi pozostaną 0, co może oznaczać brak zastosowania stylu tła w starszych wersjach
             # Ale mimo wszystko próbujemy, bo w niektórych wersjach samo SetBackgroundColour może wystarczyć z TE_RICH2.


        # Próbujemy ustawić zaawansowany styl podkreślenia i ustawić flagę
        underline_style_attr = wx.TextAttr()
        try:
            # Sprawdź czy stałe potrzebne do podkreślenia istnieją
            wx.TEXT_ATTR_UNDERLINE_TYPE
            wx.TEXT_CTRL_UNDERLINE_RED_WAVY

            underline_style_attr.SetFlags(wx.TEXT_ATTR_UNDERLINE_TYPE)
            underline_style_attr.SetUnderlineStyle(wx.TEXT_CTRL_UNDERLINE_RED_WAVY)
            underline_style_attr.SetUnderlineColour(wx.RED)

            # Jeśli powyższe się powiodło, nadpisujemy domyślny styl tła stylem podkreślenia
            self.spell_error_style = underline_style_attr
            self.using_underline_highlight = True # Udało się ustawić podkreślenie
            print("Użyto wyróżnienia: czerwona falista linia.")

        except AttributeError:
            print("Zaawansowane style podkreślenia (TEXT_ATTR_UNDERLINE_TYPE, TEXT_CTRL_UNDERLINE_RED_WAVY) są niedostępne.")
            print("Użyto wyróżnienia: jasno-czerwone tło.")
            # using_underline_highlight jest już False


        self.LoadSettings() # Wczytaj ustawienia, w tym spell_check_enabled i spróbuj zainicjować słownik

        # Ustawienie tytułu
        self.SetTitle(_("Edytor tekstowy TEdit"))

        # Tworzenie panelu i pola tekstowego
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(panel, label=_("Treść dokumentu:"))
        vbox.Add(label, flag=wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, border=10)

        # Dodaj styl wx.TE_RICH lub wx.TE_RICH2 dla kolorowania tekstu/podkreślania
        self.text_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_RICH2) # Używamy TE_RICH2
        vbox.Add(self.text_ctrl, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        panel.SetSizer(vbox)

        # Tworzenie menu
        self.CreateMenuBar()

        # Ustawienie skrótów klawiaturowych i powiązań zdarzeń
        self.Bind(wx.EVT_MENU, self.OnNew, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.OnOpen, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self.OnSave, id=wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self.OnSaveAs, id=wx.ID_SAVEAS)
        self.Bind(wx.EVT_MENU, self.OnClose, id=wx.ID_EXIT)

        self.Bind(wx.EVT_MENU, self.OnUndo, id=wx.ID_UNDO)
        # edit_menu.Append(wx.ID_REDO, "Ponów...\tCtrl+Y") # Ponów może nie działać natywnie z TE_RICH2
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

        # Powiązanie dla sprawdzania pisowni
        self.Bind(wx.EVT_MENU, self.OnCheckSpelling, id=ID_SPELL_CHECK)

        self.Bind(wx.EVT_CLOSE, self.OnCloseWindow)

        # Opcjonalnie: sprawdzanie pisowni podczas pisania (wymaga optymalizacji)
        # self.text_ctrl.Bind(wx.EVT_TEXT, self.OnTextChange)



        # Timer do automatycznego zapisu
        self.auto_save_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnAutoSave, self.auto_save_timer)
        self.SetupAutoSave() # Uruchom timer zgodnie z ustawieniami

        # Otwieranie pliku przekazanego jako argument przy uruchomieniu
        if len(sys.argv) > 1:
            wx.CallAfter(self.LoadFile, sys.argv[1])

    def DownloadDictionary(self):
        """Pobiera pliki słownika pl_PL.dic i pl_PL.aff do lokalnego katalogu."""
        if not REQUESTS_AVAILABLE:
            # Komunikat o braku requests jest już wyświetlany przy starcie
            return False

        print(f"Próba pobrania słownika do: {self.app_dict_dir}")
        os.makedirs(self.app_dict_dir, exist_ok=True)

        dic_path = os.path.join(self.app_dict_dir, self.expected_dic_name)
        aff_path = os.path.join(self.app_dict_dir, self.expected_aff_name)

        # Sprawdź, czy pliki już istnieją
        if os.path.exists(dic_path) and os.path.exists(aff_path):
            print("Pliki słownika już istnieją w lokalnym katalogu.")
            return True # Słownik jest dostępny lokalnie

        try:
            print(f"Pobieranie {self.dic_url} -> {dic_path}")
            # Używamy timeoutu na wypadek problemów z siecią
            response_dic = requests.get(self.dic_url, stream=True, timeout=10)
            response_dic.raise_for_status() # Sprawdź błędy HTTP

            with open(dic_path, 'wb') as f:
                for chunk in response_dic.iter_content(chunk_size=8192):
                    f.write(chunk)

            print(f"Pobieranie {self.aff_url} -> {aff_path}")
            response_aff = requests.get(self.aff_url, stream=True, timeout=10)
            response_aff.raise_for_status() # Sprawdź błędy HTTP

            with open(aff_path, 'wb') as f:
                for chunk in response_aff.iter_content(chunk_size=8192):
                    f.write(chunk)

            print("Pobrano i zapisano pliki słownika.")
            return True

        except requests.exceptions.RequestException as e:
            wx.MessageBox(_("Błąd podczas pobierania słownika:\n{e}").format(e=e), _("Błąd pobierania"), wx.OK|wx.ICON_ERROR)
            print(f"Błąd podczas pobierania słownika: {e}")
            # Usuń niekompletne pliki, jeśli istnieją
            if os.path.exists(dic_path):
                 try: os.remove(dic_path)
                 except OSError: pass # Ignoruj błędy usuwania
            if os.path.exists(aff_path):
                 try: os.remove(aff_path)
                 except OSError: pass # Ignoruj błędy usuwania
            return False
        except IOError as e:
             wx.MessageBox(_("Błąd zapisu plików słownika:\n{e}").format(e=e), _("Błąd zapisu"), wx.OK|wx.ICON_ERROR)
             print(f"Błąd zapisu plików słownika: {e}")
             # Usuń niekompletne pliki po błędzie zapisu
             if os.path.exists(dic_path):
                 try: os.remove(dic_path)
                 except OSError: pass
             if os.path.exists(aff_path):
                 try: os.remove(aff_path)
                 except OSError: pass
             return False
        except Exception as e:
             wx.MessageBox(_("Nieoczekiwany błąd podczas pobierania:\n{e}").format(e=e), _("Błąd pobierania"), wx.OK|wx.ICON_ERROR)
             print(f"Nieoczekiwany błąd podczas pobierania: {e}")
             return False


    def LoadSettings(self):
        """Wczytuje ustawienia z pliku INI i inicjuje słownik."""
        if os.path.exists(self.ini_path):
            try:
                 self.config.read(self.ini_path, encoding='utf-8')
            except configparser.Error as e:
                 wx.LogError(f"Błąd podczas czytania pliku ustawień: {e}")
                 # Zainicjuj domyślne, jeśli wystąpił błąd
                 self.config = configparser.ConfigParser()
                 self.config['Ogólne'] = {}
                 self.config['Tekst'] = {}
        else:
            self.config['Ogólne'] = {}
            self.config['Tekst'] = {}

        # Ustawienia domyślne, jeśli brakuje ich w pliku
        if 'Ogólne' not in self.config: self.config['Ogólne'] = {}
        if 'Tekst' not in self.config: self.config['Tekst'] = {}
        self.config['Ogólne'].setdefault('spell_check_enabled', 'false')


        self.spell_check_enabled = self.config['Ogólne'].getboolean('spell_check_enabled', False)
        self.spell_dict = None # Resetuj słownik przed próbą inicjalizacji

        # Zainicjuj słownik tylko jeśli sprawdzanie pisowni jest włączone i enchant dostępny
        if self.spell_check_enabled and ENCHANT_AVAILABLE:
            # 1. Spróbuj pobrać słownik lokalnie, jeśli nie ma
            # Nie musimy sprawdzać wyniku, po prostu próbujemy
            self.DownloadDictionary()

            # 2. Dodaj lokalny katalog słowników do ścieżki enchant (jeśli backend Hunspell dostępny i katalog istnieje)
            if HUNSPELL_BACKEND_AVAILABLE and os.path.exists(self.app_dict_dir):
                 try:
                     # Dodaj katalog do ścieżki wyszukiwania Hunspell
                     # Sprawdź, czy ścieżka nie została już dodana (aby uniknąć duplikatów)
                     current_paths = [os.path.normpath(p) for p in Hunspell.get_dictionary_paths()]
                     norm_app_dict_dir = os.path.normpath(self.app_dict_dir)

                     if norm_app_dict_dir not in current_paths:
                         Hunspell.add_dictionary_path(self.app_dict_dir)
                         print(f"Dodano ścieżkę słownika do Hunspell: {self.app_dict_dir}")
                     # else:
                         # print(f"Ścieżka słownika {self.app_dict_dir} już dodana do Hunspell.")

                 except Exception as e:
                      print(f"Błąd podczas dodawania ścieżki słownika do Hunspell: {e}")
                      # Nie przerywamy, bo może słownik jest gdzie indziej systemowo

            # 3. Sprawdź, czy słownik "pl_PL" jest teraz dostępny (systemowo lub z dodanej ścieżki)
            # Używamy wx.BusyCursor, bo ładowanie słownika może chwilę potrwać
            with wx.BusyCursor():
                try:
                    if enchant.dict_exists("pl_PL"):
                         self.spell_dict = enchant.Dict("pl_PL")
                         print("Użyto słownika pl_PL.")
                    else:
                         print("Słownik pl_PL niedostępny systemowo ani w lokalnym katalogu.")
                         if enchant.dict_exists("en_US"):
                              self.spell_dict = enchant.Dict("en_US")
                              print("Użyto słownika en_US jako alternatywy.")
                              wx.MessageBox(_("Słownik języka polskiego (pl_PL) jest niedostępny.\nUżyto słownika angielskiego (en_US)."),
                                            _("Informacja o słowniku"), wx.OK|wx.ICON_INFORMATION)
                         else:
                              print("Słowniki pl_PL i en_US niedostępne. Sprawdzanie pisowni zostanie wyłączone.")
                              self.spell_check_enabled = False # Wyłącz jeśli brak słownika głównego i alternatywnego
                              wx.MessageBox(_("Brak dostępnych słowników (pl_PL, en_US). Sprawdzanie pisowni zostanie wyłączone."),
                                            _("Brak słownika"), wx.OK|wx.ICON_WARNING)

                except enchant.errors.DictNotFoundError as e:
                    # Ten błąd powinien być złapany przez dict_exists, ale na wszelki wypadek
                    print(f"Błąd inicjalizacji słownika (DictNotFoundError): {e}")
                    self.spell_check_enabled = False
                except Exception as e:
                     print(f"Nieoczekiwany błąd przy inicjalizacji słownika: {e}")
                     self.spell_check_enabled = False
                     wx.MessageBox(_("Wystąpił błąd podczas inicjalizacji słownika:\n{e}\nSprawdzanie pisowni zostanie wyłączone.").format(e=e),
                                   _("Błąd słownika"), wx.OK|wx.ICON_ERROR)


        # Jeśli spell_check_enabled został wyłączony z powodu błędu (brak enchant, brak słownika),
        # upewnij się, że jest to odzwierciedlone w konfiguracji, aby dialog ustawień pokazywał poprawny stan.
        # Nie jest to krytyczne, bo dialog i tak wczyta ustawienie przy otwarciu,
        # ale zapewnia natychmiastową spójność.
        self.config['Ogólne']['spell_check_enabled'] = str(self.spell_check_enabled).lower()


    def SetupAutoSave(self):
        """Konfiguruje i uruchamia timer autozapisu."""
        auto_val = self.config['Ogólne'].get('auto_save', 'wyłączone')
        interval = 0
        if auto_val == "5 minut":
            interval = 5 * 60 * 1000
        elif auto_val == "10 minut":
            interval = 10 * 60 * 1000

        if interval > 0:
            if not self.auto_save_timer.IsRunning():
                 self.auto_save_timer.Start(interval)
                 print(f"Autozapis włączony: co {auto_val}")
        else:
            if self.auto_save_timer.IsRunning():
                 self.auto_save_timer.Stop()
                 print("Autozapis wyłączony.")

    def CreateMenuBar(self):
        """Tworzy pasek menu aplikacji."""
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        file_menu.Append(wx.ID_NEW, _("&Nowy dokument\tCtrl+N"))
        file_menu.Append(wx.ID_OPEN, _("&Otwórz dokument...\tCtrl+O"))
        file_menu.Append(wx.ID_SAVE, _("&Zapisz plik\tCtrl+S"))
        file_menu.Append(wx.ID_SAVEAS, _("Zapisz jako...\tCtrl+Shift+S"))
        file_menu.AppendSeparator()
        file_menu.Append(ID_SETTINGS, _("Ustawienia programu..."))
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, _("&Zamknij TEdit"))

        edit_menu = wx.Menu()
        edit_menu.Append(wx.ID_UNDO, _("Cofnij...\tCtrl+Z"))
        # edit_menu.Append(wx.ID_REDO, "Ponów...\tCtrl+Y") # Ponów może nie działać natywnie z TE_RICH2
        edit_menu.AppendSeparator() # Dodaj separator przed standardowymi operacjami
        edit_menu.Append(wx.ID_CUT, _("Wytnij...\tCtrl+X"))
        edit_menu.Append(wx.ID_COPY, _("Kopiuj...\tCtrl+C"))
        edit_menu.Append(wx.ID_PASTE, _("Wklej...\tCtrl+V"))
        edit_menu.AppendSeparator() # Dodaj separator przed zaznacz wszystko
        edit_menu.Append(wx.ID_SELECTALL, _("Zaznacz wszystko...\tCtrl+A"))
        edit_menu.AppendSeparator() # Dodaj separator przed znajdź/zamień
        edit_menu.Append(ID_FIND, _("Znajdź...\tCtrl+F"))
        edit_menu.Append(ID_REPLACE, _("Zamień tekst...\tCtrl+H"))

        # Dodaj opcję sprawdzania pisowni
        # Pokaż opcję w menu tylko jeśli enchant jest w ogóle dostępny
        if ENCHANT_AVAILABLE:
             edit_menu.AppendSeparator()
             # Stan włączenia/wyłączenia funkcji sprawdzania pisowni będzie zarządzany w ustawieniach
             menu_item_spell = edit_menu.Append(ID_SPELL_CHECK, _("Sprawdź pisownię"))
             # Opcjonalnie: wyłącz pozycję menu, jeśli funkcja jest wyłączona w ustawieniach LUB słownik nie został załadowany
             # menu_item_spell.Enable(self.spell_check_enabled and self.spell_dict is not None)


        insert_menu = wx.Menu()
        insert_menu.Append(ID_INSERT_DATETIME, _("Wstaw datę i godzinę..."))
        insert_menu.Append(ID_INSERT_UNICODE, _("Wstaw znak Unicode..."))

        help_menu = wx.Menu()
        help_menu.Append(wx.ID_ABOUT, _("O Programie..."))

        menubar.Append(file_menu, _("&Plik"))
        menubar.Append(edit_menu, _("&Edycja"))
        menubar.Append(insert_menu, _("&Wstaw"))
        menubar.Append(help_menu, _("Pomoc"))

        self.SetMenuBar(menubar)
        self.Layout() # Odśwież layout okna, może być potrzebne po zmianie menu bar


    def OnNew(self, event):
        """Tworzy nowy, pusty dokument."""
        if self.text_ctrl.IsModified():
            res = wx.MessageBox(_("Dokument został zmodyfikowany. Zapisać przed utworzeniem nowego?"), _("Potwierdzenie"),
                                 wx.ICON_QUESTION | wx.YES_NO | wx.CANCEL, self)
            if res == wx.YES:
                if not self.OnSave(event): # Jeśli zapis się nie udał, przerwij tworzenie nowego
                    return
            elif res == wx.CANCEL:
                return # Anuluj tworzenie nowego dokumentu

        self.text_ctrl.Clear()
        self.current_file = None
        self.SetTitle(_("Edytor tekstowy TEdit"))
        self.text_ctrl.SetModified(False) # Upewnij się, że flaga modyfikacji jest czysta
        self.ClearSpellCheckHighlights() # Wyczyść ewentualne stare podkreślenia


    def OnOpen(self, event):
        """Otwiera istniejący plik tekstowy."""
        if self.text_ctrl.IsModified():
            res = wx.MessageBox(_("Dokument został zmodyfikowany. Zapisać przed otwarciem nowego?"), _("Potwierdzenie"),
                                 wx.ICON_QUESTION | wx.YES_NO | wx.CANCEL, self)
            if res == wx.YES:
                 if not self.OnSave(event):
                     return
            elif res == wx.CANCEL:
                 return

        with wx.FileDialog(self, _("Otwórz plik"), wildcard=_("Pliki tekstowe (*.txt)|*.txt|Wszystkie pliki (*.*)|*.*"),
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            pathname = fileDialog.GetPath()
            self.LoadFile(pathname)

    def LoadFile(self, path):
        """Wczytuje zawartość pliku do edytora."""
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as file:
                content = file.read()
                self.text_ctrl.SetValue(content)
            self.text_ctrl.SetModified(False)
            self.current_file = path
            self.SetTitle(f"{os.path.basename(path)} - TEdit")
            self.ClearSpellCheckHighlights() # Wyczyść stare podkreślenia po wczytaniu nowego pliku

            # Opcjonalnie: Wykonaj automatyczne sprawdzanie pisowni po otwarciu
            # if self.spell_check_enabled and self.spell_dict:
            #    self.OnCheckSpelling(None) # Wywołaj sprawdzanie pisowni

        except IOError as e:
            wx.LogError(_("Nie można otworzyć pliku '{path}': {e}").format(path=path, e=e))
            self.current_file = None # Resetuj current_file w przypadku błędu


    def OnSave(self, event):
        """Zapisuje aktualny dokument."""
        if self.current_file:
            return self.SaveFile(self.current_file) # Zwróć True/False z SaveFile
        else:
            return self.OnSaveAs(event) # OnSaveAs zwróci True/False

    def OnSaveAs(self, event):
        """Zapisuje dokument pod nową nazwą."""
        with wx.FileDialog(self, _("Zapisz plik jako"), wildcard=_("Pliki tekstowe (*.txt)|*.txt|Wszystkie pliki (*.*)|*.*"),
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return False # Użytkownik anulował

            pathname = fileDialog.GetPath()
            return self.SaveFile(pathname) # Zwróć True/False z SaveFile

    def SaveFile(self, path):
        """Zapisuje zawartość edytora do podanego pliku."""
        text = self.text_ctrl.GetValue()
        # Zastosuj symbol końca linii z ustawień
        line_ending = self.config['Tekst'].get('line_ending', 'windows')
        custom_le = self.config['Tekst'].get('custom_line_ending', '')
        if line_ending == 'windows':
            le = '\r\n'
        elif line_ending == 'MAC OS/linux/unix':
            le = '\n'
        elif line_ending == 'inny symbol...':
            le = custom_le if custom_le else '\n' # Użyj domyślnego '\n' jeśli custom jest pusty
        else:
            le = '\n' # Domyślny na wszelki wypadek

        # Zamień istniejące standardowe końce linii na wybrany symbol
        # Używamy re.sub aby obsłużyć różne istniejące formaty (\r\n, \r, \n)
        text_to_save = re.sub(r'\r\n|\r|\n', le, text)

        try:
            with open(path, 'w', encoding='utf-8') as file:
                file.write(text_to_save)
            self.text_ctrl.SetModified(False)
            self.current_file = path
            self.SetTitle(f"{os.path.basename(path)} - TEdit")
            return True # Zapisano pomyślnie
        except IOError as e:
            wx.LogError(_("Nie można zapisać pliku '{path}': {e}").format(path=path, e=e))
            return False # Błąd zapisu

    def OnUndo(self, event):
        """Cofa ostatnią operację."""
        self.text_ctrl.Undo()

    # def OnRedo(self, event):
    #     """Ponawia cofniętą operację."""
    #     # TE_RICH2 może nie wspierać Redo natywnie lub wymaga innego sposobu
    #     # self.text_ctrl.Redo()
    #     pass # Wykomentowane/zastąpione, jeśli nie działa

    def OnCut(self, event):
        """Wykonuje operację Wytnij."""
        self.text_ctrl.Cut()

    def OnCopy(self, event):
        """Wykonuje operację Kopiuj."""
        self.text_ctrl.Copy()

    def OnPaste(self, event):
        """Wykonuje operację Wklej."""
        self.text_ctrl.Paste()

    def OnSelectAll(self, event):
        """Zaznacza cały tekst w edytorze."""
        self.text_ctrl.SelectAll()

    def OnAbout(self, event):
        """Wyświetla okno "O programie"."""
        info = wx.AboutDialogInfo()
        info.SetName("TEdit")
        info.SetVersion("0.1")
        info.SetDescription(_("TEdit jest edytorem tekstowym,\naplikacja jest jednym z podstawowych składników tSuite."))
        info.SetCopyright("(c) 2024 TitoSoft")
        info.AddDeveloper("Twoje Imię/Nazwa (opcjonalnie)") # Możesz dodać swoje imię/nazwę
        info.SetLicence(_("Licencja (np. MIT, GPL - opcjonalnie)")) # Dodaj informację o licencji, jeśli jest
        # info.SetWebSite("Twoja strona (opcjonalnie)") # Dodaj stronę projektu
        # info.SetIcon(wx.Icon("ikonka.png", wx.BITMAP_TYPE_PNG)) # Opcjonalnie: ustaw ikonkę

        wx.AboutBox(info)

    def OnClose(self, event):
        """Zamyka aplikację."""
        self.Close(True)

    def OnCloseWindow(self, event):
        """Obsługa zamknięcia okna (pytanie o zapis)."""
        if self.text_ctrl.IsModified():
            res = wx.MessageBox(_("Dokument został zmodyfikowany. Czy chcesz zapisać zmiany?"), _("Potwierdzenie"),
                                 wx.ICON_QUESTION | wx.YES_NO | wx.CANCEL, self)
            if res == wx.YES:
                if not self.OnSave(event):
                    event.Veto() # Przerwij zamykanie, jeśli zapis się nie udał
                    return
            elif res == wx.CANCEL:
                event.Veto() # Przerwij zamykanie
                return
        self.Destroy() # Zamknij okno po pomyślnym zapisie lub rezygnacji/braku zmian


    def OnFind(self, event):
        """Otwiera dialog Znajdź."""
        dlg = FindDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            find_text = dlg.GetFindText()
            if find_text:
                content = self.text_ctrl.GetValue()
                start = self.text_ctrl.GetInsertionPoint() # Szukaj od aktualnej pozycji kursora
                # Znajdź pierwsze wystąpienie od aktualnej pozycji
                pos = content.find(find_text, start)
                if pos == -1:
                    # Jeśli nie znaleziono od kursora, szukaj od początku
                    pos = content.find(find_text, 0)
                if pos != -1:
                    # Znaleziono, zaznacz tekst i przesuń kursor
                    self.text_ctrl.SetInsertionPoint(pos)
                    self.text_ctrl.SetSelection(pos, pos+len(find_text))
                    # Przewiń do zaznaczenia (opcjonalnie, wymagałoby dodatkowej logiki przewijania)
                    # self.text_ctrl.ShowPosition(pos)
                else:
                    wx.MessageBox(_("Nie znaleziono szukanego tekstu."), _("Informacja"), wx.OK|wx.ICON_INFORMATION)
        dlg.Destroy()

    def OnReplace(self, event):
        """Otwiera dialog Zamień."""
        dlg = ReplaceDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            find_text = dlg.GetFindText()
            replace_text = dlg.GetReplaceText()
            if find_text:
                # Zastąpienie wszystkich wystąpień - proste rozwiązanie
                # Bardziej zaawansowane wymagałoby iteracji i opcji "Zamień następne", "Zamień wszystko"
                content = self.text_ctrl.GetValue()
                new_content = content.replace(find_text, replace_text)
                if new_content != content:
                    self.text_ctrl.SetValue(new_content)
                    self.text_ctrl.SetModified(True) # Oznacz jako zmodyfikowany
                else:
                    wx.MessageBox(_("Nie znaleziono tekstu do zamiany."), _("Informacja"), wx.OK|wx.ICON_INFORMATION)
        dlg.Destroy()

    def OnInsertDateTime(self, event):
        """Wstawia aktualną datę i godzinę w miejscu kursora."""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.text_ctrl.WriteText(now)

    def OnInsertUnicode(self, event):
        """Wstawia znak Unicode na podstawie podanego kodu."""
        dlg = UnicodeDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            uch = dlg.GetUnicodeChar()
            if uch:
                self.text_ctrl.WriteText(uch)
            else:
                wx.MessageBox(_("Nieprawidłowy kod Unicode. Użyj formatu Hex (np. 00A9) lub U+Hex (np. U+00A9)."),
                              _("Błąd"), wx.OK|wx.ICON_ERROR)
        dlg.Destroy()

    def OnSettings(self, event):
        """Otwiera dialog ustawień programu."""
        dlg = SettingsDialog(self, self.ini_path)
        if dlg.ShowModal() == wx.ID_OK:
            # Ponownie wczytaj ustawienia i dostosuj timer autozapisu oraz słownik
            self.LoadSettings()
            self.SetupAutoSave()
            # Aktualizuj menu bar na wypadek gdyby dostępność sprawdzania pisowni się zmieniła
            self.CreateMenuBar()
            # Nie trzeba już Layout() po CreateMenuBar, bo SetMenuBar to robi

        dlg.Destroy()

    def OnAutoSave(self, event):
        """Wykonywane przez timer autozapisu."""
        if self.current_file and self.text_ctrl.IsModified():
            print(f"Autozapis pliku: {os.path.basename(self.current_file)} @ {datetime.datetime.now().strftime('%H:%M:%S')}")
            self.SaveFile(self.current_file)
        # else:
        #     print("Autozapis pominięty (brak pliku lub brak zmian).") # Opcjonalne logowanie


    def ClearSpellCheckHighlights(self):
        """Usuwa wszystkie podkreślenia/wyróżnienia błędów pisowni."""
        if self.using_underline_highlight:
            # Usuń tylko podkreślenia, jeśli ich używaliśmy
            default_underline_style = wx.TextAttr()
            try: # Ponownie sprawdź dostępność flagi na wszelki wypadek
                 default_underline_style.SetFlags(wx.TEXT_ATTR_UNDERLINE_TYPE)
                 default_underline_style.SetUnderlineStyle(wx.UNDERLINE_NONE)
            except AttributeError:
                 # Jeśli flaga niedostępna, nie możemy precyzyjnie usunąć tylko underline
                 # W tym przypadku, najlepiej zresetować cały styl dla zakresu do domyślnego
                 default_underline_style = wx.TextAttr() # Pusty TextAttr oznacza domyślny styl

            self.text_ctrl.SetStyle(0, self.text_ctrl.GetLastPosition(), default_underline_style)

        else:
            # Jeśli używaliśmy tła, zresetuj tło dla całego tekstu
            default_bg_style = wx.TextAttr()
            default_bg_style.SetBackgroundColour(wx.NullColour) # Resetuj tło do domyślnego
            # Spróbuj ustawić flagę, jeśli dostępna, aby być precyzyjnym
            try:
                default_bg_style.SetFlags(wx.TEXT_ATTR_BACKGROUND_COLOUR)
            except AttributeError:
                pass # Flaga niedostępna, polegaj na NullColour z TE_RICH2

            self.text_ctrl.SetStyle(0, self.text_ctrl.GetLastPosition(), default_bg_style)


    def OnCheckSpelling(self, event):
        """Sprawdza pisownię w całym dokumencie i wyróżnia błędy."""
        if not self.spell_check_enabled or not self.spell_dict:
            wx.MessageBox(_("Sprawdzanie pisowni jest wyłączone w ustawieniach lub słownik nie został poprawnie załadowany."),
                          _("Sprawdzanie pisowni - Status"), wx.OK|wx.ICON_INFORMATION)
            # Jeśli enchant jest dostępny, ale słownik nie, spróbuj wczytać słownik ponownie
            if ENCHANT_AVAILABLE and not self.spell_dict:
                 # wx.CallAfter(self.LoadSettings) # Wywołanie LoadSettings może być asynchroniczne
                 # Zamiast tego, możemy spróbować zainicjować słownik bezpośrednio tutaj,
                 # choć LoadSettings robi więcej rzeczy (ustawienia, timer).
                 # Prostsze jest poproszenie użytkownika o wejście w ustawienia.
                 wx.MessageBox(_("Spróbuj włączyć sprawdzanie pisowni w Ustawieniach programu."),
                               _("Wskazówka"), wx.OK|wx.ICON_INFORMATION)
            return # Przerwij, jeśli sprawdzanie jest wyłączone lub słownik brak

        self.ClearSpellCheckHighlights() # Wyczyść poprzednie wyróżnienia

        content = self.text_ctrl.GetValue()
        # Użyj regex do znalezienia słów (ciągi liter)
        # \b - granica słowa, [^\W\d_]+ - jeden lub więcej znaków, które nie są (nie-literą, cyfrą, podkreśleniem)
        # Zapewnia obsługę polskich znaków i innych liter Unicode, ignoruje cyfry i _ wewnątrz słowa
        word_regex = re.compile(r'\b[^\W\d_]+\b', re.UNICODE)

        errors_found = 0
        # Iteruj przez wszystkie znalezione słowa wraz z ich pozycjami
        for match in word_regex.finditer(content):
            word = match.group(0) # Użyj group(0) by wziąć całe dopasowanie (słowo)
            start, end = match.span()

            # Sprawdź pisownię. Enchant jest case-sensitive, często sprawdza się lowercase.
            # Możesz dodać logikę ignorowania wyrazów pisanych w całości dużymi literami lub rozpoczynających się od dużej litery, jeśli nie są na początku zdania.
            # Dla uproszczenia, sprawdzamy lowercase, ale oryginalna pozycja jest używana do podkreślenia.
            if not self.spell_dict.check(word.lower()):
                # Znaleziono błąd, zastosuj styl wyróżnienia
                self.text_ctrl.SetStyle(start, end, self.spell_error_style)
                errors_found += 1

        if errors_found == 0:
            wx.MessageBox(_("Nie znaleziono błędów pisowni."), _("Informacja"), wx.OK|wx.ICON_INFORMATION)
        else:
            wx.MessageBox(_("Zakończono sprawdzanie pisowni. Znaleziono {errors_found} błędów.").format(errors_found=errors_found), _("Informacja"), wx.OK|wx.ICON_INFORMATION)


if __name__ == "__main__":
    app = wx.App()
    frame = TextEditor(None) # Usunięto title="TEdit" z Frame, bo ustawiamy je w __init__
    frame.Show()
    app.MainLoop()

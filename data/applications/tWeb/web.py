# -*- coding: utf-8 -*-
import wx
import wx.html2
import threading
import os
import platform
import configparser
import re
import pygame
from translation import _
import accessible_output3.outputs.auto

pygame.mixer.init()
speaker = accessible_output3.outputs.auto.Auto()

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

def get_config_path():
    if platform.system() == 'Windows':
        appdata = os.getenv('APPDATA')
        config_dir = os.path.join(appdata, 'Titosoft', 'Titan', 'appsettings')
    elif platform.system() == 'Darwin':  # macOS
        home = os.path.expanduser('~')
        config_dir = os.path.join(home, 'Library', 'Application Support', 'Titosoft', 'Titan', 'appsettings')
    else:
        home = os.path.expanduser('~')
        config_dir = os.path.join(home, '.config', 'Titosoft', 'Titan', 'appsettings')
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    config_path = os.path.join(config_dir, 'tbrowser.ini')
    return config_path

CONFIG_PATH = get_config_path()

DEFAULT_SETTINGS = {
    'announcements': {
        'announce_page_summary': 'True',
        'loading_messages': 'True'
    },
    'interface': {
        'view_mode': 'edge'
    },
    # Nowa sekcja privacy
    'privacy': {
        'block_cookie_banners': 'False'
    }
}

config = configparser.ConfigParser()
if not os.path.exists(CONFIG_PATH):
    # Jeśli pliku nie ma, tworzymy go z domyślnymi ustawieniami
    config.read_dict(DEFAULT_SETTINGS)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as configfile:
        config.write(configfile)
else:
    config.read(CONFIG_PATH, encoding='utf-8')

    # Uzupełniamy ewentualnie brakujące sekcje/klucze
    for section in DEFAULT_SETTINGS:
        if section not in config:
            config[section] = DEFAULT_SETTINGS[section]
        else:
            for key in DEFAULT_SETTINGS[section]:
                if key not in config[section]:
                    config[section][key] = DEFAULT_SETTINGS[section][key]

    with open(CONFIG_PATH, 'w', encoding='utf-8') as configfile:
        config.write(configfile)

def play_sound(sound_file):
    sound_path = os.path.join('sfx', sound_file)
    if not os.path.exists(sound_path):
        print(_("Nie znaleziono pliku dźwiękowego: {}").format(sound_path))
        return
    try:
        sound = pygame.mixer.Sound(sound_path)
        sound.play()
    except Exception as e:
        print(_("Nie można odtworzyć dźwięku: {}").format(e))

def speak(text):
    speaker.speak(text)

class DownloadsDialog(wx.Dialog):
    def __init__(self, parent, downloads):
        super(DownloadsDialog, self).__init__(parent, title=_("Pobrane pliki"))
        self.parent = parent
        self.downloads = downloads

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        info_text = wx.StaticText(panel, label=_("Lista plików pobranych przez tBrowser:"))
        vbox.Add(info_text, flag=wx.ALL, border=5)

        self.listbox = wx.ListBox(panel, choices=self.downloads, style=wx.LB_SINGLE)
        vbox.Add(self.listbox, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)

        # Enter i Del w liście
        self.listbox.Bind(wx.EVT_KEY_DOWN, self.onKeyDown)

        panel.SetSizer(vbox)
        self.SetSize((400, 300))
        self.Centre()

    def onKeyDown(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_RETURN:
            self.openSelectedFile()
        elif keycode == wx.WXK_DELETE:
            self.removeSelectedFile()
        else:
            event.Skip()

    def openSelectedFile(self):
        selection = self.listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        file_path = self.listbox.GetString(selection)
        if platform.system() == 'Windows':
            os.startfile(file_path)
        elif platform.system() == 'Darwin':
            os.system(f"open '{file_path}'")
        else:
            os.system(f"xdg-open '{file_path}'")

    def removeSelectedFile(self):
        selection = self.listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        self.listbox.Delete(selection)
        del self.downloads[selection]

class BrowserFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(BrowserFrame, self).__init__(*args, **kwargs)

        self.loading = False
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnTimer)

        self.settings = config
        self.home_url = 'http://titosofttitan.com/titan'

        # Lista pobranych plików (póki co pusta).
        self.downloads = []

        self.InitUI()
        self.Centre()
        self.Show()
        self.LoadHomePage()

    def InitUI(self):
        self.SetTitle(_("tBrowser"))
        self.SetSize((800, 600))

        self.panel = wx.Panel(self)
        self.panel.SetWindowStyleFlag(wx.TAB_TRAVERSAL)

        vbox = wx.BoxSizer(wx.VERTICAL)

        self.toolbar = wx.Panel(self.panel)
        self.toolbar_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.back_button = wx.Button(self.toolbar, label=_("Wstecz"))
        self.forward_button = wx.Button(self.toolbar, label=_("Dalej"))
        self.refresh_button = wx.Button(self.toolbar, label=_("Odśwież"))

        self.back_button.SetToolTip(_("Przycisk Wstecz"))
        self.forward_button.SetToolTip(_("Przycisk Dalej"))
        self.refresh_button.SetToolTip(_("Przycisk Odśwież"))

        self.address = wx.TextCtrl(self.toolbar, style=wx.TE_PROCESS_ENTER)
        self.address.SetHint(_("Wpisz adres lub wyszukaj w Google"))

        self.toolbar_sizer.Add(self.back_button, 0, wx.ALL, 5)
        self.toolbar_sizer.Add(self.forward_button, 0, wx.ALL, 5)
        self.toolbar_sizer.Add(self.refresh_button, 0, wx.ALL, 5)
        self.toolbar_sizer.Add(self.address, 1, wx.ALL | wx.EXPAND, 5)

        self.toolbar.SetSizer(self.toolbar_sizer)
        vbox.Add(self.toolbar, 0, wx.EXPAND)

        view_mode = self.settings['interface'].get('view_mode', 'edge')
        if view_mode == 'edge':
            self.browser = wx.html2.WebView.New(self.panel)
            self.browser.EnableAccessToDevTools(True)
            self.browser.Bind(wx.EVT_CHAR_HOOK, self.OnBrowserCharHook)
            self.browser.SetFocus()
        else:
            self.browser = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
            self.browser.SetFocus()

        vbox.Add(self.browser, 1, wx.EXPAND)

        self.panel.SetSizer(vbox)

        self.statusbar = self.CreateStatusBar(2)
        self.statusbar.SetStatusWidths([-1, 100])

        self.progress = wx.Gauge(self.statusbar, range=100, style=wx.GA_HORIZONTAL)
        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.OnSize(None)

        self.BindEvents()
        self.CreateMenuBar()

    def LoadHomePage(self):
        if isinstance(self.browser, wx.html2.WebView):
            self.browser.LoadURL(self.home_url)
        else:
            self.address.SetValue(self.home_url)
            self.LoadVirtualBuffer(self.home_url)

    def OnSize(self, event):
        rect = self.statusbar.GetFieldRect(1)
        self.progress.SetPosition((rect.x + 2, rect.y + 2))
        self.progress.SetSize((rect.width - 4, rect.height - 4))
        if event:
            event.Skip()

    def BindEvents(self):
        if isinstance(self.browser, wx.html2.WebView):
            self.browser.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, self.OnNavigating)
            self.browser.Bind(wx.html2.EVT_WEBVIEW_LOADED, self.OnPageLoaded)
            self.browser.Bind(wx.html2.EVT_WEBVIEW_TITLE_CHANGED, self.OnTitleChanged)

        self.address.Bind(wx.EVT_TEXT_ENTER, self.OnAddressEnter)
        self.back_button.Bind(wx.EVT_BUTTON, self.OnBack)
        self.forward_button.Bind(wx.EVT_BUTTON, self.OnForward)
        self.refresh_button.Bind(wx.EVT_BUTTON, self.OnRefresh)

        self.Bind(wx.EVT_CHAR_HOOK, self.OnCharHook)

        if isinstance(self.browser, wx.TextCtrl):
            self.browser.Bind(wx.EVT_LEFT_DOWN, self.OnTextCtrlClick)
            self.browser.Bind(wx.EVT_KEY_DOWN, self.OnTextCtrlKeyDown)

    def CreateMenuBar(self):
        menubar = wx.MenuBar()
        app_menu = wx.Menu()

        settings_item = app_menu.Append(wx.ID_ANY, _("Ustawienia..."))
        menubar.Append(app_menu, _("Aplikacja"))

        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_MENU, self.OnSettings, settings_item)

    def OnSettings(self, event):
        settings_dialog = SettingsDialog(self)
        settings_dialog.ShowModal()
        settings_dialog.Destroy()

    def OnBack(self, event):
        if isinstance(self.browser, wx.html2.WebView):
            if self.browser.CanGoBack():
                self.browser.GoBack()
        else:
            wx.MessageBox(_("Nawigacja wstecz nie jest dostępna w trybie wirtualnego bufora."),
                          _("Informacja"), wx.OK | wx.ICON_INFORMATION)

    def OnForward(self, event):
        if isinstance(self.browser, wx.html2.WebView):
            if self.browser.CanGoForward():
                self.browser.GoForward()
        else:
            wx.MessageBox(_("Nawigacja do przodu nie jest dostępna w trybie wirtualnego bufora."),
                          _("Informacja"), wx.OK | wx.ICON_INFORMATION)

    def OnRefresh(self, event):
        if isinstance(self.browser, wx.html2.WebView):
            self.browser.Reload()
        else:
            self.LoadVirtualBuffer(self.address.GetValue())

    def OnNavigating(self, event):
        url = event.GetURL()
        self.address.SetValue(url)
        self.statusbar.SetStatusText(_("Ładowanie strony..."))
        threading.Thread(target=play_sound, args=('select.ogg',), daemon=True).start()
        self.progress.SetValue(0)
        self.loading = True
        self.timer.Start(100)

        if self.settings.getboolean('announcements', 'loading_messages'):
            threading.Thread(target=speak, args=(_("Ładowanie strony..."),), daemon=True).start()

    def OnPageLoaded(self, event):
        """Po załadowaniu strony w WebView."""
        self.statusbar.SetStatusText(_("Strona załadowana."))
        self.progress.SetValue(100)
        threading.Thread(target=play_sound, args=('ding.ogg',), daemon=True).start()
        self.loading = False
        self.timer.Stop()

        # Jeśli włączone komunikaty
        if self.settings.getboolean('announcements', 'loading_messages'):
            title = self.browser.GetCurrentTitle()
            threading.Thread(target=speak, args=(_("Załadowano stronę {}").format(title),), daemon=True).start()

        # Ustawiamy tytuł okna
        title = self.browser.GetCurrentTitle()
        self.SetTitle(f"{title} - tBrowser")
        self.browser.SetFocus()

        # Jeśli jest włączone ukrywanie alertów cookie, to uruchamiamy krótki JS
        if self.settings.getboolean('privacy', 'block_cookie_banners'):
            self.hide_cookie_banners_webview()

        # Komunikat o strukturze strony
        if self.settings.getboolean('announcements', 'announce_page_summary'):
            self.DisplayPageInfo()

    def hide_cookie_banners_webview(self):
        """
        Przykładowy skrypt JS, który próbuje odnaleźć dowolny element,
        w którego klasie lub ID pojawia się słowo 'cookie', i go ukrywa.
        """
        script = r"""
        var banners = document.querySelectorAll('[id*="cookie"], [class*="cookie"]');
        for (var i = 0; i < banners.length; i++) {
            banners[i].style.display = 'none';
        }
        """
        self.browser.RunScript(script)

    def OnTitleChanged(self, event):
        title = event.GetString()
        self.SetTitle(f"{title} - tBrowser")

    def OnTimer(self, event):
        if self.loading:
            current_value = self.progress.GetValue()
            if current_value < 90:
                self.progress.SetValue(current_value + 5)
        else:
            self.timer.Stop()

    def OnAddressEnter(self, event):
        input_text = self.address.GetValue().strip()
        if not input_text:
            return
        if self.is_probable_url(input_text):
            url = input_text
            if not url.startswith(('http://', 'https://')):
                url = 'http://' + url
            self.address.SetValue(url)
        else:
            query = requests.utils.quote(input_text)
            url = f"https://www.google.com/search?q={query}"
            self.address.SetValue(url)

        if isinstance(self.browser, wx.html2.WebView):
            self.browser.LoadURL(url)
            self.browser.SetFocus()
        else:
            self.LoadVirtualBuffer(url)

    def is_probable_url(self, text):
        return bool(re.match(r'^[\w.-]+\.[a-z]{2,}$', text, re.IGNORECASE))

    def OnCharHook(self, event):
        """
        Globalny skrót klawiaturowy dla okna głównego:
        - F6 lub Ctrl+L: fokus na pasek adresu
        - Ctrl+J: wyświetlenie okna pobranych plików
        """
        keycode = event.GetKeyCode()
        ctrl_down = event.ControlDown()

        if keycode == wx.WXK_F6 or (ctrl_down and keycode == ord('L')):
            self.address.SetFocus()
            self.address.SelectAll()
        elif ctrl_down and keycode == ord('J'):
            self.ShowDownloads()
        else:
            event.Skip()

    def OnBrowserCharHook(self, event):
        """
        Skróty wewnątrz WebView:
        - F5: odświeżenie strony
        - F6 lub Ctrl+L: fokus na pasek adresu
        Wszystkie inne skróty są przekazywane do silnika przeglądarki.
        """
        keycode = event.GetKeyCode()
        ctrl_down = event.ControlDown()

        if keycode == wx.WXK_F5:
            self.OnRefresh(event)
        elif keycode == wx.WXK_F6 or (ctrl_down and keycode == ord('L')):
            self.address.SetFocus()
            self.address.SelectAll()
        else:
            # Przekazujemy zdarzenie dalej, aby standardowe skróty (np. Ctrl+C, Ctrl+F) działały
            event.Skip()

    def ShowDownloads(self):
        dlg = DownloadsDialog(self, self.downloads)
        dlg.ShowModal()
        dlg.Destroy()

    def OnTextCtrlClick(self, event):
        # Dotyczy trybu wirtualnego bufora
        position = self.browser.HitTestPos(event.GetPosition())
        # Search from last to first because elements can be nested.
        for element in reversed(self.interactive_elements):
            if element['start'] <= position <= element['end']:
                element_type = element.get('type')
                if element_type == 'link':
                    # Make sure href is a full URL
                    base_url = self.address.GetValue()
                    href = element['tag'].get('href', '')
                    full_url = requests.compat.urljoin(base_url, href)
                    self.address.SetValue(full_url)
                    self.LoadVirtualBuffer(full_url)
                elif element_type == 'button':
                    # For now, just a message. Form submission would be complex.
                    wx.MessageBox(_("Kliknięto przycisk: {}").format(element['label']), _("Informacja"), wx.OK | wx.ICON_INFORMATION)
                elif element_type in ['input_text', 'textarea']:
                    self.EditTextElement(element)
                elif element_type in ['checkbox', 'radio']:
                    self.ToggleCheckElement(element)
                return # Stop after handling the first match
        event.Skip()

    def OnTextCtrlKeyDown(self, event):
        keycode = event.GetKeyCode()
        ctrl_down = event.ControlDown()
        shift_down = event.ShiftDown()
        if keycode == wx.WXK_TAB:
            self.Navigate()
        elif keycode == wx.WXK_F6 or (ctrl_down and keycode == ord('L')):
            self.address.SetFocus()
            self.address.SelectAll()
        else:
            event.Skip()

    def Navigate(self):
        pass

    def DisplayPageInfo(self):
        if isinstance(self.browser, wx.html2.WebView):
            script = """
            var forms = document.getElementsByTagName('form').length;
            var links = document.getElementsByTagName('a').length;
            var buttons = document.getElementsByTagName('button').length;
            var rows = document.getElementsByTagName('tr').length;
            var result = forms + ',' + links + ',' + buttons + ',' + rows;
            result;
            """
            result = self.browser.RunScript(script)
            if result:
                data = result.split(',')
                if len(data) == 4:
                    forms, links, buttons, rows = data
                    message = _("Strona zawiera {} pól formularza, {} łączy, {} przycisków i {} wierszy.").format(forms, links, buttons, rows)
                    threading.Thread(target=speak, args=(message,), daemon=True).start()
        else:
            if hasattr(self, 'current_soup'):
                forms = len(self.current_soup.find_all('form'))
                links = len(self.current_soup.find_all('a'))
                buttons = len(self.current_soup.find_all('button'))
                rows = len(self.current_soup.find_all('tr'))
                message = _("Strona zawiera {} pól formularza, {} łączy, {} przycisków i {} wierszy.").format(forms, links, buttons, rows)
                threading.Thread(target=speak, args=(message,), daemon=True).start()

    def get_label_for_input(self, input_element):
        # 1. Check for a <label> with a 'for' attribute matching the input's id
        if input_element.get('id'):
            # BeautifulSoup's find doesn't automatically search the whole document
            # from a tag object, so we search from the root soup.
            label = self.current_soup.find('label', {'for': input_element['id']})
            if label:
                return label.get_text(strip=True)

        # 2. Check if the input is wrapped inside a <label>
        parent_label = input_element.find_parent('label')
        if parent_label:
            # We need to be careful not to include the text of the input itself if it's inside the label
            # A simple way is to get all text and then remove the input's value if present.
            # A cleaner way is to extract the input and get text again, but that modifies the tree.
            # Let's stick to a simple text extraction.
            return ' '.join(parent_label.find_all(string=True, recursive=False)).strip()


        # 3. Fallback to 'aria-label', 'placeholder', or 'name' attribute
        for attr in ['aria-label', 'placeholder', 'title', 'name']:
            if input_element.get(attr):
                return input_element.get(attr)
        
        return '' # No label found

    def parse_input_tag(self, child):
        input_type = child.get('type', 'text').lower()
        label = self.get_label_for_input(child)
        start = self.browser.GetLastPosition()
        
        display_text = ""
        element_type = None

        if input_type in ['text', 'password', 'email', 'search', 'tel', 'url']:
            element_type = 'input_text'
            value = child.get('value', '')
            display_text = _("Pole edycji: {}").format(label)
            if value:
                display_text += _(", Wartość: {}").format(value)
        
        elif input_type in ['button', 'submit', 'reset']:
            element_type = 'button'
            value = child.get('value')
            # If value is empty, try to get label from text, though inputs don't have text content.
            label = value or label or _("Przycisk bez etykiety")
            display_text = _("Przycisk: {}").format(label)

        elif input_type in ['checkbox', 'radio']:
            element_type = input_type
            is_checked = child.has_attr('checked')
            state = _("zaznaczone") if is_checked else _("niezaznaczone")
            if input_type == 'checkbox':
                display_text = _("Pole wyboru: {} ({})").format(label, state)
            else: # radio
                display_text = _("Przycisk radiowy: {} ({})").format(label, state)

        if display_text:
            self.browser.AppendText(display_text + ' ')
            end = self.browser.GetLastPosition()
            self.interactive_elements.append({
                'start': start, 'end': end, 'type': element_type,
                'label': label, 'tag': child
            })

    def parse_textarea_tag(self, child):
        label = self.get_label_for_input(child)
        value = child.get_text(strip=True)
        start = self.browser.GetLastPosition()
        display_text = _("Pole tekstowe: {}").format(label)
        if value:
            display_text += _(", Wartość: {}").format(value)
        
        self.browser.AppendText(display_text + ' ')
        end = self.browser.GetLastPosition()
        self.interactive_elements.append({
            'start': start, 'end': end, 'type': 'textarea',
            'label': label, 'tag': child
        })

    def EditTextElement(self, element):
        tag = element['tag']
        current_value = ''
        if element['type'] == 'textarea':
            current_value = ''.join(tag.stripped_strings)
        else: # input_text
            current_value = tag.get('value', '')

        dlg = wx.TextEntryDialog(self, _("Wprowadź tekst dla: {}").format(element['label']), _("Edycja pola"), current_value)
        
        if dlg.ShowModal() == wx.ID_OK:
            new_value = dlg.GetValue()
            if element['type'] == 'textarea':
                tag.clear() # Remove old content
                tag.append(new_value)
            else: # input_text
                tag['value'] = new_value
            
            self.render_content(self.current_soup)
            speak(_("Wpisano: {}").format(new_value))
        
        dlg.Destroy()

    def ToggleCheckElement(self, element):
        tag = element['tag']
        
        if element['type'] == 'checkbox':
            if tag.has_attr('checked'):
                del tag['checked']
            else:
                tag['checked'] = 'checked'
        
        elif element['type'] == 'radio':
            # In radio groups, only one can be selected.
            # First, ensure the clicked one is checked.
            if not tag.has_attr('checked'):
                name = tag.get('name')
                if name:
                    # Find all radio buttons in the same group within the same form
                    form = tag.find_parent('form')
                    search_root = form if form else self.current_soup
                    radios = search_root.find_all('input', {'type': 'radio', 'name': name})
                    for r in radios:
                        if r.has_attr('checked'):
                            del r['checked']
                tag['checked'] = 'checked'

        self.render_content(self.current_soup)
        new_state = _("zaznaczone") if tag.has_attr('checked') else _("niezaznaczone")
        speak(_("{} {}").format(element['label'], new_state))

    def LoadVirtualBuffer(self, url):
        """Ładowanie strony w trybie wirtualnego bufora."""
        self.statusbar.SetStatusText(_("Ładowanie strony..."))
        threading.Thread(target=play_sound, args=('select.ogg',), daemon=True).start()
        self.progress.SetValue(0)
        self.loading = True
        self.timer.Start(100)

        def load_content():
            try:
                response = requests.get(url)
                soup = BeautifulSoup(response.content, 'html.parser')
                self.current_soup = soup

                # Jeśli włączone blokowanie cookie-banners, usuwamy z DOM to, co wygląda na banner.
                if self.settings.getboolean('privacy', 'block_cookie_banners'):
                    # Prosta heurystyka: usuwamy elementy, w których ID lub class zawiera "cookie"
                    cookie_divs = soup.find_all(lambda tag:
                        ('cookie' in (tag.get('id') or '').lower()) or
                        ('cookie' in ' '.join(tag.get('class', [])).lower())
                    )
                    for c in cookie_divs:
                        c.decompose()  # usuwa element z drzewa

                wx.CallAfter(self.render_content, soup)

                self.loading = False
                wx.CallAfter(self.timer.Stop)
                wx.CallAfter(self.progress.SetValue, 100)
                wx.CallAfter(self.statusbar.SetStatusText, _("Strona załadowana."))
                threading.Thread(target=play_sound, args=('ding.ogg',), daemon=True).start()

                if self.settings.getboolean('announcements', 'loading_messages'):
                    threading.Thread(target=speak, args=(_("Załadowano stronę"),), daemon=True).start()

                title_tag = soup.find('title')
                if title_tag:
                    title = title_tag.get_text()
                else:
                    title = url
                wx.CallAfter(self.SetTitle, f"{title} - tBrowser")
                wx.CallAfter(self.browser.SetFocus)

                if self.settings.getboolean('announcements', 'announce_page_summary'):
                    wx.CallAfter(self.DisplayPageInfo)
            except Exception as e:
                print(_("Błąd podczas ładowania strony: {}").format(e))
                wx.CallAfter(self.statusbar.SetStatusText, _("Błąd podczas ładowania strony."))
                self.loading = False
                wx.CallAfter(self.timer.Stop)

        threading.Thread(target=load_content, daemon=True).start()

    def render_content(self, soup):
        self.browser.Freeze()
        self.browser.Clear()
        self.interactive_elements = []

        # Ignorowane tagi, które nie powinny być renderowane
        ignored_tags = ['script', 'style', 'meta', 'link', 'head']
        for tag in soup.find_all(ignored_tags):
            tag.decompose()

        body = soup.find('body')
        if body:
            self.parse_element(body)

        self.browser.Thaw()

    def parse_element(self, element):
        for child in element.children:
            if isinstance(child, NavigableString):
                text = child.strip()
                if text:
                    self.browser.AppendText(text + ' ')
            elif isinstance(child, Tag):
                # Elementy blokowe, które wymagają nowej linii przed i po
                if child.name in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'pre', 'form', 'table', 'tr', 'th', 'td']:
                    self.browser.AppendText('\n')
                    self.parse_element(child)
                    self.browser.AppendText('\n')
                elif child.name == 'a':
                    link_label = child.get_text(strip=True) or child.get('href', '')
                    start = self.browser.GetLastPosition()
                    display_text = _("Łącze: {}").format(link_label)
                    self.browser.AppendText(display_text + ' ')
                    end = self.browser.GetLastPosition()
                    self.interactive_elements.append({
                        'start': start, 'end': end, 'type': 'link',
                        'label': link_label, 'tag': child
                    })
                elif child.name == 'button':
                    button_label = child.get_text(strip=True) or child.get('value', _('Przycisk'))
                    start = self.browser.GetLastPosition()
                    display_text = _("Przycisk: {}").format(button_label)
                    self.browser.AppendText(display_text + ' ')
                    end = self.browser.GetLastPosition()
                    self.interactive_elements.append({
                        'start': start, 'end': end, 'type': 'button',
                        'label': button_label, 'tag': child
                    })
                elif child.name == 'input':
                    self.parse_input_tag(child)
                elif child.name == 'textarea':
                    self.parse_textarea_tag(child)
                elif child.name == 'br':
                    self.browser.AppendText('\n')
                else:
                    # Inne tagi traktujemy jako liniowe
                    self.parse_element(child)

class SettingsDialog(wx.Dialog):
    def __init__(self, parent):
        super(SettingsDialog, self).__init__(parent, title=_("Ustawienia tBrowser"))
        self.settings = config

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Grupa "Oznajmianie"
        announcement_box = wx.StaticBox(panel, label=_("Oznajmianie"))
        announcement_sizer = wx.StaticBoxSizer(announcement_box, wx.VERTICAL)

        self.announce_summary_cb = wx.CheckBox(panel, label=_("Oznajmiaj podsumowanie strony"))
        self.announce_summary_cb.SetValue(self.settings.getboolean('announcements', 'announce_page_summary'))

        self.loading_messages_cb = wx.CheckBox(panel, label=_("Komunikaty o ładowaniu strony"))
        self.loading_messages_cb.SetValue(self.settings.getboolean('announcements', 'loading_messages'))

        announcement_sizer.Add(self.announce_summary_cb, flag=wx.ALL, border=5)
        announcement_sizer.Add(self.loading_messages_cb, flag=wx.ALL, border=5)

        # Grupa "Interfejs"
        interface_box = wx.StaticBox(panel, label=_("Interfejs"))
        interface_sizer = wx.StaticBoxSizer(interface_box, wx.VERTICAL)

        view_mode_label = wx.StaticText(panel, label=_("Wybierz tryb przeglądania strony:"))
        self.view_mode_choice = wx.Choice(panel, 
            choices=[_("Widok sieciowy (edge)"), _("Tryb wirtualnego bufora")])
        current_mode = self.settings['interface'].get('view_mode', 'edge')
        if current_mode == 'edge':
            self.view_mode_choice.SetSelection(0)
        else:
            self.view_mode_choice.SetSelection(1)

        interface_sizer.Add(view_mode_label, flag=wx.ALL, border=5)
        interface_sizer.Add(self.view_mode_choice, flag=wx.ALL | wx.EXPAND, border=5)

        # Nowa grupa "Prywatność"
        privacy_box = wx.StaticBox(panel, label=_("Prywatność"))
        privacy_sizer = wx.StaticBoxSizer(privacy_box, wx.VERTICAL)

        # Checkbox do blokowania komunikatów o cookies
        self.block_cookies_cb = wx.CheckBox(panel, label=_("Nie wyświetlaj alertów o plikach cookie (o ile to możliwe)"))
        self.block_cookies_cb.SetValue(self.settings.getboolean('privacy', 'block_cookie_banners'))

        privacy_sizer.Add(self.block_cookies_cb, flag=wx.ALL, border=5)

        # Przyciski Zapisz i Anuluj
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(panel, label=_("Zapisz"))
        cancel_btn = wx.Button(panel, label=_("Anuluj"))
        btn_sizer.Add(save_btn, flag=wx.ALL, border=5)
        btn_sizer.Add(cancel_btn, flag=wx.ALL, border=5)

        save_btn.Bind(wx.EVT_BUTTON, self.OnSave)
        cancel_btn.Bind(wx.EVT_BUTTON, self.OnCancel)

        # Układ w oknie ustawień
        vbox.Add(announcement_sizer, flag=wx.ALL | wx.EXPAND, border=10)
        vbox.Add(interface_sizer, flag=wx.ALL | wx.EXPAND, border=10)
        vbox.Add(privacy_sizer, flag=wx.ALL | wx.EXPAND, border=10)
        vbox.Add(btn_sizer, flag=wx.ALIGN_CENTER)

        panel.SetSizer(vbox)
        self.SetSize((400, 400))
        self.Centre()

    def OnSave(self, event):
        self.settings['announcements']['announce_page_summary'] = str(self.announce_summary_cb.GetValue())
        self.settings['announcements']['loading_messages'] = str(self.loading_messages_cb.GetValue())

        if self.view_mode_choice.GetSelection() == 0:
            self.settings['interface']['view_mode'] = 'edge'
        else:
            self.settings['interface']['view_mode'] = 'virtual_buffer'

        # Zapisujemy ustawienie dotyczące plików cookie:
        self.settings['privacy']['block_cookie_banners'] = str(self.block_cookies_cb.GetValue())

        with open(CONFIG_PATH, 'w', encoding='utf-8') as configfile:
            self.settings.write(configfile)

        wx.MessageBox(_("Ustawienia zostały zapisane. Uruchom ponownie aplikację, aby zastosować zmiany."),
                      _("Informacja"), wx.OK | wx.ICON_INFORMATION)
        self.EndModal(wx.ID_OK)

    def OnCancel(self, event):
        self.EndModal(wx.ID_CANCEL)

if __name__ == '__main__':
    app = wx.App()
    frame = BrowserFrame(None)
    app.MainLoop()
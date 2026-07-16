# -*- coding: utf-8 -*-
"""A single tWeb tab: either a wx.html2.WebView (edge mode) or the
virtual-buffer reader (BeautifulSoup HTML parsed into a read-only TextCtrl).

BrowserFrame (web.py) hosts N of these inside a wx.Notebook. Toolbar/menu
actions (back/forward/refresh/address bar/zoom/find) are global and act on
whichever BrowserTab is active; per-tab state (loading, interactive
elements, virtual cursor) lives here.
"""
import wx
import wx.html2
import threading
import re
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from translation import _

from common import speak, play_sound
import downloads


class BrowserTab(wx.Panel):
    def __init__(self, notebook, owner, url=None):
        super(BrowserTab, self).__init__(notebook)
        self.owner = owner
        self.loading = False
        self.current_url = url or ''
        self.current_title = _("Nowa karta")
        self.current_soup = None
        self.interactive_elements = []
        self._cursor_index = -1
        # WebView2's backend attaches asynchronously after wx.html2.WebView.New()
        # returns; querying live state (e.g. GetZoomFactor()) before the first
        # EVT_WEBVIEW_LOADED is a native access violation, not a Python
        # exception -- it cannot be caught with try/except and crashes the
        # whole process. This flags when it's actually safe to query.
        self._webview_ready = False

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.view_mode = self.owner.settings['interface'].get('view_mode', 'edge')
        if self.view_mode == 'edge':
            self.browser = wx.html2.WebView.New(self)
            self.browser.EnableAccessToDevTools(True)
            self.browser.Bind(wx.EVT_CHAR_HOOK, self.OnBrowserCharHook)
            self.browser.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, self.OnNavigating)
            self.browser.Bind(wx.html2.EVT_WEBVIEW_LOADED, self.OnPageLoaded)
            self.browser.Bind(wx.html2.EVT_WEBVIEW_TITLE_CHANGED, self.OnTitleChanged)
            self.browser.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, self.OnNewWindow)
        else:
            self.browser = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
            self.browser.Bind(wx.EVT_LEFT_DOWN, self.OnTextCtrlClick)
            self.browser.Bind(wx.EVT_KEY_DOWN, self.OnTextCtrlKeyDown)

        vbox.Add(self.browser, 1, wx.EXPAND)
        self.SetSizer(vbox)

        # Deliberately not auto-loading `url` here: is_active()/_set_loading_ui()
        # need self.owner.get_active_tab() to already resolve to this tab, which
        # requires the caller to have added it to the notebook first. See
        # BrowserFrame.open_new_tab, which constructs with url=None then calls
        # load() once the tab is wired in.

    # ------------------------------------------------------------------ #
    # Frame-facing helpers
    # ------------------------------------------------------------------ #
    def is_active(self):
        return self.owner.get_active_tab() is self

    def focus_content(self):
        self.browser.SetFocus()

    def is_webview(self):
        return isinstance(self.browser, wx.html2.WebView)

    def is_zoom_ready(self):
        """True once it's safe to call GetZoomFactor()/SetZoomFactor() -- see
        the _webview_ready comment in __init__."""
        return self.is_webview() and self._webview_ready

    def load(self, url):
        self.current_url = url
        if self.is_webview():
            self.browser.LoadURL(url)
            self.browser.SetFocus()
        else:
            self.LoadVirtualBuffer(url)

    def get_url(self):
        if self.is_webview():
            try:
                return self.browser.GetCurrentURL() or self.current_url
            except Exception:
                pass
        return self.current_url

    def get_title(self):
        if self.is_webview():
            try:
                return self.browser.GetCurrentTitle() or self.get_url()
            except Exception:
                pass
        return self.current_title

    def can_go_back(self):
        return self.is_webview() and self.browser.CanGoBack()

    def can_go_forward(self):
        return self.is_webview() and self.browser.CanGoForward()

    def go_back(self):
        if self.can_go_back():
            self.browser.GoBack()

    def go_forward(self):
        if self.can_go_forward():
            self.browser.GoForward()

    def refresh(self):
        if self.is_webview():
            self.browser.Reload()
        else:
            self.LoadVirtualBuffer(self.current_url)

    def zoom_in(self):
        if not self.is_zoom_ready():
            return
        try:
            self.browser.SetZoomType(wx.html2.WEBVIEW_ZOOM_TYPE_LAYOUT)
            current = self.browser.GetZoomFactor()
            self.browser.SetZoomFactor(min(current + 0.1, 3.0))
        except Exception:
            pass

    def zoom_out(self):
        if not self.is_zoom_ready():
            return
        try:
            self.browser.SetZoomType(wx.html2.WEBVIEW_ZOOM_TYPE_LAYOUT)
            current = self.browser.GetZoomFactor()
            self.browser.SetZoomFactor(max(current - 0.1, 0.5))
        except Exception:
            pass

    def zoom_reset(self):
        if not self.is_zoom_ready():
            return
        try:
            self.browser.SetZoomFactor(1.0)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Find in page
    # ------------------------------------------------------------------ #
    def find_text(self, term, match_case=False, whole_word=False, backwards=False):
        if self.is_webview():
            flags = 0
            if match_case:
                flags |= wx.html2.WEBVIEW_FIND_MATCH_CASE
            if whole_word:
                flags |= wx.html2.WEBVIEW_FIND_ENTIRE_WORD
            if backwards:
                flags |= wx.html2.WEBVIEW_FIND_BACKWARDS
            flags |= wx.html2.WEBVIEW_FIND_WRAP | wx.html2.WEBVIEW_FIND_HIGHLIGHT_RESULT
            try:
                result = self.browser.Find(term, flags)
            except Exception:
                return False
            return result != wx.NOT_FOUND
        return self._find_in_buffer(term, match_case, whole_word, backwards)

    def clear_find_highlight(self):
        if self.is_webview():
            try:
                self.browser.Find("")
            except Exception:
                pass

    def _find_in_buffer(self, term, match_case, whole_word, backwards):
        text = self.browser.GetValue()
        flags = 0 if match_case else re.IGNORECASE
        pattern_str = re.escape(term)
        if whole_word:
            pattern_str = r'\b' + pattern_str + r'\b'
        try:
            pattern = re.compile(pattern_str, flags)
        except re.error:
            return False
        matches = [m.span() for m in pattern.finditer(text)]
        if not matches:
            return False
        start_pos, end_pos = self.browser.GetSelection()
        if backwards:
            candidates = [m for m in matches if m[1] <= start_pos]
            span = candidates[-1] if candidates else matches[-1]
        else:
            candidates = [m for m in matches if m[0] >= end_pos]
            span = candidates[0] if candidates else matches[0]
        self.browser.SetSelection(span[0], span[1])
        self.browser.ShowPosition(span[0])
        return True

    # ------------------------------------------------------------------ #
    # Loading state / status bar plumbing (only the active tab drives the UI)
    # ------------------------------------------------------------------ #
    def _set_loading_ui(self, is_loading):
        self.loading = is_loading
        if is_loading:
            threading.Thread(target=play_sound, args=('select.ogg',), daemon=True).start()
            if self.owner.settings.getboolean('announcements', 'loading_messages'):
                threading.Thread(target=speak, args=(_("Ładowanie strony..."),), daemon=True).start()
        if self.is_active():
            self.owner.set_loading_state(is_loading)

    # ------------------------------------------------------------------ #
    # WebView (edge mode) events
    # ------------------------------------------------------------------ #
    def OnNavigating(self, event):
        url = event.GetURL()
        if downloads.should_download(url):
            event.Veto()
            self.owner.download_manager.start_download(url)
            self.owner.notify_download_started(url)
            return
        self.current_url = url
        self._set_loading_ui(True)

    def OnPageLoaded(self, event):
        self._webview_ready = True
        self._set_loading_ui(False)
        threading.Thread(target=play_sound, args=('ding.ogg',), daemon=True).start()

        title = self.browser.GetCurrentTitle()
        self.current_title = title or self.current_url
        try:
            self.current_url = self.browser.GetCurrentURL() or self.current_url
        except Exception:
            pass
        self.owner.notify_tab_changed(self)

        if self.owner.settings.getboolean('announcements', 'loading_messages'):
            threading.Thread(
                target=speak,
                args=(_("Załadowano stronę {}").format(title),),
                daemon=True).start()

        if self.owner.settings.getboolean('privacy', 'block_cookie_banners'):
            self.hide_cookie_banners_webview()

        if self.owner.settings.getboolean('announcements', 'announce_page_summary'):
            self.DisplayPageInfo()

        self.owner.history_store.add(self.current_url, self.current_title)
        self.owner.update_bookmark_star()
        if self.is_active():
            self.browser.SetFocus()

    def hide_cookie_banners_webview(self):
        """Hides any element whose id/class mentions "cookie"."""
        script = r"""
        var banners = document.querySelectorAll('[id*="cookie"], [class*="cookie"]');
        for (var i = 0; i < banners.length; i++) {
            banners[i].style.display = 'none';
        }
        """
        self.browser.RunScript(script)

    def OnTitleChanged(self, event):
        self.current_title = event.GetString()
        self.owner.notify_tab_changed(self)

    def OnNewWindow(self, event):
        url = event.GetURL()
        event.Veto()
        if url:
            self.owner.open_new_tab(url)

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
            self.refresh()
        elif keycode == wx.WXK_F6 or (ctrl_down and keycode == ord('L')):
            self.owner.focus_address()
        elif keycode == wx.WXK_ALT:
            # A bare Alt tap must not reach the default window proc, or it
            # enters Windows' native menu-tracking loop (SC_KEYMENU) and
            # freezes the WebView2-hosted page -- see web.py's OnCharHook.
            pass
        else:
            event.Skip()

    # ------------------------------------------------------------------ #
    # Virtual buffer: loading
    # ------------------------------------------------------------------ #
    def LoadVirtualBuffer(self, url):
        self._set_loading_ui(True)

        def load_content():
            try:
                response = requests.get(url, timeout=15)
                wx.CallAfter(self._process_html_response, response)
            except Exception as e:
                print(_("Błąd podczas ładowania strony: {}").format(e))
                wx.CallAfter(self.owner.statusbar.SetStatusText, _("Błąd podczas ładowania strony."))
                wx.CallAfter(self._set_loading_ui, False)

        threading.Thread(target=load_content, daemon=True).start()

    def _process_html_response(self, response):
        soup = BeautifulSoup(response.content, 'html.parser')
        self.current_soup = soup
        self.current_url = response.url

        if self.owner.settings.getboolean('privacy', 'block_cookie_banners'):
            cookie_divs = soup.find_all(lambda tag:
                ('cookie' in (tag.get('id') or '').lower()) or
                ('cookie' in ' '.join(tag.get('class', [])).lower()))
            for c in cookie_divs:
                c.decompose()

        self.render_content(soup)

        title_tag = soup.find('title')
        self.current_title = title_tag.get_text() if title_tag else response.url
        self.owner.notify_tab_changed(self)

        self._set_loading_ui(False)
        threading.Thread(target=play_sound, args=('ding.ogg',), daemon=True).start()
        if self.owner.settings.getboolean('announcements', 'loading_messages'):
            threading.Thread(target=speak, args=(_("Załadowano stronę"),), daemon=True).start()
        if self.owner.settings.getboolean('announcements', 'announce_page_summary'):
            self.DisplayPageInfo()

        if self.is_active():
            self.browser.SetFocus()

        self.owner.history_store.add(self.current_url, self.current_title)
        self.owner.update_bookmark_star()

    def DisplayPageInfo(self):
        if self.is_webview():
            script = """
            var forms = document.getElementsByTagName('form').length;
            var links = document.getElementsByTagName('a').length;
            var buttons = document.getElementsByTagName('button').length;
            var rows = document.getElementsByTagName('tr').length;
            var result = forms + ',' + links + ',' + buttons + ',' + rows;
            result;
            """
            success, result = self.browser.RunScript(script)
            if success and result:
                data = result.split(',')
                if len(data) == 4:
                    forms, links, buttons, rows = data
                    message = _("Strona zawiera {} pól formularza, {} łączy, {} przycisków i {} wierszy.").format(forms, links, buttons, rows)
                    threading.Thread(target=speak, args=(message,), daemon=True).start()
        else:
            if self.current_soup is not None:
                forms = len(self.current_soup.find_all('form'))
                links = len(self.current_soup.find_all('a'))
                buttons = len(self.current_soup.find_all('button'))
                rows = len(self.current_soup.find_all('tr'))
                message = _("Strona zawiera {} pól formularza, {} łączy, {} przycisków i {} wierszy.").format(forms, links, buttons, rows)
                threading.Thread(target=speak, args=(message,), daemon=True).start()

    # ------------------------------------------------------------------ #
    # Virtual buffer: interactive-element parsing
    # ------------------------------------------------------------------ #
    def get_label_for_input(self, input_element):
        if input_element.get('id'):
            label = self.current_soup.find('label', {'for': input_element['id']})
            if label:
                return label.get_text(strip=True)

        parent_label = input_element.find_parent('label')
        if parent_label:
            return ' '.join(parent_label.find_all(string=True, recursive=False)).strip()

        for attr in ['aria-label', 'placeholder', 'title', 'name']:
            if input_element.get(attr):
                return input_element.get(attr)

        return ''

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
            label = value or label or _("Przycisk bez etykiety")
            display_text = _("Przycisk: {}").format(label)

        elif input_type in ['checkbox', 'radio']:
            element_type = input_type
            is_checked = child.has_attr('checked')
            state = _("zaznaczone") if is_checked else _("niezaznaczone")
            if input_type == 'checkbox':
                display_text = _("Pole wyboru: {} ({})").format(label, state)
            else:  # radio
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

    def render_content(self, soup):
        self.browser.Freeze()
        self.browser.Clear()
        self.interactive_elements = []
        self._cursor_index = -1

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
                    self.parse_element(child)

    def _restore_cursor_to_tag(self, tag):
        for i, el in enumerate(self.interactive_elements):
            if el['tag'] is tag:
                self._cursor_index = i
                return

    def _describe_element(self, element):
        etype = element['type']
        label = element['label']
        tag = element['tag']
        if etype == 'link':
            return _("Łącze: {}").format(label)
        if etype == 'button':
            return _("Przycisk: {}").format(label)
        if etype == 'input_text':
            value = tag.get('value', '')
            text = _("Pole edycji: {}").format(label)
            if value:
                text += _(", Wartość: {}").format(value)
            return text
        if etype == 'textarea':
            value = ''.join(tag.stripped_strings)
            text = _("Pole tekstowe: {}").format(label)
            if value:
                text += _(", Wartość: {}").format(value)
            return text
        if etype in ('checkbox', 'radio'):
            state = _("zaznaczone") if tag.has_attr('checked') else _("niezaznaczone")
            kind = _("Pole wyboru") if etype == 'checkbox' else _("Przycisk radiowy")
            return "{}: {} ({})".format(kind, label, state)
        return label

    # ------------------------------------------------------------------ #
    # Virtual buffer: real keyboard-driven interactivity (virtual cursor)
    # ------------------------------------------------------------------ #
    def MoveCursor(self, delta):
        if not self.interactive_elements:
            speak(_("Brak elementów interaktywnych na stronie."))
            return
        if self._cursor_index == -1:
            self._cursor_index = 0 if delta >= 0 else len(self.interactive_elements) - 1
        else:
            self._cursor_index = (self._cursor_index + delta) % len(self.interactive_elements)
        element = self.interactive_elements[self._cursor_index]
        self.browser.SetSelection(element['start'], element['end'])
        self.browser.ShowPosition(element['start'])
        speak(self._describe_element(element))

    def ActivateElement(self, element, new_tab=False):
        element_type = element.get('type')
        if element_type == 'link':
            base_url = self.get_url()
            href = element['tag'].get('href', '')
            full_url = requests.compat.urljoin(base_url, href)
            if new_tab:
                self.owner.open_new_tab(full_url)
            else:
                self.load(full_url)
        elif element_type == 'button':
            self.SubmitForm(element['tag'])
        elif element_type in ('input_text', 'textarea'):
            self.EditTextElement(element)
        elif element_type in ('checkbox', 'radio'):
            self.ToggleCheckElement(element)

    def OnTextCtrlClick(self, event):
        position = self.browser.HitTestPos(event.GetPosition())
        # Search from last to first because elements can be nested.
        for i in reversed(range(len(self.interactive_elements))):
            element = self.interactive_elements[i]
            if element['start'] <= position <= element['end']:
                self._cursor_index = i
                # Ctrl+click a link opens it in a new tab, matching every
                # other browser's convention.
                self.ActivateElement(element, new_tab=event.ControlDown())
                return
        event.Skip()

    def OnTextCtrlKeyDown(self, event):
        keycode = event.GetKeyCode()
        shift_down = event.ShiftDown()
        ctrl_down = event.ControlDown()
        if keycode == wx.WXK_TAB:
            self.MoveCursor(-1 if shift_down else 1)
        elif keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE) and self._cursor_index != -1:
            self.ActivateElement(self.interactive_elements[self._cursor_index], new_tab=ctrl_down)
        elif keycode == wx.WXK_F6 or (ctrl_down and keycode == ord('L')):
            self.owner.focus_address()
        else:
            event.Skip()

    def EditTextElement(self, element):
        tag = element['tag']
        current_value = ''
        if element['type'] == 'textarea':
            current_value = ''.join(tag.stripped_strings)
        else:  # input_text
            current_value = tag.get('value', '')

        dlg = wx.TextEntryDialog(self, _("Wprowadź tekst dla: {}").format(element['label']), _("Edycja pola"), current_value)

        if dlg.ShowModal() == wx.ID_OK:
            new_value = dlg.GetValue()
            if element['type'] == 'textarea':
                tag.clear()
                tag.append(new_value)
            else:  # input_text
                tag['value'] = new_value

            self.render_content(self.current_soup)
            self._restore_cursor_to_tag(tag)
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
            if not tag.has_attr('checked'):
                name = tag.get('name')
                if name:
                    form = tag.find_parent('form')
                    search_root = form if form else self.current_soup
                    radios = search_root.find_all('input', {'type': 'radio', 'name': name})
                    for r in radios:
                        if r.has_attr('checked'):
                            del r['checked']
                tag['checked'] = 'checked'

        self.render_content(self.current_soup)
        self._restore_cursor_to_tag(tag)
        new_state = _("zaznaczone") if tag.has_attr('checked') else _("niezaznaczone")
        speak(_("{} {}").format(element['label'], new_state))

    # ------------------------------------------------------------------ #
    # Virtual buffer: real form submission (button activation)
    # ------------------------------------------------------------------ #
    def SubmitForm(self, button_tag):
        form = button_tag.find_parent('form')
        if form is None:
            wx.MessageBox(_("Ten przycisk nie należy do żadnego formularza."),
                          _("Informacja"), wx.OK | wx.ICON_INFORMATION)
            return

        method = (form.get('method') or 'get').strip().lower()
        action = form.get('action') or self.get_url()
        action_url = requests.compat.urljoin(self.get_url(), action)

        data = []
        for field in form.find_all(['input', 'textarea', 'select']):
            name = field.get('name')
            if not name:
                continue
            if field.name == 'input':
                ftype = (field.get('type') or 'text').lower()
                if ftype in ('checkbox', 'radio'):
                    if field.has_attr('checked'):
                        data.append((name, field.get('value', 'on')))
                elif ftype in ('submit', 'reset', 'button'):
                    if field is button_tag:
                        data.append((name, field.get('value', '')))
                else:
                    data.append((name, field.get('value', '')))
            elif field.name == 'textarea':
                data.append((name, ''.join(field.stripped_strings)))
            elif field.name == 'select':
                selected = field.find('option', selected=True) or field.find('option')
                if selected is not None:
                    data.append((name, selected.get('value', selected.get_text(strip=True))))

        self._set_loading_ui(True)
        if self.is_active():
            self.owner.statusbar.SetStatusText(_("Wysyłanie formularza..."))

        def do_submit():
            try:
                if method == 'post':
                    response = requests.post(action_url, data=data, timeout=15)
                else:
                    response = requests.get(action_url, params=data, timeout=15)
                wx.CallAfter(self._process_html_response, response)
            except Exception as e:
                print(_("Błąd podczas wysyłania formularza: {}").format(e))
                wx.CallAfter(self.owner.statusbar.SetStatusText, _("Błąd podczas wysyłania formularza."))
                wx.CallAfter(self._set_loading_ui, False)

        threading.Thread(target=do_submit, daemon=True).start()

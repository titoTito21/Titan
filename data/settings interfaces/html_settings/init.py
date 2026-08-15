# -*- coding: utf-8 -*-
"""
Titan's settings as a web page - the proof that an interface needs to know
nothing about what a setting is.

There is not one setting named anywhere in this file.  Everything it draws
comes from `api.categories()`, which Titan reads out of its own settings
window, so this page has every category (including the ones components
registered at run time), every control, every label in the user's language
and every live list of choices - and a setting added to Titan tomorrow
appears here with this file unchanged.

How the page talks back: it never posts anywhere.  Every control's change
handler sets `location.href` to `titan:set?item=<id>&value=<value>`, and the
Python side answers `EVT_WEBVIEW_NAVIGATING`, vetoes the navigation and does
the work.  Deliberately the oldest trick there is, because it works on every
WebView backend wxPython can be built with, needs no script-message bridge
and no local server, and cannot be reached by anything but this page.
"""

import urllib.parse

import wx

try:
    import wx.html2 as webview
except Exception:                                     # pragma: no cover
    webview = None

try:
    from src.titan_core.translation import _
except Exception:                                     # pragma: no cover
    def _(text):
        return text


SCHEME = 'titan:'


class HtmlSettingsFrame(wx.Frame):
    """One window, one page, every setting Titan has."""

    def __init__(self, api, parent=None):
        super().__init__(parent, title=_("Settings"), size=(900, 700))
        self.api = api
        self.browser = webview.WebView.New(self)
        self.browser.Bind(webview.EVT_WEBVIEW_NAVIGATING, self._on_navigating)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.render()

    # -- drawing ---------------------------------------------------------
    def render(self):
        self.browser.SetPage(self._page(), '')

    def _page(self):
        categories = self.api.categories()
        parts = [_HEAD.replace('__SEARCH__', _("Search settings"))
                 .replace('__SAVE__', _("Save"))
                 .replace('__CANCEL__', _("Cancel"))
                 .replace('__TITLE__', _("Titan settings"))]
        parts.append('<nav aria-label="%s"><ul>' % _("Categories"))
        for category in categories:
            parts.append('<li><a href="#%s">%s</a></li>'
                         % (_slug(category['name']), _escape(category['name'])))
        parts.append('</ul></nav>')
        for category in categories:
            parts.append('<section id="%s"><h2>%s</h2>'
                         % (_slug(category['name']),
                            _escape(category['name'])))
            for item in category['items']:
                parts.append(_control(item))
            parts.append('</section>')
        parts.append(_FOOT)
        return '\n'.join(parts)

    # -- listening -------------------------------------------------------
    def _on_navigating(self, event):
        url = event.GetURL() or ''
        if not url.startswith(SCHEME):
            return
        # Nothing this page asks for is a navigation; every one of them is a
        # message to Python.
        event.Veto()
        query = urllib.parse.urlparse(url)
        arguments = urllib.parse.parse_qs(query.query)
        command = query.path.strip('/') or query.netloc
        first = lambda name: (arguments.get(name) or [''])[0]

        if command == 'set':
            item_id = first('item')
            value = first('value')
            # A tick-list answers with its ticked options, one per line -
            # the page cannot send a list and the model wants one.
            described = self.api.get(item_id)
            if isinstance(described, list):
                value = [line for line in value.splitlines() if line]
            self.api.set(item_id, value)
        elif command == 'press':
            self.api.press(first('item'))
            wx.CallAfter(self.render)
        elif command == 'save':
            if self.api.save():
                self.api.speak(_("Settings have been saved."))
            self.Close()
        elif command == 'cancel':
            self.Close()

    def _on_close(self, event):
        self.api.cancel()
        event.Skip()
        self.Destroy()


def _escape(text):
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _slug(text):
    return 'c' + ''.join(character if character.isalnum() else '_'
                         for character in str(text))


def _control(item):
    """One setting as HTML - by what the control IS, never by its name."""
    kind = item['kind']
    identifier = _escape(item['id'])
    label = _escape(item['label'])
    disabled = '' if item.get('enabled', True) else ' disabled'
    send = "titanSet('%s', this)" % identifier

    if kind == 'bool':
        checked = ' checked' if item['value'] else ''
        return ('<p><label><input type="checkbox" id="%s"%s%s '
                'onchange="%s"> %s</label></p>'
                % (identifier, checked, disabled, send, label))
    if kind in ('choice', 'list'):
        options = []
        for option in item['options']:
            selected = ' selected' if option == item['value'] else ''
            options.append('<option%s>%s</option>'
                           % (selected, _escape(option)))
        return ('<p><label for="%s">%s</label><br>'
                '<select id="%s"%s onchange="%s">%s</select></p>'
                % (identifier, label, identifier, disabled, send,
                   ''.join(options)))
    if kind == 'number':
        return ('<p><label for="%s">%s</label><br>'
                '<input type="number" id="%s" value="%s" min="%s" max="%s"%s '
                'onchange="%s"></p>'
                % (identifier, label, identifier, _escape(item['value']),
                   _escape(item.get('minimum')), _escape(item.get('maximum')),
                   disabled, send))
    if kind in ('text', 'secret'):
        field = 'password' if kind == 'secret' else 'text'
        return ('<p><label for="%s">%s</label><br>'
                '<input type="%s" id="%s" value="%s"%s onchange="%s"></p>'
                % (identifier, label, field, identifier,
                   _escape(item['value'] or ''), disabled, send))
    if kind == 'multi':
        chosen = set(item['value'] or [])
        boxes = []
        for index, option in enumerate(item['options']):
            checked = ' checked' if option in chosen else ''
            boxes.append('<label><input type="checkbox" name="%s" value="%s"%s '
                         'onchange="titanSetMulti(\'%s\')"> %s</label><br>'
                         % (identifier, _escape(option), checked, identifier,
                            _escape(option)))
        return ('<fieldset><legend>%s</legend>%s</fieldset>'
                % (label, ''.join(boxes)))
    if kind == 'command':
        return ('<p><button type="button" onclick="titanPress(\'%s\')"%s>%s'
                '</button></p>' % (identifier, disabled, label))
    if kind == 'info':
        return '<p class="info"><strong>%s</strong><br>%s</p>' % (
            label, _escape(item['value'] or ''))
    return ''


_HEAD = """<!doctype html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
 body { font-family: sans-serif; margin: 0 auto; max-width: 52rem;
        padding: 1rem 2rem; line-height: 1.5; }
 h1 { font-size: 1.6rem; }
 h2 { font-size: 1.2rem; margin-top: 2rem; border-bottom: 1px solid #ccc; }
 nav ul { list-style: none; padding: 0; display: flex; flex-wrap: wrap;
          gap: .5rem 1rem; }
 label { font-weight: 500; }
 input, select, button { font-size: 1rem; padding: .25rem; }
 input[type=text], input[type=password], select { min-width: 22rem; }
 .info { background: #f4f4f4; padding: .5rem; }
 .bar { position: sticky; top: 0; background: inherit; padding: .5rem 0;
        border-bottom: 1px solid #ccc; }
 @media (prefers-color-scheme: dark) {
   body { background: #1b1b1b; color: #eee; }
   .info { background: #2a2a2a; }
   input, select, button { background: #2a2a2a; color: #eee;
                           border: 1px solid #555; }
 }
</style>
<script>
 function titanGo(url) { window.location.href = url; }
 function titanValue(control) {
   if (control.type === 'checkbox') { return control.checked ? 'true' : 'false'; }
   return control.value;
 }
 function titanSet(id, control) {
   titanGo('titan:set?item=' + encodeURIComponent(id) +
           '&value=' + encodeURIComponent(titanValue(control)));
 }
 function titanSetMulti(id) {
   var boxes = document.getElementsByName(id);
   var chosen = [];
   for (var i = 0; i < boxes.length; i++) {
     if (boxes[i].checked) { chosen.push(boxes[i].value); }
   }
   titanGo('titan:set?item=' + encodeURIComponent(id) +
           '&value=' + encodeURIComponent(chosen.join('\n')));
 }
 function titanPress(id) {
   titanGo('titan:press?item=' + encodeURIComponent(id));
 }
 function titanFilter(text) {
   var needle = text.toLowerCase();
   var sections = document.getElementsByTagName('section');
   for (var s = 0; s < sections.length; s++) {
     var any = false;
     var rows = sections[s].querySelectorAll('p, fieldset');
     for (var r = 0; r < rows.length; r++) {
       var hit = !needle || rows[r].textContent.toLowerCase().indexOf(needle) >= 0;
       rows[r].style.display = hit ? '' : 'none';
       any = any || hit;
     }
     sections[s].style.display = any ? '' : 'none';
   }
 }
</script>
</head><body>
<h1>__TITLE__</h1>
<div class="bar">
 <label for="q">__SEARCH__</label>
 <input type="search" id="q" oninput="titanFilter(this.value)">
 <button type="button" onclick="titanGo('titan:save')">__SAVE__</button>
 <button type="button" onclick="titanGo('titan:cancel')">__CANCEL__</button>
</div>
"""

_FOOT = "</body></html>"


def open_settings(api):
    """What makes this folder a settings interface."""
    if webview is None:
        api.log("wx.html2 is not available in this build")
        return None
    frame = HtmlSettingsFrame(api, api.parent())
    frame.Show()
    frame.Raise()
    return frame

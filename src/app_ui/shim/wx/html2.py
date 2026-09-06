# -*- coding: utf-8 -*-
"""A web view, as an interface made of controls can have one.

**A browser engine cannot be a list of controls, but a PAGE can be.** The
application asked for `wx.html2.WebView` and got a refusal, which left
tWeb - a browser, and the one application whose whole interface this is -
readable only by looking at its real window. But what a person wants out
of a browser is the page, and a page is text with links in it, which every
interface here can carry.

So this is a real WebView as far as the application is concerned - it
navigates, it reports where it is and what the page is called, its events
fire - and what it DESCRIBES is the page as readable text plus the address
it came from. An interface that knows nothing about the web still gets a
document to read; one that does can offer the address to its own browser.

What is honestly given up: anything the page does. There is no script, no
form to fill in on the page itself, no video. `RunScript` answers nothing
rather than pretending, and the application is told so.
"""

import re
import sys

from . import _titan_runtime
from . import model  # noqa: F401  (re-exported for the describing side)

RUNTIME = _titan_runtime.RUNTIME

#: Long enough for a page, short enough that a dead host does not hold the
#: application. The application's own thread is waiting on this.
TIMEOUT = 12.0

#: More than anybody reads in one go, and a ceiling on what crosses the
#: wire as one control.
MAX_TEXT = 200000

WEBVIEW_ZOOM_TYPE_LAYOUT = 1
WEBVIEW_ZOOM_TYPE_TEXT = 0
WEBVIEW_FIND_WRAP = 1
WEBVIEW_FIND_ENTIRE_WORD = 2
WEBVIEW_FIND_MATCH_CASE = 4
WEBVIEW_FIND_HIGHLIGHT_RESULT = 8
WEBVIEW_FIND_BACKWARDS = 16
WEBVIEW_BACKEND_DEFAULT = 'default'


def _shim():
    return sys.modules['wx']


class WebView(object):
    """What `wx.html2.WebView.New` hands back."""

    @classmethod
    def New(cls, parent=None, *_a, **_k):
        return cls(parent)

    @classmethod
    def IsBackendAvailable(cls, _backend=None):
        return True

    def __init__(self, parent=None, *_a, **_k):
        shim = _shim()
        # A real widget of the shim's own, so it is described, focused and
        # destroyed like every other control on the screen.
        self._widget = shim.TextCtrl(parent, shim.ID_ANY, '',
                                     style=shim.TE_MULTILINE | shim.TE_READONLY)
        self._widget.SetName('Page')
        self._url = ''
        self._title = ''
        self._html = ''
        self._history = []
        self._forward = []
        RUNTIME.refuse('wx.html2',
                       'a page is shown as its text; nothing on it runs')

    # ---------------------------------------------------------- navigating
    def LoadURL(self, url):
        url = str(url or '').strip()
        if not url:
            return
        if self._url and self._url != url:
            self._history.append(self._url)
            self._forward = []
        self._fetch(url)

    def SetPage(self, html, base_url=''):
        self._html = str(html or '')
        self._url = str(base_url or self._url)
        self._show(self._html)

    def _fetch(self, url):
        if '://' not in url:
            url = 'http://' + url
        self._url = url
        try:
            import urllib.request
            request = urllib.request.Request(url, headers={
                # A page answers 403 to a client with no name, and reads
                # to the user as a page that is not there.
                'User-Agent': 'Mozilla/5.0 (compatible; Titan)'})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
                raw = answer.read(4 * 1024 * 1024)
                charset = 'utf-8'
                try:
                    charset = answer.headers.get_content_charset() or 'utf-8'
                except Exception:
                    pass
            self._html = raw.decode(charset, 'replace')
        except Exception as error:
            self._html = ''
            self._title = url
            self._widget.SetValue('This page could not be read: %s: %s'
                                  % (type(error).__name__, error))
            self._fire('ERROR')
            return
        self._show(self._html)

    def _show(self, html):
        self._title = _title_of(html) or self._url
        self._widget.SetName(self._title or 'Page')
        self._widget.SetValue(readable(html)[:MAX_TEXT])
        self._widget._url = self._url
        self._fire('LOADED')

    def _fire(self, name):
        shim = _shim()
        kind = getattr(shim, 'EVT_WEBVIEW_%s' % name, None)
        if kind is None:
            return
        try:
            self._widget._fire(kind)
        except Exception:
            pass

    def GoBack(self):
        if self._history:
            self._forward.append(self._url)
            self._fetch(self._history.pop())

    def GoForward(self):
        if self._forward:
            self._history.append(self._url)
            self._fetch(self._forward.pop())

    def CanGoBack(self):
        return bool(self._history)

    def CanGoForward(self):
        return bool(self._forward)

    def Reload(self, *_a, **_k):
        if self._url:
            self._fetch(self._url)

    def Stop(self):
        return None

    # ------------------------------------------------------------- asking
    def GetCurrentURL(self):
        return self._url

    def GetCurrentTitle(self):
        return self._title

    def GetPageText(self):
        return self._widget.GetValue()

    def GetPageSource(self):
        return self._html

    def IsBusy(self):
        return False

    def Find(self, text, _flags=0):
        where = self._widget.GetValue().lower().find(str(text or '').lower())
        return where

    def RunScript(self, *_a, **_k):
        """**Nothing on the page runs, and the application is told.** A
        script that silently did nothing would be worse than one that
        says it cannot: an application checking the answer finds out."""
        RUNTIME.refuse('wx.html2.RunScript',
                       'nothing on the page runs; only its text is here')
        return False

    def SetZoomFactor(self, *_a, **_k):
        return None
    SetZoomType = SetZoom = SetZoomFactor
    EnableContextMenu = EnableHistory = ClearHistory = SetZoomFactor
    SetEditable = SelectAll = SetPage2 = SetZoomFactor

    # Everything a wx control is asked, handed to the real one underneath.
    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self._widget, name)


def _title_of(html):
    found = re.search(r'<title[^>]*>(.*?)</title>', html or '',
                      re.I | re.S)
    return _unescape(re.sub(r'\s+', ' ', found.group(1)).strip()) if found else ''


#: Whole elements whose CONTENT is not the page.
_SILENT = re.compile(r'<(script|style|noscript|template|svg)[^>]*>.*?</\1>',
                     re.I | re.S)
#: Where a line break really belongs.
_BREAKS = re.compile(r'</(p|div|li|tr|h[1-6]|section|article|header|footer|'
                     r'blockquote|pre)\s*>|<br\s*/?>', re.I)


def readable(html):
    """A page as the text somebody would read out of it.

    Deliberately small: the whole point is that the application already
    fetched the page and the interface only needs its words. A heading, a
    paragraph and a list item each end a line; everything else is taken
    out. A link keeps its text - the address is on the control, not
    scattered through the words.
    """
    text = _SILENT.sub(' ', html or '')
    text = _BREAKS.sub('\n', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = _unescape(text)
    lines = [re.sub(r'[ \t\r\f\v]+', ' ', line).strip()
             for line in text.split('\n')]
    out, blank = [], False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif not blank and out:
            out.append('')
            blank = True
    return '\n'.join(out).strip()


def _unescape(text):
    try:
        import html as _html
        return _html.unescape(text)
    except Exception:
        return text


def __getattr__(name):
    """The rest of `wx.html2` - events and flags - answered rather than
    raised, as everywhere else in this shim."""
    shim = _shim()
    RUNTIME.note_unknown('wx.html2.%s' % name)
    if name.startswith('EVT_'):
        return shim._EventKind(name[4:])
    if name.isupper() or name.startswith(('WEBVIEW_', 'ID_')):
        return shim._Unknown(0)
    if name[:1].isupper():
        return shim._UnknownClass
    return shim._Silence(name)

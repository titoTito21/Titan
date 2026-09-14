# -*- coding: utf-8 -*-
"""Braille: a control shown in cells, and sent to a display.

The last thing a reader with voice classes and a sound scheme was missing.
JAWS shows a control in braille as well as saying it - "btn Save", a check
box as its state and no type word - and a speech scheme already carries HOW
(`portable/speechSchemes.py`, the braille half): which parts are shown, and
what the type is abbreviated to. This is the other end of it, for the reader
that had no braille at all.

Three layers, and each degrades to the one below rather than to nothing:

* **The translation is liblouis'**, the library every screen reader uses.
  It is BUNDLED in this component's ``lib`` (``liblouis.dll`` and
  ``lib/louis/tables``) and read from there FIRST - a feature may require
  Titan but never Titan Access, and Titan Access requires nothing outside
  its own folder - with an installed NVDA's copy as a fall-back only.
  The table is Titan's language in braille, computer (8-dot) by default,
  with the grade tables the user's copy carries offered. The output is
  Unicode braille (U+2800..U+28FF), which is both what a viewer shows and,
  low byte, what a display's cells are.
* **The display is BrlAPI's**, BRLTTY's own protocol - the one way to reach
  a braille display from outside a reader without writing a driver per
  device, and what BRLTTY exposes for exactly this. Reached by ctypes when
  BRLTTY is running; absent otherwise, and then:
* **The viewer** is a window of Titan's own showing the cells as Unicode
  braille and the text beneath them, so braille WORKS with no hardware at
  all - which is how it is developed, tested and read on this machine.

Nothing here is on the focus path but a dictionary lookup and one liblouis
call on a short string; the translation of a control is a few milliseconds
and the result is not cached because a control's state changes under it.
"""

import ctypes
import os
import threading

from .localization import translate as _

_LOCK = threading.RLock()
_state = {
    'dll': None, 'why': '', 'data_path': '', 'char_size': 4,
    'shown': 0, 'sent': 0, 'translated': 0, 'failed': 0,
}

#: liblouis translation flags: dotsIO | ucBrl - answer Unicode braille
#: cells rather than the table's own output characters, so a cell is a
#: code point in U+2800..U+28FF whatever the table.
_DOTS_IO = 4
_UC_BRL = 0x40
_MODE = _DOTS_IO | _UC_BRL

#: Where NVDA keeps liblouis and its tables, and this component's own copy.
def _dll_candidates():
    here = os.path.dirname(os.path.abspath(__file__))
    lib = os.path.join(os.path.dirname(here), 'lib')
    found = [os.path.join(lib, 'liblouis.dll')]
    program = os.environ.get('ProgramFiles', r'C:\Program Files')
    found.append(os.path.join(program, 'NVDA', 'liblouis.dll'))
    return found


def _table_dirs():
    dirs = []
    here = os.path.dirname(os.path.abspath(__file__))
    dirs.append(os.path.join(os.path.dirname(here), 'lib', 'louis', 'tables'))
    program = os.environ.get('ProgramFiles', r'C:\Program Files')
    dirs.append(os.path.join(program, 'NVDA', 'louis', 'tables'))
    return [one for one in dirs if os.path.isdir(one)]


#: Titan's language -> the tables that suit it, most specific first. The
#: name is the file in the tables folder; the first that exists is used.
LANGUAGE_TABLES = {
    'pl': ('pl-pl-comp8.ctb', 'Pl-Pl-g1.utb', 'pl.tbl'),
    'en': ('en-us-comp8.ctb', 'en-us-g2.ctb', 'en-gb-comp8.ctb'),
    'de': ('de-g0.utb', 'de-g1.ctb', 'de-comp8.ctb'),
    'fr': ('fr-bfu-comp8.utb', 'fr-bfu-g2.ctb'),
    'es': ('es-g1.ctb',),
    'ru': ('ru-comp8.utb', 'ru.ctb'),
    'it': ('it-comp8.utb',),
}
DEFAULT_TABLES = ('en-us-comp8.ctb', 'unicode.dis')


def report():
    with _LOCK:
        out = dict(_state)
    out['dll'] = out['dll'] is not None
    out['available'] = out['dll']
    try:
        out['display'] = _display().connected()
    except Exception:                                # noqa: BLE001
        out['display'] = False
    return out


# --------------------------------------------------------------------------- #
# liblouis
# --------------------------------------------------------------------------- #
def _load():
    with _LOCK:
        if _state['dll'] is not None:
            return _state['dll']
        if _state['why']:
            return None
    for path in _dll_candidates():
        if not os.path.isfile(path):
            continue
        try:
            dll = ctypes.CDLL(path)
            dll.lou_version.restype = ctypes.c_char_p
            dll.lou_charSize.restype = ctypes.c_int
            size = int(dll.lou_charSize())
            dll.lou_translateString.argtypes = [
                ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        except Exception as error:                   # noqa: BLE001
            with _LOCK:
                _state['why'] = '%s: %s' % (path, error)
            continue
        with _LOCK:
            _state['dll'] = dll
            _state['char_size'] = size
            _state['why'] = ''
        return dll
    with _LOCK:
        if not _state['why']:
            _state['why'] = 'liblouis.dll was not found'
    return None


def available():
    return _load() is not None


def _cell_type():
    return ctypes.c_uint16 if _state['char_size'] == 2 else ctypes.c_uint32


def _table_for(language=None):
    """The full path of the braille table for a language, or the default.

    A user's choice (the Braille section, `Table`) wins; then the
    language's own tables; then the default. Answered as a path so
    liblouis resolves it whatever the working directory.
    """
    dirs = _table_dirs()

    def resolve(name):
        for folder in dirs:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
        return ''

    chosen = str(_setting('Table', '') or '').strip()
    if chosen:
        path = resolve(chosen) or (chosen if os.path.isfile(chosen) else '')
        if path:
            return path
    language = str(language or _language()).lower().split('-')[0].split('_')[0]
    for name in LANGUAGE_TABLES.get(language, ()):
        path = resolve(name)
        if path:
            return path
    for name in DEFAULT_TABLES:
        path = resolve(name)
        if path:
            return path
    return ''


def translate(text, language=None):
    """``text`` as a Unicode-braille string, or the text unchanged.

    Unchanged - never empty - is the safe answer: a display shows the
    letters it can and a viewer the text, which beats an empty line when
    liblouis or its table is missing.
    """
    text = str(text or '')
    if not text.strip():
        return text
    dll = _load()
    table = _table_for(language)
    if dll is None or not table:
        return text
    cell = _cell_type()
    length = len(text)
    inbuf = (cell * length)(*[ord(char) for char in text])
    inlen = ctypes.c_int(length)
    outcap = max(64, length * 4)
    outbuf = (cell * outcap)()
    outlen = ctypes.c_int(outcap)
    try:
        ok = dll.lou_translateString(
            table.encode('utf-8'), inbuf, ctypes.byref(inlen),
            outbuf, ctypes.byref(outlen), None, None, _MODE)
    except Exception:                                # noqa: BLE001
        ok = 0
    if not ok:
        with _LOCK:
            _state['failed'] += 1
        return text
    with _LOCK:
        _state['translated'] += 1
    return ''.join(chr(outbuf[i]) for i in range(outlen.value))


def cells_of(braille):
    """The dot bytes of a Unicode-braille string - what a display shows,
    one byte per cell (0..255)."""
    return bytes((ord(char) - 0x2800) & 0xFF if 0x2800 <= ord(char) <= 0x28FF
                 else 0 for char in str(braille or ''))


# --------------------------------------------------------------------------- #
# A control, presented
# --------------------------------------------------------------------------- #
def line_for(obj, kind=None):
    """The braille LINE for a control - the words, in the scheme's braille
    order, with the type abbreviated as the scheme says.

    Built out of the same parts the speech does, so what is on the display
    matches what was said, and shaped by the speech scheme's braille rule
    (`speechSchemes.braille_for`): which parts, and the type's own
    abbreviation. NVDA writes the abbreviation before the name ("btn
    Save"); this does the same.
    """
    parts = _parts_of(obj)
    if kind is None:
        kind = _kind_of(obj)
    rule = _braille_rule(kind)
    wanted = rule.get('parts') or ['name', 'kind', 'state', 'value']
    abbreviation = rule.get('kind')
    pieces = []
    for part in wanted:
        if part == 'kind':
            if abbreviation == '':
                continue
            word = abbreviation if abbreviation else parts.get('kind', '')
            if word:
                pieces.append(word)
        else:
            value = parts.get(part, '')
            if value:
                pieces.append(value)
    return ' '.join(piece for piece in pieces if piece).strip()


def _parts_of(obj):
    """``{'name','kind','state','value'}`` for a control, in words.

    Read the way both readers read a control, so the braille says what the
    voice said. Kept forgiving: a missing piece is '' and never an error.
    """
    out = {'name': '', 'kind': '', 'state': '', 'value': ''}
    try:
        out['name'] = str(getattr(obj, 'name', '') or '').strip()
    except Exception:                                # noqa: BLE001
        pass
    try:
        from . import accessible
        out['kind'] = str(accessible.role_label(getattr(obj, 'role', ''))
                          or '').strip()
    except Exception:                                # noqa: BLE001
        out['kind'] = str(getattr(obj, 'role', '') or '').strip()
    try:
        states = getattr(obj, 'states', None) or ()
        out['state'] = ' '.join(str(one) for one in states).strip()
    except Exception:                                # noqa: BLE001
        pass
    try:
        value = str(getattr(obj, 'value', '') or '').strip()
        if value and value != out['name']:
            out['value'] = value
    except Exception:                                # noqa: BLE001
        pass
    return out


def _kind_of(obj):
    try:
        from .portable import speechSchemes
        return speechSchemes.kind_of(getattr(obj, 'role', None))
    except Exception:                                # noqa: BLE001
        return 'other'


def _braille_rule(kind):
    try:
        from .portable import speechSchemes
        return speechSchemes.braille_for(kind)
    except Exception:                                # noqa: BLE001
        return {'parts': ['name', 'kind', 'state', 'value'], 'kind': None}


# --------------------------------------------------------------------------- #
# Showing it
# --------------------------------------------------------------------------- #
def show_object(obj):
    """Put a control on the braille display and in the viewer. Answers the
    braille line, or '' when braille is switched off."""
    if not _wanted():
        return ''
    line = line_for(obj)
    return _show_line(line)


def show_text(text):
    if not _wanted():
        return ''
    return _show_line(str(text or ''))


def _show_line(line):
    braille = translate(line)
    with _LOCK:
        _state['shown'] += 1
    display = _display()
    try:
        if display.connected() and display.write(braille):
            with _LOCK:
                _state['sent'] += 1
    except Exception:                                # noqa: BLE001
        pass
    if _viewer_wanted():
        try:
            _viewer().show(braille, line)
        except Exception:                            # noqa: BLE001
            pass
    return line


# --------------------------------------------------------------------------- #
# The display (BrlAPI)
# --------------------------------------------------------------------------- #
_display_singleton = {'it': None}


def _display():
    with _LOCK:
        if _display_singleton['it'] is None:
            _display_singleton['it'] = _BrlApiDisplay()
        return _display_singleton['it']


class _BrlApiDisplay:
    """A braille display through BRLTTY's BrlAPI, by ctypes.

    BrlAPI is BRLTTY's own client protocol - a running BRLTTY owns the
    device and Titan Access borrows it, which is the one way to reach a
    display from outside a reader without a driver per device. It is opened
    lazily, its failure is silent (there is usually no BRLTTY, and the
    viewer stands in), and it is only ever asked to write a line.
    """

    def __init__(self):
        self._dll = None
        self._handle = None
        self._cells = 0
        self._tried = False

    def _library(self):
        if self._dll is not None or self._tried:
            return self._dll
        self._tried = True
        for name in ('brlapi-0.8.dll', 'brlapi-0.7.dll', 'brlapi-0.6.dll',
                     'brlapi.dll', 'libbrlapi.so.0.8', 'libbrlapi.so'):
            try:
                self._dll = ctypes.CDLL(name)
                return self._dll
            except Exception:                        # noqa: BLE001
                continue
        return None

    def connected(self):
        return self._handle is not None and self._cells > 0

    def _open(self):
        dll = self._library()
        if dll is None:
            return False
        try:
            size = int(dll.brlapi_getHandleSize())
            self._handle = ctypes.create_string_buffer(size)
            fd = dll.brlapi__openConnection(self._handle, None, None)
            if fd < 0:
                self._handle = None
                return False
            x = ctypes.c_uint()
            y = ctypes.c_uint()
            dll.brlapi__getDisplaySize(self._handle, ctypes.byref(x),
                                       ctypes.byref(y))
            self._cells = int(x.value) or 40
            dll.brlapi__enterTtyMode(self._handle, -1, None)
            return True
        except Exception:                            # noqa: BLE001
            self._handle = None
            return False

    def write(self, braille):
        if not self.connected() and not self._open():
            return False
        dll = self._library()
        try:
            text = str(braille or '')[:self._cells].ljust(self._cells)
            return dll.brlapi__writeText(
                self._handle, 0, text.encode('utf-8')) >= 0
        except Exception:                            # noqa: BLE001
            self._handle = None
            return False


# --------------------------------------------------------------------------- #
# The viewer
# --------------------------------------------------------------------------- #
_viewer_singleton = {'it': None}


def _viewer():
    with _LOCK:
        if _viewer_singleton['it'] is None:
            _viewer_singleton['it'] = _Viewer()
        return _viewer_singleton['it']


class _Viewer:
    """A window that shows the cells as Unicode braille and the text under
    them, so braille works with no display at all - and is how it is read
    and tested here.  Built on the GUI thread the first time it is shown."""

    def __init__(self):
        self._frame = None

    def show(self, braille, text):
        try:
            import wx
        except Exception:                            # noqa: BLE001
            return False

        def put():
            try:
                if self._frame is None or not self._frame:
                    self._build(wx)
                self._braille.SetValue(str(braille or ''))
                self._text.SetValue(str(text or ''))
            except Exception:                        # noqa: BLE001
                self._frame = None

        try:
            wx.CallAfter(put)
            return True
        except Exception:                            # noqa: BLE001
            return False

    def _build(self, wx):
        from .portable import wxkit
        parent = wxkit.frame()
        self._frame = wx.Frame(parent, title=_('Braille viewer'),
                               style=wx.CAPTION | wx.CLOSE_BOX | wx.STAY_ON_TOP)
        panel = wx.Panel(self._frame)
        sizer = wx.BoxSizer(wx.VERTICAL)
        font = wx.Font(wx.FontInfo(20))
        self._braille = wx.TextCtrl(panel, style=wx.TE_READONLY)
        self._braille.SetFont(font)
        self._braille.SetName(_('Braille cells'))
        self._text = wx.TextCtrl(panel, style=wx.TE_READONLY)
        self._text.SetName(_('The text'))
        sizer.Add(self._braille, 0, wx.EXPAND | wx.ALL, 6)
        sizer.Add(self._text, 0, wx.EXPAND | wx.ALL, 6)
        panel.SetSizer(sizer)
        self._frame.SetClientSize((640, 120))
        self._frame.Show()

    def close(self):
        try:
            if self._frame:
                self._frame.Destroy()
        except Exception:                            # noqa: BLE001
            pass
        self._frame = None


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
SECTION = 'Braille'


def _settings():
    try:
        from .settings_store import get_settings
        return get_settings()
    except Exception:                                # noqa: BLE001
        return None


def _setting(key, default):
    store = _settings()
    if store is None:
        return default
    try:
        found = store.get(SECTION, key, default)
        return found if found not in (None, '') else default
    except Exception:                                # noqa: BLE001
        return default


def _bool_setting(key, default):
    store = _settings()
    if store is None:
        return default
    try:
        return store.get_bool(SECTION, key, default)
    except Exception:                                # noqa: BLE001
        return default


def _wanted():
    return _bool_setting('Enabled', False)


def _viewer_wanted():
    return _bool_setting('Viewer', True)


def _language():
    try:
        from src.titan_core import translation
        return getattr(translation, 'current_language', lambda: 'en')() \
            if hasattr(translation, 'current_language') else 'en'
    except Exception:                                # noqa: BLE001
        return 'en'


def tables_available():
    """``[(file name, label)]`` - every table the machine's liblouis has,
    for the Braille settings section. The language's own first."""
    seen = []
    for folder in _table_dirs():
        try:
            for name in sorted(os.listdir(folder)):
                low = name.lower()
                if low.endswith(('.ctb', '.utb', '.tbl', '.dis')) \
                        and name not in seen:
                    seen.append(name)
        except Exception:                            # noqa: BLE001
            continue
    return [(name, name) for name in seen]

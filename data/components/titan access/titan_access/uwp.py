# -*- coding: utf-8 -*-
"""UWP and XAML applications: who they are, and what their icons say.

Measured on Unigram (UWP, Telegram.exe) and the Windows inbox apps; three
things a reader written for Win32 gets wrong in every one of them:

* **The window in front belongs to ApplicationFrameHost, not the app.**
  A UWP app's top-level window is an ``ApplicationFrameWindow`` owned by
  ``ApplicationFrameHost.exe``; the app's own ``Windows.UI.Core.CoreWindow``
  is a CHILD of it - and when the app is minimised, a separate top-level
  window with the same title. So everything that asks "which program is in
  front" (profiles, app modules, .tas scripts, labels, the mute-outside-TCE
  gate) got "applicationframehost" for every UWP app alike. ``app_pid``
  answers the app's own process; :func:`finish` puts it on the object.
* **Icons are characters.** XAML draws an icon as a TextBlock in the Segoe
  MDL2 / Fluent icon font: U+E711 is the Cancel cross. A name or a label
  holding one was read as nothing or as a stray character ("\\uea07 pon."
  in Unigram's chat list). Known icons are said as the word they mean
  (``GLYPHS``), unknown ones - private-use codepoints - are left out.
* **A button that IS an icon has no name.** Unigram's Hide button is a
  Button with one icon TextBlock inside: "Przycisk", and nothing else. Its
  name is taken from what it shows: its tooltip, its children's text or
  icon, and last its AutomationId spelled as words.
"""

import ctypes
import re
import sys
import threading
import time

IS_WINDOWS = sys.platform.startswith('win')

FRAME_CLASS = 'ApplicationFrameWindow'
CORE_CLASS = 'Windows.UI.Core.CoreWindow'
FRAME_HOST = 'applicationframehost'
XAML_FRAMEWORKS = ('XAML', 'DirectUI', 'WinUI', 'Microsoft.UI.Xaml')

#: Segoe MDL2 Assets / Segoe Fluent Icons codepoints (Microsoft's own
#: published names), to the locale key of what they mean.
GLYPHS = {
    0xE700: 'menu', 0xE70D: 'expand', 0xE70E: 'collapse', 0xE70F: 'edit',
    0xE710: 'add', 0xE711: 'cancel', 0xE712: 'more', 0xE713: 'settings',
    0xE714: 'video', 0xE715: 'mail', 0xE716: 'people', 0xE717: 'phone',
    0xE718: 'pin', 0xE71A: 'stop', 0xE71B: 'link', 0xE71C: 'filter',
    0xE71E: 'zoom', 0xE720: 'microphone', 0xE721: 'search', 0xE722: 'camera',
    0xE723: 'attach', 0xE724: 'send', 0xE725: 'send', 0xE72A: 'forward',
    0xE72B: 'back', 0xE72C: 'refresh', 0xE72D: 'share', 0xE72E: 'lock',
    0xE734: 'favorite', 0xE735: 'favorite', 0xE738: 'remove',
    0xE73E: 'checkMark', 0xE740: 'fullScreen', 0xE74D: 'delete',
    0xE74E: 'save', 0xE74F: 'mute', 0xE765: 'keyboard', 0xE767: 'volume',
    0xE768: 'play', 0xE769: 'pause', 0xE76B: 'previous', 0xE76C: 'next',
    0xE77B: 'contact', 0xE77F: 'paste', 0xE787: 'calendar', 0xE81C: 'history',
    0xE890: 'view', 0xE894: 'clear', 0xE895: 'sync', 0xE896: 'download',
    0xE898: 'upload', 0xE897: 'help', 0xE8A3: 'zoomIn', 0xE8A7: 'openInNewWindow',
    0xE8B7: 'folder', 0xE8BB: 'close', 0xE8BD: 'message', 0xE8C6: 'cut',
    0xE8C8: 'copy', 0xE8E5: 'openFile', 0xE8F4: 'newFolder', 0xE8FB: 'accept',
    0xE921: 'minimize', 0xE922: 'maximize', 0xE923: 'restore', 0xE946: 'info',
    0xE7E8: 'power', 0xE8D6: 'audio', 0xE91B: 'photo', 0xE8EC: 'tag',
}

_PRIVATE = re.compile('[-\U000f0000-\U000ffffd\U00100000-\U0010fffd]')
_SPACES = re.compile(r'[  ​]{2,}')


def _word(key):
    try:
        from .localization import L
        found = L('glyph.' + key)
        return '' if found == 'glyph.' + key else found
    except Exception:                                # noqa: BLE001
        return ''


def has_glyph(text):
    return bool(text) and bool(_PRIVATE.search(text))


def glyph_words(text):
    """The meaning of every known icon in ``text``, in order."""
    words = []
    for ch in _PRIVATE.findall(text or ''):
        key = GLYPHS.get(ord(ch))
        word = _word(key) if key else ''
        if word and word not in words:
            words.append(word)
    return words


#: Settings -> UWP apps -> how an icon is read: its meaning in words, left
#: out, or left as it is (`UWP/Glyphs`).
GLYPH_MODES = ('word', 'strip', 'off')


def _setting(key, default):
    try:
        from titan_access.settings_store import get_settings
        store = get_settings()
        if isinstance(default, bool):
            return bool(store.get_bool('UWP', key, default))
        return store.get('UWP', key, default) or default
    except Exception:                                # noqa: BLE001
        return default


def glyph_mode():
    mode = str(_setting('Glyphs', 'word'))
    return mode if mode in GLYPH_MODES else 'word'


def clean(text):
    """``text`` with its icons said as words (known) or left out (unknown).

    A text that IS one known icon becomes its word; icons beside words are
    left out - "\\uea07 pon." is "pon.", the double tick of a read message
    being decoration of a date, not something to say before it."""
    if not text or not _PRIVATE.search(text):
        return text
    mode = glyph_mode()
    if mode == 'off':
        return text
    rest = _PRIVATE.sub(' ', text)
    rest = _SPACES.sub(' ', rest).strip('  ​')
    if rest or mode == 'strip':
        return rest
    return ', '.join(glyph_words(text))


# --------------------------------------------------------------------------- #
# Which program
# --------------------------------------------------------------------------- #
_LOCK = threading.Lock()
_cache = {}                     # frame hwnd -> (pid, when)
_names = {}                     # pid -> executable (lower, no .exe)
CACHE_S = 2.0


def _user32():
    return ctypes.windll.user32


def _class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    _user32().GetClassNameW(ctypes.c_void_p(hwnd), buf, 256)
    return buf.value


def _title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    _user32().GetWindowTextW(ctypes.c_void_p(hwnd), buf, 512)
    return buf.value


def _pid(hwnd):
    from ctypes import wintypes
    pid = wintypes.DWORD()
    _user32().GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    return int(pid.value)


def executable(pid):
    if not pid:
        return ''
    found = _names.get(pid)
    if found is not None:
        return found
    name = ''
    try:
        import psutil
        name = psutil.Process(pid).name()
    except Exception:                                # noqa: BLE001
        try:
            from titan_access.nvda_shape import executable_of
            name = executable_of(pid)
        except Exception:                            # noqa: BLE001
            name = ''
    name = name.lower()
    if name.endswith('.exe'):
        name = name[:-4]
    _names[pid] = name
    return name


def _root(hwnd):
    try:
        return int(_user32().GetAncestor(ctypes.c_void_p(hwnd), 2) or 0)  # GA_ROOT
    except Exception:                                # noqa: BLE001
        return 0


def app_pid(hwnd):
    """The pid of the program a window really belongs to.

    For anything but a UWP frame it is the window's own pid. For an
    ``ApplicationFrameWindow`` it is the pid of its ``CoreWindow`` child,
    or - minimised, when the CoreWindow is a top-level window of its own -
    of the CoreWindow with the frame's title. 0 for no window."""
    if not IS_WINDOWS or not hwnd:
        return 0
    try:
        top = _root(hwnd) or hwnd
        own = _pid(top)
        if _class(top) != FRAME_CLASS:
            return _pid(hwnd) if top != hwnd else own
        now = time.time()
        with _LOCK:
            hit = _cache.get(top)
            if hit and now - hit[1] < CACHE_S:
                return hit[0]
        found = _core_child(top, own) or _detached_core(top, own) or own
        with _LOCK:
            _cache[top] = (found, now)
        return found
    except Exception:                                # noqa: BLE001
        return 0


def _core_child(frame, own):
    from ctypes import wintypes
    found = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def child(h, _l):
        if _class(h) == CORE_CLASS:
            pid = _pid(h)
            if pid and pid != own:
                found.append(pid)
                return False
        return True
    _user32().EnumChildWindows(ctypes.c_void_p(frame), proto(child), 0)
    return found[0] if found else 0


def _detached_core(frame, own):
    title = _title(frame)
    if not title:
        return 0
    from ctypes import wintypes
    found = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def top(h, _l):
        if _class(h) == CORE_CLASS and _title(h) == title:
            pid = _pid(h)
            if pid and pid != own:
                found.append(pid)
                return False
        return True
    _user32().EnumWindows(proto(top), 0)
    return found[0] if found else 0


def foreground_pid():
    """The pid of the program in front, a UWP app's own and not its frame's."""
    if not IS_WINDOWS:
        return 0
    try:
        hwnd = int(_user32().GetForegroundWindow() or 0)
    except Exception:                                # noqa: BLE001
        return 0
    return app_pid(hwnd) if hwnd else 0


def is_uwp_window(hwnd):
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        top = _root(hwnd) or hwnd
        return _class(top) in (FRAME_CLASS, CORE_CLASS)
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# The object a provider built
# --------------------------------------------------------------------------- #
#: Roles a user acts on: one of these with no name is worth naming.
_NAMEABLE = ('button', 'split_button', 'link', 'menuitem', 'checkbox', 'radio',
             'tab', 'listitem', 'treeitem', 'griditem', 'combobox', 'image')


def _humanise(automation_id):
    """``SetBirthdateCard`` -> ``Set birthdate card``; '' for an id that is
    a number or a generated one."""
    text = str(automation_id or '').strip()
    if not text or not re.search('[A-Za-z]{3}', text) or re.search(r'\d{3}', text):
        return ''
    text = re.sub(r'[_\-.]+', ' ', text)
    text = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', text)
    words = text.split()
    if not words:
        return ''
    out = ' '.join([words[0]] + [w.lower() for w in words[1:]])
    return out[:1].upper() + out[1:]


def _children_text(control, depth=2, budget=None):
    """The words a control shows: its text children, and their icons."""
    budget = budget if budget is not None else [12]
    words = []
    try:
        children = control.GetChildren()
    except Exception:                                # noqa: BLE001
        return words
    for child in children:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        try:
            name = child.Name or ''
        except Exception:                            # noqa: BLE001
            name = ''
        said = clean(name) if name else ''
        if said and said not in words:
            words.append(said)
        elif depth > 1:
            for word in _children_text(child, depth - 1, budget):
                if word not in words:
                    words.append(word)
    return words


def name_for(obj, control):
    """A name for a nameless control, from what it shows. '' when nothing."""
    for text in (getattr(obj, 'help_text', ''), getattr(obj, 'description', '')):
        if text and clean(text):
            return clean(text)
    if control is not None:
        words = _children_text(control)
        if words:
            return ', '.join(words)[:200]
    if (getattr(obj, 'framework_id', '') or '') in XAML_FRAMEWORKS:
        return _humanise(getattr(obj, 'automation_id', ''))
    return ''


def finish(obj, control=None):
    """What the provider built, made right for a UWP / XAML app: the real
    program, icons as words, and a name for a control that had none.
    Never raises; costs nothing for a named control in a Win32 program."""
    if obj is None:
        return obj
    try:
        if IS_WINDOWS and obj.process_id and executable(obj.process_id) == FRAME_HOST:
            hwnd = getattr(obj, 'hwnd', 0) or 0
            real = app_pid(hwnd) if hwnd else foreground_pid()
            if real:
                obj.process_id = real
        for field in ('name', 'help_text', 'description'):
            value = getattr(obj, field, '')
            if value and has_glyph(value):
                setattr(obj, field, clean(value))
        if obj.value and has_glyph(obj.value) and obj.role not in ('edit', 'document'):
            obj.value = clean(obj.value)
        if not (obj.name or '').strip() and obj.role in _NAMEABLE \
                and _setting('NameIconControls', True):
            named = name_for(obj, control)
            if named:
                obj.name = named
    except Exception:                                # noqa: BLE001
        pass
    return obj


def node_name(name, role, control=None, framework='', automation_id='',
              help_text=''):
    """A virtual document entry's name, the same rules as :func:`finish`.

    Answers None for an entry that should not be a line at all: a text
    that is nothing but icons is decoration of the control around it (the
    pencil inside an Edit button), which already says what it is."""
    if name and has_glyph(name) and glyph_mode() != 'off':
        if role == 'text' and not _PRIVATE.sub('', name).strip(' \u00a0\u200b'):
            return None
        name = clean(name)
    if not (name or '').strip() and role in _NAMEABLE \
            and _setting('NameIconControls', True):

        class _Shape(object):
            pass
        shape = _Shape()
        shape.help_text, shape.description = help_text, ''
        shape.framework_id, shape.automation_id = framework, automation_id
        name = name_for(shape, control)
    return name


#: UI Automation's own default is 20 s per call: a suspended UWP app (a
#: minimised one Windows has frozen) held the reader that long for every
#: question put to it. 6 s still lets a large page be read in one call.
CONNECTION_TIMEOUT_MS = 2000
TRANSACTION_TIMEOUT_MS = 6000


def limit_timeouts(client):
    """Give an IUIAutomation client short timeouts (IUIAutomation2, Win 8.1+).
    True when they were set."""
    if client is None:
        return False
    try:
        import comtypes.client
        mod = comtypes.client.GetModule('UIAutomationCore.dll')
        second = client.QueryInterface(mod.IUIAutomation2)
        second.ConnectionTimeout = CONNECTION_TIMEOUT_MS
        second.TransactionTimeout = TRANSACTION_TIMEOUT_MS
        return True
    except Exception:                                # noqa: BLE001
        return False


def limit_all_timeouts(own_client=None):
    """The reader's own client and the vendored library's, both."""
    done = limit_timeouts(own_client)
    try:
        from uiautomation.uiautomation import _AutomationClient
        done = limit_timeouts(_AutomationClient.instance().IUIAutomation) or done
    except Exception:                                # noqa: BLE001
        pass
    return done


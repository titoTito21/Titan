# -*- coding: utf-8 -*-
"""What each part of Titan's own shell MEANS - read off the shell itself.

Titan's shell (`src/shell/`: the desktop, the taskbar, the notification
area, the Start menu and the file browser) is readable through MSAA like
any program: every painted control answers a name, a role and a state.
That is what a reader gets from OUTSIDE, and it leaves out everything the
shell knows and Windows' accessibility layer has no field for:

* a window button is "a list item called Notepad" - not a WINDOW, and
  nothing says whether it is the one in front, minimised, asking for
  attention or no longer answering;
* the bar is four groups, and nothing says which one the keyboard is in
  or where in it ("2 of 5") - the taskbar's own group announcement went
  through the host bridge as a replacement for the next focus report, so
  Tab into "Open windows" said the GROUP and never the window it landed
  on;
* a desktop icon is "Recycle Bin, list item" whether it is a folder, a
  shortcut or a document, and a Start-menu entry does not say whether it
  is a Titan application, a game, a macro, a messenger or a Windows
  program;
* a window opening or closing behind the user is said by nobody.

Titan Access runs INSIDE Titan, in the very process the shell runs in, so
it can ask the shell's own live objects rather than Windows' picture of
them - and does, without one line of the shell being changed for it: the
shell is found through ``sys.modules`` (nothing is imported that would
start anything), and everything read off a wx window is read on wx's own
thread (`on_gui`), with a short deadline, because wx is not thread-safe
and the reader's thread is not wx's. A compiled Titan freezes ``src``;
this file is data in the component, so it reaches a user with no rebuild.

The answer is an :class:`Info`. The engine turns it into speech
(`engine._titan_shell_layers`), the where-am-I command says the whole of
it, and :class:`WindowWatch` reads the taskbar's own window list for the
windows that come and go behind the user.
"""

import os
import sys
import threading

from titan_access.localization import L

#: How long the reader waits for wx's thread to answer a question about
#: the shell. On the focus path, so short: an answer that comes later is
#: an announcement without the shell's words, never a stalled reader.
GUI_TIMEOUT = 0.25

_LOCK = threading.RLock()
_counted = {'asked': 0, 'answered': 0, 'late': 0, 'groups': 0,
            'opened': 0, 'closed': 0}
#: The group the keyboard was last in, per surface, so a group is said
#: once on arriving in it and not on every arrow inside it.
_last_group = {}


def report():
    with _LOCK:
        return dict(_counted)


def forget():
    with _LOCK:
        _last_group.clear()
        for key in _counted:
            _counted[key] = 0


def _count(key):
    with _LOCK:
        _counted[key] = _counted.get(key, 0) + 1


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
SECTION = 'TitanShell'


def _setting(engine, key, default):
    store = getattr(engine, 'settings', None)
    if store is None:
        return default
    try:
        if isinstance(default, bool):
            return bool(store.get_bool(SECTION, key, default))
        return str(store.get(SECTION, key, default) or default)
    except Exception:                                # noqa: BLE001
        return default


def wanted(engine):
    """``TitanShell/Semantics`` - the whole layer."""
    return _setting(engine, 'Semantics', True)


# --------------------------------------------------------------------------- #
# The shell, found without starting anything
# --------------------------------------------------------------------------- #
def _module(name):
    return sys.modules.get(name)


def shell():
    """The running Titan shell, or None. Never makes one."""
    manager = _module('src.shell.shell_manager')
    if manager is None:
        return None
    try:
        found = manager.get_shell(create=False)
    except Exception:                                # noqa: BLE001
        return None
    if found is None or not getattr(found, '_running', False):
        return None
    return found


def _window(found, name):
    try:
        return found.window(name)
    except Exception:                                # noqa: BLE001
        return getattr(found, name, None)


def on_gui(fn, timeout=GUI_TIMEOUT):
    """``fn()`` on wx's own thread, waited for at most ``timeout``.

    Called from wx's thread (Linux, where the reader IS the main thread,
    and the tests) it simply runs. Late is None: the reader carries on with
    what it would have said anyway."""
    try:
        import wx
    except Exception:                                # noqa: BLE001
        return None
    try:
        if wx.IsMainThread() or wx.GetApp() is None:
            return fn()
    except Exception:                                # noqa: BLE001
        return None
    box = {}
    done = threading.Event()

    def run():
        try:
            box['value'] = fn()
        except Exception as error:                   # noqa: BLE001
            box['error'] = error
        finally:
            done.set()
    try:
        wx.CallAfter(run)
    except Exception:                                # noqa: BLE001
        return None
    if not done.wait(timeout):
        _count('late')
        return None
    return box.get('value')


def _alive(window):
    try:
        return window is not None and bool(window)
    except Exception:                                # noqa: BLE001
        return False


def _class_names(window):
    try:
        return {klass.__name__ for klass in type(window).__mro__}
    except Exception:                                # noqa: BLE001
        return set()


def _handle(window):
    try:
        return int(window.GetHandle() or 0)
    except Exception:                                # noqa: BLE001
        return 0


def focused_window():
    """wx's own answer to "what has the keyboard" - on wx's thread only."""
    import wx
    return wx.Window.FindFocus()


# --------------------------------------------------------------------------- #
# The answer
# --------------------------------------------------------------------------- #
class Info(object):
    """What a part of the shell IS.

    ``surface`` - taskbar / desktop / start_menu / explorer;
    ``group`` - the taskbar group's name, in the user's language;
    ``kind`` - the word for what this is, where it says more than the role;
    ``states`` - words, in the order they are said;
    ``position`` - ``(index, count)`` within its group, or None;
    ``detail`` - what the where-am-I command adds (a path, a program)."""

    __slots__ = ('surface', 'group', 'kind', 'states', 'position', 'detail',
                 'place', 'name')

    def __init__(self, surface, group='', kind='', states=None,
                 position=None, detail='', place='', name=''):
        self.surface = surface
        self.group = group or ''
        self.kind = kind or ''
        self.states = list(states or [])
        self.position = position
        self.detail = detail or ''
        self.place = place or ''
        self.name = name or ''

    def __repr__(self):
        return 'Info(%s)' % ', '.join(
            '%s=%r' % (slot, getattr(self, slot)) for slot in self.__slots__)


def surface_word(surface):
    return L('titanShell.surface.' + surface) if surface else ''


# --------------------------------------------------------------------------- #
# Windows: the program behind a window button, and whether it answers
# --------------------------------------------------------------------------- #
def _hung(hwnd):
    if os.name != 'nt' or not hwnd:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.IsHungAppWindow(int(hwnd)))
    except Exception:                                # noqa: BLE001
        return False


def program_of(hwnd):
    """The executable's name for a window, or ''."""
    if os.name != 'nt' or not hwnd:
        return ''
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        process = kernel32.OpenProcess(0x1000, False, pid.value)
        if not process:
            return ''
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(
                    process, 0, buffer, ctypes.byref(size)):
                return os.path.basename(buffer.value)
        finally:
            kernel32.CloseHandle(process)
    except Exception:                                # noqa: BLE001
        pass
    return ''


# --------------------------------------------------------------------------- #
# The taskbar
# --------------------------------------------------------------------------- #
def _group_label(name):
    taskbar = _module('src.shell.taskbar')
    if taskbar is not None:
        try:
            label = taskbar.group_label(name)
            if label:
                return label
        except Exception:                            # noqa: BLE001
            pass
    return L('titanShell.group.' + name) if name else ''


def describe_taskbar_control(bar, control):
    """An :class:`Info` for a control of the bar (wx's thread)."""
    try:
        _index, group, controls = bar._group_of(control)
    except Exception:                                # noqa: BLE001
        group, controls = '', []
    position = None
    if control in controls and len(controls) > 0:
        position = (controls.index(control) + 1, len(controls))
    names = _class_names(control)
    kind, states, detail = '', [], ''
    if 'TaskButton' in names:
        window = getattr(control, 'window', None)
        kind = L('titanShell.kind.window')
        if getattr(window, 'flashing', False):
            states.append(L('titanShell.state.attention'))
        if _hung(getattr(window, 'hwnd', 0)):
            states.append(L('titanShell.state.notResponding'))
        if getattr(window, 'minimized', False):
            states.append(L('titanShell.state.minimized'))
        elif getattr(window, 'active', False):
            states.append(L('titanShell.state.active'))
        detail = program_of(getattr(window, 'hwnd', 0))
    elif 'TrayIconButton' in names:
        icon = getattr(control, 'icon', None)
        if getattr(icon, 'chevron', False):
            kind = ''
        else:
            kind = L('titanShell.kind.trayIcon')
            if getattr(icon, 'hidden', False):
                states.append(L('titanShell.state.hidden'))
    elif 'QuickLaunchButton' in names:
        kind = L('titanShell.kind.dockItem')
        item = getattr(control, 'item', None) or {}
        detail = str(item.get('path', '') or '') if isinstance(item, dict) else ''
    elif 'StartButton' in names:
        if getattr(control, '_menu_open', False):
            states.append(L('titanShell.state.menuOpen'))
    elif 'ClockControl' in names:
        kind = L('titanShell.kind.clock')
    return Info('taskbar', group=_group_label(group), kind=kind,
                states=states, position=position, detail=detail,
                name=_shell_name(control))


def _shell_name(control):
    try:
        return str(control.shell_name() or '')
    except Exception:                                # noqa: BLE001
        return ''


# --------------------------------------------------------------------------- #
# The desktop
# --------------------------------------------------------------------------- #
def kind_of_path(path):
    """Folder / shortcut / internet shortcut / a file of its type."""
    path = str(path or '')
    if not path:
        return ''
    lower = path.lower()
    if os.path.isdir(path):
        return L('titanShell.kind.folder')
    if lower.endswith('.lnk') or lower.endswith('.desktop'):
        return L('titanShell.kind.shortcut')
    if lower.endswith('.url'):
        return L('titanShell.kind.internetShortcut')
    explorer = _module('src.shell.explorer')
    if explorer is not None:
        try:
            word = explorer._extension_type_name(path)
            if word:
                return str(word)
        except Exception:                            # noqa: BLE001
            pass
    return L('titanShell.kind.file')


def shortcut_target(path):
    lower = str(path or '').lower()
    if not (lower.endswith('.lnk') or lower.endswith('.desktop')):
        return ''
    win_shell = _module('src.shell.win_shell')
    if win_shell is None:
        return ''
    try:
        return str(win_shell.shortcut_target(path) or '')
    except Exception:                                # noqa: BLE001
        return ''


def _entry_by_name(entries, name, position, key):
    """The entry the reader is on: by its place when the name agrees, by
    its name otherwise (a list re-read under the cursor moves places)."""
    entries = list(entries or [])
    name = (name or '').strip()
    if position and 0 < position <= len(entries):
        entry = entries[position - 1]
        if not name or _key(entry, key) == name:
            return position - 1, entry
    if name:
        for index, entry in enumerate(entries):
            if _key(entry, key) == name:
                return index, entry
    return -1, None


def _key(entry, key):
    if isinstance(entry, dict):
        return str(entry.get(key, '') or '').strip()
    return str(getattr(entry, key, '') or '').strip()


def describe_desktop_item(desktop, name, position):
    index, entry = -1, None
    try:
        selected = desktop.list.GetFocusedItem()
    except Exception:                                # noqa: BLE001
        selected = -1
    items = list(getattr(desktop, 'items', []) or [])
    if 0 <= selected < len(items) and (
            not name or _key(items[selected], 'name') == name.strip()):
        index, entry = selected, items[selected]
    else:
        index, entry = _entry_by_name(items, name, position, 'name')
    if entry is None:
        return Info('desktop', name=name)
    path = entry.get('path', '') if isinstance(entry, dict) else ''
    kind = kind_of_path(path)
    detail = path
    target = shortcut_target(path)
    if target:
        detail = L('titanShell.detail.target', target)
    return Info('desktop', kind=kind, position=(index + 1, len(items)),
                detail=detail, name=_key(entry, 'name'))


# --------------------------------------------------------------------------- #
# The Start menu
# --------------------------------------------------------------------------- #
#: `MenuEntry.kind` -> the word for it. ``action`` (Lock, Run, Log off...)
#: is a command and its role says so already.
MENU_KINDS = {
    'app': 'titanShell.kind.app',
    'game': 'titanShell.kind.game',
    'im_module': 'titanShell.kind.messenger',
    'macro': 'titanShell.kind.macro',
    'program': 'titanShell.kind.program',
    'folder': 'titanShell.kind.branch',
    'uwp': 'titanShell.kind.storeApp',
}


def menu_kind(entry):
    key = MENU_KINDS.get(str(getattr(entry, 'kind', '') or ''))
    if not key:
        return ''
    payload = getattr(entry, 'payload', None)
    # A packaged (Store) application: its payload is an AUMID.
    if getattr(entry, 'kind', '') == 'program' and isinstance(payload, str):
        win_shell = _module('src.shell.win_shell')
        try:
            if win_shell is not None and win_shell.is_packaged_app(payload):
                return L(MENU_KINDS['uwp'])
        except Exception:                            # noqa: BLE001
            pass
    return L(key)


def describe_menu_entry(control, names):
    entry = None
    try:
        if 'MenuTree' in names:
            entry = control.selected_entry()
        else:
            index = control.GetFocusedItem()
            if index < 0:
                index = control.GetFirstSelected()
            entries = list(getattr(control, 'entries', []) or [])
            if 0 <= index < len(entries):
                entry = entries[index]
    except Exception:                                # noqa: BLE001
        entry = None
    if entry is None:
        return Info('start_menu')
    detail = str(getattr(entry, 'description', '') or '')
    payload = getattr(entry, 'payload', None)
    if not detail and isinstance(payload, str) and os.path.isabs(payload):
        detail = payload
    return Info('start_menu', kind=menu_kind(entry), detail=detail,
                name=str(getattr(entry, 'label', '') or ''))


# --------------------------------------------------------------------------- #
# The file browser
# --------------------------------------------------------------------------- #
def describe_explorer(frame, focus):
    place = ''
    explorer = _module('src.shell.explorer')
    try:
        if explorer is not None:
            place = str(explorer.location_name(frame.location) or '')
    except Exception:                                # noqa: BLE001
        place = ''
    detail = ''
    try:
        if focus is frame.list:
            count = frame.list.GetSelectedItemCount()
            total = len(getattr(frame, 'entries', []) or [])
            if count > 1:
                detail = L('titanShell.detail.selected', count, total)
            else:
                detail = L('titanShell.detail.items', total)
    except Exception:                                # noqa: BLE001
        pass
    return Info('explorer', place=place, detail=detail)


# --------------------------------------------------------------------------- #
# The question the engine asks
# --------------------------------------------------------------------------- #
def _explorer_frame_of(top):
    explorer = _module('src.shell.explorer')
    if explorer is None:
        return None
    try:
        for frame in explorer.open_windows():
            if frame is top:
                return frame
    except Exception:                                # noqa: BLE001
        pass
    return None


def describe_focus(name='', position=0, hwnd=0):
    """An :class:`Info` for whatever in the shell has the keyboard, or None
    when it is not the shell (wx's thread)."""
    found = shell()
    focus = focused_window()
    if focus is None or not _alive(focus):
        return None
    # The reader's object must be the control wx has the focus on, or a row
    # inside it (a row of a list view has no window of its own).
    if hwnd and _handle(focus) and hwnd != _handle(focus):
        return None
    names = _class_names(focus)
    # The Start menu's columns are the shell's whether or not the desktop
    # shell is up (the classic menu shows them too).
    if 'MenuTree' in names or 'MenuList' in names:
        return describe_menu_entry(focus, names)
    try:
        top = focus.GetTopLevelParent()
    except Exception:                                # noqa: BLE001
        top = None
    frame = _explorer_frame_of(top)
    if frame is not None:
        return describe_explorer(frame, focus)
    if found is None:
        return None
    bar = _window(found, 'taskbar')
    if bar is not None and top is bar:
        return describe_taskbar_control(bar, focus)
    desktop = _window(found, 'desktop')
    if desktop is not None and top is desktop:
        if focus is getattr(desktop, 'list', None):
            return describe_desktop_item(desktop, name, position)
        return Info('desktop')
    start = _window(found, 'start_menu')
    if start is not None and top is start:
        return Info('start_menu')
    return None


#: Native controls the Start menu's columns are made of - the one part of
#: the shell that also lives outside the shell (the classic menu).
_MENU_CLASSES = ('SysTreeView32', 'SysListView32')


def _shell_handles():
    """The handles of the shell's own top-level windows (cheap: wx keeps
    the HWND in a field)."""
    handles = set()
    found = shell()
    if found is not None:
        for name in ('taskbar', 'desktop', 'start_menu'):
            window = getattr(found, name, None)
            if window is not None:
                handles.add(_handle(window))
    explorer = _module('src.shell.explorer')
    if explorer is not None:
        try:
            for frame in list(getattr(explorer, '_frames', []) or []):
                handles.add(_handle(frame))
        except Exception:                            # noqa: BLE001
            pass
    handles.discard(0)
    return handles


def worth_asking():
    """Whether the keyboard is anywhere the shell could answer for - asked
    on the reader's thread, of Windows, so a focus in one of Titan's own
    ordinary windows does not wait for wx's thread to say "not mine"."""
    if os.name != 'nt':
        return True
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        if int(user32.GetForegroundWindow() or 0) in _shell_handles():
            return True

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                        ('hwndActive', wintypes.HWND),
                        ('hwndFocus', wintypes.HWND),
                        ('hwndCapture', wintypes.HWND),
                        ('hwndMenuOwner', wintypes.HWND),
                        ('hwndMoveSize', wintypes.HWND),
                        ('hwndCaret', wintypes.HWND),
                        ('rcCaret', wintypes.RECT)]
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        if not user32.GetGUIThreadInfo(0, ctypes.byref(info)):
            return True
        if not info.hwndFocus:
            return False
        buffer = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(info.hwndFocus, buffer, 64)
        return buffer.value in _MENU_CLASSES
    except Exception:                                # noqa: BLE001
        return True


def read(obj, engine=None):
    """The shell's answer for the reader's object, or None.

    Only ever asked about a control in Titan's own process: everything
    else on the machine is somebody else's and has nothing to ask."""
    if obj is None:
        return None
    try:
        pid = int(getattr(obj, 'process_id', 0) or 0)
    except Exception:                                # noqa: BLE001
        pid = 0
    if pid and pid != os.getpid():
        return None
    if _module('src.shell.shell_manager') is None and \
            _module('src.ui.start_menu_content') is None:
        return None
    if not worth_asking():
        return None
    _count('asked')
    name = str(getattr(obj, 'name', '') or '')
    position = int(getattr(obj, 'pos_in_set', 0) or 0)
    hwnd = int(getattr(obj, 'hwnd', 0) or 0)
    info = on_gui(lambda: describe_focus(name, position, hwnd))
    if info is not None:
        _count('answered')
    return info


def group_arrived(info):
    """The group's name the first time the keyboard is in it, else ''."""
    if info is None or not info.group:
        if info is not None:
            with _LOCK:
                _last_group.pop(info.surface, None)
        return ''
    with _LOCK:
        if _last_group.get(info.surface) == info.group:
            return ''
        _last_group[info.surface] = info.group
        _counted['groups'] += 1
    return info.group


def leave_surface(surface):
    """The keyboard left the bar: coming back says the group again."""
    with _LOCK:
        _last_group.pop(surface, None)


def segments_for(info, engine, obj=None):
    """``(before, after)`` segments for an announcement."""
    from titan_access.accessible import STATE_PITCH, ROLE_PITCH
    before, after = [], []
    if info is None:
        return before, after
    if _setting(engine, 'GroupNames', True):
        group = group_arrived(info)
        if group:
            before.append((group, ROLE_PITCH))
    for word in info.states:
        if word:
            after.append((word, STATE_PITCH))
    already = bool(getattr(obj, 'pos_in_set', 0)) if obj is not None else False
    if info.position and not already and _setting(engine, 'Positions', True):
        index, count = info.position
        if count > 1:
            after.append((L('element.positionOf', index, count), STATE_PITCH))
    return before, after


def where_am_i_text(info, obj=None):
    """The whole of it, for the where-am-I command."""
    if info is None:
        return ''
    parts = [surface_word(info.surface)]
    if info.place:
        parts.append(info.place)
    if info.group:
        parts.append(info.group)
    name = info.name or str(getattr(obj, 'name', '') or '')
    if name:
        parts.append(name)
    if info.kind:
        parts.append(info.kind)
    parts.extend(info.states)
    if info.position and info.position[1] > 1:
        parts.append(L('element.positionOf', *info.position))
    if info.detail:
        parts.append(info.detail)
    return ', '.join(part for part in parts if part)


# --------------------------------------------------------------------------- #
# Windows opening and closing behind the user
# --------------------------------------------------------------------------- #
#: How often the taskbar's own window list is looked at. It is a Python
#: list the bar replaces whenever Windows' shell hook tells it something
#: changed, so reading it costs nothing and asks Windows nothing.
WATCH_INTERVAL = 1.0


def _snapshot():
    found = shell()
    bar = _window(found, 'taskbar') if found is not None else None
    if bar is None:
        return None
    windows = list(getattr(bar, '_windows', []) or [])
    return {getattr(w, 'hwnd', 0): (str(getattr(w, 'title', '') or ''),
                                    bool(getattr(w, 'active', False)))
            for w in windows if getattr(w, 'hwnd', 0)}


def changes(before, after, mode):
    """``[(event, title)]`` between two snapshots.

    ``background`` - a window that appeared without coming to the front,
    and one that went away while it was not the one in front: the two
    nobody else says (a window that opens in front announces itself, and
    one the user closes hands the focus to the next, which is read).
    ``all`` - every one."""
    said = []
    if before is None or after is None or mode == 'none':
        return said
    for hwnd, (title, active) in after.items():
        if hwnd in before or not title:
            continue
        if mode == 'all' or not active:
            said.append(('opened', title))
    for hwnd, (title, active) in before.items():
        if hwnd in after or not title:
            continue
        if mode == 'all' or not active:
            said.append(('closed', title))
    return said


class WindowWatch(object):
    """Reads the taskbar's window list once a second and says the windows
    that came and went behind the user (``TitanShell/WindowEvents``)."""

    def __init__(self, engine):
        self.engine = engine
        self._stop = threading.Event()
        self._thread = None
        self._last = None

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='TitanAccessShellWatch')
        self._thread.start()

    def stop(self):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(2.0)

    def _run(self):
        while not self._stop.wait(WATCH_INTERVAL):
            try:
                self.tick()
            except Exception:                        # noqa: BLE001
                pass

    def tick(self):
        mode = _setting(self.engine, 'WindowEvents', 'background')
        if not wanted(self.engine) or mode == 'none':
            self._last = None
            return []
        now = _snapshot()
        said = changes(self._last, now, mode)
        self._last = now
        for event, title in said:
            _count(event)
            self._say(L('titanShell.event.' + event, title))
        return said

    def _say(self, text):
        engine = self.engine
        try:
            if hasattr(engine, 'for_titan'):
                with engine.for_titan():
                    engine.speak(text, interrupt=False)
            else:
                engine.speak(text, interrupt=False)
        except Exception:                            # noqa: BLE001
            pass


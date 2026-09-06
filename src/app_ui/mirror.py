# -*- coding: utf-8 -*-
"""The floor: an application read off its own window, not out of its `wx`.

Some applications cannot be described. tWeb's interface IS a web view -
`wx.html2` - and a web view is a document being rendered by a browser
engine, not a list of controls; a media surface is the same. The shim
refuses those by name, which is honest and leaves the user with nothing.

So this is the tier underneath: the application is launched **normally**,
with the real wxPython and a real window, and that window is READ - by UI
Automation, then MSAA, then the raw child-window tree - into the same
neutral screen model everything else here produces. The interface at the
other end renders it with the code it already has.

**It is a mirror and it says so.** A described screen is the application's
own account of itself; this is what Windows can see of a window, which is
a weaker thing: a control Windows cannot name has no name, a value it
cannot read is not read, and the window really exists and can be looked
at. Calling the two the same would be the dishonesty this whole subsystem
is built to avoid, so a mirrored screen carries `mirror: true` and one
sentence saying what it is.

Nothing here is new machinery. Titan Access has read any window in this
way since it was written (`virtual_buffer.build_for_window`, four tiers in
descending order of trust), and this is that, turned into the shape the
rest of `src/app_ui` speaks.
"""

import os
import sys
import threading
import time

from src.app_ui import model

#: Long enough for an application that builds a browser before it shows
#: anything. A window that has not appeared by then has not appeared.
WINDOW_WAIT = 25.0

#: How much of a window to carry. A browser's document can be thousands of
#: entries and an interface made of speech is not helped by all of them.
MAX_CONTROLS = 400

#: What Windows calls a control -> what this calls it. Anything not here
#: becomes a line of text, which is what an unnameable control honestly is.
KINDS = {
    'button': 'button', 'split_button': 'button', 'menuitem': 'button',
    'link': 'button',
    'edit': 'text', 'password': 'text', 'document': 'multiline',
    'checkbox': 'check', 'radio': 'check',
    'combobox': 'choice', 'tab': 'choice',
    'list': 'list', 'tree': 'tree', 'table': 'table', 'grid': 'table',
    'slider': 'slider', 'spinner': 'slider', 'progressbar': 'gauge',
    'text': 'label', 'heading': 'label', 'statusbar': 'label',
}

#: Read but never offered: they are the frame around the interface rather
#: than part of it, and a list of them is a list of nothing to do.
SKIP = ('window', 'pane', 'group', 'toolbar', 'menubar', 'separator',
        'image', 'scrollbar', 'unknown')

#: A window with no text of its own is named by its CLASS by the
#: child-window tier, and a class name is not something on the screen.
#: Only the containers, and only as a LABEL - a button really called
#: "panel" would still be offered.
CONTAINERS = frozenset((
    'panel', 'wxpanel', 'window', 'wxwindow', 'frame', 'wxframe',
    'dialog', 'wxdialog', 'wxwebview', 'chrome legacy window',
    'intermediate d3d window', 'wxglcanvas', 'scrollbar', 'static',
))


def available():
    """Whether this machine can read a window at all."""
    return os.name == 'nt' and _titan_access() is not None


def _titan_access():
    """Titan Access's document builder, wherever the component is."""
    module = sys.modules.get('_app_ui_virtual_buffer')
    if module is not None:
        return module
    try:
        from src import platform_utils
        found = platform_utils.find_resource(
            os.path.join('data', 'components', 'titan access'))
    except Exception:
        found = ''
    if not found:
        found = os.path.join(_root(), 'data', 'components', 'titan access')
    if not os.path.isdir(found):
        return None
    if found not in sys.path:
        sys.path.insert(0, found)
    try:
        from titan_access import virtual_buffer
    except Exception as error:
        print('[app_ui] the window reader is not available: %s' % error)
        return None
    sys.modules['_app_ui_virtual_buffer'] = virtual_buffer
    return virtual_buffer


def _root():
    return os.path.dirname(os.path.dirname(os.path.abspath(
        os.path.dirname(__file__))))


class Mirror(object):
    """An application running in its own window, read rather than described.

    The same surface as `host.Application` - `start`, `screen`, `tell`,
    `stop`, `log` - so `sessions` and every interface above it cannot tell
    the two apart except by the sentence the screen carries.
    """

    def __init__(self, entry, name=''):
        self.entry = entry
        self.name = name or os.path.basename(os.path.dirname(entry))
        self.process = None
        self.hwnd = 0
        self.screen = None
        self.status = ''
        self.detail = ''
        self.log = []
        self.refused = []
        self.unknown = []
        self.mirrored = True
        self.started = threading.Event()
        self.ended = threading.Event()
        self.changed = threading.Event()
        self._nodes = []
        self._lock = threading.RLock()

    # ------------------------------------------------------------- start
    def start(self, python=None):
        if not available():
            self.status, self.detail = 'failed', (
                'this machine cannot read another program\'s window, so '
                'there is no way to show %s' % self.name)
            self.ended.set()
            return False
        import subprocess
        folder = os.path.dirname(os.path.abspath(self.entry))
        environment = dict(os.environ)
        paths = [folder, _root()]
        try:
            from src.titan_core.app_manager import SITEPACKAGES_DIR
            paths.append(SITEPACKAGES_DIR)
        except Exception:
            pass
        existing = environment.get('PYTHONPATH', '')
        if existing:
            paths.append(existing)
        environment['PYTHONPATH'] = os.pathsep.join(paths)
        environment['PYTHONIOENCODING'] = 'utf-8'
        environment.pop('PYTHONHOME', None)
        # **The real wxPython.** That is the whole of this tier: the
        # application draws its window exactly as it always does, and what
        # is different is only who reads it.
        command = [python or _python(), '-X', 'utf8', '-c', _BOOT % {
            'folder': folder.replace('\\', '\\\\'),
            'root': _root().replace('\\', '\\\\'),
            'entry': os.path.abspath(self.entry).replace('\\', '\\\\')}]
        try:
            self.process = subprocess.Popen(
                command, cwd=folder, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as error:
            self.status, self.detail = 'failed', str(error)
            self.ended.set()
            return False
        threading.Thread(target=self._read_log, name='mirror-log',
                         daemon=True).start()
        self.hwnd = self._wait_for_window()
        if not self.hwnd:
            self.status = 'failed'
            self.detail = self.detail or (
                '%s did not put a window up' % self.name)
            self.stop()
            return False
        self.status = 'running'
        self.read()
        self.started.set()
        return True

    def _wait_for_window(self):
        """The application's own top-level window, by its process id.

        A window is looked for rather than assumed: an application that
        fails on its first line has a process for a moment and never a
        window, and waiting for one is how that is told apart from an
        application that is merely slow to start.
        """
        deadline = time.time() + WINDOW_WAIT
        while time.time() < deadline:
            if self.process.poll() is not None:
                return 0
            found = _window_of(self.process.pid)
            if found:
                # Give it a moment to finish building: the first window a
                # wx application shows is often empty for a frame or two.
                time.sleep(0.4)
                return found
            time.sleep(0.15)
        return 0

    # -------------------------------------------------------------- read
    #: **The raw child-window tree FIRST**, which is the opposite of the
    #: order Titan Access uses for a window in general - and for a reason
    #: that is specific and measurable. A TCE application is wxWidgets,
    #: where every control IS a real child window, so the child tree is
    #: the most faithful account of it there is. Measured on tWeb's own
    #: window: UI Automation answered **0** nodes, MSAA answered **530** -
    #: 349 buttons, 52 menu bars, 52 scroll bars, almost all of it the
    #: frame's own furniture and none of it carrying a rectangle - and
    #: win32 answered **15**, every one of them a control the application
    #: had put there: Back, Forward, Refresh, Add bookmark, the address
    #: field. The others are kept underneath for a window the child tree
    #: cannot read.
    TIERS = ('win32', 'msaa', 'uia')

    #: Below this the tier has not really read the window.
    ENOUGH = 3

    def read(self):
        """What is on the window now, as a screen."""
        reader = _titan_access()
        if reader is None or not self.hwnd:
            return self.screen
        document = None
        for tier in self.TIERS:
            try:
                found = reader.build_for_window(self.hwnd, allow_ocr=False,
                                                prefer=tier)
            except Exception as error:
                self._note('mirror', '%s could not read the window: %s'
                           % (tier, error))
                continue
            if document is None:
                document = found
            if len(found.nodes or []) >= self.ENOUGH:
                document = found
                break
        if document is None:
            return self.screen
        with self._lock:
            self._nodes = list(document.nodes or [])
            self.screen = self._as_screen(document)
        self.changed.set()
        return self.screen

    def _as_screen(self, document):
        controls = [{'id': -2, 'kind': 'label',
                     'label': ('This is what Windows can see of %s\'s own '
                               'window, not the application describing '
                               'itself.' % self.name)}]
        inside = _client_area(self.hwnd)
        seen = set()
        for index, node in enumerate(self._nodes[:MAX_CONTROLS]):
            # **The frame around a window is not the window.** Read as it
            # comes, a browser answered with Minimise, Maximise, Close,
            # context help, the IME button and both scrollbars' arrows -
            # three times over, once per pane - before a word of the page.
            # Those live in the NON-CLIENT area, which is the one test
            # that does not depend on what language Windows is in.
            if not _within(getattr(node, 'rect', ()), inside):
                continue
            described = self._as_control(index, node)
            if described is None:
                continue
            # The same control reported by two panes is one control.
            mark = (described['kind'], described['label'],
                    tuple(getattr(node, 'rect', ()) or ()))
            if mark in seen:
                continue
            seen.add(mark)
            controls.append(described)
        screen = model.screen(self.hwnd, 'window',
                              getattr(document, 'title', '') or self.name,
                              controls, [], None)
        screen['mirror'] = True
        screen['source'] = getattr(document, 'source', '') or 'window'
        return screen

    def _as_control(self, index, node):
        role = str(getattr(node, 'role', '') or '')
        if role in SKIP:
            return None
        name = str(getattr(node, 'name', '') or '').strip()
        value = str(getattr(node, 'value', '') or '')
        kind = KINDS.get(role, 'label')
        # **A field that is empty is still a field.** The browser's
        # address bar has no name and, at rest, no text - and dropping it
        # took away the one control the whole application is for.
        if kind in ('text', 'multiline'):
            name = name or 'Field'
        elif not name and not value:
            return None
        # A container's CLASS name is not something on the screen. The
        # child-window tier falls back to the class when a window has no
        # text of its own, so a wx application answers "panel", "panel",
        # "wxWebView" between its real controls.
        if kind == 'label' and name.lower() in CONTAINERS:
            return None
        extra = {'enabled': 'unavailable' not in (getattr(node, 'states', ()) or ())}
        if kind in ('text', 'multiline'):
            extra['value'] = value
        elif kind == 'check':
            extra['value'] = 'checked' in (getattr(node, 'states', ()) or ())
        elif kind in ('list', 'table', 'tree'):
            # A mirrored list is one ROW - Windows reports the items as
            # separate entries - so it is offered as what it is rather
            # than as a list with nothing in it.
            kind = 'button' if value or name else 'label'
            extra = {'enabled': extra['enabled']}
        return model.control(index, kind, name or value, **extra)

    # -------------------------------------------------------------- act
    def tell(self, kind, **rest):
        """Do it to the real control, and read the window again."""
        if self.ended.is_set():
            return False
        self.changed.clear()
        try:
            if kind == 'press':
                self._press(rest.get('control'))
            elif kind == 'set':
                self._type(rest.get('control'), rest.get('value'))
            elif kind == 'key':
                self._key(str(rest.get('key') or ''))
            elif kind == 'quit':
                self.stop()
                return True
        except Exception as error:
            self._note('mirror', '%s: %s' % (type(error).__name__, error))
        time.sleep(0.25)
        self.read()
        return True

    def _node(self, index):
        try:
            index = int(index)
        except (TypeError, ValueError):
            return None
        with self._lock:
            if 0 <= index < len(self._nodes):
                return self._nodes[index]
        return None

    def _press(self, index):
        node = self._node(index)
        if node is None:
            return
        activate = getattr(node, 'activate', None)
        if callable(activate):
            activate()

    def _type(self, index, value):
        node = self._node(index)
        if node is None:
            return
        setter = getattr(node, 'set_value', None)
        if callable(setter):
            setter('' if value is None else str(value))
            return
        focus = getattr(node, 'focus', None)
        if callable(focus):
            focus()
        _send_text('' if value is None else str(value))

    def _key(self, key):
        if not key:
            return
        _foreground(self.hwnd)
        _send_key(key)

    # -------------------------------------------------------------- stop
    def stop(self):
        if self.process is not None:
            for step in (self.process.terminate, self.process.kill):
                if self.process.poll() is not None:
                    break
                try:
                    step()
                except Exception:
                    pass
                try:
                    self.process.wait(timeout=1.5)
                except Exception:
                    pass
            for pipe in ('stdout', 'stderr'):
                try:
                    stream = getattr(self.process, pipe, None)
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass
        self.status = self.status or 'finished'
        self.ended.set()
        self.changed.set()

    def ask_report(self):
        return []

    def _read_log(self):
        from src.app_ui import wire
        try:
            for raw in wire.lines(self.process.stderr):
                self._note('stderr', raw.decode('utf-8', 'replace').rstrip())
        except Exception:
            pass

    def _note(self, level, text):
        if len(self.log) >= 400:
            del self.log[0]
        self.log.append((level, text))


# --------------------------------------------------------------------------
# Windows, at arm's length
# --------------------------------------------------------------------------
def _client_area(hwnd):
    """The window's client rectangle in screen pixels, or () when it
    cannot be had - in which case nothing is filtered, because dropping
    everything would be worse than showing the furniture."""
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                        ('right', ctypes.c_long), ('bottom', ctypes.c_long)]

        class POINT(ctypes.Structure):
            _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]

        user32 = ctypes.windll.user32
        rect = RECT()
        if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return ()
        corner = POINT(rect.left, rect.top)
        user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(corner))
        return (corner.x, corner.y,
                corner.x + (rect.right - rect.left),
                corner.y + (rect.bottom - rect.top))
    except Exception:
        return ()


def _within(rect, area):
    """Is the control inside the client area? A control with no rectangle
    is kept: not knowing where something is is not a reason to hide it."""
    if not area or not rect or len(rect) < 4:
        return True
    left, top, right, bottom = rect[:4]
    # Its middle, so a control that merely overlaps the edge still counts.
    x, y = (left + right) / 2.0, (top + bottom) / 2.0
    return area[0] <= x <= area[2] and area[1] <= y <= area[3]


def _window_of(pid):
    """The application's own visible top-level window."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return 0
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, 4):        # GW_OWNER: not a top level
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        found.append(hwnd)
        return False

    try:
        user32.EnumWindows(each, 0)
    except Exception:
        return 0
    return found[0] if found else 0


def _foreground(hwnd):
    try:
        import ctypes
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _send_text(text):
    try:
        import keyboard
        keyboard.write(text)
    except Exception:
        pass


def _send_key(key):
    try:
        import keyboard
        keyboard.send(key.replace('escape', 'esc'))
    except Exception:
        pass


def _python():
    try:
        from src.titan_core.app_manager import get_python_executable
        found, _problem = get_python_executable()
        if found:
            return found
    except Exception:
        pass
    return sys.executable


_BOOT = '''\
import sys
sys.path.insert(0, r"%(root)s")
sys.path.insert(0, r"%(folder)s")
sys.argv = [r"%(entry)s"]
try:
    import runpy
    runpy.run_path(r"%(entry)s", run_name="__main__")
except SystemExit:
    pass
except BaseException:
    import traceback
    traceback.print_exc()
'''

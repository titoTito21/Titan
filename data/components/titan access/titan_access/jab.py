# -*- coding: utf-8 -*-
"""Java Access Bridge: what a Java program says about itself.

A Swing or AWT window exposes almost nothing to UI Automation - a pane, a
frame, and silence inside it - because Java speaks its own accessibility
language, the Java Access Bridge (JAB). NVDA reaches it through
`WindowsAccessBridge-64.dll` (Oracle's, shipped with every JRE since 7 and
switched on with `jabswitch -enable`); this does the same from Titan
Access, with ctypes and nothing else.

What is read: the control that has the focus (name, description, role,
states, its place among its siblings, its rectangle) and, for the virtual
window and browse mode, the tree under a window walked breadth-first.
Pressing is the control's own accessible action, and a text control's
contents come through the accessible text interface.

**The bridge needs a message loop on the thread that called
``Windows_run``** - Java answers over window messages - so this is
initialised on the engine's own Win32 thread (`engine._run`), which pumps.
Without the DLL (no Java, or the bridge not enabled) every answer here is
None, and the reader carries on with UI Automation as before.
"""

import ctypes
import os
import threading
from ctypes import wintypes

_LOCK = threading.RLock()
_state = {'dll': None, 'why': '', 'started': False, 'windows': 0,
          'reads': 0, 'failed': 0}

MAX_STRING = 1024
SHORT_STRING = 256
MAX_CHILDREN = 200

JOBJECT64 = ctypes.c_int64
VMID = ctypes.c_long


class AccessibleContextInfo(ctypes.Structure):
    _fields_ = [
        ('name', ctypes.c_wchar * MAX_STRING),
        ('description', ctypes.c_wchar * MAX_STRING),
        ('role', ctypes.c_wchar * SHORT_STRING),
        ('role_en_US', ctypes.c_wchar * SHORT_STRING),
        ('states', ctypes.c_wchar * SHORT_STRING),
        ('states_en_US', ctypes.c_wchar * SHORT_STRING),
        ('indexInParent', ctypes.c_int),
        ('childrenCount', ctypes.c_int),
        ('x', ctypes.c_int), ('y', ctypes.c_int),
        ('width', ctypes.c_int), ('height', ctypes.c_int),
        ('accessibleComponent', wintypes.BOOL),
        ('accessibleAction', wintypes.BOOL),
        ('accessibleSelection', wintypes.BOOL),
        ('accessibleText', wintypes.BOOL),
        ('accessibleInterfaces', wintypes.BOOL),
    ]


class AccessibleTextInfo(ctypes.Structure):
    _fields_ = [('charCount', ctypes.c_int), ('caretIndex', ctypes.c_int),
                ('indexAtPoint', ctypes.c_int)]


class AccessibleActions(ctypes.Structure):
    _fields_ = [('actionsCount', ctypes.c_int),
                ('actionInfo', (ctypes.c_wchar * SHORT_STRING) * 256)]


class AccessibleActionsToDo(ctypes.Structure):
    _fields_ = [('actionsCount', ctypes.c_int),
                ('actions', (ctypes.c_wchar * SHORT_STRING) * 32)]


#: Java's role names -> Titan Access's.
ROLES = {
    'push button': 'button', 'toggle button': 'button', 'check box': 'checkbox',
    'radio button': 'radio', 'combo box': 'combobox', 'list': 'list',
    'list item': 'listitem', 'tree': 'tree', 'tree item': 'treeitem',
    'menu': 'menu', 'menu bar': 'menubar', 'menu item': 'menuitem',
    'check menu item': 'menuitem', 'radio menu item': 'menuitem',
    'page tab': 'tab', 'page tab list': 'tabcontrol', 'slider': 'slider',
    'spinbox': 'spinner', 'progress bar': 'progressbar',
    'scroll bar': 'scrollbar', 'hyperlink': 'link', 'label': 'text',
    'text': 'edit', 'password text': 'password', 'table': 'table',
    'tool bar': 'toolbar', 'status bar': 'statusbar', 'panel': 'pane',
    'dialog': 'dialog', 'frame': 'window', 'window': 'window',
    'root pane': 'pane', 'layered pane': 'pane', 'glass pane': 'pane',
    'viewport': 'pane', 'scroll pane': 'pane', 'split pane': 'pane',
    'internal frame': 'window', 'icon': 'image', 'separator': 'separator',
    'group box': 'group', 'header': 'heading', 'editbar': 'edit',
    'filler': 'pane', 'canvas': 'pane', 'desktop pane': 'pane',
}

STATES = {
    'checked': 'checked', 'selected': 'selected', 'expanded': 'expanded',
    'collapsed': 'collapsed', 'pressed': 'pressed', 'enabled': None,
    'focused': 'focused', 'editable': None, 'multiselectable': None,
    'busy': 'busy', 'modal': None, 'showing': None, 'visible': None,
}

DLL_NAMES = ('WindowsAccessBridge-64.dll', 'WindowsAccessBridge-32.dll',
             'windowsaccessbridge-64.dll', 'windowsaccessbridge.dll')


def report():
    with _LOCK:
        return dict(_state, available=_state['dll'] is not None)


def _candidates():
    found = []
    for folder in (os.environ.get('WINDIR', r'C:\Windows') + r'\System32',
                   os.environ.get('JAVA_HOME', '') + r'\bin',
                   os.environ.get('JAVA_HOME', '') + r'\jre\bin'):
        for name in DLL_NAMES:
            path = os.path.join(folder, name)
            if folder and os.path.isfile(path):
                found.append(path)
    for root in (os.environ.get('ProgramFiles', r'C:\Program Files'),
                 os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')):
        for vendor in ('Java', 'Eclipse Adoptium', 'Zulu', 'Amazon Corretto',
                       'Microsoft', 'BellSoft'):
            base = os.path.join(root, vendor)
            if not os.path.isdir(base):
                continue
            try:
                for release in os.listdir(base):
                    for sub in ('bin', os.path.join('jre', 'bin')):
                        for name in DLL_NAMES:
                            path = os.path.join(base, release, sub, name)
                            if os.path.isfile(path):
                                found.append(path)
            except Exception:                        # noqa: BLE001
                continue
    return found


def start():
    """Load the bridge and start it on THIS thread. ``(ok, why)``.

    Must be called on a thread that pumps messages; the engine's own.
    """
    with _LOCK:
        if _state['dll'] is not None:
            return True, ''
    paths = _candidates()
    if not paths:
        with _LOCK:
            _state['why'] = 'no Java Access Bridge on this machine'
        return False, _state['why']
    for path in paths:
        try:
            dll = ctypes.WinDLL(path)
            dll.Windows_run()
            _declare(dll)
        except Exception as error:                   # noqa: BLE001
            with _LOCK:
                _state['why'] = '%s: %s' % (path, error)
            continue
        with _LOCK:
            _state['dll'] = dll
            _state['started'] = True
            _state['why'] = ''
        return True, ''
    return False, _state['why']


def _declare(dll):
    dll.isJavaWindow.argtypes = [wintypes.HWND]
    dll.isJavaWindow.restype = wintypes.BOOL
    dll.getAccessibleContextFromHWND.argtypes = [
        wintypes.HWND, ctypes.POINTER(VMID), ctypes.POINTER(JOBJECT64)]
    dll.getAccessibleContextFromHWND.restype = wintypes.BOOL
    dll.getAccessibleContextWithFocus.argtypes = [
        wintypes.HWND, ctypes.POINTER(VMID), ctypes.POINTER(JOBJECT64)]
    dll.getAccessibleContextWithFocus.restype = wintypes.BOOL
    dll.getAccessibleContextInfo.argtypes = [
        VMID, JOBJECT64, ctypes.POINTER(AccessibleContextInfo)]
    dll.getAccessibleContextInfo.restype = wintypes.BOOL
    dll.getAccessibleChildFromContext.argtypes = [VMID, JOBJECT64, ctypes.c_int]
    dll.getAccessibleChildFromContext.restype = JOBJECT64
    dll.getAccessibleParentFromContext.argtypes = [VMID, JOBJECT64]
    dll.getAccessibleParentFromContext.restype = JOBJECT64
    dll.releaseJavaObject.argtypes = [VMID, JOBJECT64]
    dll.releaseJavaObject.restype = None
    dll.getAccessibleTextInfo.argtypes = [
        VMID, JOBJECT64, ctypes.POINTER(AccessibleTextInfo), ctypes.c_int,
        ctypes.c_int]
    dll.getAccessibleTextInfo.restype = wintypes.BOOL
    dll.getAccessibleTextRange.argtypes = [
        VMID, JOBJECT64, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p,
        ctypes.c_short]
    dll.getAccessibleTextRange.restype = wintypes.BOOL
    dll.getAccessibleActions.argtypes = [
        VMID, JOBJECT64, ctypes.POINTER(AccessibleActions)]
    dll.getAccessibleActions.restype = wintypes.BOOL
    dll.doAccessibleActions.argtypes = [
        VMID, JOBJECT64, ctypes.POINTER(AccessibleActionsToDo),
        ctypes.POINTER(ctypes.c_int)]
    dll.doAccessibleActions.restype = wintypes.BOOL
    dll.requestFocus.argtypes = [VMID, JOBJECT64]
    dll.requestFocus.restype = wintypes.BOOL


def available():
    with _LOCK:
        return _state['dll'] is not None


def is_java_window(hwnd):
    dll = _state['dll']
    if dll is None or not hwnd:
        return False
    try:
        return bool(dll.isJavaWindow(int(hwnd)))
    except Exception:                                # noqa: BLE001
        return False


class Context:
    """One Java accessible, released when it is dropped."""

    def __init__(self, vmid, handle):
        self.vmid, self.handle = vmid, handle
        self._info = None

    def __del__(self):
        try:
            dll = _state['dll']
            if dll is not None and self.handle:
                dll.releaseJavaObject(self.vmid, self.handle)
        except Exception:                            # noqa: BLE001
            pass

    def info(self):
        if self._info is not None:
            return self._info
        dll = _state['dll']
        found = AccessibleContextInfo()
        try:
            if not dll.getAccessibleContextInfo(self.vmid, self.handle,
                                                ctypes.byref(found)):
                return None
        except Exception:                            # noqa: BLE001
            return None
        self._info = found
        with _LOCK:
            _state['reads'] += 1
        return found

    def child(self, index):
        dll = _state['dll']
        try:
            handle = dll.getAccessibleChildFromContext(self.vmid, self.handle,
                                                       int(index))
        except Exception:                            # noqa: BLE001
            return None
        return Context(self.vmid, handle) if handle else None

    def children(self, limit=MAX_CHILDREN):
        info = self.info()
        if info is None:
            return []
        found = []
        for index in range(min(int(info.childrenCount), limit)):
            child = self.child(index)
            if child is not None:
                found.append(child)
        return found

    def text(self, limit=4000):
        info = self.info()
        if info is None or not info.accessibleText:
            return ''
        dll = _state['dll']
        text_info = AccessibleTextInfo()
        try:
            if not dll.getAccessibleTextInfo(self.vmid, self.handle,
                                             ctypes.byref(text_info), 0, 0):
                return ''
            count = min(int(text_info.charCount), limit)
            if count <= 0:
                return ''
            buffer = ctypes.create_unicode_buffer(count + 1)
            if not dll.getAccessibleTextRange(self.vmid, self.handle, 0,
                                              count - 1, buffer, count + 1):
                return ''
            return str(buffer.value or '')
        except Exception:                            # noqa: BLE001
            return ''

    def press(self):
        """The control's first accessible action, or focus it."""
        dll = _state['dll']
        actions = AccessibleActions()
        try:
            if dll.getAccessibleActions(self.vmid, self.handle,
                                        ctypes.byref(actions)) \
                    and actions.actionsCount > 0:
                todo = AccessibleActionsToDo()
                todo.actionsCount = 1
                todo.actions[0].value = actions.actionInfo[0].value
                failure = ctypes.c_int(0)
                return bool(dll.doAccessibleActions(self.vmid, self.handle,
                                                    ctypes.byref(todo),
                                                    ctypes.byref(failure)))
            return bool(dll.requestFocus(self.vmid, self.handle))
        except Exception:                            # noqa: BLE001
            return False


def _context(getter, hwnd):
    dll = _state['dll']
    if dll is None or not hwnd:
        return None
    vmid = VMID(0)
    handle = JOBJECT64(0)
    try:
        if not getter(int(hwnd), ctypes.byref(vmid), ctypes.byref(handle)):
            return None
    except Exception:                                # noqa: BLE001
        return None
    return Context(vmid.value, handle.value) if handle.value else None


def focus(hwnd):
    """The control that has the focus in a Java window, or None."""
    dll = _state['dll']
    return _context(dll.getAccessibleContextWithFocus, hwnd) if dll else None


def root(hwnd):
    dll = _state['dll']
    return _context(dll.getAccessibleContextFromHWND, hwnd) if dll else None


def role_of(info):
    return ROLES.get(str(info.role_en_US or '').lower(), 'unknown')


def states_of(info):
    found = set()
    for word in str(info.states_en_US or '').split(','):
        mapped = STATES.get(word.strip().lower())
        if mapped:
            found.add(mapped)
    if 'enabled' not in str(info.states_en_US or '').lower():
        found.add('unavailable')
    return found


def describe(context):
    """``AccessibleObject`` for a Java accessible, or None."""
    info = context.info() if context is not None else None
    if info is None:
        return None
    try:
        from titan_access.contracts import AccessibleObject
    except Exception:                                # noqa: BLE001
        return None
    obj = AccessibleObject(native=context, provider='jab')
    obj.name = str(info.name or '')
    obj.description = str(info.description or '')
    obj.role = role_of(info)
    obj.states = states_of(info)
    obj.bounds = (int(info.x), int(info.y), int(info.width), int(info.height))
    obj.pos_in_set = int(info.indexInParent) + 1 if info.indexInParent >= 0 else 0
    if info.accessibleText and obj.role in ('edit', 'password', 'text'):
        obj.value = context.text(400) if obj.role != 'password' else ''
    return obj


def nodes(hwnd, limit=400):
    """The tree under a Java window, breadth first, as ``VNode`` rows."""
    top = root(hwnd)
    if top is None:
        return []
    try:
        from titan_access.virtual_buffer import VNode
    except Exception:                                # noqa: BLE001
        return []
    found = []
    queue = [top]
    while queue and len(found) < limit:
        context = queue.pop(0)
        info = context.info()
        if info is None:
            continue
        queue.extend(context.children())
        role = role_of(info)
        name = str(info.name or '').strip()
        if not name and role in ('pane', 'window', 'unknown'):
            continue
        node = VNode()
        node.name = name
        node.role = role
        node.states = tuple(states_of(info))
        node.rect = (int(info.x), int(info.y), int(info.x + info.width),
                     int(info.y + info.height))
        node.source = 'jab'
        node.hwnd = int(hwnd)
        node.element = context
        found.append(node)
    with _LOCK:
        _state['windows'] += 1
    return found

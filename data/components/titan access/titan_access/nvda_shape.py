# -*- coding: utf-8 -*-
"""Titan Access's objects in the shape the shared reader modules read.

The modules shared with the NVDA add-on - markers, monitors, procedures,
labels, reader modules, live regions, the drawn-window watcher, the guest
reader - read a control through NVDA's attribute names: ``windowClassName``,
``role.name``, ``UIAAutomationId``, ``windowHandle``, ``processID``,
``location`` with ``left``/``top``/``width``/``height``, ``children``,
``parent``, ``appModule.appName``, ``actionCount`` / ``doAction``,
``setFocus``. Titan Access's :class:`AccessibleObject` has the same facts
under its own names. Rather than teach forty shared modules a second
spelling - which is how two readers stop agreeing - one adapter gives a
Titan Access object the NVDA spelling, lazily, and the original stays
reachable as ``.original``.

:class:`Hooks` is the other half: the six answers `portable/readerApi.py`
asks of the reader underneath (what is in front, what has the focus, what
is at a point, focus this, do this, press this key), each answered out of
this reader and handed back already adapted.
"""

import ctypes
import os

#: Titan Access's role names in NVDA's spelling. `icons.ROLE_ALIASES` does
#: the reverse job for the icon table; this is the general one.
ROLE_NAMES = {
    'button': 'BUTTON', 'split_button': 'SPLITBUTTON', 'edit': 'EDITABLETEXT',
    'password': 'PASSWORDEDIT', 'document': 'DOCUMENT', 'checkbox': 'CHECKBOX',
    'radio': 'RADIOBUTTON', 'combobox': 'COMBOBOX', 'list': 'LIST',
    'listitem': 'LISTITEM', 'tree': 'TREEVIEW', 'treeitem': 'TREEVIEWITEM',
    'menu': 'POPUPMENU', 'menubar': 'MENUBAR', 'menuitem': 'MENUITEM',
    'tab': 'TAB', 'tabcontrol': 'TABCONTROL', 'slider': 'SLIDER',
    'spinner': 'SPINBUTTON', 'progressbar': 'PROGRESSBAR',
    'scrollbar': 'SCROLLBAR', 'link': 'LINK', 'text': 'STATICTEXT',
    'heading': 'HEADING', 'image': 'GRAPHIC', 'table': 'TABLE', 'row': 'TABLEROW',
    'cell': 'TABLECELL', 'toolbar': 'TOOLBAR', 'statusbar': 'STATUSBAR',
    'group': 'GROUPING', 'dialog': 'DIALOG', 'window': 'WINDOW', 'pane': 'PANE',
    'separator': 'SEPARATOR', 'grid': 'TABLE', 'griditem': 'DATAITEM',
    'unknown': 'UNKNOWN',
}

STATE_NAMES = {
    'checked': 'CHECKED', 'partially_checked': 'HALFCHECKED',
    'selected': 'SELECTED', 'expanded': 'EXPANDED', 'collapsed': 'COLLAPSED',
    'pressed': 'PRESSED', 'unavailable': 'UNAVAILABLE', 'readonly': 'READONLY',
    'required': 'REQUIRED', 'protected': 'PROTECTED', 'busy': 'BUSY',
    'haspopup': 'HASPOPUP', 'offscreen': 'OFFSCREEN', 'focused': 'FOCUSED',
    'focusable': 'FOCUSABLE',
}


_ROLE_KEYS = {nvda: ours for ours, nvda in ROLE_NAMES.items()}
_STATE_KEYS = {nvda: ours for ours, nvda in STATE_NAMES.items()}


class _Named:
    """Something with a ``.name`` - NVDA's roles and states are enums.

    ``displayString`` is what NVDA's enums answer with the word in the
    user's own language, and the shared modules ask for it first
    (`context.role_name`); without it the virtual window read every row
    as "MENUBAR" and "EDITABLETEXT". It answers out of this reader's own
    catalogue.
    """

    def __init__(self, name):
        self.name = str(name or '')

    @property
    def displayString(self):
        try:
            from titan_access import localization
            key = _ROLE_KEYS.get(self.name)
            if key:
                return localization.role_label(key)
            key = _STATE_KEYS.get(self.name)
            if key:
                return localization.state_label(key)
        except Exception:                            # noqa: BLE001
            pass
        return ''

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    def __eq__(self, other):
        return str(getattr(other, 'name', other)) == self.name

    def __hash__(self):
        return hash(self.name)


class _Rect:
    def __init__(self, left, top, width, height):
        self.left, self.top, self.width, self.height = (int(left), int(top),
                                                        int(width), int(height))

    def __iter__(self):
        return iter((self.left, self.top, self.width, self.height))


class _AppModule:
    def __init__(self, name):
        self.appName = name


_names_by_pid = {}


def executable_of(pid):
    """The executable's base name for a process, lower-cased, or ''."""
    pid = int(pid or 0)
    if not pid:
        return ''
    found = _names_by_pid.get(pid)
    if found is not None:
        return found
    name = ''
    try:
        import psutil
        name = os.path.splitext(psutil.Process(pid).name())[0].lower()
    except Exception:                                # noqa: BLE001
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                buffer = ctypes.create_unicode_buffer(1024)
                size = ctypes.c_uint(1024)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buffer,
                                                       ctypes.byref(size)):
                    name = os.path.splitext(
                        os.path.basename(buffer.value))[0].lower()
                kernel32.CloseHandle(handle)
        except Exception:                            # noqa: BLE001
            name = ''
    _names_by_pid[pid] = name
    return name


class Adapted:
    """One Titan Access object, read as the shared modules read NVDA's."""

    def __init__(self, original, provider=None):
        self.original = original
        self._provider = provider
        self._children = None
        self._parent = None
        self._headers = None

    # -- columns ------------------------------------------------------ #
    # NVDA's `sysListView32.ListItem` answers `_getColumnHeader(index)`,
    # `_getColumnContent(index)` and `columnCount`, and that is what the
    # reader-module schema (`headers_of`) and the semantics layer read a
    # row's columns through. A UI Automation list in report mode carries
    # its headings as a HeaderControl child with one HeaderItemControl per
    # column, and a row's cells as its own children - so the same three
    # names are answered here, and a module written against "Type" matches
    # this reader's lists as it matches NVDA's.
    def _header_items(self):
        if self._headers is not None:
            return self._headers
        found = []
        native = getattr(self.original, 'native', None)
        # The first few children only, one sibling at a time: the header
        # of a report list is its first child, and `GetChildren()` on a
        # list of three thousand rows fetches all three thousand before
        # anything is looked at - once per focused row.
        first = getattr(native, 'GetFirstChildControl', None)
        if callable(first):
            try:
                child = first()
                for _step in range(8):
                    if child is None:
                        break
                    if getattr(child, 'ControlTypeName', '') == 'HeaderControl':
                        for item in (child.GetChildren() or [])[:32]:
                            if getattr(item, 'ControlTypeName', '') == \
                                    'HeaderItemControl':
                                found.append(str(item.Name or '').strip())
                        break
                    child = child.GetNextSiblingControl()
            except Exception:                        # noqa: BLE001
                found = []
        self._headers = found
        return found

    def _headings(self):
        """This list's headings, or - for a row - its list's."""
        own = self._header_items()
        if own:
            return own
        parent = self.parent
        if parent is not None and isinstance(parent, Adapted):
            return parent._header_items()
        return []

    @property
    def columnCount(self):
        return len(self._headings())

    def _getColumnHeader(self, index):
        headings = self._headings()
        try:
            index = int(index)
        except (TypeError, ValueError):
            return ''
        return headings[index - 1] if 1 <= index <= len(headings) else ''

    def _getColumnContent(self, index):
        cells = [str(getattr(child, 'name', '') or '') for child in self.children]
        try:
            index = int(index)
        except (TypeError, ValueError):
            return ''
        return cells[index - 1] if 1 <= index <= len(cells) else ''

    # -- identity ----------------------------------------------------- #
    @property
    def name(self):
        return str(getattr(self.original, 'name', '') or '')

    @property
    def value(self):
        return str(getattr(self.original, 'value', '') or '')

    @property
    def description(self):
        return str(getattr(self.original, 'description', '') or '')

    @property
    def windowText(self):
        return self.name

    @property
    def role(self):
        role = str(getattr(self.original, 'role', '') or 'unknown')
        return _Named(ROLE_NAMES.get(role, role.upper()))

    @property
    def states(self):
        found = set()
        for state in (getattr(self.original, 'states', None) or ()):
            found.add(_Named(STATE_NAMES.get(str(state), str(state).upper())))
        return found

    @property
    def windowClassName(self):
        return str(getattr(self.original, 'class_name', '') or '')

    @property
    def UIAAutomationId(self):
        return str(getattr(self.original, 'automation_id', '') or '')

    @property
    def windowHandle(self):
        return int(getattr(self.original, 'hwnd', 0) or 0)

    @property
    def processID(self):
        return int(getattr(self.original, 'process_id', 0) or 0)

    @property
    def appModule(self):
        return _AppModule(executable_of(self.processID) or 'unknown')

    @property
    def location(self):
        bounds = getattr(self.original, 'bounds', None) or (0, 0, 0, 0)
        return _Rect(*bounds)

    @property
    def indexInParent(self):
        return -1

    # -- the tree ----------------------------------------------------- #
    def _wrap(self, native):
        if native is None or self._provider is None:
            return None
        try:
            obj = self._provider.element_to_object(native)
        except Exception:                            # noqa: BLE001
            obj = None
        return Adapted(obj, self._provider) if obj is not None else None

    @property
    def children(self):
        if self._children is not None:
            return self._children
        found = []
        native = getattr(self.original, 'native', None)
        get = getattr(native, 'GetChildren', None)
        if callable(get):
            try:
                for child in (get() or [])[:400]:
                    wrapped = self._wrap(child)
                    if wrapped is not None:
                        found.append(wrapped)
            except Exception:                        # noqa: BLE001
                pass
        self._children = found
        return found

    @property
    def parent(self):
        if self._parent is not None:
            return self._parent
        native = getattr(self.original, 'native', None)
        get = getattr(native, 'GetParentControl', None)
        if callable(get):
            try:
                self._parent = self._wrap(get())
            except Exception:                        # noqa: BLE001
                self._parent = None
        return self._parent

    # -- acting ------------------------------------------------------- #
    @property
    def actionCount(self):
        return 1 if self._pattern() is not None else 0

    def getActionName(self, index=0):
        found = self._pattern()
        return found[0] if found else ''

    def _pattern(self):
        native = getattr(self.original, 'native', None)
        if native is None:
            return None
        for getter, method in (('GetInvokePattern', 'Invoke'),
                               ('GetTogglePattern', 'Toggle'),
                               ('GetSelectionItemPattern', 'Select'),
                               ('GetExpandCollapsePattern', 'Expand'),
                               ('GetLegacyIAccessiblePattern',
                                'DoDefaultAction')):
            get = getattr(native, getter, None)
            if not callable(get):
                continue
            try:
                pattern = get()
            except Exception:                        # noqa: BLE001
                pattern = None
            if pattern is not None and callable(getattr(pattern, method, None)):
                return method, pattern
        return None

    def doAction(self, index=0):
        found = self._pattern()
        if not found:
            raise NotImplementedError('no action')
        method, pattern = found
        getattr(pattern, method)()

    def setFocus(self):
        native = getattr(self.original, 'native', None)
        put = getattr(native, 'SetFocus', None)
        if not callable(put):
            raise NotImplementedError('cannot focus')
        if not put():
            raise RuntimeError('focus refused')

    def __repr__(self):
        return '<Adapted %s %r>' % (self.role.name, self.name[:30])


def adapt(obj, provider=None):
    """``Adapted`` for a Titan Access object; an adapted one as it is."""
    if obj is None or isinstance(obj, Adapted):
        return obj
    return Adapted(obj, provider)


def original_of(obj):
    return getattr(obj, 'original', obj)


class Hooks:
    """What `readerApi` asks of this reader."""

    def __init__(self, engine):
        self.engine = engine

    def _provider(self):
        return getattr(self.engine, 'provider', None)

    def foreground(self):
        provider = self._provider()
        if provider is None:
            return None
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            obj = provider.object_from_handle(hwnd) if hwnd else None
        except Exception:                            # noqa: BLE001
            obj = None
        return adapt(obj, provider)

    def focus(self):
        obj = getattr(self.engine, 'current_object', None)
        if obj is None:
            provider = self._provider()
            try:
                obj = provider.get_focused_object() if provider else None
            except Exception:                        # noqa: BLE001
                obj = None
        return adapt(obj, self._provider())

    def object_at(self, x, y):
        provider = self._provider()
        if provider is None:
            return None
        try:
            return adapt(provider.object_from_point(int(x), int(y)), provider)
        except Exception:                            # noqa: BLE001
            return None

    def set_focus(self, obj):
        try:
            adapt(obj, self._provider()).setFocus()
            return True
        except Exception:                            # noqa: BLE001
            return False

    def navigate_to(self, obj):
        try:
            self.engine.announce_object(original_of(obj), for_navigation=True)
            return True
        except Exception:                            # noqa: BLE001
            return False

    def do_action(self, obj):
        try:
            adapt(obj, self._provider()).doAction(0)
            return True
        except Exception:                            # noqa: BLE001
            return False

    @staticmethod
    def _key_name(name):
        """NVDA's key spelling into the `keyboard` library's."""
        parts = []
        for part in str(name or '').split('+'):
            part = part.strip().lower()
            parts.append({'control': 'ctrl', 'windows': 'win',
                          'numpadenter': 'enter', 'upArrow': 'up',
                          'uparrow': 'up', 'downarrow': 'down',
                          'leftarrow': 'left', 'rightarrow': 'right',
                          'pageup': 'page up', 'pagedown': 'page down'}
                         .get(part, part))
        return '+'.join(parts)

    def send_key(self, name):
        try:
            import keyboard
            keyboard.send(self._key_name(name))
            return True
        except Exception:                            # noqa: BLE001
            return False

    def type_text(self, text):
        try:
            import keyboard
            keyboard.write(str(text))
            return True
        except Exception:                            # noqa: BLE001
            return False

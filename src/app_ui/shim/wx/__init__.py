# -*- coding: utf-8 -*-
"""wx, as far as an application whose interface is somewhere else needs it.

Put first on `sys.path` when a TCE application is launched in this mode,
so the application's own `import wx` reaches here. The application is not
modified and cannot tell.

What is implemented is what Titan's applications measurably use: 17 widget
classes, and of the 3286 method calls across all of them a fifth is layout
that a list-shaped interface throws away. What is NOT implemented answers
instead of raising - see `_titan_runtime.Runtime.refuse` and `_Unknown`.
"""

from ._titan_runtime import RUNTIME, model

# --------------------------------------------------------------------------
# The ids and flags an application really names. Everything else is made up
# on demand by `__getattr__`, which is what keeps the long tail from being a
# wall: 98 of the wx names Titan's applications use are used exactly once.
# --------------------------------------------------------------------------
ID_ANY = -1
ID_OK, ID_CANCEL, ID_YES, ID_NO, ID_CLOSE = 5100, 5101, 5103, 5104, 5505
ID_NEW, ID_OPEN, ID_SAVE, ID_SAVEAS, ID_EXIT = 5002, 5000, 5003, 5004, 5006
ID_ABOUT, ID_PREFERENCES, ID_DELETE, ID_COPY, ID_PASTE = 5014, 5022, 5011, 5032, 5033
NOT_FOUND = -1

OK, CANCEL, YES_NO, YES, NO, APPLY, CLOSE = 4, 16, 10, 2, 8, 32, 64
ICON_ERROR, ICON_INFORMATION, ICON_QUESTION, ICON_WARNING = 512, 2048, 1024, 256
ICON_EXCLAMATION, ICON_HAND = 256, 512

VERTICAL, HORIZONTAL, BOTH = 8, 4, 12
ALL, LEFT, RIGHT, TOP, BOTTOM, EXPAND = 0xF, 0x10, 0x20, 0x40, 0x80, 0x2000
ALIGN_CENTER = ALIGN_CENTRE = 0x900
TE_MULTILINE, TE_READONLY, TE_PASSWORD, TE_PROCESS_ENTER = 32, 16, 2048, 1024
LC_REPORT, LC_LIST, LC_ICON, LC_SINGLE_SEL = 32, 2048, 1024, 16384
LB_SINGLE, LB_MULTIPLE, LB_EXTENDED = 0, 8, 16
CB_READONLY, CB_DROPDOWN = 16, 4
DEFAULT_FRAME_STYLE = 541072960
DEFAULT_DIALOG_STYLE = 536877120
ACCEL_CTRL, ACCEL_ALT, ACCEL_SHIFT, ACCEL_NORMAL = 2, 1, 4, 0

WXK_RETURN, WXK_NUMPAD_ENTER, WXK_ESCAPE, WXK_SPACE = 13, 370, 27, 32
WXK_UP, WXK_DOWN, WXK_LEFT, WXK_RIGHT = 315, 317, 314, 316
WXK_BACK, WXK_DELETE, WXK_TAB, WXK_HOME, WXK_END = 8, 127, 9, 313, 312
WXK_F1, WXK_F2, WXK_F3, WXK_F4, WXK_F5 = 340, 341, 342, 343, 344
WXK_PAGEUP, WXK_PAGEDOWN = 366, 367

#: An event is only ever compared and bound, never read, so a name is
#: enough to be one.
class _EventKind(object):
    __slots__ = ('name',)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return 'EVT_%s' % self.name


EVT_BUTTON = _EventKind('BUTTON')
EVT_MENU = _EventKind('MENU')
EVT_CLOSE = _EventKind('CLOSE')
EVT_TEXT = _EventKind('TEXT')
EVT_TEXT_ENTER = _EventKind('TEXT_ENTER')
EVT_CHECKBOX = _EventKind('CHECKBOX')
EVT_CHOICE = _EventKind('CHOICE')
EVT_COMBOBOX = _EventKind('COMBOBOX')
EVT_LISTBOX = _EventKind('LISTBOX')
EVT_LISTBOX_DCLICK = _EventKind('LISTBOX_DCLICK')
EVT_LIST_ITEM_ACTIVATED = _EventKind('LIST_ITEM_ACTIVATED')
EVT_LIST_ITEM_SELECTED = _EventKind('LIST_ITEM_SELECTED')
EVT_TREE_ITEM_ACTIVATED = _EventKind('TREE_ITEM_ACTIVATED')
EVT_KEY_DOWN = _EventKind('KEY_DOWN')
EVT_CHAR_HOOK = _EventKind('CHAR_HOOK')
EVT_SLIDER = _EventKind('SLIDER')
EVT_SPINCTRL = _EventKind('SPINCTRL')
EVT_TIMER = _EventKind('TIMER')
EVT_SIZE = _EventKind('SIZE')
EVT_SHOW = _EventKind('SHOW')
EVT_ICONIZE = _EventKind('ICONIZE')
EVT_ACTIVATE = _EventKind('ACTIVATE')
EVT_NOTEBOOK_PAGE_CHANGED = _EventKind('NOTEBOOK_PAGE_CHANGED')
EVT_CHECKLISTBOX = _EventKind('CHECKLISTBOX')


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------
class Event(object):
    def __init__(self, source=None, identifier=-1, key=0, string=''):
        self._source = source
        self._id = identifier
        self._key = key
        self._string = string
        self._skipped = False
        self._veto = False

    def GetId(self):
        return self._id

    def GetEventObject(self):
        return self._source

    def GetKeyCode(self):
        return self._key

    def GetString(self):
        return self._string

    def GetSelection(self):
        return getattr(self._source, '_index', -1)

    def GetIndex(self):
        return getattr(self._source, '_index', -1)

    def GetInt(self):
        return getattr(self._source, '_index', -1)

    def Skip(self, skip=True):
        self._skipped = bool(skip)

    def GetSkipped(self):
        return self._skipped

    def Veto(self):
        self._veto = True

    def CanVeto(self):
        return True

    # A key event answers about the modifiers; the interface says which
    # ones it sent, and an interface that says nothing means none.
    def ControlDown(self):
        return bool(getattr(self, '_ctrl', False))

    def ShiftDown(self):
        return bool(getattr(self, '_shift', False))

    def AltDown(self):
        return bool(getattr(self, '_alt', False))

    def CmdDown(self):
        return self.ControlDown()


CommandEvent = KeyEvent = CloseEvent = ListEvent = TreeEvent = Event


# --------------------------------------------------------------------------
# Every control
# --------------------------------------------------------------------------
class _Widget(object):
    """What every control here has. A control is a thing with a name, a
    kind and a value; where it sits is not part of it."""

    _kind = 'label'

    def __init__(self, parent=None, identifier=ID_ANY, label='', **kw):
        self._parent = parent
        self._label = str(label or kw.get('label', '') or '')
        self._name = ''
        self._value = None
        self._enabled = True
        self._shown = True
        self._handlers = []
        self._children = []
        self._alive = True
        RUNTIME.register(self)
        window = _window_of(parent)
        if window is not None and window is not self:
            window._adopt(self)
        RUNTIME.changed()

    # ------------------------------------------------------------ naming
    def SetName(self, name):
        self._name = str(name or '')
        RUNTIME.changed()

    def GetName(self):
        return self._name or self._label

    def SetLabel(self, label):
        self._label = str(label or '')
        RUNTIME.changed()

    def GetLabel(self):
        return self._label

    SetTitle = SetLabel
    GetTitle = GetLabel

    def label(self):
        """**The accessible name first.** Titan's applications call
        `SetName` on every control precisely because they are written for
        people who cannot see them, so it is the best label there is."""
        return self._name or self._label or ''

    # ------------------------------------------------------------- state
    def Enable(self, enable=True):
        self._enabled = bool(enable)
        RUNTIME.changed()
        return True

    def Disable(self):
        return self.Enable(False)

    def IsEnabled(self):
        return self._enabled

    def Show(self, show=True):
        self._shown = bool(show)
        RUNTIME.changed()
        return True

    def Hide(self):
        return self.Show(False)

    def IsShown(self):
        return self._shown

    def SetFocus(self):
        window = _window_of(self._parent) or _window_of(self)
        if window is not None:
            window._focus = self._id
        RUNTIME.changed()

    def Destroy(self):
        self._alive = False
        RUNTIME.forget(self)
        return True

    def GetChildren(self):
        return list(self._children)

    def GetParent(self):
        return self._parent

    def GetId(self):
        return self._id

    def _adopt(self, child):
        self._children.append(child)

    # ------------------------------------------------------------ events
    def Bind(self, event, handler, source=None, id=ID_ANY, **_rest):
        self._handlers.append((event, handler, source, id))
        return True

    def Unbind(self, event, source=None, handler=None, **_rest):
        self._handlers = [entry for entry in self._handlers
                          if entry[0] is not event]
        return True

    def _fire(self, kind, **rest):
        """Run whatever is bound to this, on this control or on a window
        above it - `Bind(EVT_MENU, handler, item)` is bound on the frame
        and names the item, which is how every menu in every one of
        Titan's applications is written."""
        event = Event(source=self, identifier=self._id, **rest)
        for holder in self._up():
            for bound, handler, source, identifier in list(holder._handlers):
                if bound is not kind:
                    continue
                if source is not None and source is not self \
                        and getattr(source, '_id', None) != self._id:
                    continue
                if source is None and identifier not in (ID_ANY, self._id) \
                        and holder is not self:
                    continue
                if source is None and holder is not self \
                        and identifier == ID_ANY:
                    # A frame-wide binding with no source really is
                    # frame-wide; a control's own comes first.
                    pass
                handler(event)
                if not event.GetSkipped():
                    return True
        return False

    def _up(self):
        seen, holder = [], self
        while holder is not None and holder not in seen:
            seen.append(holder)
            holder = getattr(holder, '_parent', None)
        return seen

    def _pressed(self, message):
        self._fire(self._press_event())

    def _press_event(self):
        return EVT_BUTTON

    def _set_from_user(self, value):
        self._value = value
        RUNTIME.changed()

    # --------------------------------------------------------- described
    def describe(self):
        if not self._shown:
            return None
        return model.control(self._id, self._kind, self.label(),
                             enabled=self._enabled)

    # ------------------------------- everything a window is asked and is not
    def SetSizer(self, *_a, **_k):
        return None
    SetSizerAndFit = SetAutoLayout = Layout = Fit = SetSizer

    def SetSize(self, *_a, **_k):
        return None
    SetMinSize = SetMaxSize = SetPosition = SetClientSize = SetSize
    Centre = Center = CentreOnParent = CenterOnParent = SetSize
    SetBackgroundColour = SetForegroundColour = SetFont = SetSize
    Refresh = Update = Freeze = Thaw = SetIcon = SetSize
    SetToolTip = SetHelpText = SetDoubleBuffered = SetSize

    def GetSize(self, *_a, **_k):
        return (0, 0)
    GetClientSize = GetBestSize = GetSize

    def __getattr__(self, name):
        # A method nobody wrote answers nothing rather than raising. This
        # is the rule that lets an application be wrong about one thing
        # instead of stopping - and it is recorded, so what is missing can
        # be read rather than guessed at.
        if name.startswith('_'):
            raise AttributeError(name)
        RUNTIME.note_unknown('%s.%s' % (type(self).__name__, name))
        return _Silence(name)


class _Silence(object):
    """A method that is not here. Answers itself, so a chain of them is
    still only one thing that did not happen."""

    __slots__ = ('name',)

    def __init__(self, name):
        self.name = name

    def __call__(self, *_a, **_k):
        return None

    def __bool__(self):
        return False
    __nonzero__ = __bool__


def _window_of(widget):
    while widget is not None:
        if isinstance(widget, _Window):
            return widget
        widget = getattr(widget, '_parent', None)
    return None


# --------------------------------------------------------------------------
# The controls themselves
# --------------------------------------------------------------------------
class Panel(_Widget):
    """A box to put things in. It has no interface of its own here, and its
    children belong to the window, which is what a list-shaped interface
    renders."""
    _kind = 'panel'

    def describe(self):
        return None


class StaticText(_Widget):
    _kind = 'label'


class StaticBox(StaticText):
    pass


class Button(_Widget):
    _kind = 'button'

    def describe(self):
        if not self._shown:
            return None
        return model.control(self._id, 'button', self.label(),
                             enabled=self._enabled,
                             default=bool(getattr(self, '_default', False)))

    def SetDefault(self):
        self._default = True
        RUNTIME.changed()


class BitmapButton(Button):
    pass


class ToggleButton(Button):
    pass


class TextCtrl(_Widget):
    def __init__(self, parent=None, identifier=ID_ANY, value='', style=0, **kw):
        self._style = int(style or kw.pop('style', 0) or 0)
        _Widget.__init__(self, parent, identifier, **kw)
        self._value = str(value or kw.get('value', '') or '')
        self._insertion = len(self._value)

    @property
    def _kind(self):
        return 'multiline' if self._style & TE_MULTILINE else 'text'

    def GetValue(self):
        return self._value

    def SetValue(self, value):
        self._value = '' if value is None else str(value)
        RUNTIME.changed()

    ChangeValue = SetValue

    def AppendText(self, text):
        self._value += str(text or '')
        RUNTIME.changed()

    def WriteText(self, text):
        self.AppendText(text)

    def Clear(self):
        self.SetValue('')

    def GetNumberOfLines(self):
        return len(self._value.split('\n'))

    def SetInsertionPoint(self, where):
        self._insertion = int(where or 0)

    def SetInsertionPointEnd(self):
        self._insertion = len(self._value)

    def GetInsertionPoint(self):
        return self._insertion

    def SetEditable(self, editable=True):
        if editable:
            self._style &= ~TE_READONLY
        else:
            self._style |= TE_READONLY
        RUNTIME.changed()

    def IsEditable(self):
        return not self._style & TE_READONLY

    def describe(self):
        if not self._shown:
            return None
        return model.control(self._id, self._kind, self.label(),
                             value=self._value, enabled=self._enabled,
                             readonly=bool(self._style & TE_READONLY),
                             secret=bool(self._style & TE_PASSWORD))

    def _set_from_user(self, value):
        self._value = '' if value is None else str(value)
        RUNTIME.changed()
        self._fire(EVT_TEXT)


class SearchCtrl(TextCtrl):
    pass


class CheckBox(_Widget):
    _kind = 'check'

    def __init__(self, parent=None, identifier=ID_ANY, label='', **kw):
        _Widget.__init__(self, parent, identifier, label, **kw)
        self._value = False

    def GetValue(self):
        return bool(self._value)

    IsChecked = GetValue

    def SetValue(self, value):
        self._value = bool(value)
        RUNTIME.changed()

    def describe(self):
        if not self._shown:
            return None
        return model.control(self._id, 'check', self.label(),
                             value=bool(self._value), enabled=self._enabled)

    def _set_from_user(self, value):
        self._value = bool(value)
        RUNTIME.changed()
        self._fire(EVT_CHECKBOX)

    def _pressed(self, _message):
        self._set_from_user(not self._value)


class _Chooser(_Widget):
    """Everything with a list of options and one of them chosen."""

    def __init__(self, parent=None, identifier=ID_ANY, choices=None, **kw):
        _Widget.__init__(self, parent, identifier, **kw)
        self._options = [str(one) for one in (choices or kw.get('choices') or [])]
        self._index = -1
        if self._options:
            self._index = 0

    def Append(self, item, *_rest):
        if isinstance(item, (list, tuple)):
            self._options.extend(str(one) for one in item)
        else:
            self._options.append(str(item))
        if self._index < 0 and self._options:
            self._index = 0
        RUNTIME.changed()
        return len(self._options) - 1

    def AppendItems(self, items):
        for item in items or []:
            self.Append(item)

    def Set(self, items):
        self._options = [str(one) for one in (items or [])]
        self._index = 0 if self._options else -1
        RUNTIME.changed()

    def Clear(self):
        self._options = []
        self._index = -1
        RUNTIME.changed()

    def Delete(self, index):
        if 0 <= index < len(self._options):
            self._options.pop(index)
            self._index = min(self._index, len(self._options) - 1)
            RUNTIME.changed()

    def GetCount(self):
        return len(self._options)

    def GetSelection(self):
        return self._index

    def SetSelection(self, index):
        self._index = int(index) if index is not None else -1
        RUNTIME.changed()

    def GetString(self, index):
        return self._options[index] if 0 <= index < len(self._options) else ''

    def GetStringSelection(self):
        return self.GetString(self._index)

    def SetStringSelection(self, text):
        if text in self._options:
            self.SetSelection(self._options.index(text))
            return True
        return False

    def GetStrings(self):
        return list(self._options)

    def FindString(self, text):
        return self._options.index(text) if text in self._options else NOT_FOUND

    def _set_from_user(self, value):
        try:
            self._index = int(value)
        except (TypeError, ValueError):
            if value in self._options:
                self._index = self._options.index(value)
        RUNTIME.changed()
        self._fire(self._change_event())

    def _change_event(self):
        return EVT_CHOICE


class Choice(_Chooser):
    _kind = 'choice'

    def describe(self):
        if not self._shown:
            return None
        return model.control(self._id, 'choice', self.label(),
                             options=list(self._options), index=self._index,
                             enabled=self._enabled)


class ComboBox(Choice):
    def GetValue(self):
        return self.GetStringSelection()

    def SetValue(self, value):
        self.SetStringSelection(str(value or ''))

    def _change_event(self):
        return EVT_COMBOBOX


class ListBox(_Chooser):
    _kind = 'list'

    def describe(self):
        if not self._shown:
            return None
        return model.control(self._id, 'list', self.label(),
                             items=list(self._options), index=self._index,
                             enabled=self._enabled)

    def _change_event(self):
        return EVT_LISTBOX

    def _pressed(self, _message):
        if not self._fire(EVT_LISTBOX_DCLICK):
            self._fire(EVT_LISTBOX)


class CheckListBox(ListBox):
    def __init__(self, *args, **kw):
        ListBox.__init__(self, *args, **kw)
        self._checked = set()

    def Check(self, index, check=True):
        if check:
            self._checked.add(int(index))
        else:
            self._checked.discard(int(index))
        RUNTIME.changed()

    def IsChecked(self, index):
        return int(index) in self._checked

    def GetCheckedItems(self):
        return sorted(self._checked)

    def describe(self):
        described = ListBox.describe(self)
        if described is not None:
            described['checked'] = sorted(self._checked)
            described['multi'] = True
        return described


class ListCtrl(_Widget):
    """Rows with columns. tNotes' whole screen is one of these, in report
    mode, and so is tDownloader's."""

    _kind = 'table'

    def __init__(self, parent=None, identifier=ID_ANY, style=0, **kw):
        _Widget.__init__(self, parent, identifier, **kw)
        self._style = int(style or kw.get('style', 0) or 0)
        self._columns = []
        self._rows = []
        self._index = -1
        self._checked = set()

    # ---------------------------------------------------------- columns
    def InsertColumn(self, index, heading, *_a, **_k):
        self._columns.insert(int(index), str(heading))
        RUNTIME.changed()
        return int(index)

    def AppendColumn(self, heading, *_a, **_k):
        self._columns.append(str(heading))
        RUNTIME.changed()
        return len(self._columns) - 1

    def GetColumnCount(self):
        return len(self._columns)

    def SetColumnWidth(self, *_a, **_k):
        return None

    # ------------------------------------------------------------- rows
    def InsertItem(self, index, text='', *_a, **_k):
        row = [''] * max(1, len(self._columns))
        row[0] = str(text)
        self._rows.insert(int(index), row)
        if self._index < 0:
            self._index = 0
        RUNTIME.changed()
        return int(index)

    InsertStringItem = InsertItem

    def Append(self, row):
        cells = [str(cell) for cell in (row or [])]
        while len(cells) < max(1, len(self._columns)):
            cells.append('')
        self._rows.append(cells)
        if self._index < 0:
            self._index = 0
        RUNTIME.changed()
        return len(self._rows) - 1

    def SetItem(self, index, column, text, *_a, **_k):
        index, column = int(index), int(column)
        if 0 <= index < len(self._rows):
            while len(self._rows[index]) <= column:
                self._rows[index].append('')
            self._rows[index][column] = str(text)
            RUNTIME.changed()

    SetStringItem = SetItem

    def GetItemText(self, index, column=0):
        index, column = int(index), int(column)
        if 0 <= index < len(self._rows) and column < len(self._rows[index]):
            return self._rows[index][column]
        return ''

    def GetItemCount(self):
        return len(self._rows)

    def DeleteAllItems(self):
        self._rows = []
        self._index = -1
        self._checked = set()
        RUNTIME.changed()

    ClearAll = DeleteAllItems

    def DeleteItem(self, index):
        if 0 <= int(index) < len(self._rows):
            self._rows.pop(int(index))
            self._index = min(self._index, len(self._rows) - 1)
            RUNTIME.changed()

    # -------------------------------------------------------- selection
    def GetFirstSelected(self):
        return self._index

    def GetNextSelected(self, _after):
        return -1

    def GetSelectedItemCount(self):
        return 1 if self._index >= 0 else 0

    def Select(self, index, on=1):
        if on:
            self._index = int(index)
            RUNTIME.changed()

    def Focus(self, index):
        self.Select(index)

    def SetItemState(self, index, state, _mask):
        if state:
            self.Select(index)

    def GetItemState(self, index, _mask):
        return 4 if int(index) == self._index else 0

    def EnableCheckBoxes(self, enable=True):
        self._checkable = bool(enable)

    def CheckItem(self, index, check=True):
        if check:
            self._checked.add(int(index))
        else:
            self._checked.discard(int(index))
        RUNTIME.changed()

    def IsItemChecked(self, index):
        return int(index) in self._checked

    def describe(self):
        if not self._shown:
            return None
        return model.control(self._id, 'table', self.label(),
                             columns=list(self._columns),
                             items=[list(row) for row in self._rows],
                             index=self._index, enabled=self._enabled,
                             checked=sorted(self._checked) or None)

    def _set_from_user(self, value):
        try:
            self._index = int(value)
        except (TypeError, ValueError):
            return
        RUNTIME.changed()
        self._fire(EVT_LIST_ITEM_SELECTED)

    def _pressed(self, _message):
        self._fire(EVT_LIST_ITEM_ACTIVATED)


class Gauge(_Widget):
    _kind = 'gauge'

    def __init__(self, parent=None, identifier=ID_ANY, range=100, **kw):
        _Widget.__init__(self, parent, identifier, **kw)
        self._range = int(range or 100)
        self._value = 0

    def SetValue(self, value):
        self._value = int(value or 0)
        RUNTIME.changed()

    def GetValue(self):
        return self._value

    def SetRange(self, value):
        self._range = int(value or 100)
        RUNTIME.changed()

    def GetRange(self):
        return self._range

    def Pulse(self):
        return None

    def describe(self):
        if not self._shown:
            return None
        return model.control(self._id, 'gauge', self.label(),
                             value=self._value, maximum=self._range)


class Slider(_Widget):
    _kind = 'slider'

    def __init__(self, parent=None, identifier=ID_ANY, value=0,
                 minValue=0, maxValue=100, **kw):
        _Widget.__init__(self, parent, identifier, **kw)
        self._value = int(value or 0)
        self._min = int(minValue or 0)
        self._max = int(maxValue or 100)

    def GetValue(self):
        return self._value

    def SetValue(self, value):
        self._value = int(value or 0)
        RUNTIME.changed()

    def GetMin(self):
        return self._min

    def GetMax(self):
        return self._max

    def SetRange(self, low, high):
        self._min, self._max = int(low), int(high)
        RUNTIME.changed()

    def describe(self):
        if not self._shown:
            return None
        return model.control(self._id, 'slider', self.label(),
                             value=self._value, minimum=self._min,
                             maximum=self._max, enabled=self._enabled)

    def _set_from_user(self, value):
        try:
            self._value = max(self._min, min(self._max, int(value)))
        except (TypeError, ValueError):
            return
        RUNTIME.changed()
        self._fire(EVT_SLIDER)


class SpinCtrl(Slider):
    def _set_from_user(self, value):
        Slider._set_from_user(self, value)
        self._fire(EVT_SPINCTRL)


class TreeCtrl(_Widget):
    """Rows that nest. Described flat with a depth per row, because an
    interface made of speech reads a tree as indented rows anyway."""

    _kind = 'tree'

    def __init__(self, parent=None, identifier=ID_ANY, **kw):
        _Widget.__init__(self, parent, identifier, **kw)
        self._nodes = {}
        self._order = []
        self._root = None
        self._index = -1
        self._next = 0

    def AddRoot(self, text, *_a, **_k):
        self._root = self._add(text, None)
        return self._root

    def AppendItem(self, parent, text, *_a, **_k):
        return self._add(text, parent)

    def _add(self, text, parent):
        self._next += 1
        key = self._next
        depth = 0 if parent is None else self._nodes.get(parent, {}).get('depth', 0) + 1
        self._nodes[key] = {'text': str(text), 'parent': parent,
                            'depth': depth, 'data': None}
        self._order.append(key)
        if self._index < 0:
            self._index = 0
        RUNTIME.changed()
        return key

    def SetItemData(self, item, data):
        if item in self._nodes:
            self._nodes[item]['data'] = data

    def GetItemData(self, item):
        return self._nodes.get(item, {}).get('data')

    def GetItemText(self, item):
        return self._nodes.get(item, {}).get('text', '')

    def GetSelection(self):
        if 0 <= self._index < len(self._order):
            return self._order[self._index]
        return None

    def SelectItem(self, item):
        if item in self._order:
            self._index = self._order.index(item)
            RUNTIME.changed()

    def DeleteAllItems(self):
        self._nodes, self._order, self._index = {}, [], -1
        RUNTIME.changed()

    def Expand(self, _item):
        return None
    Collapse = ExpandAll = Expand

    def describe(self):
        if not self._shown:
            return None
        rows = [{'text': self._nodes[key]['text'],
                 'depth': self._nodes[key]['depth']} for key in self._order]
        return model.control(self._id, 'tree', self.label(),
                             items=rows, index=self._index,
                             enabled=self._enabled)

    def _set_from_user(self, value):
        try:
            self._index = int(value)
        except (TypeError, ValueError):
            return
        RUNTIME.changed()

    def _pressed(self, _message):
        self._fire(EVT_TREE_ITEM_ACTIVATED)


class Notebook(_Widget):
    _kind = 'tabs'

    def __init__(self, parent=None, identifier=ID_ANY, **kw):
        _Widget.__init__(self, parent, identifier, **kw)
        self._pages = []
        self._index = 0

    def AddPage(self, page, text, select=False, *_a, **_k):
        self._pages.append((str(text), page))
        if select:
            self._index = len(self._pages) - 1
        RUNTIME.changed()
        return True

    InsertPage = AddPage

    def GetSelection(self):
        return self._index

    def SetSelection(self, index):
        self._index = int(index)
        RUNTIME.changed()

    def GetPageCount(self):
        return len(self._pages)

    def GetPage(self, index):
        return self._pages[index][1] if 0 <= index < len(self._pages) else None

    def describe(self):
        if not self._shown:
            return None
        return model.control(self._id, 'tabs', self.label(),
                             options=[name for name, _page in self._pages],
                             index=self._index)

    def _set_from_user(self, value):
        try:
            self._index = int(value)
        except (TypeError, ValueError):
            return
        RUNTIME.changed()
        self._fire(EVT_NOTEBOOK_PAGE_CHANGED)


# --------------------------------------------------------------------------
# Menus
# --------------------------------------------------------------------------
class MenuItem(_Widget):
    _kind = 'menuitem'

    def __init__(self, menu=None, identifier=ID_ANY, text='', *_a, **kw):
        _Widget.__init__(self, menu, identifier, text, **kw)
        self._menu = menu
        self._separator = False
        self._checked = False
        self._wanted_id = identifier

    def describe(self):
        if self._separator:
            return {'separator': True}
        label, key = _split_accelerator(self.label())
        return {'id': self._id, 'label': label, 'key': key,
                'enabled': self._enabled, 'checked': self._checked}

    def Check(self, check=True):
        self._checked = bool(check)
        RUNTIME.changed()

    def IsChecked(self):
        return self._checked

    def GetItemLabel(self):
        return self._label

    def _pressed(self, _message):
        self._fire(EVT_MENU)


class Menu(_Widget):
    _kind = 'menu'

    def __init__(self, title='', *_a, **kw):
        _Widget.__init__(self, None, ID_ANY, title, **kw)
        self._items = []

    def Append(self, identifier=ID_ANY, text='', *_a, **kw):
        # `Append(id, "&New\tCtrl+N")`, `Append(item)` and
        # `Append(id, text, help)` are all written in Titan's applications.
        if isinstance(identifier, MenuItem):
            item = identifier
        elif isinstance(identifier, Menu):
            return self.AppendSubMenu(identifier, text)
        else:
            item = MenuItem(self, identifier, text)
        item._menu = self
        self._items.append(item)
        RUNTIME.changed()
        return item

    AppendItem = Append

    def AppendCheckItem(self, identifier=ID_ANY, text='', *_a, **_k):
        item = self.Append(identifier, text)
        item._checkable = True
        return item

    AppendRadioItem = AppendCheckItem

    def AppendSubMenu(self, submenu, text='', *_a, **_k):
        submenu._label = str(text or submenu._label)
        self._items.append(submenu)
        RUNTIME.changed()
        return submenu

    def AppendSeparator(self):
        item = MenuItem(self, ID_ANY, '')
        item._separator = True
        self._items.append(item)
        RUNTIME.changed()
        return item

    def Destroy(self, *_a, **_k):
        return _Widget.Destroy(self)

    def describe(self):
        items = []
        for item in self._items:
            if isinstance(item, Menu):
                items.append({'id': item._id, 'label': item.label(),
                              'items': item.describe()['items']})
            else:
                described = item.describe()
                if described is not None:
                    items.append(described)
        return {'label': self.label(), 'items': items}


class MenuBar(_Widget):
    _kind = 'menubar'

    def __init__(self, *_a, **kw):
        _Widget.__init__(self, None, ID_ANY, '', **kw)
        self._menus = []

    def Append(self, menu, title=''):
        menu._label = str(title or menu._label)
        self._menus.append(menu)
        RUNTIME.changed()
        return True

    def GetMenuCount(self):
        return len(self._menus)

    def describe(self):
        return [menu.describe() for menu in self._menus]


def _split_accelerator(text):
    """"&New note\\tCtrl+N" is a label and a shortcut. The ampersand is a
    mouse-and-keyboard idea (the underlined letter) and means nothing in an
    interface made of speech, so it goes; the shortcut is real and is kept,
    because it is how somebody drives the application quickly."""
    label, _tab, key = str(text or '').partition('\t')
    return label.replace('&&', '\0').replace('&', '').replace('\0', '&'), key


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------
class _Window(_Widget):
    """A screen. What the interface at the other end is showing."""

    _screen_kind = 'window'

    def __init__(self, parent=None, identifier=ID_ANY, title='', *_a, **kw):
        self._focus = None
        self._menubar = None
        self._owned = []
        self._modal_ended = None
        self._closing = False
        _Widget.__init__(self, parent, identifier, title, **kw)
        self._label = str(title or kw.get('title', '') or '')

    def _adopt(self, child):
        self._owned.append(child)

    def SetMenuBar(self, menubar):
        self._menubar = menubar
        RUNTIME.changed()

    def GetMenuBar(self):
        return self._menubar

    def SetAcceleratorTable(self, *_a, **_k):
        return None

    def CreateStatusBar(self, *_a, **_k):
        return _Silence('CreateStatusBar')

    def SetStatusText(self, text, *_a, **_k):
        self._status = str(text or '')
        RUNTIME.changed()

    def Show(self, show=True):
        self._shown = bool(show)
        if show:
            RUNTIME.push(self)
        else:
            RUNTIME.pop(self)
        return True

    def Hide(self):
        return self.Show(False)

    def Close(self, force=False):
        if not self._fire(EVT_CLOSE) or force:
            self.Destroy()
        return True

    def Destroy(self):
        RUNTIME.pop(self)
        for child in list(self._owned):
            child._alive = False
            RUNTIME.forget(child)
        return _Widget.Destroy(self)

    def _closed_by_user(self):
        self.Close()

    def _key(self, name):
        """A key the interface could not deal with itself. It reaches the
        window's own handler, which is where an application binds F5, Escape
        and its own letters."""
        event = Event(source=self, identifier=self._id, key=_key_code(name))
        event._ctrl = 'ctrl+' in name
        event._shift = 'shift+' in name
        event._alt = 'alt+' in name
        for holder in [self] + list(self._owned):
            for bound, handler, _source, _identifier in list(holder._handlers):
                if bound in (EVT_KEY_DOWN, EVT_CHAR_HOOK):
                    handler(event)
                    if not event.GetSkipped():
                        return True
        return False

    # --------------------------------------------------------- described
    def _describe(self):
        controls = []
        for child in self._flatten():
            described = child.describe()
            if described is not None:
                controls.append(described)
        menus = self._menubar.describe() if self._menubar is not None else []
        return model.screen(self._id, self._screen_kind, self.label(),
                            controls, menus, self._focus,
                            modal=self._modal_ended is not None)

    def _flatten(self):
        found, seen = [], set()

        def walk(widget):
            for child in getattr(widget, '_children', []):
                if id(child) in seen or not getattr(child, '_alive', True):
                    continue
                seen.add(id(child))
                if isinstance(child, _Window):
                    continue
                found.append(child)
                walk(child)
        walk(self)
        for child in self._owned:
            if id(child) not in seen and getattr(child, '_alive', True) \
                    and not isinstance(child, _Window):
                seen.add(id(child))
                found.append(child)
        return found


class Frame(_Window):
    _screen_kind = 'window'


class Dialog(_Window):
    _screen_kind = 'dialog'

    def ShowModal(self):
        """**This blocks, as wx's does.** An application opens a dialog and
        reads its fields on the next line; a `ShowModal` that returned at
        once would read them before anybody had filled them in."""
        self._modal_ended = None
        RUNTIME.push(self)
        RUNTIME.run(until=lambda: self._modal_ended is not None)
        RUNTIME.pop(self)
        return ID_CANCEL if self._modal_ended is None else self._modal_ended

    def EndModal(self, result):
        self._modal_ended = int(result)

    def _closed_by_user(self):
        if self._modal_ended is None:
            self.EndModal(ID_CANCEL)
        else:
            self.Close()

    def _pressed(self, message):
        _Widget._pressed(self, message)


def _key_code(name):
    return {'return': WXK_RETURN, 'enter': WXK_RETURN, 'escape': WXK_ESCAPE,
            'space': WXK_SPACE, 'up': WXK_UP, 'down': WXK_DOWN,
            'left': WXK_LEFT, 'right': WXK_RIGHT, 'back': WXK_BACK,
            'backspace': WXK_BACK, 'delete': WXK_DELETE, 'tab': WXK_TAB,
            'home': WXK_HOME, 'end': WXK_END, 'f1': WXK_F1, 'f2': WXK_F2,
            'f3': WXK_F3, 'f4': WXK_F4, 'f5': WXK_F5,
            'pageup': WXK_PAGEUP, 'pagedown': WXK_PAGEDOWN,
            }.get(str(name or '').rsplit('+', 1)[-1].lower(),
                  ord(str(name or ' ')[-1].upper()) if name else 0)

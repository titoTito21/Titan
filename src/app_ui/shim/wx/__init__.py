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

import os

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
# **A constant that is only made up is a constant that is zero.** The
# long tail answers an unknown name with 0, which is right for a style
# flag nobody reads and wrong for one that DECIDES something: `FD_SAVE`
# fabricated as 0 made every save dialog look like an open dialog.
FD_OPEN, FD_SAVE, FD_OVERWRITE_PROMPT = 1, 4, 8
FD_FILE_MUST_EXIST, FD_MULTIPLE, FD_CHANGE_DIR = 16, 32, 128
DD_DIR_MUST_EXIST, DD_CHANGE_DIR = 512, 256
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

    def GetItem(self):
        """`event.GetItem().GetId()` is how the file manager and the
        download manager both read which row was opened."""
        index = getattr(self._source, '_index', -1)
        text = ''
        rows = getattr(self._source, '_rows', None)
        if rows is not None and 0 <= index < len(rows):
            text = rows[index][0] if rows[index] else ''
        return ListItem(index, text)

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
class Point(object):
    """Where something is, which here is always nowhere."""

    __slots__ = ('x', 'y')

    def __init__(self, x=0, y=0):
        self.x, self.y = int(x or 0), int(y or 0)

    def __iter__(self):
        return iter((self.x, self.y))

    def __getitem__(self, index):
        return (self.x, self.y)[index]

    def Get(self):
        return (self.x, self.y)


class Size(Point):
    """How big, which here is always nothing."""

    def __init__(self, width=0, height=0):
        Point.__init__(self, width, height)

    @property
    def width(self):
        return self.x

    @property
    def height(self):
        return self.y

    GetWidth = lambda self: self.x       # noqa: E731 - wx's own spelling
    GetHeight = lambda self: self.y      # noqa: E731


class Rect(object):
    """**Geometry answers ZEROS, not nothing.**

    "Layout does not matter" is right about what is described and wrong
    about what is ANSWERED: an application that lays nothing out still
    asks where things are, and does arithmetic on the answer.
    `rect.x + 2` on a nothing is a `TypeError` that ends the browser
    before it has drawn a line.
    """

    __slots__ = ('x', 'y', 'width', 'height')

    def __init__(self, x=0, y=0, width=0, height=0):
        self.x, self.y = int(x or 0), int(y or 0)
        self.width, self.height = int(width or 0), int(height or 0)

    def __iter__(self):
        return iter((self.x, self.y, self.width, self.height))

    def __getitem__(self, index):
        return (self.x, self.y, self.width, self.height)[index]

    def GetX(self):
        return self.x

    def GetY(self):
        return self.y

    def GetWidth(self):
        return self.width

    def GetHeight(self):
        return self.height

    def GetPosition(self):
        return Point(self.x, self.y)

    def GetSize(self):
        return Size(self.width, self.height)

    def Contains(self, *_a):
        return False

    def Inflate(self, *_a):
        return self

    def Deflate(self, *_a):
        return self


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
        self._sizer = None
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
        people who cannot see them, so it is the best label there is.

        And **without the accelerator ampersand**. "&Play" underlines the
        P for somebody using a mouse and a keyboard; to a reader it is
        the word "ampersand" in front of every second button. It was
        taken off menu items and left on everything else, so the
        ElevenLabs client offered "ampersand Odtworz" and "ampersand
        Zapisz na dysku"."""
        return _without_ampersand(self._name or self._label or '')

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
    def SetSizer(self, sizer=None, *_a, **_k):
        # Kept for its ORDER, which is the reading order of the screen.
        if isinstance(sizer, _Sizer):
            self._sizer = sizer
        return None

    def SetSizerAndFit(self, sizer=None, *_a, **_k):
        return self.SetSizer(sizer)

    def SetAutoLayout(self, *_a, **_k):
        return None
    Layout = Fit = SetAutoLayout

    def SetSize(self, *_a, **_k):
        return None
    SetMinSize = SetMaxSize = SetPosition = SetClientSize = SetSize
    Centre = Center = CentreOnParent = CenterOnParent = SetSize
    SetBackgroundColour = SetForegroundColour = SetFont = SetSize
    Refresh = Update = Freeze = Thaw = SetIcon = SetSize
    SetToolTip = SetHelpText = SetDoubleBuffered = SetSize

    def GetSize(self, *_a, **_k):
        return Size(0, 0)
    GetClientSize = GetBestSize = GetMinSize = GetMaxSize = GetSize
    GetVirtualSize = GetTextExtent = GetSize

    def GetRect(self, *_a, **_k):
        return Rect(0, 0, 0, 0)
    GetClientRect = GetScreenRect = GetUpdateRegion = GetRect

    def GetPosition(self, *_a, **_k):
        return Point(0, 0)
    GetScreenPosition = ClientToScreen = ScreenToClient = GetPosition

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
    """A method that is not here.

    **It answers a chain, not just a call.** `bar.SetStatusWidths(...)`
    on something that is already nothing must be nothing again, or the
    application stops one attribute further along than it would have -
    which is exactly where the browser stopped. So calling it, reading
    off it and iterating it all give something that is still nothing, and
    the application carries on being wrong about one thing instead of
    ending.
    """

    __slots__ = ('name',)

    def __init__(self, name):
        self.name = name

    def __call__(self, *_a, **_k):
        return _Silence(self.name)

    def __getattr__(self, name):
        # **A private name is refused, not answered.** Answering `_parent`
        # with another nothing made `_window_of` walk up a chain that
        # never ends - the browser hung there, inside its own first
        # window, before it had built anything. Everything in this shim
        # asks about private names with `getattr(x, '_thing', None)`, and
        # that only works if the answer can be "there is none".
        if name.startswith('_'):
            raise AttributeError(name)
        RUNTIME.note_unknown('%s.%s' % (self.name, name))
        return _Silence('%s.%s' % (self.name, name))

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    # **A nothing that survives arithmetic.** Everything unwritten here
    # answers with one of these, and geometry is what applications do
    # sums on: `rect.x + 2` must be a number that means nothing rather
    # than an exception that ends the application. Same rule as
    # `_Unknown`, one level further in.
    def __int__(self):
        return 0

    def __float__(self):
        return 0.0

    def __index__(self):
        return 0

    def __add__(self, other):
        return other

    def __radd__(self, other):
        return other

    def __sub__(self, other):
        return -other if isinstance(other, (int, float)) else other

    def __rsub__(self, other):
        return other

    def __mul__(self, other):
        return 0
    __rmul__ = __mul__

    def __lt__(self, other):
        return True

    def __gt__(self, other):
        return False

    def __eq__(self, other):
        return other is self or other is None

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return ''

    def __bool__(self):
        return False
    __nonzero__ = __bool__


def _window_of(widget):
    """The window a control belongs to.

    Only real widgets are walked: a parent that is something else - a
    class this shim never wrote, standing in for a container - has no
    chain to follow, and following one anyway is how this hung.
    """
    seen = 0
    while isinstance(widget, _Widget):
        if isinstance(widget, _Window):
            return widget
        seen += 1
        if seen > 200:          # a parent chain that has a loop in it
            return None
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
                             secret=bool(self._style & TE_PASSWORD),
                             # **A path is said to be one.** There is no
                             # file system on the other side of this - the
                             # interface may be in another program, or on
                             # another machine - so the field cannot be a
                             # file chooser here. Saying that it holds a
                             # PATH lets the interface offer its own,
                             # which is the one the user already knows.
                             # `open`, `save` or `folder` - what the
                             # chooser is FOR, because saving is not
                             # opening and a folder is not a file.
                             path=getattr(self, '_path', None) or None,
                             extensions=getattr(self, '_extensions', None)
                             or None,
                             # A page carries where it came from, so an
                             # interface can offer it to its own browser
                             # instead of only reading it out.
                             url=getattr(self, '_url', None) or None)

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

    def GetColumn(self, index):
        """A column answers its own heading. The file manager finds its
        Date and Type columns by reading them - `GetColumn(i).GetText()` -
        so a column that is None ends the application on its first
        listing."""
        return _Column(self._columns[index]
                       if 0 <= int(index) < len(self._columns) else '')

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


class _Column(object):
    """What `ListCtrl.GetColumn` answers."""

    __slots__ = ('_text',)

    def __init__(self, text=''):
        self._text = str(text or '')

    def GetText(self):
        return self._text

    def SetText(self, text):
        self._text = str(text or '')

    def GetWidth(self):
        return 0


class ListItem(object):
    """`wx.ListItem` - a row an application builds before adding it, and
    what a list event answers when asked which row it was about."""

    def __init__(self, index=-1, text=''):
        self._index = int(index)
        self._text = str(text or '')
        self._column = 0

    def GetId(self):
        return self._index

    def SetId(self, index):
        self._index = int(index)

    def GetText(self):
        return self._text

    def SetText(self, text):
        self._text = str(text or '')

    def GetColumn(self):
        return self._column

    def SetColumn(self, column):
        self._column = int(column)

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        RUNTIME.note_unknown('ListItem.%s' % name)
        return _Silence(name)


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
        # The menu's OWN label is written "&Plik" as well, and the
        # ampersand is a mouse-and-keyboard idea that means nothing in an
        # interface made of speech.
        for item in self._items:
            if isinstance(item, Menu):
                items.append({'id': item._id, 'label': item.label(),
                              'items': item.describe()['items']})
            else:
                described = item.describe()
                if described is not None:
                    items.append(described)
        return {'label': _split_accelerator(self.label())[0],
                'items': items}


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


def _belongs_to(menu, window):
    """A menu and everything on it answer to this window."""
    menu._parent = window
    for item in getattr(menu, '_items', []):
        if isinstance(item, Menu):
            _belongs_to(item, window)
        else:
            item._parent = menu


def _without_ampersand(text):
    """The accelerator ampersand off, a real one kept: wx writes a
    literal ampersand as `&&`."""
    return str(text or '').replace('&&', '\0').replace('&', '').replace('\0', '&')


def _split_accelerator(text):
    """"&New note\\tCtrl+N" is a label and a shortcut. The ampersand is a
    mouse-and-keyboard idea (the underlined letter) and means nothing in an
    interface made of speech, so it goes; the shortcut is real and is kept,
    because it is how somebody drives the application quickly."""
    label, _tab, key = str(text or '').partition('\t')
    return _without_ampersand(label), key


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
        """**And the menus become this window's.**

        A menu item is created with the MENU as its parent and a menu has
        no parent at all, so walking up from an item reached the menu and
        stopped - while every application binds its menu on the FRAME
        (`self.Bind(wx.EVT_MENU, self.on_new_note, new_note_item)`, which
        is how all 24 menus across Titan's applications are written). So
        not one menu item did anything: the file manager and the editor
        both answered every menu press with the screen they already had.
        """
        self._menubar = menubar
        for menu in getattr(menubar, '_menus', []):
            _belongs_to(menu, self)
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
        _label_from_the_left(controls)
        menus = self._menubar.describe() if self._menubar is not None else []
        return model.screen(self._id, self._screen_kind, self.label(),
                            controls, menus, self._focus,
                            modal=self._modal_ended is not None)

    def _flatten(self):
        """Every control on this screen, in the order it is READ in.

        **Every control belongs to the WINDOW, and the order lives in the
        panels' sizers**, so the two have to be put back together. A
        control is created with a panel as its parent but registered on
        the window (`_Window._adopt`), which is what makes a screen one
        flat list; the sizer of each container then says what order those
        were laid out in.

        Order is not geometry. Where a control sits on a rectangle means
        nothing to an interface made of speech, but the order it was added
        in is exactly the reading order - and it is what pairs a label
        with the control it names. The organiser BUILDS three drop-downs
        and only then adds "Day:", the day, "Month:", the month to the
        sizer: read in creation order the labels are stranded at the end
        and two of the drop-downs have no name at all.

        Anything no sizer took keeps its creation order, after the rest: a
        control the application built and never laid out is still a
        control.
        """
        order = {}
        for holder in [self] + list(self._owned):
            sizer = getattr(holder, '_sizer', None)
            if not isinstance(sizer, _Sizer):
                continue
            for item in sizer.leaves():
                if id(item) not in order:
                    order[id(item)] = len(order)
        laid_out, loose = [], []
        for child in self._owned:
            if not getattr(child, '_alive', True) or isinstance(child, _Window):
                continue
            (laid_out if id(child) in order else loose).append(child)
        laid_out.sort(key=lambda child: order[id(child)])
        return laid_out + loose


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

    def _key(self, name):
        """**Escape leaves a dialog, because it does in wx.** wx answers
        it itself - no application binds it - so a shim that only passed
        it to the application left every dialog with no way out but the
        button the application happened to provide."""
        if _Window._key(self, name):
            return True
        if name.rsplit('+', 1)[-1].lower() == 'escape' \
                and self._modal_ended is None:
            self.EndModal(ID_CANCEL)
            return True
        return False

    def _pressed(self, message):
        _Widget._pressed(self, message)


def _extensions(wildcard):
    """The extensions out of a wx wildcard, so a chooser can filter.

    `"Text files (*.txt)|*.txt|All files (*.*)|*.*"` is the shape; what
    an interface needs from it is `['txt']`, and `*.*` means anything,
    which is the same as saying nothing.
    """
    found = []
    for piece in str(wildcard or '').split('|'):
        for pattern in piece.split(';'):
            pattern = pattern.strip()
            if not pattern.startswith('*.') or pattern == '*.*':
                continue
            suffix = pattern[2:].lower()
            if suffix and suffix not in found:
                found.append(suffix)
    return found


def _label_from_the_left(controls):
    """A control with no name takes the text just before it.

    That is how every wx program is built - a `StaticText` and then the
    field it names - and it is the rule Titan already applies to its own
    settings (`src/settings/ui_model.py`: "a `wx.Choice` is labelled by
    the static text in front of it"). Without it tNotes' note dialog
    describes a field called nothing followed by another field called
    nothing, and an interface made of speech has no way to tell the title
    from the body.

    A control that named ITSELF keeps its name: `SetName` is deliberate,
    and Titan's applications call it precisely because they are written
    for people who cannot see the screen.
    """
    named = ('text', 'multiline', 'list', 'table', 'choice', 'tree',
             'slider', 'gauge', 'tabs')
    previous = None
    used = []
    for index, entry in enumerate(controls):
        if entry.get('kind') in named and not entry.get('label') \
                and previous is not None:
            entry['label'] = controls[previous].get('label', '').rstrip(':').strip()
            entry['labelled_by'] = 'the text before it'
            used.append(previous)
        previous = index if entry.get('kind') == 'label' else None
    # **And it is not read twice.** A label that has named the control
    # after it is that control's name now; leaving it on its own line as
    # well makes the reader say "Reminder name" and then "Reminder name,
    # field".
    for index in reversed(used):
        del controls[index]
    # **A label with nothing to say is nothing.** The file manager builds
    # an empty `StaticText` as a status line and fills it in later; read
    # as it comes it is a line the reader stops on and says nothing about.
    controls[:] = [entry for entry in controls
                   if entry.get('kind') != 'label' or entry.get('label')]
    # **A control the application never named says what it IS.** Two of
    # Titan's own applications put their main table up with no name and
    # no text before it, and a table called nothing is, to somebody
    # working by ear, a list of rows belonging to nothing. The kind word
    # is the most that can be said without inventing content, and
    # `unnamed` marks it so an interface can tell it from a real name.
    for entry in controls:
        if entry.get('label') or entry.get('kind') not in _MUST_BE_NAMED:
            continue
        entry['label'] = _KIND_WORDS.get(entry['kind'], entry['kind'])
        entry['unnamed'] = True


#: A control that cannot be used without knowing which one it is.
_MUST_BE_NAMED = ('text', 'multiline', 'choice', 'check', 'slider', 'list',
                  'table', 'tree', 'gauge', 'tabs', 'button')

_KIND_WORDS = {'text': 'Field', 'multiline': 'Text', 'choice': 'Choice',
               'check': 'Check box', 'slider': 'Slider', 'list': 'List',
               'table': 'Table', 'tree': 'Tree', 'gauge': 'Progress',
               'tabs': 'Tabs', 'button': 'Button'}


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


# --------------------------------------------------------------------------
# The ready-made dialogs, which are most of what an application says
# --------------------------------------------------------------------------
class _Answered(Dialog):
    """A dialog wx builds for the application: a message, a question, a
    field, a list of things to pick from.

    **Its buttons are real controls.** They were described as nothing at
    all at first, which left an interface with a question on the screen
    and no way to answer it - the entry dialog could be typed into and
    never accepted. Building them as ordinary `Button`s instead means
    pressing one goes down exactly the same path as pressing any other
    button, so there is one implementation of "the user pressed
    something" rather than a second one for the dialogs wx supplies.
    """

    def _answers(self, pairs):
        self._answer_buttons = []
        for label, result in pairs:
            button = Button(self, ID_ANY, label)
            button._answer = result
            button.Bind(EVT_BUTTON, self._answer_pressed)
            if result in (ID_OK, ID_YES):
                button._default = True
            self._answer_buttons.append(button)

    def _answer_pressed(self, event):
        source = event.GetEventObject()
        self.EndModal(getattr(source, '_answer', ID_OK))


class MessageDialog(_Answered):
    _screen_kind = 'message'

    def __init__(self, parent=None, message='', caption='', style=OK, **kw):
        Dialog.__init__(self, parent, ID_ANY, caption or kw.get('caption', ''))
        self._style = int(style or OK)
        StaticText(self, ID_ANY, str(message or ''))
        self._answers(_message_buttons(self._style))

    @property
    def _screen_kind(self):
        return 'question' if self._style & YES_NO else 'message'


def _message_buttons(style):
    if style & YES_NO:
        answers = [('Yes', ID_YES), ('No', ID_NO)]
        if style & CANCEL:
            answers.append(('Cancel', ID_CANCEL))
        return answers
    if style & CANCEL:
        return [('OK', ID_OK), ('Cancel', ID_CANCEL)]
    return [('OK', ID_OK)]


def MessageBox(message='', caption='', style=OK, parent=None, **_kw):
    """`wx.MessageBox` is 111 call sites across Titan's applications - more
    than any widget but the button - so it is the one thing that has to be
    exactly right."""
    dialog = MessageDialog(parent, message, caption, style)
    answer = dialog.ShowModal()
    dialog.Destroy()
    return answer


class TextEntryDialog(_Answered):
    _screen_kind = 'entry'

    def __init__(self, parent=None, message='', caption='', value='', **kw):
        Dialog.__init__(self, parent, ID_ANY, caption or kw.get('caption', ''))
        self._field = TextCtrl(self, ID_ANY, str(value or kw.get('value', '') or ''))
        self._field.SetName(str(message or ''))
        self._focus = self._field._id
        self._answers([('OK', ID_OK), ('Cancel', ID_CANCEL)])

    def GetValue(self):
        return self._field.GetValue()

    def SetValue(self, value):
        self._field.SetValue(value)


class PasswordEntryDialog(TextEntryDialog):
    def __init__(self, *args, **kw):
        TextEntryDialog.__init__(self, *args, **kw)
        self._field._style |= TE_PASSWORD


class SingleChoiceDialog(_Answered):
    _screen_kind = 'pick'

    def __init__(self, parent=None, message='', caption='', choices=None, **kw):
        Dialog.__init__(self, parent, ID_ANY, caption or kw.get('caption', ''))
        self._list = ListBox(self, ID_ANY, choices=list(choices or []))
        self._list.SetName(str(message or ''))
        self._focus = self._list._id
        self._answers([('OK', ID_OK), ('Cancel', ID_CANCEL)])

    def GetSelection(self):
        return self._list.GetSelection()

    def GetStringSelection(self):
        return self._list.GetStringSelection()

    def SetSelection(self, index):
        self._list.SetSelection(index)


class MultiChoiceDialog(SingleChoiceDialog):
    def GetSelections(self):
        index = self._list.GetSelection()
        return [index] if index >= 0 else []


class _PathDialog(_Answered):
    """A file or folder chooser.

    **There is no file system on the other side of this**, so this cannot
    be a chooser - the interface may be in another program, on another
    machine, or made of nothing but speech. What it can do is say that a
    PATH is what is wanted here and what for, and let the interface use
    the chooser it already has: Elten has a file tree, Emacs has dired, a
    console has a prompt with completion. Every one of those is better
    than the field this would otherwise be, and none of them is something
    this can know about.

    So the field carries `path` - `open`, `save` or `folder` - and the
    extensions the application asked for. An interface that does not
    recognise any of it still gets a text field with a sensible name,
    which is the rule the whole description is built on.
    """

    _screen_kind = 'entry'

    def __init__(self, parent=None, message='', defaultDir='',
                 defaultFile='', wildcard='', style=0, *_a, **kw):
        Dialog.__init__(self, parent, ID_ANY, str(message or ''))
        folder = bool(kw.pop('_folder', False))
        start = (defaultDir or defaultFile or kw.get('defaultDir')
                 or kw.get('defaultFile') or kw.get('defaultPath') or '')
        if defaultDir and defaultFile:
            start = os.path.join(str(defaultDir), str(defaultFile))
        self._field = TextCtrl(self, ID_ANY, str(start))
        self._field.SetName(str(message or 'Path'))
        # `wx.FD_SAVE` is 0x0004 and `wx.FD_OPEN` 0x0001; an application
        # that says neither means open, which is wx's own default.
        saving = bool(int(style or kw.get('style', 0) or 0) & 0x0004)
        self._field._path = 'folder' if folder else (
            'save' if saving else 'open')
        self._field._extensions = _extensions(wildcard or kw.get('wildcard'))
        self._focus = self._field._id
        self._answers([('OK', ID_OK), ('Cancel', ID_CANCEL)])
        RUNTIME.refuse(
            'wx.FileDialog',
            'there is no file chooser here - the interface offers its own')

    def GetPath(self):
        return self._field.GetValue()

    def GetPaths(self):
        return [self.GetPath()] if self.GetPath() else []

    def GetFilename(self):
        return os.path.basename(self.GetPath())

    def GetDirectory(self):
        return os.path.dirname(self.GetPath())

    def SetPath(self, value):
        self._field.SetValue(value)


class FileDialog(_PathDialog):
    pass


class DirDialog(_PathDialog):
    """A folder, which an interface may offer differently from a file."""

    def __init__(self, parent=None, message='', *_a, **kw):
        kw['_folder'] = True
        _PathDialog.__init__(self, parent, message, *_a, **kw)


class ProgressDialog(Dialog):
    def __init__(self, title='', message='', maximum=100, parent=None, **kw):
        Dialog.__init__(self, parent, ID_ANY, title)
        self._bar = Gauge(self, ID_ANY, int(maximum or 100))
        self._bar.SetName(str(message or ''))

    def Update(self, value, newmsg=None):
        self._bar.SetValue(value)
        if newmsg is not None:
            self._bar.SetName(str(newmsg))
        return (True, False)

    def Pulse(self, newmsg=None):
        return self.Update(self._bar.GetValue(), newmsg)


# --------------------------------------------------------------------------
# Sizers - the sink. A fifth of everything Titan's applications call.
# --------------------------------------------------------------------------
class _Sizer(object):
    """**Where a control sits is thrown away; the ORDER it was added in is
    not.**

    Saying "layout does not matter" was right about geometry and wrong
    about order, and the difference is what pairs a label with its
    control. The organiser BUILDS three drop-downs and only then adds
    "Day:", the day, "Month:", the month, "Year:", the year to the sizer -
    so read in creation order the three labels are stranded at the end and
    two of the drop-downs have no name at all, which for somebody who
    cannot see the dialog is three unnamed lists in a row. Read in the
    order they were added, each label is next to the thing it names.

    An interface made of speech has no rectangle, but it certainly has a
    reading order.
    """

    def __init__(self, *_a, **_k):
        self.items = []

    def Add(self, item=None, *_a, **_k):
        if isinstance(item, (_Widget, _Sizer)):
            self.items.append(item)
        return None

    def AddMany(self, items=None, *_a, **_k):
        for entry in items or []:
            self.Add(entry[0] if isinstance(entry, (list, tuple)) else entry)
        return None

    def Insert(self, index=0, item=None, *_a, **_k):
        if isinstance(item, (_Widget, _Sizer)):
            try:
                self.items.insert(int(index), item)
            except (TypeError, ValueError):
                self.items.append(item)
        return None

    def Prepend(self, item=None, *_a, **_k):
        return self.Insert(0, item)

    def Detach(self, item=None, *_a, **_k):
        if item in self.items:
            self.items.remove(item)
        return None
    Remove = Detach

    def Clear(self, *_a, **_k):
        self.items = []
        return None

    AddSpacer = AddStretchSpacer = Layout = Fit = FitInside = Clear
    SetSizeHints = Show = Hide = SetMinSize = Clear

    def GetChildren(self):
        return list(self.items)

    def leaves(self):
        """The controls this sizer holds, in the order they were added."""
        found = []
        for item in self.items:
            if isinstance(item, _Sizer):
                found.extend(item.leaves())
            else:
                found.append(item)
        return found

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return _Silence(name)


BoxSizer = GridSizer = FlexGridSizer = GridBagSizer = WrapSizer = _Sizer


class StaticBoxSizer(_Sizer):
    def __init__(self, box=None, orient=VERTICAL, *_a, **_k):
        _Sizer.__init__(self)
        self.box = box


class AcceleratorEntry(object):
    def __init__(self, flags=0, keyCode=0, cmdID=0, *_a, **_k):
        self.flags, self.key, self.command = flags, keyCode, cmdID


class AcceleratorTable(object):
    def __init__(self, entries=None, *_a, **_k):
        self.entries = list(entries or [])


# --------------------------------------------------------------------------
# The application, its loop, and the two ways work comes back to it
# --------------------------------------------------------------------------
class App(object):
    def __init__(self, *_a, **_k):
        RUNTIME.open_wire()
        self.OnInit()

    def OnInit(self):
        return True

    def MainLoop(self):
        RUNTIME.say('ready', refused=list(RUNTIME.refused))
        RUNTIME.run()
        RUNTIME.say('gone')

    def ExitMainLoop(self):
        RUNTIME.quitting = True

    def SetTopWindow(self, *_a, **_k):
        return None

    def Yield(self, *_a, **_k):
        RUNTIME._drain()
        return True

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        RUNTIME.note_unknown('App.%s' % name)
        return _Silence(name)


PySimpleApp = App


def CallAfter(work, *args, **kwargs):
    RUNTIME.later(work, *args, **kwargs)


def CallLater(_milliseconds, work, *args, **kwargs):
    RUNTIME.later(work, *args, **kwargs)
    return _Silence('CallLater')


def Yield(*_a, **_k):
    RUNTIME._drain()
    return True


SafeYield = YieldIfNeeded = Yield


def GetApp():
    return _APP


def Exit():
    RUNTIME.quitting = True


def NewId():
    RUNTIME.next_id += 1
    return 40000 + RUNTIME.next_id


NewIdRef = NewId


def IsMainThread():
    import threading as _threading
    return _threading.current_thread() is _threading.main_thread()


class Timer(object):
    """**A timer that really ticks.**

    It used to be a recorded refusal, and for an application that merely
    polls that was survivable - what it polled for arrived when the user
    did something. For one that WAITS on a timer it was fatal: the
    browser reports its engine attaching on one, so it never showed
    anything at all and could only be looked at through its own window.

    The loop now waits with a deadline rather than blocking on the pipe,
    so a timer fires between keystrokes as well as after them. It is not
    a real clock - nothing runs while the application is inside a handler,
    exactly as in wx, where a timer is a message like any other - and it
    cannot fire more often than the loop goes round.
    """

    def __init__(self, owner=None, identifier=ID_ANY):
        self._owner = owner if owner is not None else self
        self._id = identifier
        self.due = None
        self._every = None

    def Start(self, milliseconds=-1, oneShot=False):
        import time as _time
        try:
            seconds = max(0.01, float(milliseconds) / 1000.0)
        except (TypeError, ValueError):
            seconds = 1.0
        self._every = None if oneShot else seconds
        self.due = _time.time() + seconds
        RUNTIME.add_timer(self)
        return True

    StartOnce = Start

    def Stop(self, *_a, **_k):
        self.due = None
        RUNTIME.drop_timer(self)
        return True

    def IsRunning(self):
        return self.due is not None

    def GetId(self):
        return self._id

    def GetInterval(self):
        return int((self._every or 0) * 1000)

    def fire(self, now):
        """The loop says the moment has come."""
        if self._every is None:
            self.due = None
            RUNTIME.drop_timer(self)
        else:
            self.due = now + self._every
        event = Event(source=self, identifier=self._id)
        owner = self._owner
        if isinstance(owner, _Widget):
            for holder in owner._up():
                for bound, handler, source, identifier in list(holder._handlers):
                    if bound is not EVT_TIMER:
                        continue
                    if source is not None and source is not self:
                        continue
                    handler(event)
                    return
        self.Notify()

    def Notify(self):
        return None

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        RUNTIME.note_unknown('Timer.%s' % name)
        return _Silence(name)


_APP = None


# --------------------------------------------------------------------------
# Everything else
# --------------------------------------------------------------------------
class _Unknown(int):
    """A wx name nobody wrote. It is an int so it works as a style flag or
    an id, and callable so it works as a function - which between them is
    what almost every unwritten name is used as."""

    def __call__(self, *_a, **_k):
        return _Unknown(0)


class _UnknownMeta(type):
    """**And on the class itself, not only on an instance.**
    `wx.SomeThing.Open(...)` is a class attribute, which `__getattr__` on
    the class body never sees - the download manager stopped on exactly
    that (`type object '_UnknownClass' has no attribute 'Open'`). A
    metaclass is where a class is asked about its own attributes.
    """

    def __getattr__(cls, name):
        if name.startswith('_'):
            raise AttributeError(name)
        RUNTIME.note_unknown('<class>.%s' % name)
        return _Silence(name)


class _UnknownClass(object, metaclass=_UnknownMeta):
    """A wx CLASS nobody wrote, so that `class Mine(wx.Something)` still
    imports. Every method answers nothing."""

    def __init__(self, *_a, **_k):
        pass

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        RUNTIME.note_unknown('%s.%s' % (type(self).__name__, name))
        return _Silence(name)


# `import wx.adv` is an IMPORT and a module-level `__getattr__` cannot
# answer one - three of Titan's eight applications failed at their first
# line for want of this.
from . import _submodules as _submodules_module   # noqa: E402
import sys as _sys                                # noqa: E402
_submodules_module.install(_sys.modules[__name__])

# **The wire opens at import, not at `wx.App()`.** Everything an
# application refuses it usually refuses at its very first line -
# `import wx.html2` is the browser's - and an application that then never
# reaches `MainLoop` had recorded the one useful sentence about itself and
# had no way to say it. Guarded on the variable the host sets, so
# importing the shim in a test does not take a test runner's stdout.
if os.environ.get('TITAN_APP_UI'):
    RUNTIME.open_wire()


def __getattr__(name):
    """**The long tail, answered rather than raised.**

    98 of the 274 wx names Titan's applications use are used exactly once,
    and a shim that raises on the first one it has not got never finishes.
    So an unknown name becomes a constant or a class by how it is spelled -
    ALL_CAPS is a flag, CamelCase is a class - and every one of them is
    recorded, so what is missing can be read rather than guessed at.
    """
    if name.startswith('__'):
        raise AttributeError(name)
    RUNTIME.note_unknown('wx.%s' % name)
    if name.isupper() or name.startswith(('ID_', 'WXK_', 'EVT_')):
        if name.startswith('EVT_'):
            return _EventKind(name[4:])
        return _Unknown(0)
    if name[:1].isupper():
        return _UnknownClass
    return _Silence(name)

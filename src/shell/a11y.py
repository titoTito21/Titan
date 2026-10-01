# -*- coding: utf-8 -*-
"""
What makes the Titan shell readable.

A taskbar that looks like XP has to be painted, and a painted control is, to
Windows, a blank rectangle.  So every element of this shell is a real
focusable window that answers the accessibility interfaces with a name, a
role and a state (`ShellAccessible`) - which is what lets Titan Access, NVDA
and JAWS read it without knowing anything about Titan.

**The shell itself never speaks.**  It is the system interface: a screen
reader is already announcing every focus change in it, so a Titan
announcement on top of that would say every button twice.  All the effort
goes into the name, the role and the state instead.  The only sound the shell
makes on its own is Titan's non-speech focus cue, which is a cue, not an
announcement, and which the user can turn off.

There is one thing a name cannot carry: which *part* of the bar the keyboard
has just arrived in.  That is announced exactly the way a Titan window
announces its virtual tab bar - through
`accessibility.messages.announce_shell_group`, which reaches the screen
reader and nothing else, so with no reader running nothing is said at all.
"""

import sys

import wx

from src.settings.settings import get_setting
from src.titan_core.translation import _

try:
    from src.titan_core.sound import play_sound, play_shell_sound
except Exception:  # pragma: no cover - sound is optional for the shell
    def play_sound(*_args, **_kwargs):
        pass

    def play_shell_sound(*_args, **_kwargs):
        return False


# What the shell calls itself.  It is the system interface, not a window of
# the Titan application, so its own windows are announced as TCEShell rather
# than as "the Titan taskbar" - and it is deliberately not translated, being
# a name.
SHELL_NAME = 'TCEShell'


# Roles the shell uses, mapped to what MSAA calls them.
ROLE_BUTTON = getattr(wx, 'ROLE_SYSTEM_PUSHBUTTON', 43)
ROLE_LIST = getattr(wx, 'ROLE_SYSTEM_LIST', 33)
ROLE_LISTITEM = getattr(wx, 'ROLE_SYSTEM_LISTITEM', 34)
ROLE_TOOLBAR = getattr(wx, 'ROLE_SYSTEM_TOOLBAR', 22)
ROLE_MENUITEM = getattr(wx, 'ROLE_SYSTEM_MENUITEM', 12)
ROLE_STATICTEXT = getattr(wx, 'ROLE_SYSTEM_STATICTEXT', 41)
ROLE_CLIENT = getattr(wx, 'ROLE_SYSTEM_CLIENT', 10)
ROLE_CLOCK = getattr(wx, 'ROLE_SYSTEM_CLOCK', 61)

STATE_FOCUSABLE = getattr(wx, 'ACC_STATE_SYSTEM_FOCUSABLE', 0x00100000)
STATE_FOCUSED = getattr(wx, 'ACC_STATE_SYSTEM_FOCUSED', 0x00000004)
STATE_SELECTED = getattr(wx, 'ACC_STATE_SYSTEM_SELECTED', 0x00000002)
STATE_PRESSED = getattr(wx, 'ACC_STATE_SYSTEM_PRESSED', 0x00000008)


def shell_setting(key, default):
    """Read one `titan_shell` setting, with a type-preserving default."""
    value = get_setting(key, None, 'titan_shell')
    if value is None:
        return default
    if isinstance(default, bool):
        return str(value).strip().lower() in ('true', '1', 'yes')
    if isinstance(default, int):
        try:
            return int(str(value).strip())
        except Exception:
            return default
    return value


def cues_enabled():
    """Titan's focus/select sounds inside the shell (not speech)."""
    return bool(shell_setting('focus_cues', True))


def screen_position(window):
    """Where a window is across the screen, as -1.0 .. 1.0.

    Used to pan the focus cue, so the Start button clicks from the left and
    the clock from the right - the taskbar is heard as the shape it is.
    """
    try:
        rect = window.GetScreenRect()
        width = wx.GetDisplaySize().width or 1
        centre = rect.x + rect.width / 2.0
        return max(-1.0, min(1.0, (centre / width) * 2.0 - 1.0))
    except Exception:
        return 0.0


def mixer_pan(position):
    """The shell's -1.0 .. 1.0 turned into the mixer's 0.0 .. 1.0.

    Everything Titan puts in front of a user says -1 (left), 0 (centre), 1
    (right); `sound.py` has always taken 0 (left), 0.5 (centre), 1 (right)
    and works out the two channel volumes as `1 - pan` and `pan`.  Handing
    one straight to the other is the same bug the Titan Script `play`
    statement had: every position left of centre - INCLUDING the centre -
    comes out hard left.  That is why the shell's own sounds were only in
    the left channel, and why the taskbar's focus cues used only the right
    half of the stereo image (the Start button and everything before the
    middle of the screen clamped to 0.0, hard left).
    """
    try:
        position = float(position)
    except (TypeError, ValueError):
        position = 0.0
    position = max(-1.0, min(1.0, position))
    return (position + 1.0) / 2.0


def focus_cue(position=0.0):
    if not cues_enabled():
        return
    try:
        play_sound('core/FOCUS.ogg', pan=mixer_pan(position))
    except Exception:
        pass


def select_cue(position=0.0):
    if not cues_enabled():
        return
    try:
        play_sound('core/SELECT.ogg', pan=mixer_pan(position))
    except Exception:
        pass


# The shell's own sounds, in `sfx/<theme>/shell/`.  They say what the shell
# is DOING - it has started, it is going away, it has gone somewhere - which
# is a different thing from the focus cues (`focus_cues`), and so has its own
# switch: somebody may want the quiet focus clicks and no fanfare, or the
# other way round.
SOUND_STARTUP = 'shell_startup.ogg'
SOUND_SHUTDOWN = 'shell_shutdown.ogg'
SOUND_NAVIGATE = 'shell_start.ogg'


def sounds_enabled():
    """Settings -> Titan shell -> Sounds -> "Play the shell's own sounds"."""
    return bool(shell_setting('shell_sounds', True))


def shell_sound(name, position=None):
    """Play one of the shell's sounds, if the user wants to hear them.

    This is a sound and never speech: the shell says nothing through TTS,
    because the screen reader is already announcing every focus change in
    it.

    `position` is None because these sounds have no position: the shell
    starting, the shell going away and a folder opening happen to the
    whole desktop, not at a place on it, so they belong in BOTH channels.
    An unpanned sound is also the only way to get both channels at full
    volume - `sound.py`'s pan law is linear, so a sound placed dead centre
    is half in each.  A caller that really does mean somewhere says so in
    the shell's own -1 .. 1, and `mixer_pan` converts it.
    """
    if not sounds_enabled():
        return False
    try:
        pan = None if position is None else mixer_pan(position)
        return bool(play_shell_sound(name, pan=pan))
    except Exception:
        return False


def edge_cue():
    if not cues_enabled():
        return
    try:
        play_sound('core/endoflist.ogg')
    except Exception:
        pass


class ShellAccessible(wx.Accessible):
    """Give a painted shell control a name, a role and a state.

    Without this the taskbar is a wall of unnamed panes to every screen
    reader on the machine, Titan Access included.  The control supplies the
    pieces through `shell_name()`, `shell_role()` and `shell_state()`, so one
    class covers buttons, list items and the bars themselves.
    """

    def __init__(self, window):
        super().__init__(window)
        self._window = window

    def GetName(self, child_id):
        try:
            name = self._window.shell_name()
        except Exception:
            name = None
        if not name:
            return (wx.ACC_NOT_IMPLEMENTED, '')
        return (wx.ACC_OK, str(name))

    def GetRole(self, child_id):
        try:
            role = self._window.shell_role()
        except Exception:
            role = None
        if role is None:
            return (wx.ACC_NOT_IMPLEMENTED, 0)
        return (wx.ACC_OK, role)

    def GetState(self, child_id):
        try:
            state = self._window.shell_state()
        except Exception:
            state = None
        if state is None:
            return (wx.ACC_NOT_IMPLEMENTED, 0)
        return (wx.ACC_OK, state)

    def GetDescription(self, child_id):
        try:
            description = self._window.shell_description()
        except Exception:
            description = None
        if not description:
            return (wx.ACC_NOT_IMPLEMENTED, '')
        return (wx.ACC_OK, str(description))

    def GetDefaultAction(self, child_id):
        try:
            action = self._window.shell_default_action()
        except Exception:
            action = None
        if not action:
            return (wx.ACC_NOT_IMPLEMENTED, '')
        return (wx.ACC_OK, str(action))

    def DoDefaultAction(self, child_id):
        try:
            self._window.shell_activate()
            return wx.ACC_OK
        except Exception:
            return wx.ACC_NOT_IMPLEMENTED


class NamedAccessible(wx.Accessible):
    """Give a **native** control a name a screen reader will actually read.

    `wxWindow.SetName` is wx's own name and never reaches MSAA: a list view
    or a tree view answers with its own IAccessible, whose name comes from
    the window text (which these controls have none of) or from a label
    beside it (which a desktop has none of).  That is why the desktop list
    was read as an unnamed list however many times it was called "Desktop".

    Only the name of the control itself is answered here.  Everything else -
    the items, their states, their positions - returns
    `wxACC_NOT_IMPLEMENTED`, which is the documented way of saying "use the
    standard behaviour", so the control keeps every bit of the native
    accessibility a screen reader relies on.
    """

    def __init__(self, window, name=''):
        super().__init__(window)
        self._name = name

    def set_name(self, name):
        self._name = name or ''

    def GetName(self, child_id):
        if child_id == 0 and self._name:
            return (wx.ACC_OK, str(self._name))
        return (wx.ACC_NOT_IMPLEMENTED, '')


# --------------------------------------------------------------------------- #
# GTK: the name goes to ATK, which is what Orca reads
# --------------------------------------------------------------------------- #
_gtk_libs = None


def _gtk():
    """(libgtk-3, libatk) as ctypes libraries, or None off GTK."""
    global _gtk_libs
    if _gtk_libs is not None:
        return _gtk_libs or None
    _gtk_libs = False
    # PlatformInfo is a tuple of words ('__WXGTK__', 'gtk3', ...): look
    # INSIDE them, 'gtk' is not one of them.
    if sys.platform != 'linux' or not any('gtk' in str(p).lower() for p in wx.PlatformInfo):
        return None
    try:
        import ctypes
        gtk = ctypes.CDLL('libgtk-3.so.0')
        atk = ctypes.CDLL('libatk-1.0.so.0')
        gobject = ctypes.CDLL('libgobject-2.0.so.0')
        gtk.gtk_widget_get_accessible.argtypes = [ctypes.c_void_p]
        gtk.gtk_widget_get_accessible.restype = ctypes.c_void_p
        gtk.gtk_bin_get_child.argtypes = [ctypes.c_void_p]
        gtk.gtk_bin_get_child.restype = ctypes.c_void_p
        gtk.gtk_scrolled_window_get_type.restype = ctypes.c_size_t
        gobject.g_type_check_instance_is_a.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        gobject.g_type_check_instance_is_a.restype = ctypes.c_int
        atk.atk_object_set_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        atk.atk_object_set_name.restype = None
        _gtk_libs = (gtk, atk, gobject)
    except Exception:
        return None
    return _gtk_libs


def gtk_set_accessible_name(window, name):
    """Give a wx control's GTK widget the ATK name Orca announces.

    ``wx.Window.SetName`` on GTK is wx's own bookkeeping and never reaches
    the accessibility tree - measured under WSLg through AT-SPI: Titan's
    application list was a table with no name beside a label saying
    "Lista aplikacji:". ATK is asked directly, through the widget handle.
    """
    libs = _gtk()
    if libs is None:
        return False
    gtk, atk, gobject = libs
    try:
        # GetHandle() is the X window id, which under XWayland is 0 for
        # anything but a native window; GetGtkWidget() is the GtkWidget.
        handle = int(window.GetGtkWidget())
        if not handle:
            return False
        encoded = str(name or '').encode('utf-8')
        accessible = gtk.gtk_widget_get_accessible(handle)
        if not accessible:
            return False
        atk.atk_object_set_name(accessible, encoded)
        # A wx list is a GtkScrolledWindow round the GtkTreeView, and the
        # tree view is what a reader lands on (measured: the focused
        # control was a 'table' with no name while its scrolled window had
        # one). The child gets the name too - only for a scrolled window,
        # since a button's child is its label and must keep its own text.
        if gobject.g_type_check_instance_is_a(handle, gtk.gtk_scrolled_window_get_type()):
            child = gtk.gtk_bin_get_child(handle)
            if child:
                child_accessible = gtk.gtk_widget_get_accessible(child)
                if child_accessible:
                    atk.atk_object_set_name(child_accessible, encoded)
        return True
    except Exception:
        return False


_gtk_names_installed = False


def install_gtk_names():
    """Make every ``SetName`` in Titan reach ATK on GTK.

    Titan names its controls for screen readers with ``SetName`` in hundreds
    of places, written for MSAA. One hook here, rather than a second call
    at each of them, and off GTK it does nothing at all.
    """
    global _gtk_names_installed
    if _gtk_names_installed or _gtk() is None:
        return False
    original = wx.Window.SetName

    def set_name(self, name):
        original(self, name)
        gtk_set_accessible_name(self, name)

    wx.Window.SetName = set_name
    # A top-level window's title is its name to a reader; a frame without a
    # caption (the Start menu, the bar) has one in wx and none in ATK.
    original_title = wx.TopLevelWindow.SetTitle

    def set_title(self, title):
        original_title(self, title)
        gtk_set_accessible_name(self, title)

    wx.TopLevelWindow.SetTitle = set_title
    # A title given at construction never goes through SetTitle: name the
    # window as it is shown.
    original_show = wx.TopLevelWindow.Show

    def show(self, show=True):
        result = original_show(self, show)
        if show:
            try:
                title = self.GetTitle()
                if title:
                    gtk_set_accessible_name(self, title)
            except Exception:
                pass
        return result

    wx.TopLevelWindow.Show = show
    _gtk_names_installed = True
    return True


_ATK_ROLES = {
    'button': 42, 'list item': 33, 'list': 32, 'text': 60, 'label': 28,
    'panel': 38, 'check box': 8, 'menu item': 30, 'tab': 36, 'slider': 50,
    'progress bar': 43, 'link': 56, 'tool bar': 62, 'status bar': 53,
    'combo box': 9, 'radio button': 44, 'tree': 62 + 1, 'separator': 46,
}


def atk_role_name(msaa_role):
    """The ATK role word for one of the MSAA roles the shell's controls use."""
    return {ROLE_BUTTON: 'button', ROLE_LIST: 'list', ROLE_LISTITEM: 'list item',
            ROLE_TOOLBAR: 'tool bar', ROLE_MENUITEM: 'menu item',
            ROLE_STATICTEXT: 'label', ROLE_CLIENT: 'panel', ROLE_CLOCK: 'label',
            }.get(msaa_role, '')


def gtk_set_accessible_role(window, role_name):
    """Give a painted control the ATK role its MSAA role says it is.

    The shell's controls are drawn by Titan and answer MSAA with a role of
    their own; GTK sees a plain widget. `atk_object_set_role` makes Orca
    say "button" or "list item" for it, as MSAA readers do.
    """
    libs = _gtk()
    if libs is None:
        return False
    gtk, atk, _gobject = libs
    role = _ATK_ROLES.get(str(role_name or '').lower())
    if role is None:
        return False
    try:
        import ctypes
        if not hasattr(atk, '_role_typed'):
            atk.atk_object_set_role.argtypes = [ctypes.c_void_p, ctypes.c_int]
            atk.atk_object_set_role.restype = None
            atk._role_typed = True
        handle = int(window.GetGtkWidget())
        accessible = gtk.gtk_widget_get_accessible(handle) if handle else 0
        if not accessible:
            return False
        atk.atk_object_set_role(accessible, role)
        return True
    except Exception:
        return False


def name_control(window, name):
    """Name a native control for wx **and** for every screen reader.

    Returns the accessible object, so a control whose name changes (the
    search results and their count) can be renamed without building a new
    one.
    """
    gtk_set_accessible_name(window, name)
    try:
        # The BASE SetName, not the window's own: CheckList.SetName calls
        # this function, so calling its override back is a recursion that
        # Windows swallowed at the recursion limit (a thousand frames, per
        # rename, silently) and GTK ended in a fatal stack overflow.
        wx.Window.SetName(window, name or '')
    except Exception:
        pass
    accessible = getattr(window, '_shell_accessible', None)
    try:
        if accessible is None:
            accessible = NamedAccessible(window, name)
            window.SetAccessible(accessible)
            window._shell_accessible = accessible
        else:
            accessible.set_name(name)
        wx.Accessible.NotifyEvent(
            getattr(wx, 'ACC_EVENT_OBJECT_NAMECHANGE', 0x800C), window,
            getattr(wx, 'OBJID_CLIENT', -4), 0)
    except Exception:
        # A wx build without MSAA support still has the wx-side name.
        pass
    return accessible


class AccessibleMixin:
    """Mixin for a painted control that must be readable and focusable.

    A control mixes this in, sets `accessible_name` (or overrides
    `shell_name`) and gets an MSAA identity plus a panned focus cue.  It does
    not get a voice: the user's screen reader is what reads the name this
    provides.
    """

    accessible_name = ''
    accessible_role = ROLE_BUTTON
    accessible_description = ''
    accessible_action = ''

    def install_accessibility(self):
        try:
            self.SetName(self.shell_name() or '')
        except Exception:
            pass
        try:
            self.SetAccessible(ShellAccessible(self))
        except Exception:
            # A wx build without MSAA support still gives the control a name.
            pass
        # On GTK the painted control is a plain widget to ATK; the name
        # went through SetName (install_gtk_names), the role goes here.
        try:
            gtk_set_accessible_role(self, atk_role_name(self.shell_role()))
        except Exception:
            pass
        try:
            self.Bind(wx.EVT_SET_FOCUS, self._on_shell_focus)
        except Exception:
            pass

    # -- what the accessibility layer asks for ----------------------------
    def shell_name(self):
        return self.accessible_name

    def shell_role(self):
        return self.accessible_role

    def shell_description(self):
        return self.accessible_description

    def shell_default_action(self):
        return self.accessible_action

    def shell_state(self):
        state = STATE_FOCUSABLE
        try:
            if self.HasFocus():
                state |= STATE_FOCUSED
        except Exception:
            pass
        return state

    def shell_activate(self):
        """Pressed by the accessibility layer; controls override this."""

    # -- focus ------------------------------------------------------------
    def notify_focus_event(self):
        """Tell the accessibility layer the focus moved to this control.

        A painted control does not raise an MSAA focus event by itself, and
        without one a screen reader has nothing to react to - which is the
        whole reason this shell is readable at all.
        """
        try:
            wx.Accessible.NotifyEvent(
                getattr(wx, 'ACC_EVENT_OBJECT_FOCUS', 0x8005), self,
                getattr(wx, 'OBJID_CLIENT', -4), 0)
        except Exception:
            pass

    def _on_shell_focus(self, event):
        try:
            self.Refresh()
            focus_cue(screen_position(self))
            self.notify_focus_event()
        except Exception:
            pass
        event.Skip()

    def refresh_accessible_name(self):
        """Re-publish the name after it changed (a window title, the clock)."""
        try:
            self.SetName(self.shell_name() or '')
        except Exception:
            pass
        try:
            wx.Accessible.NotifyEvent(
                getattr(wx, 'ACC_EVENT_OBJECT_NAMECHANGE', 0x800C), self,
                getattr(wx, 'OBJID_CLIENT', -4), 0)
        except Exception:
            pass


def role_name(role):
    """The word for a role, for names that have to spell one out."""
    return {
        ROLE_BUTTON: _("button"),
        ROLE_LIST: _("list"),
        ROLE_LISTITEM: _("item"),
        ROLE_TOOLBAR: _("toolbar"),
        ROLE_MENUITEM: _("menu item"),
        ROLE_CLOCK: _("clock"),
    }.get(role, '')

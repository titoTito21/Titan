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
"""

import wx

from src.settings.settings import get_setting
from src.titan_core.translation import _

try:
    from src.titan_core.sound import play_sound
except Exception:  # pragma: no cover - sound is optional for the shell
    def play_sound(*_args, **_kwargs):
        pass


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


def focus_cue(position=0.0):
    if not cues_enabled():
        return
    try:
        play_sound('core/FOCUS.ogg', pan=position)
    except Exception:
        pass


def select_cue(position=0.0):
    if not cues_enabled():
        return
    try:
        play_sound('core/SELECT.ogg', pan=position)
    except Exception:
        pass


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

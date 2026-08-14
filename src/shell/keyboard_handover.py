# -*- coding: utf-8 -*-
"""
Who the keyboard belongs to while one of Titan's own windows is in front.

The Invisible UI is Titan's non-visual interface, and with **Titan UI mode**
on it answers every key in the session - which is exactly right while Titan is
an application the user has put away, and exactly wrong the moment a window of
Titan's own is in front of them, because that window has a keyboard of its
own.  The main window has always known this: showing it calls
`temporarily_disable_titan_ui('main_window')` and minimising it hands the keys
back (`src/ui/gui.py`, `restore_from_tray` / `_on_window_minimize`).

**The shell's windows never did**, and under the shell that is the common case
rather than a rare one.  Windows+M minimises Titan; `on_minimize` answers by
putting Titan in the tray and starting the Invisible UI listening; and the
same shortcut then puts the keyboard on the desktop - a window whose whole
content is a list of the user's icons.  From there every arrow key went to the
Invisible UI instead of to the list, so the desktop read as though it had gone
and only a key the Invisible UI understood brought anything back.

So every shell window says who has the keyboard the moment it becomes the
active window, and gives it back when it stops being one.  It is the same
mechanism the main window uses, under one name - the windows of a shell hand
over to each other constantly, and they must not each be undoing the last
one's hand-over.
"""

import wx

#: One name for the whole shell.  The desktop, the bar, the Start menu and
#: the file browser pass the keyboard between themselves all the time; naming
#: them separately would mean the window being LEFT giving the Invisible UI
#: the keyboard back a moment after the window being ENTERED had taken it.
SHELL = 'titan_shell'


def invisible_ui():
    """Titan's Invisible UI, if this process has one."""
    try:
        app = wx.GetApp()
    except Exception:
        return None
    if app is None:
        return None
    frame = None
    try:
        frame = app.GetTopWindow()
    except Exception:
        frame = None
    interface = getattr(frame, 'invisible_ui', None)
    if interface is not None:
        return interface
    try:
        for window in wx.GetTopLevelWindows():
            interface = getattr(window, 'invisible_ui', None)
            if interface is not None:
                return interface
    except Exception:
        pass
    return None


def take_keyboard(name=SHELL):
    """A Titan window is in front: the Invisible UI stands down.

    A no-op when Titan UI mode is off or something else has already asked -
    `temporarily_disable_titan_ui` is what decides, and it remembers WHO
    asked, so only that one can give the keyboard back.
    """
    interface = invisible_ui()
    if interface is None:
        return False
    try:
        interface.temporarily_disable_titan_ui(name)
        return True
    except Exception as error:
        print(f"[TitanShell] could not quiet the Invisible UI: {error}")
        return False


def give_keyboard_back(name=SHELL):
    """The Titan window has gone: the Invisible UI may answer keys again."""
    interface = invisible_ui()
    if interface is None:
        return False
    try:
        interface._on_dialog_close(name, None)
        return True
    except Exception as error:
        print(f"[TitanShell] could not restore the Invisible UI: {error}")
        return False


def follows_activation(event, name=SHELL):
    """Wire an `EVT_ACTIVATE` straight through to the two calls above.

    Every shell window's activate handler ends with this, so the rule is
    written once: in front means the window's own keyboard, behind means the
    Invisible UI's.
    """
    try:
        active = bool(event.GetActive())
    except Exception:
        return False
    return take_keyboard(name) if active else give_keyboard_back(name)

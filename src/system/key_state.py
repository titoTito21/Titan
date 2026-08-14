"""What the keyboard is REALLY doing, asked of Windows rather than of a cache.

Two of Titan's own mechanisms can leave a modifier key looking held when the
user is not holding it, and both of them belong to the shell:

* ``AttachThreadInput`` - which is how ``win_shell.take_foreground()`` gets
  the keyboard onto the taskbar, the desktop and the Start menu - MERGES the
  two threads' input queues, and the queue is where the per-thread key state
  that ``GetKeyState`` (and therefore ``wxKeyEvent::ShiftDown()``) answers
  from lives.  A modifier that was down across an attach/detach can stay
  latched in one of the queues afterwards: wx then reports Shift held for
  every key from then on, so Tab moves backwards for ever, F10 opens a
  context menu and an ordinary Escape is read as Shift+Escape.

* the ``keyboard`` library's own table, which is filled from the events its
  hook saw and so goes wrong permanently as soon as one event goes missing -
  the lock screen, Ctrl+Alt+Del and a UAC prompt each take a key up on a
  desktop no hook of ours runs on.

``GetAsyncKeyState`` is neither: it is the state of the hardware, not a
record of events and not a per-queue copy, so it cannot go stale and cannot
be latched by an input-queue attachment.  It is the same answer
``tce_system._key_physically_down`` already relies on for Control.

The one thing it cannot answer about is a key SUPPRESSED in a low-level hook
- such a key never reaches the system, so Windows reports it up while it is
held.  Titan suppresses only the Windows key, which is why nothing here is
about that key.
"""

import ctypes
import sys

IS_WINDOWS = sys.platform == 'win32'

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12          # Alt


def physically_down(vk):
    """Whether a key is held right now, according to the hardware state."""
    if not IS_WINDOWS:
        return True
    try:
        user32 = ctypes.windll.user32
        user32.GetAsyncKeyState.restype = ctypes.c_short
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        # Fail open: better to believe the event than to drop a real Shift.
        return True


def shift_down(event=None):
    """True only when Shift is really held.

    An event is believed only when Windows agrees with it, so a Shift left
    latched in this thread's input queue reads as "not pressed" - which is
    what the user asked for: pressing Shift is a press, not something the
    shell goes on holding.
    """
    if event is not None:
        try:
            if not event.ShiftDown():
                return False
        except Exception:
            pass
    return physically_down(VK_SHIFT)


def control_down(event=None):
    """True only when Control is really held."""
    if event is not None:
        try:
            if not event.ControlDown():
                return False
        except Exception:
            pass
    return physically_down(VK_CONTROL)


def alt_down(event=None):
    """True only when Alt is really held."""
    if event is not None:
        try:
            if not event.AltDown():
                return False
        except Exception:
            pass
    return physically_down(VK_MENU)


def modifiers(event):
    """The event's modifiers with any phantom Shift taken out.

    Control and Alt are left alone: nothing latches them the way an input
    queue latches Shift, and a wrong answer about them would break real
    shortcuts.  Returns a ``wx`` modifier mask.
    """
    try:
        import wx
    except Exception:
        return 0
    try:
        mask = event.GetModifiers()
    except Exception:
        return 0
    if mask & wx.MOD_SHIFT and not physically_down(VK_SHIFT):
        mask &= ~wx.MOD_SHIFT
    return mask

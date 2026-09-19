# -*- coding: utf-8 -*-
"""A real window that holds the keyboard while a list is walked.

The palette, a message and the virtual window are lists nothing draws:
the reader borrows the arrows for them and the program underneath is
never told. That is enough on the desktop, in Explorer, in a browser -
anywhere the program reads its keys the ordinary way and the reader's
hook takes them first. It is not enough in a program that reads the
keyboard ITSELF - Elten polls the keys it is interested in, a launcher
built on a game engine reads raw input, a game does both - because a key
the reader's hook swallowed still reaches those, so the arrows walked the
list AND moved the program's own cursor, and Enter chose a row here and
pressed something there. Reported as "the palette works on the desktop
and not in Elten or Battle.net".

What every reader does about that for its own dialogs is to give them a
window: the foreground one, so the program behind is not the foreground
and gets no keys at all. This is that window - one small frame, made
once and reused, shown while a list is up, put in FRONT with the same
input-queue attachment Titan's own shell uses to take the keyboard
(`AttachThreadInput` + `SetForegroundWindow`, because Windows refuses the
foreground to a process that does not already have it), and hidden again
with the foreground given BACK to the window the list was opened over.

Three rules keep it out of the way:

* **It says nothing.** Both readers swallow the focus event for it
  (:func:`is_host`), because the list already said its own title and its
  own row; a reader that read "Commands, window" over the top would say
  everything twice.
* **It is not the window the walkers ask about.** `left_the_window` in
  every walker compares the window in front against the one it was opened
  over, and this window in front is not the user leaving - so the walkers
  ask :func:`foreground_hwnd`, which answers the window UNDER the host
  while the host is up. The virtual window rebuilds for that window too.
* **Losing the foreground is asked about, not acted on.** A row's action
  can open a dialog, a click can make the program take the foreground
  back, the user can Alt+Tab away. On a deactivation the host asks the
  walker whether it is still up: if not, it hides; if the window in front
  is the one it was opened over, it takes the keyboard again (the program
  took it back and nothing new appeared); anything else - a dialog, a
  menu, another program - is left to the walker's own `left_the_window`,
  which follows a sub-window and stops for a different program.

Without wx (a test, a console) every call answers False and the walkers
work exactly as they did: a list that could not be given a window is
still a list.
"""

import threading

_LOCK = threading.RLock()

_state = {'hwnd': 0, 'over': 0, 'up': False, 'title': '', 'wanted': None,
          'frame': None, 'panel': None}

_counted = {'shown': 0, 'taken': 0, 'refused': 0, 'retaken': 0,
            'hidden': 0, 'given_back': 0, 'lost': 0}

#: How long after a deactivation the host asks what to do about it. The
#: focus event that says WHY it happened (a dialog opened, the user left)
#: arrives a moment after the deactivation itself.
LOST_DELAY_MS = 80

#: Where the frame is parked and how big it is. Two pixels at the top left:
#: a window that is on the screen and takes the foreground, and nothing a
#: sighted helper would notice.
SIZE = (2, 2)
POSITION = (0, 0)


# --------------------------------------------------------------------------- #
# What the walkers ask
# --------------------------------------------------------------------------- #
def available():
    """Whether there is a wx application to put a window in."""
    try:
        import wx
    except Exception:                                # noqa: BLE001
        return False
    try:
        return wx.GetApp() is not None
    except Exception:                                # noqa: BLE001
        return False


def _user32():
    import ctypes
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetAncestor.restype = ctypes.c_void_p
    return user32


def _raw_foreground():
    try:
        return int(_user32().GetForegroundWindow() or 0)
    except Exception:                                # noqa: BLE001
        return 0


def _root_of(hwnd):
    try:
        import ctypes
        return int(_user32().GetAncestor(ctypes.c_void_p(int(hwnd)), 2) or 0)
    except Exception:                                # noqa: BLE001
        return 0


def is_host(hwnd):
    """Whether this handle is the host window, or a control inside it."""
    try:
        hwnd = int(hwnd or 0)
    except (TypeError, ValueError):
        return False
    with _LOCK:
        mine = int(_state['hwnd'] or 0)
    if not mine or not hwnd:
        return False
    return hwnd == mine or _root_of(hwnd) == mine


def is_host_object(obj):
    """The same question about a reader's object (``windowHandle`` in
    NVDA's spelling, ``hwnd`` in Titan Access's)."""
    if obj is None:
        return False
    for name in ('windowHandle', 'hwnd'):
        try:
            handle = getattr(obj, name, 0)
        except Exception:                            # noqa: BLE001
            handle = 0
        if handle and is_host(handle):
            return True
    return False


def up():
    with _LOCK:
        return bool(_state['up'])


def hwnd():
    with _LOCK:
        return int(_state['hwnd'] or 0)


def over():
    """The window the list was opened over."""
    with _LOCK:
        return int(_state['over'] or 0)


def foreground_hwnd():
    """The window in front - the one UNDER the host while the host is up.

    This is what every walker's `left_the_window` compares, so the host
    taking the foreground is never mistaken for the user leaving.
    """
    now = _raw_foreground()
    if now and is_host(now):
        return over() or 0
    return now


def title():
    with _LOCK:
        return str(_state['title'] or '')


def report():
    with _LOCK:
        found = dict(_counted)
        found.update({'up': _state['up'], 'hwnd': _state['hwnd'],
                      'over': _state['over'], 'title': _state['title'],
                      'available': available()})
    return found


# --------------------------------------------------------------------------- #
# Showing and hiding
# --------------------------------------------------------------------------- #
def show(title, wanted, then=None):
    """Put the host in front of the window the user is in.

    ``wanted`` answers whether the list is still up - asked whenever the
    host loses the foreground, which is how it knows whether to take the
    keyboard back or go away. ``then`` runs once the host has the
    keyboard (or at once, where there is no wx), and is where a walker
    says its title: said before the focus has moved, a reader that
    cancels speech on a focus change would cut it off.

    A level opened over a level (the palette's commands over its layers)
    keeps the window the FIRST level was opened over: the user has not
    moved.
    """
    now = _raw_foreground()
    with _LOCK:
        if not (now and is_host(now)):
            _state['over'] = now
        _state.update({'title': str(title or ''), 'wanted': wanted,
                       'up': True})
        _counted['shown'] += 1
    if not available():
        if then is not None:
            _safely(then)
        return False
    import wx
    wx.CallAfter(_show_on_gui, then)
    return True


def retitle(title):
    """The list's title changed (a new level); the window's name follows."""
    with _LOCK:
        _state['title'] = str(title or '')
        frame = _state['frame']
    if frame is None or not available():
        return
    import wx
    wx.CallAfter(_retitle_on_gui)


def follow(over_hwnd, title=None):
    """The list now walks a sub-window that took the foreground: remember
    it as the window the host stands over, and take the keyboard back."""
    with _LOCK:
        if over_hwnd:
            _state['over'] = int(over_hwnd)
        if title is not None:
            _state['title'] = str(title or '')
        wanted_up = _state['up']
    if not wanted_up or not available():
        return
    import wx
    wx.CallAfter(_retake_on_gui)


def hide():
    """Go away, and give the keyboard back to the window underneath."""
    with _LOCK:
        was = _state['up']
        _state['up'] = False
        _state['wanted'] = None
    if not was or not available():
        return False
    import wx
    wx.CallAfter(_hide_on_gui)
    return True


def destroy():
    """The reader is going away; so is the window."""
    with _LOCK:
        _state['up'] = False
        frame = _state['frame']
        _state.update({'frame': None, 'panel': None, 'hwnd': 0})
    if frame is None:
        return
    try:
        import wx
        wx.CallAfter(_destroy_frame, frame)
    except Exception:                                # noqa: BLE001
        pass


def forget():
    """Tests: back to nothing."""
    destroy()
    with _LOCK:
        _state.update({'hwnd': 0, 'over': 0, 'up': False, 'title': '',
                       'wanted': None, 'frame': None, 'panel': None})
        for key in _counted:
            _counted[key] = 0


# --------------------------------------------------------------------------- #
# On the GUI thread
# --------------------------------------------------------------------------- #
def _safely(function, *args):
    try:
        return function(*args)
    except Exception:                                # noqa: BLE001
        return None


def _frame():
    """The one frame, made the first time it is needed."""
    with _LOCK:
        frame = _state['frame']
    if frame is not None:
        try:
            if frame:                # a destroyed wx window is falsy
                return frame
        except Exception:                            # noqa: BLE001
            pass
    import wx
    style = (wx.FRAME_TOOL_WINDOW | wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP
             | wx.CLIP_CHILDREN)
    frame = wx.Frame(None, title=title(), style=style, size=SIZE,
                     pos=POSITION)
    panel = wx.Panel(frame)
    panel.SetName(title())
    frame.Bind(wx.EVT_ACTIVATE, _on_activate)
    frame.Bind(wx.EVT_CLOSE, _on_close)
    with _LOCK:
        _state['frame'] = frame
        _state['panel'] = panel
        try:
            _state['hwnd'] = int(frame.GetHandle() or 0)
        except Exception:                            # noqa: BLE001
            _state['hwnd'] = 0
    return frame


def _show_on_gui(then):
    with _LOCK:
        wanted_up = _state['up']
    if not wanted_up:
        # Hidden again before this ran (a review that opened and closed
        # inside one event). Nothing to put up.
        if then is not None:
            _safely(then)
        return
    try:
        frame = _frame()
        frame.SetTitle(title())
        with _LOCK:
            panel = _state['panel']
        if panel is not None:
            panel.SetName(title())
        if not frame.IsShown():
            frame.Show()
        _take(hwnd())
        if panel is not None:
            _safely(panel.SetFocus)
    except Exception:                                # noqa: BLE001
        pass
    if then is not None:
        _safely(then)


def _retitle_on_gui():
    with _LOCK:
        frame = _state['frame']
        panel = _state['panel']
    try:
        if frame:
            frame.SetTitle(title())
        if panel:
            panel.SetName(title())
    except Exception:                                # noqa: BLE001
        pass


def _retake_on_gui():
    with _LOCK:
        wanted_up = _state['up']
    if not wanted_up:
        return
    _retitle_on_gui()
    if _take(hwnd()):
        with _LOCK:
            _counted['retaken'] += 1


def _hide_on_gui():
    with _LOCK:
        if _state['up']:
            return                   # a show came after the hide
        frame = _state['frame']
        mine = int(_state['hwnd'] or 0)
        back_to = int(_state['over'] or 0)
    if frame is None:
        return
    try:
        if mine and _raw_foreground() == mine and back_to and _exists(back_to):
            if _take(back_to):
                with _LOCK:
                    _counted['given_back'] += 1
        if frame.IsShown():
            frame.Hide()
        with _LOCK:
            _counted['hidden'] += 1
    except Exception:                                # noqa: BLE001
        pass


def _destroy_frame(frame):
    try:
        frame.Destroy()
    except Exception:                                # noqa: BLE001
        pass


def _on_close(event):
    """Alt+F4 on the host: it is not a document, so it is hidden rather
    than destroyed - and the list keeps its keys, since the reader still
    binds them."""
    try:
        event.Veto()
    except Exception:                                # noqa: BLE001
        pass
    with _LOCK:
        frame = _state['frame']
    try:
        if frame:
            frame.Hide()
    except Exception:                                # noqa: BLE001
        pass


def _on_activate(event):
    try:
        active = bool(event.GetActive())
    except Exception:                                # noqa: BLE001
        active = True
    try:
        event.Skip()
    except Exception:                                # noqa: BLE001
        pass
    if active:
        return
    with _LOCK:
        _counted['lost'] += 1
    try:
        import wx
        wx.CallLater(LOST_DELAY_MS, _after_lost)
    except Exception:                                # noqa: BLE001
        _after_lost()


def _after_lost():
    """The host is no longer in front. Ask the walker what that means."""
    with _LOCK:
        wanted_up = _state['up']
        wanted = _state['wanted']
        back_to = int(_state['over'] or 0)
        mine = int(_state['hwnd'] or 0)
    if not wanted_up:
        return
    still = False
    if wanted is not None:
        try:
            still = bool(wanted())
        except Exception:                            # noqa: BLE001
            still = False
    if not still:
        hide()
        return
    now = _raw_foreground()
    if not now or now == mine:
        return
    if now == back_to:
        # The program took the keyboard back (a click, a control that
        # activates its window) and nothing new appeared: the list is
        # still what the user is in, so the keys are its own again.
        if _take(mine):
            with _LOCK:
                _counted['retaken'] += 1
    # Anything else is a sub-window or another program, and the walker's
    # own `left_the_window` decides on the focus event that follows.


# --------------------------------------------------------------------------- #
# Taking the foreground
# --------------------------------------------------------------------------- #
def _exists(handle):
    try:
        import ctypes
        return bool(_user32().IsWindow(ctypes.c_void_p(int(handle))))
    except Exception:                                # noqa: BLE001
        return False


def _take(target):
    """Make ``target`` the foreground window. True when Windows agreed.

    `SetFocus` only moves the focus within the window that is already
    active, and Windows refuses `SetForegroundWindow` to a process that
    does not own the foreground - unless it is attached to the foreground
    thread's input queue, which is what lifts the refusal. The same move
    Titan's own shell makes for its taskbar.
    """
    if not target:
        return False
    try:
        import ctypes
        user32 = _user32()
        kernel32 = ctypes.windll.kernel32
        target = ctypes.c_void_p(int(target))
        foreground = user32.GetForegroundWindow()
        if foreground and int(foreground) == target.value:
            return True
        own_thread = kernel32.GetCurrentThreadId()
        threads = []
        if foreground:
            threads.append(user32.GetWindowThreadProcessId(
                ctypes.c_void_p(int(foreground)), None))
        threads.append(user32.GetWindowThreadProcessId(target, None))
        attached = [thread for thread in threads
                    if thread and thread != own_thread
                    and user32.AttachThreadInput(thread, own_thread, True)]
        try:
            user32.SetForegroundWindow(target)
            user32.SetActiveWindow(target)
            user32.SetFocus(target)
        finally:
            for thread in attached:
                user32.AttachThreadInput(thread, own_thread, False)
        took = int(user32.GetForegroundWindow() or 0) == target.value
        with _LOCK:
            _counted['taken' if took else 'refused'] += 1
        return took
    except Exception:                                # noqa: BLE001
        with _LOCK:
            _counted['refused'] += 1
        return False

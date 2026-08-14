# -*- coding: utf-8 -*-
"""
Work queued for later that must not outlive the window it was queued for.

The shell queues a great deal: a taskbar button asks Windows to activate a
window and rebuilds the bar 120 ms later, the appbar answers on a worker and
comes back to the GUI thread, the notification area is re-read four hundred
milliseconds after Explorer has been made to move the work area.  Every one of
those is a `wx.CallLater` or a `wx.CallAfter` holding a bound method of a
frame - and the shell's frames are destroyed the moment the shell is switched
off, the user exits Titan or the Shut Down dialog is answered.

wxPython does not know the difference.  When the timer fires it calls the
method it was given, the C++ object behind `self` is gone, and the first
attribute touched raises

    RuntimeError: wrapped C/C++ object of type TaskbarFrame has been deleted

*inside wx's event loop*, where there is nothing to catch it.  That is a
crash, and it is the one the shell produced most often: it needed only for a
window to be closed within the delay of anything it had queued.

So nothing in the shell calls `wx.CallLater` or `wx.CallAfter` directly with a
window's own method.  It goes through here, and here the window is asked
whether it is still alive *at the moment the call fires* rather than at the
moment it was queued.  `bool(window)` is wxPython's own answer to that
question (it is False for a deleted object), and `RuntimeError` catches the
rest - a window destroyed between the check and the call.
"""

import wx


def alive(window):
    """True when this wx object is still there to be called into."""
    if window is None:
        return False
    try:
        if not window:
            return False
        return not window.IsBeingDeleted()
    except RuntimeError:
        # The C++ side has gone; the Python wrapper is all that is left.
        return False
    except AttributeError:
        # Not a wx.Window - a wx.Timer, say.  `bool()` already answered.
        return True


def _guarded(window, function, args, kwargs):
    def run():
        if not alive(window):
            return None
        try:
            return function(*args, **kwargs)
        except RuntimeError as error:
            # Something the call touched was destroyed under it.  A queued
            # call must never raise into wx's event loop.
            print(f"[TitanShell] a deferred call was dropped: {error}")
            return None
    return run


def call_later(window, milliseconds, function, *args, **kwargs):
    """`wx.CallLater`, dropped if `window` has gone by the time it fires.

    Returns the timer, so a caller that wants to can stop it early; nobody
    has to, which is the point.
    """
    return wx.CallLater(milliseconds, _guarded(window, function, args, kwargs))


def call_after(window, function, *args, **kwargs):
    """`wx.CallAfter`, dropped if `window` has gone by the time it runs."""
    return wx.CallAfter(_guarded(window, function, args, kwargs))


class Coalesced:
    """One call, however many times it is asked for.

    The shell is told about a change far more often than it can usefully act
    on one: selecting a thousand files fires a thousand selection events, a
    program starting fires created/activated/redraw within a few
    milliseconds, and a folder being written to fires a notification per
    file.  Answering each one is what turned a Ctrl+A into half a minute.

    So the work is asked for as often as it likes and done once, at the end
    of the burst - and not at all if the window has gone in the meantime.
    """

    def __init__(self, window, function, milliseconds=0):
        self.window = window
        self.function = function
        self.milliseconds = int(milliseconds)
        self._timer = None
        self._pending = False

    def request(self):
        """Ask for the work; the first ask of a burst is the one that runs."""
        if self._pending:
            return False
        if not alive(self.window):
            return False
        self._pending = True
        if self.milliseconds > 0:
            self._timer = call_later(self.window, self.milliseconds, self._run)
        else:
            call_after(self.window, self._run)
        return True

    def cancel(self):
        """Forget what was asked for.

        The queued call itself cannot always be taken back - `wx.CallAfter`
        has no handle to stop - so what is cancelled is the ASK: the call
        still arrives and finds nothing outstanding to do.
        """
        self._pending = False
        if self._timer is not None:
            try:
                self._timer.Stop()
            except Exception:
                pass
            self._timer = None

    def now(self):
        """Do it at once, and forget anything that was asked for."""
        self.cancel()
        if alive(self.window):
            self.function()

    def _run(self):
        if not self._pending:
            return
        self._pending = False
        self._timer = None
        self.function()

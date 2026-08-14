# -*- coding: utf-8 -*-
"""
The painted controls the shell is built from.

Each one is a real `wx.Window`: it takes the keyboard focus, it has an HWND,
and it answers the accessibility layer with a name, a role and a state.  That
is deliberate.  A taskbar drawn as one big custom-painted panel would look
like XP and be a single unnamed rectangle to every screen reader; one window
per button costs a handle each and makes the bar navigable with nothing but
the keyboard.
"""

import wx

from src.shell import luna
from src.system import key_state
from src.shell.a11y import (AccessibleMixin, ROLE_BUTTON, ROLE_CLOCK,
                            STATE_FOCUSABLE, STATE_FOCUSED, STATE_PRESSED,
                            select_cue, screen_position)


def bitmap_from_icon_handle(handle, size=16):
    """Turn an HICON into something wx can draw, and own it.

    Every part of the shell that shows a real Windows icon - the quick
    launch buttons, the window buttons, the notification area - needs this,
    and it is worth having in one place because the ownership rule is easy
    to get wrong: `wx.Icon.SetHandle` takes the handle over, so the icon
    must not also be destroyed here.
    """
    if not handle:
        return None
    try:
        icon = wx.Icon()
        icon.SetHandle(handle)
        icon.SetWidth(size)
        icon.SetHeight(size)
        bitmap = wx.Bitmap()
        bitmap.CopyFromIcon(icon)
        return bitmap if bitmap.IsOk() else None
    except Exception:
        return None


class ShellControl(AccessibleMixin, wx.Window):
    """A focusable, painted, named control."""

    def __init__(self, parent, size=wx.DefaultSize, name=''):
        super().__init__(parent, size=size,
                         style=wx.WANTS_CHARS | wx.FULL_REPAINT_ON_RESIZE)
        self.accessible_name = name
        self.palette = luna.get_palette()
        self._hover = False
        self._pressed = False

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_left_dclick)
        self.Bind(wx.EVT_MIDDLE_UP, self._on_middle_up)
        self.Bind(wx.EVT_RIGHT_DOWN, lambda event: self.SetFocus())
        self.Bind(wx.EVT_RIGHT_UP, self._on_right_up)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_KILL_FOCUS, lambda event: (self.Refresh(),
                                                    event.Skip()))
        self.install_accessibility()

    # -- painting ---------------------------------------------------------
    def state_name(self):
        if self._pressed:
            return 'pressed'
        if self._hover:
            return 'hover'
        return 'normal'

    def paint(self, dc, rect):
        """Subclasses draw here; the background is already the bar's."""

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        rect = wx.Rect(0, 0, *self.GetSize())
        # The bar's own gradient runs behind every control, so a control
        # that does not fill its rectangle still sits on the taskbar rather
        # than on a grey hole.
        luna.draw_gradient(dc, self._background_rect(rect),
                           self.palette['taskbar_gradient'])
        self.paint(dc, rect)

    def _background_rect(self, rect):
        """The rectangle the bar's gradient is computed over.

        Controls are full-height children of the bar, so their own rectangle
        is the bar's - except for controls that are not, which override this.
        """
        return rect

    def refresh_palette(self, palette):
        self.palette = palette
        self.Refresh()

    # -- interaction ------------------------------------------------------
    def _on_enter(self, event):
        self._hover = True
        self.Refresh()
        event.Skip()

    def _on_leave(self, event):
        self._hover = False
        self._pressed = False
        self.Refresh()
        event.Skip()

    def _on_left_down(self, event):
        self._pressed = True
        self.SetFocus()
        self.Refresh()
        event.Skip()

    def _on_left_up(self, event):
        was_pressed = self._pressed
        self._pressed = False
        self.Refresh()
        if was_pressed:
            self.activate()
        event.Skip()

    def _on_left_dclick(self, event):
        # XP treats the second click of a double click as another press on
        # everything in the taskbar; only controls that mean something else
        # by it override this.
        self._on_left_up(event)

    def _on_middle_up(self, event):
        self.middle_activate()
        event.Skip()

    def middle_activate(self):
        """XP's middle click, where a control has one (close a window)."""

    def _on_right_up(self, event):
        self.show_context_menu()
        event.Skip()

    def set_tooltip(self, text):
        """The yellow hover tip a sighted user expects on a taskbar."""
        try:
            if text:
                self.SetToolTip(str(text))
            else:
                self.UnsetToolTip()
        except Exception:
            pass

    def _on_key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            self.activate()
        elif key == wx.WXK_WINDOWS_MENU or \
                (key == wx.WXK_F10 and key_state.shift_down(event)):
            self.show_context_menu()
        else:
            event.Skip()

    def activate(self):
        select_cue(screen_position(self))
        self.shell_activate()

    def show_context_menu(self):
        """Subclasses that have one build it here."""

    def AcceptsFocusFromKeyboard(self):
        return True

    def AcceptsFocus(self):
        return True


class TextControl(ShellControl):
    """A painted label that is still a real, focusable, named control.

    The clock is the reason this exists: it must be reachable with Tab and
    readable by name, which a `wx.StaticText` on a gradient is not.
    """

    accessible_role = ROLE_CLOCK

    def __init__(self, parent, text='', name='', colour_key='clock_text',
                 bold=False, size=wx.DefaultSize):
        self._text = text
        self._colour_key = colour_key
        self._bold = bold
        super().__init__(parent, size=size, name=name or text)

    def set_text(self, text, name=None):
        # Nothing to say, nothing to repaint.  The clock is told the time
        # every second and its text changes once a minute; without the name
        # being compared as well, the taskbar repainted itself and told
        # MSAA its clock had been renamed sixty times for every one time
        # either was true.
        if text == self._text and (name is None
                                   or name == self.accessible_name):
            return
        self._text = text
        if name is not None:
            self.accessible_name = name
        self.refresh_accessible_name()
        self.Refresh()

    def get_text(self):
        return self._text

    def paint(self, dc, rect):
        dc.SetFont(self.palette.font(size=8, bold=self._bold))
        dc.SetTextForeground(self.palette[self._colour_key])
        width, height = dc.GetTextExtent(self._text)
        dc.DrawText(self._text, (rect.width - width) // 2,
                    (rect.height - height) // 2)
        if self.HasFocus():
            dc.SetPen(wx.Pen(self.palette[self._colour_key], 1,
                             wx.PENSTYLE_DOT))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle(1, 2, rect.width - 2, rect.height - 4)


class IconTextControl(ShellControl):
    """A button drawn as XP draws a task button: icon, then text."""

    def __init__(self, parent, text='', icon=None, name='', size=wx.DefaultSize):
        self._text = text
        self._icon = icon
        super().__init__(parent, size=size, name=name or text)

    def set_text(self, text):
        self._text = text
        self.accessible_name = text
        self.refresh_accessible_name()
        self.Refresh()

    def set_icon(self, icon):
        self._icon = icon
        self.Refresh()

    def button_state(self):
        return self.state_name()

    def paint(self, dc, rect):
        state = self.button_state()
        luna.draw_task_button(dc, wx.Rect(0, 2, rect.width - 1,
                                          rect.height - 4),
                              self.palette, state=state,
                              focused=self.HasFocus())
        text_left = 6
        if self._icon is not None and self._icon.IsOk():
            try:
                dc.DrawBitmap(self._icon, 5,
                              (rect.height - self._icon.GetHeight()) // 2, True)
                text_left = 5 + self._icon.GetWidth() + 4
            except Exception:
                pass

        dc.SetFont(self.palette.font(size=8))
        dc.SetTextForeground(self.palette['task_text'])
        available = max(0, rect.width - text_left - 8)
        text = self._elide(dc, self._text, available)
        _width, height = dc.GetTextExtent(text)
        dc.DrawText(text, text_left, (rect.height - height) // 2)

    @staticmethod
    def _elide(dc, text, available):
        """XP truncates a long title with an ellipsis; so do we."""
        if not text:
            return ''
        width, _height = dc.GetTextExtent(text)
        if width <= available:
            return text
        ellipsis = '...'
        for length in range(len(text) - 1, 0, -1):
            candidate = text[:length] + ellipsis
            if dc.GetTextExtent(candidate)[0] <= available:
                return candidate
        return ellipsis

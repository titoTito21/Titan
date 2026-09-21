"""Side panels of the main window: a list of somebody else's, between the
current view and the status bar.

Elten's main screen is a column of SECTIONS - the notifications, the quick
actions, the feed, and whatever an application's extension contributes with
`main_tab` (the Weather forecast is one) - walked with Tab. Titan's main
window had two such places, the current view and the status bar, and
nothing an add-on could put between them: a component's list could only
be a VIEW, one more card of the tab bar, which is a different thing from a
panel that is always there.

So this is a third place. A side panel is a label and a control an add-on
owns, inserted into the main window's column just before the status bar,
and the Tab ring becomes: the current view, the side panels in the order
they were added, the status bar, and round again. Enter on one goes to the
owner's `on_activate`; the arrows are the control's own. A panel is taken
away as cleanly as it was added, with the keyboard moved off it first, so
an application whose widget has gone never leaves the focus on a control
that is about to be destroyed.

Kept out of `gui.py` so it can be driven against a bare `wx.Frame`.
"""
import wx


class SidePanels(object):
    def __init__(self, parent, sizer, before, view_control, statusbar,
                 border=10):
        """`parent`: the window the controls belong to. `sizer`: the main
        column. `before`: the window (the status bar's label) every panel is
        inserted in front of. `view_control`: a callable answering the
        current view's control. `statusbar`: the status bar's list."""
        self.parent = parent
        self.sizer = sizer
        self.before = before
        self.view_control = view_control
        self.statusbar = statusbar
        self.border = border
        self.panels = []

    # ------------------------------------------------------------- adding
    def add(self, panel_id, label, control, on_activate=None):
        """Put a control into the column before the status bar. Adding an
        id that is already there replaces its label and handler and keeps
        the control, so a refresh is not a second panel."""
        panel_id = str(panel_id)
        held = self.find(panel_id)
        if held is not None:
            held['on_activate'] = on_activate
            if held['label'] != label:
                held['label'] = label
                held['label_control'].SetLabel(label + ':')
                held['control'].SetName(label)
            return held
        label_control = wx.StaticText(self.parent, label=label + ':')
        control.SetName(label)
        index = self._index_of(self.before)
        self.sizer.Insert(index, label_control,
                          flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=self.border)
        self.sizer.Insert(index + 1, control, proportion=1,
                          flag=wx.EXPAND | wx.ALL, border=self.border)
        held = {'id': panel_id, 'label': label, 'label_control': label_control,
                'control': control, 'on_activate': on_activate}
        self.panels.append(held)
        self._layout()
        return held

    def remove(self, panel_id):
        """Take a panel away. The keyboard, if it was on the panel, goes to
        the current view first."""
        held = self.find(str(panel_id))
        if held is None:
            return False
        self.panels.remove(held)
        try:
            if self._focused() is held['control']:
                self.focus_view()
        except Exception:
            pass
        for window in (held['label_control'], held['control']):
            try:
                self.sizer.Detach(window)
            except Exception:
                pass
            try:
                window.Destroy()
            except Exception:
                pass
        self._layout()
        return True

    def find(self, panel_id):
        for held in self.panels:
            if held['id'] == panel_id:
                return held
        return None

    def ids(self):
        return [held['id'] for held in self.panels]

    # ------------------------------------------------------------ the ring
    def controls(self):
        return [held['control'] for held in self.panels if self._shown(held['control'])]

    def holds(self, control):
        return any(held['control'] is control for held in self.panels)

    def ring(self):
        """The Tab ring: the current view, the panels, the status bar."""
        chain = []
        try:
            view = self.view_control()
        except Exception:
            view = None
        if view is not None:
            chain.append(view)
        chain.extend(self.controls())
        if self.statusbar is not None:
            chain.append(self.statusbar)
        return chain

    def next_after(self, control, backwards=False):
        """Where Tab (or Shift+Tab) goes from `control`, or None when the
        control is not on the ring at all."""
        chain = self.ring()
        for index, candidate in enumerate(chain):
            if candidate is control:
                step = -1 if backwards else 1
                return chain[(index + step) % len(chain)]
        return None

    def activate(self, control, event=None):
        """Enter on a panel's control: the owner's handler. True when it
        was a panel's."""
        for held in self.panels:
            if held['control'] is control:
                handler = held.get('on_activate')
                if handler is not None:
                    try:
                        handler(event)
                    except Exception as error:
                        print('[side panels] %s: %s' % (held['id'], error))
                return True
        return False

    def focus_view(self):
        try:
            view = self.view_control()
            if view is not None:
                view.SetFocus()
        except Exception:
            pass

    # ------------------------------------------------------------ private
    def _index_of(self, window):
        for index, item in enumerate(self.sizer.GetChildren()):
            if item.IsWindow() and item.GetWindow() is window:
                return index
        return len(self.sizer.GetChildren())

    def _layout(self):
        try:
            self.parent.Layout()
        except Exception:
            pass

    @staticmethod
    def _shown(control):
        try:
            return bool(control) and control.IsShown()
        except Exception:
            return False

    @staticmethod
    def _focused():
        try:
            return wx.Window.FindFocus()
        except Exception:
            return None

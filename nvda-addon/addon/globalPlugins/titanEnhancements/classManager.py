# -*- coding: utf-8 -*-
"""The class manager: a window onto what each kind of thing sounds like.

:mod:`classes` is the model - which semantic class has which pitch, rate and
volume, and whose answer that is. This is the one place a user can see the
whole list, hear one, change it and put it back.

**It is accessible because it is native.** A list, three spin controls and
four buttons, each a real control with a real label, so a reader announces
every one of them without a word being written here. That is the same rule
the Titan shell arrived at and the same rule this add-on applies to
everything else it puts on the screen.

**A change is HEARD before it is kept.** Whether a two-point pitch change is
audible depends on the synthesizer, the rate and the listener - which is
exactly the kind of question that cannot be answered by reading a number.
So Try speaks the sample in the voice as it stands, on the synthesizer the
user really has.
"""

from . import classes
from . import i18n

_ = i18n.install(globals())


def build():
    """The dialog class, or None when there is no wx."""
    try:
        import wx
        from gui import guiHelper
    except Exception:                                # noqa: BLE001
        return None

    class ClassManager(wx.Dialog):

        def __init__(self, parent):
            # Translators: the title of the voice class manager.
            super().__init__(parent, title=_('Voice classes'))
            self._rows = classes.described()
            main = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

            # Translators: the label of the list of voice classes.
            self.list = main.addLabeledControl(
                _('What is being said'), wx.ListBox,
                choices=[self._label(row) for row in self._rows])
            self.list.Bind(wx.EVT_LISTBOX, self._chosen)
            if self._rows:
                self.list.SetSelection(0)

            dials = main.addItem(guiHelper.BoxSizerHelper(
                self, sizer=wx.StaticBoxSizer(
                    # Translators: a group in the voice class manager.
                    wx.StaticBox(self, label=_('How it sounds')),
                    wx.VERTICAL)))
            box = dials.sizer.GetStaticBox()

            def spin(label):
                return dials.addLabeledControl(
                    label, wx.SpinCtrl, min=-classes.LIMIT,
                    max=classes.LIMIT, initial=0)

            # Translators: a dial in the voice class manager.
            self.pitch = spin(_('Pitch'))
            # Translators: a dial in the voice class manager.
            self.rate = spin(_('Rate'))
            # Translators: a dial in the voice class manager.
            self.volume = spin(_('Volume'))

            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the voice class manager.
            try_it = buttons.addButton(self, label=_('&Try it'))
            try_it.Bind(wx.EVT_BUTTON, self._try)
            # Translators: a button in the voice class manager.
            keep = buttons.addButton(self, label=_('&Keep'))
            keep.Bind(wx.EVT_BUTTON, self._keep)
            # Translators: a button in the voice class manager.
            back = buttons.addButton(self, label=_('Put this one &back'))
            back.Bind(wx.EVT_BUTTON, self._back)
            # Translators: a button in the voice class manager.
            all_back = buttons.addButton(self, label=_('Put them &all back'))
            all_back.Bind(wx.EVT_BUTTON, self._all_back)
            main.addItem(buttons)
            main.addDialogDismissButtons(
                self.CreateButtonSizer(wx.CLOSE))
            self.Bind(wx.EVT_BUTTON, self._close, id=wx.ID_CLOSE)
            self.EscapeId = wx.ID_CLOSE

            self._show()
            self.Sizer = main.sizer
            main.sizer.Fit(self)
            self.CentreOnScreen()

        # ------------------------------------------------------------ helpers
        def _label(self, row):
            said = row['meaning'] or row['id']
            if row['changed']:
                # Translators: marks a voice class the user has changed.
                return _('{what} (changed)').format(what=said)
            return said

        def _current(self):
            index = self.list.GetSelection()
            if index < 0 or index >= len(self._rows):
                return None
            return self._rows[index]

        def _show(self):
            row = self._current()
            voice = (row or {}).get('voice') or {}
            self.pitch.SetValue(int(voice.get('pitch') or 0))
            self.rate.SetValue(int(voice.get('rate') or 0))
            self.volume.SetValue(int(voice.get('volume') or 0))

        def _dials(self):
            return {'pitch': self.pitch.GetValue(),
                    'rate': self.rate.GetValue(),
                    'volume': self.volume.GetValue()}

        def _refresh(self, keep_at=None):
            self._rows = classes.described()
            at = self.list.GetSelection() if keep_at is None else keep_at
            self.list.Set([self._label(row) for row in self._rows])
            if 0 <= at < len(self._rows):
                self.list.SetSelection(at)
            self._show()

        # ------------------------------------------------------------ actions
        def _chosen(self, _event):
            self._show()

        def _try(self, _event):
            """Speak the sample as the dials stand, not as they are stored.

            The whole point of the button: the user is deciding whether a
            change is audible, and a preview of what is already saved would
            answer a different question.
            """
            row = self._current()
            if row is None:
                return
            from . import compat
            from . import voices
            speech = compat.speech
            if speech is None:
                return
            try:
                speech.speak(voices.sequence(
                    [(classes.sample_text(row['id']), self._dials())]))
            except Exception:                        # noqa: BLE001
                pass

        def _keep(self, _event):
            row = self._current()
            if row is None:
                return
            classes.set_voice(row['id'], self._dials())
            self._refresh()

        def _back(self, _event):
            row = self._current()
            if row is None:
                return
            classes.reset(row['id'])
            self._refresh()

        def _all_back(self, _event):
            classes.reset(None)
            self._refresh(keep_at=0)

        def _close(self, _event):
            self.Destroy()

    return ClassManager


def show(parent=None):
    """Put the manager up. Answers whether it could."""
    manager = build()
    if manager is None:
        return False
    try:
        import gui
        import wx
        if parent is None:
            parent = gui.mainFrame
        def open_it():
            dialog = manager(parent)
            dialog.Show()
        wx.CallAfter(open_it)
        return True
    except Exception:                                # noqa: BLE001
        return False

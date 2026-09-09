# -*- coding: utf-8 -*-
"""The few windows this add-on puts up, in NVDA's own idiom.

Everything here runs on NVDA's main thread and goes through
``gui.mainFrame.prePopup`` / ``postPopup``, which is how NVDA gives a dialog
the foreground and takes it back afterwards. A dialog raised any other way
comes up behind whatever the user was in, which for somebody who cannot see
it is a window that did not open.

The controls are plain wx, deliberately: NVDA reads a real ``wx.ListBox``
and a real ``wx.Button`` already, and a hand-drawn list would be a control
NVDA has to be taught about.
"""

from . import i18n

_ = i18n.install(globals())


def _gui():
    try:
        import gui
        return gui
    except Exception:                                # noqa: BLE001
        return None


def _wx():
    try:
        import wx
        return wx
    except Exception:                                # noqa: BLE001
        return None


def message(text, title=None, error=False):
    """One sentence to the user. Spoken by NVDA because it is a real dialog."""
    gui = _gui()
    wx = _wx()
    if gui is None or wx is None:
        return
    caption = title or _('Titan')
    style = wx.ICON_ERROR | wx.OK if error else wx.ICON_INFORMATION | wx.OK

    def show():
        gui.messageBox(text, caption, style)
    wx.CallAfter(show)


def report(text, voice_class='notification'):
    """Say something without a window - the answer to most gestures.

    Everything this add-on tells the user goes through here, so this is
    where the **notification** class is applied: what a reader says ABOUT
    the machine is not what it says about the control the user is on, and a
    listener is entitled to hear the difference before the words arrive.

    A class that names a synthesizer of its own is spoken by it and NVDA is
    not asked; a class that names only dials is spoken by NVDA with them
    applied; a class the user has left alone is spoken exactly as it always
    was. Every one of those ends with the message being said.
    """
    from . import compat
    try:
        from . import voices
        if voices.say_whole(voice_class, text):
            return
    except Exception:                                # noqa: BLE001
        pass
    if compat.ui is None:
        return
    try:
        from . import voices
        sequence = voices.sequence([(str(text), voice_class)])
        if sequence and compat.speech is not None:
            compat.speech.speak(sequence)
            return
    except Exception:                                # noqa: BLE001
        pass
    try:
        compat.ui.message(text)
    except Exception:                                # noqa: BLE001
        pass


def browse(text, title=None):
    """A page to read, with the reader's own cursor on it.

    ``browseableMessage`` is NVDA's own, so find, say-all and copy all work
    - which is what somebody wants from a screen that has just been read to
    them by AI OCR, and what a message box would not give them.
    """
    from . import compat
    if compat.ui is None:
        return
    try:
        compat.ui.browseableMessage(text, title or _('Titan'))
    except Exception:                                # noqa: BLE001
        report(text)


def choose(rows, title, prompt=None, on_chosen=None):
    """Pick one of ``rows`` (label strings). ``on_chosen(index)`` afterwards.

    Asynchronous, because a gesture handler must return: NVDA's main thread
    is the one reading the screen, and a modal loop entered from inside a
    script is a reader that has stopped answering.
    """
    gui = _gui()
    wx = _wx()
    if gui is None or wx is None or not rows:
        return

    def show():
        gui.mainFrame.prePopup()
        try:
            dialog = wx.SingleChoiceDialog(gui.mainFrame,
                                           prompt or _('Choose:'),
                                           title, list(rows))
            try:
                if dialog.ShowModal() == wx.ID_OK and on_chosen is not None:
                    on_chosen(dialog.GetSelection())
            finally:
                dialog.Destroy()
        finally:
            gui.mainFrame.postPopup()
    wx.CallAfter(show)


def ask_text(prompt, title, on_answer=None, default=''):
    """One line of text from the user, asked the same way."""
    gui = _gui()
    wx = _wx()
    if gui is None or wx is None:
        return

    def show():
        gui.mainFrame.prePopup()
        try:
            dialog = wx.TextEntryDialog(gui.mainFrame, prompt, title, default)
            try:
                if dialog.ShowModal() == wx.ID_OK and on_answer is not None:
                    on_answer(dialog.GetValue())
            finally:
                dialog.Destroy()
        finally:
            gui.mainFrame.postPopup()
    wx.CallAfter(show)


def confirm(prompt, title, on_yes=None, on_no=None):
    """Ask a yes/no question. ``on_yes()`` only when the answer is yes.

    A real ``wx.MessageDialog`` with YES_NO, so NVDA reads it as the question
    it is and Escape means no - which for a dialog put up by a key the user
    pressed by accident is the only safe default.

    ``on_no`` matters where a refusal is an ANSWER rather than the absence
    of one: a question the reader asks by itself - "this window shows
    nothing, shall I read it as a picture?" - must write the no down, or it
    is asked again the next time that window comes to the front, for ever.
    Escape counts as no, because it is one.
    """
    gui = _gui()
    wx = _wx()
    if gui is None or wx is None:
        return

    def show():
        gui.mainFrame.prePopup()
        try:
            dialog = wx.MessageDialog(gui.mainFrame, prompt, title,
                                      wx.YES_NO | wx.NO_DEFAULT
                                      | wx.ICON_QUESTION)
            try:
                said_yes = dialog.ShowModal() == wx.ID_YES
            finally:
                dialog.Destroy()
            if said_yes:
                if on_yes is not None:
                    on_yes()
            elif on_no is not None:
                on_no()
        finally:
            gui.mainFrame.postPopup()
    wx.CallAfter(show)

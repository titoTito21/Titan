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

from . import compat
from . import i18n

_ = i18n.install(globals())


def _gui():
    """NVDA's interface, or Titan's own window where there is no NVDA.

    ``compat`` is what differs between the two trees, so this module is
    the same file in both: inside NVDA it is NVDA's ``gui``, inside Titan
    Access it is a shim whose ``mainFrame`` is Titan's own window.

    It answers None unless there really is a frame to put a window on.
    Every caller here already checks - and the alternative is a
    ``NoneType`` raised inside wx's own event loop, where nothing catches
    it and the user is told nothing at all.
    """
    found = compat.gui
    if found is None:
        return None
    try:
        if getattr(found, 'mainFrame', None) is None:
            return None
    except Exception:                                # noqa: BLE001
        return None
    return found


def _wx():
    try:
        import wx
        return wx
    except Exception:                                # noqa: BLE001
        return None


def message(text, title=None, error=False):
    """A message to the user, as text to WALK rather than a box to close.

    **A message box is a dialog, and a dialog is the wrong shape for an
    answer.** It takes the foreground away from the program the user was
    in, it has to be dismissed before anything else can happen, and what
    it says is said once - so a message that arrives while something else
    is speaking is cut in half. Short ones too: "krotkie komunikaty tez
    maja byc wirtualnym tekstem".

    So it becomes the same walked page every other answer here is: it
    says "Komunikat" on the way in, the arrows read it, and Escape says
    "Zamykam komunikat". The real message box is the fallback, for a
    machine where the walker could not be put up - and for an ERROR,
    which is the one message worth interrupting for.
    """
    caption = title or _('Titan')
    if not error:
        try:
            from . import palette
            ok, _said = palette.page(text, caption)
            if ok:
                _keep_keys_right()
                return
        except Exception:                            # noqa: BLE001
            pass
    gui = _gui()
    wx = _wx()
    if gui is None or wx is None:
        report(text)
        return
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
    """A long answer as something to WALK. Never something said once.

    **An answer that is spoken is an answer that gets interrupted.** A
    paragraph handed to `ui.message` is one utterance, and the next focus
    event cancels it halfway through - so Titan's status, what it can do,
    what an application said and the journal were all answers the user
    heard the beginning of. A reader that answers a question and is cut
    off has not answered it.

    So it is walked: the lines are a list, the arrows move through it,
    Enter says a line again and Escape closes. That is the same
    interaction as every other list in this add-on, which is the point -
    there is one way to read something here.

    NVDA's own `browseableMessage` is the fallback, because it gives find
    and copy on a machine where the walker could not be put up.
    """
    from . import palette
    try:
        ok, _said = palette.page(text, title or _('Titan'))
        if ok:
            _keep_keys_right()
            return
    except Exception:                                # noqa: BLE001
        pass
    from . import compat
    if compat.ui is None:
        return
    try:
        compat.ui.browseableMessage(text, title or _('Titan'))
    except Exception:                                # noqa: BLE001
        report(text)


def _keep_keys_right():
    """Ask the plugin to take the walker's keys, now that one is up.

    The palette borrows its arrows from the plugin, and nothing else
    would tell it that a page has just appeared.
    """
    try:
        import globalPluginHandler
        for plugin in getattr(globalPluginHandler, 'runningPlugins', []):
            keep = getattr(plugin, '_keep_palette_keys_right', None)
            if callable(keep):
                keep()
                return True
    except Exception:                                # noqa: BLE001
        pass
    return False


def choose(rows, title, prompt=None, on_chosen=None, on_cancel=None):
    """Pick one of ``rows`` (label strings). ``on_chosen(index)`` afterwards.

    Asynchronous, because a gesture handler must return: NVDA's main thread
    is the one reading the screen, and a modal loop entered from inside a
    script is a reader that has stopped answering.

    ``on_cancel`` is what Escape does, and it is what makes a list of
    lists walkable: **Escape goes back one level before it closes**, which
    is how every other list in Titan behaves and the only way a chooser
    that opens another chooser can be left without starting again. A list
    with nothing behind it passes None and Escape simply closes it.
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
                pressed = dialog.ShowModal()
                chosen = dialog.GetSelection()
            finally:
                dialog.Destroy()
        finally:
            gui.mainFrame.postPopup()
        # **Outside the popup, and after the dialog has gone.** What
        # either of these does is usually to put another window up, and
        # raising one from inside `prePopup`/`postPopup` nests NVDA's own
        # bookkeeping about which dialog it is in.
        if pressed == wx.ID_OK:
            if on_chosen is not None:
                on_chosen(chosen)
        elif on_cancel is not None:
            on_cancel()
    wx.CallAfter(show)


def customise(title, fields, on_kept=None):
    """A small form: several answers about one thing, in one window.

    ``fields`` is ``[{'id', 'kind', 'label', 'value', 'choices'}]`` where
    ``kind`` is 'text', 'check' or 'choice'. ``on_kept`` is called with
    ``{id: answer}``, or with ``None`` when the user cancelled - which is
    a different thing from every field being empty and has to stay
    tellable apart.

    **Every control is the real one for its kind**, which is the rule the
    whole add-on follows: a check box is a `wx.CheckBox` Windows itself
    reports as a check box with a state, a choice is a `wx.Choice` whose
    arrows announce the new value themselves. Nothing here is drawn, and
    nothing here says out loud what the platform already says.

    Asynchronous, like everything else in this module: a modal loop
    entered from inside a script is a reader that has stopped answering.
    """
    gui = _gui()
    wx = _wx()
    if gui is None or wx is None or not fields:
        return

    def show():
        gui.mainFrame.prePopup()
        try:
            dialog = wx.Dialog(gui.mainFrame, title=title,
                               style=wx.DEFAULT_DIALOG_STYLE
                               | wx.RESIZE_BORDER)
            outer = wx.BoxSizer(wx.VERTICAL)
            panel = wx.Panel(dialog)
            box = wx.BoxSizer(wx.VERTICAL)
            made = {}
            for field in fields:
                kind = str(field.get('kind') or 'text')
                label = str(field.get('label') or '')
                if kind == 'check':
                    control = wx.CheckBox(panel, label=label)
                    control.SetValue(bool(field.get('value')))
                    box.Add(control, 0, wx.ALL, 5)
                else:
                    box.Add(wx.StaticText(panel, label=label), 0,
                            wx.LEFT | wx.TOP, 5)
                    if kind == 'choice':
                        control = wx.Choice(
                            panel, choices=[str(one) for one
                                            in field.get('choices') or []])
                        try:
                            control.SetSelection(int(field.get('value') or 0))
                        except Exception:            # noqa: BLE001
                            control.SetSelection(0)
                    else:
                        control = wx.TextCtrl(
                            panel, value=str(field.get('value') or ''))
                    # The label is the static above it, which wx does not
                    # pass on to the platform for these - so it is given
                    # to the control itself as well.
                    try:
                        control.SetName(label)
                    except Exception:                # noqa: BLE001
                        pass
                    box.Add(control, 0, wx.EXPAND | wx.LEFT | wx.RIGHT
                            | wx.BOTTOM, 5)
                made[str(field.get('id') or label)] = (kind, control)
            panel.SetSizer(box)
            outer.Add(panel, 1, wx.EXPAND)
            buttons = dialog.CreateButtonSizer(wx.OK | wx.CANCEL)
            if buttons is not None:
                outer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
            dialog.SetSizer(outer)
            outer.Fit(dialog)
            dialog.CentreOnScreen()
            try:
                if dialog.ShowModal() != wx.ID_OK:
                    if on_kept is not None:
                        on_kept(None)
                    return
                answers = {}
                for name, (kind, control) in made.items():
                    if kind == 'check':
                        answers[name] = bool(control.GetValue())
                    elif kind == 'choice':
                        answers[name] = int(control.GetSelection())
                    else:
                        answers[name] = str(control.GetValue())
                if on_kept is not None:
                    on_kept(answers)
            finally:
                dialog.Destroy()
        finally:
            gui.mainFrame.postPopup()
    wx.CallAfter(show)


def ask_text(prompt, title, on_answer=None, default='', on_cancel=None):
    """One line of text from the user, asked the same way.

    ``on_cancel`` is what Escape does, for the same reason `choose` has
    one: a question asked from inside a list the user was walking has to
    put them back in that list when they decide not to answer it.
    Cancelling is an ANSWER - "leave it as it was" - and a caller that
    cannot hear it leaves somebody nowhere.
    """
    gui = _gui()
    wx = _wx()
    if gui is None or wx is None:
        return

    def show():
        gui.mainFrame.prePopup()
        try:
            dialog = wx.TextEntryDialog(gui.mainFrame, prompt, title, default)
            try:
                pressed = dialog.ShowModal()
                answer = dialog.GetValue()
            finally:
                dialog.Destroy()
        finally:
            gui.mainFrame.postPopup()
        # **Outside the popup, and after the dialog has gone** - the same
        # rule as `choose`: what either of these does is usually to put
        # another window up, and raising one from inside
        # `prePopup`/`postPopup` nests NVDA's own bookkeeping.
        if pressed == wx.ID_OK:
            if on_answer is not None:
                on_answer(answer)
        elif on_cancel is not None:
            on_cancel()
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

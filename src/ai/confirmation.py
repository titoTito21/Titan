# -*- coding: utf-8 -*-
"""
Asking the user whether the AI may do something - once, safely, for everybody.

The agent window, the assistant window and the windowless assistant each had a
copy of the same twenty lines: build a ``wx.MessageDialog`` on the GUI thread
with ``wx.CallAfter`` and wait for it with ``done.wait()``. Two things were
wrong with that, and both were reported as one sentence - "with the default
settings it keeps asking, and the question hangs the program":

* **It asked about everything.** ``titan_run_action`` is one tool for every
  action of every add-on, and it was marked ``confirm`` whatever the action
  itself declared - so saying the time, listing notes or reading a setting
  asked first. AI OCR's reads asked as well. Now an action's OWN risk decides
  (:func:`risk_of`, a tool may carry ``risk_of(args)``), and an answer can be
  "allow this for the rest of the session", so a run that sends five messages
  is one question, not five.
* **The wait could not end.** ``done.wait()`` had no deadline and looked at
  nothing: a dialog that failed to build (its parent destroyed, the frame
  hidden in the tray) left the worker waiting for ever, Shift+Escape could not
  reach it, and a question raised from the GUI thread itself waited for a
  ``CallAfter`` that thread would never run - the whole of Titan stopped. And
  a dialog parented to a hidden frame was behind everything with the Invisible
  UI still taking every key, so nobody could answer it.

So here: the policy is asked first, approvals are remembered, the dialog is a
window of its own put in front with the keyboard handed to it, a question
from the GUI thread is shown there and then, and the wait looks at the
cancel event and at whether the dialog is still alive.
"""

import threading

try:
    from src.titan_core.translation import set_language
    from src.settings.settings import get_setting
    _ = set_language(get_setting('language', 'pl'))
except Exception:                                    # noqa: BLE001
    def _(text):
        return text


#: What the user allowed for the rest of this Titan session, by key
#: (``tool`` or ``tool:addon.action``). Cleared by :func:`forget_approvals`.
_approved = set()
_lock = threading.Lock()

#: How the three answers come back from the dialog.
DENY, ONCE, SESSION = 'deny', 'once', 'session'

#: The keyboard hand-over name while a question is up.
_KEYBOARD_NAME = 'ai_confirmation'


# --------------------------------------------------------------------------- #
# What needs asking
# --------------------------------------------------------------------------- #
def risk_of(tool, args):
    """'auto', 'confirm' or 'always_confirm' for this call of this tool.

    A tool that stands for many things (``titan_run_action``) carries
    ``risk_of(args)`` and answers for the thing it is about to do; anything
    that goes wrong there is treated as 'confirm', never as 'auto'."""
    if not tool:
        return 'confirm'
    dynamic = tool.get('risk_of')
    if callable(dynamic):
        try:
            answer = dynamic(args or {})
            if answer in ('auto', 'confirm', 'always_confirm'):
                return answer
        except Exception as e:                       # noqa: BLE001
            print(f"[confirmation] risk_of failed for {tool.get('name')}: {e}")
        return 'confirm'
    if tool.get('always_confirm'):
        return 'always_confirm'
    return 'confirm' if tool.get('risk') == 'confirm' else 'auto'


def approval_key(tool, args):
    """What an approval is remembered under. For a tool that stands for many
    actions it is the action, so allowing "create a note" does not allow
    "delete a file"."""
    name = (tool or {}).get('name') or ''
    keyer = (tool or {}).get('approval_key')
    if callable(keyer):
        try:
            extra = keyer(args or {})
        except Exception:                            # noqa: BLE001
            extra = ''
        if extra:
            return f"{name}:{extra}"
    return name


def needs_confirm(tool, args, confirm_all=False):
    """Whether this call must be put to the user at all (before any policy
    or remembered approval is consulted)."""
    if tool is None:
        return False
    return bool(confirm_all) or risk_of(tool, args) != 'auto'


def is_approved(tool, args):
    with _lock:
        return approval_key(tool, args) in _approved


def approve(tool, args):
    with _lock:
        _approved.add(approval_key(tool, args))


def forget_approvals():
    """Take back every "allow for this session" answer."""
    with _lock:
        count = len(_approved)
        _approved.clear()
    return count


def approvals():
    with _lock:
        return sorted(_approved)


# --------------------------------------------------------------------------- #
# Asking
# --------------------------------------------------------------------------- #
def _describe(tool, args):
    try:
        from src.ai.agent_tools import describe_action
        desc = describe_action(tool.get('name'), args)
    except Exception:                                # noqa: BLE001
        desc = None
    return desc or tool.get('description') or tool.get('name') or ''


def _alive(window):
    if window is None:
        return False
    try:
        return bool(window) and window.IsShown()
    except Exception:                                # noqa: BLE001
        return False


class _QuestionDialog(object):
    """A small dialog of Titan's own: the sentence, then Allow, Allow for this
    session and Do not allow. Not a native message box - that one cannot have
    three buttons with these words, and cannot be raised by us."""

    def __init__(self, parent, title, message):
        import wx
        style = wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP
        self.dialog = wx.Dialog(parent if _alive(parent) else None,
                                title=title, style=style)
        panel = self.dialog
        sizer = wx.BoxSizer(wx.VERTICAL)
        # Plain dialog text, read by a screen reader when the dialog opens.
        # Not a multi-line text box: that keeps Enter for itself, and the
        # focus landing in it meant Enter answered nothing (measured).
        text = wx.StaticText(panel, label=message)
        text.Wrap(460)
        sizer.Add(text, 1, wx.ALL | wx.EXPAND, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.once = wx.Button(panel, wx.ID_YES, _("&Allow"))
        self.session = wx.Button(panel, wx.ID_YESTOALL,
                                 _("Allow for this &session"))
        self.deny = wx.Button(panel, wx.ID_NO, _("&Do not allow"))
        for button in (self.once, self.session, self.deny):
            row.Add(button, 0, wx.ALL, 5)
        sizer.Add(row, 0, wx.ALIGN_CENTER | wx.BOTTOM, 5)
        panel.SetSizerAndFit(sizer)
        self.answer = DENY
        self.once.Bind(wx.EVT_BUTTON, lambda e: self._end(ONCE, wx.ID_YES))
        self.session.Bind(wx.EVT_BUTTON,
                          lambda e: self._end(SESSION, wx.ID_YESTOALL))
        self.deny.Bind(wx.EVT_BUTTON, lambda e: self._end(DENY, wx.ID_NO))
        self.dialog.SetEscapeId(wx.ID_NO)
        self.dialog.SetAffirmativeId(wx.ID_YES)
        self.once.SetDefault()
        self._focus_on = self.once

    def _end(self, answer, code):
        self.answer = answer
        try:
            self.dialog.EndModal(code)
        except Exception:                            # noqa: BLE001
            pass

    def show(self):
        """Modal. Put in front and given the keyboard first."""
        import wx
        self.dialog.CentreOnScreen()
        # Both after ShowModal has put the window up: a window that is not
        # shown cannot be given the foreground.
        wx.CallAfter(_bring_to_front, self.dialog)
        wx.CallAfter(_focus, self._focus_on)
        self.dialog.ShowModal()
        return self.answer

    def close(self):
        """Ended from outside (the run was cancelled)."""
        self._end(DENY, 0)

    def destroy(self):
        try:
            self.dialog.Destroy()
        except Exception:                            # noqa: BLE001
            pass


def _focus(window):
    try:
        window.SetFocus()
    except Exception:                                # noqa: BLE001
        pass


def _bring_to_front(dialog):
    """A Titan in the tray is not the foreground process, and Windows refuses
    the foreground to a process that does not have it; the shell's own helper
    attaches to the foreground thread's input first."""
    try:
        if not dialog or not dialog.IsShown():
            return
        dialog.Raise()
    except Exception:                                # noqa: BLE001
        return
    try:
        from src.shell import win_shell
        win_shell.take_foreground(dialog.GetHandle())
    except Exception:                                # noqa: BLE001
        pass


def _take_keyboard():
    try:
        from src.shell import keyboard_handover
        return keyboard_handover.take_keyboard(_KEYBOARD_NAME)
    except Exception:                                # noqa: BLE001
        return False


def _give_keyboard_back(taken):
    if not taken:
        return
    try:
        from src.shell import keyboard_handover
        keyboard_handover.give_keyboard_back(_KEYBOARD_NAME)
    except Exception:                                # noqa: BLE001
        pass


def _say(text):
    # The AI's own speaker: asynchronous. `tce_speech.speak` can be
    # synchronous, and this runs on the GUI thread just before the dialog.
    try:
        from src.ai.ai_speech import speak
        speak(text)
    except Exception:                                # noqa: BLE001
        pass


def _question_sound():
    try:
        from src.ai import ai_speech
        ai_speech.play_question_sound(agent=True)
    except Exception:                                # noqa: BLE001
        pass


def _ask_on_gui(parent, tool, args, who):
    """Builds, shows and destroys the dialog. GUI thread only."""
    desc = _describe(tool, args)
    if who == 'assistant':
        title = _("Confirm action")
        sentence = _("The assistant wants to run:\n\n{action}\n\n{desc}\n\n"
                     "Allow it?")
    elif who == 'subagent':
        title = _("Confirm subagent action")
        sentence = _("A subagent wants to run:\n\n{action}\n\n{desc}\n\n"
                     "Allow it?")
    else:
        title = _("Confirm agent action")
        sentence = _("The agent wants to run this action:\n\n{action}\n\n"
                     "{desc}\n\nAllow it?")
    message = sentence.format(action=desc, desc=tool.get('description', ''))
    _say(_("Confirm action: {action}").format(action=desc))
    _question_sound()
    taken = _take_keyboard()
    dialog = None
    try:
        dialog = _QuestionDialog(parent, title, message)
        _current['dialog'] = dialog
        return dialog.show()
    finally:
        _current.pop('dialog', None)
        if dialog is not None:
            dialog.destroy()
        _give_keyboard_back(taken)


#: The dialog that is up, so a cancelled run can close it.
_current = {}


def ask(tool, args, parent=None, cancel_event=None, who='agent'):
    """Whether this call may go ahead, asking the user if it must.

    Honours the policy (Autonomous never asks), remembers "allow for this
    session", never waits for a dialog that failed to appear, and gives up
    (as a no) the moment ``cancel_event`` is set. Safe from any thread."""
    try:
        from src.ai import ai_provider
        policy = ai_provider.get_agent_confirm()
    except Exception:                                # noqa: BLE001
        policy = 'tiered'
    if policy == 'none':
        return True
    if is_approved(tool, args):
        return True
    try:
        import wx
        app = wx.GetApp()
    except Exception:                                # noqa: BLE001
        app = None
    if app is None:
        # Nobody to ask is not a yes.
        return False
    try:
        looping = app.IsMainLoopRunning()
    except Exception:                                # noqa: BLE001
        looping = True
    if not looping and not wx.IsMainThread():
        # A CallAfter would never be run, and the wait would never end.
        return False

    if wx.IsMainThread():
        # Asked from the GUI thread itself: a CallAfter would run only after
        # this returned, which is never. Show it here.
        try:
            answer = _ask_on_gui(parent, tool, args, who)
        except Exception as e:                       # noqa: BLE001
            print(f"[confirmation] the question could not be shown: {e}")
            return False
        return _settle(answer, tool, args)

    # Subagents running side by side may all want to ask at once: one
    # dialog at a time, and the next one asks only if the answer to the
    # last did not already cover it ("allow for this session").
    while not _one_question.acquire(timeout=0.25):
        if cancel_event is not None and cancel_event.is_set():
            return False
    try:
        if is_approved(tool, args):
            return True
        return _ask_from_worker(parent, tool, args, cancel_event, who)
    finally:
        _one_question.release()


#: Only one confirmation dialog on the screen at a time.
_one_question = threading.Lock()


def _ask_from_worker(parent, tool, args, cancel_event, who):
    import wx
    box = {}
    done = threading.Event()

    def run():
        try:
            box['answer'] = _ask_on_gui(parent, tool, args, who)
        except Exception as e:                       # noqa: BLE001
            print(f"[confirmation] the question could not be shown: {e}")
            box['answer'] = DENY
        finally:
            done.set()

    wx.CallAfter(run)
    while not done.wait(0.25):
        if cancel_event is not None and cancel_event.is_set():
            dialog = _current.get('dialog')
            if dialog is not None:
                wx.CallAfter(dialog.close)
            # Do not wait for the dialog to finish closing: the run is over.
            return False
    return _settle(box.get('answer', DENY), tool, args)


def _settle(answer, tool, args):
    if answer == SESSION:
        approve(tool, args)
        return True
    return answer == ONCE


def make_confirm(parent=None, cancel_event=None, who='agent'):
    """A ``confirm(tool, args)`` for ``run_agent``. ``parent`` and
    ``cancel_event`` may be callables, read when the question is asked."""
    def confirm(tool, args):
        p = parent() if callable(parent) else parent
        c = cancel_event() if callable(cancel_event) else cancel_event
        return ask(tool, args, parent=p, cancel_event=c, who=who)
    return confirm

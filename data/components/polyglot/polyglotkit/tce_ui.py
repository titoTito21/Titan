# -*- coding: utf-8 -*-
"""How a Titan window behaves, for Polyglot's own windows.

Polyglot's windows are wx windows of a component, and nothing made them
behave like the rest of TCE: no focus sound as the keyboard moved, no sound
when a list ran out, no dialog sound, no word to the screen reader about
what kind of message box was coming, and a modal dialog opened while Titan
UI was on left the Invisible UI holding Enter and Escape. Every one of
those is something a TCE user hears everywhere else and would hear missing
here. This module is that behaviour, written once:

* `cue_focus` / `cue_tree` - ``core/FOCUS.ogg`` when a control takes the
  keyboard, which is what every control of Titan's own settings window
  plays (`SettingsFrame.OnFocus`);
* `cue_list` - a report list played the way Titan's own lists are: the
  focus cue panned to how far down the list the row is, and
  ``ui/endoflist.ogg`` when an arrow runs off either end;
* `modal` - a modal dialog with ``ui/dialog.ogg`` / ``ui/dialogclose.ogg``
  round it and the keyboard taken from the Invisible UI while it is up;
* `message` / `ask` - a native message box (a reader reads it as one) told
  to the reader as a question, a warning, an error or a notice first
  (`messages.announce_dialog_kind`), with the matching sound.

Everything degrades to plain wx when Titan's modules are not there (the
test suite, an older Titan): a component must never stop working because a
sound could not be played.
"""

from contextlib import contextmanager

KEYBOARD_NAME = 'polyglot'


def play(name, pan=None):
    """One of the user's theme sounds; silence when there is no mixer."""
    try:
        from src.titan_core.sound import play_sound
        play_sound(name, pan=pan)
    except Exception:
        pass


def _on_focus(event):
    play('core/FOCUS.ogg')
    event.Skip()


def cue_focus(*controls):
    for control in controls:
        try:
            control.Bind(_wx().EVT_SET_FOCUS, _on_focus)
        except Exception:
            pass


def cue_tree(window, skip=()):
    """The focus cue on every control in ``window`` that takes the keyboard.

    A list played by `cue_list`, or one that plays its own earcons (Titan's
    `CheckList`), is passed in ``skip`` - two sounds for one move is what
    this module exists to prevent elsewhere.
    """
    wx = _wx()
    focusable = (wx.Button, wx.CheckBox, wx.TextCtrl, wx.Choice,
                 wx.ComboBox, wx.ListBox, wx.SpinCtrl, wx.Slider,
                 wx.RadioButton, wx.RadioBox, wx.ListCtrl)
    skipped = {id(control) for control in skip}
    for child in _walk(window):
        if id(child) in skipped or not isinstance(child, focusable):
            continue
        if isinstance(child, wx.ListCtrl) and getattr(child, '_polyglot_cued',
                                                      False):
            continue
        cue_focus(child)


def _walk(parent, depth=0):
    if depth > 8:
        return
    try:
        children = list(parent.GetChildren())
    except Exception:
        return
    for child in children:
        yield child
        for grandchild in _walk(child, depth + 1):
            yield grandchild


def row_pan(index, count):
    """Where a row is heard: the top of a list left, its end right (0..1)."""
    if count <= 1 or index < 0:
        return 0.5
    return min(1.0, max(0.0, float(index) / float(count - 1)))


def cue_list(listing, plays_own_focus=False):
    """Titan's list sounds on a report list.

    ``plays_own_focus`` is for a list that already plays a cue as its row
    changes (`CheckList` plays the checked/unchecked earcon): only the end
    of the list is added to it.
    """
    wx = _wx()
    listing._polyglot_cued = True
    state = {'last': -1}

    def focused(event):
        event.Skip()
        index = event.GetIndex()
        if index < 0 or index == state['last']:
            return
        state['last'] = index
        if not plays_own_focus:
            play('core/FOCUS.ogg', pan=row_pan(index, listing.GetItemCount()))

    def gained(event):
        event.Skip()
        # Arriving on the list is a focus change of its own; the row cue
        # follows when the row is (re)focused.
        if not plays_own_focus:
            play('core/FOCUS.ogg')

    def key(event):
        code = event.GetKeyCode()
        count = listing.GetItemCount()
        current = listing.GetFocusedItem()
        if count and not event.HasAnyModifiers():
            if code in (wx.WXK_UP, wx.WXK_HOME, wx.WXK_PAGEUP) and current <= 0:
                play('ui/endoflist.ogg')
            elif code in (wx.WXK_DOWN, wx.WXK_END, wx.WXK_PAGEDOWN) and \
                    current >= count - 1:
                play('ui/endoflist.ogg')
        event.Skip()

    listing.Bind(wx.EVT_LIST_ITEM_FOCUSED, focused)
    listing.Bind(wx.EVT_SET_FOCUS, gained)
    listing.Bind(wx.EVT_KEY_DOWN, key)


@contextmanager
def keyboard_taken():
    """The Invisible UI stands down while a Polyglot window is in front."""
    try:
        from src.shell.keyboard_handover import (take_keyboard,
                                                 give_keyboard_back)
    except Exception:
        take_keyboard = give_keyboard_back = None
    taken = bool(take_keyboard and take_keyboard(KEYBOARD_NAME))
    try:
        yield
    finally:
        if taken:
            give_keyboard_back(KEYBOARD_NAME)


def modal(dialog, sound=True):
    """Show ``dialog`` modally, the way Titan shows one. Answers its code."""
    if sound:
        play('ui/dialog.ogg')
    try:
        with keyboard_taken():
            return dialog.ShowModal()
    finally:
        if sound:
            play('ui/dialogclose.ogg')


_SOUND_OF_KIND = {'question': 'ui/dialog.ogg', 'warning': 'ui/dialog.ogg',
                  'error': 'core/error.ogg', 'information': 'ui/msg.ogg'}


def _tell_reader(kind):
    try:
        from src.accessibility.messages import announce_dialog_kind
        announce_dialog_kind(kind)
    except Exception:
        pass


def message(parent, text, title, kind='information'):
    """A notice, a warning or an error, as a native message box."""
    wx = _wx()
    icon = {'warning': wx.ICON_WARNING, 'error': wx.ICON_ERROR}.get(
        kind, wx.ICON_INFORMATION)
    play(_SOUND_OF_KIND.get(kind, 'ui/msg.ogg'))
    _tell_reader(kind)
    dialog = wx.MessageDialog(parent, str(text), str(title), wx.OK | icon)
    try:
        with keyboard_taken():
            dialog.ShowModal()
    finally:
        dialog.Destroy()
        play('ui/msgclose.ogg')


def ask(parent, text, title):
    """A yes-or-no question. True only for Yes."""
    wx = _wx()
    play('ui/dialog.ogg')
    _tell_reader('question')
    dialog = wx.MessageDialog(parent, str(text), str(title),
                              wx.YES_NO | wx.ICON_QUESTION)
    try:
        with keyboard_taken():
            answer = dialog.ShowModal()
    finally:
        dialog.Destroy()
        play('ui/dialogclose.ogg')
    return answer == wx.ID_YES


def _wx():
    import wx
    return wx

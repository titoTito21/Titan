# -*- coding: utf-8 -*-
"""Titan-Net Mail: the window sounds like the Feedback Hub and Escape leaves it.

Two things the user asked for, and one cause they could not have seen:

1. Mail is a Titan-Net window, so it uses the Feedback Hub's popup pair
   (`ui/popup.ogg` / `ui/popupclose.ogg`) rather than the Titan IM window
   pair the shared `TabbedListFrame` plays for the messenger clients - and
   exactly ONE earcon per close, where Escape used to play the popup close
   and the base class then played the window close on top of it.

2. Escape leaves the mailbox, a message, the page view and the composer.
   It always looked as though it should, which is the interesting part: the
   handlers demanded `MOD_NONE`, and `wxKeyEvent` reads Shift out of the
   calling thread's input queue - the queue the Titan shell merges with
   another program's every time it takes the foreground.  A Shift latched
   there turns every Escape into Shift+Escape and the window silently stops
   closing.  The modifiers are now asked of the hardware.

Run directly: python tests/test_mail_window.py
"""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import wx                                                      # noqa: E402

_app = wx.App(False)                                           # noqa: E402

from src.network import mail_gui                               # noqa: E402
from src.network import im_ui_common                           # noqa: E402
from src.system import key_state                               # noqa: E402


class _Event:
    """Just enough of a wx.KeyEvent for the two things the handlers ask."""

    def __init__(self, keycode=wx.WXK_ESCAPE, mask=wx.MOD_NONE):
        self._keycode = keycode
        self._mask = mask

    def GetKeyCode(self):
        return self._keycode

    def GetModifiers(self):
        return self._mask

    def ShiftDown(self):
        return bool(self._mask & wx.MOD_SHIFT)


class MailSoundTests(unittest.TestCase):

    def test_mail_uses_the_popup_pair(self):
        self.assertEqual(mail_gui.MAIL_OPEN_SOUND, 'ui/popup.ogg')
        self.assertEqual(mail_gui.MAIL_CLOSE_SOUND, 'ui/popupclose.ogg')

    def test_no_mail_window_plays_the_titan_im_window_sounds(self):
        with open(os.path.join(REPO, 'src/network/mail_gui.py'),
                  encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('window_open()', source)
        self.assertNotIn('window_close()', source)

    def test_one_earcon_per_close(self):
        """The list frames blank the base class's Escape sound.

        Otherwise leaving with Escape plays the popup close and then the
        closing sound on top of it - two clips for one close.
        """
        for frame in (mail_gui.MailFrame, mail_gui.MailMessageFrame):
            self.assertEqual(frame.ESCAPE_SOUND, '', frame.__name__)
            self.assertEqual(frame.CLOSE_SOUND, mail_gui.MAIL_CLOSE_SOUND,
                             frame.__name__)

    def test_the_messenger_clients_keep_their_own_sounds(self):
        """Only mail changes: the shared base class still defaults to IM's."""
        self.assertEqual(im_ui_common.TabbedListFrame.CLOSE_SOUND, '')
        self.assertEqual(im_ui_common.TabbedListFrame.ESCAPE_SOUND,
                         'ui/popupclose.ogg')


class MailEscapeTests(unittest.TestCase):

    def setUp(self):
        self._real = key_state.physically_down
        self.addCleanup(setattr, key_state, 'physically_down', self._real)

    def _no_key_is_really_held(self):
        key_state.physically_down = lambda vk: False

    def test_escape_closes_when_nothing_is_held(self):
        self._no_key_is_really_held()
        self.assertTrue(mail_gui._escape_pressed(_Event()))

    def test_a_latched_shift_does_not_stop_escape(self):
        self._no_key_is_really_held()
        self.assertTrue(mail_gui._escape_pressed(_Event(mask=wx.MOD_SHIFT)))
        self.assertEqual(im_ui_common._real_modifiers(_Event(mask=wx.MOD_SHIFT)),
                         wx.MOD_NONE)

    def test_a_real_control_or_alt_still_means_something_else(self):
        key_state.physically_down = lambda vk: True
        self.assertFalse(mail_gui._escape_pressed(_Event(mask=wx.MOD_CONTROL)))
        self.assertFalse(mail_gui._escape_pressed(_Event(mask=wx.MOD_ALT)))

    def test_only_escape(self):
        self._no_key_is_really_held()
        self.assertFalse(mail_gui._escape_pressed(_Event(keycode=ord('A'))))

    def test_every_mail_window_answers_escape(self):
        """All four: the mailbox, a message, the page view and the composer."""
        with open(os.path.join(REPO, 'src/network/mail_gui.py'),
                  encoding='utf-8') as handle:
            source = handle.read()
        # The two plain frames route Escape through the shared test; the two
        # list frames inherit it from TabbedListFrame's own key hook.
        self.assertEqual(source.count('if _escape_pressed(event):'), 2)
        self.assertIn('def on_escape', source)
        with open(os.path.join(REPO, 'src/network/im_ui_common.py'),
                  encoding='utf-8') as handle:
            base = handle.read()
        self.assertIn('_real_modifiers(event) == wx.MOD_NONE', base)


if __name__ == '__main__':
    unittest.main(verbosity=2)

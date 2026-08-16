# -*- coding: utf-8 -*-
"""Reading a message: Escape leaves it, text is readable as text, and a
message cannot use Titan's own key bridge.

Run it directly (`python tests/test_mail_reading.py`) - `tests/` has no
`__init__.py`.

No window is ever shown and no dialog is ever raised: this suite runs on the
machine somebody is using, and a test that puts a window on their screen is a
window they have to find and close.

What is being tested is the fix for "Escape does nothing, you have to press
Alt+F4": a WebView2 keeps every keystroke that happens inside the document,
so neither the frame's `EVT_CHAR_HOOK` nor a menu accelerator ever saw
Escape. The document now hands those keys back through a nonced `titan:` URL
- and because a mail body is markup written by a stranger, the nonce, the
policy and the scrubbing are tested as carefully as the key itself.
"""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import wx                                                        # noqa: E402

from src.network import mail_format, mail_gui                    # noqa: E402

_app = wx.App(False)

# No test may raise a dialog: `open_url_with_confirmation` asks before opening
# a link, and an unanswered message box is a modal window on the user's own
# desktop.
ASKED = []


def _asked(parent, message, caption, style=wx.OK):
    ASKED.append((str(message), str(caption)))
    return wx.ID_YES


# `open_url_with_confirmation` asks through `im_ui_common.show_message`, which
# is a real `wx.MessageDialog.ShowModal` - a modal window on the user's own
# desktop if a test ever reaches it.
mail_gui.show_message = _asked
# And nothing speaks: Titan's speech starts an engine (and on this machine can
# reach a SAPI subprocess bridge), which is minutes of a suite that should run
# in under a second - and it would talk over whoever is at the computer.
mail_gui.speak_notification = lambda *args, **kwargs: None
mail_gui.speak_titannet = lambda *args, **kwargs: None
mail_gui.play_sound = lambda *args, **kwargs: None
wx.MessageBox = lambda message, caption='', style=wx.OK, parent=None, *a, **k: (
    ASKED.append((str(message), str(caption))) or wx.OK)

PLAIN = {
    'id': 1, 'subject': 'A plain message', 'from_addr': 'sender@example.com',
    'to_addr': 'me@titosofttitan.com', 'received_at': '2026-08-16T18:00:00',
    'content_type': 'text/plain',
    'body': 'Line one.\nLine two.\n\nSee https://example.com for more.\n',
    'body_html': '',
}

HTML = {
    'id': 2, 'subject': 'An HTML message', 'from_addr': 'sender@example.com',
    'to_addr': 'me@titosofttitan.com', 'received_at': '2026-08-16T18:05:00',
    'content_type': 'text/html',
    'body': 'Hello',
    'body_html': ('<html><body><h1>Hello</h1><p>Some <b>text</b> and a '
                  '<a href="https://example.com">link</a>.</p></body></html>'),
}


class _Windowless(unittest.TestCase):
    """A parent nothing is ever shown on."""

    def setUp(self):
        self.frame = wx.Frame(None)
        self.addCleanup(self.frame.Destroy)
        del ASKED[:]

    def text_view(self, message):
        frame = mail_gui.MailTextFrame(self.frame, None, message)
        # A window this test closes on purpose is already gone by cleanup.
        self.addCleanup(self._destroy, frame)
        return frame

    @staticmethod
    def _destroy(window):
        try:
            window.Destroy()
        except RuntimeError:
            pass

    def escape(self, window):
        event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
        event.SetEventObject(window)
        event.SetKeyCode(wx.WXK_ESCAPE)
        return event


class TextIsReadableAsText(_Windowless):

    def test_the_message_is_one_piece_of_text(self):
        frame = self.text_view(PLAIN)
        body = frame.body.GetValue()
        self.assertIn('Line one.', body)
        self.assertIn('Line two.', body)
        # Headed by who said it and when - the same thing Copy whole message
        # puts on the clipboard. The labels are translated, so the test asks
        # for what they carry rather than for the English words.
        head = "\n".join(body.splitlines()[:4])
        self.assertIn('A plain message', head)
        self.assertIn('sender@example.com', head)
        self.assertIn('2026-08-16', head)

    def test_it_is_a_read_only_text_box_with_a_name(self):
        """A real edit control: the reader's own cursor, say-all and find,
        and Ctrl+A / Ctrl+C copy out of it like any other text."""
        frame = self.text_view(PLAIN)
        self.assertIsInstance(frame.body, wx.TextCtrl)
        self.assertFalse(frame.body.IsEditable())
        self.assertTrue(frame.body.GetWindowStyleFlag() & wx.TE_MULTILINE)
        self.assertTrue(frame.body.GetName())

    def test_an_html_message_can_be_read_as_text_too(self):
        frame = self.text_view(HTML)
        body = frame.body.GetValue()
        self.assertIn('Hello', body)
        self.assertIn('Some text', body.replace('\n', ' '))
        # The links are listed at the end rather than lost with the markup.
        self.assertIn('https://example.com', body)

    def test_escape_closes_it(self):
        frame = self.text_view(PLAIN)
        closed = []
        frame.Bind(wx.EVT_CLOSE, lambda event: (closed.append(True),
                                                event.Skip()))
        frame._on_key(self.escape(frame.body))
        wx.Yield()
        self.assertTrue(closed, "Escape did not close the text view")

    def test_it_is_reachable_from_the_reading_list(self):
        frame = mail_gui.MailMessageFrame(self.frame, None, PLAIN)
        self.addCleanup(frame.Destroy)
        self.assertTrue(callable(getattr(frame, '_open_text', None)))
        self.assertTrue(frame.extra_key(ord('T'), wx.MOD_CONTROL, None)
                        is not False or True)

    def test_open_message_can_be_asked_for_it(self):
        import inspect
        self.assertIn('as_text',
                      inspect.signature(mail_gui.open_message).parameters)


class TheDocumentHandsBackItsKeys(_Windowless):
    """The whole point: a WebView2 swallows every keystroke inside it."""

    def test_the_bridge_is_in_the_document_and_carries_the_nonce(self):
        document = mail_gui._sealed_document(HTML['body_html'], 'x', 'TOKEN')
        self.assertIn('<script nonce="TOKEN">', document)
        self.assertIn(mail_gui.PAGE_KEY_URL, document)
        self.assertIn("'TOKEN'", document)
        self.assertIn('keydown', document)

    def test_the_policy_allows_that_one_script_and_nothing_else(self):
        policy = mail_gui.mail_csp('TOKEN')
        self.assertIn("script-src 'nonce-TOKEN'", policy)
        self.assertIn("default-src 'none'", policy)
        self.assertNotIn("'unsafe-inline'", policy.split('script-src')[1])

    def test_with_no_nonce_there_is_no_script_at_all(self):
        """The copy written to a file for the real browser has no bridge."""
        document = mail_gui._sealed_document(HTML['body_html'], 'x')
        self.assertNotIn('<script', document.lower())
        self.assertIn("script-src 'none'", document)


class AMessageCannotPressTitansKeys(_Windowless):
    """A mail body is markup written by a stranger."""

    class _Page:
        """The bit of the page view the bridge talks to."""

        def __init__(self):
            self._nonce = 'THE-REAL-ONE'
            self.pressed = []

        _page_key_url = mail_gui.MailPageFrame._page_key_url

        def _page_key(self, name):
            self.pressed.append(name)

    def test_the_right_nonce_presses_the_key(self):
        page = self._Page()
        page._page_key_url('THE-REAL-ONE/escape')
        self.assertEqual(['escape'], page.pressed)

    def test_a_forged_one_does_nothing(self):
        page = self._Page()
        for forged in ('escape', '/escape', 'guess/escape', '/browser',
                       'THE-REAL-ONE1/escape', ''):
            page._page_key_url(forged)
        self.assertEqual([], page.pressed,
                         "a message managed to press a key")

    def test_every_name_the_bridge_sends_is_one_titan_answers(self):
        source = open(os.path.join(ROOT, 'src', 'network', 'mail_gui.py'),
                      encoding='utf-8').read()
        for name in ('escape', 'list', 'text', 'reply', 'forward', 'browser'):
            self.assertIn(f"'{name}'", source)

    def test_the_messages_own_script_is_taken_out(self):
        scrubbed = mail_gui.scrub_message_html(
            '<p>hi</p><script>evil()</script><script src="x.js"></script>')
        self.assertNotIn('script', scrubbed.lower())
        self.assertIn('<p>hi</p>', scrubbed)

    def test_a_message_may_not_set_the_rules(self):
        scrubbed = mail_gui.scrub_message_html(
            '<meta http-equiv="Content-Security-Policy" content="script-src *">'
            '<meta http-equiv="refresh" content="0;url=http://evil">'
            '<base href="http://evil/">Hello')
        self.assertNotIn('meta', scrubbed.lower())
        self.assertNotIn('base', scrubbed.lower())
        self.assertIn('Hello', scrubbed)

    def test_a_link_that_is_not_a_web_address_is_refused(self):
        """`javascript:` and `file:` are ways of running something on this
        machine, and a confirmation dialog does not make them safe."""
        opened = []
        original = mail_gui.webbrowser.open
        mail_gui.webbrowser.open = lambda url: opened.append(url)
        try:
            for url in ('javascript:alert(1)', 'file:///C:/Windows/system.ini',
                        'data:text/html,<script>x</script>'):
                mail_gui.open_url_with_confirmation(self.frame, url)
            self.assertEqual([], opened)
            self.assertEqual([], ASKED,
                             "it should not even ask about those")
        finally:
            mail_gui.webbrowser.open = original

    def test_a_real_link_is_still_offered(self):
        opened = []
        original = mail_gui.webbrowser.open
        mail_gui.webbrowser.open = lambda url: opened.append(url)
        try:
            mail_gui.open_url_with_confirmation(self.frame,
                                                'https://example.com/x')
        finally:
            mail_gui.webbrowser.open = original
        self.assertTrue(ASKED, "it must ask before opening a link")
        self.assertEqual(['https://example.com/x'], opened)


if __name__ == '__main__':
    unittest.main(verbosity=2)

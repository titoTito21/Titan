# -*- coding: utf-8 -*-
"""The reader's worker thread survives what is posted to it.

Reported as "in the compiled build, minimising TCE hangs the screen
reader". Minimising puts the focus on a WINDOW - the desktop, the next
program - and a window is a container, whose announcement is deferred and
then posted to the worker thread as a thread message. The loop recognised
one by reading ``msg.hwnd``, a field ``ctypes.wintypes.MSG`` has never had
(it is ``hWnd``); the AttributeError left the loop, the ``finally`` tore
every subsystem down, and the reader was dead with ``running`` still
True. Nothing posted to the worker in ordinary use before the container
announcement started going through it, which is why the previous Titan
Access had no such problem.

And the shared dialogs call ``gui.mainFrame.prePopup()`` ON THE FRAME,
which NVDA's MainFrame has and a plain wx.Frame has not - so every
question the shared modules asked here raised inside a `wx.CallAfter`,
where nothing catches it, and no dialog ever appeared.

Run directly: ``python tests/test_titan_access_worker.py``.
"""

import ctypes
import io
import os
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)

IS_WINDOWS = sys.platform.startswith('win')
_WX_APP = []                       # kept, or wx collects it under the frame


def _wx_app():
    import wx
    app = wx.GetApp()
    if app is None:
        app = wx.App(False)
        _WX_APP.append(app)
    return app


def _engine_source():
    return io.open(os.path.join(COMPONENT, 'titan_access', 'engine.py'),
                   encoding='utf-8').read()


class TheWorkersMessageLoop(unittest.TestCase):

    def test_the_loop_reads_the_field_windows_spells(self):
        """``MSG.hWnd``: the field is spelled as ctypes spells it, and the
        loop never asks for one it has not got."""
        source = _engine_source()
        # The code, not the docstring that tells the story of the field.
        code = '\n'.join(line for line in source.splitlines()
                         if 'WM_TA_INVOKE and not' in line)
        self.assertTrue('not msg.hWnd' in code, code)
        self.assertFalse('not msg.hwnd' in code, code)
        if IS_WINDOWS:
            from ctypes import wintypes
            names = [name for name, _t in wintypes.MSG._fields_]
            self.assertIn('hWnd', names)
            self.assertNotIn('hwnd', names)

    def test_one_message_never_takes_the_loop_down(self):
        """The dispatch of one message is its own `try`: a message that
        raises costs that message, and the loop goes on to the next."""
        source = _engine_source()
        at = source.index('def _dispatch_message(')
        block = source[at:source.index('\n    def ', at + 10)]
        self.assertIn('except Exception', block)
        loop = source[source.index('while self.running:'):]
        loop = loop[:loop.index('except Exception')]
        self.assertIn('self._dispatch_message(msg, user32)', loop)
        self.assertNotIn('TranslateMessage', loop)

    @unittest.skipUnless(IS_WINDOWS, 'a Win32 MSG')
    def test_a_posted_callable_runs_from_a_real_message(self):
        from ctypes import wintypes
        from titan_access import engine as engine_module
        engine = engine_module.TitanAccessEngine.__new__(
            engine_module.TitanAccessEngine)
        engine._invoke_lock = threading.Lock()
        engine._invoke_queue = []
        ran = []
        engine._invoke_queue.append(lambda: ran.append('yes'))
        msg = wintypes.MSG()
        msg.message = engine_module.WM_TA_INVOKE
        msg.hWnd = None

        class _User32:
            dispatched = []

            def TranslateMessage(self, *_a):
                self.dispatched.append('translate')

            def DispatchMessageW(self, *_a):
                self.dispatched.append('dispatch')
        user32 = _User32()
        engine._dispatch_message(msg, user32)
        self.assertEqual(ran, ['yes'])
        self.assertEqual(user32.dispatched, [])   # a thread message is ours
        other = wintypes.MSG()
        other.message = 0x0100                     # WM_KEYDOWN, somebody's
        engine._dispatch_message(other, user32)
        self.assertEqual(user32.dispatched, ['translate', 'dispatch'])

    @unittest.skipUnless(IS_WINDOWS, 'a Win32 MSG')
    def test_a_callable_that_raises_costs_only_itself(self):
        from ctypes import wintypes
        from titan_access import engine as engine_module
        engine = engine_module.TitanAccessEngine.__new__(
            engine_module.TitanAccessEngine)
        engine._invoke_lock = threading.Lock()
        engine._invoke_queue = []
        ran = []

        def bad():
            raise RuntimeError('no')
        engine._invoke_queue.append(bad)
        engine._invoke_queue.append(lambda: ran.append('after'))
        msg = wintypes.MSG()
        msg.message = engine_module.WM_TA_INVOKE

        class _Raising:
            def TranslateMessage(self, *_a):
                raise RuntimeError('translate')

            def DispatchMessageW(self, *_a):
                raise RuntimeError('dispatch')
        engine._dispatch_message(msg, _Raising())  # must not raise
        self.assertEqual(ran, ['after'])
        other = wintypes.MSG()
        other.message = 0x0100
        engine._dispatch_message(other, _Raising())  # must not raise

    def test_a_loop_that_ends_by_itself_stops_claiming_to_run(self):
        source = _engine_source()
        at = source.index('def _run(self):')
        block = source[at:source.index('\n    def _dispatch_message', at)]
        self.assertIn('if self.running and not asked_to_stop:', block)
        self.assertIn('self.running = False', block)


class TheSharedDialogsCanOpenHere(unittest.TestCase):
    """``gui.mainFrame.prePopup()`` is called on the FRAME."""

    def test_the_frame_compat_hands_out_takes_the_popup_calls(self):
        try:
            import wx
        except Exception:                            # noqa: BLE001
            self.skipTest('no wx')
        app = _wx_app()
        frame = wx.Frame(None, title='compat probe')
        try:
            app.SetTopWindow(frame)
            from titan_access.portable import compat
            found = compat.gui.mainFrame
            self.assertIs(found, frame)
            self.assertIsNone(found.prePopup())
            self.assertIsNone(found.postPopup())
            # And `dialogs` finds a GUI to put a question on.
            from titan_access.portable import dialogs
            self.assertIsNotNone(dialogs._gui())
        finally:
            frame.Destroy()


class TheSwitchIsInGeneral(unittest.TestCase):
    """"Turn the reader on" is the first control of General - on the
    settings page and in the walked settings alike - and the parent
    category keeps only the note saying where things are."""

    def test_the_page_builds_the_switch_inside_general(self):
        try:
            import wx
        except Exception:                            # noqa: BLE001
            self.skipTest('no wx')
        _wx_app()
        from titan_access import settings_panel
        frame = wx.Frame(None)
        try:
            main = settings_panel.build_panel(frame, 'main')
            self.assertFalse(hasattr(main, 'chk_enabled'))
            general = settings_panel.build_panel(frame, 'general')
            self.assertTrue(hasattr(general, 'chk_enabled'))
            box = general.chk_enabled.GetContainingSizer()
            self.assertIsInstance(box, wx.StaticBoxSizer)
            first = box.GetChildren()[0].GetWindow()
            self.assertIs(first, general.chk_enabled)
        finally:
            frame.Destroy()

    def test_the_walked_general_section_starts_with_the_switch(self):
        from titan_access import settings_walk
        for sid, _title, entries in settings_walk.SCHEMA:
            if sid == 'general':
                self.assertEqual(entries[0][:2], ('General', 'Enabled'))
                break
        else:
            self.fail('no General section')

    def test_the_switch_says_whether_the_reader_runs(self):
        from titan_access import settings_walk, engine as engine_module
        entry = ('General', 'Enabled', 'settings.general.enable', 'bool',
                 None, False)
        old = engine_module.TitanAccessEngine.instance
        try:
            engine_module.TitanAccessEngine.instance = None
            self.assertFalse(settings_walk.value_of(entry))
        finally:
            engine_module.TitanAccessEngine.instance = old

    def test_changing_it_switches_the_reader_not_the_voice(self):
        from titan_access import settings_walk
        switched = []
        old = settings_walk._switch_reader
        settings_walk._switch_reader = lambda on: switched.append(on)
        import tempfile
        from titan_access import settings_store
        store = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), 'screenReader.ini'))
        old_store = settings_walk._store
        settings_walk._store = lambda: store
        try:
            entry = ('General', 'Enabled', 'settings.general.enable', 'bool',
                     None, False)
            settings_walk.set_value(entry, True, engine=None)
            self.assertEqual(switched, [True])
            self.assertTrue(store.get_bool('General', 'Enabled', False))
        finally:
            settings_walk._switch_reader = old
            settings_walk._store = old_store


if __name__ == '__main__':
    unittest.main(verbosity=1)

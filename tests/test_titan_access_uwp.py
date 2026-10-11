# -*- coding: utf-8 -*-
"""Titan Access and UWP / XAML applications.

Measured on Unigram (UWP, Telegram.exe): the window in front belonged to
ApplicationFrameHost rather than the app; icons were characters ("\\uea07
pon."); a button that is an icon said only "Button"; scan mode ended where
the screen did, because a XAML list holds only its visible rows; and a
message arriving in the open chat was said by nothing.

The rules are tested on stand-ins; the live tests use windows of their own
(WPF, off the screen, never activated - a probe must not take the keyboard
from whoever runs it) and skip off Windows. Nothing touches the user's
stores. Run directly with the Windows Python.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='ta_uwp_')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TA = os.path.join(ROOT, 'data', 'components', 'titan access')
sys.path.insert(0, TA)
sys.path.insert(0, os.path.join(TA, 'lib'))

from titan_access import uwp, live_lists, virtual_lists   # noqa: E402

IS_WINDOWS = sys.platform.startswith('win')


class _Child(object):
    def __init__(self, name, children=()):
        self.Name = name
        self._children = list(children)

    def GetChildren(self):
        return self._children


class _Obj(object):
    def __init__(self, **kw):
        self.name = ''
        self.help_text = ''
        self.description = ''
        self.value = ''
        self.role = 'button'
        self.framework_id = 'XAML'
        self.automation_id = ''
        self.process_id = 0
        self.hwnd = 0
        self.__dict__.update(kw)


class IconsAreWords(unittest.TestCase):

    def test_a_known_icon_is_its_meaning_in_the_users_language(self):
        self.assertIn(uwp.clean(''), ('Anuluj', 'Cancel'))
        self.assertEqual(len(uwp.clean('').split(', ')), 2)

    def test_an_icon_beside_words_is_left_out(self):
        self.assertEqual(uwp.clean('\xa0pon.'), 'pon.')
        self.assertEqual(uwp.clean('\U000f0001'), '')
        self.assertEqual(uwp.clean('Zapisz'), 'Zapisz')

    def test_every_icon_has_words_in_both_languages(self):
        import json
        for lang in ('en', 'pl'):
            with open(os.path.join(TA, 'locale', lang + '.json'), encoding='utf-8') as f:
                words = json.load(f)
            for key in set(uwp.GLYPHS.values()):
                self.assertIn('glyph.' + key, words, (lang, key))


class AnIconOnlyControlIsNamed(unittest.TestCase):

    def test_from_its_icon_child(self):
        obj = _Obj(automation_id='Hide')
        uwp.finish(obj, _Child('', [_Child('')]))
        self.assertIn(obj.name, ('Anuluj', 'Cancel'))

    def test_the_tooltip_comes_first(self):
        obj = _Obj(help_text='Ukryj kartę')
        uwp.finish(obj, _Child('', [_Child('')]))
        self.assertEqual(obj.name, 'Ukryj kartę')

    def test_a_hyperlink_is_named_by_its_content(self):
        obj = _Obj(role='link')
        uwp.finish(obj, _Child('', [_Child('T'), _Child('TCE group')]))
        self.assertEqual(obj.name, 'T, TCE group')

    def test_last_the_automation_id_in_words_for_xaml_only(self):
        obj = _Obj(automation_id='SetBirthdateCard')
        uwp.finish(obj, _Child('', []))
        self.assertEqual(obj.name, 'Set birthdate card')
        win32 = _Obj(automation_id='1001', framework_id='Win32')
        uwp.finish(win32, _Child('', []))
        self.assertEqual(win32.name, '')

    def test_a_named_control_and_a_text_field_are_untouched(self):
        named = _Obj(name='Nowa rozmowa')
        uwp.finish(named, _Child('', [_Child('')]))
        self.assertEqual(named.name, 'Nowa rozmowa')
        field = _Obj(role='edit', value=' typed')
        uwp.finish(field, None)
        self.assertEqual(field.value, ' typed')

    def test_an_icon_text_inside_a_control_is_not_a_line_of_its_own(self):
        self.assertIsNone(uwp.node_name('', 'text'))
        self.assertEqual(uwp.node_name('\xa0pon.', 'text'), 'pon.')


class TheProgramIsTheAppNotItsFrame(unittest.TestCase):

    def test_an_object_of_applicationframehost_is_given_the_apps_process(self):
        saved = (uwp.executable, uwp.app_pid, uwp.IS_WINDOWS)
        uwp.executable = lambda pid: {10: 'applicationframehost', 20: 'telegram'}.get(pid, '')
        uwp.app_pid = lambda hwnd: 20
        uwp.IS_WINDOWS = True
        try:
            obj = _Obj(name='Unigram', role='window', process_id=10, hwnd=5)
            uwp.finish(obj)
            self.assertEqual(obj.process_id, 20)
            other = _Obj(name='x', process_id=30, hwnd=5)
            uwp.finish(other)
            self.assertEqual(other.process_id, 30)
        finally:
            uwp.executable, uwp.app_pid, uwp.IS_WINDOWS = saved

    @unittest.skipUnless(IS_WINDOWS, 'Windows only')
    def test_a_real_uwp_frame_names_its_app(self):
        import ctypes
        frames = []
        from ctypes import wintypes
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def top(h, _l):
            if uwp._class(h) == uwp.FRAME_CLASS and uwp._title(h):
                frames.append(h)
            return True
        ctypes.windll.user32.EnumWindows(proto(top), 0)
        resolved = [uwp.executable(uwp.app_pid(f)) for f in frames]
        resolved = [r for r in resolved if r and r != uwp.FRAME_HOST]
        if not resolved:
            self.skipTest('no running UWP app with its window here')
        self.assertNotIn(uwp.FRAME_HOST, resolved)

    @unittest.skipUnless(IS_WINDOWS, 'Windows only')
    def test_a_suspended_app_cannot_hold_the_reader_20_seconds(self):
        from titan_access.uia_focus import get_provider
        import comtypes.client
        provider = get_provider()
        self.assertTrue(uwp.limit_all_timeouts(provider._uia))
        mod = comtypes.client.GetModule('UIAutomationCore.dll')
        second = provider._uia.QueryInterface(mod.IUIAutomation2)
        self.assertEqual(second.TransactionTimeout, uwp.TRANSACTION_TIMEOUT_MS)
        from uiautomation.uiautomation import _AutomationClient
        lib = _AutomationClient.instance().IUIAutomation.QueryInterface(mod.IUIAutomation2)
        self.assertEqual(lib.ConnectionTimeout, uwp.CONNECTION_TIMEOUT_MS)


class ANewRowIsReadOnlyWhenItIsNews(unittest.TestCase):

    def setUp(self):
        self.now = [100.0]
        self.input = [1e9]
        self.d = live_lists.Decider(input_age=lambda: self.input[0],
                                    clock=lambda: self.now[0])
        self.now[0] += 5

    def say(self, key, last=True, framework='XAML', text='Ala: hej'):
        return self.d.decide(key, live_lists.LIST_ITEM, framework, last, text)

    def test_a_new_last_row_is_said(self):
        self.assertEqual(self.say(1), 'Ala: hej')

    def test_not_while_the_window_is_opening(self):
        self.d.reset()
        self.assertEqual(self.say(1), '')
        self.now[0] += 2
        self.assertEqual(self.say(1), '')       # seen while settling

    def test_not_a_row_scrolled_to_or_typed_by_the_user(self):
        self.input[0] = 0.3
        self.assertEqual(self.say(1), '')
        self.input[0] = 1e9
        self.assertEqual(self.say(1), '')       # and never later either

    def test_not_a_row_that_is_not_at_the_end(self):
        self.assertEqual(self.say(1, last=False), '')

    def test_not_a_win32_list(self):
        self.assertEqual(self.say(1, framework='Win32'), '')

    def test_icons_are_words_and_a_repeat_is_said_once(self):
        self.assertEqual(self.say(1, text=' Gotowe'), 'Gotowe')
        self.assertEqual(self.say(2, text=' Gotowe'), '')


def _probe(script, title):
    """An off-screen, never-activated WPF window of the test's own."""
    path = os.path.join(tempfile.mkdtemp(), 'probe.ps1')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(script.replace('TITLE', title))
    p = subprocess.Popen(['powershell', '-NoProfile', '-STA', '-File', path],
                         creationflags=0x08000000)
    import ctypes
    for _ in range(80):
        h = ctypes.windll.user32.FindWindowW(None, title)
        if h:
            time.sleep(1.0)
            return p, h
        time.sleep(0.25)
    p.kill()
    return None, 0


_HEADER = """Add-Type -AssemblyName PresentationFramework
$w = New-Object System.Windows.Window
$w.Title = 'TITLE'; $w.Width = 300; $w.Height = 300
$w.Left = -3000; $w.Top = 50; $w.ShowActivated = $false; $w.ShowInTaskbar = $false
$lb = New-Object System.Windows.Controls.ListBox
$w.Content = $lb
"""


@unittest.skipUnless(IS_WINDOWS, 'Windows only')
class LiveWindows(unittest.TestCase):

    def test_a_virtualised_list_is_walked_past_the_screen(self):
        script = _HEADER + """
for ($i = 1; $i -le 500; $i++) { [void]$lb.Items.Add("Wiadomosc $i") }
$t = New-Object System.Windows.Threading.DispatcherTimer
$t.Interval = [TimeSpan]::FromSeconds(40); $t.Add_Tick({ $w.Close() }); $t.Start()
[void]$w.ShowDialog()
"""
        import ctypes
        before = ctypes.windll.user32.GetForegroundWindow()
        p, h = _probe(script, 'TA uwp test list %d' % os.getpid())
        if not h:
            self.skipTest('the WPF probe window did not open')
        try:
            import uiautomation as auto
            from titan_access import virtual_buffer
            nodes = virtual_buffer.build_uia(auto.ControlFromHandle(h))
            rows = [i for i, n in enumerate(nodes) if n.role == 'listitem']
            self.assertLess(len(rows), 100)
            last = rows[-1]
            shown = len(rows)
            self.assertEqual(virtual_lists.extend(nodes, last, +1), virtual_lists.BATCH)
            self.assertEqual(nodes[last + 1].name, 'Wiadomosc %d' % (shown + 1))
            # Up from a document that starts further down.
            tail = nodes[last + 5:last + 7]
            added = virtual_lists.extend(tail, 0, -1)
            self.assertGreater(added, 0)
            self.assertEqual(tail[added].name, 'Wiadomosc %d' % (shown + 5))
            self.assertEqual(ctypes.windll.user32.GetForegroundWindow(), before)
        finally:
            p.kill()

    def test_a_row_added_at_the_end_is_read_and_one_inserted_above_is_not(self):
        script = _HEADER + """
for ($i = 1; $i -le 3; $i++) { [void]$lb.Items.Add("Stara $i") }
$script:n = 0
$t = New-Object System.Windows.Threading.DispatcherTimer
$t.Interval = [TimeSpan]::FromSeconds(1.5)
$t.Add_Tick({
  $script:n++
  if ($script:n -le 1) { }
  elseif ($script:n -eq 3) { $lb.Items.Insert(0, "Wstawiona") }
  elseif ($script:n -le 5) { [void]$lb.Items.Add("Nowa $($script:n)") }
  else { $w.Close() }
})
$t.Start()
[void]$w.ShowDialog()
"""
        said = []
        lists = live_lists.LiveLists(said.append)
        lists.decider = live_lists.Decider(input_age=lambda: 1e9,
                                           frameworks=('WPF',))
        self.assertTrue(lists.start())
        p, h = _probe(script, 'TA uwp test live %d' % os.getpid())
        if not h:
            self.skipTest('the WPF probe window did not open')
        try:
            lists.follow(h)
            p.wait(30)
        finally:
            lists.stop()
            if p.poll() is None:
                p.kill()
        self.assertIn('Nowa 4', said)
        self.assertIn('Nowa 5', said)
        self.assertNotIn('Wstawiona', said)


if __name__ == '__main__':
    unittest.main()

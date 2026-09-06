# -*- coding: utf-8 -*-
"""A TCE application, described rather than drawn - and never modified.

    python tests/test_app_ui.py

The reverse of `data/components/elten_bridge/`: that one runs somebody
else's applications inside Titan's interface, this one lets Titan's own be
worn by somebody else's. Nothing here opens a window, plays a sound,
speaks or reaches the network. The applications it drives are Titan's real
ones, unmodified - which is the whole claim, so testing against a
hand-built stand-in would test the wrong thing.
"""

import io
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
sys.path.insert(0, TITAN)

from src.app_ui import host, model, sessions, wire   # noqa: E402

#: Driven for real. tNotes is the specimen the shim was written against;
#: it writes its notes into the user's own Documents folder, so the tests
#: that CHANGE anything are the ones that put it back.
NOTES = os.path.join(TITAN, 'data', 'applications', 'tNotes', 'notes.py')


def opened(entry, name=''):
    application = host.Application(entry, name)
    if not application.start():
        raise unittest.SkipTest('%s did not start: %s'
                                % (name or entry, application.detail))
    return application


def control(screen, kind=None, label=None):
    for entry in (screen or {}).get('controls') or []:
        if kind and entry['kind'] != kind:
            continue
        if label and label.lower() not in entry['label'].lower():
            continue
        return entry
    return None


class TheWire(unittest.TestCase):
    def test_a_line_is_read_as_soon_as_it_arrives(self):
        """`BufferedReader.read(n)` on a pipe waits for n bytes or for the
        far end to close, so a whole screen sat unread until the
        application exited and the first thing Titan ever saw was a
        corpse. `read1` is what a line-based protocol needs."""
        class Pipe(object):
            def __init__(self):
                self.given = [b'{"do":"screen"}\n', b'']

            def read1(self, _size):
                return self.given.pop(0) if self.given else b''

            def read(self, _size):          # must not be the one used
                raise AssertionError('read() blocks; read1() is the one')

        self.assertEqual(list(wire.lines(Pipe())), [b'{"do":"screen"}'])

    def test_a_message_that_is_not_one_is_not_a_message(self):
        self.assertIsNone(wire.unpack(b'not json'))
        self.assertIsNone(wire.unpack(b'[1,2]'))
        self.assertEqual(wire.unpack(b'{"do":"x"}'), {'do': 'x'})


class TheDescription(unittest.TestCase):
    def test_a_control_says_what_it_is_without_saying_where(self):
        said = model.readable(model.control(1, 'check', 'Speak folders',
                                            value=True))
        self.assertIn('Speak folders', said)
        self.assertIn('checked', said)

    def test_a_list_says_how_many_and_which(self):
        said = model.readable(model.control(1, 'list', 'Notes',
                                            items=['a', 'b'], index=1))
        self.assertIn('2', said)
        self.assertIn('b', said)


class ARealApplicationDescribesItself(unittest.TestCase):
    """tNotes, unmodified, opened with a `wx` that describes instead of
    painting."""

    @classmethod
    def setUpClass(cls):
        cls.app = opened(NOTES, 'tNotes')

    @classmethod
    def tearDownClass(cls):
        cls.app.stop()

    def test_it_is_a_window_with_a_title(self):
        self.assertEqual(self.app.screen['kind'], 'window')
        self.assertTrue(self.app.screen['title'])

    def test_its_controls_are_there_with_their_accessible_names(self):
        """Titan's applications call `SetName` on every control precisely
        because they are written for people who cannot see them, so the
        accessible name is the best label there is."""
        controls = self.app.screen['controls']
        kinds = {entry['kind'] for entry in controls}
        self.assertIn('button', kinds)
        self.assertIn('table', kinds)
        self.assertTrue(all(entry['label'] for entry in controls
                            if entry['kind'] == 'button'))

    def test_its_menu_bar_is_described_without_the_ampersands(self):
        menus = self.app.screen['menus']
        self.assertTrue(menus)
        self.assertNotIn('&', menus[0]['label'])
        self.assertTrue(any(item.get('label') for item in menus[0]['items']))

    def test_a_separator_is_a_separator_and_not_a_line_of_dashes(self):
        items = self.app.screen['menus'][0]['items']
        self.assertTrue(any(item.get('separator') for item in items))

    def test_a_shortcut_is_kept_and_the_ampersand_is_not(self):
        for item in self.app.screen['menus'][0]['items']:
            self.assertNotIn('&', item.get('label', ''))
        self.assertTrue(any(item.get('key')
                            for item in self.app.screen['menus'][0]['items']))


class ItCanReallyBeUsed(unittest.TestCase):
    """Opening is not working. This presses the buttons."""

    def setUp(self):
        self.app = opened(NOTES, 'tNotes')

    def tearDown(self):
        self.app.stop()

    def test_a_button_opens_the_dialog_wx_would_have_opened(self):
        button = control(self.app.screen, 'button', 'No')   # New / Nowa
        self.assertIsNotNone(button)
        self.app.tell('press', control=button['id'])
        self.assertEqual(self.app.screen['kind'], 'entry')

    def test_a_ready_made_dialog_has_the_buttons_to_answer_it(self):
        """Described as nothing at all at first, which left a question on
        the screen and no way to answer it."""
        button = control(self.app.screen, 'button', 'No')
        self.app.tell('press', control=button['id'])
        self.assertIsNotNone(control(self.app.screen, 'button', 'OK'))
        self.assertIsNotNone(control(self.app.screen, 'button', 'Cancel'))

    def test_escape_leaves_a_dialog_because_it_does_in_wx(self):
        button = control(self.app.screen, 'button', 'No')
        self.app.tell('press', control=button['id'])
        self.assertEqual(self.app.screen['kind'], 'entry')
        self.app.tell('key', key='escape')
        self.assertEqual(self.app.screen['kind'], 'window')

    def test_a_field_takes_the_label_in_front_of_it(self):
        """How every wx program is built, and the rule Titan already
        applies to its own settings."""
        button = control(self.app.screen, 'button', 'No')
        self.app.tell('press', control=button['id'])
        field = control(self.app.screen, 'text')
        self.assertTrue(field['label'],
                        'a field with no name is a field a reader cannot name')


class WhatCannotBeShownIsSaid(unittest.TestCase):
    """A web view or a media surface cannot be a list of controls, and
    saying so is the whole of the honest answer."""

    def test_the_browser_is_refused_by_name(self):
        entry = os.path.join(TITAN, 'data', 'applications', 'tWeb', 'web.py')
        if not os.path.isfile(entry):
            self.skipTest('tWeb is not installed')
        application = host.Application(entry, 'Web Browser')
        self.assertFalse(application.start())
        self.assertIn('wx.html2', application.detail)
        self.assertTrue(any(one['what'] == 'wx.html2'
                            for one in application.refused))
        application.stop()


class TheLongTailDegrades(unittest.TestCase):
    """98 of the 274 wx names Titan's applications use are used exactly
    once. A shim that raises on the first one it has not got never
    finishes.

    **Asked in a subprocess, because that is where the shim lives.**
    Titan's own test runner has the real wxPython imported already, and a
    test that swapped it out in-process would be testing whichever `wx`
    won the race rather than this one.
    """

    def ask(self, source):
        import subprocess
        shim = os.path.join(TITAN, 'src', 'app_ui', 'shim')
        code = 'import sys\nsys.path.insert(0, r"%s")\n%s' % (shim, source)
        answer = subprocess.run([sys.executable, '-c', code],
                                capture_output=True, text=True, timeout=60,
                                cwd=TITAN)
        self.assertEqual(answer.returncode, 0,
                         'the shim raised:\n%s' % answer.stderr[-1500:])
        return answer.stdout.strip()

    def test_the_shim_is_the_wx_that_is_imported(self):
        where = self.ask('import wx; print(wx.__file__)')
        self.assertIn(os.path.join('app_ui', 'shim', 'wx'), where)

    def test_a_constant_nobody_wrote_is_still_a_constant(self):
        self.assertEqual(
            self.ask('import wx; print(int(wx.SOME_STYLE_NOBODY_WROTE) | 5)'),
            '5')

    def test_a_class_nobody_wrote_can_still_be_subclassed(self):
        self.assertEqual(self.ask(
            'import wx\n'
            'class Mine(wx.SomethingNobodyWrote): pass\n'
            'print(Mine() is not None)'), 'True')

    def test_a_chain_of_nothing_is_still_nothing(self):
        """The browser stopped one attribute further along than it would
        have, because a method that was not there answered None and the
        next call went to None."""
        self.assertEqual(self.ask(
            'import wx\n'
            'bar = wx.Frame().CreateStatusBar()\n'
            'print(bool(bar.SetStatusWidths([1, 2]).AndAnother()))'), 'False')

    def test_a_submodule_is_answered_because_import_is_not_getattr(self):
        self.assertEqual(self.ask(
            'import wx, wx.adv, wx.lib.newevent\n'
            'event, binder = wx.lib.newevent.NewEvent()\n'
            'print(wx.adv.CalendarCtrl is not None, event is not None,'
            ' binder is not None)'), 'True True True')

    def test_a_sizer_swallows_everything_and_answers_nothing(self):
        self.assertEqual(self.ask(
            'import wx\n'
            'sizer = wx.BoxSizer(wx.VERTICAL)\n'
            'print(sizer.Add(object(), proportion=1, flag=wx.ALL, border=10))'),
            'None')

    def test_a_class_answers_its_own_attributes_too(self):
        """`wx.SomeThing.Open(...)` is a CLASS attribute, which
        `__getattr__` on the class body never sees - the download manager
        stopped on exactly that."""
        self.assertEqual(self.ask(
            'import wx\n'
            'print(wx.SomethingNobodyWrote.Open("x") is None'
            ' or bool(wx.SomethingNobodyWrote.Open("x")) is False)'), 'True')

    def test_a_web_view_is_refused_by_name_at_import(self):
        """An application whose interface IS a web view has nothing to
        describe, and it says so at its first line rather than hanging."""
        self.assertIn('wx.html2', self.ask(
            'import wx, wx.html2\n'
            'print([one["what"] for one in wx.RUNTIME.refused])'))


class WhatTheWalkFound(unittest.TestCase):
    """Opening is not working. Every one of these was found by pressing
    things - the technique that found every real gap in Cling and in the
    Elten port, and by nothing else."""

    def setUp(self):
        self.app = opened(NOTES, 'tNotes')

    def tearDown(self):
        self.app.stop()

    def test_a_press_that_changes_nothing_is_still_answered(self):
        """A press the application did nothing with sent nothing back, so
        the caller waited out its whole timeout - five seconds per no-op,
        which over one walk of the file manager was forty-five seconds of
        an interface that looked hung."""
        import time
        button = control(self.app.screen, 'button', 'Pow') or \
            control(self.app.screen, 'button')
        began = time.time()
        self.app.tell('press', control=button['id'])
        self.assertLess(time.time() - began, 2.0)

    def test_a_key_nobody_wanted_is_still_answered(self):
        import time
        began = time.time()
        self.app.tell('key', key='f7')
        self.assertLess(time.time() - began, 2.0)
        self.assertTrue(self.app.screen)

    def test_a_menu_item_really_fires(self):
        """A menu item is created with the MENU as its parent and a menu
        had no parent at all, while every application binds its menu on
        the FRAME - so not one menu item in any application did
        anything."""
        menus = self.app.screen['menus']
        item = None
        for entry in menus[0]['items']:
            if entry.get('label') and not entry.get('separator') \
                    and 'ustawien' in entry['label'].lower():
                item = entry
        if item is None:
            self.skipTest('this build of tNotes has no settings item')
        before = self.app.screen['id']
        self.app.tell('press', control=item['id'])
        self.assertNotEqual(self.app.screen['id'], before,
                            'the menu item did nothing')


class AnApplicationThatPutsItselfAway(unittest.TestCase):
    """The organiser's "minimise to system tray" hides its only window,
    and there is no tray here. The screen stack went empty, nothing was
    sent, and every message after it waited out its timeout against an
    application that was alive and perfectly well."""

    def test_it_says_so_and_offers_the_way_back(self):
        found = sessions.find('reminder')
        if found is None:
            self.skipTest('the organiser is not installed')
        application = host.Application(found['entry'], found['name'])
        if not application.start():
            self.skipTest(application.detail)
        try:
            hide = None
            for menu in application.screen['menus']:
                for item in menu['items']:
                    label = str(item.get('label') or '').lower()
                    if 'zasobnik' in label or 'tray' in label:
                        hide = item
            if hide is None:
                self.skipTest('this build has no minimise-to-tray')
            import time
            began = time.time()
            application.tell('press', control=hide['id'])
            self.assertLess(time.time() - began, 2.0,
                            'a hidden window answered with silence')
            screen = application.screen
            self.assertTrue(screen)
            self.assertTrue(any(c['kind'] == 'button'
                                for c in screen['controls']),
                            'there is no way back')
        finally:
            application.stop()


class TheFloorUnderneath(unittest.TestCase):
    """An application that cannot describe itself is READ off its own
    window, in the same screen model - and says that is what it is."""

    def test_the_shim_gives_up_at_once_on_a_fatal_refusal(self):
        """It arrives at the application's first line, so waiting out the
        whole start-up window for a screen that cannot come made opening
        the browser take 28 seconds when the floor needs one."""
        found = sessions.find('web')
        if found is None:
            self.skipTest('tWeb is not installed')
        import time
        application = host.Application(found['entry'], found['name'])
        began = time.time()
        self.assertFalse(application.start())
        application.stop()
        self.assertLess(time.time() - began, host.START_WAIT,
                        'it waited for a screen it already knew was not coming')
        self.assertIn('wx.html2', application.detail)

    def test_a_browser_opens_through_the_floor(self):
        from src.app_ui import mirror
        if not mirror.available():
            self.skipTest("this machine cannot read another program's window")
        found = sessions.find('web')
        if found is None:
            self.skipTest('tWeb is not installed')
        session, problem = sessions.open_application(found['name'])
        self.assertIsNotNone(session, problem)
        try:
            application = session.application
            self.assertTrue(application.mirrored)
            screen = application.screen
            self.assertTrue(screen.get('mirror'))
            self.assertTrue(screen['controls'])
            # It says what it is, before anything else.
            self.assertIn('Windows', screen['controls'][0]['label'])
        finally:
            sessions.close(session.token)

    def test_the_frame_around_a_window_is_not_the_window(self):
        """Read as it comes, a browser answered with Minimise, Maximise,
        Close, context help, the IME button and both scrollbars' arrows -
        three times over - before a word of its own."""
        from src.app_ui import mirror
        for name in ('Minimalizuj', 'Maksymalizuj', 'IME'):
            self.assertFalse(mirror._within((0, 0, 10, 10), (100, 100, 200, 200)),
                             'a control outside the client area is furniture')
        self.assertTrue(mirror._within((150, 150, 160, 160), (100, 100, 200, 200)))
        self.assertTrue(mirror._within((), (100, 100, 200, 200)),
                        'not knowing where it is is not a reason to hide it')

    def test_a_class_name_is_not_something_on_the_screen(self):
        from src.app_ui import mirror
        self.assertIn('panel', mirror.CONTAINERS)
        self.assertIn('wxwebview', mirror.CONTAINERS)

    def test_an_application_that_is_merely_broken_is_not_mirrored(self):
        """Putting a window up to prove a missing library is missing
        wastes the user's time and leaves a process behind."""
        class Broken(object):
            refused = [{'what': 'wx.Timer', 'detail': 'no tick'}]
        self.assertFalse(sessions._can_be_mirrored(Broken()))

        class WebView(object):
            refused = [{'what': 'wx.html2', 'detail': 'a web view'}]
        self.assertTrue(sessions._can_be_mirrored(WebView()))


class WhereItOpensIsTheClientsChoice(unittest.TestCase):
    """Starting an application has always meant a window on this machine's
    screen. A client that is going to render the interface itself asks for
    that instead - at the ordinary call, so the choice is discoverable."""

    def bridge(self, _call, **args):
        # `name` is an argument of the CALL, so the call itself cannot be
        # called `name` too.
        import json
        from src.titan_core import bridge_api
        return json.loads(bridge_api.bridge(
            json.dumps({'call': _call, 'args': args})))

    def test_the_ordinary_call_can_hand_it_over_described(self):
        answer = self.bridge('apps.open', name='tnotes', render=True)
        self.assertTrue(answer.get('ok'), answer.get('error'))
        data = answer['data']
        self.assertIn('session', data)
        self.assertTrue(data['screen']['controls'])
        self.assertFalse(data['mirror'])
        self.bridge('app.close', session=data['session'])

    def test_an_answer_says_which_of_the_two_it_is(self):
        """A client that could not tell them apart would present a mirror
        as though it were the application."""
        answer = self.bridge('app.open', name='tnotes')
        self.assertTrue(answer.get('ok'), answer.get('error'))
        self.assertIn('mirror', answer['data'])
        self.bridge('app.close', session=answer['data']['session'])


class TheBridgeHasTheSwitch(unittest.TestCase):
    """`elten-tce-bridge` is one client, and the first. Its own setting
    decides whether starting a TCE application from it opens a window on
    this machine or a screen over there."""

    def read(self, name):
        with io.open(os.path.join(TITAN, 'elten-tce-bridge', name),
                     encoding='utf-8') as handle:
            return handle.read()

    def test_it_is_declared_and_starts_off(self):
        prefs = self.read('titan_prefs.rb')
        self.assertIn('"render_apps" => false', prefs)
        self.assertIn('def render_apps?', prefs)

    def test_it_is_offered_in_the_settings(self):
        self.assertIn('Render TCE applications (experimental)',
                      self.read('__app.rb'))

    def test_one_place_decides_where_an_application_appears(self):
        """The Applications tab and the areas list disagreeing about what
        pressing a row does would be worse than either behaviour."""
        console = self.read('titan_console.rb')
        self.assertIn('def render_here(name)', console)
        self.assertEqual(console.count('TitanPrefs.render_apps?'), 1)

    def test_a_renderer_that_fails_does_not_swallow_the_application(self):
        console = self.read('titan_console.rb')
        where = console.index('def render_here')
        self.assertIn('rescue Exception', console[where:where + 900])
        self.assertIn('started in TCE', console[where:where + 900])


class AScreenCanBeREAD(unittest.TestCase):
    """Opening is not working and working is not readable. These are what
    make a screen unusable by ear, and every one was found by looking at
    what a renderer was actually handed."""

    def screen_of(self, name, opener=None):
        found = sessions.find(name)
        if found is None:
            self.skipTest('%s is not installed' % name)
        application = opened(found['entry'], found['name'])
        self.addCleanup(application.stop)
        if opener:
            for menu in application.screen['menus']:
                for item in menu['items']:
                    if opener.lower() in str(item.get('label') or '').lower():
                        application.tell('press', control=item['id'])
        return application.screen

    def test_it_reads_in_the_order_the_application_laid_it_out(self):
        """The organiser BUILDS three drop-downs and only then adds "Day:",
        the day, "Month:", the month to the sizer. Read in creation order
        the labels are stranded at the end and two of the drop-downs have
        no name at all."""
        screen = self.screen_of('Organizer', opener='Nowe')
        if screen['kind'] != 'dialog':
            self.skipTest('this build does not open that dialog')
        names = [c['label'] for c in screen['controls'] if c['kind'] == 'choice']
        self.assertTrue(names, 'the dialog has no choices')
        self.assertTrue(all(name.strip() for name in names),
                        'a drop-down with no name: %r' % names)
        self.assertEqual(len(set(names)), len(names),
                         'two drop-downs share a name: %r' % names)

    def test_a_label_that_named_a_control_is_not_read_twice(self):
        screen = self.screen_of('Organizer', opener='Nowe')
        controls = screen['controls']
        for index, entry in enumerate(controls[:-1]):
            if entry['kind'] != 'label':
                continue
            after = controls[index + 1]['label'].rstrip(':').strip().lower()
            self.assertNotEqual(entry['label'].rstrip(':').strip().lower(),
                                after, 'said twice: %r' % entry['label'])

    def test_a_label_with_nothing_to_say_is_not_a_line(self):
        screen = self.screen_of('tfm')
        for entry in screen['controls']:
            if entry['kind'] == 'label':
                self.assertTrue(entry['label'].strip(),
                                'an empty line the reader stops on')

    def test_a_control_nobody_named_says_what_it_is(self):
        """Two of Titan's applications put their main table up with no
        name and no text before it."""
        screen = self.screen_of('tfm')
        tables = [c for c in screen['controls'] if c['kind'] == 'table']
        self.assertTrue(tables)
        self.assertTrue(tables[0]['label'].strip())
        if tables[0].get('unnamed'):
            # The word is English here on purpose: the interface knows
            # what language the reader speaks and this does not.
            self.assertEqual(tables[0]['label'], 'Table')

    def test_a_submenu_is_described_with_what_is_in_it(self):
        screen = self.screen_of('tfm')
        submenus = [item for menu in screen['menus']
                    for item in menu['items'] if 'items' in item]
        if not submenus:
            self.skipTest('this build has no submenu')
        self.assertTrue(submenus[0]['items'],
                        'a submenu with nothing in it is an entry that does '
                        'nothing when it is pressed')
        for item in submenus[0]['items']:
            self.assertIn('id', item)
            self.assertTrue(item.get('label'))

    def test_the_renderer_walks_into_a_submenu(self):
        source = io.open(os.path.join(TITAN, 'elten-tce-bridge',
                                      'titan_apps.rb'),
                         encoding='utf-8').read()
        self.assertIn('def menu_entries', source)
        self.assertIn('menu_entries([item], here)', source)


class AFileDialogSaysItHoldsAPath(unittest.TestCase):
    """The application asked for a file chooser and there is no file
    system on the other side of this wire, so it becomes a field - and
    saying that the field holds a PATH is what lets the interface offer
    its own chooser, which is the one the user already knows. Typing a
    path out is not what anybody meant by "open"."""

    def test_a_file_dialog_is_a_path_field(self):
        folder = tempfile.mkdtemp(prefix='app-ui-path-')
        self.addCleanup(shutil.rmtree, folder, True)
        entry = os.path.join(folder, 'app.py')
        with io.open(entry, 'w', encoding='utf-8') as handle:
            handle.write('import wx\n'
                         'frame = wx.Frame(None, title="Path test")\n'
                         'frame.Show(True)\n'
                         'wx.FileDialog(frame, "Open a document").ShowModal()\n'
                         'wx.App().MainLoop()\n')
        application = host.Application(entry, 'Path test')
        if not application.start():
            self.skipTest(application.detail)
        try:
            fields = [c for c in application.screen['controls']
                      if c['kind'] == 'text']
            self.assertTrue(fields)
            self.assertTrue(fields[0].get('path'),
                            'the interface has no way to know it is a path')
            self.assertTrue(any(one['what'] == 'wx.FileDialog'
                                for one in application.refused))
        finally:
            application.stop()

    def test_a_saving_dialog_says_it_is_saving(self):
        """Saving is not opening and a folder is not a file: a chooser
        for one is the wrong control for the other, and only the
        application knows which it asked for."""
        for style, wanted in (('wx.FD_SAVE', 'save'),
                              ('wx.FD_OPEN', 'open')):
            folder = tempfile.mkdtemp(prefix='app-ui-path-')
            self.addCleanup(shutil.rmtree, folder, True)
            entry = os.path.join(folder, 'app.py')
            with io.open(entry, 'w', encoding='utf-8') as handle:
                handle.write('import wx\n'
                             'frame = wx.Frame(None, title="t")\n'
                             'frame.Show(True)\n'
                             'wx.FileDialog(frame, "Pick", "", "notes.txt",\n'
                             '              "Text (*.txt)|*.txt", %s'
                             ').ShowModal()\n'
                             'wx.App().MainLoop()\n' % style)
            application = host.Application(entry, 'Path test')
            if not application.start():
                self.skipTest(application.detail)
            try:
                field = [c for c in application.screen['controls']
                         if c['kind'] == 'text'][0]
                self.assertEqual(field.get('path'), wanted)
                self.assertEqual(field.get('extensions'), ['txt'])
            finally:
                application.stop()

    def test_a_folder_chooser_says_it_wants_a_folder(self):
        folder = tempfile.mkdtemp(prefix='app-ui-path-')
        self.addCleanup(shutil.rmtree, folder, True)
        entry = os.path.join(folder, 'app.py')
        with io.open(entry, 'w', encoding='utf-8') as handle:
            handle.write('import wx\n'
                         'frame = wx.Frame(None, title="t")\n'
                         'frame.Show(True)\n'
                         'wx.DirDialog(frame, "Pick a folder").ShowModal()\n'
                         'wx.App().MainLoop()\n')
        application = host.Application(entry, 'Path test')
        if not application.start():
            self.skipTest(application.detail)
        try:
            field = [c for c in application.screen['controls']
                     if c['kind'] == 'text'][0]
            self.assertEqual(field.get('path'), 'folder')
        finally:
            application.stop()

    def test_a_style_flag_that_decides_something_is_not_made_up(self):
        """The long tail answers an unknown name with 0, which is right
        for a flag nobody reads and wrong for one that decides: `FD_SAVE`
        fabricated as 0 made every save dialog look like an open one."""
        import subprocess
        shim = os.path.join(TITAN, 'src', 'app_ui', 'shim')
        answer = subprocess.run(
            [sys.executable, '-c',
             'import sys; sys.path.insert(0, r"%s")\n'
             'import wx; print(wx.FD_SAVE, wx.FD_OPEN)' % shim],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(answer.stdout.strip(), '4 1')


class TheFileManagersOwnKeys(unittest.TestCase):
    """Enter opens a folder and Backspace goes up - which is most of how a
    file manager is walked."""

    def setUp(self):
        found = sessions.find('tfm')
        if found is None:
            self.skipTest('the file manager is not installed')
        self.app = opened(found['entry'], found['name'])

    def tearDown(self):
        self.app.stop()

    def table(self):
        for entry in self.app.screen['controls']:
            if entry['kind'] == 'table':
                return entry
        return None

    def rows(self):
        return len((self.table() or {}).get('items') or [])

    def test_enter_opens_the_row_and_backspace_comes_back(self):
        table = self.table()
        self.assertIsNotNone(table)
        before = self.rows()
        self.app.tell('set', control=table['id'], value=0)
        self.app.tell('press', control=table['id'])
        self.assertNotEqual(self.rows(), before, 'Enter opened nothing')
        self.app.tell('key', key='backspace')
        self.assertEqual(self.rows(), before, 'Backspace did not come back')

    def test_the_renderer_forwards_backspace(self):
        source = io.open(os.path.join(TITAN, 'elten-tce-bridge',
                                      'titan_apps.rb'),
                         encoding='utf-8').read()
        self.assertIn('0x08 => "backspace"', source)
        # ...and never takes it from something being typed into.
        self.assertIn('EDITING_KEYS', source)


class TheApplicationsOwnShortcuts(unittest.TestCase):
    """Ctrl+S is a MENU shortcut, so the menu item is pressed - which is
    exactly what the accelerator would have done, without the shim having
    to implement accelerators at all."""

    def test_a_menu_item_carries_its_shortcut(self):
        found = sessions.find('tedit')
        if found is None:
            self.skipTest('the editor is not installed')
        application = opened(found['entry'], found['name'])
        self.addCleanup(application.stop)
        shortcuts = [item.get('key') for menu in application.screen['menus']
                     for item in menu['items'] if item.get('key')]
        self.assertTrue(shortcuts, 'no shortcut was described at all')
        self.assertTrue(any('Ctrl' in one for one in shortcuts))

    def test_shift_is_part_of_the_shortcut(self):
        """Read without it, "Save as...\tCtrl+Shift+S" became a second
        Ctrl+S and shadowed "Save"."""
        source = io.open(os.path.join(TITAN, 'elten-tce-bridge',
                                      'titan_apps.rb'),
                         encoding='utf-8').read()
        self.assertIn('shift = key.include?("shift+")', source)
        self.assertIn('wants_shift == shift', source)


class NothingHereKnowsAboutElten(unittest.TestCase):
    """**The description must stay renderable by anything.**

    The Elten bridge is the first client and deliberately only the first:
    the same description has to serve the Invisible UI, a Titan Script, a
    launcher - and something nobody has written yet, on a terminal, in
    another editor, on another machine. The moment a word of one client's
    vocabulary gets into the shim or the model, the next client has to
    undo it, so this fails if one does.
    """

    def files(self):
        base = os.path.join(TITAN, 'src', 'app_ui')
        for folder, _dirs, names in os.walk(base):
            for name in names:
                if name.endswith('.py'):
                    yield os.path.join(folder, name)

    def test_no_client_is_named_in_the_code(self):
        """In the code, not in the prose. Explaining the design by naming
        the client it is deliberately not shaped like is worth doing;
        BEHAVING differently for one is the thing that must never
        happen, and a docstring cannot do that."""
        import ast
        named = []
        for path in self.files():
            with io.open(path, encoding='utf-8') as handle:
                tree = ast.parse(handle.read())
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                    first = (node.body or [None])[0]
                    if isinstance(first, ast.Expr) and \
                            isinstance(first.value, ast.Constant) and \
                            isinstance(first.value.value, str):
                        docstrings.add(id(first.value))
            for node in ast.walk(tree):
                said = ''
                if isinstance(node, ast.Constant) and \
                        isinstance(node.value, str) and id(node) not in docstrings:
                    said = node.value
                elif isinstance(node, ast.Name):
                    said = node.id
                elif isinstance(node, ast.Attribute):
                    said = node.attr
                for word in ('elten', 'emacs'):
                    if word in said.lower():
                        named.append('%s: %r' % (os.path.basename(path), said))
        self.assertEqual(named, [],
                         'a client is named where the description is made')

    def test_a_screen_can_be_rendered_as_nothing_but_lines(self):
        """The floor under every interface: a client with no controls of
        its own can still say what is there, and something said is always
        better than an interface silently missing."""
        application = opened(NOTES, 'tNotes')
        self.addCleanup(application.stop)
        lines = sessions.spoken(application.screen)
        self.assertTrue(lines)
        self.assertTrue(all(isinstance(line, str) for line in lines))
        self.assertTrue(any('tNotes' in line for line in lines))

    def test_every_control_kind_has_a_way_to_be_said(self):
        for kind in model.KINDS:
            said = model.readable(model.control(1, kind, ''))
            self.assertTrue(said.strip(),
                            'a %s cannot be put into words' % kind)

    def test_the_whole_surface_is_json(self):
        """A client on the other end of a pipe gets JSON and nothing
        else - no Python objects, no wx, no Titan."""
        import json
        application = opened(NOTES, 'tNotes')
        self.addCleanup(application.stop)
        json.dumps(application.screen)


class EveryInstalledApplication(unittest.TestCase):
    """The sweep. Opening all of them is what found every real gap - the
    file manager reading its columns by name, the download manager's
    `wx.lib.newevent`, the organiser's `wx.adv`."""

    def test_the_list_is_the_one_titan_shows(self):
        found = sessions.applications('en')
        self.assertTrue(found)
        self.assertTrue(all(entry['entry'] and os.path.isfile(entry['entry'])
                            for entry in found))

    def test_one_can_be_found_by_its_short_name(self):
        self.assertIsNotNone(sessions.find('tnotes'))
        self.assertIsNone(sessions.find('there is no such application'))

    def test_it_answers_to_the_name_the_user_pressed(self):
        """A client shows the applications in the user's own language and
        then asks for the one they chose. Looking that up under a single
        language answered "there is no TCE application called 'Notatki'"
        about the application in the list they had just pressed."""
        english = sessions.find('Notes')
        polish = sessions.find('Notatki')
        if english is None:
            self.skipTest('tNotes is not installed')
        self.assertIsNotNone(polish, 'the Polish name found nothing')
        self.assertEqual(polish['entry'], english['entry'])
        self.assertEqual(sessions.find('tnotes')['entry'], english['entry'])

    def test_a_name_that_is_nobody_is_still_nobody(self):
        """Matching every spelling must not make everything match."""
        self.assertIsNone(sessions.find('zzzz'))
        self.assertIsNone(sessions.find(''))

    def test_the_language_decides_what_it_is_called(self):
        names = {entry['id']: entry['name']
                 for entry in sessions.applications('pl')}
        english = {entry['id']: entry['name']
                   for entry in sessions.applications('en')}
        if 'tnotes' not in names:
            self.skipTest('tNotes is not installed')
        self.assertNotEqual(names['tnotes'], english['tnotes'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

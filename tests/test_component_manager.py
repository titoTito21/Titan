# -*- coding: utf-8 -*-
"""The Component Manager: every module of Titan switched on and off.

Run directly: ``python tests/test_component_manager.py``. Every test runs on
a temporary APPDATA, so the store and the add-ons it writes are its own;
nothing is shown, spoken or sent anywhere.
"""
import os
import shutil
import sys
import tempfile
import unittest

_HOME = tempfile.mkdtemp(prefix='titan_modules_')
os.environ['APPDATA'] = _HOME
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import wx  # noqa: E402

_APP = wx.App(False)

from src import platform_utils  # noqa: E402
from src.titan_core import modules  # noqa: E402


def _user_addon(subdir, name, manifest, text):
    folder = os.path.join(platform_utils.get_user_data_dir(), 'data', subdir, name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, manifest), 'w', encoding='utf-8') as handle:
        handle.write(text)
    return folder


def _reset():
    try:
        os.remove(modules.store_path())
    except OSError:
        pass
    modules._session_changes.clear()


class TheStoreIsWhatDiscoveryAsks(unittest.TestCase):
    def setUp(self):
        _reset()
        _user_addon('applications', 'zz_test_app', '__app.TCE',
                    'name_pl="Testowa"\nname_en="Test app"\nopenfile="x.py"\n')

    def test_a_switched_off_app_is_absent_everywhere(self):
        module = modules.find('app', 'zz_test_app')
        self.assertTrue(module.enabled)
        change = modules.set_enabled(module, False)
        self.assertTrue(change.ok)
        self.assertEqual(change.applies, 'live')
        self.assertNotIn('zz_test_app',
                         platform_utils.discover_data_entries('applications'))
        self.assertIn('zz_test_app', platform_utils.discover_data_entries(
            'applications', include_disabled=True))
        from src.titan_core import app_manager
        self.assertNotIn('x.py', [a.get('openfile') for a in app_manager.get_applications()
                                  if a.get('path', '').endswith('zz_test_app')])
        self.assertFalse(modules.find('app', 'zz_test_app').enabled)

    def test_switching_back_on_clears_the_store(self):
        module = modules.find('app', 'zz_test_app')
        modules.set_enabled(module, False)
        modules.set_enabled(module, True)
        self.assertIn('zz_test_app',
                      platform_utils.discover_data_entries('applications'))
        self.assertEqual(modules.disabled_names('applications'), frozenset())


class AManifestWithAStatusIsTheSwitch(unittest.TestCase):
    TEXT = ("[component]\n; keep this comment\nname = Test component\n"
            "status = 0\ndescription = Something\n")

    def setUp(self):
        _reset()
        self.folder = _user_addon('components', 'zz_test_component',
                                  '__component__.TCE', self.TEXT)
        self.manifest = os.path.join(self.folder, '__component__.TCE')

    def read(self):
        with open(self.manifest, encoding='utf-8') as handle:
            return handle.read()

    def test_the_status_line_is_written_and_nothing_else(self):
        module = modules.find('component', 'zz_test_component')
        change = modules.set_enabled(module, False)
        self.assertTrue(change.ok)
        self.assertTrue(change.needs_restart)
        text = self.read()
        self.assertIn('status = 1', text)
        self.assertIn('; keep this comment', text)
        self.assertIn('description = Something', text)
        # The manifest is the switch, not the store.
        self.assertEqual(modules.disabled_names('components'), frozenset())
        self.assertFalse(modules.find('component', 'zz_test_component').enabled)

    def test_switching_back_needs_no_restart_any_more(self):
        module = modules.find('component', 'zz_test_component')
        modules.set_enabled(module, False)
        self.assertTrue(modules.waits_for_restart(module))
        modules.set_enabled(module, True)
        self.assertFalse(modules.pending_restart())
        self.assertIn('status = 0', self.read())

    def test_a_manifest_without_a_status_gets_one(self):
        with open(self.manifest, 'w', encoding='utf-8') as handle:
            handle.write("[component]\nname = Test component\n")
        module = modules.find('component', 'zz_test_component')
        modules.set_enabled(module, False)
        self.assertIn('status = 1', self.read())


class BuiltInServices(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_every_service_is_listed_and_switches(self):
        self.assertEqual([m.id for m in modules.services()],
                         list(modules.SERVICE_IDS))
        module = modules.find('service', 'telegram')
        self.assertTrue(module.enabled)
        modules.set_enabled(module, False)
        self.assertFalse(modules.service_enabled('telegram'))
        modules.set_enabled(module, True)
        self.assertTrue(modules.service_enabled('telegram'))

    def test_a_titan_im_row_is_recognised_however_it_is_labelled(self):
        modules.set_enabled(modules.find('service', 'telegram'), False)
        self.assertFalse(modules.im_row_shown('Telegram'))
        self.assertFalse(modules.im_row_shown('Telegram - connected as anna'))
        self.assertTrue(modules.im_row_shown('WhatsApp'))
        self.assertTrue(modules.im_row_shown('Example IM'))
        self.assertEqual(modules.im_service_of('EltenLink (Beta)'), 'eltenlink')

    def test_steam_is_not_asked_when_switched_off(self):
        from src.titan_core import game_manager
        asked = []
        original = game_manager.get_steam_games
        game_manager.get_steam_games = lambda: asked.append(1) or []
        try:
            modules.set_enabled(modules.find('service', 'steam'), False)
            game_manager.get_games()
            self.assertEqual(asked, [])
            modules.set_enabled(modules.find('service', 'steam'), True)
            game_manager.get_games()
            self.assertEqual(asked, [1])
        finally:
            game_manager.get_steam_games = original

    def test_a_setting_backed_service_is_the_setting(self):
        from src.settings.settings import get_setting
        module = modules.find('service', 'ai')
        modules.set_enabled(module, True)
        self.assertEqual(str(get_setting('enabled', '0', section='ai')), '1')
        modules.set_enabled(module, False)
        self.assertEqual(str(get_setting('enabled', '0', section='ai')), '0')


class TheWindow(unittest.TestCase):
    def setUp(self):
        _reset()
        _user_addon('applications', 'zz_test_app', '__app.TCE',
                    'name_en="Test app"\nname_pl="Testowa"\nopenfile="x.py"\n')
        from src.ui import componentmanagergui as gui
        self.gui = gui
        self.messages = []
        self._message = gui._show_skinned_message
        gui._show_skinned_message = lambda *a, **k: self.messages.append(a) or wx.ID_NO
        self.dialog = gui.ComponentManagerDialog(None, "CM")
        self.spoken = []
        self.dialog.tts = type('S', (), {'output': lambda _s, t, **k: self.spoken.append(t)})()

    def tearDown(self):
        self.dialog._asked_restart = True
        self.dialog.Destroy()
        self.gui._show_skinned_message = self._message

    def test_row_zero_is_the_tab_bar_and_components_come_first(self):
        listbox = self.dialog.component_listbox
        self.assertEqual(self.dialog.current_tab, 'component')
        self.assertTrue(self.dialog.is_tab_bar_row(0))
        self.assertIn('service', [kind for kind, _l in self.dialog.tabs])
        self.assertEqual(listbox.GetCount(), len(self.dialog.items) + 1)

    def test_the_tab_bar_cycles_and_stops_at_its_ends(self):
        self.dialog.cycle_tab(-1)
        self.assertEqual(self.dialog.current_tab, 'component')
        self.dialog.cycle_tab(+1)
        self.assertEqual(self.dialog.current_tab, self.dialog.tabs[1][0])

    def test_space_switches_the_row_and_says_so(self):
        self.dialog.current_tab = 'app'
        self.dialog.populate_component_list()
        listbox = self.dialog.component_listbox
        position = next(i for i, m in enumerate(self.dialog.items)
                        if m.id == 'zz_test_app')
        listbox.SetSelection(position + 1)
        listbox.SetFocus()
        self.dialog.toggle_selected()
        module = self.dialog.items[position]
        self.assertFalse(module.enabled)
        self.assertIn(self.gui._("Disabled"), listbox.GetString(position + 1))
        self.assertTrue(self.spoken)
        self.assertNotIn('zz_test_app',
                         platform_utils.discover_data_entries('applications'))
        labels = [label for label, _f in self.dialog.menu_entries(module)]
        self.assertIn(self.gui._("Switch on"), labels)

    def test_closing_with_a_waiting_change_offers_a_restart(self):
        folder = _user_addon('components', 'zz_test_component',
                             '__component__.TCE', "[component]\nname = T\nstatus = 0\n")
        self.assertTrue(folder)
        modules.set_enabled(modules.find('component', 'zz_test_component'), False)
        self.dialog.offer_restart(ask=True)
        self.assertEqual(len(self.messages), 1)   # answered No: nothing restarts


class ExternalClientsHaveATab(unittest.TestCase):
    """Titan asks whether an external client (the Elten bridge, the NVDA
    add-on) may control it, and says when one arrives - and the refusal told
    the user to look "in Settings, General, under External clients", which
    did not exist. It is a tab of this window now."""

    def setUp(self):
        _reset()
        from src.titan_core import client_consent, external_clients
        self.consent = client_consent
        self.clients = external_clients
        from src.settings.settings import load_settings, save_settings
        settings = load_settings()
        settings.pop(client_consent.SECTION, None)
        settings.pop(client_consent.OPTIONS_SECTION, None)
        save_settings(settings)
        client_consent.remember('elten_tce_bridge', True)
        client_consent.remember('nvda', False)
        from src.ui import componentmanagergui as gui
        self.gui = gui
        self.dialog = gui.ComponentManagerDialog(None, "CM")
        self.spoken = []
        self.dialog.tts = type('S', (), {'output': lambda _s, t, **k: self.spoken.append(t)})()
        self.asked = []
        self._ask = client_consent._ask_now
        client_consent._ask_now = lambda cid, label: self.asked.append(cid)

    def tearDown(self):
        self.consent._ask_now = self._ask
        self.dialog._asked_restart = True
        self.dialog.Destroy()

    def _open_tab(self):
        self.dialog.current_tab = 'client'
        self.dialog.populate_component_list()
        return self.dialog.items

    def _select(self, ident):
        position = next(i for i, m in enumerate(self.dialog.items) if m.id == ident)
        self.dialog.component_listbox.SetSelection(position + 1)
        return position

    def test_the_tab_is_there_with_its_settings_and_every_client(self):
        self.assertIn('client', [kind for kind, _l in self.dialog.tabs])
        ids = [m.id for m in self._open_tab()]
        self.assertEqual(ids[:2], [self.clients.POLICY_ROW, self.clients.ANNOUNCE_ROW])
        self.assertIn('elten_tce_bridge', ids)
        self.assertIn('nvda', ids)
        text = self.dialog.component_listbox.GetString(ids.index('nvda') + 1)
        self.assertIn(self.gui._("not allowed to control Titan"), text)

    def test_space_allows_a_client_and_says_so(self):
        self._open_tab()
        position = self._select('nvda')
        self.dialog.toggle_selected()
        self.assertTrue(self.consent.known('nvda'))
        self.assertTrue(self.consent.may_drive('nvda'))
        self.assertIn(self.gui._("allowed to control Titan"),
                      self.dialog.component_listbox.GetString(position + 1))
        self.assertTrue(self.spoken)

    def test_ask_again_forgets_the_answer(self):
        self._open_tab()
        self._select('elten_tce_bridge')
        module = self.dialog.selected_module()
        entries = dict(self.dialog.menu_entries(module))
        entries[self.gui._("Ask again when it next connects")]()
        self.assertIsNone(self.consent.known('elten_tce_bridge'))

    def test_the_rule_for_new_clients_is_used_and_nothing_is_asked(self):
        self._open_tab()
        self._select(self.clients.POLICY_ROW)
        self.dialog.toggle_selected()                  # ask -> allow
        self.assertEqual(self.consent.new_client_policy(), 'allow')
        self.assertTrue(self.consent.may_drive('somebody_new'))
        self.dialog.toggle_selected()                  # allow -> deny
        self.assertFalse(self.consent.may_drive('somebody_new'))
        self.consent.ask('somebody_new')
        self.assertEqual(self.asked, [])
        self.dialog.toggle_selected()                  # deny -> ask
        self.assertEqual(self.consent.new_client_policy(), 'ask')

    def test_announcing_can_be_switched_off(self):
        from src.titan_core.actions import bus
        said = []
        saved = bus.threading.Thread
        def record(target=None, **k):
            if getattr(target, '__name__', '') == 'say':
                said.append(target)
                return type('T', (), {'start': lambda _s: None})()
            return saved(target=target, **k)
        bus.threading.Thread = record
        peer = type('P', (), {'addon_id': 'zz_client', 'client': True,
                              'kind': 'app', 'actions': [], 'label': 'Z'})()
        try:
            self._open_tab()
            self._select(self.clients.ANNOUNCE_ROW)
            self.dialog.toggle_selected()
            self.assertFalse(self.consent.announce_clients())
            bus._announced.clear()
            bus._announce_client(peer, True)
            self.assertEqual(said, [])
            self.consent.set_announce_clients(True)
            bus._announced.clear()
            bus._announce_client(peer, True)
            self.assertEqual(len(said), 1)
        finally:
            bus.threading.Thread = saved

    def test_the_refusal_points_at_the_tab(self):
        text = self.consent.refusal('nvda', 'NVDA')
        self.assertNotIn('Settings, General', text)
        self.assertIn('NVDA', text)


class TheActions(unittest.TestCase):
    def setUp(self):
        _reset()
        _user_addon('applications', 'zz_test_app', '__app.TCE',
                    'name_en="Test app"\nname_pl="Testowa"\nopenfile="x.py"\n')

    def test_list_switch_and_say(self):
        from src.titan_core import modules_actions as acts
        self.assertIn('telegram', acts.list_modules(kind='service'))
        self.assertIn('now off', acts.disable_module(name='zz_test_app'))
        self.assertIn('is off', acts.module_status(name='zz_test_app'))
        self.assertIn('already off', acts.disable_module(name='zz_test_app'))
        self.assertIn('now on', acts.enable_module(name='zz_test_app', kind='app'))
        self.assertIn('no kind', acts.list_modules(kind='nonsense'))
        self.assertIn('no module', acts.module_status(name='zzz_nothing_like_it'))

    def test_the_provider_is_registered(self):
        from src.titan_core import actions
        actions.invalidate()
        addon = actions.find_addon('modules')
        self.assertIsNotNone(addon)
        self.assertEqual({a.name for a in addon.actions},
                         {'list_modules', 'module_status', 'enable_module',
                          'disable_module', 'pending_changes', 'open_manager',
                          'restart_titan'})


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(_HOME, ignore_errors=True)

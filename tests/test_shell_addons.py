# -*- coding: utf-8 -*-
"""Shell add-ons: discovery, contribution, and the two providers.

Run it directly (`python tests/test_shell_addons.py`) - `tests/` has no
`__init__.py`.

Nothing here starts the shell.  The point of the add-on layer is that it is
asked for contributions by whichever surface is being built, so the surfaces
are stood in for and what is tested is the layer itself: that a manifest is
read the way the file says, that a broken add-on cannot take a menu down,
and that a provider only wins when the user has chosen it.
"""

import os
import sys
import types
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import wx                                                        # noqa: E402

from src.shell import addons                                     # noqa: E402

_app = wx.App(False)


def _fake_addon(manager, addon_id='fake', module=None, **manifest):
    """An add-on with no folder: a config, a module and an API object."""
    config = addons.ShellAddonConfig.__new__(addons.ShellAddonConfig)
    config.path = manifest.get('path', ROOT)
    config.id = addon_id
    config.name = manifest.get('name', addon_id)
    config.description = manifest.get('description', '')
    config.author = ''
    config.version = '1.0'
    config.status = manifest.get('status', 0)
    config.surfaces = tuple(manifest.get('surfaces', ()))
    config.provides = manifest.get('provides', '')
    config.libs = []
    config.error = ''
    api = addons.ShellAddonAPI(config, manager)
    addon = addons.ShellAddon(config, module or types.ModuleType(addon_id),
                              api)
    manager._configs[addon_id] = config
    manager._scanned = True
    manager._loaded[addon_id] = addon
    return addon


class ManifestTests(unittest.TestCase):
    """`__shell_addon__.TCE`, as the file says."""

    def test_the_examples_are_found(self):
        found = {config.id for config in addons.manager().configs()}
        self.assertIn('example_shell_addon', found)
        self.assertIn('simple_start_menu', found)

    def test_the_examples_ship_switched_off(self):
        # An add-on that changed the user's shell the moment it was
        # unpacked would be a shell nobody asked for.
        for addon_id in ('example_shell_addon', 'simple_start_menu'):
            self.assertFalse(addons.manager().config(addon_id).enabled,
                             f"{addon_id} should ship disabled")

    def test_surfaces_and_provides_are_read(self):
        example = addons.manager().config('example_shell_addon')
        self.assertIn('taskbar', example.surfaces)
        self.assertEqual('', example.provides)
        menu = addons.manager().config('simple_start_menu')
        self.assertEqual('start_menu', menu.provides)

    def test_an_addon_with_no_surfaces_is_asked_about_everything(self):
        config = addons.ShellAddonConfig.__new__(addons.ShellAddonConfig)
        config.surfaces = ()
        self.assertTrue(config.touches('explorer'))
        config.surfaces = ('desktop',)
        self.assertFalse(config.touches('explorer'))
        self.assertTrue(config.touches('desktop'))


class ContributionTests(unittest.TestCase):
    """What `collect` accepts, refuses and survives."""

    def setUp(self):
        self.manager = addons.ShellAddonManager()
        self.manager._scanned = True

    def test_entries_are_stamped_with_their_addon(self):
        module = types.ModuleType('m')
        module.desktop_menu_items = lambda api, *rest: [
            {'id': 'one', 'label': "One", 'action': lambda: None}]
        _fake_addon(self.manager, 'a', module, name="Add-on A")
        entries = self.manager.collect('desktop', 'desktop_menu_items', None)
        self.assertEqual(1, len(entries))
        self.assertEqual('a', entries[0]['addon'])
        self.assertEqual("Add-on A", entries[0]['addon_name'])

    def test_a_nameless_or_inert_entry_is_dropped(self):
        module = types.ModuleType('m')
        module.desktop_menu_items = lambda api, *rest: [
            {'id': 'no_label', 'action': lambda: None},
            {'id': 'no_action', 'label': "Nothing happens"},
            {'id': 'fine', 'label': "Fine", 'action': lambda: None},
        ]
        _fake_addon(self.manager, 'a', module)
        entries = self.manager.collect('desktop', 'desktop_menu_items', None)
        self.assertEqual(['fine'], [entry['id'] for entry in entries])

    def test_a_control_needs_no_action(self):
        # A taskbar band is its own evidence that it is real.
        module = types.ModuleType('m')
        module.taskbar_bands = lambda api, bar: [
            {'id': 'band', 'label': "Band", 'control': lambda parent: None}]
        _fake_addon(self.manager, 'a', module)
        self.assertEqual(1, len(self.manager.collect('taskbar',
                                                     'taskbar_bands', None)))

    def test_an_addon_that_raises_contributes_nothing_and_does_not_escape(self):
        def explode(api, *rest):
            raise RuntimeError("boom")

        module = types.ModuleType('m')
        module.desktop_menu_items = explode
        _fake_addon(self.manager, 'bad', module)

        good = types.ModuleType('g')
        good.desktop_menu_items = lambda api, *rest: [
            {'id': 'ok', 'label': "OK", 'action': lambda: None}]
        _fake_addon(self.manager, 'good', good)

        entries = self.manager.collect('desktop', 'desktop_menu_items', None)
        self.assertEqual(['ok'], [entry['id'] for entry in entries])

    def test_an_addon_answering_rubbish_contributes_nothing(self):
        module = types.ModuleType('m')
        module.desktop_menu_items = lambda api, *rest: "not a list"
        _fake_addon(self.manager, 'a', module)
        self.assertEqual([], self.manager.collect('desktop',
                                                  'desktop_menu_items', None))

    def test_a_disabled_addon_is_not_asked(self):
        module = types.ModuleType('m')
        module.desktop_menu_items = lambda api, *rest: [
            {'id': 'x', 'label': "X", 'action': lambda: None}]
        _fake_addon(self.manager, 'off', module, status=1)
        self.assertEqual([], self.manager.collect('desktop',
                                                  'desktop_menu_items', None))

    def test_only_the_addons_that_touch_a_surface_are_asked(self):
        asked = []

        def items(api, *rest):
            asked.append(api.id)
            return []

        module = types.ModuleType('m')
        module.explorer_menu_items = items
        _fake_addon(self.manager, 'desktop_only', module,
                    surfaces=('desktop',))
        _fake_addon(self.manager, 'everywhere', module)
        self.manager.collect('explorer', 'explorer_menu_items', None)
        self.assertEqual(['everywhere'], asked)


class MenuTests(unittest.TestCase):
    """`add_to_menu`: the one place contributed entries reach a wx.Menu."""

    def test_entries_are_appended_behind_a_separator(self):
        menu = wx.Menu()
        menu.Append(wx.ID_ANY, "Titan's own")
        added = addons.add_to_menu(menu, [
            {'id': 'a', 'label': "Theirs", 'action': lambda: None,
             'addon': 'x'}])
        self.assertEqual(1, added)
        # Titan's entry, a separator, then theirs.
        self.assertEqual(3, menu.GetMenuItemCount())

    def test_nothing_is_added_for_no_entries(self):
        menu = wx.Menu()
        menu.Append(wx.ID_ANY, "Titan's own")
        self.assertEqual(0, addons.add_to_menu(menu, []))
        self.assertEqual(1, menu.GetMenuItemCount())


class ProviderTests(unittest.TestCase):
    """A provider replaces a part of the shell - once it is chosen."""

    def setUp(self):
        self.manager = addons.ShellAddonManager()
        self.manager._scanned = True
        module = types.ModuleType('m')
        module.open_start_menu = lambda api, parent: object()
        self.module = module

    def _chosen(self, value):
        from src.settings import settings as settings_module
        original = settings_module.get_setting

        def fake(key, default=None, section='general'):
            if key == 'provider_start_menu' and section == 'titan_shell':
                return value
            return original(key, default, section)

        settings_module.get_setting = fake
        self.addCleanup(setattr, settings_module, 'get_setting', original)

    def test_the_first_one_wins_when_nothing_is_chosen(self):
        self._chosen('')
        _fake_addon(self.manager, 'theirs', self.module,
                    provides='start_menu')
        self.assertEqual('theirs', self.manager.provider('start_menu').id)

    def test_the_chosen_one_wins(self):
        self._chosen('second')
        _fake_addon(self.manager, 'first', self.module, provides='start_menu')
        _fake_addon(self.manager, 'second', self.module,
                    provides='start_menu')
        self.assertEqual('second', self.manager.provider('start_menu').id)

    def test_a_chosen_addon_that_has_gone_means_titans_own(self):
        # Never silently promote a different add-on to "your Start menu".
        self._chosen('uninstalled')
        _fake_addon(self.manager, 'other', self.module, provides='start_menu')
        self.assertIsNone(self.manager.provider('start_menu'))

    def test_a_claim_without_the_function_is_not_a_provider(self):
        self._chosen('')
        _fake_addon(self.manager, 'claims', types.ModuleType('empty'),
                    provides='start_menu')
        self.assertIsNone(self.manager.provider('start_menu'))

    def test_only_the_parts_that_can_be_replaced(self):
        self._chosen('')
        _fake_addon(self.manager, 'a', self.module, provides='taskbar')
        self.assertIsNone(self.manager.provider('taskbar'))

    def test_providers_lists_them_for_the_properties_sheet(self):
        self._chosen('')
        _fake_addon(self.manager, 'theirs', self.module,
                    provides='start_menu', name="Theirs")
        listed = self.manager.providers('start_menu')
        self.assertEqual(['Theirs'], [config.name for config in listed])


class ShellIntegrationTests(unittest.TestCase):
    """The surfaces really do ask, and the wiring is where it says."""

    def test_the_shell_asks_before_it_builds_its_own_start_menu(self):
        import inspect
        from src.shell import shell_manager
        source = inspect.getsource(shell_manager.TitanShell.get_start_menu)
        self.assertIn('_addon_start_menu', source)

    def test_the_start_menu_is_only_replaced_when_it_was_chosen(self):
        import inspect
        from src.shell import shell_manager
        source = inspect.getsource(shell_manager.TitanShell._addon_start_menu)
        self.assertIn("start_menu_style", source)

    def test_the_file_browser_asks_before_it_opens_its_own(self):
        import inspect
        from src.shell import explorer
        self.assertIn('_addon_explorer',
                      inspect.getsource(explorer.open_explorer))

    def test_every_surface_is_wired(self):
        """Each surface's hook is called somewhere in the shell."""
        import inspect
        from src.shell import desktop, explorer, taskbar
        from src.ui import start_menu_content
        wiring = {
            'desktop_menu_items': desktop,
            'explorer_menu_items': explorer,
            'explorer_context_items': explorer,
            'explorer_toolbar_items': explorer,
            'explorer_columns': explorer,
            'taskbar_bands': taskbar,
            'taskbar_menu_items': taskbar,
            'start_menu_items': start_menu_content,
        }
        for hook, module in wiring.items():
            self.assertIn(hook, inspect.getsource(module),
                          f"{hook} is not asked for anywhere")


class StartMenuContentTests(unittest.TestCase):
    """Contributed entries become Start menu entries, on both menus."""

    def setUp(self):
        self.manager = addons.ShellAddonManager()
        self.manager._scanned = True
        self._real = addons._manager
        addons._manager = self.manager
        self.addCleanup(setattr, addons, '_manager', self._real)

    def _content(self):
        from src.ui.start_menu_content import StartMenuContent
        return StartMenuContent()

    def test_an_entry_becomes_an_action_and_a_branch_becomes_a_folder(self):
        module = types.ModuleType('m')
        module.start_menu_items = lambda api, menu: [
            {'id': 'one', 'label': "One", 'action': lambda: None},
            {'id': 'many', 'label': "Many", 'children': [
                {'id': 'child', 'label': "Child", 'action': lambda: None}]},
        ]
        _fake_addon(self.manager, 'a', module)
        entries = self._content().addon_entries()
        self.assertEqual(['addon', 'folder'],
                         [entry.kind for entry in entries])
        self.assertEqual(["One", "Many"], [entry.label for entry in entries])

    def test_a_branch_fills_itself_when_it_is_opened(self):
        from src.ui.start_menu_content import StartMenuContent
        module = types.ModuleType('m')
        module.start_menu_items = lambda api, menu: [
            {'id': 'many', 'label': "Many", 'children': lambda: [
                {'id': 'child', 'label': "Child", 'action': lambda: None}]}]
        _fake_addon(self.manager, 'a', module)
        content = self._content()
        branch = content.addon_entries()[0]
        children = StartMenuContent._children_of(content, branch)
        self.assertEqual(["Child"], [child.label for child in children])

    def test_children_that_are_not_entries_are_dropped(self):
        from src.ui.start_menu_content import StartMenuContent
        module = types.ModuleType('m')
        module.start_menu_items = lambda api, menu: [
            {'id': 'many', 'label': "Many", 'children': [
                "not a dict", {'label': "No action"},
                {'label': "Real", 'action': lambda: None}]}]
        _fake_addon(self.manager, 'a', module)
        content = self._content()
        children = StartMenuContent._children_of(content,
                                                 content.addon_entries()[0])
        self.assertEqual(["Real"], [child.label for child in children])


class HookTableTests(unittest.TestCase):
    """`addons.HOOKS` has to say what the shell really asks for.

    The table is not decoration: it is what the AI creation kit teaches and
    what it checks a generated add-on against, so a hook renamed in the shell
    and not here would produce add-ons that pass every check and do nothing.
    So the surfaces' own source is read - every `collect(...)` / `notify(...)`
    and every `hook('...')` call - and compared with the table, name by name
    and argument by argument.
    """

    @staticmethod
    def _asked_for():
        """{hook name: how many arguments it is called with}, from the source."""
        import ast
        found = {}
        roots = [os.path.join(ROOT, 'src', 'shell')]
        files = [os.path.join(ROOT, 'src', 'ui', 'start_menu_content.py')]
        for root in roots:
            for name in sorted(os.listdir(root)):
                if name.endswith('.py'):
                    files.append(os.path.join(root, name))
        for path in files:
            try:
                with open(path, encoding='utf-8') as handle:
                    tree = ast.parse(handle.read(), filename=path)
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                # shell_addons.collect('surface', 'hook', extra...)
                if isinstance(func, ast.Attribute) and func.attr in ('collect',
                                                                     'notify'):
                    if len(node.args) >= 2 and all(
                            isinstance(a, ast.Constant) for a in node.args[:2]):
                        hook = node.args[1].value
                        found[hook] = 1 + len(node.args) - 2
                # addon.hook('open_start_menu')(addon.api, ...)
                if isinstance(func, ast.Call) and isinstance(func.func,
                                                             ast.Attribute) \
                        and func.func.attr == 'hook' and func.args \
                        and isinstance(func.args[0], ast.Constant):
                    found[func.args[0].value] = len(node.args)
        return found

    def test_every_hook_in_the_table_is_really_asked_for(self):
        asked = self._asked_for()
        # `setup` and `teardown` are called by the manager itself rather than
        # by a surface, so they are looked for where they are called from.
        with open(os.path.join(ROOT, 'src', 'shell', 'addons.py'),
                  encoding='utf-8') as handle:
            manager_source = handle.read()
        for name in sorted(addons.ALL_HOOKS):
            if name in asked:
                continue
            self.assertIn(f"hook('{name}')", manager_source,
                          f"{name} is in the table but nothing asks for it")

    def test_the_documented_signatures_match_the_calls(self):
        asked = self._asked_for()
        for name, count in sorted(asked.items()):
            if name not in addons.HOOK_ARGS:
                self.fail(f"{name} is asked for but is not in addons.HOOKS")
            self.assertEqual(addons.HOOK_ARGS[name], count,
                             f"{name} is documented as taking "
                             f"{addons.HOOK_ARGS[name]} arguments and called "
                             f"with {count}")

    def test_the_reference_add_on_matches_the_table(self):
        """The example is the shape every generated add-on is grown from."""
        import ast
        path = os.path.join(ROOT, 'data', 'shell addons',
                            'example_shell_addon', 'init.py')
        with open(path, encoding='utf-8') as handle:
            tree = ast.parse(handle.read(), filename=path)
        defined = {node.name: len(node.args.args) for node in tree.body
                   if isinstance(node, ast.FunctionDef)}
        for name, count in defined.items():
            if name.startswith('_'):
                continue
            self.assertIn(name, addons.ALL_HOOKS,
                          f"the example defines {name}, which Titan never calls")
            self.assertEqual(addons.HOOK_ARGS[name], count,
                             f"the example's {name} takes {count} arguments")

    def test_the_manifest_keys_are_the_ones_that_are_read(self):
        """Every key in the table is read by the parser, and vice versa."""
        with open(os.path.join(ROOT, 'src', 'shell', 'addons.py'),
                  encoding='utf-8') as handle:
            source = handle.read()
        body = source.split('def _parse(self):')[1].split('\n    @property')[0]
        for key in addons.MANIFEST_KEYS:
            self.assertIn(f"'{key}'", body,
                          f"{key} is offered to add-on authors but never read")


if __name__ == '__main__':
    unittest.main(verbosity=2)

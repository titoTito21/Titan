# -*- coding: utf-8 -*-
"""The AI creation kit writing shell add-ons and settings interfaces.

Run it directly (`python tests/test_creation_kit_kinds.py`) - `tests/` has no
`__init__.py`.

Nothing here talks to a model. What is being tested is the part that decides
whether a generated add-on is real: the kit is grounded on the two guides, its
prompt is written out of Titan's own live tables, and its static check refuses
every shape of invention a model actually produces - a hook whose name is
almost right, a hook with the wrong number of arguments, a manifest key
nobody reads, a surface that does not exist, a provider with nothing to open,
an `api.` method that was never there, and a settings interface writing the
ini file behind Titan's back.

The other half is the anti-drift half: the four add-ons Titan itself ships
must pass the same check, and every hook the kit teaches must be one the shell
really asks for.
"""

import os
import sys
import threading
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import wx                                                        # noqa: E402

from src.ai import ai_creation_kit as kit                        # noqa: E402
from src.ai import creation_check                                # noqa: E402
from src.ai import creation_docs                                 # noqa: E402
from src.settings import interfaces                              # noqa: E402
from src.shell import addons                                     # noqa: E402
from src.titan_core import titan_package                         # noqa: E402

_app = wx.App(False)

# The one test that presses Generate builds a wizard, and the wizard speaks;
# Titan's speech can go through a SAPI subprocess bridge that takes minutes.
kit._speak = lambda *_args, **_kwargs: None
kit._question_sound = lambda *_args, **_kwargs: None

# No test may put a window in front of whoever is running it. `load_project`
# reports a failure with `wx.MessageBox`, and a message box raised by a test
# run is a modal window on the user's own screen, waiting for a click that
# nobody knows to give - which is exactly what happened: a run of this file
# put "That project could not be read" on the user's desktop and looked, from
# here, like a suite that had gone slow.
MESSAGES = []


def _message_box(message, caption='', style=wx.OK, parent=None, *_a, **_k):
    MESSAGES.append((str(message), str(caption)))
    return wx.OK


wx.MessageBox = _message_box

SHELL = kit.get_kind('shell_addon')
UI = kit.get_kind('settings_interface')


def files_of(folder):
    """One shipped add-on as the kit's {relative path: content} mapping."""
    base = os.path.join(ROOT, folder)
    files = {}
    for dirpath, _dirs, names in os.walk(base):
        for name in names:
            if not name.endswith(('.py', '.TCE', '.json', '.md', '.po')):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, base).replace(os.sep, '/')
            with open(full, encoding='utf-8', errors='replace') as handle:
                files[rel] = handle.read()
    return files


class TheKindsExist(unittest.TestCase):

    def test_both_kinds_are_offered(self):
        self.assertIsNotNone(SHELL, "the kit cannot write a shell add-on")
        self.assertIsNotNone(UI, "the kit cannot write a settings interface")
        self.assertEqual('shell addons', SHELL['subdir'])
        self.assertEqual('settings interfaces', UI['subdir'])
        self.assertEqual(('__shell_addon__.TCE',), SHELL['manifests'])
        self.assertEqual(('__settings_ui__.TCE',), UI['manifests'])

    def test_they_can_be_packed_where_they_belong(self):
        """The kit's id IS the package kind, and the package kind knows the
        directory - so 'save as package' cannot put one in the wrong place."""
        for kind in (SHELL, UI):
            self.assertTrue(kind['package'])
            pkg_kind = titan_package.NAME_TO_KIND[kind['id']]
            self.assertEqual(kind['subdir'],
                             titan_package.KIND_TO_SUBDIR[pkg_kind])
            self.assertEqual('.tcd',
                             titan_package.default_extension(pkg_kind))

    def test_the_menu_lists_them(self):
        """Programmer -> AI is built from KINDS, in every interface."""
        ids = [kind['id'] for kind in kit.KINDS]
        self.assertIn('shell_addon', ids)
        self.assertIn('settings_interface', ids)


class TheModelIsGrounded(unittest.TestCase):
    """A guide it can read beats a rule it has to guess."""

    def test_each_kind_has_its_guide(self):
        for kind_id, title in (('shell_addon', 'Shell Add-on'),
                               ('settings_interface', 'Settings Interface')):
            guide = creation_docs.load_guide(kind_id)
            self.assertTrue(guide, f"{kind_id} has no guide")
            self.assertIn(title, guide.splitlines()[0])
            block = creation_docs.build_docs_block(kind_id)
            self.assertIn(title, block)
            # The shared references travel with it.
            self.assertIn('Titan Core API Reference', block)

    def test_the_prompt_is_written_from_titans_own_tables(self):
        prompt = kit.build_system_prompt(SHELL)
        for name in addons.ALL_HOOKS:
            self.assertIn(name, prompt, f"{name} is not taught")
        for surface in addons.SURFACES:
            self.assertIn(surface, prompt)
        # Every hook is shown with its real signature, not a made-up one.
        self.assertIn('desktop_menu_items(api, desktop, where, entry)', prompt)
        self.assertIn('api.run_action', prompt)
        # And nothing that does not exist is mentioned.
        for invented in ('start_menu_entries', 'on_taskbar_start',
                         'api.get_windows'):
            self.assertNotIn(invented, prompt)

    def test_the_settings_prompt_names_the_real_contract(self):
        prompt = kit.build_system_prompt(UI)
        self.assertIn('open_settings(api)', prompt)
        self.assertIn('api.categories()', prompt)
        self.assertIn('api.save()', prompt)
        self.assertIn('CheckList', prompt)
        for kind_name in ('bool', 'choice', 'multi', 'secret'):
            self.assertIn(kind_name, prompt)


class WhatTitanShipsPasses(unittest.TestCase):
    """The check is measured against the add-ons that really work.

    This is the anti-drift test: change a hook name, an API method or a
    manifest key in Titan and the reference add-ons stop passing here long
    before a user's generated one does.
    """

    def test_the_reference_shell_addons(self):
        for folder in ('data/shell addons/example_shell_addon',
                       'data/shell addons/simple_start_menu'):
            with self.subTest(folder=folder):
                self.assertEqual([], kit.static_check(files_of(folder), SHELL))

    def test_the_reference_settings_interfaces(self):
        for folder in ('data/settings interfaces/console_settings',
                       'data/settings interfaces/html_settings'):
            with self.subTest(folder=folder):
                self.assertEqual([], kit.static_check(files_of(folder), UI))

    def test_a_kind_with_no_hook_contract_still_gets_the_generic_checks(self):
        """There is no unchecked kind any more.

        Only shell add-ons and settings interfaces have a hook contract to
        check, but every kind is read for invented imports, attributes,
        actions, emoji and manifest keys - and with no kind given at all, the
        kind-independent ones still apply.
        """
        good = {'__app.TCE': 'name_en="X"\nopenfile="main.py"\nshortname="x"\n',
                'main.py': "x = 1\n"}
        self.assertEqual([], kit.static_check(good, kit.get_kind('app')))
        self.assertEqual([], kit.static_check(good))

        invented = dict(good)
        invented['main.py'] = "from src.titan_core.speech import say\n"
        self.assertTrue(kit.static_check(invented, kit.get_kind('app')))
        self.assertTrue(kit.static_check(invented))


class InventionIsRefused(unittest.TestCase):
    """Every shape of hallucination, with the message that corrects it."""

    def check(self, kind, files):
        return "\n".join(kit.static_check(files, kind))

    def shell(self, manifest_extra='', code=''):
        return {'__shell_addon__.TCE':
                "[shell addon]\nname = X\nstatus = 1\n" + manifest_extra,
                'init.py': code}

    def ui(self, manifest="[settings interface]\nname = X\nstatus = 0\n",
           code=''):
        return {'__settings_ui__.TCE': manifest, 'init.py': code}

    # -- shell add-ons ----------------------------------------------------
    def test_a_hook_that_is_almost_right(self):
        said = self.check(SHELL, self.shell(
            'surfaces = start_menu\n',
            "def start_menu_entries(api, menu):\n    return []\n"))
        self.assertIn('start_menu_entries() is not a function Titan ever '
                      'calls', said)
        self.assertIn('did you mean start_menu_items()', said)

    def test_a_hook_with_the_wrong_arguments(self):
        said = self.check(SHELL, self.shell(
            'surfaces = desktop\n',
            "def desktop_menu_items(api, desktop):\n    return []\n"))
        self.assertIn('Titan calls it with 4', said)

    def test_a_helper_of_your_own_is_fine(self):
        said = self.check(SHELL, self.shell(
            'surfaces = desktop\n',
            "def _label(entry):\n    return ''\n\n"
            "def desktop_menu_items(api, desktop, where, entry):\n"
            "    return [{'id': 'x', 'label': _label(entry),\n"
            "             'action': lambda: None}]\n"))
        self.assertEqual('', said)

    def test_an_invented_manifest_key(self):
        said = self.check(SHELL, self.shell(
            'entry = init.py\n', "def setup(api):\n    pass\n"))
        self.assertIn("'entry' is not a key Titan reads", said)

    def test_an_invented_surface(self):
        said = self.check(SHELL, self.shell(
            'surfaces = notification_area\n', "def setup(api):\n    pass\n"))
        self.assertIn("'notification_area' is not a surface", said)

    def test_a_status_that_is_a_word(self):
        said = self.check(SHELL, {
            '__shell_addon__.TCE': "[shell addon]\nname = X\nstatus = on\n",
            'init.py': "def setup(api):\n    pass\n"})
        self.assertIn('status must be 0 or 1', said)

    def test_a_provider_with_nothing_to_open(self):
        said = self.check(SHELL, self.shell(
            'provides = start_menu\n',
            "def start_menu_items(api, menu):\n    return []\n"))
        self.assertIn('open_start_menu() must be defined', said)

    def test_providing_something_that_is_not_providable(self):
        said = self.check(SHELL, self.shell(
            'provides = taskbar\n', "def setup(api):\n    pass\n"))
        self.assertIn('can only provide', said)

    def test_an_api_method_that_never_existed(self):
        said = self.check(SHELL, self.shell(
            '', "def taskbar_menu_items(api, taskbar):\n"
                "    api.get_windows()\n    return []\n"))
        self.assertIn('api.get_windows does not exist', said)

    def test_the_api_it_really_has_is_accepted(self):
        said = self.check(SHELL, self.shell(
            '', "def start_menu_items(api, menu):\n"
                "    api.log(api.id + api.path)\n"
                "    api.run_action('titan', 'open_settings')\n"
                "    return [{'id': 'a', 'label': 'A',\n"
                "             'action': lambda: api.speak('hi')}]\n"))
        self.assertEqual('', said)

    def test_an_add_on_that_would_do_nothing(self):
        said = self.check(SHELL, self.shell('', "def main():\n    pass\n"))
        self.assertIn("not one of Titan's hooks is defined", said)

    def test_a_missing_manifest_says_its_real_name(self):
        said = self.check(SHELL, {'init.py': "def setup(api):\n    pass\n"})
        self.assertIn('__shell_addon__.TCE is missing', said)

    def test_a_missing_init_says_so(self):
        said = self.check(SHELL, {
            '__shell_addon__.TCE': "[shell addon]\nname = X\nstatus = 1\n"})
        self.assertIn('init.py is missing', said)

    # -- settings interfaces ----------------------------------------------
    def test_the_entry_point_is_the_whole_contract(self):
        said = self.check(UI, self.ui(
            code="def show_settings(api):\n    return None\n"))
        self.assertIn('open_settings(api) is missing', said)
        self.assertIn('show_settings() is not it', said)

    def test_the_entry_point_takes_one_argument(self):
        said = self.check(UI, self.ui(
            code="def open_settings(api, parent):\n    return None\n"))
        self.assertIn('exactly one', said)

    def test_writing_the_ini_file_itself(self):
        said = self.check(UI, self.ui(
            code="from src.settings.settings import set_setting\n"
                 "def open_settings(api):\n"
                 "    set_setting('a', 'b')\n    return True\n"))
        self.assertIn("behind Titan's back", said)
        self.assertIn('api.save()', said)

    def test_an_invented_settings_api(self):
        said = self.check(UI, self.ui(
            code="def open_settings(api):\n"
                 "    api.get_categories()\n    return True\n"))
        self.assertIn('api.get_categories does not exist', said)
        self.assertIn('did you mean api.categories', said)

    def test_the_wrong_section_heading(self):
        said = self.check(UI, self.ui(
            manifest="[settings_interface]\nname = X\nstatus = 0\n",
            code="def open_settings(api):\n    return True\n"))
        self.assertIn('there is no [settings interface] section', said)

    def test_a_real_interface_shape_passes(self):
        said = self.check(UI, self.ui(
            code="def open_settings(api):\n"
                 "    for category in api.categories():\n"
                 "        for item in category['items']:\n"
                 "            api.set(item['id'], item['value'])\n"
                 "    api.save()\n"
                 "    return True\n"))
        self.assertEqual('', said)


class NothingIsInvented(unittest.TestCase):
    """The checks that apply to EVERY kind (`src/ai/creation_check.py`).

    A model does not usually write broken Python; it writes plausible Python
    that names things Titan does not have - `from src.titan_core.speech
    import say`, `sound.play_notification(...)`, an action that reads like
    one. All of it imports cleanly and does nothing, so all of it is checked
    against the real source tree and the live action registry.
    """

    def check(self, files, kind=None):
        return "\n".join(creation_check.check_everything(files, kind))

    def test_a_module_that_does_not_exist(self):
        said = self.check({'init.py': "from src.titan_core.speech import say\n"})
        self.assertIn('there is no module src.titan_core.speech', said)

    def test_a_name_that_module_does_not_have(self):
        said = self.check(
            {'init.py': "from src.titan_core.sound import play_notification\n"})
        self.assertIn('src.titan_core.sound has no play_notification', said)

    def test_the_real_helpers_are_accepted(self):
        said = self.check({'init.py':
                           "from src.accessibility.messages import "
                           "speak_sr_only\n"
                           "from src.titan_core.sound import play_sound\n"
                           "from src.settings.settings import get_setting\n"
                           "from src.titan_core import actions\n"})
        self.assertEqual('', said)

    def test_an_attribute_read_off_a_titan_module(self):
        said = self.check({'init.py':
                           "from src.titan_core import sound\n"
                           "def go():\n"
                           "    sound.play_notification('x')\n"})
        self.assertIn('src.titan_core.sound has no play_notification', said)

    def test_a_local_name_may_shadow_a_module(self):
        """`actions = []` then `actions.append(...)` is a list, not Titan."""
        said = self.check({'init.py':
                           "from src.titan_core import actions\n"
                           "def go():\n"
                           "    actions = []\n"
                           "    actions.append(1)\n"
                           "    return actions\n"})
        self.assertEqual('', said)

    def test_an_action_that_does_not_exist(self):
        said = self.check({'init.py':
                           "from src.titan_core import actions\n"
                           "def go():\n"
                           "    actions.run('titan', 'open_the_settings')\n"})
        self.assertIn("titan has no action 'open_the_settings'", said)
        self.assertIn('did you mean open_settings', said)

    def test_a_real_action_is_accepted(self):
        said = self.check({'init.py':
                           "from src.titan_core import actions\n"
                           "def go():\n"
                           "    actions.run('titan', 'open_settings')\n"
                           "    actions.run('shell', 'show_desktop')\n"})
        self.assertEqual('', said)

    def test_an_add_on_of_the_users_own_is_not_second_guessed(self):
        """Only Titan's own providers are known to be installed."""
        said = self.check({'init.py':
                           "from src.titan_core import actions\n"
                           "def go():\n"
                           "    actions.run('tedit', 'whatever_it_offers')\n"})
        self.assertEqual('', said)

    def test_an_emoji_in_the_text(self):
        said = self.check({'init.py': "TITLE = 'Ready \U0001F600'\n"})
        self.assertIn('emoji', said)

    def test_an_arrow_is_not_an_emoji(self):
        """Titan's own apps write "File -> Settings" with a real arrow."""
        said = self.check({'init.py': "HELP = 'File \u2192 Settings'\n"
                                      "# a star \u2606 in a comment\n"})
        self.assertEqual('', said)

    def test_a_manifest_key_nobody_reads(self):
        said = self.check(
            {'__component__.TCE': "[component]\nname = X\nstatus = 0\n"
                                  "entry_point = init.py\n",
             'init.py': "def add_menu(menu, frame):\n    pass\n"},
            kit.get_kind('component'))
        self.assertIn("'entry_point' is not a key Titan reads", said)

    def test_a_section_in_a_manifest_that_has_none(self):
        """`__app.TCE` is a plain list of key = value lines."""
        said = self.check(
            {'__app.TCE': '[app]\nname_en="X"\nopenfile="main.py"\n'
                          'shortname="x"\n',
             'main.py': "x = 1\n"},
            kit.get_kind('app'))
        self.assertIn('plain list of key = value lines', said)

    def test_a_real_app_manifest_passes(self):
        said = self.check(
            {'__app.TCE': 'name_pl="X"\nname_en="X"\ndescription=""\n'
                          'openfile="main.py"\nshortname="x"\n',
             'main.py': "x = 1\n"},
            kit.get_kind('app'))
        self.assertEqual('', said)


class EverythingTitanShipsPassesTheGenericChecks(unittest.TestCase):
    """The false-positive guard, and the reason the checks can be trusted.

    Every add-on in `data/` is real, working code. If a check reports one of
    them, the check is wrong - and a wrong report is the expensive kind of
    mistake here, because the auto-fix loop would ask the model to "correct"
    something that was already right.
    """

    SKIP = {'lib', 'vendor', '__pycache__', 'languages', 'node_modules'}

    def _files(self, folder):
        files = {}
        for dirpath, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in self.SKIP]
            for name in names:
                if not name.endswith(('.py', '.TCE', '.json')):
                    continue
                full = os.path.join(dirpath, name)
                if os.path.getsize(full) > 400000:
                    continue
                rel = os.path.relpath(full, folder).replace(os.sep, '/')
                with open(full, encoding='utf-8', errors='replace') as handle:
                    files[rel] = handle.read()
        return files

    def test_no_shipped_add_on_is_refused(self):
        reported = {}
        checked = 0
        for kind in kit.KINDS:
            subdir = kind.get('subdir')
            if not subdir:
                continue
            root = os.path.join(ROOT, 'data', subdir)
            if not os.path.isdir(root):
                continue
            for name in sorted(os.listdir(root)):
                folder = os.path.join(root, name)
                if not os.path.isdir(folder):
                    continue
                files = self._files(folder)
                if not files:
                    continue
                checked += 1
                problems = [problem for problem
                            in creation_check.check_everything(files, kind)
                            # data/components/macros has a real dead import
                            # (`from src.titan_core.sound import speaker`) in
                            # a fallback branch - a true positive, kept out
                            # of this sweep rather than pretended away.
                            if 'sound has no speaker' not in problem]
                if problems:
                    reported[f"{kind['id']}/{name}"] = problems[:3]
        self.assertGreater(checked, 20, "no add-ons were checked at all")
        self.assertEqual({}, reported)


class TheWholeRunIsExercised(unittest.TestCase):
    """Generate, with the model stubbed out - including the auto-fix loop.

    Everything else in this file checks a function; this presses the button.
    It exists because the auto-fix loop is a closure inside a worker thread,
    where a name that is not defined is not a syntax error, not an import
    error and not caught by any other test here - it is a message box saying
    "name 'kind' is not defined" after the user has waited for a generation.
    """

    CANNED = ("@@FILE: __component__.TCE\n"
              "[component]\nname = Demo\nstatus = 0\n"
              "@@FILE: init.py\n"
              "from src.titan_core.sound import play_notification\n"
              "def add_menu(menu, frame):\n    pass\n")

    def setUp(self):
        import wx
        from src.ai import ai_provider
        self.frame = wx.Frame(None)
        self.addCleanup(self.frame.Destroy)
        self.calls = []
        self._ready = ai_provider.is_ai_ready
        self._generate = ai_provider.generate
        ai_provider.is_ai_ready = lambda: True

        def generate(system, messages, on_chunk=None, **kwargs):
            self.calls.append(system)
            return self.CANNED

        ai_provider.generate = generate

        def restore():
            ai_provider.is_ai_ready = self._ready
            ai_provider.generate = self._generate

        self.addCleanup(restore)

    def _run(self, kind_id='component'):
        import wx
        wizard = kit.AICreationWizardDialog(self.frame, kind_id)
        self.addCleanup(wizard.Destroy)
        wizard.ask_cb.SetValue(False)          # no questionnaire in a test
        wizard.autofix_cb.SetValue(True)       # the loop that was broken
        wizard.desc.SetValue("a demo component")
        answer = {}
        finished = threading.Event()

        def done(raw, files, note, error):
            answer.update(raw=raw, files=files, note=note, error=error)
            finished.set()

        wizard._on_done = done
        wizard.OnGenerate(None)
        deadline = time.time() + 30
        while not finished.is_set() and time.time() < deadline:
            wx.Yield()
            time.sleep(0.02)
        self.assertTrue(finished.is_set(), "the generation never finished")
        return answer, wizard

    def test_generating_does_not_raise_inside_the_worker(self):
        answer, _wizard = self._run()
        self.assertIsNone(answer['error'],
                          f"the worker failed: {answer['error']}")
        self.assertIn('init.py', answer['files'])

    def test_the_auto_fix_loop_is_told_what_the_kind_is(self):
        """The canned answer has an invented import, so the loop runs - and
        the message the model gets back has to name the real problem."""
        answer, _wizard = self._run()
        self.assertGreater(len(self.calls), 1,
                           "the auto-fix loop never ran")
        problems = kit.static_check(kit.parse_files(self.CANNED),
                                    kit.get_kind('component'))
        self.assertTrue(any('play_notification' in problem
                            for problem in problems))


class TheProblemsReachTheModel(unittest.TestCase):

    def test_the_fix_message_lists_every_problem(self):
        problems = kit.static_check(
            {'__shell_addon__.TCE': "[shell addon]\nname = X\nstatus = 1\n",
             'init.py': "def start_menu_entries(api, menu):\n    return []\n"},
            SHELL)
        message = kit.build_fix_message(problems)
        for problem in problems:
            self.assertIn(problem, message)
        self.assertIn('@@FILE', message)


if __name__ == '__main__':
    unittest.main(verbosity=2)

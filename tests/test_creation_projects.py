# -*- coding: utf-8 -*-
"""Projects, and the questions a complicated add-on needs asking.

Run it directly (`python tests/test_creation_projects.py`) - `tests/` has no
`__init__.py`. Nothing here talks to a model.

Two features are being tested, and they exist for the same reason: an
application, a component or a launcher is not built in one round trip. The
form has to be able to ask fifteen questions without becoming unreadable
(sections, help, follow-ups, real controls), and the session has to survive
the dialog being closed (`src/ai/creation_project.py`).

Every project written here is written under a name of its own and deleted
again, so the user's real projects are never touched.
"""

import json
import os
import shutil
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import wx                                                        # noqa: E402

from src.ai import ai_creation_kit as kit                        # noqa: E402
from src.ai import creation_project                              # noqa: E402

_app = wx.App(False)

# Nothing here speaks or plays anything. Titan's own speech may go through a
# SAPI subprocess bridge that takes minutes to answer on a machine whose
# voice is not directly usable, and a suite that waits for a voice is a suite
# nobody runs - the same reason `test_tcs_macros.py` replaces the AI provider.
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

NAME = "__titan test project__"


def questions_from(*raw):
    return kit.parse_questions("@@QUESTIONS_JSON\n"
                               + json.dumps({'questions': list(raw)})
                               + "\n@@END_QUESTIONS_JSON")


class QuestionsCanBeComplicated(unittest.TestCase):
    """What the model may ask for, and what Titan makes of it."""

    def test_every_type_survives_parsing(self):
        questions = questions_from(
            {'id': 'a', 'text': 'One line?', 'type': 'text'},
            {'id': 'b', 'text': 'Several?', 'type': 'longtext'},
            {'id': 'c', 'text': 'Which?', 'type': 'choice',
             'options': ['X', 'Y']},
            {'id': 'd', 'text': 'Which ones?', 'type': 'multichoice',
             'options': ['X', 'Y']},
            {'id': 'e', 'text': 'Yes?', 'type': 'boolean'},
            {'id': 'f', 'text': 'How many?', 'type': 'number',
             'minimum': 2, 'maximum': 9},
            {'id': 'g', 'text': 'Which file?', 'type': 'path'},
            {'id': 'h', 'text': 'Which folder?', 'type': 'folder'})
        self.assertEqual(['text', 'longtext', 'choice', 'multichoice',
                          'boolean', 'number', 'path', 'folder'],
                         [question['type'] for question in questions])
        self.assertEqual((2, 9), (questions[5]['minimum'],
                                  questions[5]['maximum']))
        self.assertTrue(questions[1]['multiline'])

    def test_a_type_nobody_has_becomes_a_text_field(self):
        questions = questions_from({'id': 'a', 'text': 'Hm?',
                                    'type': 'telepathy'})
        self.assertEqual('text', questions[0]['type'])

    def test_a_backwards_range_is_put_the_right_way_round(self):
        questions = questions_from({'id': 'a', 'text': 'How many?',
                                    'type': 'number', 'minimum': 9,
                                    'maximum': 2})
        self.assertEqual((2, 9), (questions[0]['minimum'],
                                  questions[0]['maximum']))

    def test_sections_keep_their_order(self):
        questions = questions_from(
            {'id': 'a', 'text': 'A?', 'section': 'Names'},
            {'id': 'b', 'text': 'B?', 'section': 'Behaviour'},
            {'id': 'c', 'text': 'C?', 'section': 'Names'},
            {'id': 'd', 'text': 'D?'})
        sections = kit.question_sections(questions)
        self.assertEqual(['Names', 'Behaviour', ''],
                         [name for name, _group in sections])
        self.assertEqual(['a', 'c'], [q['id'] for q in sections[0][1]])

    def test_a_follow_up_waits_for_its_answer(self):
        questions = questions_from(
            {'id': 'layout', 'text': 'Which?', 'type': 'choice',
             'options': ['List', 'Grid']},
            {'id': 'columns', 'text': 'How many?', 'type': 'number',
             'depends_on': 'layout', 'depends_value': 'Grid'})
        follower = questions[1]
        self.assertFalse(kit.question_applies(follower, {}))
        self.assertFalse(kit.question_applies(follower, {'layout': 'List'}))
        self.assertTrue(kit.question_applies(follower, {'layout': 'Grid'}))

    def test_a_follow_up_on_a_tick_box(self):
        questions = questions_from(
            {'id': 'sound', 'text': 'Sounds?', 'type': 'boolean'},
            {'id': 'which', 'text': 'Which sound?', 'depends_on': 'sound'})
        self.assertTrue(kit.question_applies(questions[1], {'sound': 'Yes'}))
        self.assertFalse(kit.question_applies(questions[1], {'sound': 'No'}))

    def test_a_follow_up_on_a_question_that_is_not_there_is_dropped(self):
        """It would otherwise be a question nobody could ever see."""
        questions = questions_from(
            {'id': 'a', 'text': 'A?', 'depends_on': 'nothing_like_this'})
        self.assertEqual('', questions[0]['depends_on'])

    def test_enough_questions_for_something_real(self):
        self.assertGreaterEqual(kit._MAX_QUESTIONS, 15)


class TheFormRendersThem(unittest.TestCase):
    """The wizard is real controls, because a real control reads itself."""

    def setUp(self):
        self.frame = wx.Frame(None)
        self.addCleanup(self.frame.Destroy)

    def dialog(self, questions):
        dialog = kit.QuestionnaireDialog(self.frame, kit.get_kind('component'),
                                         questions)
        self.addCleanup(dialog.Destroy)
        return dialog

    def test_each_question_gets_the_control_it_deserves(self):
        questions = questions_from(
            {'id': 'a', 'text': 'One line?', 'type': 'text'},
            {'id': 'b', 'text': 'Several?', 'type': 'longtext'},
            {'id': 'c', 'text': 'Which?', 'type': 'choice',
             'options': ['X', 'Y']},
            {'id': 'd', 'text': 'Which ones?', 'type': 'multichoice',
             'options': ['X', 'Y']},
            {'id': 'e', 'text': 'Yes?', 'type': 'boolean'},
            {'id': 'f', 'text': 'How many?', 'type': 'number'},
            {'id': 'g', 'text': 'Which folder?', 'type': 'folder'})
        dialog = self.dialog(questions)
        controls = {qid: control
                    for qid, (_q, control) in dialog._controls.items()}
        self.assertIsInstance(controls['a'], wx.TextCtrl)
        self.assertTrue(controls['b'].GetWindowStyleFlag() & wx.TE_MULTILINE)
        self.assertIsInstance(controls['c'], wx.RadioBox)
        self.assertEqual(2, len(controls['d']))
        self.assertIsInstance(controls['e'], wx.CheckBox)
        self.assertIsInstance(controls['f'], wx.SpinCtrl)
        self.assertIsInstance(controls['g'], wx.TextCtrl)

    def test_every_control_carries_the_question_as_its_name(self):
        """It is what the screen reader says when the keyboard lands."""
        questions = questions_from(
            {'id': 'a', 'text': 'English name?'},
            {'id': 'b', 'text': 'Which?', 'type': 'choice',
             'options': ['X', 'Y']})
        dialog = self.dialog(questions)
        self.assertEqual('English name?', dialog._controls['a'][1].GetName())
        self.assertEqual('Which?', dialog._controls['b'][1].GetName())

    def test_a_follow_up_is_hidden_until_it_applies(self):
        questions = questions_from(
            {'id': 'layout', 'text': 'Which?', 'type': 'choice',
             'options': ['List', 'Grid']},
            {'id': 'columns', 'text': 'How many?', 'type': 'number',
             'depends_on': 'layout', 'depends_value': 'Grid'})
        dialog = self.dialog(questions)
        self.assertFalse(any(window.IsShown()
                             for window in dialog._rows['columns']))
        dialog._controls['layout'][1].SetSelection(1)      # Grid
        dialog._apply_conditions()
        self.assertTrue(all(window.IsShown()
                            for window in dialog._rows['columns']))

    def test_the_answers_come_back_typed_as_the_control_gives_them(self):
        questions = questions_from(
            {'id': 'name', 'text': 'Name?'},
            {'id': 'many', 'text': 'How many?', 'type': 'number',
             'minimum': 1, 'maximum': 8},
            {'id': 'which', 'text': 'Which ones?', 'type': 'multichoice',
             'options': ['X', 'Y']},
            {'id': 'on', 'text': 'On?', 'type': 'boolean'})
        dialog = self.dialog(questions)
        dialog._controls['name'][1].SetValue(" Notes ")
        dialog._controls['many'][1].SetValue(4)
        dialog._controls['which'][1][1].SetValue(True)
        dialog._controls['on'][1].SetValue(True)
        answers = dialog.current_answers()
        self.assertEqual('Notes', answers['name'])
        self.assertEqual('4', answers['many'])
        self.assertEqual(['Y'], answers['which'])
        self.assertIn(answers['on'].lower(), ('yes', 'tak'))

    def test_the_answers_reach_the_model_as_words(self):
        questions = questions_from(
            {'id': 'which', 'text': 'Which ones?', 'type': 'multichoice',
             'options': ['X', 'Y']},
            {'id': 'skip', 'text': 'Anything else?'})
        message = kit.format_answers_for_prompt(
            questions, {'which': ['X', 'Y'], 'skip': ''})
        self.assertIn('Which ones?', message)
        self.assertIn('X, Y', message)
        self.assertIn('best judgement', message)


class AProjectSurvivesTheDialog(unittest.TestCase):
    """The session on disk: description, interview, conversation, files."""

    def setUp(self):
        creation_project.delete(NAME)
        self.addCleanup(creation_project.delete, NAME)

    def save(self, **overrides):
        data = dict(
            kind_id='component', description="a notes component",
            messages=[{'role': 'user', 'content': 'make notes'},
                      {'role': 'assistant', 'content': 'ok'}],
            files={'__component__.TCE': "[component]\nname = N\nstatus = 0\n",
                   'init.py': "def add_menu(menu, frame):\n    pass\n"},
            questions=questions_from({'id': 'a', 'text': 'Name?'}),
            answers={'a': 'Notes'}, plan="1. manifest", raw="@@FILE: init.py",
            options={'web': False, 'autofix': True, 'ask': True})
        data.update(overrides)
        return creation_project.save(NAME, **data)

    def test_it_writes_the_files_as_files(self):
        folder = self.save()
        tree = os.path.join(folder, creation_project.FILES_DIR)
        self.assertTrue(os.path.isfile(os.path.join(tree, 'init.py')))
        self.assertTrue(os.path.isfile(os.path.join(folder,
                                                    creation_project.MANIFEST)))

    def test_everything_comes_back(self):
        self.save()
        data = creation_project.load(NAME)
        self.assertEqual('component', data['kind'])
        self.assertEqual("a notes component", data['description'])
        self.assertEqual(2, len(data['messages']))
        self.assertEqual({'a': 'Notes'}, data['answers'])
        self.assertEqual("1. manifest", data['plan'])
        self.assertIn('init.py', data['files'])
        self.assertIn('add_menu', data['files']['init.py'])

    def test_saving_again_does_not_leave_an_old_file_behind(self):
        self.save()
        self.save(files={'init.py': "x = 1\n"})
        data = creation_project.load(NAME)
        self.assertEqual(['init.py'], sorted(data['files']))

    def test_it_is_listed_with_what_a_chooser_needs(self):
        self.save()
        entry = next((item for item in creation_project.list_projects()
                      if item['name'] == NAME), None)
        self.assertIsNotNone(entry)
        self.assertEqual('component', entry['kind'])
        self.assertEqual(2, entry['files'])
        self.assertEqual(2, entry['turns'])
        self.assertTrue(entry['updated'])

    def test_the_created_time_is_kept_when_it_is_saved_again(self):
        self.save()
        created = creation_project.describe(NAME)['created']
        self.save(description="changed")
        self.assertEqual(created, creation_project.describe(NAME)['created'])

    def test_a_name_with_awkward_characters(self):
        awkward = 'my/add-on: "notes"?'
        self.addCleanup(creation_project.delete, awkward)
        creation_project.save(awkward, 'component')
        self.assertTrue(creation_project.exists(awkward))
        self.assertNotIn('/', os.path.basename(
            creation_project.project_path(awkward)))

    def test_opening_one_that_is_not_there(self):
        self.assertIsNone(creation_project.load("__no such project__"))
        self.assertIsNone(creation_project.describe("__no such project__"))

    def test_deleting_and_renaming(self):
        self.save()
        other = NAME + " 2"
        self.addCleanup(creation_project.delete, other)
        self.assertTrue(creation_project.rename(NAME, other))
        self.assertFalse(creation_project.exists(NAME))
        self.assertEqual(other, creation_project.load(other)['name'])
        self.assertTrue(creation_project.delete(other))

    def test_a_project_is_suggested_a_name(self):
        name = creation_project.suggest_name(
            "Component", "a notes component with reminders")
        self.assertTrue(name)
        self.assertNotIn('/', name)


class AProjectIsFoundByTheNameTheUserSees(unittest.TestCase):
    """The name in the list and the folder on disk are not the same string.

    `safe_name()` makes the folder out of what was typed, so "Zegar
    słoneczny" lives in "Zegar s_oneczny"; a project can also be renamed,
    copied in by hand or brought from another machine. Looking only where
    the name would have put it is what makes a project that is plainly
    there report "that project could not be read".
    """

    ODD = '__titan odd folder__'
    SHOWN = 'Zegar słoneczny (test)'

    def setUp(self):
        self.folder = os.path.join(creation_project.projects_root(), self.ODD)
        shutil.rmtree(self.folder, ignore_errors=True)
        os.makedirs(self.folder, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.folder, True)
        with open(os.path.join(self.folder, creation_project.MANIFEST),
                  'w', encoding='utf-8') as handle:
            json.dump({'format': 1, 'name': self.SHOWN, 'kind': 'component',
                       'files': [], 'messages': [], 'created': 'then',
                       'updated': 'now'}, handle, ensure_ascii=False)

    def test_by_the_name_it_calls_itself(self):
        data = creation_project.load(self.SHOWN)
        self.assertIsNotNone(data)
        self.assertEqual('component', data['kind'])
        self.assertEqual(self.folder, data['path'])

    def test_by_the_name_of_its_folder(self):
        self.assertIsNotNone(creation_project.load(self.ODD))

    def test_the_list_and_the_lookup_agree(self):
        """Whatever `list_projects` shows, opening it must work - that is the
        whole of the bug this guards."""
        for entry in creation_project.list_projects():
            with self.subTest(project=entry['name']):
                self.assertIsNotNone(creation_project.load(entry['name']),
                                     f"{entry['name']} is listed but does "
                                     f"not open")

    def test_it_is_described_and_exists(self):
        self.assertTrue(creation_project.exists(self.SHOWN))
        described = creation_project.describe(self.SHOWN)
        self.assertEqual(self.folder, described['path'])
        self.assertEqual(self.SHOWN, described['name'])

    def test_saving_it_again_updates_that_one(self):
        """Not a second folder beside it under a differently spelt name."""
        before = set(os.listdir(creation_project.projects_root()))
        creation_project.save(self.SHOWN, 'component', description="changed")
        after = set(os.listdir(creation_project.projects_root()))
        self.assertEqual(before, after)
        self.assertEqual("changed",
                         creation_project.load(self.SHOWN)['description'])

    def test_a_name_nobody_has(self):
        self.assertIsNone(creation_project.load('__no such project at all__'))
        self.assertFalse(creation_project.exists('__no such project at all__'))


class TheWizardCarriesOn(unittest.TestCase):
    """Reopening a project puts the whole session back in the window."""

    def setUp(self):
        self.frame = wx.Frame(None)
        self.addCleanup(self.frame.Destroy)
        creation_project.delete(NAME)
        self.addCleanup(creation_project.delete, NAME)

    def test_open_restores_files_conversation_and_options(self):
        creation_project.save(
            NAME, 'component', description="a notes component",
            messages=[{'role': 'user', 'content': 'make notes'}],
            files={'init.py': "x = 1\n",
                   '__component__.TCE': "[component]\nname = N\nstatus = 0\n"},
            plan="1. manifest", options={'web': True, 'autofix': False,
                                         'ask': False})
        wizard = kit.AICreationWizardDialog(self.frame, 'component')
        self.addCleanup(wizard.Destroy)
        self.assertTrue(wizard.load_project(NAME))
        self.assertEqual(NAME, wizard.project_name)
        self.assertEqual(2, wizard.file_list.GetCount())
        self.assertTrue(wizard.save_btn.IsEnabled())
        self.assertEqual(1, len(wizard.messages))
        self.assertTrue(wizard.web_cb.GetValue())
        self.assertFalse(wizard.autofix_cb.GetValue())
        self.assertIn(NAME, wizard.GetTitle())
        self.assertIn("a notes component", wizard.transcript.GetValue())
        self.assertIn("1. manifest", wizard.transcript.GetValue())

    def test_a_project_that_cannot_be_read_says_so_and_changes_nothing(self):
        wizard = kit.AICreationWizardDialog(self.frame, 'component')
        self.addCleanup(wizard.Destroy)
        del MESSAGES[:]
        self.assertFalse(wizard.load_project("__no such project__"))
        self.assertEqual('', wizard.project_name)
        # It says where it looked, so the user can go and see for themselves.
        self.assertTrue(MESSAGES)
        self.assertIn('ai projects', MESSAGES[0][0])

    def test_saving_a_project_from_the_wizard(self):
        wizard = kit.AICreationWizardDialog(self.frame, 'component')
        self.addCleanup(wizard.Destroy)
        wizard._first_description = "a notes component"
        wizard.generated_files = {'init.py': "x = 1\n"}
        wizard.messages = [{'role': 'user', 'content': 'make notes'}]
        self.assertTrue(wizard._store_project(NAME, quiet=True))
        data = creation_project.load(NAME)
        self.assertEqual('component', data['kind'])
        self.assertEqual({'init.py': "x = 1\n"}, data['files'])
        self.assertEqual(NAME, wizard.project_name)


class TheQuestionHasASoundOfItsOwn(unittest.TestCase):
    """`sfx/<theme>/ai/agent_question.ogg`: a question that arrives silently
    while the user is listening to something else is a question they do not
    know is there."""

    def test_the_sound_ships_and_is_found(self):
        from src.titan_core import sound
        from src.ai import ai_speech
        path = sound.ai_sound_path(ai_speech.SOUND_QUESTION)
        self.assertTrue(path, "agent_question.ogg was not found")
        self.assertTrue(os.path.isfile(path))
        self.assertEqual('ai', os.path.basename(os.path.dirname(path)))

    def test_it_is_found_with_or_without_its_folder_in_the_name(self):
        from src.titan_core import sound
        self.assertEqual(sound.ai_sound_path('agent_question.ogg'),
                         sound.ai_sound_path('ai/agent_question.ogg'))

    def test_the_users_own_theme_wins(self):
        """A theme is free to ship its own ai/ set, and then it is heard."""
        from src.titan_core import sound
        original = sound.current_theme
        try:
            sound.current_theme = 'default'
            path = sound.ai_sound_path('agent_question.ogg',
                                       allow_default=False)
        finally:
            sound.current_theme = original
        self.assertIn(os.path.join('default', 'ai'), path)

    def test_a_theme_without_it_answers_to_the_users_setting(self):
        """Settings -> Sounds -> "use equivalent from default theme". A user
        who turned that off has said they do not want sounds their theme does
        not have, and the AI does not get to overrule them."""
        from src.titan_core import sound
        original = sound.current_theme
        try:
            sound.current_theme = 'a theme that does not exist'
            self.assertEqual('', sound.ai_sound_path('agent_question.ogg',
                                                     allow_default=False))
            filled = sound.ai_sound_path('agent_question.ogg',
                                         allow_default=True)
        finally:
            sound.current_theme = original
        self.assertIn(os.path.join('default', 'ai'), filled)

    def test_the_setting_is_the_one_play_sound_reads(self):
        from src.titan_core import sound
        self.assertIn(str(sound.default_theme_fallback_allowed()),
                      ('True', 'False'))
        with open(os.path.join(ROOT, 'src', 'ui', 'settingsgui.py'),
                  encoding='utf-8') as handle:
            self.assertIn('fallback_to_default_theme', handle.read())

    def test_a_sound_that_is_not_there_is_silence_not_a_crash(self):
        from src.titan_core import sound
        self.assertEqual('', sound.ai_sound_path('no_such_sound.ogg'))

    def test_every_place_the_ai_asks_plays_it(self):
        """Four dialogs, one cue - and no old `core/` sound left behind."""
        places = {
            'src/ai/ai_creation_kit.py': '_question_sound()',
            'src/ai/ai_agent_gui.py': '_question_sound()',
            'src/ai/assistant/assistant_gui.py': '_question_sound()',
            'src/titan_core/actions/interaction.py': 'play_question_sound()',
        }
        for relative, expected in places.items():
            with open(os.path.join(ROOT, relative), encoding='utf-8') as handle:
                source = handle.read()
            self.assertIn(expected, source,
                          f"{relative} does not play the question sound")
        with open(os.path.join(ROOT, 'src', 'ai', 'ai_agent_gui.py'),
                  encoding='utf-8') as handle:
            self.assertNotIn("play_sound('core/dialog.ogg')", handle.read())

    def test_the_assistants_own_cues_go_the_same_way(self):
        """Read, not imported: importing the assistant brings the whole TTS
        stack up, which is a minute this suite is not going to spend."""
        with open(os.path.join(ROOT, 'src', 'ai', 'assistant',
                               'voice_assistant.py'), encoding='utf-8') as f:
            source = f.read()
        self.assertIn('from src.titan_core.sound import play_ai_sound as '
                      'play_sound', source)


class TheMenuKnowsAboutProjects(unittest.TestCase):

    def test_there_is_a_way_back_into_one(self):
        from src.ui import program_menu
        self.assertTrue(hasattr(program_menu, 'open_project_browser'))
        self.assertTrue(hasattr(kit, 'open_project_browser'))
        # The wizard can be opened straight onto a project.
        import inspect
        signature = inspect.signature(kit.open_creation_wizard)
        self.assertIn('project', signature.parameters)


if __name__ == '__main__':
    unittest.main(verbosity=2)

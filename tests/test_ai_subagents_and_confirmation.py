# -*- coding: utf-8 -*-
"""
The AI's confirmations, and subagents.

Reported as: "with the default settings 'confirm risky actions' keeps asking,
and the question hangs the program" - and asked for: the agent, the
assistants and AI OCR able to hand work to subagents.

Nothing here reaches a provider, opens a window or speaks: the model is a
scripted step function, the dialog is replaced, and APPDATA is a folder of
the test's own.

Run it directly: python tests/test_ai_subagents_and_confirmation.py
"""

import os
import sys
import tempfile
import threading
import time
import unittest

_HOME = tempfile.mkdtemp(prefix='titan_subagents_')
os.environ['APPDATA'] = _HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai import ai_agent, ai_provider, confirmation, subagents  # noqa: E402

# A test never speaks or plays a sound.
confirmation._say = lambda text: None
confirmation._question_sound = lambda: None


def _tool(name, run, risk='auto', **extra):
    tool = {'name': name, 'description': name, 'run': run, 'risk': risk,
            'always_confirm': False,
            'parameters': {'type': 'object', 'properties': {}, 'required': []}}
    tool.update(extra)
    return tool


class _Script(object):
    """A model: each call answers with the next planned step."""

    def __init__(self, plan):
        self.plan = plan            # callable(system, history) -> dict
        self.calls = []

    def __call__(self, model, system, history, tools, api_key):
        self.calls.append({'system': system, 'tools': [t['name'] for t in tools],
                           'history': list(history)})
        return self.plan(system, history, tools)


class _FakeProvider(object):
    def __init__(self, script):
        self.script = script

    def __enter__(self):
        self._saved = (ai_provider.get_ai_key, ai_provider.resolve_latest_model,
                       ai_provider.get_agent_confirm,
                       dict(ai_agent._STEP_FUNCS))
        ai_provider.get_ai_key = lambda provider: 'key'
        ai_provider.resolve_latest_model = lambda provider, key: 'model'
        ai_provider.get_agent_confirm = lambda: 'tiered'
        ai_agent._STEP_FUNCS['fake'] = self.script
        return self

    def __exit__(self, *exc):
        (ai_provider.get_ai_key, ai_provider.resolve_latest_model,
         ai_provider.get_agent_confirm, steps) = self._saved
        ai_agent._STEP_FUNCS.clear()
        ai_agent._STEP_FUNCS.update(steps)


def _calls_then_done(calls):
    """Call each (name, args) once, in turn, then finish."""
    def plan(system, history, tools):
        done = sum(1 for h in history if h.get('role') == 'tool')
        if done < len(calls):
            name, args = calls[done]
            return {'text': '', 'tool_calls': [
                {'id': str(done), 'name': name, 'args': args}]}
        return {'text': 'finished', 'tool_calls': []}
    return plan


class AnActionAsksOnlyWhenItIsRisky(unittest.TestCase):
    """titan_run_action is one tool for every action; it used to ask before
    every one of them, saying the time included."""

    def setUp(self):
        from src.ai import action_tools
        self.action_tools = action_tools
        self.saved = action_tools._declared_risk
        risks = {('tnotes', 'list_notes'): 'auto',
                 ('tnotes', 'delete_note'): 'confirm',
                 ('shell', 'power'): 'always_confirm'}
        action_tools._declared_risk = lambda a, n: risks.get((a, n), 'confirm')
        self.tool = [t for t in action_tools.get_action_tools()
                     if t['name'] == 'titan_run_action'][0]

    def tearDown(self):
        self.action_tools._declared_risk = self.saved

    def test_reading_is_not_asked_about(self):
        self.assertFalse(confirmation.needs_confirm(
            self.tool, {'addon': 'tnotes', 'action': 'list_notes'}))

    def test_a_risky_action_is(self):
        self.assertTrue(confirmation.needs_confirm(
            self.tool, {'addon': 'tnotes', 'action': 'delete_note'}))
        self.assertTrue(confirmation.needs_confirm(
            self.tool, {'addon': 'shell', 'action': 'power'}))

    def test_an_unknown_action_is_never_waved_through(self):
        self.assertTrue(confirmation.needs_confirm(
            self.tool, {'addon': 'nobody', 'action': 'anything'}))

    def test_confirm_every_action_still_asks_everything(self):
        self.assertTrue(confirmation.needs_confirm(
            self.tool, {'addon': 'tnotes', 'action': 'list_notes'}, True))

    def test_an_approval_is_for_that_action_only(self):
        a = confirmation.approval_key(self.tool, {'addon': 'tnotes',
                                                  'action': 'delete_note'})
        b = confirmation.approval_key(self.tool, {'addon': 'tfm',
                                                  'action': 'delete'})
        self.assertNotEqual(a, b)

    def test_a_sequence_is_as_risky_as_its_riskiest_step(self):
        seq = [t for t in self.action_tools.get_action_tools()
               if t['name'] == 'titan_run_actions'][0]
        self.assertEqual(confirmation.risk_of(seq, {'steps': [
            {'addon': 'tnotes', 'action': 'list_notes'}]}), 'auto')
        self.assertEqual(confirmation.risk_of(seq, {'steps': (
            '[{"addon": "tnotes", "action": "list_notes"},'
            ' {"addon": "tnotes", "action": "delete_note"}]')}), 'confirm')


class OrdinaryThingsDoNotAsk(unittest.TestCase):

    def test_ai_ocr_does_not_ask(self):
        from src.ai.tools.ocr_tools import get_ocr_tools
        for tool in get_ocr_tools():
            self.assertEqual(confirmation.risk_of(tool, {}), 'auto', tool['name'])

    def test_what_stays_risky_is_still_asked_about(self):
        from src.ai import agent_tools
        names = {t['name']: t for t in agent_tools.get_desktop_tools()}
        for name in ('run_shell', 'write_file', 'delete_path', 'launch_program'):
            self.assertNotEqual(confirmation.risk_of(names[name], {}), 'auto')


class AllowForThisSession(unittest.TestCase):

    def tearDown(self):
        confirmation.forget_approvals()

    def test_the_second_call_is_not_asked_again(self):
        asked = []
        script = _Script(_calls_then_done([('send', {}), ('send', {}),
                                           ('send', {})]))

        def confirm(tool, args):
            asked.append(tool['name'])
            return confirmation._settle(confirmation.SESSION, tool, args)

        sent = []
        tools = [_tool('send', lambda **a: sent.append(1) or 'sent',
                       risk='confirm')]
        with _FakeProvider(script):
            # The policy is asked by confirmation.ask; here the callback is
            # the dialog's answer, and run_agent consults approvals through
            # the real ask path below.
            answer = ai_agent.run_agent(
                'go', tools, provider='fake', remember=False,
                confirm=lambda t, a: (confirmation.is_approved(t, a)
                                      or confirm(t, a)))
        self.assertEqual(answer, 'finished')
        self.assertEqual(len(sent), 3)
        self.assertEqual(asked, ['send'])

    def test_ask_honours_a_remembered_answer_without_any_window(self):
        tool = _tool('send', None, risk='confirm')
        confirmation.approve(tool, {})
        saved = ai_provider.get_agent_confirm
        ai_provider.get_agent_confirm = lambda: 'tiered'
        try:
            self.assertTrue(confirmation.ask(tool, {}))
        finally:
            ai_provider.get_agent_confirm = saved

    def test_forgetting_takes_it_back(self):
        tool = _tool('send', None, risk='confirm')
        confirmation.approve(tool, {})
        self.assertEqual(confirmation.forget_approvals(), 1)
        self.assertFalse(confirmation.is_approved(tool, {}))


class TheQuestionCannotHangTitan(unittest.TestCase):
    """The old wait was done.wait() with no deadline and no way out."""

    def setUp(self):
        import wx
        self.wx = wx
        self.saved = (wx.GetApp, wx.CallAfter, wx.IsMainThread,
                      ai_provider.get_agent_confirm)
        ai_provider.get_agent_confirm = lambda: 'tiered'

    def tearDown(self):
        (self.wx.GetApp, self.wx.CallAfter, self.wx.IsMainThread,
         ai_provider.get_agent_confirm) = self.saved

    def _fake_app(self, looping):
        class App(object):
            def IsMainLoopRunning(self):
                return looping
        self.wx.GetApp = lambda: App()

    def test_no_running_loop_is_a_no_at_once(self):
        self._fake_app(looping=False)
        self.wx.IsMainThread = lambda: False
        started = time.time()
        self.assertFalse(confirmation.ask(_tool('x', None, risk='confirm'), {}))
        self.assertLess(time.time() - started, 0.5)

    def test_a_dialog_that_never_comes_is_ended_by_cancelling(self):
        self._fake_app(looping=True)
        self.wx.IsMainThread = lambda: False
        self.wx.CallAfter = lambda *a, **k: None     # the GUI never runs it
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        started = time.time()
        self.assertFalse(confirmation.ask(_tool('x', None, risk='confirm'), {},
                                          cancel_event=cancel))
        self.assertLess(time.time() - started, 2.0)

    def test_a_dialog_that_fails_to_build_is_a_no(self):
        self._fake_app(looping=True)
        self.wx.IsMainThread = lambda: False
        self.wx.CallAfter = lambda fn, *a, **k: fn(*a, **k)
        saved = confirmation._QuestionDialog
        confirmation._QuestionDialog = None          # calling it raises
        try:
            started = time.time()
            self.assertFalse(confirmation.ask(_tool('x', None, risk='confirm'),
                                              {}))
            self.assertLess(time.time() - started, 1.0)
        finally:
            confirmation._QuestionDialog = saved

    def test_asked_on_the_gui_thread_it_is_shown_there(self):
        """A CallAfter from the GUI thread would run after this returned -
        never. That was the whole of Titan stopping."""
        self._fake_app(looping=True)
        self.wx.IsMainThread = lambda: True
        self.wx.CallAfter = lambda *a, **k: self.fail("CallAfter from the GUI")
        saved = confirmation._ask_on_gui
        confirmation._ask_on_gui = lambda *a: confirmation.ONCE
        try:
            self.assertTrue(confirmation.ask(_tool('x', None, risk='confirm'),
                                             {}))
        finally:
            confirmation._ask_on_gui = saved

    def test_autonomous_never_asks(self):
        ai_provider.get_agent_confirm = lambda: 'none'
        self.wx.GetApp = lambda: self.fail("asked under Autonomous")
        self.assertTrue(confirmation.ask(_tool('x', None, risk='confirm'), {}))


class TheRealDialog(unittest.TestCase):
    """Built for real on a running wx main loop and asked from a worker, as
    the agent asks. Never shown: a test must not put a window in front of
    whoever runs it, so the press is an event fired at the real button."""

    def test_a_worker_asks_through_the_running_loop(self):
        import wx
        app = wx.App(False)
        anchor = wx.Frame(None)                      # keeps MainLoop up
        built = {}
        saved_show = confirmation._QuestionDialog.show
        saved_policy = ai_provider.get_agent_confirm
        ai_provider.get_agent_confirm = lambda: 'tiered'

        def show(dialog):
            built['labels'] = [dialog.once.GetLabel(), dialog.session.GetLabel(),
                               dialog.deny.GetLabel()]
            event = wx.CommandEvent(wx.wxEVT_BUTTON, dialog.session.GetId())
            event.SetEventObject(dialog.session)
            dialog.session.GetEventHandler().ProcessEvent(event)
            return dialog.answer
        confirmation._QuestionDialog.show = show
        answers = []
        tool = _tool('send_mail', None, risk='confirm')

        def worker():
            answers.append(confirmation.ask(tool, {}))
            answers.append(confirmation.ask(tool, {}))   # remembered
            wx.CallAfter(anchor.Destroy)
        try:
            # Started from inside the loop: asked before it runs, the answer
            # is (rightly) no.
            wx.CallAfter(lambda: threading.Thread(target=worker,
                                                  daemon=True).start())
            wx.CallLater(10000, anchor.Destroy)          # never for ever
            app.MainLoop()
        finally:
            confirmation._QuestionDialog.show = saved_show
            ai_provider.get_agent_confirm = saved_policy
            confirmation.forget_approvals()
        self.assertEqual(answers, [True, True])
        self.assertEqual(len(built['labels']), 3)


class SubagentsAreDefinedAndKept(unittest.TestCase):

    def tearDown(self):
        try:
            os.remove(subagents.store_path())
        except OSError:
            pass

    def test_the_built_in_kinds_exist(self):
        found = subagents.definitions()
        for name in ('general', 'screen', 'web', 'titan'):
            self.assertIn(name, found)
        self.assertIn('ocr', found['screen']['tools'])

    def test_one_of_the_users_own_is_saved_and_read_back(self):
        key = subagents.save('Mail sorter', 'Sorts mail', 'Read and sort.',
                             'services, nonsense, memory', 12)
        self.assertEqual(key, 'mail_sorter')
        entry = subagents.definitions()[key]
        self.assertEqual(entry['tools'], ['services', 'memory'])
        self.assertEqual(entry['max_steps'], 12)
        self.assertFalse(entry['builtin'])
        self.assertTrue(subagents.remove('Mail sorter'))
        self.assertNotIn(key, subagents.definitions())

    def test_a_built_in_one_cannot_be_deleted(self):
        self.assertIn('built in', subagents.ai_delete_subagent('web'))
        self.assertIn('web', subagents.definitions())


class SubagentsRun(unittest.TestCase):

    def setUp(self):
        self.saved_on = subagents._ai_on
        subagents._ai_on = lambda: True
        self.saved_tools = subagents._group_tools
        self.sub_tool_runs = []
        subagents._group_tools = lambda group: [
            _tool('look', lambda **a: self.sub_tool_runs.append(group) or 'seen'),
            _tool('erase', lambda **a: 'erased', risk='confirm')]

    def tearDown(self):
        subagents._ai_on = self.saved_on
        subagents._group_tools = self.saved_tools
        confirmation.forget_approvals()

    def _plan(self, parent_calls, sub_calls):
        def plan(system, history, tools):
            calls = sub_calls if 'You are a SUBAGENT' in system else parent_calls
            return _calls_then_done(calls)(system, history, tools)
        return plan

    def test_a_subagent_does_its_task_and_hands_the_result_back(self):
        script = _Script(self._plan(
            [('ai_run_subagent', {'task': 'look around', 'subagent': 'screen'})],
            [('look', {})]))
        results = []
        with _FakeProvider(script):
            answer = ai_agent.run_agent(
                'go', subagents.get_subagent_tools(), provider='fake',
                remember=False,
                on_tool_result=lambda n, r: results.append((n, r)))
        self.assertEqual(answer, 'finished')
        self.assertEqual(self.sub_tool_runs, ['desktop'])
        self.assertIn(('ai_run_subagent', "Subagent 'screen': finished"), results)
        sub_call = [c for c in script.calls if 'You are a SUBAGENT' in c['system']][0]
        # Its own short history: the task and nothing of the parent's.
        self.assertEqual(sub_call['history'][0]['content'], 'look around')
        self.assertIn('look', sub_call['tools'])

    def test_it_asks_through_the_parents_confirmation(self):
        asked = []
        script = _Script(self._plan(
            [('ai_run_subagent', {'task': 'clean up'})], [('erase', {})]))
        with _FakeProvider(script):
            ai_agent.run_agent(
                'go', subagents.get_subagent_tools(), provider='fake',
                remember=False,
                confirm=lambda t, a: asked.append(t['name']) or False)
        self.assertEqual(asked, ['erase'])

    def test_cancelling_the_parent_cancels_the_subagent(self):
        cancel = threading.Event()

        def look(**a):
            cancel.set()
            return 'seen'
        subagents._group_tools = lambda group: [_tool('look', look)]
        script = _Script(self._plan(
            [('ai_run_subagent', {'task': 't'})], [('look', {}), ('look', {})]))
        with _FakeProvider(script):
            with self.assertRaises(ai_agent.AgentCancelled):
                ai_agent.run_agent('go', subagents.get_subagent_tools(),
                                   provider='fake', remember=False,
                                   cancel_event=cancel)

    def test_several_run_side_by_side_and_come_back_in_order(self):
        def plan(system, history, tools):
            if 'You are a SUBAGENT' in system:
                task = history[0]['content']
                time.sleep(0.2)
                return {'text': f"done: {task}", 'tool_calls': []}
            return _calls_then_done([('ai_run_subagents', {'tasks': (
                '[{"task": "one"}, {"task": "two", "subagent": "web"},'
                ' "three"]')})])(system, history, tools)
        results = []
        script = _Script(plan)
        started = time.time()
        with _FakeProvider(script):
            ai_agent.run_agent('go', subagents.get_subagent_tools(),
                               provider='fake', remember=False,
                               on_tool_result=lambda n, r: results.append(r))
        self.assertLess(time.time() - started, 0.55)    # not 3 x 0.2 in turn
        self.assertEqual(results[0],
                         "1. (general) done: one\n2. (web) done: two\n"
                         "3. (general) done: three")

    def test_nesting_stops_at_the_limit(self):
        depths = []

        def plan(system, history, tools):
            depths.append(ai_agent.run_depth())
            return _calls_then_done([('ai_run_subagent', {'task': 'deeper'})])(
                system, history, tools) if 'ai_run_subagent' in [
                    t['name'] for t in tools] else {'text': 'leaf',
                                                    'tool_calls': []}
        subagents._group_tools = lambda group: []
        with _FakeProvider(_Script(plan)):
            ai_agent.run_agent('go', subagents.get_subagent_tools(),
                               provider='fake', remember=False)
        self.assertEqual(max(depths), subagents.MAX_DEPTH)


class ABackgroundSubagentDoesNotKeepTheUserWaiting(unittest.TestCase):
    """Asked for as "can the agents do it asynchronously, so there is no long
    wait for an answer?": the run answers at once and the result is
    delivered when it is ready."""

    def setUp(self):
        self.saved = (subagents._ai_on, subagents._deliver,
                      subagents._group_tools)
        subagents._ai_on = lambda: True
        self.delivered = []
        self.arrived = threading.Event()

        def deliver(job):
            self.delivered.append(dict(job))
            self.arrived.set()
        subagents._deliver = deliver
        subagents._group_tools = lambda group: []

    def tearDown(self):
        # Every job ends BEFORE the real delivery is put back: a late one
        # would announce itself through Titan's notifications mid-suite.
        for job in subagents.jobs():
            subagents.cancel_job(job['id'])
        deadline = time.time() + 10
        while (any(j['state'] == 'running' for j in subagents.jobs())
               and time.time() < deadline):
            time.sleep(0.05)
        (subagents._ai_on, subagents._deliver,
         subagents._group_tools) = self.saved

    def test_the_parent_answers_before_the_subagent_is_done(self):
        release = threading.Event()

        def plan(system, history, tools):
            if 'You are a SUBAGENT' in system:
                release.wait(5)
                return {'text': 'the slow result', 'tool_calls': []}
            return _calls_then_done([('ai_start_subagent', {
                'task': 'something slow', 'subagent': 'web'})])(
                    system, history, tools)
        replies = []
        with _FakeProvider(_Script(plan)):
            started = time.time()
            answer = ai_agent.run_agent(
                'go', subagents.get_subagent_tools(), provider='fake',
                remember=False, on_tool_result=lambda n, r: replies.append(r))
            took = time.time() - started
            self.assertEqual(answer, 'finished')
            self.assertLess(took, 1.0)
            self.assertIn('Started background subagent', replies[0])
            self.assertEqual(self.delivered, [])          # not yet
            self.assertIn('running', subagents.ai_subagent_status())
            release.set()
            self.assertTrue(self.arrived.wait(5))
        job = self.delivered[0]
        self.assertEqual((job['state'], job['result'], job['name']),
                         ('done', 'the slow result', 'web'))
        self.assertIn('the slow result',
                      subagents.ai_subagent_status(str(job['id'])))

    def test_one_can_be_stopped_and_is_then_not_announced(self):
        def plan(system, history, tools):
            time.sleep(0.1)
            return {'text': '', 'tool_calls': [
                {'id': str(len(history)), 'name': 'nothing', 'args': {}}]}
        with _FakeProvider(_Script(plan)):
            number = subagents.start_background('loop for ever')
            time.sleep(0.2)
            self.assertIn('being stopped', subagents.ai_cancel_subagent(number))
            deadline = time.time() + 5
            while time.time() < deadline:
                state = [j for j in subagents.jobs() if j['id'] == number][0]
                if state['state'] != 'running':
                    break
                time.sleep(0.05)
        self.assertEqual(state['state'], 'cancelled')
        self.assertEqual(self.delivered, [])

    def test_there_is_a_ceiling(self):
        hold = threading.Event()

        def plan(system, history, tools):
            hold.wait(5)
            return {'text': 'x', 'tool_calls': []}
        with _FakeProvider(_Script(plan)):
            for _n in range(subagents.MAX_BACKGROUND):
                subagents.start_background('wait')
            self.assertIn('already running', subagents.ai_start_subagent('one more'))
            hold.set()


class SubagentsAreAnAction(unittest.TestCase):

    def test_the_action_api_has_them(self):
        from src.titan_core.actions import builtin
        addon = [a for a in builtin.build() if a.addon_id == 'subagents'][0]
        names = {a.name: a for a in addon.actions}
        for name in ('run_subagent', 'run_subagents', 'start_subagent',
                     'subagent_status', 'cancel_subagent', 'list_subagents',
                     'create_subagent', 'delete_subagent'):
            self.assertIn(name, names)
        self.assertTrue(names['run_subagent'].needs_ai)
        self.assertFalse(names['run_subagent'].needs_gui)

    def test_the_agent_and_the_assistant_have_them(self):
        from src.ai import agent_tools
        from src.ai.assistant.assistant_tools import get_assistant_tools
        for tools in (agent_tools.get_tools(), get_assistant_tools()):
            self.assertIn('ai_run_subagent', [t['name'] for t in tools])


if __name__ == '__main__':
    unittest.main()

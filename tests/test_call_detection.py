# -*- coding: utf-8 -*-
"""
Regression tests for WhatsApp / Messenger call detection.

The bug being locked down: opening the app announced "Incoming call" and then
"call ended" for a call that never existed, because detection matched any
element whose class or aria-label merely contained "call" / "Video" - which the
Voice call and Video call buttons in every chat header do.

The in-page script is JavaScript, so these tests run it under node against a
simulated DOM. ``node`` is required; the test is skipped when it is missing.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.network.call_detection_js import (  # noqa: E402
    build_monitor_script,
    build_poll_script,
    IN_CALL_SELECTORS,
    IGNORED_SELECTORS,
)

NODE = shutil.which('node')

# Minimal DOM stub: only what the detection script touches. Selectors are
# matched by looking for the quoted substring inside each element's attributes,
# which mirrors how [attr*="x" i] behaves for our purposes.
DOM_HARNESS = r"""
function makeDom(elements) {
    function attrText(el) {
        return ((el.ariaLabel || '') + ' ' + (el.testId || '')).toLowerCase();
    }
    function parseSelector(sel) {
        var m = sel.match(/\[(aria-label|data-testid)\*="([^"]+)"\s*i?\]/);
        return m ? m[2].toLowerCase() : null;
    }
    return {
        body: {},
        querySelector: function(sel) {
            var needle = parseSelector(sel);
            if (needle === null) { throw new Error('unsupported selector: ' + sel); }
            for (var i = 0; i < elements.length; i++) {
                if (attrText(elements[i]).indexOf(needle) !== -1) { return elements[i]; }
            }
            return null;
        }
    };
}

global.MutationObserver = function(cb) {
    this.observe = function() {};
    this.disconnect = function() {};
};
global.setInterval = function() { return 0; };
global.console = console;

var scenarios = SCENARIOS_JSON;
var results = {};
for (var name in scenarios) {
    global.window = {};
    global.document = makeDom(scenarios[name]);
    global.RTCPeerConnection = null;
    MONITOR_SCRIPT
    results[name] = window.__titanDetectCall();
}
console.log(JSON.stringify(results));
"""

# What the page looks like in each situation.
SCENARIOS = {
    # Freshly logged in: the chat header's call launch buttons are present.
    # This is the exact state that used to announce a phantom incoming call.
    'just_logged_in': [
        {'ariaLabel': 'Voice call'},
        {'ariaLabel': 'Video call'},
        {'ariaLabel': 'Search'},
        {'testId': 'chat-list'},
        {'testId': 'conversation-panel-messages'},
    ],
    # Chat list rendering, including nodes whose test ids contain "call".
    'browsing_chats': [
        {'ariaLabel': 'Voice call'},
        {'ariaLabel': 'Video call'},
        {'testId': 'recent-calls-list'},
        {'testId': 'call-log-item'},
    ],
    # A real incoming call: accept / decline controls exist.
    'incoming_call': [
        {'ariaLabel': 'Voice call'},
        {'ariaLabel': 'Decline'},
        {'ariaLabel': 'Accept call'},
    ],
    # A real outgoing / connected call: only End call exists.
    'outgoing_call': [
        {'ariaLabel': 'Voice call'},
        {'ariaLabel': 'End call'},
        {'ariaLabel': 'Mute'},
    ],
    # Nothing at all on screen.
    'empty': [],
}


@unittest.skipIf(NODE is None, "node is required to exercise the in-page script")
class CallDetectionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        script = DOM_HARNESS.replace('SCENARIOS_JSON', json.dumps(SCENARIOS))
        script = script.replace('MONITOR_SCRIPT', build_monitor_script('Test'))
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                         encoding='utf-8') as fh:
            fh.write(script)
            cls.script_path = fh.name
        proc = subprocess.run([NODE, cls.script_path], capture_output=True,
                              text=True, timeout=60)
        if proc.returncode != 0:
            raise AssertionError(f"node failed:\n{proc.stdout}\n{proc.stderr}")
        cls.results = json.loads(proc.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls.script_path)
        except OSError:
            pass

    def test_login_does_not_look_like_a_call(self):
        """The reported bug: logging in must not detect any call."""
        self.assertFalse(self.results['just_logged_in']['active'])

    def test_browsing_chats_does_not_look_like_a_call(self):
        self.assertFalse(self.results['browsing_chats']['active'])

    def test_empty_page_has_no_call(self):
        self.assertFalse(self.results['empty']['active'])

    def test_real_incoming_call_is_detected(self):
        self.assertTrue(self.results['incoming_call']['active'])
        self.assertEqual(self.results['incoming_call']['direction'], 'incoming')

    def test_real_outgoing_call_is_detected(self):
        self.assertTrue(self.results['outgoing_call']['active'])
        self.assertEqual(self.results['outgoing_call']['direction'], 'outgoing')

    def test_start_buttons_are_never_in_call_controls(self):
        """Voice/Video call buttons must not be part of the in-call selectors."""
        for ignored in IGNORED_SELECTORS:
            self.assertNotIn(ignored, IN_CALL_SELECTORS)

    def test_poll_script_reports_not_setup_without_state(self):
        proc = subprocess.run(
            [NODE, '-e', 'global.window={}; console.log(eval(%s));'
             % json.dumps(build_poll_script())],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout.strip())['status'], 'not_setup')


if __name__ == '__main__':
    unittest.main(verbosity=2)

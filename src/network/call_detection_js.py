# -*- coding: utf-8 -*-
"""
Shared in-page call detection for the WhatsApp / Messenger webviews
==================================================================

Why this module exists
----------------------
Both webviews used to decide "a call is happening" from very broad DOM
substring matches - ``[class*="call"]``, ``[aria-label*="Call"]``,
``[aria-label*="Video"]``, or any clicked button whose text contained "call".
WhatsApp Web and Messenger put a *Voice call* and *Video call* button in every
chat header, so simply opening the app on login matched those selectors. The
client then announced "Incoming call", and when the same nodes were swapped out
during normal rendering it announced "call ended" - a call that never existed.

The corrected rule is: **a call exists only when a control that can only exist
during a live call is on the page.** Ending a call, declining it or accepting it
are such controls. Starting one is not - a *Voice call* button is an invitation,
not a call.

On top of that:

* one boolean state machine (``active``) - ``callStarted`` fires only on
  false -> true and ``callEnded`` only on true -> false, so a phantom "ended"
  can no longer be emitted when nothing was ringing;
* a warm-up window after injection, so the burst of DOM nodes created while the
  app first paints (i.e. right after login) can never be read as a call;
* the detection predicate is exposed as ``window.__titanDetectCall()`` so it can
  be exercised against a simulated DOM outside the browser.

``build_monitor_script`` returns the injection script, ``build_poll_script``
the one polled by the wx timer. Both are plain strings so callers keep using
``webview.RunScript``.
"""

from __future__ import annotations

# Controls that only exist while a call is live/ringing. Case-insensitive.
_IN_CALL_SELECTORS = [
    '[aria-label*="End call" i]',
    '[aria-label*="Leave call" i]',
    '[aria-label*="Hang up" i]',
    '[aria-label*="Decline" i]',
    '[aria-label*="Reject" i]',
    '[aria-label*="Accept call" i]',
    '[aria-label*="Answer call" i]',
    '[aria-label*="Join call" i]',
    '[data-testid*="end-call" i]',
    '[data-testid*="decline" i]',
    '[data-testid*="accept-call" i]',
]

# Present while an incoming call is ringing (accept/decline pair).
_INCOMING_SELECTORS = [
    '[aria-label*="Decline" i]',
    '[aria-label*="Reject" i]',
    '[aria-label*="Accept call" i]',
    '[aria-label*="Answer call" i]',
    '[data-testid*="decline" i]',
    '[data-testid*="accept-call" i]',
]

# Present once we are the caller and the call is up / ringing out.
_OUTGOING_SELECTORS = [
    '[aria-label*="End call" i]',
    '[aria-label*="Hang up" i]',
    '[data-testid*="end-call" i]',
]

# Deliberately NOT treated as a call: these are the buttons that *start* one.
_IGNORED_SELECTORS = [
    '[aria-label*="Voice call" i]',
    '[aria-label*="Video call" i]',
    '[aria-label*="Start call" i]',
]

# Milliseconds after injection during which detection stays muted. Covers the
# initial render/login burst that produced the phantom announcements.
WARMUP_MS = 10000


def _js_array(items) -> str:
    return '[' + ', '.join("'" + s.replace("'", "\\'") + "'" for s in items) + ']'


def build_monitor_script(platform: str = 'WhatsApp') -> str:
    """JavaScript injected once per page load to watch for real calls."""
    tag = platform.replace("'", '')
    return """
    (function() {
        if (window.__titanCallMonitor) { return 'already'; }

        var IN_CALL = %(in_call)s;
        var INCOMING = %(incoming)s;
        var OUTGOING = %(outgoing)s;
        var WARMUP_MS = %(warmup)d;
        var PLATFORM = '%(tag)s';

        var state = {
            active: false,
            direction: null,
            connected: false,
            startedAt: null,
            injectedAt: Date.now(),
            pcConnected: false,
            events: []
        };
        window.__titanCallState = state;

        function anyMatch(selectors) {
            for (var i = 0; i < selectors.length; i++) {
                try {
                    if (document.querySelector(selectors[i])) { return true; }
                } catch (e) { /* selector unsupported - ignore */ }
            }
            return false;
        }

        // Pure predicate over the current DOM. Exposed for testing.
        function detectCall() {
            var inCall = anyMatch(IN_CALL);
            if (!inCall) { return { active: false, direction: null }; }
            if (anyMatch(INCOMING)) { return { active: true, direction: 'incoming' }; }
            if (anyMatch(OUTGOING)) { return { active: true, direction: 'outgoing' }; }
            return { active: true, direction: 'unknown' };
        }
        window.__titanDetectCall = detectCall;

        function warmingUp() {
            return (Date.now() - state.injectedAt) < WARMUP_MS;
        }

        // Single place where the state machine may change. Emits at most one
        // started / ended event per real transition.
        function evaluate() {
            if (warmingUp()) { return; }

            var found = detectCall();

            if (found.active && !state.active) {
                state.active = true;
                state.direction = found.direction;
                state.connected = false;
                state.startedAt = Date.now();
                state.events.push(found.direction === 'incoming' ? 'incoming' : 'outgoing');
                console.log('TITAN: ' + PLATFORM + ' call started (' + found.direction + ')');
                return;
            }

            if (!found.active && state.active) {
                state.active = false;
                state.direction = null;
                state.connected = false;
                state.startedAt = null;
                state.events.push('ended');
                console.log('TITAN: ' + PLATFORM + ' call ended');
                return;
            }

            // Still in a call: promote ringing -> connected once the transport
            // reports connected. Never invents a call on its own.
            if (found.active && state.active && state.pcConnected && !state.connected) {
                state.connected = true;
                state.events.push('connected');
                console.log('TITAN: ' + PLATFORM + ' call connected');
            }
        }

        // WebRTC only refines an already-detected call - a peer connection on
        // its own is not proof of a call (these apps open them for other
        // features too).
        var OriginalPC = window.RTCPeerConnection || window.webkitRTCPeerConnection;
        if (OriginalPC) {
            var Wrapped = function() {
                var pc = new (Function.prototype.bind.apply(
                    OriginalPC, [null].concat(Array.prototype.slice.call(arguments))))();
                try {
                    pc.addEventListener('connectionstatechange', function() {
                        var s = pc.connectionState;
                        if (s === 'connected') {
                            state.pcConnected = true;
                        } else if (s === 'disconnected' || s === 'failed' || s === 'closed') {
                            state.pcConnected = false;
                        }
                        evaluate();
                    });
                } catch (e) { /* older engines */ }
                return pc;
            };
            try {
                Object.setPrototypeOf(Wrapped, OriginalPC);
                Wrapped.prototype = OriginalPC.prototype;
                window.RTCPeerConnection = Wrapped;
            } catch (e) { /* keep the original on failure */ }
        }

        var observer = new MutationObserver(function() { evaluate(); });
        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['aria-label', 'data-testid']
        });

        // Safety net for call UI that appears without a matching mutation.
        var poll = setInterval(evaluate, 1500);

        window.__titanCallMonitor = { observer: observer, poll: poll };
        console.log('TITAN: ' + PLATFORM + ' call monitoring armed');
        return 'ok';
    })();
    """ % {
        'in_call': _js_array(_IN_CALL_SELECTORS),
        'incoming': _js_array(_INCOMING_SELECTORS),
        'outgoing': _js_array(_OUTGOING_SELECTORS),
        'warmup': WARMUP_MS,
        'tag': tag,
    }


def build_poll_script() -> str:
    """JavaScript polled by the wx timer: drains queued call events."""
    return """
    (function() {
        if (!window.__titanCallState) { return JSON.stringify({status: 'not_setup'}); }
        var s = window.__titanCallState;
        var out = {
            status: 'ok',
            active: !!s.active,
            direction: s.direction,
            connected: !!s.connected,
            events: s.events.slice(0)
        };
        s.events.length = 0;
        return JSON.stringify(out);
    })();
    """


# Selectors that must never, on their own, be read as an active call. Kept as a
# module-level constant so the test suite can assert the regression stays fixed.
IGNORED_SELECTORS = tuple(_IGNORED_SELECTORS)
IN_CALL_SELECTORS = tuple(_IN_CALL_SELECTORS)

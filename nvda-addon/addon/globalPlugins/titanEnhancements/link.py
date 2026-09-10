# -*- coding: utf-8 -*-
"""The connection to Titan: what we serve it, and what we ask of it.

The transport is Titan's own Action Bus, joined with the library Titan
ships for exactly this (``titan_actions.py``, vendored beside this file and
kept byte-identical by a test). Two properties of it decide the shape of
everything here:

* **It is bidirectional.** We ``serve`` handlers, so Titan calls INTO NVDA -
  that is the structured announcement channel, and it is the whole point.
  We also ``call``, so NVDA reaches Titan's subsystems.
* **It costs nothing when Titan is not there.** ``serve`` returns at once
  and a daemon thread keeps trying quietly. NVDA must never wait for a
  desktop that is not running.

**We join as a CLIENT** (``kind='client'``), not as an add-on. That is not
cosmetic: it is what makes Titan announce out loud that another program has
taken hold of it, and what puts this add-on behind the user's own consent
for anything that would CHANGE Titan. Reading Titan is always served, so
everything above - the announcements, the notifications, the status - works
whether or not that consent was given.

Answers come back as JSON through ``titan.bridge`` rather than as prose from
an action. That is deliberate and Titan's own documentation says why: every
live bug the Elten bridge hit came from parsing a sentence written for a
person.
"""

import json
import threading
import time

from . import titan_actions
from . import i18n

_ = i18n.install(globals())

#: Our id on the bus. It is also the key the user's consent is remembered
#: under, so it must never change.
CLIENT_ID = 'nvda'
CLIENT_LABEL = 'NVDA'

#: Long enough for Titan to reach a component and come back, short enough
#: that a gesture never feels hung.
CALL_TIMEOUT = 12.0


class Link:
    """What we know about the Titan on the other end."""

    def __init__(self):
        self.attached = False
        self.pid = 0
        self.titan_version = ''
        self.language = ''
        self.api = 0
        self.last_error = ''
        self.attached_at = 0.0
        #: Set the first time Titan refuses because its own user has not
        #: answered the question yet. Read by the status command, so "it
        #: does nothing" has an answer that is not "it is broken".
        self.needs_consent = False
        self._lock = threading.RLock()

    # ------------------------------------------------------ Titan calls us
    def attach(self, pid=0, version='', language='', api=0, **_):
        """Titan introducing itself, right after we join.

        The PID is the part that matters: it is how the focus layer knows
        which windows are Titan's, and it is asked for rather than guessed
        because Titan run from source is ``python.exe`` and recognising it
        by name would take over every Python program on the machine.
        """
        from . import focus
        with self._lock:
            self.attached = True
            self.pid = focus.set_titan_pid(pid)
            self.titan_version = str(version or '')
            self.language = str(language or '')
            try:
                self.api = int(api or 0)
            except (TypeError, ValueError):
                self.api = 0
            self.attached_at = time.time()
        from . import channel
        return {'attached': True, 'addon': '1.0.0',
                'capabilities': channel.CHANNEL.capabilities()}

    def detach(self, **_):
        from . import focus, panner, semantics
        with self._lock:
            self.attached = False
        focus.set_titan_pid(0)
        panner.PANNER.restore()
        # Which process was which is only true while that Titan was
        # running: a pid is reused, and reading somebody else's window as
        # though it were the file manager is worse than reading it plainly.
        semantics.forget()
        semantics.forget_titles()
        return {'attached': False}

    def status(self, **_):
        with self._lock:
            return {'attached': self.attached, 'pid': self.pid,
                    'titan': self.titan_version, 'language': self.language,
                    'connected': titan_actions.is_connected()}

    # ------------------------------------------------------- we call Titan
    def connected(self):
        return titan_actions.is_connected()

    def introduce(self):
        """Ask Titan who it is, rather than waiting to be told.

        `attach` is Titan introducing itself, and Titan only does that the
        first time it ANNOUNCES something - which on a desktop where nobody
        has pressed anything is never. Everything that behaves differently
        inside Titan's own windows was therefore switched off until Titan
        happened to speak. Asking costs one call at connection.
        """
        ok, data = self.bridge('hello', timeout=CALL_TIMEOUT)
        if not ok or not isinstance(data, dict):
            return False
        from . import focus
        pid = data.get('pid')
        if pid:
            with self._lock:
                self.pid = focus.set_titan_pid(pid)
                self.attached = True
                self.language = str(data.get('language') or '')
                try:
                    self.api = int(data.get('api') or 0)
                except (TypeError, ValueError):
                    pass
                self.attached_at = time.time()
        return bool(pid)

    def bridge(self, call, timeout=CALL_TIMEOUT, **args):
        """One typed call into Titan. Returns (ok, data_or_error).

        Never raises: a gesture that reaches a Titan which is not running,
        is older than this add-on, or has refused consent must say so, not
        put a traceback in NVDA's log where nobody using it will look.
        """
        if not titan_actions.is_connected():
            return False, _('Titan is not running.')
        request = json.dumps({'call': call, 'args': args}, ensure_ascii=False)
        try:
            result = titan_actions.call('titan', 'bridge', timeout=timeout,
                                        request=request)
        except Exception as error:                   # noqa: BLE001
            self.last_error = f'{type(error).__name__}: {error}'
            return False, self.last_error
        if not result.ok:
            text = str(result)
            self.last_error = text
            # A refusal because the user has not said yes is a different
            # thing from a call that failed, and telling the two apart is
            # what stops this add-on retrying something the user declined.
            #
            # **Asked of the wire, never of the wording.** It used to look
            # for the words "consent" or "permission" in the answer - and
            # Titan writes that sentence in ITS user's own language, so on
            # a Polish Titan the test matched nothing and a refusal read
            # like a broken bridge. Titan marks it (`'consent': 'needed'`)
            # and the client now carries the mark.
            if getattr(result, 'needs_consent', False):
                self.needs_consent = True
                # Titan's own sentence is kept: it is in the user's
                # language and it names the one thing that changes the
                # answer, which a translation of ours would not.
                return False, text or _('Titan has not been told this '
                                        'add-on may control it. Answer the '
                                        'question Titan asked when NVDA '
                                        'connected, or allow it in Titan\'s '
                                        'settings.')
            return False, text
        try:
            payload = json.loads(str(result))
        except ValueError as error:
            return False, f'Titan answered something that is not JSON: {error}'
        if not payload.get('ok'):
            error = str(payload.get('error') or 'the call failed')
            if 'has no bridge call' in error:
                return False, _('This Titan is older than the add-on: it does '
                                'not have {call}.').format(call=call)
            return False, error
        with self._lock:
            self.needs_consent = False
            try:
                self.api = int(payload.get('api') or 0)
            except (TypeError, ValueError):
                pass
        return True, payload.get('data')

    def run_action(self, addon, action, timeout=CALL_TIMEOUT, **args):
        """An add-on's action, through the bridge. (ok, text).

        **The timeout is the caller's, because twelve seconds is right for
        a question about a window and wrong for one that reaches an AI
        provider.** It used to be fixed at `CALL_TIMEOUT`, and
        `surface.read(hwnd, timeout=45.0)` took a timeout it then never
        passed on - a dead parameter, and every AI reading answered
        "Titan did not answer within 12s" while Titan was answering
        perfectly well, a few seconds later, into a caller that had
        stopped listening. Seen in the log on a real session, repeatedly.
        """
        ok, data = self.bridge('addons.run', timeout=timeout, addon=addon,
                               action=action, args=args)
        if not ok:
            return False, data
        if isinstance(data, dict):
            return bool(data.get('ok', True)), str(data.get('text') or '')
        return True, str(data)


#: The one link.
LINK = Link()


def handlers():
    """Everything Titan may call in NVDA.

    Kept in one place because it is also what Titan reads to decide what it
    can send: an announcement carrying a position is composed differently
    from one that has to fold the position into a sentence, and Titan must
    not have to find that out by sending one and being told no.
    """
    from . import channel
    from . import focus
    from . import interject
    from . import nvda_control
    served = {
        'attach': LINK.attach,
        'detach': LINK.detach,
        'status': LINK.status,
        'announce': channel.CHANNEL.announce,
        'braille': channel.CHANNEL.braille,
        'interrupt': channel.CHANNEL.interrupt,
        'speaking': channel.CHANNEL.speaking,
        'beep': channel.CHANNEL.beep,
        'capabilities': channel.CHANNEL.capabilities,
        'stand_down': lambda **kw: {'standing_down':
                                    focus.stand_down(kw.get('down', True))},
    }
    # The channel runs both ways.  Everything above is Titan SAYING
    # something; everything below is Titan asking what the reader can see
    # and - behind the user's own switch - changing it.  That is what makes
    # Titan's own subsystems contextual: AI OCR reads the window NVDA is in,
    # and the assistant is asked about the control the user is actually on.
    served.update(nvda_control.handlers())
    # Titan Access's own habits: a tone and a word for the kind of dialog
    # about to appear, and a state added to the control just read. Titan
    # has always done both and only its own reader ever heard them.
    # **The add-on's own features, run inside the NVDA that is really
    # running.** Everything else here is Titan asking the reader something;
    # this is the reader being asked to prove that its own half works, and
    # it is served because a check nobody can run from outside is a check
    # that is run once and then never again.
    from . import selftest
    served['selftest'] = selftest.run
    served['dialog_kind'] = interject.dialog_kind
    served['state_suffix'] = interject.state_suffix
    # A live region, pushed. A program that KNOWS it has news says so,
    # which is the half no amount of watching a screen can do for itself.
    from . import live as live_regions
    served['live'] = live_regions.pushed
    # **What is actually switched on, and what has actually happened.**
    # "The dialog kinds are not read" is a report with no evidence in it,
    # and there are half a dozen different reasons it can be true: the
    # switch, the speech filter that was never registered, a speech mode
    # that cannot be muted, a Titan that is not there to play the sound.
    # Each is a different thing to do about it, and none of them is
    # visible from outside.
    served['diagnostics'] = diagnostics
    served['switch'] = switch
    return served


def switch(name='', value=None, **_):
    """Read or set one of THIS ADD-ON's switches, while NVDA is running.

    **A switch can only be set from inside NVDA**, which is not obvious and
    cost an hour: writing one into `nvda.ini` by hand does nothing, because
    NVDA validates the file against the configuration spec at load time and
    an add-on's spec is not registered until the add-on starts. The key is
    simply deleted. So the only ways in are the settings panel and this.

    Changing the reader is the same permission Titan already asks for
    (`letTitanDrive`); reading what is set is always answered, because it
    is the user's own screen reader described to their own desktop.
    """
    from . import configSpec
    values = configSpec.read()
    wanted = str(name or '').strip()
    if not wanted:
        return {'switches': values}
    if wanted not in configSpec.SPEC:
        return {'ok': False, 'why': "there is no switch called '%s'" % wanted,
                'switches': sorted(configSpec.SPEC)}
    if value is None:
        return {'ok': True, 'name': wanted, 'value': bool(values.get(wanted))}
    if not values.get('letTitanDrive', True):
        return {'ok': False, 'why': 'Titan has not been allowed to change '
                                    'NVDA; the switch is in NVDA\'s '
                                    'settings, under Titan enhancements'}
    if isinstance(value, str):
        value = value.strip().lower() in ('1', 'true', 'yes', 'on')
    values[wanted] = bool(value)
    configSpec.write(values)
    configSpec.apply()
    return {'ok': True, 'name': wanted, 'value': bool(value)}


def diagnostics(**_):
    """Everything about this add-on's state, as data. Never raises."""
    found = {}

    def ask(name, get):
        try:
            found[name] = get()
        except Exception as error:                   # noqa: BLE001
            found[name] = 'failed: %s' % error

    from . import compat
    ask('nvda_missing', compat.missing)
    ask('speech_extensions', lambda: compat.speechExtensions is not None)
    ask('speech', lambda: compat.speech is not None)
    ask('tones', lambda: compat.tones is not None)
    ask('ui', lambda: compat.ui is not None)

    from . import focus
    ask('can_mute', focus.can_mute)
    ask('titan_pid', focus.titan_pid)
    ask('standing_down', focus.standing_down)
    ask('counts', lambda: {'pitched': focus.pitched(),
                           'replaced': focus.suppressed(),
                           'semantic': focus.semantic(),
                           'windows': focus.windows(),
                           'pictures': focus.pictures(),
                           'labelled': focus.labelled()})

    from . import interject
    ask('interject_registered', interject.registered)
    ask('interject_applied', interject.applied)
    ask('spoken_log', lambda: [line[1][:60] for line in
                               interject.spoken_log()[-6:]])

    for name in ('dialog_kind', 'live', 'surface', 'smart', 'trackpad',
                 'states', 'semantics', 'ancestry'):
        def get(name=name):
            # **Relative, because the package is not called what it is
            # called.** Inside NVDA this is `globalPlugins.
            # titanEnhancements`, and asking for the top-level name gets
            # "No module named 'titanEnhancements'" - a diagnostic that
            # fails to diagnose, which is worse than none.
            import importlib
            module = importlib.import_module('.' + name, __package__)
            reporter = getattr(module, 'report', None) or \
                getattr(module, 'timing', None)
            return reporter() if callable(reporter) else 'no report'
        ask(name, get)

    from . import configSpec
    ask('settings', configSpec.read)
    from . import readerModules
    ask('modules', lambda: len(readerModules.load()))
    return found


#: What Titan is TOLD this add-on offers, which is deliberately less than
#: what it serves. Everything in `handlers()` can be called; only what is
#: declared here becomes an add-on in Titan's registry, and therefore only
#: this is what Titan's assistant, its macros and its Titan Scripts are
#: offered. `announce`, `attach`, `stand_down` and `capabilities` are the
#: channel's own plumbing - Titan's reader layer calls them by name and
#: nobody should ever be shown them as things to do.
#:
#: Declaring them is what makes this add-on an ORDINARY Titan add-on, with
#: no code on Titan's side: `registry._merge_bus` builds a real add-on out
#: of any bus client that says what it offers. Anyone writing a bridge of
#: their own gets the same, which is the point.
_STRING = {'type': 'string'}

DECLARED = [
    {'name': 'context',
     'summary': "What NVDA can see right now: the focused control by name, "
                "role and state, what is selected, where the review cursor "
                "is, and whether NVDA is in browse mode.",
     'params': {}},
    {'name': 'window',
     'summary': "The window NVDA is reading, with its handle - which is not "
                "always the window Windows calls the foreground.",
     'params': {}},
    {'name': 'describe',
     'summary': "What the reader would say about the focused control, in "
                "parts: the name, the control type and each state, each "
                "with the tone it is said at.",
     'params': {}},
    {'name': 'speak',
     'summary': "Read something out in NVDA's own voice, optionally from a "
                "place in the stereo image and at a pitch of its own.",
     'params': {'text': dict(_STRING, required=True),
                'interrupt': {'type': 'boolean'},
                'position': {'type': 'number',
                             'description': '-1 left, 0 centre, 1 right'},
                'pitch': {'type': 'number', 'description': '-10 to 10'},
                'rate': {'type': 'number', 'description': '-10 to 10'},
                'segments': {'type': 'array',
                             'description': "The parts and their tones, as "
                                            "[[text, pitch], ...] - the "
                                            "name at 0, the control type "
                                            "at -4, a state at +4, which "
                                            "is Titan Access's own shape."}}},
    {'name': 'stop', 'summary': "Stop NVDA speaking.", 'params': {}},
    {'name': 'switch',
     'summary': "Read or set one of the add-on's own switches while NVDA is "
                "running - which is the only way there is: a switch written "
                "into nvda.ini by hand is deleted, because NVDA validates "
                "the file before an add-on has registered what its switches "
                "are. With no name, answers all of them.",
     'params': {'name': dict(_STRING), 'value': {'type': 'boolean'}}},
    {'name': 'selftest',
     'summary': "Run the add-on's own features inside the NVDA that is "
                "really running, and answer what happened: the local "
                "recogniser, the screen review, the controls of the window "
                "in front, anchoring a control and finding it again, the "
                "journal, the sound scheme, the names, the monitors, the "
                "speech origins and the voice. It reads; it presses "
                "nothing, writes nothing and sends nothing to a provider.",
     'params': {}},
    {'name': 'diagnostics',
     'summary': "What this add-on has switched on and what it has actually "
                "done: whether NVDA's speech filter registered, whether its "
                "speech can be muted, how many controls were read each way, "
                "and every layer's own report. Reading it is how 'the "
                "dialog kinds are not read' becomes a reason.",
     'params': {}},
    {'name': 'live',
     'summary': "Say that something changed while the user was looking "
                "somewhere else - a status line, a message that arrived. "
                "Said without moving the focus, and never twice in a row.",
     'params': {'text': dict(_STRING, required=True),
                'politeness': dict(_STRING,
                                   description="polite waits for whatever "
                                               "is being said; assertive "
                                               "interrupts it"),
                'source': dict(_STRING,
                               description="What it is about, said in "
                                           "front of it.")}},
    {'name': 'dialog_kind',
     'summary': "Say what kind of dialog is about to appear - question, "
                "warning, error - with its own tone, in front of NVDA's own "
                "report of it.",
     'params': {'kind': dict(_STRING, required=True,
                             description='question, information, warning '
                                         'or error'),
                'label': dict(_STRING,
                              description="The word to say, in the user's "
                                          "own language. Titan sends the "
                                          "one its own reader uses.")}},
    {'name': 'state_suffix',
     'summary': "Add a state to the control NVDA reads next - 'checked', "
                "'unchecked' - when the state is Titan's own and the "
                "platform cannot report it.",
     'params': {'text': dict(_STRING, required=True)}},
    {'name': 'say_all',
     'summary': "Have NVDA read on from the review cursor.", 'params': {}},
    {'name': 'read_focus',
     'summary': "Have NVDA say the focused control again.", 'params': {}},
    {'name': 'review',
     'summary': "Move NVDA's review cursor and read what is there.",
     'params': {'where': dict(_STRING,
                              description="line, word, character, paragraph"),
                'direction': dict(_STRING,
                                  description="next, previous or current")}},
    {'name': 'mode',
     'summary': "Put NVDA into browse mode or focus mode.",
     'params': {'name': dict(_STRING, description="browse, focus or toggle")}},
    {'name': 'settings',
     'summary': "Every NVDA setting Titan may read or change, and whether "
                "the user has allowed changing them.", 'params': {}},
    {'name': 'setting',
     'summary': "Read one NVDA setting, or change it.",
     'params': {'name': dict(_STRING, required=True),
                'value': dict(_STRING)}},
    {'name': 'synths', 'summary': "NVDA's synthesizers.", 'params': {}},
    {'name': 'use_synth', 'summary': "Switch NVDA to another synthesizer.",
     'params': {'name': dict(_STRING, required=True)}, 'risk': 'confirm'},
    {'name': 'voices', 'summary': "The current synthesizer's voices.",
     'params': {}},
    {'name': 'use_voice', 'summary': "Switch NVDA to another voice.",
     'params': {'name': dict(_STRING, required=True)}, 'risk': 'confirm'},
    {'name': 'press',
     'summary': "Run one of NVDA's own commands, written kb:NVDA+f7. Off "
                "until the user switches it on in the add-on's settings.",
     'params': {'gesture': dict(_STRING, required=True)},
     'risk': 'always_confirm'},
]


def _on_bus_thread(function):
    """Run a handler where it arrives.

    ``serve`` would otherwise detect wxPython - NVDA has it - and marshal
    every call onto NVDA's main thread, waiting up to thirty seconds for it.
    That is exactly wrong here: an announcement must return to Titan in
    microseconds, and each handler already puts the part that touches NVDA
    onto the main thread itself. Titan is waiting on a pipe; a reader that
    made Titan's interface wait for speech would undo the work Titan did to
    stop doing that.
    """
    return function()


def start():
    """Join the bus. Returns True when the connection thread was started."""
    return titan_actions.serve(handlers(), id=CLIENT_ID, label=CLIENT_LABEL,
                               kind='client', actions=DECLARED,
                               marshal=_on_bus_thread)


def stop():
    from . import panner
    try:
        panner.PANNER.restore()
    finally:
        titan_actions.stop()

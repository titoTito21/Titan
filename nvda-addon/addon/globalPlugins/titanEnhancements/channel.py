# -*- coding: utf-8 -*-
"""What Titan says, said by NVDA - with everything Titan knew about it.

This is the receiving end of the structured channel. Titan invokes
``announce`` over the Action Bus; the call arrives on the bus thread, and
**nothing that touches NVDA may happen there**, so every one of these
marshals onto the main thread through ``queueHandler`` and returns at once.
Titan is waiting on the other end of a pipe: an announcement that blocked
until it had been spoken would make Titan's own interface wait for speech,
which is the thing Titan has spent a lot of effort not doing.

**Saying it twice is the failure to design against.** Before this add-on,
Titan's own ``announce_view_switched`` and ``announce_shell_group`` stayed
SILENT whenever the reader was not Titan Access, because NVDA would read the
list row itself and Titan's sentence would be a second copy. That is a real
loss - "Applications, 1 of 4, tab" carries three things the row does not -
so the rule is inverted here: an announcement carrying ``replaces_focus``
tells the add-on that NVDA's own report of the object about to be focused is
this same event, and it is suppressed once. See ``focus.py``.
"""

import time

from . import compat
from . import focus
from . import interject
from . import prosody

#: A ``replaces_focus`` mark is good for this long. Titan announces and then
#: moves the focus, which is microseconds apart; a mark that outlived that
#: would eat the report of whatever the user did next.
REPLACE_WINDOW = 1.5


def _main_thread(function):
    """Run ``function`` on NVDA's main thread. Never waits for it."""
    if compat.queueHandler is None:
        function()
        return
    compat.queueHandler.queueFunction(compat.queueHandler.eventQueue, function)


def _priority(announcement):
    """NVDA's own speech priority for this announcement.

    Titan's ``interrupt`` is a boolean and NVDA's model is richer, so the
    two are mapped rather than one being forced onto the other: something
    that interrupts is NOW, and something that does not is queued behind
    whatever is being said. That is exactly the distinction Titan Access had
    to build a whole utterance queue to get, and NVDA has it already.
    """
    try:
        from speech.priorities import SpeechPriority
    except Exception:                                # noqa: BLE001
        return None
    return SpeechPriority.NOW if announcement.get('interrupt', True) \
        else SpeechPriority.NORMAL


class Channel:
    """Titan's announcements, in NVDA."""

    #: The last few announcements Titan made, as they arrived. The speech
    #: log says what NVDA said; this says what it was ASKED to say, and the
    #: two together are what tell "Titan never sent it" from "it was sent
    #: and something ate it".
    HEARD_KEEP = 10

    def __init__(self):
        self.heard = []
        self.enabled = True
        self.braille_enabled = True
        # `prosody.build` took two of these and nothing passed them, and
        # the third did not exist - so three switches on the settings page
        # were switches that did nothing. A switch that lies is worse than
        # one that is absent. They are three different questions: where the
        # voice is, whether a tone stands in when it cannot be moved, and
        # whether the pitch and rate Titan asks for are applied at all.
        self.position_enabled = True
        self.marker_enabled = True
        self.prosody_enabled = True
        self.last_notes = []
        self.last_text = ''
        self.spoken = 0

    # ------------------------------------------------------------ announce
    def announce(self, **announcement):
        """The one call Titan makes. Answers what was and was not applied.

        The FIRST line notes that Titan is talking through this channel at
        all, before any of the reasons this call might do nothing. That is
        deliberate: it is what tells a Titan that coordinates with the
        add-on from one whose `messages.py` predates the channel and
        announces past it through `accessible_output3`, and it is true the
        moment Titan calls - whether or not the user has the announcements
        switched off, and whether or not there was anything to say.
        """
        focus.note_titan_spoke()
        focus.cancel_pending_read()
        try:
            self.heard.append({
                'at': time.time(),
                'text': str(announcement.get('text') or '')[:90],
                'replaces_focus': bool(announcement.get('replaces_focus')),
                'segments': len(announcement.get('segments') or []),
                'position': announcement.get('position', 0),
                'pitch': announcement.get('pitch', 0),
            })
            del self.heard[:-self.HEARD_KEEP]
        except Exception:                            # noqa: BLE001
            pass
        if not self.enabled:
            return {'spoken': False, 'reason': 'the channel is switched off'}
        if focus.standing_down():
            return {'spoken': False,
                    'reason': 'Titan Access is the reader, so NVDA stands down'}
        text = prosody.spoken_text(announcement)
        if not text:
            return {'spoken': False, 'reason': 'there is nothing to say'}

        if announcement.get('replaces_focus'):
            focus.replace_next(time.time() + REPLACE_WINDOW)

        sequence, notes = prosody.build(
            announcement,
            allow_pan=self.position_enabled,
            allow_marker=self.marker_enabled,
            allow_prosody=self.prosody_enabled)
        self.last_notes = list(notes)
        self.last_text = text
        priority = _priority(announcement)
        braille_text = announcement.get('braille')
        if braille_text is None:
            braille_text = text

        def speak():
            self.spoken += 1
            if compat.speech is not None:
                try:
                    if announcement.get('interrupt', True):
                        compat.speech.cancelSpeech()
                    if priority is not None:
                        compat.speech.speak(sequence, priority=priority)
                    else:
                        compat.speech.speak(sequence)
                except Exception as error:           # noqa: BLE001
                    if compat.log is not None:
                        compat.log.error(f'Titan announcement failed: {error}')
            if self.braille_enabled and braille_text:
                self._braille(str(braille_text))

        _main_thread(speak)
        return {'spoken': True, 'text': text, 'notes': notes}

    # ------------------------------------------------------------- braille
    def _braille(self, text):
        if compat.braille is None:
            return
        try:
            handler = getattr(compat.braille, 'handler', None)
            if handler is not None:
                handler.message(text)
        except Exception:                            # noqa: BLE001
            pass

    def braille(self, text='', **_):
        """Braille alone - a status line, a count, something not worth saying."""
        if not self.braille_enabled:
            return {'shown': False, 'reason': 'braille is switched off'}
        message = str(text or '')
        if not message:
            return {'shown': False, 'reason': 'there is nothing to show'}
        _main_thread(lambda: self._braille(message))
        return {'shown': True}

    # ------------------------------------------------------------ the rest
    def interrupt(self, **_):
        def stop():
            if compat.speech is not None:
                try:
                    compat.speech.cancelSpeech()
                except Exception:                    # noqa: BLE001
                    pass
            from . import panner
            panner.PANNER.restore()
        _main_thread(stop)
        return {'stopped': True}

    def speaking(self, **_):
        """Whether NVDA is saying something right now.

        Asked by Titan before it decides whether to interrupt. There is no
        single flag for this in NVDA, so the synth is asked directly and an
        answer that cannot be had is reported as unknown rather than as no -
        a false 'no' makes Titan speak over the reader.
        """
        from . import panner
        synth = panner.current_synth()
        state = getattr(synth, 'isSpeaking', None) if synth is not None else None
        if state is None:
            try:
                import speech
                state = bool(getattr(speech, 'isPaused', False)) or None
            except Exception:                        # noqa: BLE001
                state = None
        return {'speaking': None if state is None else bool(state),
                'synth': str(getattr(synth, 'name', '') or '')}

    def beep(self, hz=660, milliseconds=40, position=0, **_):
        """A tone where Titan says the thing is. Native, so any synth."""
        marker = prosody.position_marker(position, int(hz), int(milliseconds))
        if marker is None:
            return {'played': False, 'reason': 'this NVDA has no BeepCommand'}

        def play():
            if compat.speech is not None:
                compat.speech.speak([marker])
        _main_thread(play)
        return {'played': True}

    # -------------------------------------------------------- capabilities
    def capabilities(self, **_):
        """What Titan may send, asked rather than assumed on the far side.

        Titan composes a DIFFERENT announcement depending on the answer -
        a position it can send as a position, or one it has to fold into a
        sentence - so this is read at connection and whenever the synth
        changes.
        """
        from . import panner
        report = panner.PANNER.report()
        # **A channel that is switched off says so.** It used to answer
        # `announce: True` whatever the switch said, and then drop every
        # announcement with a reason nobody reads - so a user who turned
        # Titan's announcements off did not get NVDA's own behaviour back,
        # they got SILENCE: Titan asks `replaces_focus` before it says the
        # tab bar or a shell group at all, was told yes, said it into this
        # channel, and the channel threw it away. Off must mean "behave as
        # though this add-on were not installed", which is what Titan does
        # with an answer of no.
        on = bool(self.enabled)
        return {
            'announce': on,
            'braille': (on and compat.braille is not None
                        and self.braille_enabled),
            'position': bool(on and report['can_place']
                             and self.position_enabled
                             and panner.PANNER.enabled),
            'position_marker': (on and compat.BeepCommand is not None
                                and self.marker_enabled),
            'pitch': (on and compat.PitchCommand is not None
                      and self.prosody_enabled),
            'rate': (on and compat.RateCommand is not None
                     and self.prosody_enabled),
            'volume': (on and compat.VolumeCommand is not None
                       and self.prosody_enabled),
            'queue': on,
            'replaces_focus': on,
            # Whether the three parts can be said at three pitches in ONE
            # utterance. Without PitchCommand they would all be the same
            # tone, and Titan should send the flat sentence instead of a
            # shape nothing acts on.
            'segments': (on and compat.PitchCommand is not None
                         and self.prosody_enabled),
            'synth': report['synth'],
            'channels': report['channels'],
            'problem': report['problem'],
            'missing': compat.missing(),
            **interject.capabilities(),
        }


#: The one channel.
CHANNEL = Channel()

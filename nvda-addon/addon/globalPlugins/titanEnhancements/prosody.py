# -*- coding: utf-8 -*-
"""One of Titan's announcements, as a sequence NVDA can speak.

Titan says things with structure - a position in the stereo image, a pitch
offset, a role, a place in a list - and the only thing that ever crossed to
NVDA was the text. This is where the rest of it is put back, in NVDA's own
terms:

* ``PitchCommand`` / ``RateCommand`` / ``VolumeCommand`` for the prosody.
  Every synthesizer that declares them in ``supportedCommands`` honours
  them, and one that does not is not lied to - the command is left out.
* ``CallbackCommand`` around the text for the position. A callback runs in
  NVDA's main thread **when speech reaches that point**, which is the timing
  this needs: the pan has to be standing while this fragment is audible and
  gone afterwards, and the moment the sequence was queued is neither.
* ``BeepCommand``, which carries its own ``left`` and ``right``, as the
  honest fallback when the stream cannot be panned at all. A position that
  cannot be heard in the voice is still heard.

**The scales are Titan's, deliberately.** Titan's ``pitch_offset`` runs -10
to 10 and its own ``stereo_speech`` applies it as ``pitch + offset * 5`` on a
0..99 scale; NVDA's ``PitchCommand(offset=)`` is an offset on its own 0..100
setting. So ``offset * 5`` is the same number in both, and nothing has to be
guessed at or tuned by ear.
"""

from . import compat
from . import panner

#: Titan's -10..10 scales onto NVDA's 0..100 settings.
SCALE = 5

#: The beep that stands in for a position the voice cannot carry.
MARKER_HZ = 660
MARKER_MS = 40


def _supported(synth, command):
    """Whether this synthesizer really honours ``command``."""
    if command is None or synth is None:
        return False
    try:
        return command in synth.supportedCommands
    except Exception:                                # noqa: BLE001
        # A driver that will not answer is assumed not to support it: an
        # unsupported command is dropped by NVDA anyway, but a driver that
        # raises when asked is one to stay away from.
        return False


def _segments_of(announcement):
    """``[(text, pitch)]`` Titan sent, or None.

    Refused rather than half-read when it is the wrong shape: a malformed
    segment list would otherwise become a sequence NVDA says nothing for,
    and the flat text is right there beside it.
    """
    raw = announcement.get('segments')
    if not raw:
        return None
    parts = []
    for entry in raw:
        try:
            text, pitch = entry[0], entry[1]
        except (TypeError, IndexError, KeyError):
            return None
        text = str(text or '')
        if not text.strip():
            continue
        try:
            parts.append((text, float(pitch or 0)))
        except (TypeError, ValueError):
            parts.append((text, 0.0))
    return parts or None


def _offset(value):
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(-10, min(10, number)) * SCALE


def _text_of(announcement):
    text = announcement.get('text')
    return '' if text is None else str(text)


def spoken_text(announcement):
    """The whole sentence, with the role and the place in the list.

    Titan usually composes this itself - ``"Applications, 1 of 4, tab"`` -
    but a caller that sends the parts separately gets them assembled here,
    in the order NVDA itself uses: what it is, then what state it is in,
    then where it is among its siblings.
    """
    parts = [_text_of(announcement)]
    role = str(announcement.get('role') or '').strip()
    if role:
        parts.append(role)
    states = announcement.get('states') or []
    if isinstance(states, (list, tuple)):
        parts.extend(str(state) for state in states if str(state).strip())
    index = announcement.get('index')
    count = announcement.get('count')
    if index not in (None, '') and count not in (None, ''):
        try:
            parts.append(f'{int(index)} / {int(count)}')
        except (TypeError, ValueError):
            pass
    return ', '.join(part for part in parts if str(part).strip())


def build(announcement, synth=None, allow_pan=True, allow_marker=True,
          allow_prosody=True):
    """``announcement`` -> (sequence, notes).

    ``notes`` says what could not be applied, so the caller can report it
    rather than the position silently going missing.
    """
    if synth is None:
        synth = panner.current_synth()
    notes = []
    sequence = []
    text = spoken_text(announcement)
    if not text:
        return [], notes

    position = announcement.get('position', 0) or 0
    try:
        position = float(position)
    except (TypeError, ValueError):
        position = 0.0

    # ------------------------------------------------------------- prosody
    pitch = _offset(announcement.get('pitch', 0)) if allow_prosody else 0
    if pitch and _supported(synth, compat.PitchCommand):
        sequence.append(compat.PitchCommand(offset=pitch))
    elif pitch:
        notes.append('this synthesizer does not take a pitch change')

    rate = _offset(announcement.get('rate', 0)) if allow_prosody else 0
    if rate and _supported(synth, compat.RateCommand):
        sequence.append(compat.RateCommand(offset=rate))
    elif rate:
        notes.append('this synthesizer does not take a rate change')

    volume = _offset(announcement.get('volume', 0)) if allow_prosody else 0
    if volume and _supported(synth, compat.VolumeCommand):
        sequence.append(compat.VolumeCommand(offset=volume))
    elif volume:
        notes.append('this synthesizer does not take a volume change')

    language = str(announcement.get('language') or '').strip()
    if language and compat.LangChangeCommand is not None \
            and _supported(synth, compat.LangChangeCommand):
        sequence.append(compat.LangChangeCommand(language))

    if announcement.get('spelling') and compat.CharacterModeCommand is not None \
            and _supported(synth, compat.CharacterModeCommand):
        sequence.append(compat.CharacterModeCommand(True))

    # ------------------------------------------------------------ position
    placed = False
    if allow_pan and abs(position) > 1e-6 and compat.CallbackCommand is not None:
        # The callback is what makes the timing right, and it is also what
        # makes the restore certain: it is queued in the same sequence, so a
        # sequence that is spoken at all always ends with the pan undone.
        def _place(_position=position):
            panner.PANNER.place(_position)

        def _restore():
            panner.PANNER.restore()

        sequence.append(compat.CallbackCommand(_place, name='titanPan'))
        placed = True

    parts = _segments_of(announcement)
    if parts is not None and allow_prosody and _supported(synth,
                                                          compat.PitchCommand):
        # Titan Access's own three-part shape: the name at the neutral tone,
        # the control type a little lower, a state a little higher. It is
        # how somebody working by ear tells "Save, button" from a list item
        # called "Save button", and it is one utterance, so nothing in it
        # can be cut off by the part after it.
        for index, (piece, offset) in enumerate(parts):
            sequence.append(compat.PitchCommand(offset=_offset(offset)))
            sequence.append(piece if index == len(parts) - 1
                            else piece + ', ')
        sequence.append(compat.PitchCommand(offset=0))
    else:
        sequence.append(text)

    if placed:
        sequence.append(compat.CallbackCommand(_restore, name='titanUnpan'))

    if announcement.get('spelling') and compat.CharacterModeCommand is not None \
            and _supported(synth, compat.CharacterModeCommand):
        sequence.append(compat.CharacterModeCommand(False))

    # --------------------------------------------- the honest fallback beep
    if allow_marker and abs(position) > 1e-6 and not _can_pan_now(synth):
        marker = position_marker(position)
        if marker is not None:
            sequence.insert(0, marker)
            notes.append(panner.last_problem()
                         or 'the position is carried by a tone rather than '
                            'by the voice')
    return sequence, notes


def _can_pan_now(synth):
    """Whether the voice itself can be moved, right now, by either layer."""
    return panner.PANNER.can_place()


def position_marker(position, hz=MARKER_HZ, milliseconds=MARKER_MS):
    """A short tone at the place the voice could not be moved to.

    ``BeepCommand`` carries its own left and right channel volumes, so this
    needs nothing below NVDA and works on every synthesizer - including one
    whose stream is mono, because the beep is NVDA's own audio and not the
    synthesizer's.
    """
    if compat.BeepCommand is None:
        return None
    left, right = panner.constant_power(position)
    try:
        return compat.BeepCommand(hz, milliseconds,
                                  left=int(round(left * 100)),
                                  right=int(round(right * 100)))
    except Exception:                                # noqa: BLE001
        return None

# -*- coding: utf-8 -*-
"""Not saying the same thing twice, and knowing when to say nothing at all.

Two different silences live here.

**The first is one focus event.** Titan composes announcements NVDA cannot
compose - "Applications, 1 of 4, tab" for a row whose text is just
"Applications", the name of the shell group the keyboard has entered, the
count of search results. Titan announces, and then moves the focus; NVDA
then reads the object, and the user hears the same thing twice with the
second copy worse than the first. Titan's own answer until now was to stay
silent whenever the reader was not Titan Access, which loses the extra
information rather than the duplicate. So an announcement may carry
``replaces_focus``, and the very next focus event inside Titan's own process
is **read with speech muted**.

Muted rather than skipped, and that is the whole care in this module: NVDA's
``event_gainFocus`` does more than speak - it moves the review cursor,
updates braille, and lets the object cache itself - and a global plugin that
simply does not call ``nextHandler`` throws all of that away to stop one
sentence. Speech mode goes off for the length of the call and back
immediately after, so everything except the duplicate still happens.

**The second is the whole add-on.** If Titan Access is the reader, Titan is
already speaking through its own engine, and NVDA speaking as well is two
readers over each other. Titan says so (``stand_down``) and everything here
answers no until it says otherwise.
"""

import threading
import time

from . import compat
from . import i18n

_ = i18n.install(globals())

_LOCK = threading.RLock()
_replace_until = 0.0
_standing_down = False
_titan_pid = 0
_suppressed = 0
_titan_spoke = 0.0


# --------------------------------------------------------------------------- #
# Standing down for Titan Access
# --------------------------------------------------------------------------- #
def stand_down(down=True):
    """Titan Access has taken over, or given the reader back.

    **The user's own switch decides whether this is obeyed.** It used to be
    obeyed unconditionally while `configSpec.apply()` merely cleared the
    flag once, so unticking "stay silent while Titan Access is the reader"
    changed nothing the next time Titan asked - a switch that lies, which
    is the one thing this add-on keeps taking back out.
    """
    global _standing_down
    if down and not _stand_down_wanted():
        with _LOCK:
            _standing_down = False
        return False
    with _LOCK:
        _standing_down = bool(down)
    return _standing_down


def _stand_down_wanted():
    try:
        from . import configSpec
        return bool(configSpec.read().get('standDownForTitanAccess', True))
    except Exception:                                # noqa: BLE001
        return True


def standing_down():
    with _LOCK:
        if _standing_down and not _stand_down_wanted():
            # Asked here as well, because the switch can be unticked while
            # we are already standing down, and the user would otherwise
            # have to make Titan Access hand the reader back to be heard
            # again.
            return False
        return _standing_down


# --------------------------------------------------------------------------- #
# Whose window this is
# --------------------------------------------------------------------------- #
def set_titan_pid(pid):
    """Titan's own process id, told to us by Titan over the bus.

    **Matched by process, never by executable name.** Titan run from source
    is ``python.exe``, and an add-on that recognised Titan by that name
    would take over the focus reporting of every Python script on the
    machine.
    """
    global _titan_pid
    try:
        value = int(pid or 0)
    except (TypeError, ValueError):
        value = 0
    with _LOCK:
        _titan_pid = value
    return value


def titan_pid():
    with _LOCK:
        return _titan_pid


def is_titan_object(obj):
    """Whether this NVDA object belongs to the Titan we are connected to."""
    pid = titan_pid()
    if not pid or obj is None:
        return False
    try:
        return int(getattr(obj, 'processID', 0) or 0) == pid
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# The one-event mark
# --------------------------------------------------------------------------- #
def replace_next(until):
    """Titan has just said what the next focus event would have said."""
    global _replace_until
    with _LOCK:
        _replace_until = float(until)


def take_mark():
    """Consume the mark. True at most once, and only while it is fresh."""
    global _replace_until
    with _LOCK:
        if _replace_until and time.time() <= _replace_until:
            _replace_until = 0.0
            return True
        _replace_until = 0.0
        return False


def suppressed():
    return _suppressed


# --------------------------------------------------------------------------- #
# Whether Titan is coordinating with us at all
# --------------------------------------------------------------------------- #
def note_titan_spoke():
    """Titan has announced something through this channel."""
    global _titan_spoke
    with _LOCK:
        _titan_spoke = time.time()


def spoke_at():
    with _LOCK:
        return _titan_spoke


def titan_coordinates():
    """Whether Titan is announcing THROUGH US rather than past us.

    This decides whether the add-on may stand in for NVDA's own report of a
    control, and the reason it has to be asked is a regression this add-on
    caused: reading every control in Titan in three tones also replaced the
    tab bar's report - and what made that row a TAB BAR was said by Titan,
    through `accessible_output3`, which this add-on never sees. The user
    heard the tab bar announcement disappear.

    A Titan whose `messages.py` predates the reader channel announces that
    way and never calls in here at all, so "has Titan ever announced
    through this channel" tells the two apart exactly. Until it has, NVDA's
    own reporting is left alone: taking it over to add three tones, and
    losing a sentence in the process, is not a trade worth making.
    """
    with _LOCK:
        return bool(_titan_spoke)


# --------------------------------------------------------------------------- #
# Muting, across NVDA's two spellings of it
# --------------------------------------------------------------------------- #
def _get_mode():
    speech = compat.speech
    if speech is None:
        return None, None
    state = getattr(speech, 'getState', None)
    if callable(state):
        try:
            return 'state', state().speechMode
        except Exception:                            # noqa: BLE001
            pass
    mode = getattr(speech, 'speechMode', None)
    if mode is not None:
        return 'attribute', mode
    return None, None


def _set_mode(kind, value):
    speech = compat.speech
    if speech is None or kind is None:
        return
    if kind == 'state':
        setter = getattr(speech, 'setSpeechMode', None)
        if callable(setter):
            try:
                setter(value)
            except Exception:                        # noqa: BLE001
                pass
        return
    try:
        speech.speechMode = value
    except Exception:                                # noqa: BLE001
        pass


def _off_value(kind):
    speech = compat.speech
    if speech is None:
        return None
    if kind == 'state':
        mode = getattr(speech, 'SpeechMode', None)
        return getattr(mode, 'off', None) if mode is not None else None
    return getattr(speech, 'speechMode_off', None)


def can_mute():
    """Whether this NVDA's speech can really be turned off and back.

    Asked, not assumed. A mute that quietly does nothing is the worst
    possible outcome for anything that stands in for NVDA's own report:
    NVDA reads the control, we read it again, and the user hears everything
    twice with no clue why.
    """
    kind, _previous = _get_mode()
    return kind is not None and _off_value(kind) is not None


class muted:
    """Speech off for the length of a ``with`` block, then back as it was.

    Restoring what was THERE rather than setting 'talk' is the point: a user
    who has NVDA in beeps mode, or has muted speech deliberately, must not
    have it turned on again by a Titan announcement.

    ``worked`` says whether it really happened, because a caller that was
    going to speak in NVDA's place needs to know that NVDA has been kept
    quiet before it does.
    """

    def __init__(self):
        self._kind = None
        self._previous = None
        self.worked = False

    def __enter__(self):
        kind, previous = _get_mode()
        off = _off_value(kind)
        if kind is None or off is None:
            return self
        self._kind, self._previous = kind, previous
        _set_mode(kind, off)
        self.worked = True
        return self

    def __exit__(self, *_exception):
        if self._kind is not None:
            _set_mode(self._kind, self._previous)
        self._kind = None
        return False


#: How many focus reports were read in Titan Access's three tones instead
#: of NVDA's one. Shown by the status command, because "it is not doing it"
#: and "it is doing it and you cannot hear the difference" are different
#: problems.
_pitched = 0


def pitched():
    return _pitched


def module_for(obj):
    """The reader module for this window, or None. Cached per process."""
    try:
        from . import semantics
        return semantics.module_for(obj, semantics.application_of(obj))
    except Exception:                                # noqa: BLE001
        return None


def _menu_left(obj, module):
    """Say that the keyboard has left a menu, which nothing else says.

    Every reader announces a menu OPENING - NVDA speaks a menu bar and a
    popup menu as a full focus report when the focus enters them. None of
    them announces one CLOSING, so a user who pressed Escape, or pressed a
    key the menu did not take, is left guessing whether their next
    keystroke is a command or a letter in a document. JAWS has said this
    for twenty years and it is the one thing in this module that is not
    about not repeating somebody.
    """
    from . import configSpec
    if not configSpec.read().get('menuLeaving', True):
        return False
    try:
        from . import ancestry
        _entered, left = ancestry.changes(obj, module)
    except Exception:                                # noqa: BLE001
        return False
    if not left:
        return False
    word = ancestry.leaving_word(left)
    if not word:
        return False
    try:
        from . import earcons
        earcons.play_named('menu_closed.ogg')
    except Exception:                                # noqa: BLE001
        pass
    try:
        from . import interject
        # In FRONT of NVDA's own report of whatever the keyboard landed
        # on, and in the same utterance, so it cannot be cut off by it.
        interject.prefix_next(word, 'context')
        return True
    except Exception:                                # noqa: BLE001
        return False


def handle_gain_focus(obj, next_handler):
    """The global plugin's ``event_gainFocus``, factored out to be testable.

    Three outcomes, and the order matters.

    1. Titan has just SAID what this event would say (``replaces_focus``):
       the report is muted and nothing replaces it.
    2. Otherwise, inside Titan's own windows, the control is read the way
       Titan's own reader reads one - the name, then the type lower, then
       the state higher, in one utterance. NVDA's own report is muted and
       ours takes its place.
    3. Everywhere else NVDA is the reader and is left entirely alone. That
       line is deliberate: NVDA's reporting outside Titan knows about
       tables, landmarks, browse mode and a hundred things this does not,
       and replacing it wholesale to gain three tones would be a trade
       nobody asked for.

    Returns 'replaced', 'pitched' or None.
    """
    global _suppressed, _pitched
    module = module_for(obj)
    _menu_left(obj, module)
    if not is_titan_object(obj):
        # **A TCE application is Titan too.** It runs in a subprocess of
        # its own, so it is not "Titan's window" by pid - but tNotes and
        # the file manager are as much part of this desktop as the main
        # window is, and a reader that knows what their rows MEAN is the
        # whole of what an app module buys anywhere else. Titan says which
        # process is which; :mod:`semantics` is what it means.
        if _application_reading(obj, next_handler):
            return 'semantic'
        # **And the rest of Windows, when the user has asked for it.** What
        # a sighted person gets from a window before a word is read - which
        # part of it this is, what kind of row that is - is not something
        # NVDA withholds on purpose; it is something nothing was in a
        # position to say. Titan is, so it does, everywhere.
        if _windows_reading(obj, next_handler):
            return 'windows'
        # Outside Titan, NVDA is the reader and is left alone - but Titan's
        # own cursor cues can still be played over it, which is where they
        # belong: Titan's own windows already make their own sounds. And
        # WHERE the report is spoken from is not WHAT it says, so it can be
        # placed without taking anything away: the words stay NVDA's, with
        # its tables, its landmarks and its browse mode.
        _cue(obj)
        _place_next_report(obj, everywhere=True)
        next_handler()
        return None
    if take_mark():
        _suppressed += 1
        with muted():
            next_handler()
        return 'replaced'
    if not _pitched_wanted() or not titan_coordinates():
        _place_next_report(obj)
        next_handler()
        return None
    if not can_mute():
        # Speaking in NVDA's place without being able to keep it quiet is
        # every control announced twice. Better one tone than two voices.
        _place_next_report(obj)
        next_handler()
        return None
    from . import elements
    segments = elements.describe(obj)
    if not segments or not elements.can_pitch():
        next_handler()
        return None
    # **Where the control is, said from there.** Titan Access places every
    # focus cue by the middle of the control against the width of the
    # screen, and the whole claim of this add-on is that a Titan control
    # sounds the same under NVDA. Nothing did this: positioned speech was
    # applied only to an announcement Titan SENT, and Titan sends a
    # position for the few things whose place it knows and 0 for every
    # ordinary control - so the switch was on, the machine could pan, and
    # nothing ever moved.
    placed, tone = placement_of(obj)
    # Muted rather than skipped, for the reason this whole module exists:
    # `event_gainFocus` also moves the review cursor, updates braille and
    # lets the object cache itself, and none of that should be lost to
    # change how one sentence sounds.
    with muted():
        next_handler()
    _say_unless_titan_does(_placed_sequence(elements.sequence(segments),
                                            placed, tone))
    _pitched += 1
    return 'pitched'


def placement_of(obj):
    """Where this control belongs in the voice: ``(position, pitch)``.

    Two different questions, and which one is asked depends on what the
    control IS.

    * A control has a place on the screen, so it is placed left and right.
      ``None`` rather than 0.0 when the rectangle cannot be read: a control
      whose place is unknown must be left where the voice already is, not
      moved to the centre - moving it is a pan and a restore for no
      information at all.
    * A ROW of a list is placed up and down instead. Panning a list by
      where it happens to sit on the screen says the same thing about every
      row in it; what a reader wants from a row is how far down the list it
      is, and that is a TONE - the top of the list high, the bottom low,
      which is what Titan Access's own row cue has always said.
    """
    if not _position_wanted():
        return None, 0.0
    from . import panner
    if not panner.PANNER.enabled:
        return None, 0.0
    try:
        index, count = _row_of(obj)
        if index and count and count > 1:
            # A row was always a tone: panning a list by where it happens to
            # sit says the same thing about every row in it.
            return None, panner.list_pitch(index, count)
        # And now a control's own place is one too, unless the user has
        # asked for it across. See `panner.position_way`: panning is exact
        # on a synthesizer that feeds a stereo stream and is NVDA's whole
        # audio session everywhere else, and a session is put back on a
        # timer rather than at the end of the line - which is the cutting.
        tone = panner.screen_pitch(obj) if panner.may_pitch() else 0.0
        where = panner.screen_position(obj) if panner.may_pan() else None
        return where, tone
    except Exception:                                # noqa: BLE001
        return None, 0.0


def _row_of(obj):
    """``(index, count)`` when this is a row in a collection, else (0, 0)."""
    from . import earcons
    role = str(getattr(getattr(obj, 'role', None), 'name', '') or '').upper()
    if role not in earcons.LIST_ITEM:
        return 0, 0
    try:
        info = obj.positionInfo or {}
    except Exception:                                # noqa: BLE001
        return 0, 0
    try:
        return (int(info.get('indexInGroup') or 0),
                int(info.get('similarItemsInGroup') or 0))
    except (TypeError, ValueError):
        return 0, 0


#: How many controls have been read as what the application says they are.
_semantic = 0


def semantic():
    return _semantic


def _application_reading(obj, next_handler):
    """Read a TCE application's control as the application means it.

    Answers True when it really did - and only then, because everything
    that follows in `handle_gain_focus` is the ordinary path and must run
    when this one has nothing to add. The rules are the same as for
    Titan's own windows: NVDA's report is MUTED rather than skipped (the
    review cursor, braille and the object cache all still happen), and a
    reader that cannot be kept quiet is left alone entirely rather than
    talked over.
    """
    global _semantic
    try:
        from . import semantics
        parts, application = semantics.describe(obj)
    except Exception:                                # noqa: BLE001
        return False
    if application is None:
        return False
    # This IS a Titan application's window, whether or not there was
    # anything extra to say about this particular control, so its cursor
    # cues belong to the application rather than to the rest of the
    # machine - Titan's own applications make their own sounds.
    if not parts or not can_mute():
        _place_next_report(obj)
        next_handler()
        return True
    if _only_context(parts):
        # The folder the file manager has just opened, said in front of
        # NVDA's own report of whatever the keyboard is on - not instead
        # of it. Same rule, same reason as the windows path.
        _add_context(parts, obj, next_handler, everywhere=False)
        _semantic += 1
        return True
    from . import elements
    sequence = elements.sequence(parts)
    if not sequence:
        next_handler()
        return True
    with muted():
        next_handler()
    placed, tone = placement_of(obj)
    _say_unless_titan_does(_placed_sequence(sequence, placed, tone))
    _semantic += 1
    return True


#: How many controls anywhere on the machine were read with the semantics
#: a sighted person reads off the layout.
_windows = 0


def windows():
    return _windows


def _windows_reading(obj, next_handler):
    """The semantic layer for a window that is not Titan's own.

    Two different answers, and the difference matters more here than
    anywhere else in this module, because outside Titan NVDA is the reader
    and knows things this does not:

    * A ROW of a report-mode list is READ here - the name and then every
      column with its own heading - because NVDA says the first column and
      nothing else, and the rest is the row.
    * Everything else is only ADDED to: the part of the window the
      keyboard has moved into goes in front of NVDA's own report, in the
      same utterance, and NVDA says the control exactly as it always did.

    Replacing NVDA's reporting wholesale out here would be the trade this
    add-on has refused from the first line it was written: NVDA knows
    about tables, landmarks, browse mode and a hundred things this does
    not.
    """
    global _windows
    module = module_for(obj)
    # **A picture, said as what it is.** "Graphic" is one word for an icon,
    # a photograph and something that is still moving, and the difference
    # between them is the whole of what a person decides from. This is a
    # replacement rather than an addition because the report it replaces is
    # two words long and this is strictly more of them.
    said = _picture_reading(obj, next_handler)
    if said:
        return True
    if _label_reading(obj, next_handler, module):
        return True
    try:
        from . import semantics
        parts = semantics.windows_parts(obj, module)
    except Exception:                                # noqa: BLE001
        parts = []
    if not parts and not _pitched_everywhere():
        return False
    if _pitched_everywhere() and can_mute():
        # **The whole machine read the way Titan is read**, when the user
        # has asked for it: the name, the control type a little lower, the
        # state a little higher. Where the user now IS still goes in front
        # of it, in the same utterance.
        if parts and _only_context(parts):
            try:
                from . import interject
                interject.prefix_next(parts[0][0], parts[0][1])
            except Exception:                        # noqa: BLE001
                pass
        from . import elements
        segments = elements.describe(obj)
        if segments and elements.can_pitch():
            _cue(obj)
            with muted():
                next_handler()
            placed, tone = placement_of(obj)
            if not _position_everywhere():
                placed = None
            _say_unless_titan_does(_placed_sequence(
                elements.sequence(segments), placed, tone))
            _windows += 1
            return True
    if _only_context(parts):
        # Where the user now is, and nothing about the control itself: an
        # addition, never a replacement. Asking whether the control is a
        # list ITEM instead is what silenced NVDA's report of every row in
        # a list with no columns.
        _add_context(parts, obj, next_handler)
        _windows += 1
        return True
    if not can_mute():
        _place_next_report(obj, everywhere=True)
        next_handler()
        return True
    from . import elements
    sequence = elements.sequence(parts)
    if not sequence:
        return False
    _cue(obj)
    with muted():
        next_handler()
    placed, tone = placement_of(obj)
    # A row's TONE is part of what this reading says - how far down the
    # list it is - so it applies wherever the reading does. Moving the
    # voice left and right outside Titan is a separate thing the user has
    # to have asked for.
    if not _position_everywhere():
        placed = None
    _say_unless_titan_does(_placed_sequence(sequence, placed, tone))
    _windows += 1
    return True


#: How many pictures and how many unnamed controls were read as something
#: better than "graphic" and "button".
_pictures = 0
_labelled = 0


def pictures():
    return _pictures


def labelled():
    return _labelled


def _picture_reading(obj, next_handler):
    """A graphic read as an icon, a picture or an animation."""
    global _pictures
    from . import perProgram
    if not perProgram.value('graphicKinds', obj):
        return False
    try:
        from . import graphics
        if not graphics.is_pictorial(obj):
            return False
        parts = graphics.parts(obj)
    except Exception:                                # noqa: BLE001
        return False
    if not parts or not can_mute():
        return False
    from . import elements
    sequence = elements.sequence(parts)
    if not sequence:
        return False
    with muted():
        next_handler()
    placed, tone = placement_of(obj)
    if not _position_everywhere():
        placed = None
    _say_unless_titan_does(_placed_sequence(sequence, placed, tone))
    _pictures += 1
    _maybe_label(obj)
    return True


def _label_reading(obj, next_handler, module=None):
    """A control the program never named, read by the name we have for it.

    The label is spoken in its own voice class ('guessed'), which is not
    decoration: it is the difference between "the button is called Save"
    and "the button appears to say Save", and a listener is entitled to
    know which of those they are being told.
    """
    global _labelled
    try:
        from . import labels
        # `labels.applies` is the ONE place that decides whether a stored
        # name is used, and it is one place because it was two rules in one
        # function and one of them was wrong. See its docstring.
        label, source = labels.applies(obj, module)
    except Exception:                                # noqa: BLE001
        return False
    if not label:
        try:
            if labels.needs_one(obj):
                _maybe_label(obj)
        except Exception:                            # noqa: BLE001
            pass
        return False
    if not can_mute():
        return False
    from . import context
    from . import elements
    parts = [(label, 'name' if source == 'user' else 'guessed')]
    role = context.role_name(getattr(obj, 'role', None))
    if role:
        parts.append((role, 'kind'))
    sequence = elements.sequence(parts)
    if not sequence:
        return False
    with muted():
        next_handler()
    placed, tone = placement_of(obj)
    if not _position_everywhere():
        placed = None
    _say_unless_titan_does(_placed_sequence(sequence, placed, tone))
    _labelled += 1
    return True


def _maybe_label(obj):
    """Work out a name for an unnamed control, once, on a worker.

    Never on the focus path: it is a picture sent to an AI provider and an
    answer that takes seconds. The control being focused is read exactly as
    it would have been; the name arrives afterwards and is there the next
    time - which is the whole shape of this feature, since a toolbar the
    user passes fifty times a day must cost one request in its life.
    """
    from . import perProgram
    # **Per PROGRAM.** Whether it is worth spending requests to name a
    # toolbar is a different answer in a media player and in a browser,
    # and one global switch answers it for the whole machine.
    if not perProgram.value('autoLabel', obj):
        return False
    # **There has to be somebody to ask.** Reading a control with AI is
    # Titan's work - Titan holds the provider and the key - so with Titan
    # not running there is no request to make, only a thread to start and
    # a refusal to log. Measured on a real session: eight ERROR lines
    # saying "Titan is not running", one per unnamed control the user
    # walked past, each with a thread behind it, on a machine where Titan
    # had never been started. A feature that cannot work stands down
    # quietly; it does not keep asking.
    try:
        from .link import LINK
        if not LINK.connected():
            return False
    except Exception:                                # noqa: BLE001
        return False
    try:
        from . import labels
        if not labels.needs_one(obj) or labels.get(obj):
            return False
    except Exception:                                # noqa: BLE001
        return False
    # One at a time, spaced out, and not at all once it has stood down.
    if not _label_may_ask():
        return False
    import threading

    def look():
        try:
            from . import graphics
            # **Windows' own recogniser first, and for the AUTOMATIC path
            # it is the only one.** It is local, private, free, and
            # answers in about a tenth of a second; the AI is a picture of
            # the user's screen sent to a provider and an answer that has
            # been measured taking longer than the bus waits for it -
            # "Titan did not answer within 12s", in the log, over and
            # over, from controls the reader chose to look at by itself.
            #
            # A reading somebody ASKED for still goes to the AI, which
            # understands what it reads. One the reader decided to make
            # on its own may not cost that.
            ok, said = graphics.label_locally(obj)
            if not ok and _label_ai_wanted():
                ok, said = graphics.label_with_ai(obj)
            elif not ok:
                # Which of the two it stopped at matters: the tier order
                # is the user's own setting, and "Windows read nothing,
                # and the AI was never asked" is a different situation
                # from "both tried and neither could".
                said = ('%s, and the AI was not asked because Windows\''
                        ' recogniser goes first'
                        % (str(said or '').strip() or 'it could not be read'))
        except Exception as error:                   # noqa: BLE001
            ok, said = False, str(error)
        _label_done(bool(ok and said))
        if ok and said:
            try:
                from . import live
                live.announce(said, 'polite')
            except Exception:                        # noqa: BLE001
                pass
            return
        # **A failure here used to be completely silent**, and this is the
        # feature most able to fail: it needs Titan running, its AI features
        # on and a vision provider with a key. The user switched on "work
        # out a name for an unnamed control", nothing ever happened, and
        # there was nowhere at all that said why - which is
        # indistinguishable from a switch that does nothing.
        _label_failed(said)
    threading.Thread(target=look, name='TitanLabel', daemon=True).start()
    return True


#: **One AI label at a time, and not for ever.**
#:
#: `_maybe_label` started a thread per unnamed control, and each one made
#: a bus call that waits up to twelve seconds. The Action Bus is ONE pipe:
#: tab through ten unnamed controls and that is ten calls queued nose to
#: tail, with every other call behind them - including the ones NVDA makes
#: on its own main thread. Seen in the log as "Titan did not answer within
#: 12s", and felt as a reader that has stopped.
#:
#: So: one in flight, a pause between them, and after a few failures in a
#: row the layer stands down for the session and says so. A Titan that
#: just failed to answer in twelve seconds will fail the next one too, and
#: asking anyway is how a feature that cannot work takes the reader with
#: it. Same discipline as the semantic layer, which measures itself and
#: stops.
_label_lock = threading.RLock()
_label_busy = False
_label_last = 0.0
_label_failures = 0

#: No more often than this, however many unnamed controls go past.
LABEL_GAP = 3.0

#: This many failures in a row and the layer is done for the session.
LABEL_GIVE_UP = 3


def _label_ai_wanted():
    """Whether the AI may be asked to name a control by ITSELF.

    Off unless the user has said the AI tier is what they want, which is
    the same switch that decides which recogniser reads an unreadable
    window - one answer to one question, rather than two switches that
    can disagree about whether a picture of the screen may be sent.
    """
    try:
        from . import configSpec
        return str(configSpec.read().get('ocrTier') or '').strip() == 'ai'
    except Exception:                                # noqa: BLE001
        return False


def label_layer_stood_down():
    with _label_lock:
        return _label_failures >= LABEL_GIVE_UP


def _label_may_ask():
    """Whether to ask Titan for a name right now. Never blocks."""
    with _label_lock:
        if _label_busy:
            return False
        if _label_failures >= LABEL_GIVE_UP:
            return False
        if time.time() - _label_last < LABEL_GAP:
            return False
        globals()['_label_busy'] = True
        globals()['_label_last'] = time.time()
        return True


def _label_done(worked):
    with _label_lock:
        globals()['_label_busy'] = False
        globals()['_label_last'] = time.time()
        if worked:
            globals()['_label_failures'] = 0
        else:
            globals()['_label_failures'] = _label_failures + 1


#: Why the last attempt to work out a name failed, and how many have.
#: Read by the diagnostics command, and said ONCE - the first time it
#: happens in a session - because a reader that explained it on every
#: unnamed control the user passed would be worse than the silence.
_label_trouble = {'why': '', 'failed': 0, 'said': False}


def label_trouble():
    return dict(_label_trouble)


def _label_failed(why):
    said = str(why or '').strip()
    first = not _label_trouble['said']
    _label_trouble['why'] = said
    _label_trouble['failed'] += 1
    # **Logged once, like it is said once.** The reason a name cannot be
    # worked out is a standing condition - no Titan, no key, the feature
    # switched off over there - so it is the same sentence every time, and
    # an ERROR per unnamed control turns the log into something nobody
    # reads at the moment it is most worth reading. The count is what says
    # how often it happened; `label_trouble()` and the diagnostics command
    # both carry it.
    if first and compat.log is not None:
        try:
            compat.log.error('Titan could not work out a name: %s' % said)
        except Exception:                            # noqa: BLE001
            pass
    if _label_trouble['said'] or not said:
        return
    _label_trouble['said'] = True
    if label_layer_stood_down():
        # Say WHY it will not try again, once: a feature that quietly
        # stopped is the thing this add-on keeps taking back out.
        said = _('{why} Working out names has been switched off for now.') \
            .format(why=said)
    try:
        from . import live
        live.announce(said, 'polite')
    except Exception:                                # noqa: BLE001
        pass


def _only_context(parts):
    """Whether this reading says WHERE the user is and nothing else.

    The one rule that decides whether we may stand in for NVDA, and it was
    got wrong: `_windows_reading` asked whether the control was a list ITEM
    and replaced NVDA's report whenever it was. A list item is not the same
    thing as a reading of one - NVDA's own settings dialog has a category
    list whose items have no columns at all, so the reading was the LIST's
    name and nothing else, and it replaced NVDA's report of the item. The
    user heard the list's label where the item should have been.

    So: a reading made only of context is an ADDITION - said in front of
    NVDA's own words, which still happen. Only a reading that carries the
    control's own content may take NVDA's place, and by then it is saying
    strictly more than NVDA would have.
    """
    return bool(parts) and all(voice == 'context' for _text, voice in parts)


def _add_context(parts, obj, next_handler, everywhere=True):
    """Say the context in front of NVDA's own report, and let it happen."""
    try:
        from . import interject
        interject.prefix_next(parts[0][0], parts[0][1])
    except Exception:                                # noqa: BLE001
        pass
    _cue(obj)
    _place_next_report(obj, everywhere=everywhere)
    next_handler()
    return True


def _pitched_everywhere():
    from . import configSpec
    return bool(configSpec.read().get('pitchedEverywhere', False))


def _position_everywhere():
    from . import configSpec
    return bool(configSpec.read().get('positionEverywhere', False))


def _position_wanted():
    from . import configSpec
    return bool(configSpec.read().get('position', True))


def _place_next_report(obj, everywhere=False):
    """Ask for NVDA's own next report of this control to be placed.

    Inside Titan this is the branch where the add-on is NOT standing in for
    NVDA - the three tones are switched off, or this NVDA cannot be muted -
    and the position is still worth having. Outside Titan it is behind its
    own switch, because it changes how every control on the whole machine
    is spoken, which is not a decision to make for somebody.
    """
    if everywhere:
        from . import configSpec
        if not configSpec.read().get('positionEverywhere', False):
            return False
    where, tone = placement_of(obj)
    if where is None and not tone:
        return False
    try:
        from . import interject
        return interject.place_next(where, pitch=tone)
    except Exception:                                # noqa: BLE001
        return False


def _placed_sequence(sequence, position, tone=0.0):
    """The reading, said at the control's own tone - and from its own place
    when the user has asked for that as well.

    Both, in that order, because they are not alternatives: 'both' is one of
    the three answers, and a caller handed a tone and a position meant both
    of them. Applying only the first is how a setting comes to be offered
    and quietly half-obeyed.
    """
    if not sequence:
        return sequence
    try:
        from . import configSpec
        from . import prosody
        if tone:
            sequence = prosody.pitch_sequence(sequence, tone)
        if position is None:
            return sequence
        placed, _notes = prosody.place_sequence(
            sequence, position,
            allow_marker=bool(configSpec.read().get('positionMarker', True)))
        return placed
    except Exception:                                # noqa: BLE001
        return sequence


#: Reading a control is IMMEDIATE. There is no delay here and there must
#: not be one.
#:
#: Titan announces some controls itself - the tab bar says "Tab bar, tab,
#: Applications, 1 of 6", which is three things the row's own text does not
#: carry - and either it or the focus event can land first. Waiting a beat
#: to find out which was tried and was the wrong trade: it put that delay
#: in front of EVERY control, and a reader that answers a moment late is a
#: reader that feels broken, which is a worse fault than the one it fixed.
#:
#: The race is settled the way a screen reader settles every other race
#: instead: whoever speaks second and means to interrupt, wins. Titan's
#: announcement carries `interrupt`, so it cancels this and is heard; and
#: an announcement that arrives FIRST leaves a mark, which is checked
#: before a word of this is spoken. What that costs when Titan is second is
#: the first syllable of a row name, which is what every screen reader
#: sounds like when something more important arrives.
PITCH_DELAY_MS = 0

_pending_read = [0]


def cancel_pending_read():
    """Titan has spoken: whatever this was about to read is not wanted."""
    _pending_read[0] += 1


def _say_unless_titan_does(sequence):
    """Read the control, unless Titan has already said something about it."""
    marker = _pending_read[0] = _pending_read[0] + 1
    since = spoke_at()

    def now_or_never():
        if _pending_read[0] != marker:
            return                       # a newer focus has overtaken this
        if spoke_at() != since or take_mark():
            # Titan spoke about this focus first. Its sentence carries what
            # the row's own text cannot, so it wins, and the mark is
            # consumed here rather than eating the NEXT control's report.
            global _suppressed
            _suppressed += 1
            return
        _speak(sequence)

    if PITCH_DELAY_MS <= 0:
        now_or_never()
        return
    try:
        import core
        core.callLater(PITCH_DELAY_MS, now_or_never)
    except Exception:                                # noqa: BLE001
        now_or_never()


def _cue(obj):
    try:
        from . import earcons
        earcons.announce(obj)
    except Exception:                                # noqa: BLE001
        pass
    try:
        # **Emacspeak's auditory icons, on the rest of Windows.** You are
        # told you are on a button, in a list, at a heading, before the
        # synthesizer has said a syllable. Deliberately beside the cursor
        # cues rather than instead of them: a cue says WHERE the control
        # is, an icon says WHAT it is, and a user may want either, both or
        # neither. The icons are the add-on's own files played through
        # NVDA's own audio, so this works with no Titan running at all -
        # which the cursor cues, which ask Titan to play them, cannot.
        from . import icons
        icons.for_focus(obj)
    except Exception:                                # noqa: BLE001
        pass


def _pitched_wanted():
    from . import configSpec
    return bool(configSpec.read().get('pitchedFocus', True))


def _speak(sequence):
    if not sequence:
        return
    try:
        from . import interject
        interject.mine()
    except Exception:                                # noqa: BLE001
        pass
    try:
        # **Through `voices`, not straight to NVDA.** A reading whose first
        # part asks for a voice or a variant of its own cannot carry that
        # inside the sequence - there is no utterance before it to change
        # the driver at the end of - so it is put on here, as late as it can
        # be, immediately before the words that want it. Handing the
        # sequence to `speech.speak` directly still says everything; it just
        # says the first part in the reader's own voice.
        from . import voices
        if voices.speak_sequence(sequence):
            return
    except Exception:                                # noqa: BLE001
        pass
    speech = compat.speech
    if speech is None:
        return
    try:
        speech.speak(sequence)
    except Exception:                                # noqa: BLE001
        pass

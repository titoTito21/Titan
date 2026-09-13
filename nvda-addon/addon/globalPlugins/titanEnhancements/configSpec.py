# -*- coding: utf-8 -*-
"""The add-on's own settings, in NVDA's configuration.

Kept in NVDA rather than in Titan on purpose: these are answers about how
NVDA should behave, they must be readable when Titan is not running, and a
user who uninstalls Titan should not be left with a reader configured by a
program that is gone.
"""

SECTION = 'titanEnhancements'

#: Every one of these is a thing the user can be wrong about wanting, which
#: is why each is a switch rather than a decision made for them. The
#: defaults are what somebody who installed the add-on asked for.
SPEC = {
    'enabled': 'boolean(default=True)',
    'announcements': 'boolean(default=True)',
    'replaceFocus': 'boolean(default=True)',
    'position': 'boolean(default=True)',
    # HOW a place is carried. Panning is exact where a synthesizer feeds a
    # stereo WavePlayer and is NVDA's whole audio session everywhere else -
    # including on eSpeak, its own default and a mono synthesizer - and a
    # session is not an utterance: it is put back on a timer, so a long line
    # snaps back in the middle of itself and a restore lands inside the next
    # one. Reported, correctly, as "it is not smooth, it cuts sometimes".
    # A pitch belongs to the utterance it is in and every synthesizer that
    # declares it takes it, so that is the default; panning is still here
    # for a machine where it really works.
    'positionAs': "option('pitch', 'pan', 'both', default='pitch')",
    # Where a control IS, applied to the voice that reads it. Titan sends a
    # position for the few things whose place it knows and 0 for every
    # ordinary control, so a panner fed only by Titan's announcements had
    # nothing to place - "positioned speech is on and nothing moves". The
    # screen knows where every control is, and NVDA is the thing looking at
    # the screen; this switch is what applies it inside Titan's windows.
    'positionMarker': 'boolean(default=True)',
    # The same, for NVDA's own report of every control on the whole
    # machine. Off by default: it changes how everything the user focuses
    # anywhere is spoken, which is not a decision to make for somebody -
    # the same reasoning as the cursor sounds below.
    'positionEverywhere': 'boolean(default=False)',
    'prosody': 'boolean(default=True)',
    'braille': 'boolean(default=True)',
    'standDownForTitanAccess': 'boolean(default=True)',
    'announceConnection': 'boolean(default=True)',
    # Titan reaching back INTO NVDA. Reading what NVDA can see is always
    # served - it is the user's own screen, described to their own desktop,
    # and it is what makes Titan's subsystems contextual at all. CHANGING
    # NVDA is this switch, and pressing NVDA's keys is a second one, off by
    # default: a gesture is whatever the user bound it to, and in a document
    # a bound key can delete something. Titan draws exactly this line in the
    # other direction when it asks whether an external client may drive it.
    'letTitanDrive': 'boolean(default=True)',
    'letTitanPressKeys': 'boolean(default=False)',
    # Reading a control the way Titan's own reader reads one: the name, the
    # control type a little lower, the state a little higher. Only inside
    # Titan's own windows - outside them NVDA is the reader and knows far
    # more about what it is looking at than this does.
    'pitchedFocus': 'boolean(default=True)',
    # The same three-tone reading as inside Titan, for EVERY control on
    # the machine - the name, the control type a little lower, the state a
    # little higher. Off by default and deliberately so: outside Titan,
    # NVDA is the reader and knows about tables, landmarks and browse mode,
    # and standing in for it everywhere to gain three tones is a trade
    # nobody should make on somebody's behalf. It is here because it is
    # theirs to make.
    'pitchedEverywhere': 'boolean(default=False)',
    # What a control MEANS inside a Titan application - a row of the file
    # manager's list read as a file or a folder with its own columns,
    # rather than as "list item 3". This is what a screen reader's app
    # module buys anywhere else, and Titan is a whole desktop of
    # applications nobody had written one for.
    'appSemantics': 'boolean(default=True)',
    # The same semantics for the rest of Windows: a place NVDA entered in
    # silence, and a row of any report-mode list read with the columns
    # beside its name. What a sighted person reads off the layout before a
    # word arrives, and what nothing on this machine was in a position to
    # say.
    #
    # **It was off, and it is on.** Off was the right answer while this
    # layer announced the part of the window on every control - which is
    # the bug a user reported as "dialog OK button, dialog Cancel button".
    # It no longer announces anything NVDA has already said (see
    # `ancestry`), so what is left is additions and nothing else: on an
    # ordinary dialog it now says nothing at all.
    'windowsSemantics': 'boolean(default=True)',
    # The reader modules - what an app module buys anywhere else, as data.
    'readerModules': 'boolean(default=True)',
    # The kind of a dialog - question, warning, error - anywhere on
    # Windows, read off the dialog's own icon or the answers it will take.
    # Titan has always said this for its own dialogs; this is the rest of
    # the machine, and it needs neither Titan nor Titan Access.
    'dialogKinds': 'boolean(default=True)',
    # What KIND of window you have just arrived in - an application, a
    # game, a little box, the desktop - which `dialogKinds` answers for
    # the four kinds of dialog and for nothing else, and nothing else
    # answered at all.
    'windowKinds': 'boolean(default=True)',
    # What a picture IS: an icon, a picture, an animation - instead of the
    # one word "graphic" for all three.
    'graphicKinds': 'boolean(default=True)',
    # Reading an unnamed control with AI, once, and remembering what it
    # said as its label. OFF: it sends a picture of part of the user's
    # screen to their AI provider, which is not something to switch on for
    # somebody.
    'autoLabel': 'boolean(default=False)',
    # Something that changed while the focus was somewhere else - a status
    # bar, a progress, anything a reader module or Titan declares live.
    'liveRegions': 'boolean(default=True)',
    # The generic floor under it: the status bar of the window in front.
    'liveStatusBars': 'boolean(default=True)',
    # A window that draws its own interface and exposes none of it - a
    # Unity game's menu - read as a picture, and watched so the highlight
    # moving is announced. OFF, and for the same reason as autoLabel.
    'surfaceReading': 'boolean(default=False)',
    # **Which recogniser reads a window that shows a reader nothing.**
    # Windows has one built in and NVDA already wraps it: local, free, about
    # a tenth of a second, and nothing leaves the machine. Titan's AI OCR
    # understands what it reads - which of these is a button, what is
    # highlighted - and every reading is a picture of the user's screen sent
    # to a provider.
    #
    # Local by default, and that is the same rule as everywhere else here: a
    # thing that spends somebody's money and privacy is opted INTO. 'both'
    # asks the AI first and falls back to Windows when it cannot.
    'ocrTier': "option('local', 'ai', 'both', default='local')",
    # **What the program DREW, before any picture is taken.** NVDA injects
    # `nvdaHelperRemote.dll` into every process and hooks the GDI text calls,
    # so for a window that draws its text that way the words are already
    # known - exactly, instantly, free, with a rectangle per character. It is
    # tried before either recogniser and costs nothing when it answers
    # nothing, which is what a Direct3D game or the inside of a virtual
    # machine does. On by default BECAUSE it spends nothing: this is the one
    # tier there is no reason to opt into. See `drawnText`.
    'drawnText': "boolean(default=True)",
    # **An agent on the far side of a wall.** Inside a virtual machine and
    # inside a game engine the words exist and this side cannot see them: the
    # guest draws in the guest, and Unity draws its text as meshes. So
    # something on the inside says what it sees and the reader listens on a
    # socket. Off by default, and that is not caution for its own sake - a
    # socket that makes a screen reader speak lets any program on the machine
    # say anything in the user's ear, so it is opt-in, token-checked, and
    # bound to this machine unless the guest switch below is on too.
    'agentLink': "boolean(default=False)",
    # Accept an agent from OUTSIDE this machine - which in practice means a
    # virtual machine's guest, the case the whole channel exists for. It
    # widens the socket from 127.0.0.1 to every interface, so it is a
    # separate answer from switching the channel on.
    'agentFromGuest': "boolean(default=False)",
    # The shared secret, made here and given to the agent. Never typed by
    # the user; shown on the settings page so it can be copied into the
    # agent's configuration.
    'agentToken': "string(default='')",
    # Which language Windows' own recogniser reads in. Empty means whatever
    # Windows is set to, which is right until somebody is reading a program
    # in another language.
    'localOcrLanguage': "string(default='')",
    # The hourglass, and a window whose taskbar button is flashing. Two
    # things a sighted person gets without looking at anything, and that no
    # reader says.
    'busyState': 'boolean(default=True)',
    'attentionState': 'boolean(default=True)',
    # Said when the keyboard leaves a menu. Every reader announces opening
    # one; none of them announces closing one.
    'menuLeaving': 'boolean(default=True)',
    # A laptop's touchpad driving NVDA's own touch gestures. OFF: it reads
    # every contact on the pad, and a user who has not asked for gestures
    # should not have them.
    'trackpad': 'boolean(default=False)',
    # Whether an utterance is coloured by WHERE IT CAME FROM - keyboard
    # echo, a word being spelled, a message, what another program said
    # through the controller. On: it costs nothing when no class has been
    # given a voice, and it is the thing that makes a voice table about
    # more than controls.
    'speechOrigins': 'boolean(default=True)',
    # The areas the user has marked to be watched (JAWS calls them Frames).
    # On: it costs nothing at all until somebody marks one, and a monitor
    # somebody made and cannot hear is worse than not having them.
    'monitors': 'boolean(default=True)',
    # **Emacspeak's auditory icons.** A sound under a quarter of a second
    # that says WHAT happened before a word of it is spoken - on a button,
    # something opened, that was refused. They ship on, unlike the cursor
    # earcons above, and the difference is real: a cursor cue plays on
    # every control the focus reaches all day in every program, while an
    # icon here is played by this add-on's own surfaces - the reviews, the
    # Titan window - which the user opened deliberately.
    'auditoryIcons': 'boolean(default=True)',
    # The same icons on every control in every program, not only in this
    # add-on's own windows. It ships ON where `pitchedEverywhere` and
    # `earcons` ship off, and the difference is a real one rather than a
    # preference: an icon is ADDITIVE - it never replaces, delays or
    # shortens a word NVDA was going to say - where those two stand in for
    # NVDA's own report. Nothing is lost by it and one switch takes all of
    # them away.
    'auditoryIconsEverywhere': 'boolean(default=True)',
    # Telling Titan which program the user is really in, so ITS subsystems
    # can be contextual. A self-report: nothing here changes Titan, and
    # Titan serves it to any client without asking - which is why it can
    # ship on. It is the same thing Titan can already ask this add-on for
    # at any moment (`reader.context`), pushed when it changes instead of
    # polled for.
    'reportContext': 'boolean(default=True)',

    # The sound scheme: a state answered with a sound instead of a word.
    # On, and it costs nothing until a state is given one - a state nobody
    # has touched is spoken exactly as NVDA spoke it.
    'soundScheme': 'boolean(default=True)',
    # Everything the reader said, kept in memory with the way back to what
    # said it. On: it is a deque with a ceiling and a few strings per line,
    # and it is what answers "where was that?" - which no reader answers.
    # Nothing is written to disk unless the user asks for it.
    'journal': 'boolean(default=True)',
    # ---- Titan's own window, walked ------------------------------------
    # What a row of it says about itself, and what happens to a setting
    # changed in it. They are here rather than decided because each is a
    # real trade: a value on the row is the whole point of a settings list
    # for somebody working by ear AND is a longer row to listen past, and
    # saving is Titan's own `OnSave` - the SAPI registration, the system
    # monitor, the shell, the menu bar - which is a great deal to do on
    # every keystroke.
    'titanValues': 'boolean(default=True)',
    'titanCounts': 'boolean(default=True)',
    'titanAutoSave': 'boolean(default=False)',
    # Inside a virtual machine: what the pointer is on, said as it moves.
    # A guest's window is another computer's screen, so a reader can say
    # nothing about it at all - and this needs no key and no guest tools,
    # only the host's own pointer and a strip of the picture it is on.
    #
    # OFF, because it reads a piece of the screen whenever the pointer
    # moves to another row. Everything it uses is local (Windows' own
    # recogniser) and nothing leaves the machine, but a reader that talks
    # while somebody is working is a decision to make for oneself.
    'guestCursor': 'boolean(default=False)',
    # Titan's own cursor cues on every focus change, everywhere EXCEPT
    # Titan's own windows (which already play their own). Off by default: it
    # changes what the whole machine sounds like, which is not a decision to
    # make for somebody, and it needs Titan running.
    'earcons': 'boolean(default=False)',
}


def apply(section=None):
    """Push the stored answers into the live objects. Safe with no NVDA."""
    from . import channel
    from . import focus
    from . import panner
    values = section if section is not None else read()
    channel.CHANNEL.enabled = bool(values.get('announcements', True))
    channel.CHANNEL.braille_enabled = bool(values.get('braille', True))
    channel.CHANNEL.position_enabled = bool(values.get('position', True))
    channel.CHANNEL.marker_enabled = bool(values.get('positionMarker', True))
    channel.CHANNEL.prosody_enabled = bool(values.get('prosody', True))
    panner.PANNER.enabled = bool(values.get('position', True))
    if not values.get('standDownForTitanAccess', True):
        focus.stand_down(False)
    # **A switch that opens a socket has to act when it is ticked.** Read
    # live, `agentLink` said `wanted: true, listening: false`: the channel
    # was started once at start-up and the answer changed afterwards, so
    # ticking it appeared to do nothing until NVDA was restarted - and
    # unticking it left the socket open, which is worse.
    try:
        from . import agentLink
        agentLink.keep_running()
    except Exception:                                # noqa: BLE001
        pass
    return values
#: A setting that is not a yes or a no. Everything here was a switch until
#: one question turned out to have three answers, and the two places that
#: read the file forced `bool()` on every value - which would have turned
#: 'pitch' into True and then written True back over the user's answer. A
#: spec that is an `option(...)` is read and written as the word it is.
def _is_choice(spec):
    """Whether this setting is a WORD rather than a yes or a no.

    Both shapes count: an `option(...)` is a word out of a fixed list, a
    `string(...)` is any word at all. Matching only the first read a
    `string` setting through `bool()`, so the OCR language came back as
    `False` - a value that is not one of the things it can be, written back
    over the user's answer the next time anything saved.
    """
    text = str(spec).strip()
    return text.startswith('option(') or text.startswith('string(')


def _choices(spec):
    """The words an option spec allows, in the order it lists them.

    ``[]`` for a `string(...)`: it allows any word, so there is no list -
    and the page then asks something that knows the machine what the
    answers really are (`settingsPanel._options_for`).
    """
    import re
    text = str(spec).strip()
    if not text.startswith('option('):
        return []
    inside = text[len('option('):].rstrip(') ')
    return [word.strip().strip("'\"")
            for word in re.split(r",(?![^()]*\))", inside)
            if word.strip() and not word.strip().startswith('default')]


def choices(name):
    """What a setting may be, or [] when it is an ordinary switch."""
    spec = SPEC.get(name, '')
    return _choices(spec) if _is_choice(spec) else []


def _default_of(spec):
    if _is_choice(spec):
        import re
        found = re.search(r"default=['\"]([^'\"]*)['\"]", str(spec))
        allowed = _choices(spec)
        return found.group(1) if found else (allowed[0] if allowed else '')
    return str(spec).endswith('default=True)')


def defaults():
    return {name: _default_of(spec) for name, spec in SPEC.items()}
    return {name: spec.endswith('default=True)')
            for name, spec in SPEC.items()}


#: The answers, and how long they may be believed.
#:
#: `read()` is on the FOCUS path - three times per focus event, between the
#: replace switch, the pitched-reading switch and the cursor sounds - and
#: it used to build a fresh dictionary out of NVDA's configuration each
#: time. Titan learned this about its own settings and wrote it down:
#: reading a file (or a validating ConfigObj) once per paint is invisible
#: in a settings dialog and ruinous on a path that runs whenever the user
#: presses an arrow key. The answers are the user's and change only when
#: they change them, so they are kept and thrown away by `write()`.
_CACHE = {'values': None, 'at': 0.0}

#: Short enough that a change made in NVDA's settings by any other route
#: than `write` is picked up while the user is still listening for it.
CACHE_SECONDS = 2.0


def forget():
    """Throw the kept answers away - the next read asks NVDA again."""
    _CACHE['values'] = None
    _CACHE['at'] = 0.0


def read():
    """The stored answers, or the defaults when NVDA is not here."""
    import time
    kept = _CACHE['values']
    if kept is not None and (time.time() - _CACHE['at']) < CACHE_SECONDS:
        return dict(kept)
    values = defaults()
    try:
        import config
        stored = config.conf[SECTION]
        for name in SPEC:
            # **Per key.** Read as one comprehension, a single name this
            # NVDA's configuration has not got - a setting added by a newer
            # add-on, a profile written before it existed - raised, and
            # every answer the user had given fell back to its default at
            # once. One missing key must cost that key and nothing else.
            try:
                values[name] = (str(stored[name]) if _is_choice(SPEC[name])
                                else bool(stored[name]))
            except Exception:                        # noqa: BLE001
                pass
    except Exception:                                # noqa: BLE001
        pass
    _CACHE['values'] = dict(values)
    _CACHE['at'] = time.time()
    return values


def write(values):
    written = False
    try:
        import config
        for name in SPEC:
            if name in values:
                config.conf[SECTION][name] = (
                    str(values[name]) if _is_choice(SPEC[name])
                    else bool(values[name]))
        written = True
    except Exception:                                # noqa: BLE001
        written = False
    finally:
        # Whatever happened, what is kept is no longer what the user
        # answered: a write that failed must not leave the old answers
        # looking fresh either.
        forget()
    return written


def register():
    """Add the section to NVDA's config spec. Idempotent."""
    try:
        import config
        config.conf.spec[SECTION] = dict(SPEC)
        return True
    except Exception:                                # noqa: BLE001
        return False

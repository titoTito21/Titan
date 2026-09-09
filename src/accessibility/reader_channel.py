# -*- coding: utf-8 -*-
"""Which reader is listening, and what it can be told.

Titan says things with structure. "Applications, 1 of 4, tab" is a name, a
place in a list and a role; a control on the left of the shell's taskbar is
spoken from the left; a mole on the far row of a Cling board is lower and
quieter. Titan Access, Titan's own reader, is given all of that. Everything
else was given a string through ``accessible_output3``, because the NVDA
controller protocol carries text and nothing else.

So every ``announce_*`` in :mod:`src.accessibility.messages` had to ask one
question - "is Titan Access the reader?" - and answer it in the worst
possible way when it was not: **stay silent**. ``announce_view_switched``
and ``announce_shell_group`` do exactly that today, because NVDA reads the
control itself and Titan's sentence would be a second, worse copy of it. The
duplicate is avoided and the extra information is lost with it.

This module replaces that question with a better one: **what can the reader
that is listening actually take?** Three channels answer it:

* ``TitanAccessChannel`` - Titan's own reader, in this process. It takes the
  words, the pitch, whether to interrupt, and the one thing that matters
  most here: that this announcement stands IN PLACE of its own report of the
  control about to be focused.
* ``AddonChannel`` - a reader whose add-on has joined the Action Bus. The
  NVDA add-on in ``nvda-addon/`` is the first; nothing here knows that, and
  a second reader's add-on joining under its own id works unchanged. It
  takes the structure, and it says which parts of it this machine can
  really deliver - a position it cannot pan is reported as one it cannot
  pan, rather than accepted and dropped.
* ``PlainChannel`` - a reader reached through ``accessible_output3`` and
  nothing more. Text, and whether to interrupt.

Nothing in Titan needs to know which of the three it is talking to. It says
what it means, and the channel folds away what cannot be carried - a
position that cannot be sent becomes nothing, and a role that cannot be sent
separately becomes part of the sentence.
"""

import threading
import time


#: Titan Access reads an element as THREE PARTS AT THREE PITCHES - the name
#: at the neutral tone, the control type a little lower, the state a little
#: higher - and that is not decoration: it is how somebody working by ear
#: tells "Save, button" from a list item called "Save button". The numbers
#: are Titan Access's own (`titan_access/accessible.py`), read from the
#: component when it is installed so the two cannot drift, and mirrored here
#: for the machines where it is not - which is exactly what that module does
#: itself, and says so, to avoid a circular import.
NAME_PITCH = 0
ROLE_PITCH = -4
STATE_PITCH = 4


def _pitches():
    """(name, role, state) - Titan Access's own numbers where it is here."""
    try:
        from titan_access import accessible
        return (int(accessible.NAME_PITCH), int(accessible.ROLE_PITCH),
                int(accessible.STATE_PITCH))
    except Exception:                                # noqa: BLE001
        return (NAME_PITCH, ROLE_PITCH, STATE_PITCH)


def _(text):
    """Titan's own translator, asked for lazily.

    This module is imported on the announcement path and must cost nothing
    at import time; the catalogue is already loaded by
    :mod:`src.accessibility.messages`, which is what does the announcing.
    """
    try:
        from src.accessibility.messages import _ as translate
        return translate(text)
    except Exception:                                # noqa: BLE001
        return text

#: The add-on ids that are readers. A reader's add-on announces itself on
#: the bus under its own id; this is a list rather than one name because
#: the mechanism is not NVDA's - it is any reader whose add-on speaks this
#: protocol, and hard-coding one would make the second one a rewrite.
READER_CLIENTS = ('nvda',)

#: How long an answer about what the reader can take stays fresh. The synth
#: can be changed at any moment, and a position sent to a mono voice is a
#: position silently lost - so this is short enough to follow the user
#: changing their mind and long enough not to be a round trip per sentence.
CAPABILITY_SECONDS = 20.0

#: An answer of NOTHING is not kept at all. A reader that has just started -
#: or that was slow for one call - answers nothing, and remembering that
#: like a real answer means Titan spends the next twenty seconds sending
#: flat text with no position, no tones and nothing marked as replacing the
#: reader's own report. Measured: exactly that, from one slow COM call on
#: the reader's side, and what the user heard was every control announced
#: twice. Asking again costs one call on a connection that is not answering
#: properly yet, which is the moment it is worth paying for.
EMPTY_CAPABILITY_SECONDS = 0.0

#: A reader that has not answered in this long is treated as gone. Titan
#: must never wait on speech: the interface is what the user is holding.
CALL_TIMEOUT = 2.5

_LOCK = threading.RLock()
_cache = {'peer': None, 'joined': 0.0, 'capabilities': {}, 'asked': 0.0}


# --------------------------------------------------------------------------- #
# The three channels
# --------------------------------------------------------------------------- #
class Channel:
    """What every channel can be asked."""

    name = 'none'

    def can(self, what):
        return False

    def say(self, message):
        return False

    def capabilities(self):
        return {}

    def dialog_kind(self, kind, label=''):
        """Say what kind of dialog is about to appear. True when it took."""
        return False

    def state_suffix(self, text):
        """Add a state to whatever the reader reads next."""
        return False


class TitanAccessChannel(Channel):
    """Titan's own reader, in this process, with no wire.

    What it claims is what ``host_bridge.announce`` really carries, and
    nothing else. Titan Access knows far more than this about a control -
    it reads the UIA tree itself, and ``push_focus`` / ``role_label`` /
    ``state_suffix`` exist for the toolkits it cannot see - but those
    describe the thing about to be FOCUSED, which is a different statement
    from "say this". A role claimed here and then folded into the sentence
    anyway would be a capability that lies: the caller would hand over a
    role as a field, believing the reader would word it in the user's own
    verbosity settings, and get Titan's own translation of it in the
    middle of the sentence instead.
    """

    name = 'titan_access'
    #: ``announce(text, interrupt, pitch)`` - and ``replaces_focus``, which
    #: is not an argument but what the call MEANS: it stands in place of the
    #: reader's own next focus announcement.
    _CARRIES = ('text', 'pitch', 'queue', 'replaces_focus', 'segments')

    def can(self, what):
        return what in self._CARRIES

    def capabilities(self):
        return {what: True for what in self._CARRIES}

    def say(self, message):
        parts = message.segments()
        if len(parts) > 1:
            try:
                from titan_access.host_bridge import announce_segments
                if announce_segments(parts, interrupt=message.interrupt):
                    return True
            except Exception:                        # noqa: BLE001
                pass
        try:
            from titan_access.host_bridge import announce
        except Exception:                            # noqa: BLE001
            return False
        try:
            return bool(announce(message.sentence(),
                                 interrupt=message.interrupt,
                                 pitch=message.pitch))
        except Exception:                            # noqa: BLE001
            return False

    def dialog_kind(self, kind, label=''):
        # Titan Access is told the KIND and says the word itself, out of its
        # own catalogue - it does not want a word, it wants to know which
        # earcon to play and which label to read.
        try:
            from titan_access.host_bridge import dialog_kind as declare
            return bool(declare(kind))
        except Exception:                            # noqa: BLE001
            return False

    def state_suffix(self, text):
        try:
            from titan_access.host_bridge import state_suffix as suffix
            return bool(suffix(text))
        except Exception:                            # noqa: BLE001
            return False


class AddonChannel(Channel):
    """A reader whose add-on has joined the bus.

    The call is made with a short timeout and its answer is thrown away.
    That is deliberate: this is called from the interface, often from a
    focus handler, and Titan waiting on a reader is the thing Titan spent
    a lot of work not doing.
    """

    name = 'addon'

    def __init__(self, addon_id, capabilities):
        self.addon_id = addon_id
        self._capabilities = dict(capabilities or {})

    def can(self, what):
        # 'announce' is the one capability whose ABSENCE means yes: a
        # reader add-on written before the key existed answers everything
        # it can do and never mentions it, and reading that silence as a
        # refusal would take the whole channel away from it.
        if what == 'announce' and 'announce' not in self._capabilities:
            return True
        return bool(self._capabilities.get(what))

    def capabilities(self):
        return dict(self._capabilities)

    def say(self, message):
        from src.titan_core.actions import bus
        # Asked again here as well as in `channel()`, because a channel
        # object outlives the question that built it: this one is handed
        # around and re-used, and a reader whose user switched Titan's
        # announcements off between the two must not be spoken into.
        if not self.can('announce'):
            return False
        payload = message.for_addon(self)
        ok, _answer = bus.invoke(self.addon_id, 'announce', payload,
                                 timeout=CALL_TIMEOUT)
        return bool(ok)

    def _tell(self, call, **args):
        from src.titan_core.actions import bus
        ok, _answer = bus.invoke(self.addon_id, call, args,
                                 timeout=CALL_TIMEOUT)
        return bool(ok)

    def dialog_kind(self, kind, label=''):
        if not self.can('dialog_kind'):
            return False
        # A reader add-on gets the WORD as well as the kind: it has no
        # catalogue of Titan's and would otherwise have to invent one.
        return self._tell('dialog_kind', kind=str(kind), label=str(label))

    def state_suffix(self, text):
        if not self.can('state_suffix'):
            return False
        return self._tell('state_suffix', text=str(text))


class PlainChannel(Channel):
    """A screen reader reached through ``accessible_output3``: text only."""

    name = 'plain'

    def can(self, what):
        return what in ('text',)

    def capabilities(self):
        return {'text': True}

    def say(self, message):
        from src.accessibility.messages import speak_sr_only
        speak_sr_only(message.sentence(), interrupt=message.interrupt)
        return True


# --------------------------------------------------------------------------- #
# One thing Titan wants said
# --------------------------------------------------------------------------- #
class Message:
    """What Titan means, before a channel decides how much of it survives."""

    def __init__(self, text, position=0.0, pitch=0, rate=0, volume=0,
                 elevation=0.0, role='', states=(), index=None, count=None,
                 braille=None, interrupt=True, replaces_focus=False,
                 language='', spelling=False, parts=None):
        self.text = str(text or '')
        self.position = float(position or 0.0)
        self.elevation = float(elevation or 0.0)
        self.pitch = int(pitch or 0)
        self.rate = int(rate or 0)
        self.volume = int(volume or 0)
        self.role = str(role or '')
        self.states = tuple(str(state) for state in (states or ()))
        self.index = index
        self.count = count
        self.braille = braille
        self.interrupt = bool(interrupt)
        self.replaces_focus = bool(replaces_focus)
        self.language = str(language or '')
        self.spelling = bool(spelling)
        #: The parts and their tones, written out by the caller, for an
        #: announcement whose shape is not "name, control type, state" -
        #: the tab bar says "Tab bar", then the word tab lower, then which
        #: tab higher, and that is three parts in an order of its own.
        self.parts = [(str(text or ''), int(pitch or 0))
                      for text, pitch in (parts or [])
                      if str(text or '').strip()] or None

    def sentence(self):
        """Everything, folded into one line - for a channel that takes text.

        Parts the caller wrote out are joined in the order they were given;
        everything else is Titan's own wording, below.

        The order and the wording are Titan's own, not a new invention:
        "Applications, 1 of 4, tab" is what the tab bar has always said,
        and the place in the list is joined with the name through the same
        msgid the tab bar has always used, so no catalogue has to gain a
        string for a reader to keep the sentence it already had.
        """
        if self.parts:
            return ', '.join(text for text, _pitch in self.parts)
        head = self.text
        if self.index is not None and self.count:
            head = _('{}, {} of {}').format(self.text, self.index, self.count)
        parts = [head]
        if self.role:
            parts.append(self.role)
        parts.extend(state for state in self.states if state)
        return ', '.join(part for part in parts if str(part).strip())

    def segments(self):
        """The same sentence, as ``(text, pitch)`` parts.

        The ORDER is `sentence()`'s, not Titan Access's own - the tab bar
        has always said "Applications, 1 of 4, tab" and this must not
        reword it - but the tones are Titan Access's: the control type is
        said lower and a state higher, so a reader who is not looking hears
        what is a name and what is a type without either being labelled.

        A channel that cannot pitch parts separately flattens this back to
        `sentence()`, which is the same words.
        """
        if self.parts:
            return list(self.parts)
        name_pitch, role_pitch, state_pitch = _pitches()
        head = self.text
        if self.index is not None and self.count:
            head = _('{}, {} of {}').format(self.text, self.index, self.count)
        parts = []
        if str(head).strip():
            parts.append((head, name_pitch + self.pitch))
        if self.role:
            parts.append((self.role, role_pitch + self.pitch))
        for state in self.states:
            if str(state).strip():
                parts.append((state, state_pitch + self.pitch))
        return parts

    def for_addon(self, channel):
        """The wire form, with what this reader cannot carry left out.

        Anything dropped here is folded back INTO the text rather than
        thrown away, which is the whole difference between this and the
        silence it replaces: a reader that cannot take a role as a field
        still hears the role, in the sentence.
        """
        payload = {"text": self.text, "interrupt": self.interrupt}
        if channel.can("segments"):
            # The three parts at their three pitches, which is how Titan's
            # own reader has always said them. `text` stays beside it so a
            # reader that later stops supporting segments still has the
            # words.
            payload["segments"] = [[text, pitch]
                                   for text, pitch in self.segments()]
            payload["text"] = self.sentence()
        apart = channel.can("role") and channel.can("index")
        if apart:
            if self.role:
                payload["role"] = self.role
            if self.states:
                payload["states"] = list(self.states)
            if self.index is not None:
                payload["index"] = self.index
                payload["count"] = self.count
        else:
            payload["text"] = self.sentence()
        if channel.can("position") or channel.can("position_marker"):
            payload["position"] = self.position
            payload["elevation"] = self.elevation
        if channel.can("pitch"):
            payload["pitch"] = self.pitch
        if channel.can("rate"):
            payload["rate"] = self.rate
        if channel.can("volume"):
            payload["volume"] = self.volume
        if channel.can("braille") and self.braille is not None:
            payload["braille"] = str(self.braille)
        if channel.can("replaces_focus") and self.replaces_focus:
            payload["replaces_focus"] = True
        if self.language:
            payload["language"] = self.language
        if self.spelling:
            payload["spelling"] = True
        return payload


# --------------------------------------------------------------------------- #
# Choosing the channel
# --------------------------------------------------------------------------- #
def _titan_access_active():
    try:
        from titan_access.host_bridge import is_active
        return bool(is_active())
    except Exception:                                # noqa: BLE001
        return False


def _reader_peer():
    """A reader add-on that is on the bus right now, or None."""
    try:
        from src.titan_core.actions import bus
    except Exception:                                # noqa: BLE001
        return None
    for addon_id in READER_CLIENTS:
        peer = bus.get_peer(addon_id)
        if peer is not None and getattr(peer, 'alive', False):
            return peer
    return None


def _attach(peer):
    """Tell a reader add-on which process Titan is, once per connection.

    It cannot work this out for itself and must not guess: Titan run from
    source is ``python.exe``, and an add-on that recognised Titan by an
    executable name would take over the focus reporting of every Python
    program on the machine.
    """
    import os
    from src.titan_core.actions import bus
    language = ''
    try:
        from src.titan_core import translation
        language = str(getattr(translation, 'current_language', '') or '')
    except Exception:                                # noqa: BLE001
        pass
    bus.invoke(peer.addon_id, 'attach',
               {'pid': os.getpid(), 'language': language, 'api': 1,
                'version': '1.0.0'}, timeout=CALL_TIMEOUT)


def _capabilities_of(peer):
    """What this reader can take, asked at most every few seconds."""
    from src.titan_core.actions import bus
    now = time.time()
    with _LOCK:
        same = (_cache['peer'] == peer.addon_id
                and _cache['joined'] == getattr(peer, 'joined_at', 0.0))
        # An answer of nothing is not an answer, and is not kept like one.
        keep = (CAPABILITY_SECONDS if _cache['capabilities']
                else EMPTY_CAPABILITY_SECONDS)
        fresh = same and (now - _cache['asked']) < keep
        if fresh:
            return dict(_cache['capabilities'])
        first_time = not same
    if first_time:
        try:
            _attach(peer)
        except Exception:                            # noqa: BLE001
            pass
    ok, answer = bus.invoke(peer.addon_id, 'capabilities', {},
                            timeout=CALL_TIMEOUT)
    capabilities = {}
    if ok:
        import json
        try:
            capabilities = json.loads(answer) if isinstance(answer, str) \
                else dict(answer or {})
        except (ValueError, TypeError):
            capabilities = {}
    with _LOCK:
        _cache['peer'] = peer.addon_id
        _cache['joined'] = getattr(peer, 'joined_at', 0.0)
        _cache['capabilities'] = dict(capabilities)
        _cache['asked'] = now
    return dict(capabilities)


def channel():
    """The reader that is listening, as something Titan can talk to.

    Titan Access first, because when it is running it IS the reader and a
    second one speaking as well is two readers over each other. Then a
    reader add-on. Then whatever ``accessible_output3`` can find. Then
    nothing at all, which is the ordinary case on a machine with no reader
    running and must cost nothing to discover.
    """
    if _titan_access_active():
        return TitanAccessChannel()
    peer = _reader_peer()
    if peer is not None:
        able = _capabilities_of(peer)
        # **An add-on that says it will not announce is not the channel.**
        # Its user has switched Titan's announcements off inside the reader,
        # and what that must mean is "behave as though the add-on were not
        # installed" - not silence. Answering here rather than at `say` is
        # what makes it true for the questions asked BEFORE anything is
        # said: `announce_view_switched` asks `can('replaces_focus')` and
        # stays quiet when the answer is no, so a channel that claimed it
        # could and then dropped the sentence lost it in both directions.
        if able.get('announce', True):
            return AddonChannel(peer.addon_id, able)
    try:
        from src.accessibility.messages import is_screen_reader_running
        if is_screen_reader_running():
            return PlainChannel()
    except Exception:                                # noqa: BLE001
        pass
    return Channel()


def can(what):
    """Whether the reader that is listening can take ``what``."""
    return channel().can(what)


def announce_parts(parts, **detail):
    """Say one thing whose parts and tones the caller has written out.

    For an announcement whose shape is its own rather than "name, control
    type, state": the tab bar is "Tab bar", then the word tab a little
    lower, then which tab a little higher.
    """
    parts = list(parts or [])
    if not parts:
        return False
    text = ', '.join(str(piece) for piece, _pitch in parts)
    return channel().say(Message(text, parts=parts, **detail))


def announce(text, **detail):
    """Say one structured thing to whichever reader is listening.

    Answers whether it was delivered, so a caller that has a fallback of
    its own - a sound, a different sentence - can use it.
    """
    return channel().say(Message(text, **detail))


def report():
    """What Titan is talking to, for the settings window and the actions."""
    active = channel()
    return {'channel': active.name, 'capabilities': active.capabilities()}

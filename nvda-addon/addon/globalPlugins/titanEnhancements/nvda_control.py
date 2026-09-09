# -*- coding: utf-8 -*-
"""What Titan may change in NVDA - and the line drawn across it.

The channel already runs the other way: Titan announces, NVDA speaks. This
is Titan's assistant, its agent, a macro or a Titan Script reaching the
READER - "say that again", "slow down", "read the rest of this", "switch to
the other synthesizer", "put NVDA in focus mode so my keys reach the app".
Every one of those is something the user would otherwise stop and do by
hand in the middle of what Titan is doing for them.

**Reading NVDA and driving NVDA are different permissions**, which is the
rule this repository already applies in the other direction: Titan asks its
user before an external client may act on Titan, because Enter in a
messenger sends the message. The same is true here and the same answer is
given - :mod:`context` is always served, and everything in this module is
behind a switch. Pressing an arbitrary NVDA gesture is behind a second one,
off by default, because that is not "change a setting" - it is the whole
keyboard.

Everything is a written-down table. There is no path from a name Titan
sends to an attribute of NVDA's: a setting Titan asks for is in
:data:`SETTINGS` or it does not exist, and a review command is in
:data:`REVIEW` or it does not exist. A bridge that resolved names with
``getattr`` would let whatever is on the other end of the pipe reach
anything in the process.
"""

import threading

from . import compat
from . import i18n

_ = i18n.install(globals())

#: NVDA settings Titan may read and write, each by a name that says what it
#: is rather than where it is stored. The value is (section, key, kind,
#: low, high) - a range where there is one, so a number that cannot be set
#: is refused here rather than being clamped silently by NVDA.
SETTINGS = {
    'rate': ('speech', 'rate', 'number', 0, 100),
    'volume': ('speech', 'volume', 'number', 0, 100),
    'pitch': ('speech', 'pitch', 'number', 0, 100),
    'inflection': ('speech', 'inflection', 'number', 0, 100),
    'rate_boost': ('speech', 'rateBoost', 'boolean', None, None),
    'punctuation': ('speech', 'symbolLevel', 'number', 0, 300),
    'say_cap_before': ('speech', 'sayCapForCapitals', 'boolean', None, None),
    'beep_cap': ('speech', 'beepForCapitals', 'boolean', None, None),
    'braille_tether': ('braille', 'tetherTo', 'string', None, None),
    'keyboard_echo_characters': ('keyboard', 'speakTypedCharacters',
                                 'boolean', None, None),
    'keyboard_echo_words': ('keyboard', 'speakTypedWords', 'boolean',
                            None, None),
    'report_progress': ('presentation', 'progressBarUpdates', 'string',
                        None, None),
}

#: The synth settings above live under the CURRENT synthesizer, not at the
#: top of the speech section: NVDA keeps one block per synth so switching
#: back brings your rate back with it.
_PER_SYNTH = ('rate', 'volume', 'pitch', 'inflection', 'rate_boost')

#: Where the review cursor may be told to go. Named for what the user would
#: call it, mapped to the NVDA unit; "say_all" is not a unit and is handled
#: on its own.
REVIEW = {
    'line': 'UNIT_LINE',
    'word': 'UNIT_WORD',
    'character': 'UNIT_CHARACTER',
    'paragraph': 'UNIT_PARAGRAPH',
}


class Refused(Exception):
    """Titan asked for something this NVDA will not do. Said, not raised."""


def _allowed(what='drive'):
    from . import configSpec
    values = configSpec.read()
    if what == 'keys':
        return bool(values.get('letTitanPressKeys', False))
    return bool(values.get('letTitanDrive', True))


def _guard(what='drive'):
    if not _allowed(what):
        if what == 'keys':
            raise Refused(_('This NVDA has not been told Titan may press its '
                            'keys. Turn it on in NVDA Settings, Titan.'))
        raise Refused(_('This NVDA has not been told Titan may change it. '
                        'Turn it on in NVDA Settings, Titan.'))


def _main(function):
    """Everything here touches NVDA, so everything here runs on its thread.

    Never waits: Titan is on the other end of a pipe and a reader command
    is a thing to DO, not a thing to answer with.
    """
    if compat.queueHandler is None:
        function()
        return
    compat.queueHandler.queueFunction(compat.queueHandler.eventQueue, function)


# --------------------------------------------------------------------------- #
# Speech
# --------------------------------------------------------------------------- #
def speak(text='', interrupt=True, position=0, pitch=0, rate=0,
          segments=None, **_kw):
    """Say something in NVDA's own voice.

    Different from ``announce``, which stands IN PLACE of NVDA's report of a
    control about to be focused. This is Titan simply speaking - an
    assistant's answer, a macro saying it has finished - and it is the call
    a Titan Script reaches for.

    It takes a place and a tone because Titan has them: a macro counting
    from the left of the screen to the right is a thing somebody writes, and
    without these the only way to be heard from a place was an announcement
    that also suppressed the reader's next report, which is not what a macro
    means.
    """
    _guard()
    message = str(text or '')
    if not message:
        return {'spoken': False, 'reason': 'there is nothing to say'}
    from . import channel
    return channel.CHANNEL.announce(text=message, interrupt=interrupt,
                                    position=position, pitch=pitch, rate=rate,
                                    segments=segments)


def stop(**_kw):
    _guard()
    from . import channel
    return channel.CHANNEL.interrupt()


def say_all(**_kw):
    """Read on from where the review cursor is - NVDA's own say-all."""
    _guard()

    def run():
        try:
            from speech import sayAll
            sayAll.SayAllHandler.readText(sayAll.CURSOR.REVIEW)
        except Exception:                            # noqa: BLE001
            if compat.speech is not None:
                try:                                 # NVDA before the move
                    compat.speech.sayAll.readText(0)
                except Exception:                    # noqa: BLE001
                    pass
    _main(run)
    return {'reading': True}


# --------------------------------------------------------------------------- #
# The review cursor
# --------------------------------------------------------------------------- #
def review(where='line', direction='current', **_kw):
    """Move the review cursor and say what is there.

    This is what makes "read me the next line" something Titan can do: the
    review cursor is NVDA's own idea of where the user is READING, which is
    a different place from where the focus is and the one Titan has no
    equivalent of.
    """
    _guard()
    unit_name = REVIEW.get(str(where or 'line'))
    if unit_name is None:
        raise Refused(_('NVDA has no review unit called {name}.')
                      .format(name=where))
    if compat.api is None or compat.textInfos is None:
        raise Refused(_('This NVDA does not expose its review cursor.'))
    unit = getattr(compat.textInfos, unit_name, None)
    if unit is None:
        raise Refused(_('This NVDA has no {name}.').format(name=unit_name))
    step = {'next': 1, 'previous': -1, 'current': 0}.get(
        str(direction or 'current'))
    if step is None:
        raise Refused(_('Say next, previous or current.'))

    def run():
        info = compat.api.getReviewPosition().copy()
        if step:
            info.expand(unit)
            info.collapse()
            if info.move(unit, step) == 0:
                if compat.ui is not None:
                    compat.ui.message(_('No more.'))
                return
            compat.api.setReviewPosition(info)
        spoken = info.copy()
        spoken.expand(unit)
        if compat.speech is not None:
            compat.speech.speakTextInfo(spoken, unit=unit)
    _main(run)
    return {'moved': bool(step), 'unit': str(where)}


def describe(**_kw):
    """What the reader would SAY about the focused control, in parts.

    The name, the control type and each state, each with the tone it is
    said at - Titan Access's own shape. Reading rather than acting, so it
    needs no switch.

    It is here because "what would you say about this?" is a different
    question from "what is on the screen" (:mod:`context`), and it is the
    one to ask when the answer sounds wrong: it says which part is which,
    which is exactly what cannot be heard when they are all one tone.
    """
    from . import context
    from . import elements
    from . import focus

    def gather():
        if compat.api is None:
            return {'available': False,
                    'why': 'this NVDA does not expose its api module'}
        obj = compat.api.getFocusObject()
        parts = elements.describe(obj)
        return {
            'available': True,
            'segments': [[text, pitch] for text, pitch in parts],
            'line': ', '.join(text for text, _pitch in parts),
            'can_pitch': elements.can_pitch(),
            'in_titan': focus.is_titan_object(obj),
        }
    try:
        return context._on_main(gather)
    except Exception as error:                       # noqa: BLE001
        return {'available': False, 'why': str(error)}


def read_focus(**_kw):
    """Say the focused control again - NVDA's own report of it."""
    _guard()

    def run():
        if compat.api is None or compat.speech is None:
            return
        obj = compat.api.getFocusObject()
        try:
            compat.speech.speakObject(obj)
        except Exception:                            # noqa: BLE001
            if compat.ui is not None:
                compat.ui.message(str(getattr(obj, 'name', '') or ''))
    _main(run)
    return {'said': True}


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #
def mode(name='', **_kw):
    """Browse mode or focus mode.

    Titan's own reason for wanting this: a macro or an action about to send
    keys into a web page needs focus mode, or every keystroke is a browse
    command and the page is navigated instead of typed into.
    """
    _guard()
    wanted = str(name or '').strip().lower()
    if wanted not in ('browse', 'focus', 'toggle', ''):
        raise Refused(_('Say browse, focus or toggle.'))

    box = [None]

    def run():
        if compat.api is None:
            return
        obj = compat.api.getFocusObject()
        interceptor = getattr(obj, 'treeInterceptor', None)
        if interceptor is None:
            box[0] = 'none'
            if compat.ui is not None:
                compat.ui.message(_('There is no browse mode here.'))
            return
        now = bool(getattr(interceptor, 'passThrough', False))
        want = {'browse': False, 'focus': True, 'toggle': not now,
                '': now}[wanted]
        if want != now:
            try:
                import browseMode
                browseMode.reportPassThrough(interceptor, want)
            except Exception:                        # noqa: BLE001
                pass
            interceptor.passThrough = want
        box[0] = 'focus' if want else 'browse'
    _main(run)
    return {'mode': wanted or 'unchanged'}


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def _synth_section():
    synth = None
    if compat.synthDriverHandler is not None:
        synth = compat.synthDriverHandler.getSynth()
    return str(getattr(synth, 'name', '') or '') if synth is not None else ''


def _setting_location(name):
    section, key, kind, low, high = SETTINGS[name]
    if name in _PER_SYNTH:
        synth = _synth_section()
        if not synth:
            raise Refused(_('There is no synthesizer running.'))
        return ('speech', synth, key, kind, low, high)
    return (section, '', key, kind, low, high)


#: What a setting may be. Anything else is not a setting: NVDA's
#: configuration is a TREE, and several of the names that look like
#: settings are branches of it. `presentation/progressBarUpdates` is one -
#: it holds `progressBarOutputMode` and the rest - and handing a caller the
#: branch is not "the setting is a section", it is an answer that cannot be
#: serialised at all, so the call never comes back and the whole list times
#: out. Found live, and it took the other eleven settings down with it.
_SCALARS = (str, int, float, bool)


def _store_of(name):
    """The configobj section holding ``name``, and the key in it.

    Raises :class:`Refused` when this NVDA has not got it. Which keys exist
    is a question about the NVDA that is running, not about the version
    number on it: they are renamed and moved between releases, and two of
    the ones shipped here (`sayCapForCapitals`, `beepForCapitals`) turned
    out not to exist in the alpha this was first run against. So the
    question is asked of the configuration itself.
    """
    if compat.config is None:
        raise Refused(_('This NVDA does not expose its configuration.'))
    section, synth, key, kind, low, high = _setting_location(name)
    try:
        store = compat.config.conf[section]
        if synth:
            store = store[synth]
    except Exception:                                # noqa: BLE001
        raise Refused(_('This NVDA has no {name}.').format(name=name))
    if key not in store:
        raise Refused(_('This NVDA has no setting called {name}.')
                      .format(name=name))
    return store, key, kind, low, high


def _value_of(store, key, name):
    value = store[key]
    if not isinstance(value, _SCALARS):
        raise Refused(_('{name} is a group of settings in this NVDA, not one '
                        'setting.').format(name=name))
    return value


def settings(**_kw):
    """Every NVDA setting Titan may touch, and what each is now.

    A name this NVDA has not got is left OUT rather than reported as an
    error: the table is what Titan may ask for, and what is really there is
    what this answers.
    """
    out, absent = {}, []
    for name in SETTINGS:
        try:
            store, key, _kind, _low, _high = _store_of(name)
            out[name] = _value_of(store, key, name)
        except Refused as refusal:
            absent.append('{}: {}'.format(name, refusal))
        except Exception as error:                   # noqa: BLE001
            absent.append('{}: {}'.format(name, error))
    # What the reader is DOING, beside what it is set to. "It is not doing
    # it" and "it is doing it and I cannot hear the difference" are
    # different problems, and only a count tells them apart - from Titan as
    # well as from the status gesture.
    from . import earcons
    from . import elements
    from . import focus
    from . import interject
    from . import panner
    answer = {'settings': out, 'synth': _synth_section(),
              'may_change': _allowed(), 'may_press_keys': _allowed('keys'),
              'reading': {
                  'can_pitch': elements.can_pitch(),
                  'three_tones': focus.pitched(),
                  'replaced': focus.suppressed(),
                  'cursor_sounds': earcons.played(),
                  'titan_pid': focus.titan_pid(),
                  'titan_coordinates': focus.titan_coordinates(),
                  'can_mute': focus.can_mute(),
                  # "Positioned speech is on and nothing moves" is a report
                  # with no evidence in it, and there are three different
                  # things it can mean: the voice cannot be placed at all,
                  # nothing asked for a position, or it was asked for and
                  # applied and the user cannot hear it. Only these tell
                  # them apart.
                  'can_place': panner.PANNER.can_place(),
                  'why_not_placed': panner.PANNER.why_not(),
                  'placed': interject.placed(),
                  # What the semantic layer really did, per layer, because
                  # "it does not understand my applications" and "it
                  # understands them and I cannot hear the difference" are
                  # different problems and only a count tells them apart.
                  'semantic': focus.semantic(),
                  'windows_semantic': focus.windows(),
                  # What that layer COSTS, because it runs on the thread
                  # that reads the screen and the only honest way to have
                  # it there is to measure it and stand down when it is
                  # too expensive.
                  'semantic_ms': round(_semantic_timing()
                                       .get('average', 0.0) * 1000, 2),
                  'semantic_worst_ms': round(_semantic_timing()
                                             .get('worst', 0.0) * 1000, 2),
                  'semantic_stopped': _semantic_timing().get('stopped', ''),
                  'applications': _applications_known(),
                  'bindable': _bindable(),
                  'heard': _heard_log(),
                  'spoken': _spoken_log(),
              }}
    if absent:
        answer['absent'] = absent
    return answer


def _semantic_timing():
    try:
        from . import semantics
        return semantics.timing()
    except Exception:                                # noqa: BLE001
        return {}


def _applications_known():
    """Which Titan applications this reader can recognise by their window."""
    try:
        from . import semantics
        return sorted({str(row.get('id') or '')
                       for row in semantics.known_processes().values()
                       if row.get('id')})
    except Exception:                                # noqa: BLE001
        return []


def _bindable():
    """How many Titan actions NVDA would really OFFER in Input Gestures.

    Counted the way NVDA counts them - the plugin CLASS and its bases, each
    class's own ``__dict__`` - and not by how many attributes this add-on
    thinks it installed. Those were different numbers for the whole of this
    add-on's first version: the scripts were set on the instance, ran
    perfectly for any binding that already existed, and appeared in that
    dialog nowhere at all.
    """
    try:
        from . import gestures
        import globalPlugins.titanEnhancements as plugin
        return len(gestures.bindable(plugin.GlobalPlugin))
    except Exception:                                # noqa: BLE001
        try:
            from . import gestures
            return gestures.installed()
        except Exception:                            # noqa: BLE001
            return 0


def _heard_log():
    """The last few announcements Titan made, newest last."""
    from . import channel
    import time as _time
    now = _time.time()
    out = []
    for row in list(channel.CHANNEL.heard):
        entry = dict(row)
        entry['ago'] = round(now - entry.pop('at', now), 2)
        out.append(entry)
    return out


def _spoken_log():
    """The last few things NVDA really said, newest last.

    Read this when something "is not announced any more": it says whether
    the sentence was never sent, was sent and cancelled, or was said and
    then said over.
    """
    from . import interject
    import time as _time
    now = _time.time()
    return [{'ago': round(now - when, 2), 'by': who, 'said': words}
            for when, who, words in interject.spoken_log()]


def setting(name='', value=None, **_kw):
    """Read one NVDA setting, or set it when ``value`` is given."""
    key_name = str(name or '')
    if key_name not in SETTINGS:
        raise Refused(_('NVDA has no setting Titan can change called '
                        '{name}.').format(name=key_name or '(none)'))
    store, key, kind, low, high = _store_of(key_name)
    if value is None:
        return {'name': key_name, 'value': _value_of(store, key, key_name)}
    # Refuse to WRITE anything that is not a setting, for the same reason.
    _value_of(store, key, key_name)
    _guard()
    if kind == 'boolean':
        wanted = str(value).strip().lower() in ('1', 'true', 'yes', 'on')
    elif kind == 'number':
        try:
            wanted = int(float(value))
        except (TypeError, ValueError):
            raise Refused(_('{name} is a number.').format(name=key_name))
        if low is not None and not low <= wanted <= high:
            raise Refused(_('{name} is between {low} and {high}.')
                          .format(name=key_name, low=low, high=high))
    else:
        wanted = str(value)

    def run():
        store[key] = wanted
        # A synth setting written into the configuration is not a synth
        # setting applied: NVDA keeps the two apart deliberately, so the
        # driver is told as well or nothing changes until it is restarted.
        if key_name in _PER_SYNTH and compat.synthDriverHandler is not None:
            live = compat.synthDriverHandler.getSynth()
            if live is not None and hasattr(live, key):
                try:
                    setattr(live, key, wanted)
                except Exception:                    # noqa: BLE001
                    pass
    _main(run)
    return {'name': key_name, 'value': wanted, 'set': True}


# --------------------------------------------------------------------------- #
# The synthesizer
# --------------------------------------------------------------------------- #
def synths(**_kw):
    """Every synthesizer this NVDA has, and which one is speaking."""
    if compat.synthDriverHandler is None:
        raise Refused(_('This NVDA does not expose its synthesizers.'))
    found = []
    try:
        for driver in compat.synthDriverHandler.getSynthList():
            found.append({'name': str(driver[0]), 'label': str(driver[1])})
    except Exception:                                # noqa: BLE001
        pass
    return {'synths': found, 'current': _synth_section()}


def use_synth(name='', **_kw):
    """Switch NVDA to another synthesizer."""
    _guard()
    wanted = str(name or '').strip()
    if not wanted:
        raise Refused(_('Say which synthesizer.'))
    if compat.synthDriverHandler is None:
        raise Refused(_('This NVDA does not expose its synthesizers.'))
    done = threading.Event()
    box = [False]

    def run():
        try:
            box[0] = bool(compat.synthDriverHandler.setSynth(wanted))
        finally:
            done.set()
    _main(run)
    done.wait(3.0)
    if not box[0]:
        raise Refused(_('NVDA would not switch to {name}.').format(name=wanted))
    return {'synth': wanted}


def voices(**_kw):
    """The voices of the synthesizer that is speaking."""
    if compat.synthDriverHandler is None:
        raise Refused(_('This NVDA does not expose its synthesizers.'))
    synth = compat.synthDriverHandler.getSynth()
    if synth is None:
        return {'voices': [], 'current': ''}
    found, current = [], ''
    try:
        setting_info = synth.availableVoices
        for identifier, info in setting_info.items():
            found.append({'id': str(identifier),
                          'label': str(getattr(info, 'displayName', identifier))})
        current = str(getattr(synth, 'voice', '') or '')
    except Exception:                                # noqa: BLE001
        pass
    return {'voices': found, 'current': current}


def use_voice(name='', **_kw):
    _guard()
    wanted = str(name or '').strip()
    if not wanted:
        raise Refused(_('Say which voice.'))
    if compat.synthDriverHandler is None:
        raise Refused(_('This NVDA does not expose its synthesizers.'))

    def run():
        synth = compat.synthDriverHandler.getSynth()
        if synth is not None:
            try:
                synth.voice = wanted
            except Exception:                        # noqa: BLE001
                pass
    _main(run)
    return {'voice': wanted}


# --------------------------------------------------------------------------- #
# Pressing a key
# --------------------------------------------------------------------------- #
def press(gesture='', **_kw):
    """Run one NVDA command, named the way NVDA names it: ``kb:NVDA+f7``.

    This is the powerful one and it is behind its own switch, off by
    default. It is not "change a setting": a gesture is whatever the user
    has bound it to, and in a document a bound key can delete something.
    The switch is the same distinction Titan itself draws when it asks
    whether an external client may drive it.
    """
    _guard('keys')
    wanted = str(gesture or '').strip()
    if not wanted:
        raise Refused(_('Say which gesture, as NVDA writes it - kb:NVDA+f7.'))
    if compat.inputCore is None or compat.KeyboardInputGesture is None:
        raise Refused(_('This NVDA does not expose its input layer.'))
    if not wanted.lower().startswith('kb:'):
        raise Refused(_('Only keyboard gestures can be sent, written kb:...'))

    def run():
        try:
            built = compat.KeyboardInputGesture.fromName(wanted[3:])
        except Exception:                            # noqa: BLE001
            if compat.ui is not None:
                compat.ui.message(_('NVDA does not know the gesture {name}.')
                                  .format(name=wanted))
            return
        try:
            compat.inputCore.manager.emulateGesture(built)
        except Exception as error:                   # noqa: BLE001
            if compat.log is not None:
                compat.log.error(f'Titan pressed {wanted}: {error}')
    _main(run)
    return {'pressed': wanted}


# --------------------------------------------------------------------------- #
def handlers():
    """What Titan may call. The table IS the boundary.

    The names are a READER's, not NVDA's: Titan reaches whichever reader's
    add-on is on the bus, and a second one implementing this same table
    works with no change on Titan's side. That is why nothing here is
    called ``nvda_something`` - the one thing a protocol must not be named
    after is its first implementation.
    """
    return {
        'context': _wrap(_context),
        'window': _wrap(_window),
        'describe': _wrap(describe),
        'speak': _wrap(speak),
        'stop': _wrap(stop),
        'say_all': _wrap(say_all),
        'review': _wrap(review),
        'read_focus': _wrap(read_focus),
        'mode': _wrap(mode),
        'settings': _wrap(settings),
        'setting': _wrap(setting),
        'synths': _wrap(synths),
        'use_synth': _wrap(use_synth),
        'voices': _wrap(voices),
        'use_voice': _wrap(use_voice),
        'press': _wrap(press),
    }


def _context(**kw):
    from . import context
    return context.read(**kw)


def _window(**kw):
    from . import context
    return context.window(**kw)


def _wrap(function):
    """A refusal is an ANSWER, not an exception across a pipe.

    Titan's caller is an assistant, a macro or a Titan Script, and every one
    of those shows the user what came back. A refusal that arrived as a
    transport error would be reported as "the reader did not answer", which
    is neither true nor something the user could act on; as a sentence it
    says which switch to turn on.
    """
    def call(**kw):
        try:
            return function(**kw)
        except Refused as refusal:
            return {'ok': False, 'refused': True, 'reason': str(refusal)}
        except Exception as error:                   # noqa: BLE001
            from . import compat as _compat
            if _compat.log is not None:
                _compat.log.error(f'Titan asked NVDA: {error}')
            return {'ok': False, 'reason': f'{type(error).__name__}: {error}'}
    return call

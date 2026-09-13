# -*- coding: utf-8 -*-
"""Sound schemes: a sound instead of a word, for what you already know.

JAWS calls this Speech and Sounds Schemes and it is the oldest good idea in
screen reading after Emacspeak's voices: a state that is said in words costs
a word every single time, and the word is the same length whether or not the
listener already knew. "Zaznaczone" on every row of a list you are arrowing
down is a syllable and a half per row, and a short tick is not.

:mod:`voices` is the same idea carried by the VOICE - a class heard rather
than said. This is the same idea carried by a SOUND, and the two are not
rivals: a voice can say what something IS while it is being read, and a
sound can replace a word entirely.

Three rules, and the first is the one that keeps this honest:

* **A sound is never the only way something is said.** Emacspeak's mistake
  to avoid is the one where the earcon becomes load-bearing: a listener with
  the sounds off, on a braille display, or in a room where they cannot hear
  a tick must lose nothing. So a state has three settings - said as a WORD
  (which is what NVDA does and the default), said as a SOUND, or BOTH - and
  choosing the sound is the user saying they already know the word.
* **The sounds are the reader's own.** They come from `sfx/<theme>/SRE/`
  where every one of this add-on's sounds lives, so a theme can replace any
  of them and a user with no Titan Access still has them.
* **It costs nothing until it is used.** A state nobody has given a sound is
  spoken exactly as NVDA spoke it, through the same path, with no work done
  at all.
"""

import json
import os
import threading

from . import i18n

_ = i18n.install(globals())

FILENAME = 'titanSoundScheme.json'

#: What a state may be answered with.
AS_WORD = 'word'
AS_SOUND = 'sound'
AS_BOTH = 'both'
WAYS = (AS_WORD, AS_SOUND, AS_BOTH)

#: The states worth replacing, and the sound each one gets by default. Only
#: states that are said OFTEN and that the listener nearly always already
#: expects: a tick box being ticked, a row being selected, a branch opening.
#: A state that is said rarely is one where the word is the right answer.
#:
#: NVDA's own state names, upper-cased, as `elements.STATE_ORDER` spells
#: them - so a state this NVDA does not have is simply never asked about.
STATES = {
    'CHECKED': 'clicked.ogg',
    'HALFCHECKED': 'doubletab.ogg',
    'SELECTED': 'listitem.ogg',
    'EXPANDED': 'menu_expanded.ogg',
    'COLLAPSED': 'menu_closed.ogg',
    'PRESSED': 'clicked.ogg',
    'UNAVAILABLE': 'error.ogg',
    'READONLY': 'system_item.ogg',
    'BUSY': 'ellipses.ogg',
    'HASPOPUP': 'sr_menu.ogg',
    'REQUIRED': 'notification.ogg',
    'PROTECTED': 'keyoff.ogg',
}

#: The add-on's own icon that says the same thing, for a state whose
#: sound comes from the BUILT-IN set: there on a machine with no Titan.
BUILTIN = {
    'CHECKED': 'on',
    'HALFCHECKED': 'item',
    'SELECTED': 'item',
    'EXPANDED': 'open-object',
    'COLLAPSED': 'close-object',
    'PRESSED': 'button',
    'UNAVAILABLE': 'warn-user',
    'READONLY': 'ellipses',
    'BUSY': 'progress',
    'HASPOPUP': 'open-object',
    'REQUIRED': 'alert-user',
    'PROTECTED': 'mark-object',
}

#: Where a state's sound comes from - the same three answers an auditory
#: icon has (:mod:`icons`). The reader's own set is Titan's, so a state
#: starts on Titan's sound; a machine with no Titan running plays the
#: built-in one instead rather than nothing.
SOURCE_BUILTIN = 'builtin'
SOURCE_TITAN = 'titan'
SOURCE_EXTERNAL = 'external'
SOURCES = (SOURCE_TITAN, SOURCE_BUILTIN, SOURCE_EXTERNAL)


def source_names():
    from . import icons
    return icons.source_names()


def state_names():
    return {
        # Translators: a control state, in the sound scheme manager.
        'CHECKED': _('ticked'),
        'HALFCHECKED': _('partly ticked'),
        'SELECTED': _('selected'),
        'EXPANDED': _('expanded'),
        'COLLAPSED': _('collapsed'),
        'PRESSED': _('pressed'),
        'UNAVAILABLE': _('unavailable'),
        'READONLY': _('read only'),
        'BUSY': _('busy'),
        # Translators: a control state - a menu item that opens a submenu.
        'HASPOPUP': _('has a submenu'),
        # Translators: a control state - a field that must be filled in.
        'REQUIRED': _('required'),
        # Translators: a control state - a password field.
        'PROTECTED': _('protected'),
    }


def way_names():
    return {
        # Translators: how a state is answered - in words, as NVDA does.
        AS_WORD: _('said as a word'),
        # Translators: how a state is answered - as a sound instead.
        AS_SOUND: _('a sound instead of the word'),
        # Translators: how a state is answered - both.
        AS_BOTH: _('a sound and the word'),
    }


_LOCK = threading.RLock()
_scheme = None
_state = {'sounds': 0, 'words': 0}


def report():
    with _LOCK:
        return dict(_state)


def _reader_folder():
    """NVDA's own configuration folder, or Titan's.

    This module is byte-identical in Titan Access, which has no NVDA under
    it; asking for both here is what lets it be. See
    `src/scripts/vendor_reader_modules.py`.
    """
    try:
        import globalVars
        return globalVars.appArgs.configPath
    except Exception:                                # noqa: BLE001
        pass
    try:
        import platform
        system = platform.system()
        if system == 'Windows':
            base = os.getenv('APPDATA') or os.path.expanduser('~')
            base = os.path.join(base, 'titosoft', 'Titan')
        elif system == 'Darwin':
            base = os.path.join(os.path.expanduser('~'), 'Library',
                                'Application Support', 'titosoft', 'Titan')
        else:
            base = os.path.join(os.path.expanduser('~'), '.config',
                                'titosoft', 'Titan')
        return os.path.join(base, 'screenreader')
    except Exception:                                # noqa: BLE001
        return ''


def path():
    folder = _reader_folder()
    return os.path.join(folder, FILENAME) if folder else ''


def _load():
    global _scheme
    with _LOCK:
        if _scheme is not None:
            return _scheme
        _scheme = {}
        where = path()
        if where and os.path.isfile(where):
            try:
                with open(where, encoding='utf-8') as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    for state, row in data.items():
                        if not isinstance(row, dict):
                            continue
                        way = str(row.get('way') or AS_WORD)
                        source = str(row.get('source') or SOURCE_TITAN)
                        _scheme[str(state).upper()] = {
                            'way': way if way in WAYS else AS_WORD,
                            'sound': str(row.get('sound') or ''),
                            'source': source if source in SOURCES
                            else SOURCE_TITAN,
                            'file': str(row.get('file') or ''),
                        }
            except Exception:                        # noqa: BLE001
                _scheme = {}
        return _scheme


def forget():
    global _scheme
    with _LOCK:
        _scheme = None


def save():
    where = path()
    if not where:
        return False
    with _LOCK:
        data = {state: dict(row) for state, row in _load().items()
                if row.get('way') != AS_WORD
                or row.get('source', SOURCE_TITAN) != SOURCE_TITAN
                or row.get('file')}
    try:
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1,
                      sort_keys=True)
        return True
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# What a state is answered with
# --------------------------------------------------------------------------- #
def way_of(state):
    row = _load().get(str(state).upper())
    return (row or {}).get('way', AS_WORD)


def sound_of(state):
    name = str(state).upper()
    row = _load().get(name) or {}
    return row.get('sound') or STATES.get(name, '')


def set_way(state, way, sound=''):
    name = str(state).upper()
    if way not in WAYS:
        return False
    with _LOCK:
        row = dict(_load().get(name) or {})
        row.update({'way': way,
                    'sound': str(sound or row.get('sound')
                                 or STATES.get(name, ''))})
        row.setdefault('source', SOURCE_TITAN)
        row.setdefault('file', '')
        _load()[name] = row
    return save()


def source_of(state):
    """``(source, file)`` for one state."""
    row = _load().get(str(state).upper()) or {}
    return row.get('source', SOURCE_TITAN), row.get('file', '')


def set_source(state, source, file=''):
    """Choose where one state's sound comes from. Answers what it is now."""
    name = str(state).upper()
    source = str(source or SOURCE_TITAN)
    if source not in SOURCES:
        return SOURCE_TITAN
    with _LOCK:
        row = dict(_load().get(name) or {})
        row.setdefault('way', AS_WORD)
        row.setdefault('sound', STATES.get(name, ''))
        row.update({'source': source, 'file': str(file or '')})
        _load()[name] = row
    save()
    return source


def reset(state=None):
    with _LOCK:
        scheme = _load()
        if state is None:
            scheme.clear()
        else:
            scheme.pop(str(state).upper(), None)
    return save()


def described():
    """Every state this can answer for, for the manager."""
    words = state_names()
    rows = []
    for state in sorted(STATES):
        source, chosen = source_of(state)
        rows.append({'state': state, 'label': words.get(state, state),
                     'way': way_of(state), 'sound': sound_of(state),
                     'source': source, 'external': chosen,
                     'builtin': BUILTIN.get(state, ''),
                     'changed': state in _load()})
    return rows


def wanted():
    """The scheme's own switch. A tree with no `configSpec` - Titan
    Access - has no switch yet, and absent means yes."""
    try:
        from . import configSpec
        return bool(configSpec.read().get('soundScheme', True))
    except Exception:                                # noqa: BLE001
        return True


# --------------------------------------------------------------------------- #
# Using it
# --------------------------------------------------------------------------- #
def answer(states):
    """``(words, sounds)`` for the states of one control.

    ``words`` is what is still to be SAID - which is every state whose
    answer is the word, and the ones the scheme says are both. ``sounds`` is
    what to play. A state nobody has touched comes back in ``words`` and
    nothing has been done to it at all.
    """
    words, sounds = [], []
    if not wanted():
        return list(states or []), sounds
    scheme = _load()
    for state in (states or []):
        name = str(state).upper()
        way = (scheme.get(name) or {}).get('way', AS_WORD)
        if way == AS_WORD:
            words.append(state)
            continue
        sound = sound_of(name)
        if not sound:
            words.append(state)
            continue
        # The STATE goes back, not the file: which sound it is and where it
        # comes from is decided when it is played (`play`), so a state
        # whose source is the built-in set or a file of the user's own is
        # answered the same way as one on Titan's.
        sounds.append(name)
        if way == AS_BOTH:
            words.append(state)
    with _LOCK:
        _state['sounds'] += len(sounds)
        _state['words'] += len(words)
    return words, sounds


def play(states):
    """The sounds for one control's states, in order, each from where the
    user said it comes from - Titan's set, the built-in one, or a file.

    ``states`` may also be file names, which is what a caller written
    before the sources were here still passes; those go to Titan's set as
    they always did.
    """
    if not states:
        return
    for one in states:
        try:
            _play_one(one)
        except Exception:                            # noqa: BLE001
            pass


def _reader_sound(name):
    """One of the reader's own set (`sfx/<theme>/SRE/`), through Titan -
    in-process where this runs inside Titan, over the bus from NVDA.
    `earcons` is the add-on's own module and is not in Titan Access."""
    from . import icons
    if icons.play_titan('reader/' + str(name)):
        return True
    try:
        from . import earcons
        return bool(earcons.play_named(str(name)))
    except Exception:                                # noqa: BLE001
        return False


def _play_one(state):
    from . import icons
    name = str(state).upper()
    if name not in STATES:
        # A file name from an older caller: the reader's own set.
        _reader_sound(str(state))
        return
    source, chosen = source_of(name)
    if source == SOURCE_EXTERNAL and icons.play_file(chosen):
        return
    if source == SOURCE_TITAN:
        if _reader_sound(sound_of(name)):
            return
    # Titan not there, or the built-in set asked for: the add-on's own.
    icons.play_file(icons.path_of(BUILTIN.get(name, '')))


def try_it(state):
    """Play what this state would sound like, for the manager."""
    play([str(state).upper()])

# -*- coding: utf-8 -*-
"""A command palette, in layers - one key in, one key to choose.

This add-on has a hundred and sixteen commands, and a keyboard has not got
a hundred and sixteen free chords. Binding every one of them is how a
reader ends up with `NVDA+alt+shift+g` and a user who has to keep a list;
leaving them unbound is how a feature ships and is never found.

JAWS has answered this for years with layered keystrokes, and the answer is
better than a longer list of shortcuts because of what it does for MEMORY:
one gesture opens a layer, the next key chooses inside it, and the letters
inside a layer can be the obvious ones - `w` for what this is written in,
`m` for the manager - because they only have to be unique within that
layer.

**A layer that swallows keys is worse than no layer at all**, so three
things bound it:

* it lasts for exactly ONE key, as JAWS' does, and then it is gone;
* it lets go by itself after :data:`SECONDS` - a layer entered by accident,
  or left open by a user who walked away, must not eat the next thing they
  type;
* a key the layer does not know leaves it and says so, rather than being
  silently eaten or silently passed on.

**And `?` or `h` says what is in it.** A layer nobody can enumerate is a
layer people guess at, which is the failure of every hidden shortcut ever
shipped. The help is built from the same table the keys are bound from, so
it cannot describe a command the layer has not got.
"""

import threading
import time

from . import i18n

_ = i18n.install(globals())

#: How long a layer waits for its key before letting go. Long enough to
#: think, short enough that a layer entered by accident is gone before the
#: user types anything they meant for the program.
SECONDS = 6.0

#: The keys that ask what the layer offers, in every layer.
HELP_KEYS = ('?', 'h')

#: The layers, and what is in them. ``(command, one line about it)`` per
#: key, where ``command`` is a function of :mod:`commands` - so a layer
#: can never offer something that does not exist, and a test checks it.
#:
#: The letters are chosen to be obvious IN THEIR LAYER, which is the whole
#: reason a layer is worth having: `w` is "written in" here and "where am
#: I" in the reading layer, and neither has to give way to the other.
LAYERS = {
    'reading': {
        'name': lambda: _('Reading'),
        'keys': {
            'w': ('where_am_i', lambda: _('Where am I')),
            'd': ('describe_control', lambda: _('What does this show')),
            'n': ('label_control', lambda: _('Name this control')),
            'c': ('customise_control', lambda: _('Customise this control')),
            'r': ('read_locally', lambda: _('Read this window')),
            's': ('ocr_review', lambda: _('Screen review')),
            'j': ('read_journal', lambda: _('What has been said')),
        },
    },
    'program': {
        'name': lambda: _('This program'),
        'keys': {
            'w': ('what_is_this_written_in', lambda: _('What it is written in')),
            'm': ('check_module', lambda: _('Does its module work')),
            'd': ('draft_module', lambda: _('Write a module for it')),
            'l': ('reader_modules', lambda: _('The modules installed')),
        },
    },
    'manager': {
        'name': lambda: _('Managers'),
        'keys': {
            'm': ('manager', lambda: _('The manager')),
            'v': ('voice_classes', lambda: _('Voices and reading order')),
            't': ('status', lambda: _('Is Titan there')),
            's': ('share_names', lambda: _('Share names with Titan Access')),
        },
    },
}

_LOCK = threading.RLock()
_open = ''            # which layer is open, '' for none
_opened_at = 0.0
_counted = {'entered': 0, 'used': 0, 'timed_out': 0, 'unknown': 0,
            'helped': 0}


def names():
    """The layers, in the order a person would meet them."""
    return list(LAYERS)


def keys_of(layer):
    """``{key: (command, description)}`` for one layer, or ``{}``."""
    found = LAYERS.get(str(layer or ''))
    return dict((found or {}).get('keys') or {})


def label(layer):
    found = LAYERS.get(str(layer or ''))
    if not found:
        return ''
    said = found.get('name')
    try:
        return said() if callable(said) else str(said or '')
    except Exception:                                # noqa: BLE001
        return str(layer)


def open_layer():
    """Which layer is open right now, or ``''``.

    Asked rather than remembered by the caller, because a layer that has
    timed out is closed even though nothing has run since.
    """
    with _LOCK:
        if not _open:
            return ''
        if time.time() - _opened_at > SECONDS:
            globals()['_open'] = ''
            _counted['timed_out'] += 1
            return ''
        return _open


def enter(layer):
    """Open a layer. ``(ok, what to say)``."""
    if str(layer or '') not in LAYERS:
        return False, ''
    with _LOCK:
        globals()['_open'] = str(layer)
        globals()['_opened_at'] = time.time()
        _counted['entered'] += 1
    # Translators: said when a layer of commands is opened. {name} is the
    # layer, {count} how many keys it offers.
    return True, _('{name}: {count} keys, ? for help').format(
        name=label(layer), count=len(keys_of(layer)))


def leave():
    with _LOCK:
        was = _open
        globals()['_open'] = ''
    return was


def help_for(layer):
    """Every line of the layer's own help, from the table it is bound from."""
    lines = []
    for key, (_command, said) in sorted(keys_of(layer).items()):
        try:
            text = said() if callable(said) else str(said or '')
        except Exception:                            # noqa: BLE001
            text = ''
        lines.append('%s - %s' % (key, text))
    return lines


def chose(key):
    """A key was pressed while a layer was open. ``(what, value)``.

    ``what`` is 'help', 'command', 'unknown' or 'closed', and for a
    command ``value`` is the name of the function in :mod:`commands` to
    run. The layer is closed by every one of them: a layer lasts for one
    key, which is what stops it eating the next thing typed.
    """
    layer = open_layer()
    if not layer:
        return 'closed', ''
    leave()
    pressed = str(key or '').lower()
    if pressed in HELP_KEYS:
        with _LOCK:
            _counted['helped'] += 1
        return 'help', layer
    found = keys_of(layer).get(pressed)
    if not found:
        with _LOCK:
            _counted['unknown'] += 1
        return 'unknown', layer
    with _LOCK:
        _counted['used'] += 1
    return 'command', found[0]


def unknown_sentence(layer):
    # Translators: said when a key is pressed in a layer that has no such
    # key. {key} is not named because the user knows what they pressed.
    return _('Not in {name}. Press ? in a layer for what is in it.').format(
        name=label(layer))


def report():
    with _LOCK:
        found = dict(_counted)
    found['open'] = open_layer()
    found['layers'] = len(LAYERS)
    found['keys'] = sum(len(keys_of(name)) for name in LAYERS)
    return found


def forget():
    with _LOCK:
        globals()['_open'] = ''
        for key in _counted:
            _counted[key] = 0

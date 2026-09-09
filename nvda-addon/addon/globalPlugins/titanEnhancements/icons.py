# -*- coding: utf-8 -*-
"""Auditory icons: what happened, before the words arrive.

Emacspeak's oldest idea and the one it is most right about. A sound under a
quarter of a second, played the instant something happens, says what KIND
of thing it was while the synthesizer is still drawing breath - you are on
a button, something opened, that was refused. T. V. Raman's comparison is
the one worth keeping: it is the difference between a monochrome display
and a colour one. Nothing is taken away; everything arrives sooner.

**The names are Emacspeak's own** - `select-object`, `open-object`,
`task-done`, `warn-user` - taken from its `sounds/chimes` theme, so anybody
who has used Emacspeak already knows what they mean, and a theme written
for one could be dropped in for the other. A module asks for a NAME and
never for a file, which is what makes a theme a folder that can be swapped.

**The sounds are the add-on's own.** They ship with it and are played with
NVDA's own `nvwave`, so an icon sounds with no Titan running, no Titan
Access installed and no sound theme chosen - which is the whole point of
them being here rather than being asked of the desktop. `sounds/` is made
by `nvda-addon/make_sounds.py` from a table of frequencies, so they are
auditable and changeable rather than a binary nobody can read.

**A user's own folder wins.** `titanIcons/` in NVDA's configuration is
looked in first, so replacing one is dropping a `.wav` in with the right
name - the overlay rule Titan's own `data/` and this add-on's reader
modules already follow. A name with no file anywhere is silence and a
recorded reason, never an error.

**Never in the way.** An icon is fire-and-forget on NVDA's own audio, it
never blocks, and it is not speech - so nothing an icon does can delay,
interrupt or replace a word. Turning them all off leaves the reader exactly
as it was.
"""

import json
import os
import threading

from . import compat
from . import i18n

_ = i18n.install(globals())

#: Where the ones this add-on ships live.
OURS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sounds')

#: The user's own, looked in first.
THEIRS = 'titanIcons'

#: Every icon this add-on knows how to ask for, with what it marks. The
#: list is what the manager shows, so a name with no meaning here would be
#: a row nobody could have an opinion about.
def meanings():
    return {
        # Translators: an auditory icon, shown in the icon manager.
        'select-object': _('moving onto something'),
        'item': _('a row of a list'),
        'button': _('a button'),
        'large-movement': _('a jump - a page, the end'),
        'ellipses': _('something too long to be read out whole'),
        'open-object': _('going into something'),
        'close-object': _('coming back out'),
        'section': _('a new part of a window'),
        'paragraph': _('a paragraph'),
        'on': _('ticked, switched on'),
        'off': _('unticked, switched off'),
        'mark-object': _('a place marker made'),
        'deselect-object': _('no longer selected'),
        'task-done': _('it worked'),
        'save-object': _('saved'),
        'delete-object': _('deleted'),
        'modified-object': _('changed'),
        'unmodified-object': _('unchanged'),
        'yank-object': _('pasted in'),
        'warn-user': _('refused - it will not do that'),
        'alert-user': _('something wants attention'),
        'ask-question': _('a question, waiting for an answer'),
        'help': _('help'),
        'new-mail': _('something arrived'),
        'progress': _('it is still going'),
        'search-hit': _('found'),
        'search-miss': _('not found'),
        'yes-answer': _('yes'),
        'no-answer': _('no'),
    }


NAMES = tuple(sorted(meanings().keys()))

_LOCK = threading.RLock()
_state = {'played': 0, 'missing': [], 'why': ''}


def report():
    with _LOCK:
        return dict(_state, names=len(NAMES), folder=OURS,
                    on=switched_on())


def _config():
    try:
        import globalVars
        return globalVars.appArgs.configPath
    except Exception:                                # noqa: BLE001
        return ''


def their_folder():
    where = _config()
    return os.path.join(where, THEIRS) if where else ''


def path_of(name):
    """The file for an icon: the user's own first, then the add-on's.

    Both spellings are tried because a user replacing a sound will have
    whatever their recorder made, and refusing a `.ogg` because we ship
    `.wav` would be a rule with no reason behind it. NVDA's `nvwave` plays
    wave files, so an `.ogg` is only found where NVDA can take it.
    """
    name = str(name or '').strip()
    if not name or '/' in name or '\\' in name or name.startswith('.'):
        return ''
    for folder in (their_folder(), OURS):
        if not folder:
            continue
        for suffix in ('.wav', '.ogg'):
            where = os.path.join(folder, name + suffix)
            if os.path.isfile(where):
                return where
    return ''


def switched_on():
    """Whether icons are wanted at all. Absent means yes.

    They ship ON, unlike the cursor earcons, and the difference is real: a
    cursor cue is played on EVERY control the focus reaches, all day, in
    every program; an icon here is played by this add-on's own surfaces -
    the reviews, the Titan window - which the user opened deliberately.
    """
    from . import configSpec
    return bool(configSpec.read().get('auditoryIcons', True))


#: The manager's own store, beside the markers, the monitors and the sound
#: scheme. Which icons are OFF is a thing the user made, so it belongs in a
#: store of its own rather than in the settings page - the same rule every
#: other manager here follows, and it keeps the page a page of switches.
FILENAME = 'titanIcons.json'

_off = None


def path():
    where = _config()
    return os.path.join(where, FILENAME) if where else ''


def _load():
    global _off
    with _LOCK:
        if _off is not None:
            return _off
        _off = set()
        where = path()
        if where and os.path.isfile(where):
            try:
                with open(where, encoding='utf-8') as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    data = data.get('off')
                if isinstance(data, list):
                    _off = {str(name) for name in data}
            except Exception:                        # noqa: BLE001
                _off = set()
        return _off


def forget():
    global _off
    with _LOCK:
        _off = None


def save():
    where = path()
    if not where:
        return False
    with _LOCK:
        data = sorted(_load())
    try:
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump({'off': data}, handle, ensure_ascii=False, indent=1)
        return True
    except Exception:                                # noqa: BLE001
        return False


def wanted(name):
    """Whether this particular icon is wanted."""
    if not switched_on():
        return False
    return str(name) not in _load()


def set_wanted(name, on):
    """Turn one icon on or off. Answers what it is now."""
    with _LOCK:
        if on:
            _load().discard(str(name))
        else:
            _load().add(str(name))
    save()
    return bool(on)


def described():
    """Every icon, for the manager: name, meaning, whether it sounds."""
    words = meanings()
    rows = []
    for name in NAMES:
        rows.append({'id': name, 'meaning': words.get(name, ''),
                     'on': str(name) not in _load(),
                     'file': path_of(name)})
    return rows


def play(name, wait=False):
    """Play one icon by name. Answers whether it really sounded.

    Never raises and never blocks: an icon is decoration on top of
    something that is already being said, and a reader that stumbled
    because a sound file was missing would be a worse reader than one with
    no icons at all.
    """
    if not wanted(name):
        return False
    where = path_of(name)
    if not where:
        with _LOCK:
            if name not in _state['missing']:
                _state['missing'].append(str(name))
        return False
    wave = compat.nvwave
    if wave is None:
        with _LOCK:
            _state['why'] = 'this NVDA has no nvwave'
        return False
    try:
        wave.playWaveFile(where, asynchronous=not wait)
    except TypeError:
        # Older NVDA: `async` rather than `asynchronous`, and no keyword at
        # all further back. A sound that will not play is not worth an
        # exception in a focus handler.
        try:
            wave.playWaveFile(where)
        except Exception:                            # noqa: BLE001
            return False
    except Exception:                                # noqa: BLE001
        return False
    with _LOCK:
        _state['played'] += 1
    return True


def for_control(kind):
    """The icon that belongs to a kind of control, or ''.

    One place that knows the mapping, so the review, the window and
    anything added later cannot disagree about what a button sounds like.
    """
    return {
        'button': 'button',
        'check': 'select-object',
        'choice': 'select-object',
        'list': 'item',
        'table': 'item',
        'tree': 'item',
        'text': 'select-object',
        'multiline': 'select-object',
        'slider': 'progress',
        'gauge': 'progress',
        'tabs': 'section',
        'label': 'paragraph',
    }.get(str(kind or ''), 'select-object')


#: An NVDA control role -> the icon that belongs to it. Roles are NVDA's
#: own spelling (`Role.BUTTON.name`), upper case, so a role this table has
#: not heard of falls through to the general "you moved onto something"
#: rather than being silent.
BY_ROLE = {
    'BUTTON': 'button', 'TOGGLEBUTTON': 'button', 'SPLITBUTTON': 'button',
    'MENUBUTTON': 'button', 'DROPDOWNBUTTON': 'button',
    'CHECKBOX': 'select-object', 'RADIOBUTTON': 'select-object',
    'LISTITEM': 'item', 'TREEVIEWITEM': 'item', 'TABLECELL': 'item',
    'DATAITEM': 'item', 'MENUITEM': 'item', 'TAB': 'section',
    'LIST': 'open-object', 'TREEVIEW': 'open-object', 'TABLE': 'open-object',
    'COMBOBOX': 'open-object', 'MENU': 'open-object',
    'POPUPMENU': 'open-object', 'MENUBAR': 'open-object',
    'DIALOG': 'ask-question', 'ALERT': 'alert-user',
    'PROGRESSBAR': 'progress', 'SLIDER': 'progress', 'SCROLLBAR': 'progress',
    'EDITABLETEXT': 'select-object', 'PASSWORDEDIT': 'select-object',
    'DOCUMENT': 'open-object', 'HEADING': 'section', 'LINK': 'yank-object',
    'GRAPHIC': 'paragraph', 'STATICTEXT': 'paragraph',
    'TOOLBAR': 'section', 'PANE': 'section', 'WINDOW': 'section',
    'PROPERTYPAGE': 'section', 'GROUPING': 'section',
    'TERMINAL': 'open-object', 'SPINBUTTON': 'progress',
}


def for_role(role):
    """The icon for a control NVDA is about to read, or ''.

    Emacspeak's idea taken outside the add-on's own windows, which is what
    it is for: you are told you are on a button, in a list, at a heading,
    before the synthesizer has said a syllable. It is purely ADDITIVE -
    an icon never replaces, delays or shortens a word - which is why this
    one may ship on where everything else that changes how the whole
    machine is read ships off.
    """
    name = ''
    try:
        name = str(getattr(role, 'name', '') or role or '')
    except Exception:                                # noqa: BLE001
        name = ''
    return BY_ROLE.get(name.upper().replace(' ', ''), 'select-object')


def everywhere():
    """Whether icons play on every control, not only in our own windows."""
    from . import configSpec
    return switched_on() and bool(
        configSpec.read().get('auditoryIconsEverywhere', True))


def for_focus(obj):
    """Play the icon for the control the focus has reached. Never waits."""
    if not everywhere():
        return False
    try:
        role = getattr(obj, 'role', None)
    except Exception:                                # noqa: BLE001
        return False
    return play(for_role(role))


def try_it(name):
    """Play one whatever the switches say - the manager's Try button."""
    where = path_of(name)
    if not where or compat.nvwave is None:
        return False
    try:
        compat.nvwave.playWaveFile(where, asynchronous=True)
        return True
    except Exception:                                # noqa: BLE001
        return False

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

#: Where an icon's sound comes from. **The built-in one** is the wave file
#: this add-on ships (or the user's own in `titanIcons/`), played by NVDA
#: itself and there on any machine. **Titan's own** is the sound Titan's
#: desktop plays for the same event, out of the user's sound theme,
#: through Titan's mixer - so a reader in Titan sounds like Titan; it
#: needs Titan running and falls back to the built-in one when it is not.
#: **An external file** is any wave file the user chose.
SOURCE_BUILTIN = 'builtin'
SOURCE_TITAN = 'titan'
SOURCE_EXTERNAL = 'external'
SOURCES = (SOURCE_BUILTIN, SOURCE_TITAN, SOURCE_EXTERNAL)


def source_names():
    return {
        # Translators: where an icon's sound comes from - the add-on's own.
        SOURCE_BUILTIN: _('the built-in sound'),
        # Translators: where an icon's sound comes from - Titan's theme.
        SOURCE_TITAN: _("Titan's own sound"),
        # Translators: where an icon's sound comes from - a file chosen.
        SOURCE_EXTERNAL: _('a sound file of your own'),
    }


#: The sound Titan's own desktop plays for the same event, by the name the
#: theme knows it under. `reader/` is the reader's own set (`sfx/<theme>/
#: SRE/`), everything else is the theme's own. A name Titan has not got is
#: silence at Titan's end and the built-in sound at ours.
TITAN_SOUNDS = {
    'select-object': 'core/FOCUS.ogg',
    'item': 'reader/listitem.ogg',
    'button': 'reader/cursor.ogg',
    'large-movement': 'ui/endoflist.ogg',
    'ellipses': 'reader/ellipses.ogg',
    'open-object': 'ui/uiopen.ogg',
    'close-object': 'ui/uiclose.ogg',
    'section': 'ui/sectionchange.ogg',
    'paragraph': 'ui/statusbar.ogg',
    'on': 'reader/keyon.ogg',
    'off': 'reader/keyoff.ogg',
    'mark-object': 'ui/drop.ogg',
    'deselect-object': 'ui/drag.ogg',
    'task-done': 'core/SELECT.ogg',
    'save-object': 'core/SELECT.ogg',
    'delete-object': 'ui/X.ogg',
    'modified-object': 'ui/notify.ogg',
    'unmodified-object': 'ui/statusbar.ogg',
    'yank-object': 'ui/drop.ogg',
    'warn-user': 'core/error.ogg',
    'alert-user': 'reader/notification.ogg',
    'ask-question': 'reader/question_dialog.ogg',
    'help': 'ui/tip.ogg',
    'new-mail': 'ui/notify.ogg',
    'progress': 'ui/buffer_ping.ogg',
    'search-hit': 'core/SELECT.ogg',
    'search-miss': 'core/error.ogg',
    'yes-answer': 'core/SELECT.ogg',
    'no-answer': 'core/error.ogg',
}

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

    A tree with no `configSpec` - Titan Access - has no switch for them
    yet, and absent means yes there too.
    """
    try:
        from . import configSpec
        return bool(configSpec.read().get('auditoryIcons', True))
    except Exception:                                # noqa: BLE001
        return True


#: The manager's own store, beside the markers, the monitors and the sound
#: scheme. Which icons are OFF is a thing the user made, so it belongs in a
#: store of its own rather than in the settings page - the same rule every
#: other manager here follows, and it keeps the page a page of switches.
FILENAME = 'titanIcons.json'

_off = None
_sources = {}


def path():
    where = _config()
    return os.path.join(where, FILENAME) if where else ''


def _load():
    global _off, _sources
    with _LOCK:
        if _off is not None:
            return _off
        _off = set()
        _sources = {}
        where = path()
        if where and os.path.isfile(where):
            try:
                with open(where, encoding='utf-8') as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    sources = data.get('sources')
                    if isinstance(sources, dict):
                        for name, row in sources.items():
                            if not isinstance(row, dict):
                                continue
                            source = str(row.get('source') or SOURCE_BUILTIN)
                            _sources[str(name)] = {
                                'source': source if source in SOURCES
                                else SOURCE_BUILTIN,
                                'file': str(row.get('file') or '')}
                    data = data.get('off')
                if isinstance(data, list):
                    _off = {str(name) for name in data}
            except Exception:                        # noqa: BLE001
                _off = set()
                _sources = {}
        return _off


def forget():
    global _off, _sources
    with _LOCK:
        _off = None
        _sources = {}


def save():
    where = path()
    if not where:
        return False
    with _LOCK:
        data = sorted(_load())
        sources = {name: dict(row) for name, row in _sources.items()
                   if row.get('source') != SOURCE_BUILTIN or row.get('file')}
    try:
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump({'off': data, 'sources': sources}, handle,
                      ensure_ascii=False, indent=1)
        return True
    except Exception:                                # noqa: BLE001
        return False


def source_of(name):
    """``(source, file)`` for one icon - built-in unless the user chose."""
    _load()
    with _LOCK:
        row = _sources.get(str(name)) or {}
    return row.get('source', SOURCE_BUILTIN), row.get('file', '')


def set_source(name, source, file=''):
    """Choose where one icon's sound comes from. Answers what it is now."""
    source = str(source or SOURCE_BUILTIN)
    if source not in SOURCES:
        return SOURCE_BUILTIN
    _load()
    with _LOCK:
        _sources[str(name)] = {'source': source, 'file': str(file or '')}
    save()
    return source


def titan_name(name):
    """What Titan calls the sound for this icon, or ''."""
    return TITAN_SOUNDS.get(str(name), '')


#: What NVDA's own player takes. Anything else - `.ogg` above all, which
#: is what every sound in Titan's themes is - goes through Titan's mixer,
#: which decodes it; without Titan such a file cannot sound here, and the
#: caller falls back to the built-in wave file.
NVDA_PLAYS = ('.wav',)


def play_file(where, wait=False):
    """One sound file - a wave file through NVDA's own player, anything
    else (`.ogg`, `.mp3`, `.flac`) through Titan's mixer. Never raises."""
    where = str(where or '')
    if not where or not os.path.isfile(where):
        return False
    if os.path.splitext(where)[1].lower() not in NVDA_PLAYS:
        return play_titan(where)
    wave = compat.nvwave
    if wave is None:
        # No player of the reader's own - which is the case inside Titan
        # Access, where this module runs with Titan's mixer underneath it.
        if play_titan(where):
            return True
        with _LOCK:
            _state['why'] = 'this NVDA has no nvwave'
        return False
    try:
        wave.playWaveFile(where, asynchronous=not wait)
    except TypeError:
        try:
            wave.playWaveFile(where)
        except Exception:                            # noqa: BLE001
            return False
    except Exception:                                # noqa: BLE001
        return False
    return True


def play_titan(theme_name):
    """One of Titan's own sounds - or a FILE, by its absolute path -
    through Titan's mixer. Never waits.

    Answers whether Titan is there to be asked - the sound itself plays on
    Titan's side, later, and cannot be waited for from a focus event.
    """
    theme_name = str(theme_name or '').strip()
    if not theme_name:
        return False
    # **Inside Titan, Titan's mixer is a call away.** This module is the
    # same file in Titan Access, which runs in Titan's own process: there
    # the bus would be a round trip to ourselves, and the sound module is
    # right here. Outside Titan that import fails and the bus is the way.
    if _play_in_process(theme_name):
        return True
    try:
        from .link import LINK
        if not LINK.connected():
            return False
    except Exception:                                # noqa: BLE001
        return False
    import threading as _threading

    def send():
        try:
            LINK.bridge('sounds.play', timeout=3.0, name=theme_name)
        except Exception:                            # noqa: BLE001
            pass
    _threading.Thread(target=send, name='TitanIcon', daemon=True).start()
    return True


def _play_in_process(theme_name):
    """Titan's own sound module, when this runs inside Titan. Never raises."""
    try:
        from src.titan_core import sound
    except Exception:                                # noqa: BLE001
        return False
    try:
        lowered = theme_name.lower()
        if os.path.isabs(theme_name):
            return bool(sound.play_sound_file(theme_name))
        if lowered.startswith(('reader/', 'sre/')):
            return bool(sound.play_reader_sound(theme_name.split('/', 1)[1]))
        sound.play_sound(theme_name)
        return True
    except Exception:                                # noqa: BLE001
        return False


def play_by_source(name, source, file='', wait=False):
    """Play an icon from where the user said, falling back to built-in.

    A source that cannot answer - Titan not running, a file that has gone -
    is not silence: the built-in sound stands in, because an icon that
    quietly stops sounding is one the user will think they switched off.
    """
    if source == SOURCE_TITAN and play_titan(titan_name(name)):
        return True
    if source == SOURCE_EXTERNAL and play_file(file, wait=wait):
        return True
    return play_file(path_of(name), wait=wait)


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
    """Every icon, for the manager: name, meaning, whether it sounds, and
    where its sound comes from."""
    words = meanings()
    rows = []
    for name in NAMES:
        source, chosen = source_of(name)
        rows.append({'id': name, 'meaning': words.get(name, ''),
                     'on': str(name) not in _load(),
                     'file': path_of(name),
                     'source': source, 'external': chosen,
                     'titan': titan_name(name)})
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
    source, chosen = source_of(name)
    if source == SOURCE_BUILTIN and not path_of(name):
        with _LOCK:
            if name not in _state['missing']:
                _state['missing'].append(str(name))
        return False
    if not play_by_source(name, source, chosen, wait=wait):
        with _LOCK:
            if name not in _state['missing']:
                _state['missing'].append(str(name))
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
    """Play one whatever the switches say - the manager's Try button,
    from wherever the user has chosen it comes from."""
    source, chosen = source_of(name)
    return play_by_source(name, source, chosen)

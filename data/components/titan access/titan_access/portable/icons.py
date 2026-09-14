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
        'help': _('help is opened'),
        'new-mail': _('something arrived'),
        'progress': _('it is still going'),
        'search-hit': _('found'),
        'search-miss': _('not found'),
        'yes-answer': _('yes'),
        'no-answer': _('no'),
    }


NAMES = tuple(sorted(meanings().keys()))


#: **A sound belongs to an EVENT of the reader, not to a file.** The user
#: asked for exactly that: "dźwięk ma być per akcja NVDA, a nie per nazwa
#: dźwięku". So the focus landing on a button is an event of its own, the
#: focus landing on a check box another, and each has its own sound and
#: its own source - where before every one of them shared "select-object"
#: and the manager listed the FILE names. The Emacspeak names stay as the
#: built-in SOUNDS an event plays by default; they are not what the user
#: chooses between.
#:
#: ``focus.<kind>`` events, in the order the manager shows them, with the
#: built-in icon each plays unless the user says otherwise.
FOCUS_EVENTS = (
    ('focus.button', 'button'),
    ('focus.checkbox', 'select-object'),
    ('focus.radiobutton', 'select-object'),
    ('focus.edit', 'select-object'),
    ('focus.combobox', 'open-object'),
    ('focus.listitem', 'item'),
    ('focus.list', 'open-object'),
    ('focus.treeitem', 'item'),
    ('focus.tablecell', 'item'),
    ('focus.link', 'yank-object'),
    ('focus.heading', 'section'),
    ('focus.menuitem', 'item'),
    ('focus.menu', 'open-object'),
    ('focus.tab', 'section'),
    ('focus.slider', 'progress'),
    ('focus.progressbar', 'progress'),
    ('focus.dialog', 'ask-question'),
    ('focus.document', 'open-object'),
    ('focus.text', 'paragraph'),
    ('focus.graphic', 'paragraph'),
    ('focus.toolbar', 'section'),
    ('focus.pane', 'section'),
    ('focus.other', 'select-object'),
)
FOCUS_DEFAULTS = dict(FOCUS_EVENTS)


def focus_labels():
    return {
        # Translators: a reader event, in the sounds manager: the focus
        # lands on this kind of control.
        'focus.button': _('The focus lands on a button'),
        'focus.checkbox': _('The focus lands on a check box'),
        'focus.radiobutton': _('The focus lands on a radio button'),
        'focus.edit': _('The focus lands on an edit field'),
        'focus.combobox': _('The focus lands on a combo box'),
        'focus.listitem': _('The focus lands on a list item'),
        'focus.list': _('The focus lands on a list'),
        'focus.treeitem': _('The focus lands on a tree item'),
        'focus.tablecell': _('The focus lands on a table cell'),
        'focus.link': _('The focus lands on a link'),
        'focus.heading': _('The focus lands on a heading'),
        'focus.menuitem': _('The focus lands on a menu item'),
        'focus.menu': _('The focus lands on a menu'),
        'focus.tab': _('The focus lands on a tab'),
        'focus.slider': _('The focus lands on a slider'),
        'focus.progressbar': _('The focus lands on a progress bar'),
        'focus.dialog': _('A dialog comes up'),
        'focus.document': _('The focus lands on a document'),
        'focus.text': _('The focus lands on plain text'),
        'focus.graphic': _('The focus lands on a picture'),
        'focus.toolbar': _('The focus lands on a toolbar'),
        'focus.pane': _('The focus lands on a pane or a group'),
        'focus.other': _('The focus lands on anything else'),
    }


#: NVDA's role names (upper case) -> the focus event each is.
ROLE_EVENTS = {
    'BUTTON': 'focus.button', 'TOGGLEBUTTON': 'focus.button',
    'SPLITBUTTON': 'focus.button', 'MENUBUTTON': 'focus.button',
    'DROPDOWNBUTTON': 'focus.button',
    'CHECKBOX': 'focus.checkbox', 'RADIOBUTTON': 'focus.radiobutton',
    'EDITABLETEXT': 'focus.edit', 'PASSWORDEDIT': 'focus.edit',
    'COMBOBOX': 'focus.combobox',
    'LISTITEM': 'focus.listitem', 'DATAITEM': 'focus.listitem',
    'LIST': 'focus.list', 'TREEVIEW': 'focus.list', 'TABLE': 'focus.list',
    'TREEVIEWITEM': 'focus.treeitem', 'TABLECELL': 'focus.tablecell',
    'LINK': 'focus.link', 'HEADING': 'focus.heading',
    'MENUITEM': 'focus.menuitem', 'MENU': 'focus.menu',
    'POPUPMENU': 'focus.menu', 'MENUBAR': 'focus.menu',
    'TAB': 'focus.tab', 'SLIDER': 'focus.slider', 'SPINBUTTON': 'focus.slider',
    'SCROLLBAR': 'focus.slider', 'PROGRESSBAR': 'focus.progressbar',
    'DIALOG': 'focus.dialog', 'ALERT': 'focus.dialog',
    'DOCUMENT': 'focus.document', 'TERMINAL': 'focus.document',
    'STATICTEXT': 'focus.text', 'GRAPHIC': 'focus.graphic',
    'TOOLBAR': 'focus.toolbar', 'PANE': 'focus.pane', 'WINDOW': 'focus.pane',
    'PROPERTYPAGE': 'focus.pane', 'GROUPING': 'focus.pane',
}


#: **Everything else the reader DOES**, each an event with a sound of its
#: own: ``(id, built-in icon, Titan's reader sound)``. The built-in icon
#: is what plays with no Titan; Titan's is the reader's own set
#: (`sfx/<theme>/SRE/`), which is what these events have always sounded
#: like under Titan Access, so a reader event starts on Titan's sound.
READER_EVENTS = (
    ('reader.virtual-on', 'open-object', 'reader/vscreenOn.ogg'),
    ('reader.virtual-off', 'close-object', 'reader/vscreenOff.ogg'),
    ('reader.palette-open', 'open-object', 'reader/sr_menu.ogg'),
    ('reader.palette-close', 'close-object', 'reader/sr_menu_close.ogg'),
    ('reader.review-on', 'open-object', 'reader/vscreenOn.ogg'),
    ('reader.review-off', 'close-object', 'reader/vscreenOff.ogg'),
    ('reader.edge', 'large-movement', 'reader/edge.ogg'),
    ('reader.corner', 'large-movement', 'reader/srcursor_item.ogg'),
    ('reader.layout-changed', 'section', 'reader/system_item.ogg'),
    ('reader.interact-in', 'open-object', 'reader/zoomin.ogg'),
    ('reader.interact-out', 'close-object', 'reader/zoomout.ogg'),
    ('reader.gesture-start', 'select-object', 'reader/system_item.ogg'),
    ('reader.explore-start', 'open-object', 'reader/cursor_static.ogg'),
    ('reader.explore', 'item', 'reader/cursor.ogg'),
    ('reader.click', 'button', 'reader/clicked.ogg'),
    ('reader.menu-open', 'open-object', 'reader/menu_expanded.ogg'),
    ('reader.menu-close', 'close-object', 'reader/menu_closed.ogg'),
    ('reader.menu-left', 'close-object', 'reader/sr_menu_close.ogg'),
    ('reader.dialog.question', 'ask-question', 'reader/question_dialog.ogg'),
    ('reader.dialog.warning', 'warn-user', 'reader/warning_dialog.ogg'),
    ('reader.dialog.error', 'warn-user', 'reader/error_dialog.ogg'),
    ('reader.dialog.information', 'help', 'reader/information_dialog.ogg'),
    ('reader.busy', 'progress', 'reader/ellipses.ogg'),
    ('reader.ready', 'task-done', 'reader/clicked.ogg'),
    ('reader.attention', 'alert-user', 'reader/notification.ogg'),
    ('reader.live-region', 'modified-object', 'reader/notification.ogg'),
    ('reader.monitor-changed', 'new-mail', 'reader/notification.ogg'),
    ('reader.marker-made', 'mark-object', 'reader/clicked.ogg'),
    ('reader.marker-reached', 'search-hit', 'reader/srcursor_item.ogg'),
    ('reader.procedure-recording', 'on', 'reader/keyon.ogg'),
    ('reader.procedure-kept', 'save-object', 'reader/keyoff.ogg'),
    ('reader.procedure-done', 'task-done', 'reader/clicked.ogg'),
    ('reader.trackpad-on', 'on', 'reader/sron.ogg'),
    ('reader.trackpad-off', 'off', 'reader/sroff.ogg'),
    ('reader.titan-connected', 'task-done', 'reader/controller_initialize.ogg'),
    ('reader.titan-disconnected', 'off', 'reader/controller_uninitialize.ogg'),
)
READER_DEFAULTS = {event: icon for event, icon, _titan in READER_EVENTS}
READER_TITAN = {event: titan for event, _icon, titan in READER_EVENTS}


def reader_labels():
    return {
        # Translators: a reader event, in the sounds manager.
        'reader.virtual-on': _('The virtual window is turned on'),
        'reader.virtual-off': _('The virtual window is turned off'),
        'reader.palette-open': _('The palette or a message opens'),
        'reader.palette-close': _('The palette or a message closes'),
        'reader.review-on': _('The screen review is turned on'),
        'reader.review-off': _('The screen review is turned off'),
        'reader.edge': _('The end of a list is reached'),
        'reader.corner': _('A corner of the window is reached'),
        'reader.layout-changed': _('The layout of the arrows changes'),
        'reader.interact-in': _('Stepping into a control'),
        'reader.interact-out': _('Stepping out of a control'),
        # Translators: the first finger touches the trackpad.
        'reader.gesture-start': _('The start of a gesture'),
        # Translators: one finger begins to move over the trackpad.
        'reader.explore-start': _('The start of exploration'),
        'reader.explore': _('A finger explores onto a control'),
        'reader.click': _('A control is clicked'),
        'reader.menu-open': _('A menu opens'),
        'reader.menu-close': _('A menu closes'),
        'reader.menu-left': _('The menus are left'),
        'reader.dialog.question': _('A question dialog appears'),
        'reader.dialog.warning': _('A warning dialog appears'),
        'reader.dialog.error': _('An error dialog appears'),
        'reader.dialog.information': _('An information dialog appears'),
        'reader.busy': _('A program becomes busy'),
        'reader.ready': _('A program is ready again'),
        'reader.attention': _('A window asks for attention'),
        'reader.live-region': _('A live region changes'),
        'reader.monitor-changed': _('A watched control changes'),
        'reader.marker-made': _('A marker is made'),
        'reader.marker-reached': _('A marker is reached'),
        'reader.procedure-recording': _('A procedure starts recording'),
        'reader.procedure-kept': _('A procedure is kept'),
        'reader.procedure-done': _('A procedure has run'),
        'reader.trackpad-on': _('The trackpad is turned on'),
        'reader.trackpad-off': _('The trackpad is turned off'),
        'reader.titan-connected': _('Titan is connected'),
        'reader.titan-disconnected': _('Titan is disconnected'),
    }


def is_event(name):
    name = str(name or '')
    return name in FOCUS_DEFAULTS or name in READER_DEFAULTS


def default_sound(name):
    """The built-in sound an event or an icon plays unless told otherwise."""
    name = str(name or '')
    return FOCUS_DEFAULTS.get(name) or READER_DEFAULTS.get(name) or name


def all_events():
    """Every id the manager lists: the focus events, the reader's own
    events, then the actions."""
    return ([event for event, _icon in FOCUS_EVENTS]
            + [event for event, _icon, _titan in READER_EVENTS]
            + list(NAMES))


def label_of(name):
    """What an event is called, in the user's words."""
    name = str(name or '')
    return (focus_labels().get(name) or reader_labels().get(name)
            or meanings().get(name) or name)

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
    from . import switchboard
    return switchboard.read('auditoryIcons', True)


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
    if not row and str(name) in READER_DEFAULTS:
        # A reader event has always sounded like Titan's own set; the
        # built-in icon stands in when Titan is not there.
        return SOURCE_TITAN, ''
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
    """What Titan calls the sound for this icon or event, or ''."""
    name = str(name or '')
    return READER_TITAN.get(name) or TITAN_SOUNDS.get(default_sound(name), '')


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
    return play_file(path_of(default_sound(name)), wait=wait)


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
    for name in all_events():
        source, chosen = source_of(name)
        rows.append({'id': name, 'label': label_of(name),
                     'meaning': words.get(default_sound(name), ''),
                     'on': str(name) not in _load(),
                     'file': path_of(default_sound(name)),
                     'default': default_sound(name),
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
    if source == SOURCE_BUILTIN and not path_of(default_sound(name)):
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
        'button': 'focus.button',
        'check': 'focus.checkbox',
        'choice': 'focus.combobox',
        'list': 'focus.listitem',
        'table': 'focus.tablecell',
        'tree': 'focus.treeitem',
        'text': 'focus.edit',
        'multiline': 'focus.edit',
        'slider': 'focus.slider',
        'gauge': 'focus.progressbar',
        'tabs': 'focus.tab',
        'label': 'focus.text',
    }.get(str(kind or ''), 'focus.other')


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
    name = name.upper().replace(' ', '')
    name = ROLE_ALIASES.get(name, name)
    return ROLE_EVENTS.get(name) or ('focus.other' if name else '')


#: Titan Access spells its roles its own way (`contracts.ROLE_*`); the
#: same table serves both readers through these.
ROLE_ALIASES = {
    'RADIO': 'RADIOBUTTON', 'EDIT': 'EDITABLETEXT', 'IMAGE': 'GRAPHIC',
    'TEXT': 'STATICTEXT', 'GROUP': 'GROUPING', 'TREE': 'TREEVIEW',
    'TREEITEM': 'TREEVIEWITEM', 'SPINNER': 'SPINBUTTON',
    'PASSWORD': 'PASSWORDEDIT', 'CELL': 'TABLECELL', 'GRIDITEM': 'DATAITEM',
    'SPLIT_BUTTON': 'SPLITBUTTON', 'TABCONTROL': 'TAB', 'GRID': 'TABLE',
    'ROW': 'LISTITEM', 'STATUSBAR': 'PANE',
}


def everywhere():
    """Whether icons play for the focus outside the add-on's own windows.

    Off by default, because it changes how every control on the machine
    sounds; asked of whichever reader is underneath (`switchboard`).
    """
    from . import switchboard
    return switchboard.read('auditoryIconsEverywhere', False)

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

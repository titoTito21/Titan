# -*- coding: utf-8 -*-
"""The reader's own settings as a walked list (Insert+Ctrl+G).

The NVDA add-on walks TITAN's settings category first, then the controls,
with Enter doing the one obvious thing to each kind (`portable/titanWalk`).
This is the same shape over THIS reader's own store: the sections of the
Titan Access settings page - Speech, General, Verbosity, Navigation, Dial,
Reader, Sounds and switches, Braille, Text editing - and every switch in
each, read as "label: value" and changed in place. A tick box flips, a
choice opens its answers as a level with the one in force marked, a
number opens its values, a text asks for one.

**It needs no window.** The settings page in Titan's settings window
(`settings_panel.py`) is a wx page; a user whose reader is the only thing
telling them what is on the screen should not have to find it. This reads
and writes `settings_store` directly - the same INI the page writes - and
tells the running engine to apply what changed, so the two never disagree.

The schema below is written out of `settings_panel.py`'s builders, key for
key, and `tests/test_titan_access_reading.py` checks that every key the
page reads is here and nothing here is unknown to the page.
"""

import threading

from titan_access.localization import L
from titan_access.settings_store import (
    get_settings, AnnouncementMode, ScreenReaderModifier, KeyboardEchoSetting,
)

_LOCK = threading.RLock()
_counted = {'opened': 0, 'sections': 0, 'changed': 0}
#: The section being walked and its rows, so a level can be put back.
_open = {'section': '', 'rows': [], 'at': 0}


# --------------------------------------------------------------------------- #
# The schema: (ini section, key, label key, kind, extra, default)
# --------------------------------------------------------------------------- #
def _announce():
    return [(value, "settings.announce." + name) for value, name in zip(
        AnnouncementMode.ALL, ("none", "sound", "speech", "speechAndSound"))]


def _modifiers():
    return [(value, "settings.modifier." + name) for value, name in zip(
        ScreenReaderModifier.ALL, ("insert", "capsLock", "insertAndCapsLock"))]


def _echoes():
    return [(value, "settings.echo." + name) for value, name in zip(
        KeyboardEchoSetting.ALL, ("none", "characters", "words",
                                  "charactersAndWords"))]


#: Kinds: bool, choice (extra = callable answering [(value, label key)]),
#: range (extra = (minimum, maximum, step)), text, engines, voices, scheme,
#: braille_table.
SCHEMA = (
    ('speech', 'settings.section.speech', (
        ('__scheme__', '', 'settings.speech.scheme', 'scheme', None, ''),
        ('Speech', 'OwnVoice', 'settings.speech.ownVoice', 'bool', None, False),
        ('Speech', 'Synthesizer', 'settings.speech.engine', 'engines', None, ''),
        ('Speech', 'Voice', 'settings.speech.voice', 'voices', None, ''),
        ('Speech', 'Rate', 'settings.speech.rate', 'range', (-10, 10, 1), 0),
        ('Speech', 'Pitch', 'settings.speech.pitch', 'range', (-10, 10, 1), 0),
        ('Speech', 'Volume', 'settings.speech.volume', 'range', (0, 100, 5), 100),
    )),
    ('general', 'settings.section.general', (
        ('General', 'MuteOutsideTCE', 'settings.general.muteOutsideTce', 'bool', None, False),
        ('General', 'StartupAnnouncement', 'settings.general.startupAnnouncement', 'choice', _announce, AnnouncementMode.SPEECH_AND_SOUND),
        ('General', 'TCEEntrySound', 'settings.general.tceEntrySound', 'bool', None, True),
        ('General', 'Modifier', 'settings.general.modifier', 'choice', _modifiers, ScreenReaderModifier.INSERT_AND_CAPSLOCK),
        ('General', 'WelcomeMessage', 'settings.general.welcomeMessage', 'text', None, ''),
        ('General', 'SpeakHints', 'settings.general.speakHints', 'bool', None, True),
        ('General', 'VirtualScreen', 'settings.general.virtualScreen', 'bool', None, False),
    )),
    ('verbosity', 'settings.section.verbosity', (
        ('Verbosity', 'AnnounceBasicControls', 'settings.verbosity.announceBasicControls', 'bool', None, True),
        ('Verbosity', 'AnnounceBlockControls', 'settings.verbosity.announceBlockControls', 'bool', None, True),
        ('Verbosity', 'AnnounceListPosition', 'settings.verbosity.announceListPosition', 'bool', None, True),
        ('Verbosity', 'MenuItemCount', 'settings.verbosity.menuItemCount', 'bool', None, True),
        ('Verbosity', 'MenuName', 'settings.verbosity.menuName', 'bool', None, True),
        ('Verbosity', 'MenuSounds', 'settings.verbosity.menuSounds', 'bool', None, True),
        ('Verbosity', 'ElementName', 'settings.verbosity.elementName', 'bool', None, True),
        ('Verbosity', 'ElementType', 'settings.verbosity.elementType', 'bool', None, True),
        ('Verbosity', 'ElementState', 'settings.verbosity.elementState', 'bool', None, True),
        ('Verbosity', 'ElementParameter', 'settings.verbosity.elementParameter', 'bool', None, True),
        ('Verbosity', 'ToggleKeysMode', 'settings.verbosity.toggleKeysMode', 'choice', _announce, AnnouncementMode.SPEECH_AND_SOUND),
    )),
    ('navigation', 'settings.section.navigation', (
        ('Navigation', 'AdvancedNavigation', 'settings.navigation.advancedNavigation', 'bool', None, False),
        ('Navigation', 'AnnounceControlTypesNavigation', 'settings.navigation.announceControlTypes', 'bool', None, True),
        ('Navigation', 'AnnounceHierarchyLevel', 'settings.navigation.announceHierarchyLevel', 'bool', None, True),
        ('Navigation', 'WindowBoundsMode', 'settings.navigation.windowBoundsMode', 'choice', _announce, AnnouncementMode.SPEECH_AND_SOUND),
        ('Navigation', 'PhoneticInDial', 'settings.navigation.phoneticInDial', 'bool', None, True),
    )),
    ('dial', 'settings.section.dial', (
        ('Dial', 'DialCharacters', 'settings.dial.characters', 'bool', None, True),
        ('Dial', 'DialWords', 'settings.dial.words', 'bool', None, True),
        ('Dial', 'DialButtons', 'settings.dial.buttons', 'bool', None, True),
        ('Dial', 'DialHeadings', 'settings.dial.headings', 'bool', None, True),
        ('Dial', 'DialVolume', 'settings.dial.volume', 'bool', None, True),
        ('Dial', 'DialSpeed', 'settings.dial.speed', 'bool', None, True),
        ('Dial', 'DialVoice', 'settings.dial.voice', 'bool', None, True),
        ('Dial', 'DialSynthesizer', 'settings.dial.synthesizer', 'bool', None, True),
        ('Dial', 'DialImportantPlaces', 'settings.dial.importantPlaces', 'bool', None, True),
    )),
    ('reader', 'settings.section.reader', (
        ('Reader', 'ScanMode', 'settings.reader.scanMode', 'bool', None, True),
        ('Reader', 'UseAiOcr', 'settings.reader.useAiOcr', 'bool', None, True),
        ('Reader', 'AiOcrLabels', 'settings.reader.aiOcrLabels', 'bool', None, True),
        ('Reader', 'ProgressMode', 'settings.reader.progressMode', 'choice', _announce, AnnouncementMode.SPEECH_AND_SOUND),
    )),
    ('sounds', 'settings.section.sounds', tuple(
        ('Reader', key, 'settings.reader.' + key, 'bool', None, default)
        for key, default in (
            ("auditoryIcons", True), ("auditoryIconsEverywhere", False),
            ("soundScheme", True), ("dialogKinds", True), ("busyState", True),
            ("attentionState", True), ("liveStatusBars", True),
            ("monitors", True), ("surfaceReading", False),
            ("guestCursor", False), ("agentLink", False),
            ("windowsSemantics", True),
        ))),
    ('braille', 'settings.section.braille', (
        ('Braille', 'Enabled', 'settings.braille.enabled', 'bool', None, False),
        ('Braille', 'Table', 'settings.braille.table', 'braille_table', None, ''),
        ('Braille', 'Viewer', 'settings.braille.viewer', 'bool', None, True),
    )),
    ('textEditing', 'settings.section.textEditing', (
        ('TextEditing', 'PhoneticLetters', 'settings.textEditing.phoneticLetters', 'bool', None, True),
        ('TextEditing', 'KeyboardEcho', 'settings.textEditing.keyboardEcho', 'choice', _echoes, KeyboardEchoSetting.CHARACTERS_AND_WORDS),
        ('TextEditing', 'AnnounceTextBounds', 'settings.textEditing.announceTextBounds', 'bool', None, True),
    )),
)


def report():
    with _LOCK:
        return dict(_counted)


def forget():
    with _LOCK:
        _counted.update({'opened': 0, 'sections': 0, 'changed': 0})
        _open.update({'section': '', 'rows': [], 'at': 0})


# --------------------------------------------------------------------------- #
# Reading and writing one setting
# --------------------------------------------------------------------------- #
def _store():
    return get_settings()


def _options(entry, engine=None):
    """``[(value, label)]`` for a choice-like entry."""
    _section, _key, _label, kind, extra, _default = entry
    if kind == 'choice' and callable(extra):
        return [(value, L(key)) for value, key in extra()]
    if kind == 'range':
        low, high, step = extra
        return [(value, str(value)) for value in range(low, high + 1, step)]
    if kind == 'scheme':
        try:
            from .portable import speechSchemes
            return [(key, label) for key, label in speechSchemes.names()]
        except Exception:                            # noqa: BLE001
            return []
    if kind == 'engines':
        try:
            from . import settings_panel
            return [(str(one), str(one)) for one in settings_panel._engine_ids()]
        except Exception:                            # noqa: BLE001
            return []
    if kind == 'voices':
        pairs = []
        try:
            speech = getattr(engine, 'speech', None)
            voices = speech.get_voices() if speech is not None else []
        except Exception:                            # noqa: BLE001
            voices = []
        for one in voices or []:
            if isinstance(one, dict):
                shown = one.get("display_name") or one.get("name") \
                    or one.get("id") or str(one)
                pairs.append((str(one.get("id") or one.get("name") or shown),
                              str(shown)))
            else:
                pairs.append((str(one), str(one)))
        return pairs
    if kind == 'braille_table':
        rows = [('', L('settings.braille.autoTable'))]
        try:
            from . import braille
            rows.extend((name, label) for name, label in braille.tables_available())
        except Exception:                            # noqa: BLE001
            pass
        return rows
    return []


def value_of(entry, store=None):
    """What the setting holds now, as the store keeps it."""
    store = store or _store()
    section, key, _label, kind, _extra, default = entry
    if kind == 'scheme':
        try:
            from .portable import speechSchemes
            return speechSchemes.active()
        except Exception:                            # noqa: BLE001
            return ''
    if kind == 'bool':
        return store.get_bool(section, key, bool(default))
    if kind == 'range':
        return store.get_int(section, key, int(default))
    return str(store.get(section, key, default) or '')


def value_word(entry, value, engine=None):
    """The value as words: on/off, the option's label, the number."""
    kind = entry[3]
    if kind == 'bool':
        return L('walk.on') if value else L('walk.off')
    if kind in ('choice', 'scheme', 'engines', 'voices', 'braille_table'):
        for known, label in _options(entry, engine):
            if str(known) == str(value):
                return label
        return str(value or '') or L('walk.notSet')
    return str(value or '') or L('walk.notSet')


def set_value(entry, value, engine=None):
    """Write one setting and apply it to the running reader."""
    store = _store()
    section, key, _label, kind, _extra, _default = entry
    if kind == 'scheme':
        from .portable import speechSchemes
        speechSchemes.use(str(value))
    elif kind == 'bool':
        store.set_bool(section, key, bool(value))
    elif kind == 'range':
        store.set_int(section, key, int(value))
    else:
        store.set(section, key, str(value))
    if kind != 'scheme':
        store.save()
    with _LOCK:
        _counted['changed'] += 1
    _apply(engine, section)


def _apply(engine, section):
    """Tell the running reader. Speech settings reach its own voice."""
    if engine is None:
        return
    try:
        engine.settings = _store()
    except Exception:                                # noqa: BLE001
        pass
    speech = getattr(engine, 'speech', None)
    if speech is not None and hasattr(speech, 'apply_settings'):
        try:
            speech.apply_settings()
        except Exception as error:                   # noqa: BLE001
            print('[TitanAccess] settings walk: apply: %s' % error)


# --------------------------------------------------------------------------- #
# The walk
# --------------------------------------------------------------------------- #
def _kind_word(kind):
    return L({
        'bool': 'walk.kind.checkBox', 'choice': 'walk.kind.choice',
        'range': 'walk.kind.number', 'text': 'walk.kind.field',
    }.get(kind, 'walk.kind.choice'))


def _row_label(entry, engine=None):
    label = L(entry[2]).strip().rstrip(':').strip()
    return '%s: %s' % (label, value_word(entry, value_of(entry), engine))


def open_it(engine=None):
    """The sections, as a list. ``(ok, said)``."""
    from .portable import palette
    rows = []
    for sid, title, _entries in SCHEMA:
        rows.append({'label': L(title), 'role': L('walk.kind.category'),
                     'icon': 'open-object',
                     'run': (lambda which=sid: open_section(engine, which))})
    with _LOCK:
        _counted['opened'] += 1
    return palette.show(rows, L('walk.title'))


def open_section(engine, sid, at=0):
    """One section: its settings as rows. ``(ok, said)``."""
    from .portable import palette
    for known, title, entries in SCHEMA:
        if known != sid:
            continue
        rows = []
        for entry in entries:
            row = {'label': _row_label(entry, engine),
                   'role': _kind_word(entry[3]), 'icon': 'form-field'}
            row['run'] = (lambda one=entry, where=row:
                          _change(engine, sid, one, where))
            rows.append(row)
        with _LOCK:
            _counted['sections'] += 1
            _open.update({'section': sid, 'rows': rows, 'at': at})
        return palette.show(rows, L(title), back=lambda: open_it(engine),
                            at=at)
    return False, ''


def _index_of(sid, row):
    with _LOCK:
        rows = _open.get('rows') or []
    for index, one in enumerate(rows):
        if one is row:
            return index
    return 0


def _change(engine, sid, entry, row):
    """Enter on a setting: the one obvious thing for its kind."""
    from .portable import palette
    kind = entry[3]
    if kind == 'bool':
        wanted = not value_of(entry)
        set_value(entry, wanted, engine)
        row['label'] = _row_label(entry, engine)
        # Said in place: the level is not put up again, because that
        # would read the title on top of the answer.
        return True, row['label']
    if kind in ('choice', 'range', 'scheme', 'engines', 'voices',
                'braille_table'):
        options = _options(entry, engine)
        if not options:
            return False, L('walk.nothingToChoose')
        now = str(value_of(entry))
        at = 0
        made = []
        for index, (value, label) in enumerate(options):
            current = str(value) == now
            if current:
                at = index
            made.append({
                'label': ('%s, %s' % (label, L('walk.now'))) if current
                else label,
                'role': L('walk.kind.option'), 'icon': 'form-field',
                'run': (lambda picked=value: _picked(engine, sid, entry,
                                                     row, picked))})
        where = _index_of(sid, row)
        return palette.show(made, L(entry[2]),
                            back=lambda: open_section(engine, sid, at=where),
                            at=at)
    if kind == 'text':
        return _ask(engine, sid, entry, row)
    return False, L('walk.setInWindow').format(what=L(entry[2]))


def _picked(engine, sid, entry, row, value):
    set_value(entry, value, engine)
    row['label'] = _row_label(entry, engine)
    # Back to the section, on the setting that was just answered: the row
    # is re-read holding the new value, so it IS the confirmation.
    return open_section(engine, sid, at=_index_of(sid, row))


def _ask(engine, sid, entry, row):
    from .portable import dialogs, palette
    where = _index_of(sid, row)

    def answered(text):
        set_value(entry, str(text), engine)
        row['label'] = _row_label(entry, engine)
        open_section(engine, sid, at=where)

    if dialogs._gui() is None or dialogs._wx() is None:
        return False, L('walk.setInWindow').format(what=L(entry[2]))
    # The palette borrows the arrow keys; a text box opened over it
    # would have its own taken away.
    palette.stop()
    dialogs.ask_text(L(entry[2]), L('walk.title'), on_answer=answered,
                     default=str(value_of(entry) or ''),
                     on_cancel=lambda: open_section(engine, sid, at=where))
    return True, ''

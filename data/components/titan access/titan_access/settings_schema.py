# -*- coding: utf-8 -*-
"""Every setting of the reader, described once.

The settings page in Titan's settings window (`settings_panel`), the
walked settings (`settings_walk`, Insert+Ctrl+G), the store's defaults
(`settings_store.DEFAULTS`), the per-program profiles (`profiles`) and
the settings ring (`settings_ring`) are all built out of THIS table. A
setting added here appears everywhere; one added anywhere else appears
nowhere, which is what used to happen - the page and the walk were two
hand-written copies, and a test could only check that their keys met.

An entry: ``Entry(section, key, kind, label, help, default, extra)``
    section  the INI section the value is kept in
    key      the INI key
    kind     'bool' | 'choice' | 'range' | 'text' | 'scheme' | 'engines'
             | 'voices' | 'braille_table'
    label    the locale key of the control's label
    help     the locale key of one sentence saying what it does
    default  the default, as Python (bool / int / str)
    extra    choice: ``[(value, label key)]``; range: ``(low, high, step)``

The UI SECTION an entry is shown under is where the user looks for it,
and is independent of the INI section it is stored in: the keyboard echo
has always lived under ``TextEditing`` and is shown under Keyboard.

**A setting nothing reads does not exist.** `tests/test_titan_access_
settings.py` greps the engine for every key here, so a switch that
changes nothing cannot be added by accident.
"""

import collections

from titan_access.settings_store import (
    DEFAULTS, AnnouncementMode, ScreenReaderModifier, KeyboardEchoSetting,
)

Entry = collections.namedtuple('Entry', 'section key kind label help default extra')

#: Sections for the symbols, the keyboard, the mouse and browse mode.
SEC_SYMBOLS = 'Symbols'
SEC_KEYBOARD = 'Keyboard'
SEC_MOUSE = 'Mouse'
SEC_BROWSE = 'Browse'

#: The vocabulary of the new choices, by INI value.
PUNCTUATION_LEVELS = ('none', 'some', 'most', 'all')
CAPITAL_MODES = ('none', 'word', 'beep', 'pitch')
NUMBER_MODES = ('whole', 'digits', 'pairs')
PASSWORD_ECHO = ('none', 'star')
UNDER_MOUSE = ('object', 'char', 'word', 'line')
WALK_LAYOUTS = ('linear', 'screen', 'interact')


def _announce():
    return [(value, 'settings.announce.' + name) for value, name in zip(
        AnnouncementMode.ALL, ('none', 'sound', 'speech', 'speechAndSound'))]


def _modifiers():
    return [(value, 'settings.modifier.' + name) for value, name in zip(
        ScreenReaderModifier.ALL, ('insert', 'capsLock', 'insertAndCapsLock'))]


def _echoes():
    return [(value, 'settings.echo.' + name) for value, name in zip(
        KeyboardEchoSetting.ALL, ('none', 'characters', 'words',
                                  'charactersAndWords'))]


def _named(prefix, values):
    return [(value, '%s.%s' % (prefix, value)) for value in values]


def _h(section, key):
    return 'settings.help.%s.%s' % (section, key)


def _e(section, key, kind, label, default, extra=None):
    return Entry(section, key, kind, label, _h(section, key), default, extra)


#: (ui section id, title locale key, entries)
SECTIONS = (
    ('speech', 'settings.section.speech', (
        Entry('__scheme__', '', 'scheme', 'settings.speech.scheme',
              _h('Speech', 'scheme'), '', None),
        _e('Speech', 'OwnVoice', 'bool', 'settings.speech.ownVoice', False),
        _e('Speech', 'Synthesizer', 'engines', 'settings.speech.engine', 'SAPI5'),
        _e('Speech', 'Voice', 'voices', 'settings.speech.voice', ''),
        _e('Speech', 'Rate', 'range', 'settings.speech.rate', 0, (-10, 10, 1)),
        _e('Speech', 'Pitch', 'range', 'settings.speech.pitch', 0, (-10, 10, 1)),
        _e('Speech', 'Volume', 'range', 'settings.speech.volume', 100, (0, 100, 5)),
    )),
    ('general', 'settings.section.general', (
        _e('General', 'Enabled', 'bool', 'settings.general.enable', False),
        _e('General', 'MuteOutsideTCE', 'bool', 'settings.general.muteOutsideTce', False),
        _e('General', 'StartupAnnouncement', 'choice',
           'settings.general.startupAnnouncement',
           AnnouncementMode.SPEECH_AND_SOUND, _announce),
        _e('General', 'TCEEntrySound', 'bool', 'settings.general.tceEntrySound', True),
        _e('General', 'Modifier', 'choice', 'settings.general.modifier',
           ScreenReaderModifier.INSERT_AND_CAPSLOCK, _modifiers),
        _e('General', 'WelcomeMessage', 'text', 'settings.general.welcomeMessage',
           'Czytnik ekranu uruchomiony'),
        _e('General', 'SpeakHints', 'bool', 'settings.general.speakHints', True),
        _e('General', 'VirtualScreen', 'bool', 'settings.general.virtualScreen', False),
    )),
    ('keyboard', 'settings.section.keyboard', (
        _e('TextEditing', 'KeyboardEcho', 'choice', 'settings.textEditing.keyboardEcho',
           KeyboardEchoSetting.CHARACTERS_AND_WORDS, _echoes),
        _e('TextEditing', 'PhoneticLetters', 'bool',
           'settings.textEditing.phoneticLetters', True),
        _e(SEC_KEYBOARD, 'TypingInterruptsSpeech', 'bool',
           'settings.keyboard.typingInterruptsSpeech', True),
        _e(SEC_KEYBOARD, 'SpeakCommandKeys', 'bool',
           'settings.keyboard.speakCommandKeys', False),
        _e(SEC_KEYBOARD, 'SpeakModifierKeys', 'bool',
           'settings.keyboard.speakModifierKeys', False),
        _e(SEC_KEYBOARD, 'PasswordEcho', 'choice', 'settings.keyboard.passwordEcho',
           'star', lambda: _named('settings.passwordEcho', PASSWORD_ECHO)),
        _e(SEC_KEYBOARD, 'CapsLockWarning', 'bool',
           'settings.keyboard.capsLockWarning', True),
    )),
    ('symbols', 'settings.section.symbols', (
        _e(SEC_SYMBOLS, 'PunctuationLevel', 'choice', 'settings.symbols.punctuationLevel',
           'some', lambda: _named('settings.punctuation', PUNCTUATION_LEVELS)),
        _e(SEC_SYMBOLS, 'CapitalLetters', 'choice', 'settings.symbols.capitalLetters',
           'pitch', lambda: _named('settings.capitals', CAPITAL_MODES)),
        _e(SEC_SYMBOLS, 'CapitalPitchOffset', 'range',
           'settings.symbols.capitalPitchOffset', 3, (1, 10, 1)),
        _e(SEC_SYMBOLS, 'NumbersAs', 'choice', 'settings.symbols.numbersAs',
           'whole', lambda: _named('settings.numbers', NUMBER_MODES)),
        _e(SEC_SYMBOLS, 'TrimLeadingWhitespace', 'bool',
           'settings.symbols.trimLeadingWhitespace', True),
    )),
    ('verbosity', 'settings.section.verbosity', (
        _e('Verbosity', 'AnnounceBasicControls', 'bool',
           'settings.verbosity.announceBasicControls', True),
        _e('Verbosity', 'AnnounceBlockControls', 'bool',
           'settings.verbosity.announceBlockControls', True),
        _e('Verbosity', 'AnnounceListPosition', 'bool',
           'settings.verbosity.announceListPosition', True),
        _e('Verbosity', 'MenuItemCount', 'bool', 'settings.verbosity.menuItemCount', True),
        _e('Verbosity', 'MenuName', 'bool', 'settings.verbosity.menuName', True),
        _e('Verbosity', 'MenuSounds', 'bool', 'settings.verbosity.menuSounds', True),
        _e('Verbosity', 'ElementName', 'bool', 'settings.verbosity.elementName', True),
        _e('Verbosity', 'ElementType', 'bool', 'settings.verbosity.elementType', True),
        _e('Verbosity', 'ElementState', 'bool', 'settings.verbosity.elementState', True),
        _e('Verbosity', 'ElementParameter', 'bool',
           'settings.verbosity.elementParameter', True),
        _e('Verbosity', 'ToggleKeysMode', 'choice', 'settings.verbosity.toggleKeysMode',
           AnnouncementMode.SPEECH_AND_SOUND, _announce),
    )),
    ('navigation', 'settings.section.navigation', (
        _e('Navigation', 'AnnounceControlTypesNavigation', 'bool',
           'settings.navigation.announceControlTypes', True),
        _e('Navigation', 'AnnounceHierarchyLevel', 'bool',
           'settings.navigation.announceHierarchyLevel', True),
        _e('Navigation', 'WindowBoundsMode', 'choice',
           'settings.navigation.windowBoundsMode',
           AnnouncementMode.SPEECH_AND_SOUND, _announce),
        _e('Navigation', 'PhoneticInDial', 'bool', 'settings.navigation.phoneticInDial', True),
        _e('Navigation', 'SimpleReviewMode', 'bool',
           'settings.navigation.simpleReview', True),
    )),
    ('browse', 'settings.section.browse', (
        _e(SEC_BROWSE, 'AutoFocusMode', 'bool', 'settings.browse.autoFocusMode', True),
        _e(SEC_BROWSE, 'FocusModeOnCaretMove', 'bool',
           'settings.browse.focusModeOnCaretMove', False),
        _e(SEC_BROWSE, 'QuickNavKeys', 'bool', 'settings.browse.quickNavKeys', True),
        _e(SEC_BROWSE, 'SayAllOnPageLoad', 'bool', 'settings.browse.sayAllOnPageLoad', False),
        _e(SEC_BROWSE, 'SayAllRate', 'range', 'settings.browse.sayAllRate', 0, (-10, 10, 1)),
        _e(SEC_BROWSE, 'ReportLinks', 'bool', 'settings.browse.reportLinks', True),
        _e(SEC_BROWSE, 'ReportHeadings', 'bool', 'settings.browse.reportHeadings', True),
        _e(SEC_BROWSE, 'ReportLists', 'bool', 'settings.browse.reportLists', True),
        _e(SEC_BROWSE, 'ReportTables', 'bool', 'settings.browse.reportTables', True),
        _e(SEC_BROWSE, 'ReportLandmarks', 'bool', 'settings.browse.reportLandmarks', True),
        _e(SEC_BROWSE, 'LayoutTables', 'bool', 'settings.browse.layoutTables', False),
    )),
    ('dial', 'settings.section.dial', tuple(
        _e('Dial', key, 'bool', 'settings.dial.' + label, True)
        for key, label in (
            ('DialCharacters', 'characters'), ('DialWords', 'words'),
            ('DialButtons', 'buttons'), ('DialHeadings', 'headings'),
            ('DialVolume', 'volume'), ('DialSpeed', 'speed'),
            ('DialVoice', 'voice'), ('DialSynthesizer', 'synthesizer'),
            ('DialImportantPlaces', 'importantPlaces')))),
    ('mouse', 'settings.section.mouse', (
        _e(SEC_MOUSE, 'TrackMouse', 'bool', 'settings.mouse.trackMouse', False),
        _e(SEC_MOUSE, 'SpeakUnderMouse', 'choice', 'settings.mouse.speakUnderMouse',
           'object', lambda: _named('settings.underMouse', UNDER_MOUSE)),
        _e(SEC_MOUSE, 'AudioCoordinates', 'bool', 'settings.mouse.audioCoordinates', False),
        _e(SEC_MOUSE, 'AudioCoordinatesByBrightness', 'bool',
           'settings.mouse.audioCoordinatesByBrightness', False),
        _e(SEC_MOUSE, 'MouseDelayMs', 'range', 'settings.mouse.mouseDelayMs', 100,
           (0, 500, 50)),
        _e(SEC_MOUSE, 'IgnoreMouseInsideTitan', 'bool',
           'settings.mouse.ignoreMouseInsideTitan', True),
    )),
    ('reader', 'settings.section.reader', (
        _e('Reader', 'ScanMode', 'bool', 'settings.reader.scanMode', True),
        _e('Reader', 'UseAiOcr', 'bool', 'settings.reader.useAiOcr', True),
        _e('Reader', 'AiOcrLabels', 'bool', 'settings.reader.aiOcrLabels', True),
        _e('Reader', 'ProgressMode', 'choice', 'settings.reader.progressMode',
           AnnouncementMode.SPEECH_AND_SOUND, _announce),
        _e('Reader', 'ProgressBeepInterval', 'range',
           'settings.reader.progressBeepInterval', 1, (1, 25, 1)),
        _e('Reader', 'ProgressSpeechInterval', 'range',
           'settings.reader.progressSpeechInterval', 10, (1, 50, 1)),
    )),
    ('sounds', 'settings.section.sounds', tuple(
        _e('Reader', key, 'bool', 'settings.reader.' + key, default)
        for key, default in (
            ('auditoryIcons', True), ('auditoryIconsEverywhere', False),
            ('soundScheme', True), ('dialogKinds', True), ('busyState', True),
            ('attentionState', True), ('liveStatusBars', True),
            ('monitors', True), ('surfaceReading', False),
            ('guestCursor', False), ('agentLink', False),
            ('windowsSemantics', True), ('speakShortcuts', True),
            ('uiaNotifications', True)))),
    ('walk', 'settings.section.walk', (
        # The walked lists - the palette, a message, the virtual window, the
        # managers, these settings themselves. Read by the shared modules
        # through the switchboard (`portable/palette.py`, `virtualWindow.py`).
        _e('Reader', 'walkLayout', 'choice', 'settings.walk.layout', 'linear',
           lambda: _named('settings.walkLayout', WALK_LAYOUTS)),
        _e('Reader', 'walkSayKind', 'bool', 'settings.walk.sayKind', True),
        _e('Reader', 'walkSayPosition', 'bool', 'settings.walk.sayPosition', True),
        _e('Reader', 'walkSayTitle', 'bool', 'settings.walk.sayTitle', True),
        _e('Reader', 'walkRowBeep', 'bool', 'settings.walk.rowBeep', True),
        _e('Reader', 'walkWrap', 'bool', 'settings.walk.wrap', False),
        _e('Reader', 'walkHostWindow', 'bool', 'settings.walk.hostWindow', True),
    )),
    ('braille', 'settings.section.braille', (
        _e('Braille', 'Enabled', 'bool', 'settings.braille.enabled', False),
        _e('Braille', 'Table', 'braille_table', 'settings.braille.table', ''),
        _e('Braille', 'Viewer', 'bool', 'settings.braille.viewer', True),
    )),
    ('textEditing', 'settings.section.textEditing', (
        _e('TextEditing', 'AnnounceTextBounds', 'bool',
           'settings.textEditing.announceTextBounds', True),
    )),
)

#: `Navigation/AdvancedNavigation` came over from the C# reader and is read
#: by nothing in this one, so it is NOT described: a switch that changes
#: nothing is worse than no switch. The store keeps its default for an
#: INI the C# reader wrote.
#: The sections a profile may override. The switch that turns the reader
#: on is global by nature; everything else may differ per program.
NEVER_IN_A_PROFILE = {('General', 'Enabled')}

#: What the settings ring (Insert+Ctrl+arrows) steps through, in order.
RING = (
    ('Speech', 'Rate'), ('Speech', 'Pitch'), ('Speech', 'Volume'),
    ('Speech', 'Voice'), ('Speech', 'Synthesizer'), ('__scheme__', ''),
    (SEC_SYMBOLS, 'PunctuationLevel'), ('TextEditing', 'KeyboardEcho'),
    (SEC_MOUSE, 'TrackMouse'),
)


def entries():
    """Every entry, in section order."""
    for _sid, _title, rows in SECTIONS:
        for entry in rows:
            yield entry


def find(section, key):
    for entry in entries():
        if entry.section == section and entry.key == key:
            return entry
    return None


def section_of(entry):
    """The ui section id an entry is shown under."""
    for sid, _title, rows in SECTIONS:
        if entry in rows:
            return sid
    return ''


def encode(entry, value):
    """A value as the INI keeps it."""
    if entry.kind == 'bool':
        return 'true' if value else 'false'
    if entry.kind == 'range':
        return str(int(value))
    return str(value if value is not None else '')


def options(entry):
    """``[(value, label key)]`` of a choice, or ``[]``."""
    extra = entry.extra
    if entry.kind == 'choice':
        return list(extra() if callable(extra) else (extra or []))
    if entry.kind == 'range':
        low, high, step = extra
        return [(value, str(value)) for value in range(low, high + 1, step)]
    return []


def as_walk_schema():
    """The shape `settings_walk.SCHEMA` has always had:
    ``(sid, title key, ((section, key, label key, kind, extra, default), ...))``."""
    return tuple(
        (sid, title, tuple((e.section, e.key, e.label, e.kind, e.extra, e.default)
                           for e in rows))
        for sid, title, rows in SECTIONS)


def register_defaults(defaults=DEFAULTS):
    """Put every entry's default into the store's table, where it is not
    already written down (the hand-written defaults keep their spelling)."""
    for entry in entries():
        if entry.kind == 'scheme' or not entry.key:
            continue
        defaults.setdefault((entry.section, entry.key), encode(entry, entry.default))


register_defaults()

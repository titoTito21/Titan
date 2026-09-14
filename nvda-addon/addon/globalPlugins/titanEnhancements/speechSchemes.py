# -*- coding: utf-8 -*-
"""Speech schemes: how each KIND of control is announced, named and shown.

JAWS calls them speech and sounds schemes, and they are the one thing a
reader with voice classes was still missing. The class manager says what
a NAME sounds like and what a STATE sounds like; the reading order says
which parts of a control are read and in what order - for every control
alike. A scheme says it PER KIND: a button is its name and nothing else,
because the voice already says "button"; an edit field is its name, its
type and what is in it; a list item is its name, its state and where it is;
a link plays a sound instead of the word "link"; a heading is said in the
context voice; and in braille a button is "btn" and a check box shows its
state and no type at all.

A scheme is a named table of such rules - one per kind, and a default for
every kind that has none - and several can be kept and switched between
with a key: a terse one for the program you know by heart, a verbose one
for the program you are learning, one made of sounds for when the room is
quiet. Four ship; anything the user makes is a copy of one, changed.

**Every reader that shares this module applies it in the same place**: the
NVDA add-on in `elements.describe`, Titan Access in `accessible.describe`.
The braille half is applied where a reader has braille - NVDA's own
`braille.getPropertiesBraille` and its role labels, wrapped and put back;
Titan Access has no braille display yet, and the braille rules are kept
for the day it does rather than invented on the spot.

Nothing here runs on the focus path except a dictionary lookup: the file
is read once and kept, and `rule_for` is two merges of small dicts.
"""

import json
import os
import threading

from . import i18n

_ = i18n.install(globals())

FILENAME = 'titanSpeechSchemes.json'

#: The parts a control's reading is made of - `classes.PARTS`, the same
#: words the reading order page uses, so the two managers agree.
PARTS = ('name', 'kind', 'state', 'value', 'description', 'place', 'hint')

#: The voice class each part is said in unless a rule says otherwise. `hint`
#: is the instructions a control carries ("to activate press space") - what
#: JAWS says at Beginner and Dolphin SuperNova at High, and the part that
#: makes a "very detailed" scheme genuinely more detailed. Last, and off in
#: every scheme but the detailed ones.
PART_VOICE = {'name': 'name', 'kind': 'kind', 'state': 'state',
              'value': 'value', 'description': 'description',
              'place': 'place', 'hint': 'detail'}

#: Every kind of control a rule can be about, with the NVDA role names
#: (`controlTypes.Role.<NAME>`) and Titan Access's own role keys that fall
#: into it. The ORDER is the order the managers list them in - the ones
#: somebody is likely to want to change first.
KINDS = (
    ('button', ('BUTTON', 'TOGGLEBUTTON', 'SPLITBUTTON', 'MENUBUTTON',
                'DROPDOWNBUTTON', 'SPINBUTTON'),
     ('button', 'togglebutton', 'splitbutton')),
    ('checkbox', ('CHECKBOX', 'CHECKMENUITEM', 'SWITCH'),
     ('checkbox', 'switch')),
    ('radio', ('RADIOBUTTON', 'RADIOMENUITEM'), ('radio', 'radiobutton')),
    ('edit', ('EDITABLETEXT', 'PASSWORDEDIT', 'RICHEDIT', 'TERMINAL'),
     ('edit', 'password', 'terminal')),
    ('combobox', ('COMBOBOX',), ('combobox',)),
    ('list', ('LIST',), ('list',)),
    ('listitem', ('LISTITEM',), ('listitem',)),
    ('tree', ('TREEVIEW',), ('tree',)),
    ('treeitem', ('TREEVIEWITEM',), ('treeitem',)),
    ('tab', ('TAB', 'TABCONTROL'), ('tab', 'tabcontrol')),
    ('menu', ('MENUBAR', 'POPUPMENU', 'MENU'), ('menu', 'menubar')),
    ('menuitem', ('MENUITEM',), ('menuitem',)),
    ('link', ('LINK',), ('link',)),
    ('heading', ('HEADING', 'HEADING1', 'HEADING2', 'HEADING3', 'HEADING4',
                 'HEADING5', 'HEADING6'), ('heading',)),
    ('slider', ('SLIDER', 'SCROLLBAR', 'SPINBUTTON'),
     ('slider', 'spinner', 'scrollbar')),
    ('progress', ('PROGRESSBAR', 'BUSY_INDICATOR'), ('progressbar',)),
    ('table', ('TABLE', 'TABLECELL', 'TABLEROW', 'TABLECOLUMNHEADER',
               'TABLEROWHEADER', 'TABLECOLUMN', 'DATAGRID', 'DATAITEM'),
     ('table', 'cell', 'row', 'header', 'grid', 'dataitem')),
    ('graphic', ('GRAPHIC', 'ICON', 'ANIMATION', 'DIAGRAM', 'CHART'),
     ('image', 'graphic', 'icon')),
    ('text', ('STATICTEXT', 'LABEL', 'TEXTFRAME', 'PARAGRAPH', 'DOCUMENT'),
     ('text', 'statictext', 'document')),
    ('window', ('WINDOW', 'DIALOG', 'APPLICATION', 'PANE', 'FRAME',
                'PROPERTYPAGE', 'GROUPING', 'GROUPBOX'),
     ('window', 'dialog', 'pane', 'group', 'application')),
    ('toolbar', ('TOOLBAR', 'STATUSBAR'), ('toolbar', 'statusbar')),
    ('other', (), ()),
)

KIND_KEYS = tuple(key for key, _nvda, _titan in KINDS)

#: Kinds a user can act on - TalkBack plays `focus_actionable` for these
#: and `focus` for the rest, which is the within-kit fallback when a kit
#: (TalkBack, VoiceOver) has one focus sound rather than one per role.
ACTIONABLE_KINDS = frozenset({
    'button', 'checkbox', 'radio', 'edit', 'combobox', 'listitem',
    'treeitem', 'tab', 'menuitem', 'link', 'slider', 'toolbar'})

#: The auditory icon that stands for each kind, when a rule says the
#: type is a sound rather than a word (`icons.FOCUS_EVENTS`).
KIND_EVENT = {
    'button': 'focus.button', 'checkbox': 'focus.checkbox',
    'radio': 'focus.radiobutton', 'edit': 'focus.edit',
    'combobox': 'focus.combobox', 'list': 'focus.list',
    'listitem': 'focus.listitem', 'tree': 'focus.list',
    'treeitem': 'focus.treeitem', 'tab': 'focus.tab', 'menu': 'focus.menu',
    'menuitem': 'focus.menuitem', 'link': 'focus.link',
    'heading': 'focus.heading', 'slider': 'focus.slider',
    'progress': 'focus.progressbar', 'table': 'focus.tablecell',
    'graphic': 'focus.graphic', 'text': 'focus.text',
    'window': 'focus.dialog', 'toolbar': 'focus.toolbar',
    'other': 'focus.other',
}

#: The reader switches a SCHEME may set, so choosing a scheme is a whole
#: audio style, not only how the words come out. Applied through the
#: switchboard, so a scheme sets them the same way in both readers; only
#: what is reachable there (the sounds and the "read everywhere" switches),
#: never a file - the reader's own sounds stay `default/SRE`, unchanged.
SCHEME_SETTINGS = ('auditoryIcons', 'auditoryIconsEverywhere', 'soundScheme',
                   'pitchedEverywhere', 'pitchedFocus', 'dialogKinds',
                   'busyState', 'attentionState', 'liveStatusBars',
                   'reportContext')

#: The fields a rule may carry, and nothing else is kept. `pause` is the
#: silence between the parts, in milliseconds - what makes a scheme read
#: deliberately (SuperNova, Verbose) or briskly (Terse, Window-Eyes),
#: beyond which words and which voices.
RULE_FIELDS = ('parts', 'kind_word', 'sound', 'sound_only', 'voices',
               'braille', 'pause')

#: How a part of a reading is spelled in NVDA's braille properties, so a
#: braille rule can leave one out.
BRAILLE_PROPERTIES = {
    'name': ('name',),
    'kind': ('role', 'roleText', 'roleTextPost'),
    'state': ('states', 'negativeStates'),
    'value': ('value', 'current'),
    'description': ('description',),
    'place': ('positionInfo', 'level', 'rowNumber', 'columnNumber',
              'rowSpan', 'columnSpan', 'includeTableCellCoords'),
    'hint': (),
}

_LOCK = threading.RLock()
_store = {'loaded': False, 'active': 'classic', 'schemes': {}}
_counted = {'arranged': 0, 'sounded': 0, 'brailled': 0, 'switched': 0}
_braille = {'original': None, 'labels': None, 'installed': False}


def report():
    with _LOCK:
        return dict(_counted, active=_store['active'],
                    schemes=len(all_schemes()),
                    braille=bool(_braille['installed']))


# --------------------------------------------------------------------------- #
# Words
# --------------------------------------------------------------------------- #
def kind_names():
    return {
        # Translators: a kind of control, in the speech scheme editor.
        'button': _('Buttons'),
        'checkbox': _('Check boxes'),
        'radio': _('Radio buttons'),
        'edit': _('Edit fields'),
        'combobox': _('Combo boxes'),
        'list': _('Lists'),
        'listitem': _('List items'),
        'tree': _('Trees'),
        'treeitem': _('Tree items'),
        'tab': _('Tabs'),
        'menu': _('Menus'),
        'menuitem': _('Menu items'),
        'link': _('Links'),
        'heading': _('Headings'),
        'slider': _('Sliders and spin buttons'),
        'progress': _('Progress bars'),
        'table': _('Tables and cells'),
        'graphic': _('Pictures'),
        'text': _('Text and documents'),
        'window': _('Windows, dialogs and panes'),
        'toolbar': _('Tool bars and status bars'),
        'other': _('Everything else'),
    }


def part_names():
    # Translators: the instructions part, in the scheme editor.
    names = {'hint': _('How to use it - "to activate press space"')}
    try:
        from . import classes
        names.update(classes.part_names())
    except Exception:                                # noqa: BLE001
        names.update({part: part for part in PARTS})
    return names


def short_part_names():
    return {
        # Translators: a part of a control's reading, in a short row.
        'name': _('name'),
        'kind': _('type'),
        'state': _('state'),
        'value': _('value'),
        'description': _('description'),
        'place': _('place'),
        # Translators: a short name for the instructions part.
        'hint': _('hint'),
    }


def shipped_labels():
    return {
        # Translators: the name of a shipped speech scheme.
        'classic': _('Classic'),
        # Translators: the name of a shipped speech scheme.
        'terse': _('Terse'),
        # Translators: the name of a shipped speech scheme.
        'sounds': _('Sounds instead of type words'),
        # Translators: the name of a shipped speech scheme.
        'beginner': _('Beginner'),
        # Translators: the name of a shipped speech scheme.
        'detailed': _('Detailed'),
        # Translators: the name of a shipped speech scheme.
        'emacspeak': _('Emacspeak'),
    }


def shipped_meanings():
    return {
        'classic': _('Every control read the same way: the name, what it '
                     'is, its state - in the reading order.'),
        'terse': _('The name and the state; the type only where it '
                   'matters - a field, a combo box, a slider, a window.'),
        'sounds': _('The type of a control is a sound rather than a word, '
                    'and the words are the name, the state and the place.'),
        'beginner': _('For learning: the full type of every control, its '
                      'state, where it is, and how to use it - "to '
                      'activate, press Spacebar" - read unhurried.'),
        'detailed': _('Full words for every control - "push button", '
                      '"check box", "list item" - with the state, the '
                      'value and where it is.'),
        'emacspeak': _('Emacspeak: the role\'s auditory icon played beside '
                       'the words, and each part in its own voice.'),
    }


#: The full, explicit type word the Detailed scheme uses for each kind.
#: Translated (through ``_``), so the catalogue carries English and Polish
#: - "push button" / "przycisk polecenia", "check box" / "pole wyboru".
def DETAILED_WORDS_table():
    return {
        'button': _('push button'),
        'checkbox': _('check box'),
        'radio': _('radio button'),
        'edit': _('edit field'),
        'combobox': _('combo box'),
        'list': _('list'),
        'listitem': _('list item'),
        'tree': _('tree view'),
        'treeitem': _('tree item'),
        'tab': _('tab'),
        'menu': _('menu'),
        'menuitem': _('menu item'),
        'link': _('link'),
        'heading': _('heading'),
        'slider': _('slider'),
        'progress': _('progress bar'),
        'table': _('table'),
        'graphic': _('graphic'),
        'text': _('text'),
        'window': _('window'),
        'toolbar': _('tool bar'),
    }


class _LazyWords(object):
    """The detailed words, translated at read time (so a language change
    is picked up) and only for the kinds that have one."""

    def items(self):
        return DETAILED_WORDS_table().items()


DETAILED_WORDS = _LazyWords()


# --------------------------------------------------------------------------- #
# What ships
# --------------------------------------------------------------------------- #
def shipped():
    """The schemes this reader ships with, fresh every time."""
    labels = shipped_labels()
    return {
        'classic': {
            'label': labels['classic'],
            'default': {},
            'rules': {},
            # Read Titan's own controls the three-tone way; do not take
            # over every program (that is what the other schemes are for).
            'settings': {'auditoryIcons': True, 'pitchedEverywhere': False,
                         'soundScheme': True},
        },
        'terse': {
            'label': labels['terse'],
            # As terse as it can be: the NAME, and nothing else, except the
            # few kinds whose name alone says nothing - a tick box needs
            # its state, a field its value, a window that it IS one. No
            # pause: terse is brisk.
            'default': {'parts': ['name'], 'pause': 0},
            'settings': {'auditoryIcons': True,
                         'auditoryIconsEverywhere': False,
                         'pitchedEverywhere': False},
            'rules': {
                'checkbox': {'parts': ['name', 'state']},
                'radio': {'parts': ['name', 'state']},
                'edit': {'parts': ['name', 'value']},
                'password': {'parts': ['name', 'value']},
                'combobox': {'parts': ['name', 'value']},
                'slider': {'parts': ['name', 'value']},
                'progress': {'parts': ['name', 'value']},
                'window': {'parts': ['name', 'kind']},
                'dialog': {'parts': ['name', 'kind']},
            },
        },
        'sounds': {
            'label': labels['sounds'],
            'default': {'parts': ['name', 'state', 'value', 'place'],
                        'sound_only': True},
            'settings': {'auditoryIcons': True, 'soundScheme': True,
                         'auditoryIconsEverywhere': True},
            'rules': {kind: {'sound': 'event:' + event}
                      for kind, event in KIND_EVENT.items()},
        },
        # For somebody learning: everything, in full, unhurried, with the
        # usage hint on every control - "to activate, press Spacebar". Not
        # a copy of any one reader; the beginner's own scheme.
        'beginner': {
            'label': labels['beginner'],
            'default': {'parts': ['name', 'kind', 'state', 'value',
                                  'description', 'place', 'hint'],
                        'voices': {'kind': 'detail', 'state': 'alert',
                                   'hint': 'context'},
                        'pause': 130},
            'settings': {'pitchedEverywhere': True, 'auditoryIcons': True,
                         'dialogKinds': True, 'busyState': True,
                         'attentionState': True, 'liveStatusBars': True,
                         'reportContext': True},
            'rules': {
                'window': {'parts': ['name', 'kind', 'hint']},
                'dialog': {'parts': ['name', 'kind', 'hint']},
                'text': {'parts': ['name']},
                'heading': {'parts': ['name', 'kind', 'place']},
            },
        },
        # Full words for every control: the fuller type name (`kind_word`,
        # translated, so English AND Polish carry it), the state, the value
        # and the place. Detailed without the hint - for somebody who knows
        # how to work a control but wants it named in full.
        'detailed': {
            'label': labels['detailed'],
            'default': {'parts': ['name', 'kind', 'state', 'value',
                                  'description', 'place'],
                        'pause': 40},
            'settings': {'pitchedEverywhere': True, 'auditoryIcons': True},
            'rules': {kind: {'kind_word': word}
                      for kind, word in DETAILED_WORDS.items()},
        },
        # Emacspeak: the role's auditory ICON played beside the words (not
        # instead of them), and each part in its own voice - the voice-lock
        # `voices`/`personalities` already carry. The icons are this
        # reader's own focus sounds.
        'emacspeak': {
            'label': labels['emacspeak'],
            'default': {'parts': ['name', 'kind', 'state'],
                        'sound_only': False,
                        'voices': {'kind': 'context', 'state': 'alert'},
                        'pause': 30},
            # Emacspeak IS an audio desktop: the auditory icons everywhere,
            # the sound scheme on, and it reads every program - which is
            # what makes it unmistakable the moment it is chosen.
            'settings': {'auditoryIcons': True,
                         'auditoryIconsEverywhere': True,
                         'soundScheme': True, 'pitchedEverywhere': True,
                         'reportContext': True},
            'rules': {kind: {'sound': 'event:' + event, 'sound_only': False}
                      for kind, event in KIND_EVENT.items()},
        },
    }


# --------------------------------------------------------------------------- #
# The file
# --------------------------------------------------------------------------- #
def _folder():
    try:
        from . import classes
        return classes._folder()
    except Exception:                                # noqa: BLE001
        return ''


def path():
    folder = _folder()
    return os.path.join(folder, FILENAME) if folder else ''


def _clean_rule(rule):
    """One rule with anything that is not a field thrown away."""
    out = {}
    if not isinstance(rule, dict):
        return out
    parts = rule.get('parts')
    if isinstance(parts, (list, tuple)):
        kept = [str(one) for one in parts if str(one) in PARTS]
        seen = []
        for one in kept:
            if one not in seen:
                seen.append(one)
        out['parts'] = seen
    word = str(rule.get('kind_word') or '').strip()
    if word:
        out['kind_word'] = word
    sound = str(rule.get('sound') or '').strip()
    if sound:
        out['sound'] = sound
    if rule.get('sound_only'):
        out['sound_only'] = True
    try:
        pause = int(rule.get('pause'))
    except (TypeError, ValueError):
        pause = 0
    if pause:
        out['pause'] = max(0, min(2000, pause))
    voices = rule.get('voices')
    if isinstance(voices, dict):
        kept = {str(part): str(tag) for part, tag in voices.items()
                if str(part) in PARTS and str(tag or '').strip()}
        if kept:
            out['voices'] = kept
    braille = rule.get('braille')
    if isinstance(braille, dict):
        kept = {}
        parts = braille.get('parts')
        if isinstance(parts, (list, tuple)):
            kept['parts'] = [str(one) for one in parts if str(one) in PARTS]
        if 'kind' in braille and braille.get('kind') is not None:
            kept['kind'] = str(braille.get('kind'))
        states = braille.get('states')
        if isinstance(states, dict):
            kept['states'] = {str(k): str(v) for k, v in states.items()}
        if kept:
            out['braille'] = kept
    return out


def _clean_scheme(scheme, key):
    out = {'label': str((scheme or {}).get('label') or key).strip() or key,
           'default': _clean_rule((scheme or {}).get('default')),
           'rules': {},
           'settings': {}}
    rules = (scheme or {}).get('rules')
    if isinstance(rules, dict):
        for kind, rule in rules.items():
            if str(kind) in KIND_KEYS:
                cleaned = _clean_rule(rule)
                if cleaned:
                    out['rules'][str(kind)] = cleaned
    settings = (scheme or {}).get('settings')
    if isinstance(settings, dict):
        for name, value in settings.items():
            name = str(name)
            if name in SCHEME_SETTINGS:
                out['settings'][name] = bool(value)
    # The earcon KIT the whole scheme uses (an empty string = the reader's
    # own default/SRE sounds), and whether the scheme is speech, sound, or
    # both - the "sound and speech" option.
    kit = str((scheme or {}).get('earcons') or '').strip()
    if kit:
        out['earcons'] = kit
    mode = str((scheme or {}).get('output') or '').strip()
    if mode in ('both', 'speech', 'sound'):
        out['output'] = mode
    return out


#: Schemes that once shipped and were taken out. A user who had selected
#: or changed one left an entry in the stored config, and `all_schemes`
#: would resurface any stored key not currently shipped as a "user
#: scheme" - so a removed scheme came back. These are pruned on load and
#: never resurfaced, whatever is in the file.
RETIRED = frozenset({'jaws', 'window-eyes', 'supernova', 'chromevox',
                     'talkback', 'voiceover', 'verbose'})


def _load():
    with _LOCK:
        if _store['loaded']:
            return _store
        _store['loaded'] = True
        _store['schemes'] = {}
        _store['active'] = 'classic'
        where = path()
        if where and os.path.isfile(where):
            try:
                with open(where, encoding='utf-8') as handle:
                    data = json.load(handle)
            except Exception:                        # noqa: BLE001
                data = None
            if isinstance(data, dict):
                active = str(data.get('active') or 'classic')
                schemes = data.get('schemes')
                if isinstance(schemes, dict):
                    for key, scheme in schemes.items():
                        name = _key(key)
                        if name and name not in RETIRED:
                            _store['schemes'][name] = _clean_scheme(scheme,
                                                                    name)
                _store['active'] = active
                if active in RETIRED:
                    active = 'classic'
                    _store['active'] = active
        if _store['active'] not in all_schemes():
            _store['active'] = 'classic'
        return _store


def forget():
    with _LOCK:
        _store['loaded'] = False
        _store['schemes'] = {}
        _store['active'] = 'classic'


def save():
    where = path()
    if not where:
        return False
    with _LOCK:
        _load()
        data = {'active': _store['active'],
                'schemes': {key: scheme for key, scheme
                            in _store['schemes'].items()}}
    try:
        folder = os.path.dirname(where)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1,
                      sort_keys=True)
        return True
    except Exception:                                # noqa: BLE001
        return False


def _key(label):
    """A key out of a label: letters, digits and dashes, lower case."""
    made = []
    for char in str(label or '').strip().lower():
        if char.isalnum():
            made.append(char)
        elif made and made[-1] != '-':
            made.append('-')
    return ''.join(made).strip('-')


# --------------------------------------------------------------------------- #
# The schemes
# --------------------------------------------------------------------------- #
def all_schemes():
    """Every scheme by key: the shipped ones, with the user's changes to
    them laid over, and the user's own after them."""
    with _LOCK:
        store = _load()
        found = shipped()
        for key, scheme in store['schemes'].items():
            if key in found:
                base = found[key]
                merged = {'label': base['label'],
                          'default': dict(base['default']),
                          'rules': {kind: dict(rule) for kind, rule
                                    in base['rules'].items()},
                          'settings': dict(base.get('settings') or {}),
                          'earcons': base.get('earcons', ''),
                          'output': base.get('output', 'both')}
                if scheme.get('default'):
                    merged['default'].update(scheme['default'])
                for kind, rule in scheme.get('rules', {}).items():
                    merged['rules'].setdefault(kind, {}).update(rule)
                if scheme.get('settings'):
                    merged['settings'].update(scheme['settings'])
                if scheme.get('earcons'):
                    merged['earcons'] = scheme['earcons']
                if scheme.get('output'):
                    merged['output'] = scheme['output']
                found[key] = merged
            elif key not in RETIRED:
                found[key] = {'label': scheme['label'],
                              'default': dict(scheme['default']),
                              'rules': {kind: dict(rule) for kind, rule
                                        in scheme['rules'].items()},
                              'settings': dict(scheme.get('settings') or {}),
                              'earcons': scheme.get('earcons', ''),
                              'output': scheme.get('output', 'both')}
        return found


def names():
    """``[(key, label)]``, shipped first in their order, then the user's."""
    found = all_schemes()
    out = [(key, found[key]['label']) for key in shipped() if key in found]
    for key in sorted(found):
        if key not in shipped():
            out.append((key, found[key]['label']))
    return out


def is_shipped(key):
    return str(key or '') in shipped()


def is_changed(key):
    """Whether a shipped scheme carries the user's changes."""
    with _LOCK:
        return str(key or '') in _load()['schemes']


def active():
    with _LOCK:
        return _load()['active']


def label_of(key=None):
    key = str(key or active())
    return all_schemes().get(key, {}).get('label', key)


def use(key):
    """Make ``key`` the scheme in force. Answers whether it exists."""
    key = str(key or '')
    if key not in all_schemes():
        return False
    with _LOCK:
        _load()['active'] = key
        _counted['switched'] += 1
    save()
    refresh_braille()
    # A scheme is a whole audio style: choosing it also sets the reader's
    # own switches (the sounds, and whether it reads everywhere).
    try:
        apply_settings(key)
    except Exception:                                # noqa: BLE001
        pass
    return True


def cycle(step=1):
    """The next (or previous) scheme, made active. ``(key, label)``."""
    order = [key for key, _label in names()]
    if not order:
        return 'classic', label_of('classic')
    try:
        at = order.index(active())
    except ValueError:
        at = 0
    key = order[(at + int(step)) % len(order)]
    use(key)
    return key, label_of(key)


def create(label, copy_of=None):
    """A scheme of the user's own, a copy of ``copy_of`` (the active one
    by default). Answers its key, or '' when the name is unusable."""
    key = _key(label)
    if not key or key in all_schemes():
        return ''
    source = all_schemes().get(str(copy_of or active()), {'default': {},
                                                          'rules': {}})
    with _LOCK:
        _load()['schemes'][key] = {
            'label': str(label).strip(),
            'default': dict(source.get('default') or {}),
            'rules': {kind: dict(rule) for kind, rule
                      in (source.get('rules') or {}).items()}}
    save()
    return key


def rename(key, label):
    key = str(key or '')
    label = str(label or '').strip()
    if not label or is_shipped(key):
        return False
    with _LOCK:
        store = _load()
        if key not in store['schemes']:
            return False
        store['schemes'][key]['label'] = label
    return save()


def delete(key):
    """Delete the user's scheme, or put a shipped one back as shipped."""
    key = str(key or '')
    with _LOCK:
        store = _load()
        if key not in store['schemes']:
            return False
        del store['schemes'][key]
        if store['active'] == key and key not in all_schemes():
            store['active'] = 'classic'
    save()
    refresh_braille()
    return True


def _editable(key):
    """The user's own copy of a scheme, made if it is a shipped one."""
    key = str(key or active())
    store = _load()
    if key not in store['schemes']:
        if key not in shipped():
            return None
        store['schemes'][key] = {'label': shipped()[key]['label'],
                                 'default': {}, 'rules': {}}
    return store['schemes'][key]


def rule_of(key, kind):
    """The rule for ``kind`` as STORED in this scheme (merged over the
    scheme's default and the shipped rule), for the editors."""
    scheme = all_schemes().get(str(key or active())) or {}
    rule = dict(scheme.get('default') or {})
    rule.update(scheme.get('rules', {}).get(str(kind), {}))
    return rule


def set_rule(key, kind, **fields):
    """Change fields of one kind's rule in one scheme. A field given as
    None is taken away (the kind falls back to the scheme's default)."""
    kind = str(kind)
    if kind not in KIND_KEYS:
        return False
    with _LOCK:
        scheme = _editable(key)
        if scheme is None:
            return False
        rule = dict(scheme['rules'].get(kind) or {})
        for name, value in fields.items():
            if name not in RULE_FIELDS:
                continue
            if value is None:
                rule.pop(name, None)
            else:
                rule[name] = value
        cleaned = _clean_rule(rule)
        for name, value in fields.items():
            # A field deliberately emptied - no sound, no word, the type
            # shown in braille as nothing - must survive the cleaning
            # that drops empty fields, or it would fall back to the
            # scheme's default and the change would be undone.
            if name == 'braille' and isinstance(value, dict) \
                    and value.get('kind') == '':
                cleaned.setdefault('braille', {})['kind'] = ''
            if name == 'sound_only' and value is False:
                cleaned['sound_only'] = False
        if cleaned:
            scheme['rules'][kind] = cleaned
        else:
            scheme['rules'].pop(kind, None)
    save()
    refresh_braille()
    return True


def set_default(key, **fields):
    with _LOCK:
        scheme = _editable(key)
        if scheme is None:
            return False
        rule = dict(scheme.get('default') or {})
        for name, value in fields.items():
            if name not in RULE_FIELDS:
                continue
            if value is None:
                rule.pop(name, None)
            else:
                rule[name] = value
        scheme['default'] = _clean_rule(rule)
    save()
    refresh_braille()
    return True


def toggle_part(key, kind, part):
    """Switch one part of a kind's reading on or off. Answers its state."""
    part = str(part)
    parts = list(parts_for(kind, key))
    if part in parts:
        parts.remove(part)
        on = False
    else:
        # Put back where the reading order has it, so switching a part
        # off and on again does not move it to the end.
        order = list(_default_order())
        parts.append(part)
        parts.sort(key=lambda one: order.index(one) if one in order
                   else len(order))
        on = True
    set_rule(key, kind, parts=parts)
    return on


def move_part(key, kind, part, step):
    parts = list(parts_for(kind, key))
    if part not in parts:
        return False
    at = parts.index(part)
    to = at + int(step)
    if to < 0 or to >= len(parts):
        return False
    parts[at], parts[to] = parts[to], parts[at]
    return set_rule(key, kind, parts=parts)


# --------------------------------------------------------------------------- #
# What a rule answers
# --------------------------------------------------------------------------- #
def _default_order():
    try:
        from . import classes
        found = classes.parts_read()
        if found:
            return list(found)
    except Exception:                                # noqa: BLE001
        pass
    return list(PARTS)


def kind_of(role):
    """The kind a role falls into. ``role`` may be NVDA's `Role`, its name,
    or Titan Access's role key."""
    if role is None:
        return 'other'
    name = getattr(role, 'name', None)
    word = str(name if isinstance(name, str) and name else role or '')
    word = word.strip()
    if not word:
        return 'other'
    upper = word.upper()
    lower = word.lower()
    for key, nvda, titan in KINDS:
        if upper in nvda or lower in titan:
            return key
    return 'other'


def kind_of_object(obj):
    try:
        return kind_of(getattr(obj, 'role', None))
    except Exception:                                # noqa: BLE001
        return 'other'


def rule_for(kind, key=None):
    """The rule in force for a kind: shipped default, then the scheme's
    default, then the scheme's own rule for the kind."""
    return rule_of(key, kind)


def parts_for(kind, key=None):
    """The parts said for this kind, in order."""
    rule = rule_for(kind, key)
    parts = rule.get('parts')
    if parts:
        return list(parts)
    return _default_order()


def voice_for(kind, part, key=None):
    """The voice class a part of this kind is said in."""
    rule = rule_for(kind, key)
    chosen = (rule.get('voices') or {}).get(str(part))
    return str(chosen) if chosen else PART_VOICE.get(str(part), 'name')


def kind_word_for(kind, key=None):
    return str(rule_for(kind, key).get('kind_word') or '')


def sound_for(kind, key=None):
    """``('event', id)``, ``('file', path)``, ``('set', 'name/kind')`` or
    None. A ``set`` is an earcon KIT - ChromeVox's, TalkBack's,
    VoiceOver's - a sound per kind under ``reader/earcons/<kit>/``, which
    falls back to the reader's own focus earcon when the kit has not been
    dropped in."""
    sound = str(rule_for(kind, key).get('sound') or '').strip()
    if not sound:
        # No sound on the kind's own rule: the scheme's earcon KIT, if it
        # has one, gives every kind its sound - which is how a scheme
        # SWITCHES the whole earcon set at once.
        kit = scheme_earcons(key)
        if kit:
            return 'set', '%s/%s' % (kit, kind)
        return None
    if sound.startswith('event:'):
        return 'event', sound[len('event:'):]
    if sound.startswith('set:'):
        return 'set', sound[len('set:'):]
    return 'file', sound


def sound_only(kind, key=None):
    return bool(rule_for(kind, key).get('sound_only')) \
        and sound_for(kind, key) is not None


def pause_for(kind, key=None):
    """The silence between the parts of this kind, in milliseconds."""
    try:
        return max(0, min(2000, int(rule_for(kind, key).get('pause') or 0)))
    except (TypeError, ValueError):
        return 0


#: Which family of usage hints a scheme uses. Desktop readers name the
#: KEY, mobile readers the GESTURE, Chrome OS its own chord.
HINT_STYLE = {
    'beginner': 'desktop', 'detailed': 'desktop',
}


def _hint_table(style):
    # Short functional instructions - what to press or do to work the
    # control. Written here (not copied), faithful to each reader's habit.
    if style == 'mobile':
        act = _('Double tap to activate')
        return {
            'button': act, 'link': act, 'menuitem': act, 'tab': act,
            'listitem': act, 'treeitem': act,
            'checkbox': _('Double tap to toggle'),
            'radio': _('Double tap to select'),
            'edit': _('Double tap to edit'),
            'combobox': _('Double tap to change'),
            'slider': _('Swipe up or down to adjust'),
        }
    if style == 'chromeos':
        act = _('Press Search plus Space to activate')
        return {
            'button': act, 'link': act, 'menuitem': act, 'tab': act,
            'checkbox': _('Press Search plus Space to toggle'),
            'radio': _('Press Search plus Space to select'),
            'edit': _('Type to edit'),
            'combobox': _('Use the arrow keys to change'),
            'slider': _('Use the arrow keys to adjust'),
        }
    # desktop (JAWS / Dolphin / Window-Eyes)
    return {
        'button': _('To activate, press Spacebar'),
        'link': _('To follow, press Enter'),
        'checkbox': _('To toggle, press Spacebar'),
        'radio': _('To select, use the arrow keys'),
        'edit': _('To edit, type'),
        'password': _('To edit, type'),
        'combobox': _('To change, use the arrow keys'),
        'listitem': _('To choose, press Enter'),
        'treeitem': _('To expand or collapse, use the arrow keys'),
        'menuitem': _('To choose, press Enter'),
        'tab': _('To switch, use the arrow keys'),
        'slider': _('To adjust, use the arrow keys'),
    }


def hint_text(kind, key=None):
    """The usage hint for a kind under a scheme - "To activate, press
    Spacebar", "Double tap to activate" - or '' where the scheme has none
    for that kind or is not one that gives hints."""
    style = HINT_STYLE.get(str(key or active()))
    if not style:
        return ''
    return _hint_table(style).get(str(kind), '')


def scheme_settings(key=None):
    """The reader switches a scheme sets, merged shipped + user."""
    scheme = all_schemes().get(str(key or active())) or {}
    return dict(scheme.get('settings') or {})


#: The earcon kits a scheme can switch to, '' being the reader's own
#: default/SRE sounds. `earcon_kits()` are the mobile/Chrome OS sets that
#: survive as sound options.
def earcon_kit_choices():
    # Translators: the reader's own sounds, not a mobile kit.
    rows = [('', _('The reader\'s own sounds'))]
    for kit in earcon_kits():
        rows.append((kit, kit))
    return rows


def scheme_earcons(key=None):
    """The earcon kit the scheme uses, or '' for the reader's own."""
    scheme = all_schemes().get(str(key or active())) or {}
    return str(scheme.get('earcons') or '')


def set_earcons(key, kit):
    """Switch the whole scheme to an earcon kit ('' = the reader's own)."""
    with _LOCK:
        scheme = _editable(key)
        if scheme is None:
            return False
        kit = str(kit or '').strip()
        if kit and kit not in earcon_kits():
            return False
        if kit:
            scheme['earcons'] = kit
        else:
            scheme.pop('earcons', None)
    save()
    return True


def scheme_output(key=None):
    """'both' (speech and sound), 'speech' or 'sound'. The default is
    'both'."""
    scheme = all_schemes().get(str(key or active())) or {}
    mode = str(scheme.get('output') or 'both')
    return mode if mode in ('both', 'speech', 'sound') else 'both'


def set_output(key, mode):
    mode = str(mode or 'both')
    if mode not in ('both', 'speech', 'sound'):
        return False
    with _LOCK:
        scheme = _editable(key)
        if scheme is None:
            return False
        if mode == 'both':
            scheme.pop('output', None)
        else:
            scheme['output'] = mode
    save()
    return True


def apply_settings(key=None):
    """Write the scheme's switches to the reader - so a scheme influences
    ALL the reader's settings, not only the reading. The reader's sounds
    are `default/SRE` and are not touched; this only turns them on or off
    and says whether to read everywhere."""
    settings = scheme_settings(key)
    if not settings:
        return False
    try:
        from . import switchboard
    except Exception:                                # noqa: BLE001
        return False
    wrote = False
    for name, value in settings.items():
        try:
            if switchboard.write(name, bool(value)):
                wrote = True
        except Exception:                            # noqa: BLE001
            continue
    return wrote


def set_pause(key, ms):
    """Shorten or lengthen a scheme's pause. Answers the value kept."""
    try:
        ms = max(0, min(2000, int(ms)))
    except (TypeError, ValueError):
        return None
    set_default(key, pause=ms if ms else None)
    return ms


def active_pause():
    """The pause of the scheme in force, from its default rule - the
    scheme-wide pacing a reader applies between the parts it speaks."""
    scheme = all_schemes().get(active()) or {}
    try:
        return max(0, min(2000, int((scheme.get('default') or {}).get(
            'pause') or 0)))
    except (TypeError, ValueError):
        return 0


def braille_for(kind, key=None):
    """``{'parts': [...], 'kind': None | '' | 'btn', 'states': {}}``.
    ``kind`` None means the reader's own abbreviation."""
    rule = rule_for(kind, key)
    braille = dict(rule.get('braille') or {})
    parts = braille.get('parts')
    return {'parts': list(parts) if parts else list(PARTS),
            'kind': braille.get('kind'),
            'states': dict(braille.get('states') or {})}


def arrange(kind, made, default_order=None, keep_kind_word=False):
    """The parts of one control, in the scheme's order and voices.

    ``made`` is ``{part: [(text, voice_tag)]}`` as the reader built it;
    the answer is the segments to speak, in order, with the voice class of
    each part changed where the rule names one, the type word replaced
    where the rule gives one, and the type left out where a sound stands
    for it.
    """
    with _LOCK:
        _counted['arranged'] += 1
    rule = rule_for(kind)
    order = list(rule.get('parts') or default_order or _default_order())
    voices = rule.get('voices') or {}
    out = []
    for part in order:
        segments = [tuple(one) for one in (made.get(part) or [])]
        if part == 'hint' and not segments:
            # The control carried no help of its own; give the scheme's
            # own usage hint for this kind, if it has one.
            text = hint_text(kind)
            if text:
                segments = [(text, 'detail')]
        if part == 'kind':
            if rule.get('sound_only') and rule.get('sound'):
                continue
            word = str(rule.get('kind_word') or '').strip()
            # A word the user gave THIS control (`labels.custom_of`) is
            # more specific than the scheme's word for its kind, so the
            # caller says so and the scheme's word stands aside.
            if word and not keep_kind_word:
                segments = [(word,) + tuple(segments[0][1:])] if segments \
                    else [(word, 'kind')]
        tag = voices.get(part)
        if tag:
            # Whatever a segment carries beyond its voice - Titan Access
            # keeps a default pitch there - travels with it unchanged.
            segments = [(one[0], tag) + tuple(one[2:]) for one in segments]
        out.extend(segments)
    # **A description is CONTENT, not a verbosity nicety, so it is read
    # whatever the scheme.** The Run dialog's instructions ("type the name
    # of a program...") are its description; a scheme that leaves the
    # description part out must still say it. Appended when the order did
    # not already include it and the control has one.
    if 'description' not in order:
        extra = [tuple(one) for one in (made.get('description') or [])]
        tag = voices.get('description')
        if tag:
            extra = [(one[0], tag) + tuple(one[2:]) for one in extra]
        out.extend(extra)
    return out


def sounded(kind):
    """Play the sound the rule gives this kind, if any. Answers whether.

    An earcon KIT (``set:``) is played from ``reader/earcons/<kit>/<kind>``,
    the user's theme first then the component's own; a kit that has not
    been dropped in falls back to the reader's own focus earcon, so a
    ChromeVox / TalkBack / VoiceOver scheme still sounds - with Titan's
    earcons - until the real kit is there.
    """
    if scheme_output() == 'speech':
        return False
    found = sound_for(kind)
    if found is None:
        return False
    what, where = found
    try:
        from . import icons
        if what == 'event':
            ok = bool(icons.play(where))
        elif what == 'set':
            ok = bool(_play_kit(icons, where, kind))
        else:
            ok = bool(icons.play_file(where))
    except Exception:                                # noqa: BLE001
        ok = False
    if ok:
        with _LOCK:
            _counted['sounded'] += 1
    return ok


#: An earcon-kit sound is remembered as present or missing so a kit that
#: has not been dropped in is asked for once, not on every focus.
_kit_seen = {}


def _play_kit(icons, where, kind):
    """Play the earcon kit's sound for a kind, or the kind's own focus
    earcon when the kit has not that sound.

    The kits live in the ADD-ON's own data - ``sounds/earcons/<kit>/`` next
    to `icons.py`, which in each tree is that reader's own folder (the
    add-on's `sounds`, Titan Access's `portable/sounds`) - so a kit ships
    with the add-on and needs neither a theme nor Titan running. A theme
    that carries the same kit under ``reader/earcons/<kit>/`` is tried too,
    so a user can replace one. ``where`` is ``'<kit>/<kind>'``.
    """
    import os
    ours = getattr(icons, 'OURS', '')
    kit = str(where).split('/', 1)[0]
    for extension in ('.ogg', '.wav'):
        own = os.path.join(ours, 'earcons', kit, kind + extension) \
            if ours else ''
        if own and _kit_seen.get(own) is not False:
            if os.path.isfile(own) and icons.play_file(own):
                _kit_seen[own] = True
                return True
            _kit_seen[own] = False
        theme = 'reader/earcons/%s/%s%s' % (kit, kind, extension)
        if _kit_seen.get(theme) is not False and icons.play_titan(theme):
            _kit_seen[theme] = True
            return True
        _kit_seen[theme] = False
    # **The kit's own FOCUS sound**, for a kit that has one sound on
    # navigation rather than one per role - which is TalkBack and
    # VoiceOver (ChromeVox has a file per role, matched above). An
    # actionable control gets `focus_actionable`, everything else `focus`.
    for base in (('focus_actionable', 'focus') if kind in ACTIONABLE_KINDS
                 else ('focus',)):
        for extension in ('.ogg', '.wav'):
            own = os.path.join(ours, 'earcons', kit, base + extension) \
                if ours else ''
            if own and _kit_seen.get(own) is not False:
                if os.path.isfile(own) and icons.play_file(own):
                    _kit_seen[own] = True
                    return True
                _kit_seen[own] = False
            theme = 'reader/earcons/%s/%s%s' % (kit, base, extension)
            if _kit_seen.get(theme) is not False and icons.play_titan(theme):
                _kit_seen[theme] = True
                return True
            _kit_seen[theme] = False
    # The kit has not this sound: the reader's own earcon for the kind.
    event = KIND_EVENT.get(kind)
    return bool(icons.play(event)) if event else False


def earcon_kits():
    """The kits a scheme can name, whether or not their audio is present -
    the scheme works either way. Titan's own is not a kit (it is the
    fallback); these are the mobile and Chrome OS reader sets."""
    return ('chromevox', 'talkback', 'voiceover')


# --------------------------------------------------------------------------- #
# Sounds a rule can choose from
# --------------------------------------------------------------------------- #
def sound_choices():
    """``[(value, label)]``: nothing, every icon of the reader, a file."""
    # Translators: the choice of no sound for a kind of control.
    rows = [('', _('No sound'))]
    try:
        from . import icons
        for event in icons.all_events():
            rows.append(('event:' + event, icons.label_of(event) or event))
    except Exception:                                # noqa: BLE001
        pass
    for kit in earcon_kits():
        # Translators: an earcon kit as a per-kind sound. {kit} is its name.
        rows.append(('set:%s/${kind}' % kit,
                     _('The {kit} earcon for this kind').format(kit=kit)))
    return rows


def sound_label(sound):
    sound = str(sound or '')
    for value, label in sound_choices():
        if value == sound:
            return label
    if sound.startswith('event:'):
        return sound[len('event:'):]
    return os.path.basename(sound) if sound else _('No sound')


# --------------------------------------------------------------------------- #
# Braille, where the reader has it
# --------------------------------------------------------------------------- #
def _braille_module():
    try:
        from . import compat
        return compat.braille
    except Exception:                                # noqa: BLE001
        return None


def _filtered_properties(values):
    """NVDA's braille properties with the scheme's braille rule applied."""
    role = values.get('role')
    kind = kind_of(role)
    rule = braille_for(kind)
    wanted = set(rule['parts'])
    out = dict(values)
    for part, keys in BRAILLE_PROPERTIES.items():
        if part in wanted:
            continue
        for key in keys:
            out.pop(key, None)
    abbreviation = rule.get('kind')
    if abbreviation is not None and 'kind' in wanted:
        if abbreviation == '':
            for key in BRAILLE_PROPERTIES['kind']:
                out.pop(key, None)
        else:
            out['roleText'] = abbreviation
    return out


def install_braille():
    """Wrap NVDA's braille property renderer, once. Answers whether."""
    braille = _braille_module()
    if braille is None:
        return False
    with _LOCK:
        if _braille['installed']:
            return True
        original = getattr(braille, 'getPropertiesBraille', None)
        if not callable(original):
            return False

        def wrapped(**values):
            try:
                values = _filtered_properties(values)
                with _LOCK:
                    _counted['brailled'] += 1
            except Exception:                        # noqa: BLE001
                pass
            return original(**values)

        _braille['original'] = original
        braille.getPropertiesBraille = wrapped
        _braille['installed'] = True
    return True


def uninstall_braille():
    braille = _braille_module()
    with _LOCK:
        if not _braille['installed']:
            return False
        if braille is not None and _braille['original'] is not None:
            try:
                braille.getPropertiesBraille = _braille['original']
            except Exception:                        # noqa: BLE001
                pass
        _braille['installed'] = False
        _braille['original'] = None
    return True


def refresh_braille():
    """Nothing is cached on the braille side: the wrapper asks the rule
    on every render. Kept as the one call the editors make, so a reader
    that DOES cache can answer it."""
    return bool(_braille['installed'])


# --------------------------------------------------------------------------- #
# For the walked manager and the status command
# --------------------------------------------------------------------------- #
def described():
    """One row per scheme, as words."""
    rows = []
    now = active()
    for key, label in names():
        rows.append({'id': key, 'label': label, 'active': key == now,
                     'shipped': is_shipped(key), 'changed': is_changed(key),
                     'meaning': shipped_meanings().get(key, '')})
    return rows


def rule_sentence(kind, key=None):
    """One kind's rule in a sentence, for a row of the walked manager."""
    words = short_part_names()
    said = ', '.join(words.get(part, part) for part in parts_for(kind, key))
    word = kind_word_for(kind, key)
    if word:
        # Translators: {word} is what a kind of control is called instead.
        said = '%s; %s' % (said, _('called "{word}"').format(word=word))
    sound = sound_for(kind, key)
    if sound:
        said = '%s; %s' % (said, sound_label(rule_for(kind, key).get('sound')))
    return said

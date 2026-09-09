# -*- coding: utf-8 -*-
"""The class manager: what each kind of thing sounds like, and in what order.

:mod:`voices` is the idea - a semantic class carried by the voice instead of
spent as a word - and it shipped with the numbers chosen here. That is the
right default and the wrong last word: how much pitch a listener can hear
depends on their synthesizer, their rate, their hearing and their taste, and
a dial nobody notices costs a speech command per utterance for nothing.

So the classes are a table the user owns:

* **Every class is listed with what it is FOR**, not just its name. "detail"
  means nothing; "the columns beside a row's name - a date, a size" is a
  thing somebody can have an opinion about.
* **A change is heard before it is kept.** The manager speaks a sample in
  the voice being edited, because the only way to know whether a dial is
  audible is to hear it on the synthesizer the user actually has.
* **What is stored is only what was CHANGED.** A class the user has not
  touched follows this add-on's defaults, so the defaults can be improved
  later without silently overwriting somebody's answers - and "put it back"
  really does put it back.

**A class is a whole voice, not three dials.** It began as pitch, rate and
volume, because those are the three NVDA has real speech commands for. What
a listener actually wants is often bigger than that - a notification in a
different voice entirely, so it is not mistaken for the control they were
reading - so a class may also name a **voice**, a **variant**, an
**inflection** and, when it is a whole message rather than part of one, a
**synthesizer of its own**. :mod:`speaking` is what fetches those;
:data:`WHOLE` is which classes may ask.

**And the ORDER is the user's too.** "Checked, check box" and "check box,
checked" are the same three facts in two orders, and which of them is right
is a matter of what somebody is used to - JAWS, NVDA, Window-Eyes and Titan
Access do not agree, and neither do two users of any one of them. So the
parts of a control's reading are a list that can be reordered and switched
off, and nothing in the reader assumes a fixed shape any more.

The store is in NVDA's own configuration folder, with the labels and the
reader modules, for the same reason: these are answers about how NVDA
should behave, they must survive Titan being uninstalled, and a user who
has no Titan at all still has a reader that sounds the way they set it.
"""

import json
import os
import threading

from . import i18n

_ = i18n.install(globals())

FILENAME = 'titanVoiceClasses.json'

#: The dials, in Titan's own -10..10, which is what :mod:`prosody` converts
#: onto NVDA's 0..100 settings. `inflection` is the one NVDA has no speech
#: command for, so it is only honoured where the whole utterance is ours -
#: which is exactly the classes in :data:`WHOLE`.
DIALS = ('pitch', 'rate', 'volume', 'inflection')

#: The parts of a voice that are a NAME rather than a number. Each is a
#: choice out of what this NVDA really has (:mod:`speaking`), and an empty
#: one means "whatever the reader is already using" - which is the default
#: for every class and the only safe answer for a machine whose voices are
#: not the ones the answers were written on.
NAMES = ('synth', 'voice', 'variant')

FIELDS = DIALS + NAMES
LIMIT = 10

#: **Which classes may name a synthesizer of their own.** A different synth
#: is a different program producing the sound: it cannot be part of an
#: utterance, because the two would talk over each other. These are the
#: classes that ARE a whole utterance - a message, not a piece of one - so
#: for them it is not only possible but the most useful thing on the page: a
#: notification in a plainly different voice is one the listener does not
#: have to parse to know it is not the control they were reading.
WHOLE = frozenset({'notification', 'controller', 'text', 'typed',
                   'spelling', 'alert', 'dialog', 'live', 'monitor',
                   'busy', 'attention'})

_LOCK = threading.RLock()
_overrides = None
_order = None


# --------------------------------------------------------------------------- #
# What each class is for, in words somebody can have an opinion about
# --------------------------------------------------------------------------- #
def meanings():
    return {
        # Translators: a semantic voice class, shown in the class manager.
        'name': _('the name of a control, and what is in it'),
        'kind': _('what a thing IS - button, list item, file'),
        'state': _('checked, selected, expanded'),
        'folder': _('a row that is a folder - something you go into'),
        'file': _('a row that is a file - something you open'),
        'detail': _('the columns beside a row\'s name - a date, a size'),
        'context': _('where the user now is: the folder or document that '
                     'has just been opened'),
        'place': _('orientation - "3 of 10", "level 2"'),
        'value': _('what is IN a control - the text of a field, where a '
                   'slider stands'),
        'description': _('the description a program gives a control, '
                         'beside its name'),
        'disabled': _('a control that is there and cannot be used'),
        'alert': _('something the user should act on'),
        'guessed': _('a name this add-on worked out rather than one the '
                     'program gave'),
        'icon': _('a small picture standing for a command'),
        'picture': _('a picture that is content'),
        'animation': _('a picture that is moving'),
        'dialog': _('the kind of a dialog - question, warning, error'),
        'live': _('something that changed while the focus was elsewhere'),
        'notification': _('a message from the system or from a program - '
                          'Titan\'s own notifications arrive this way'),
        'controller': _('what another program says through the NVDA '
                        'controller, rather than the reader itself'),
        'text': _('reading text - a document, a page, say all'),
        'typed': _('keyboard echo - the characters and words you type'),
        'spelling': _('a word being spelled out, letter by letter'),
        'monitor': _('a watched area saying it has changed'),
        'busy': _('a program that has stopped answering'),
        'attention': _('a window asking for you - it flashed on the '
                       'taskbar'),
        'application': _('a control of a Titan application, walked as a '
                         'virtual window'),
    }


def labels():
    """The SHORT name of each class - what the list in the manager says.

    A list is read one row at a time with the arrows, so a row has to be
    the thing itself and not a sentence about it: "control name", not "the
    name of a control, and what is in it". The sentence is still worth
    having and is still here - :func:`meanings` - but it belongs beside the
    list, where somebody who wants it can read it, rather than in front of
    every row for somebody who does not.
    """
    return {
        # Translators: the short name of a voice class, in the list.
        'name': _('control name'),
        # Translators: the short name of a voice class.
        'kind': _('control type'),
        # Translators: the short name of a voice class.
        'state': _('control state'),
        # Translators: the short name of a voice class.
        'folder': _('folder'),
        # Translators: the short name of a voice class.
        'file': _('file'),
        # Translators: the short name of a voice class.
        'detail': _('columns'),
        # Translators: the short name of a voice class.
        'context': _('where you now are'),
        # Translators: the short name of a voice class.
        'place': _('position'),
        # Translators: the short name of a voice class.
        'value': _('value'),
        # Translators: the short name of a voice class.
        'description': _('description'),
        # Translators: the short name of a voice class.
        'disabled': _('unavailable'),
        # Translators: the short name of a voice class.
        'alert': _('alert'),
        # Translators: the short name of a voice class.
        'guessed': _('guessed name'),
        # Translators: the short name of a voice class.
        'icon': _('icon'),
        # Translators: the short name of a voice class.
        'picture': _('picture'),
        # Translators: the short name of a voice class.
        'animation': _('animation'),
        # Translators: the short name of a voice class.
        'dialog': _('kind of dialog'),
        # Translators: the short name of a voice class.
        'live': _('changed elsewhere'),
        # Translators: the short name of a voice class.
        'notification': _('system notification'),
        # Translators: the short name of a voice class.
        'controller': _('NVDA controller'),
        # Translators: the short name of a voice class.
        'text': _('reading text'),
        # Translators: the short name of a voice class.
        'typed': _('keyboard echo'),
        # Translators: the short name of a voice class.
        'spelling': _('spelling'),
        # Translators: the short name of a voice class.
        'monitor': _('watched area'),
        # Translators: the short name of a voice class.
        'busy': _('busy'),
        # Translators: the short name of a voice class.
        'attention': _('wants attention'),
        # Translators: the short name of a voice class.
        'application': _('Titan application'),
    }


def label_of(tag):
    return labels().get(str(tag), str(tag))


#: Which group of the manager a class belongs in. A flat list of nineteen
#: classes is a list nobody finds anything in, and the three groups are
#: three different questions: what a control sounds like, what a message
#: sounds like, and what a picture sounds like.
GROUPS = (
    ('control', ('name', 'kind', 'state', 'value', 'description', 'place',
                 'detail', 'disabled', 'folder', 'file', 'context',
                 'guessed', 'application')),
    ('message', ('notification', 'controller', 'text', 'typed', 'spelling',
                 'alert', 'dialog', 'live', 'monitor', 'busy', 'attention')),
    ('picture', ('icon', 'picture', 'animation')),
)


def group_names():
    return {
        # Translators: a group of voice classes in the manager.
        'control': _('Reading a control'),
        # Translators: a group of voice classes in the manager.
        'message': _('Messages and reading text'),
        # Translators: a group of voice classes in the manager.
        'picture': _('Pictures'),
    }


def group_of(tag):
    for name, members in GROUPS:
        if str(tag) in members:
            return name
    return 'control'


#: Classes this add-on adds beyond :data:`voices.VOICES`, each of them a
#: distinction that only became sayable once something could tell it.
EXTRA = {
    # A name nobody gave the control and this add-on worked out - from a
    # picture, or from a reader module. It is not the program's own word,
    # and a listener is entitled to know that: quieter and a touch slower
    # is the difference between "the button is called Save" and "the
    # button appears to say Save".
    'guessed': {'volume': -2, 'rate': -1},
    'icon': {'pitch': -4},
    'picture': {'pitch': -4, 'rate': -1},
    'animation': {'pitch': -4, 'rate': 2},
    'dialog': {'pitch': -4},
    'live': {'pitch': 1, 'rate': 1},
    # The three that are a whole message. They ship with NO voice of their
    # own on purpose: a default that put every notification into a
    # different synthesizer would be this add-on deciding something loud on
    # the user's behalf, and the point of the table is that they decide.
    'notification': {},
    'controller': {},
    'text': {},
    # Keyboard echo. A dial rather than a voice by default, and a small one:
    # it is said on every keystroke, so anything that makes it longer is
    # paid for hundreds of times an hour. Higher and quicker is what says
    # "this is what you just typed" without saying it.
    'typed': {'pitch': 3, 'rate': 2},
    'spelling': {'pitch': 2},
    # A watched area saying it has changed - a build's status line, a chat
    # behind the window you are in. It is never about the control you are
    # on, so it must not sound like one: louder and a little lower is what
    # says "this is from somewhere else" before the words do.
    'monitor': {'pitch': -2, 'volume': 2},
    # A program that has stopped answering, and a window asking for you.
    # Neither is something the user did, and both are things a sighted
    # person gets from the screen without looking at anything.
    'busy': {'pitch': -3, 'rate': -1},
    'attention': {'pitch': 2, 'volume': 2},
    # A control of a Titan application walked as a virtual window. It ships
    # with nothing of its own: the parts of it are already read in `name`,
    # `kind`, `state` and `value`, and this is here so somebody who wants
    # the whole thing marked out as "not a real window" can say so.
    'application': {},
    # What is IN a control, and what the program says ABOUT it. Both are
    # said at the plain voice by default, which is what they were before
    # there was a table - the point of listing them is that they can now
    # be told apart from the name, which is what a listener actually
    # wants from a field that has something in it.
    'value': {},
    'description': {},
}


# --------------------------------------------------------------------------- #
# The order the parts of a control are read in
# --------------------------------------------------------------------------- #
#: Every part a control's reading can be made of, and what it is. The ORDER
#: of this tuple is the default order, which is Titan Access's own and
#: NVDA's: the name, then what it is, then its state.
PARTS = ('name', 'kind', 'state', 'value', 'description', 'place')

#: Which of them are read unless the user says otherwise. All of them: a
#: reader that dropped something by default would be one that is quieter
#: than NVDA, and this add-on's whole claim is the opposite.
PARTS_ON = frozenset(PARTS)


def part_names():
    return {
        # Translators: a part of a control's reading, in the order dialog.
        'name': _('The name - "Save", "Documents"'),
        # Translators: a part of a control's reading.
        'kind': _('What it is - "button", "check box", "list item"'),
        # Translators: a part of a control's reading.
        'state': _('Its state - "checked", "selected", "expanded"'),
        # Translators: a part of a control's reading.
        'value': _('Its value - what is written in a field, where a slider '
                   'is'),
        # Translators: a part of a control's reading.
        'description': _('Its description, when the program gives one'),
        # Translators: a part of a control's reading.
        'place': _('Where it is - "3 of 10", "level 2"'),
    }


def _folder():
    try:
        import globalVars
        return globalVars.appArgs.configPath
    except Exception:                                # noqa: BLE001
        return ''


def path():
    folder = _folder()
    return os.path.join(folder, FILENAME) if folder else ''


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
def _clean(profile):
    """One stored profile, with anything that is not a field thrown away."""
    out = {}
    for key, value in (profile or {}).items():
        name = str(key)
        if name in DIALS:
            amount = _clamp(value)
            if amount:
                out[name] = amount
        elif name in NAMES:
            word = str(value or '').strip()
            if word:
                out[name] = word
    return out


def _load():
    global _overrides, _order
    with _LOCK:
        if _overrides is not None:
            return _overrides
        _overrides = {}
        _order = None
        where = path()
        if where and os.path.isfile(where):
            try:
                with open(where, encoding='utf-8') as handle:
                    data = json.load(handle)
            except Exception:                        # noqa: BLE001
                data = None
            if isinstance(data, dict):
                # **Two shapes, because the first one shipped.** The file
                # used to be nothing but classes, so a key that is a class
                # is one; the reading order arrived later and lives under a
                # reserved name. Reading the old shape as the new one is
                # what would silently lose somebody's answers on upgrade.
                stored = data.get('classes')
                _order = data.get('order') if isinstance(
                    data.get('order'), dict) else None
                if not isinstance(stored, dict):
                    stored = {key: value for key, value in data.items()
                              if key not in ('classes', 'order')}
                for tag, profile in stored.items():
                    if isinstance(profile, dict):
                        _overrides[str(tag)] = _clean(profile)
        return _overrides


def forget():
    global _overrides, _order
    with _LOCK:
        _overrides = None
        _order = None
    try:
        from . import speaking
        speaking.forget()
    except Exception:                                # noqa: BLE001
        pass


def _clamp(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-LIMIT, min(LIMIT, number))


def save():
    where = path()
    if not where:
        return False
    with _LOCK:
        data = {'classes': {tag: dict(profile)
                            for tag, profile in _load().items() if profile}}
        if _order:
            data['order'] = dict(_order)
    try:
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1,
                      sort_keys=True)
        return True
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Reading and changing one
# --------------------------------------------------------------------------- #
def defaults():
    """Every class this add-on knows, with the voice it ships with."""
    from . import voices
    found = dict(voices.VOICES)
    for tag, profile in EXTRA.items():
        found.setdefault(tag, profile)
    return found


def voice_of(tag):
    """The profile in force for one class - the user's answer, or ours.

    This is what :func:`voices.voice_of` asks, so there is one answer to
    "what does a disabled control sound like" and the manager cannot drift
    away from what is really spoken.
    """
    name = str(tag or '')
    stored = _load().get(name)
    if stored is not None:
        return dict(stored)
    return dict(defaults().get(name, {}))


def is_whole(tag):
    """Whether this class is a whole utterance, so it may name a synth."""
    return str(tag or '') in WHOLE


def synth_of(tag):
    """The synthesizer a class asks for, or '' - and only where it may.

    A class that is part of a control's reading naming a synthesizer would
    be two programs producing one sentence, so the answer there is always
    '' whatever is stored: a table that can hold a wrong answer must not
    act on it.
    """
    if not is_whole(tag):
        return ''
    return str(voice_of(tag).get('synth') or '').strip()


def changed(tag):
    """Whether the user has an answer of their own for this class."""
    return str(tag or '') in _load()


def set_voice(tag, profile):
    """The user's own answer for one class."""
    name = str(tag or '')
    if not name:
        return False
    kept = _clean(profile)
    if not is_whole(name):
        kept.pop('synth', None)
    with _LOCK:
        _load()[name] = kept
    try:
        from . import speaking
        speaking.forget()
    except Exception:                                # noqa: BLE001
        pass
    return save()


def reset(tag=None):
    """Put one class back to the default, or all of them."""
    with _LOCK:
        store = _load()
        if tag is None:
            store.clear()
        else:
            store.pop(str(tag), None)
    return save()


def described():
    """Every class, for the manager and for the status command."""
    words = meanings()
    short = labels()
    rows = []
    for _group, members in GROUPS:
        for tag in members:
            if tag not in defaults():
                continue
            rows.append({'id': tag,
                         'group': _group,
                         'meaning': words.get(tag, ''),
                         'label': short.get(tag, tag),
                         'whole': is_whole(tag),
                         'voice': voice_of(tag),
                         'default': dict(defaults().get(tag, {})),
                         'changed': changed(tag)})
    listed = {row['id'] for row in rows}
    for tag in sorted(defaults()):
        if tag not in listed:
            rows.append({'id': tag, 'group': group_of(tag),
                         'meaning': words.get(tag, ''),
                         'label': short.get(tag, tag),
                         'whole': is_whole(tag),
                         'voice': voice_of(tag),
                         'default': dict(defaults().get(tag, {})),
                         'changed': changed(tag)})
    return rows


# --------------------------------------------------------------------------- #
# The order the parts are read in
# --------------------------------------------------------------------------- #
def order():
    """``[(part, on)]`` - the parts of a control's reading, in order.

    Always every part, so the dialog has something to move and to untick,
    and so a part added by a later version of this add-on appears rather
    than being silently absent from somebody's stored answer.
    """
    _load()
    with _LOCK:
        stored = dict(_order or {})
    wanted = [str(name) for name in (stored.get('parts') or [])
              if str(name) in PARTS]
    for name in PARTS:
        if name not in wanted:
            wanted.append(name)
    off = {str(name) for name in (stored.get('off') or [])}
    return [(name, name not in off) for name in wanted]


def parts_read():
    """Just the parts that are on, in order. What the reader asks."""
    return [name for name, on in order() if on]


def set_order(rows):
    """``[(part, on)]`` from the dialog. Stored, and nothing else."""
    global _order
    _load()
    wanted, off = [], []
    for row in rows or []:
        try:
            name, on = str(row[0]), bool(row[1])
        except Exception:                            # noqa: BLE001
            continue
        if name not in PARTS or name in wanted:
            continue
        wanted.append(name)
        if not on:
            off.append(name)
    if not wanted:
        return False
    with _LOCK:
        _order = {'parts': wanted, 'off': off}
    return save()


def reset_order():
    global _order
    _load()
    with _LOCK:
        _order = None
    return save()


def order_changed():
    _load()
    with _LOCK:
        return bool(_order)


# --------------------------------------------------------------------------- #
# Hearing one
# --------------------------------------------------------------------------- #
#: What a class is tried on. Short, and the same for every class, so what
#: the listener is comparing is the voice and nothing else.
def sample_text(tag):
    words = meanings()
    # Translators: spoken when trying out a voice class. {what} is what the
    # class is for.
    return _('This is {what}').format(what=words.get(tag, tag))


def speak_sample(tag, profile=None):
    """Say the sample in this class's voice, right now.

    On the synthesizer the user really has, because that is the only thing
    that can answer whether a dial is audible - and on the one the class
    ASKS for when it asks for one, or the try button would be answering a
    question nobody asked.

    ``profile`` is what is on the dialog at this moment rather than what is
    stored, so a change is heard before it is kept, which is the whole
    point of the button.
    """
    from . import compat
    from . import voices
    wanted = dict(profile) if profile is not None else voice_of(tag)
    text = sample_text(tag)
    if is_whole(tag) and str(wanted.get('synth') or '').strip():
        try:
            from . import speaking
            if speaking.speak_with(wanted, text):
                return True
        except Exception:                            # noqa: BLE001
            pass
    speech = compat.speech
    if speech is None:
        return False
    sequence = voices.sequence([(text, wanted)])
    if not sequence:
        return False
    try:
        speech.speak(sequence)
        return True
    except Exception:                                # noqa: BLE001
        return False

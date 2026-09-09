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
WHOLE = frozenset({'notification', 'controller', 'text', 'alert', 'dialog',
                   'live'})

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
    }


#: Which group of the manager a class belongs in. A flat list of nineteen
#: classes is a list nobody finds anything in, and the three groups are
#: three different questions: what a control sounds like, what a message
#: sounds like, and what a picture sounds like.
GROUPS = (
    ('control', ('name', 'kind', 'state', 'place', 'detail', 'disabled',
                 'folder', 'file', 'context', 'guessed')),
    ('message', ('notification', 'controller', 'text', 'alert', 'dialog',
                 'live')),
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

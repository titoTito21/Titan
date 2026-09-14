# -*- coding: utf-8 -*-
"""Named voices to put on a class - Emacspeak's voice overlays.

:mod:`classes` lets somebody set four dials on each of twenty-eight
semantic classes. That is the right machinery and the wrong question to
put to a person: "what pitch, rate, volume and inflection should a
disabled control have" is four numbers nobody has an opinion about, and
the honest answer to it is usually a shrug.

Emacspeak asks a better one, and has since 1994. It defines a handful of
**voice overlays** with names that mean something - `voice-bolden`,
`voice-animate`, `voice-monotone`, `voice-smoothen`, `voice-brighten`,
`voice-lighten`, each with `-medium` and `-extra` degrees - and a mode
says "this text is bolder", not "this text is pitch 4". The overlays are
written in **Aural CSS**, which is a W3C thing: `family`,
`average-pitch`, `pitch-range`, `stress`, `richness`, each 0 to 9, so an
overlay is independent of any one synthesizer and each engine maps it onto
whatever it really has.

**The names and the idea are Emacspeak's; the numbers here are what NVDA
can actually carry**, and that is stated rather than hidden:

* `average-pitch` is NVDA's **pitch**, which every synthesizer takes.
* `pitch-range` is **inflection** - eSpeak's own word for the same thing.
  NVDA has no speech command for it, so it lands only on the classes that
  are a whole utterance (:data:`classes.WHOLE`), which is exactly what
  :mod:`voices` already knows how to do.
* `stress` becomes **volume**. It is the closest NVDA has: emphasis here
  is loudness, and there is no separate stress control on any driver.
* `richness` has **no home at all** on NVDA, and is left unmapped rather
  than being quietly folded into a dial it is not. A capability that lies
  is worse than one that is absent - the rule this add-on already applies
  to everything it reports to Titan.

`rate` is not an ACSS dimension (`speech-rate` is a separate CSS property,
not part of the voice), but it is the dial listeners notice most, so an
overlay may name it too. That is an addition and is marked as one.
"""

from . import i18n

_ = i18n.install(globals())

#: The dials an overlay may move, in this add-on's own -10..10.
DIALS = ('pitch', 'rate', 'volume', 'inflection')

#: The overlays. Emacspeak's names, its three degrees, and what each is
#: FOR - which is the part that makes them worth having over four numbers.
#:
#: Read as ACSS: `pitch` is average-pitch, `inflection` is pitch-range,
#: `volume` is stress. A dimension an overlay does not name is left where
#: the class already had it, so overlays compose with what somebody has
#: already set rather than wiping it.
OVERLAYS = (
    ('plain', {}),
    ('bolden', {'pitch': -2, 'volume': 3, 'rate': -1}),
    ('bolden-medium', {'pitch': -1, 'volume': 2}),
    ('bolden-extra', {'pitch': -4, 'volume': 5, 'rate': -2}),
    ('lighten', {'pitch': 3, 'volume': -2}),
    ('lighten-medium', {'pitch': 2, 'volume': -1}),
    ('lighten-extra', {'pitch': 6, 'volume': -4}),
    ('animate', {'inflection': 4, 'volume': 2, 'rate': 1}),
    ('animate-medium', {'inflection': 3, 'volume': 1}),
    ('animate-extra', {'inflection': 8, 'volume': 4, 'rate': 2}),
    ('monotone', {'inflection': -6, 'volume': -1}),
    ('monotone-medium', {'inflection': -4}),
    ('monotone-extra', {'inflection': -10, 'volume': -2, 'rate': -1}),
    ('smoothen', {'inflection': -2, 'rate': -2}),
    ('brighten', {'pitch': 2, 'inflection': 3, 'rate': 1}),
    ('annotate', {'pitch': 2, 'rate': 3, 'volume': -2}),
    ('indent', {'pitch': -2, 'rate': 2, 'volume': -3}),
)

NAMES = tuple(name for name, _dials in OVERLAYS)


def meanings():
    return {
        # Translators: a named voice overlay, in the voice class manager.
        'plain': _('the reader\'s own voice, unchanged'),
        # Translators: a named voice overlay.
        'bolden': _('bolder - lower and louder, the way bold text reads'),
        'bolden-medium': _('bolder, a little'),
        'bolden-extra': _('bolder, a lot'),
        # Translators: a named voice overlay.
        'lighten': _('lighter - higher and quieter, for what matters less'),
        'lighten-medium': _('lighter, a little'),
        'lighten-extra': _('lighter, a lot'),
        # Translators: a named voice overlay.
        'animate': _('livelier - more inflection, for something to act on'),
        'animate-medium': _('livelier, a little'),
        'animate-extra': _('livelier, a lot'),
        # Translators: a named voice overlay.
        'monotone': _('flatter - less inflection, for what is unavailable'),
        'monotone-medium': _('flatter, a little'),
        'monotone-extra': _('flat, with no inflection at all'),
        # Translators: a named voice overlay.
        'smoothen': _('smoother - flatter and slower'),
        # Translators: a named voice overlay.
        'brighten': _('brighter - higher and livelier'),
        # Translators: a named voice overlay.
        'annotate': _('an aside - higher, quicker, quieter'),
        # Translators: a named voice overlay.
        'indent': _('set back - lower, quicker, quieter'),
    }


def dials_of(name):
    for overlay, dials in OVERLAYS:
        if overlay == str(name):
            return dict(dials)
    return {}


def label_of(name):
    return meanings().get(str(name), str(name))


def described():
    """Every overlay, for the manager."""
    words = meanings()
    return [{'id': name, 'meaning': words.get(name, ''), 'dials': dict(dials)}
            for name, dials in OVERLAYS]


def matching(voice):
    """Which overlay a class is wearing, or '' when it is none of them.

    Read off the dials rather than remembered, so a class whose numbers
    somebody edited by hand is honestly reported as not wearing one -
    a manager that showed a name the voice no longer matched would be
    worse than one that showed nothing.
    """
    voice = voice or {}
    for name, dials in OVERLAYS:
        if all(int(voice.get(dial) or 0) == int(dials.get(dial) or 0)
               for dial in DIALS):
            return name
    return ''


def put_on(voice, name):
    """A class's voice with an overlay applied. Never changes what it is given.

    A dimension the overlay does not name is LEFT where it was, so putting
    `animate` on a class somebody has already made louder keeps it loud.
    `plain` is the exception and means what it says: every dial back to
    nothing, because "the reader's own voice" is not a preference to
    compose with.
    """
    made = dict(voice or {})
    dials = dials_of(name)
    if str(name) == 'plain':
        for dial in DIALS:
            made.pop(dial, None)
        return made
    for dial in DIALS:
        if dial in dials:
            made[dial] = max(-10, min(10, int(dials[dial])))
    return made

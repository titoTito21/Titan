# -*- coding: utf-8 -*-
"""The add-on's own settings, in NVDA's configuration.

Kept in NVDA rather than in Titan on purpose: these are answers about how
NVDA should behave, they must be readable when Titan is not running, and a
user who uninstalls Titan should not be left with a reader configured by a
program that is gone.
"""

SECTION = 'titanEnhancements'

#: Every one of these is a thing the user can be wrong about wanting, which
#: is why each is a switch rather than a decision made for them. The
#: defaults are what somebody who installed the add-on asked for.
SPEC = {
    'enabled': 'boolean(default=True)',
    'announcements': 'boolean(default=True)',
    'replaceFocus': 'boolean(default=True)',
    'position': 'boolean(default=True)',
    'positionMarker': 'boolean(default=True)',
    'prosody': 'boolean(default=True)',
    'braille': 'boolean(default=True)',
    'standDownForTitanAccess': 'boolean(default=True)',
    'announceConnection': 'boolean(default=True)',
    # Titan reaching back INTO NVDA. Reading what NVDA can see is always
    # served - it is the user's own screen, described to their own desktop,
    # and it is what makes Titan's subsystems contextual at all. CHANGING
    # NVDA is this switch, and pressing NVDA's keys is a second one, off by
    # default: a gesture is whatever the user bound it to, and in a document
    # a bound key can delete something. Titan draws exactly this line in the
    # other direction when it asks whether an external client may drive it.
    'letTitanDrive': 'boolean(default=True)',
    'letTitanPressKeys': 'boolean(default=False)',
    # Reading a control the way Titan's own reader reads one: the name, the
    # control type a little lower, the state a little higher. Only inside
    # Titan's own windows - outside them NVDA is the reader and knows far
    # more about what it is looking at than this does.
    'pitchedFocus': 'boolean(default=True)',
    # Titan's own cursor cues on every focus change, everywhere EXCEPT
    # Titan's own windows (which already play their own). Off by default: it
    # changes what the whole machine sounds like, which is not a decision to
    # make for somebody, and it needs Titan running.
    'earcons': 'boolean(default=False)',
}


def apply(section=None):
    """Push the stored answers into the live objects. Safe with no NVDA."""
    from . import channel
    from . import focus
    from . import panner
    values = section if section is not None else read()
    channel.CHANNEL.enabled = bool(values.get('announcements', True))
    channel.CHANNEL.braille_enabled = bool(values.get('braille', True))
    channel.CHANNEL.position_enabled = bool(values.get('position', True))
    channel.CHANNEL.marker_enabled = bool(values.get('positionMarker', True))
    channel.CHANNEL.prosody_enabled = bool(values.get('prosody', True))
    panner.PANNER.enabled = bool(values.get('position', True))
    if not values.get('standDownForTitanAccess', True):
        focus.stand_down(False)
    return values


def read():
    """The stored answers, or the defaults when NVDA is not here."""
    defaults = {name: spec.endswith('default=True)')
                for name, spec in SPEC.items()}
    try:
        import config
        stored = config.conf[SECTION]
        return {name: bool(stored[name]) for name in SPEC}
    except Exception:                                # noqa: BLE001
        return defaults


def write(values):
    try:
        import config
        for name in SPEC:
            if name in values:
                config.conf[SECTION][name] = bool(values[name])
        return True
    except Exception:                                # noqa: BLE001
        return False


def register():
    """Add the section to NVDA's config spec. Idempotent."""
    try:
        import config
        config.conf.spec[SECTION] = dict(SPEC)
        return True
    except Exception:                                # noqa: BLE001
        return False

# -*- coding: utf-8 -*-
"""The add-on's ``configSpec``, answered out of this reader's own store.

In NVDA the shared modules keep their switches in the add-on's own
configuration spec and ask ``configSpec.read()`` for them. Titan Access
has a settings store of its own with a ``Reader`` section, and
``switchboard`` was written to ask the spec first and the store second -
but three shared modules ask the spec DIRECTLY (``perProgram._global``,
``windowKind.wanted``, ``localOcr._recognizer``), and with no module of
that name here each of them raised ``ImportError`` inside a call that
looked like a switch being read: a per-program switch was never applied,
a window's kind was never said. This is the shim: the same two names,
``read`` and ``write``, over the ``Reader`` section, with the add-on's own
defaults so an unasked switch answers what it answers in NVDA.
"""

SECTION = 'Reader'

#: The add-on's defaults, for the switches the shared modules read.
DEFAULTS = {
    'enabled': True, 'announcements': True, 'replaceFocus': True,
    'position': True, 'positionAs': 'pitch', 'positionMarker': True,
    'positionEverywhere': False, 'prosody': True, 'braille': True,
    'pitchedFocus': True, 'pitchedEverywhere': False,
    'appSemantics': True, 'windowsSemantics': True, 'readerModules': True,
    'dialogKinds': True, 'windowKinds': True, 'graphicKinds': True,
    'autoLabel': False, 'liveRegions': True, 'liveStatusBars': True,
    'surfaceReading': False, 'ocrTier': 'local', 'drawnText': True,
    'agentLink': False, 'agentFromGuest': False, 'agentToken': '',
    'localOcrLanguage': '', 'busyState': True, 'attentionState': True,
    'menuLeaving': True, 'trackpad': False, 'speechOrigins': True,
    'monitors': True, 'auditoryIcons': True,
    'auditoryIconsEverywhere': False, 'reportContext': True,
    'soundScheme': True, 'journal': True, 'guestCursor': False,
    'earcons': False,
}


def _store():
    from ..settings_store import get_settings
    return get_settings()


def defaults():
    return dict(DEFAULTS)


def read():
    """Every known switch as this reader holds it (the default when it
    was never set)."""
    out = dict(DEFAULTS)
    try:
        store = _store()
    except Exception:                                # noqa: BLE001
        return out
    for name, default in DEFAULTS.items():
        try:
            if isinstance(default, bool):
                out[name] = bool(store.get_bool(SECTION, name, default))
            else:
                found = store.get(SECTION, name, default)
                out[name] = found if found not in (None, '') else default
        except Exception:                            # noqa: BLE001
            continue
    return out


def write(values):
    """Set some switches and save the store."""
    try:
        store = _store()
    except Exception:                                # noqa: BLE001
        return False
    for name, value in (values or {}).items():
        try:
            if isinstance(value, bool):
                store.set_bool(SECTION, str(name), value)
            else:
                store.set(SECTION, str(name), str(value))
        except Exception:                            # noqa: BLE001
            continue
    try:
        store.save()
    except Exception:                                # noqa: BLE001
        return False
    return True


def choices(name):
    """The options of a choice switch, as the add-on spells them."""
    return {'positionAs': ('pitch', 'pan', 'both'),
            'ocrTier': ('local', 'ai', 'both')}.get(str(name), ())


def forget():
    """Nothing is cached here; the store is read each time."""

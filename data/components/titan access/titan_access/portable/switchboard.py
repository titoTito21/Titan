# -*- coding: utf-8 -*-
"""One answer to "is this switched on", for the modules two readers share.

The shared modules ask about their own switches - are the auditory icons
on, is the sound scheme, may the dialog kind be said - and in NVDA the
answer is in the add-on's own `configSpec`. Titan Access has no
`configSpec`; it has a settings store of its own, with a `Reader` section.
Every shared module used to ask `configSpec` directly and answer "yes" on
any machine without it, which made every one of those switches invisible
to Titan Access's own settings page. This asks the reader that is really
underneath: the add-on's spec first, Titan Access's store second, and the
default when neither is there.

The names are the add-on's own (`auditoryIcons`, `soundScheme`,
`dialogKinds`, `busyState`, `attentionState`, `trackpad`), so one setting
means one thing in both readers' pages.
"""

#: Titan Access's section for these. The keys are the add-on's names.
SECTION = 'Reader'


def read(name, default=True):
    """The switch called ``name``, from whichever reader is underneath."""
    name = str(name or '')
    try:
        from . import configSpec
        values = configSpec.read()
        if name in values:
            return bool(values.get(name))
    except Exception:                                # noqa: BLE001
        pass
    try:
        from ..settings_store import get_settings
        return bool(get_settings().get_bool(SECTION, name, bool(default)))
    except Exception:                                # noqa: BLE001
        pass
    return bool(default)


def value(name, default=None):
    """A setting that is not a switch - a text, a number, a choice."""
    name = str(name or '')
    try:
        from . import configSpec
        values = configSpec.read()
        if name in values:
            return values.get(name)
    except Exception:                                # noqa: BLE001
        pass
    try:
        from ..settings_store import get_settings
        found = get_settings().get(SECTION, name, None)
        if found not in (None, ''):
            return found
    except Exception:                                # noqa: BLE001
        pass
    return default


def write(name, value):
    """Set a setting, wherever the reader underneath keeps it.

    NVDA's spec through `configSpec.write`, Titan Access's store here.
    Answers whether anything was written.
    """
    try:
        from . import configSpec
        configSpec.write({str(name): value})
        return True
    except Exception:                                # noqa: BLE001
        pass
    try:
        from ..settings_store import get_settings
        store = get_settings()
        if isinstance(value, bool):
            store.set_bool(SECTION, str(name), value)
        else:
            store.set(SECTION, str(name), str(value))
        store.save()
        return True
    except Exception:                                # noqa: BLE001
        return False

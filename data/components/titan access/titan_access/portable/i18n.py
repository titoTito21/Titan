# -*- coding: utf-8 -*-
"""``_`` for the modules this reader shares with the NVDA add-on.

The shared modules are byte-identical in both trees, so each of them says
``from . import i18n`` and ``_ = i18n.install(globals())`` - the add-on's
own spelling. This is the other end of that: the same two names, answering
through Titan Access's own catalogue instead of NVDA's.

**A missing translation is never a missing string.** If the catalogue is
not loaded, or has not got this one, the English source is what is said -
which is what gettext does anyway and what keeps a shared module working
in a tree that has not translated it yet.
"""


def install(namespace):
    """Put ``_`` into ``namespace`` (pass ``globals()``) and return it."""
    translate = None
    try:
        from .. import localization
        for name in ('translate', 'gettext', 'get_text', '_'):
            found = getattr(localization, name, None)
            if callable(found):
                translate = found
                break
    except Exception:                                # noqa: BLE001
        translate = None
    if not callable(translate):
        def translate(text):
            return text
    namespace['_'] = translate
    return translate

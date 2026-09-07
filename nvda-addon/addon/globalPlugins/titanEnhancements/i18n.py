# -*- coding: utf-8 -*-
"""``_`` in every module, whether or not NVDA is the one importing us.

``addonHandler.initTranslation()`` is NVDA's own way of installing ``_``,
and it is what makes this add-on's catalogue
(``locale/<lang>/LC_MESSAGES/nvda.po``) reach these strings. It exists only
inside NVDA, and the tests import these modules without it - so a module
calling it directly could not be tested, and one that did not call it would
ship untranslated. ``install(globals())`` answers both.

**It installs into the CALLER's globals**, by walking one frame back
(``sys._getframe().f_back``). That is why this cannot simply be a
``from .i18n import _``: called from here, the frame it finds is this
module's, so the translation lands here and the module that asked for it
gets nothing. So it is called here on purpose, and the ``_`` that appears in
*these* globals is then copied into the namespace that asked.
"""


def install(namespace):
    """Put ``_`` into ``namespace`` (pass ``globals()``). Never raises."""
    translate = None
    try:
        import addonHandler
        addonHandler.initTranslation()
        # initTranslation walked back one frame and installed it here.
        translate = globals().get('_')
    except Exception:                                # noqa: BLE001
        translate = None
    if not callable(translate):
        try:
            import builtins
            candidate = getattr(builtins, '_', None)
            translate = candidate if callable(candidate) else None
        except Exception:                            # noqa: BLE001
            translate = None
    if not callable(translate):
        def translate(text):
            return text
    namespace['_'] = translate
    return translate

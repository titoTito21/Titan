# -*- coding: utf-8 -*-
"""The component's own catalogue (domain ``polyglot``).

Used in Titan's process and in the host process alike, so the language is
asked of Titan's settings when they can be read and of ``TITAN_LANGUAGE``
(which the launcher sets) when they cannot.
"""

import gettext
import os

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'languages')
_translation = None


def language():
    value = os.environ.get('TITAN_LANGUAGE', '')
    if not value:
        try:
            from src.settings.settings import get_setting
            value = get_setting('language', 'pl')
        except Exception:
            value = 'pl'
    return (value or 'pl').split('_')[0].split('.')[0]


def _(text):
    global _translation
    if _translation is None:
        try:
            _translation = gettext.translation(
                'polyglot', localedir=_DIR, languages=[language()],
                fallback=True)
        except Exception:
            _translation = gettext.NullTranslations()
    return _translation.gettext(text)

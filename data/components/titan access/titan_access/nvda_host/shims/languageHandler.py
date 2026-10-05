# -*- coding: utf-8 -*-
"""NVDA's `languageHandler`: the language is Titan's."""


def getLanguage():
    try:
        from titan_access import localization
        lang = getattr(localization, 'current_language', None)
        lang = lang() if callable(lang) else lang
        if lang:
            return str(lang).replace('-', '_')
    except Exception:                                # noqa: BLE001
        pass
    try:
        from src.settings.settings import get_setting
        return str(get_setting('language', 'pl') or 'pl')
    except Exception:                                # noqa: BLE001
        return 'pl'


def getWindowsLanguage():
    return getLanguage()


def normalizeLanguage(lang):
    return str(lang or '').replace('-', '_').lower() if lang else lang


def getLanguageDescription(language):
    """The language's name, in that language where Python's locale tables
    know it; ``None`` for one nobody knows (NVDA answers None too, and
    drivers fill in their own name then)."""
    code = str(language or '')
    names = {'pl': 'Polski', 'en': 'English', 'de': 'Deutsch',
             'fr': 'Français', 'es': 'Español', 'ru': 'Русский',
             'it': 'Italiano', 'cs': 'Čeština', 'sk': 'Slovenčina',
             'uk': 'Українська', 'pt': 'Português', 'nl': 'Nederlands',
             'sv': 'Svenska', 'fi': 'Suomi', 'da': 'Dansk', 'nb': 'Norsk',
             'hu': 'Magyar', 'tr': 'Türkçe', 'ja': '日本語', 'zh': '中文',
             'ko': '한국어', 'ar': 'العربية', 'he': 'עברית', 'el': 'Ελληνικά'}
    base = names.get(code.replace('-', '_').split('_')[0])
    if base is None:
        return None
    if '_' in code.replace('-', '_'):
        return '%s (%s)' % (base, code.replace('-', '_').split('_', 1)[1])
    return base


def setLanguage(lang):
    return True


def localeNameToWindowsLCID(localeName):
    return 0


LCID_NONE = 0


from . import permissive as _permissive  # noqa: E402
_permissive(globals())

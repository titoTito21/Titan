# -*- coding: utf-8 -*-
"""Localization for Titan Access.

Port of the C# ``Localization/LocalizationManager`` plus the phonetic / special
character tables from ``ScreenReaderEngine.cs``. Strings live in
``locale/<lang>.json`` (copied verbatim from the C# project, flat key -> string
with C#-style ``{0}`` placeholders). Language ("pl"/"en") comes from the
settings store so the standalone reader and the TCE dialog agree.

Usage::

    from titan_access.localization import L, set_language, role_label, state_label
    L("engine.windowNamed", title)        # positional {0}
    role_label("button"), state_label("checked")
"""

import json
import os
import threading

_LOCALE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locale")

_lock = threading.RLock()
_lang = "pl"
_strings = {}
_fallback = {}          # English, always loaded as a fallback for missing keys


def _load_json(lang):
    path = os.path.join(_LOCALE_DIR, f"{lang}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[TitanAccess] locale load failed ({lang}): {e}")
        return {}


def set_language(lang):
    """Select 'pl' or 'en' (defaults to 'pl' for anything else)."""
    global _lang, _strings, _fallback
    lang = (lang or "pl").strip().lower()
    if lang not in ("pl", "en"):
        lang = "pl"
    with _lock:
        _lang = lang
        _strings = _load_json(lang)
        _fallback = _strings if lang == "en" else _load_json("en")


def get_language():
    return _lang


def detect_tce_language():
    """Resolve the locale to use, following the configured TCE language.

    Inside the launcher we honour TCE's own ``language`` setting (the user wants
    Titan Access to match it). Standalone, we fall back to the screen reader's
    own ``Language`` setting. Only 'pl'/'en' ship as locales, so any other TCE
    language maps to 'en' as the international fallback (Polish stays 'pl').
    """
    lang = None
    # 1) Follow TCE's configured language when running inside the launcher.
    try:
        from src.settings.settings import get_setting
        lang = get_setting("language", "")
    except Exception:
        lang = None
    # 2) Standalone fallback: our own settings store.
    if not lang:
        try:
            from titan_access.settings_store import get_settings
            lang = get_settings().language
        except Exception:
            lang = "pl"
    lang = (lang or "pl").strip().lower()
    if lang.startswith("pl"):
        return "pl"
    if lang.startswith("en"):
        return "en"
    return "en"


def sync_with_tce():
    """(Re)load the locale that matches the current TCE / standalone language."""
    set_language(detect_tce_language())


def L(key, *args):
    """Translate ``key`` and apply C#-style positional formatting with ``args``."""
    with _lock:
        template = _strings.get(key)
        if template is None:
            template = _fallback.get(key, key)
    if args:
        try:
            return template.format(*args)
        except Exception:
            return template
    return template


# Initialise following the TCE language (falls back to the saved/standalone one).
try:
    set_language(detect_tce_language())
except Exception:
    set_language("pl")


# --------------------------------------------------------------------------- #
# Role labels — map canonical role keys (contracts.py) to localised names.
# Backed by the json ctrlType.* keys with a built-in fallback so it works even
# before the json is finalised.
# --------------------------------------------------------------------------- #
_ROLE_TO_JSON = {
    "button": "ctrlType.button",
    "split_button": "ctrlType.splitButton",
    "edit": "ctrlType.edit",
    "password": "ctrlType.edit",
    "document": "ctrlType.document",
    "checkbox": "ctrlType.checkBox",
    "radio": "ctrlType.radioButton",
    "combobox": "ctrlType.comboBox",
    "list": "ctrlType.list",
    "listitem": "ctrlType.listItem",
    "tree": "ctrlType.tree",
    "treeitem": "ctrlType.treeItem",
    "menu": "ctrlType.menu",
    "menubar": "ctrlType.menuBar",
    "menuitem": "ctrlType.menuItem",
    "tab": "ctrlType.tabItem",
    "tabcontrol": "ctrlType.tab",
    "slider": "ctrlType.slider",
    "spinner": "ctrlType.spinner",
    "progressbar": "ctrlType.progressBar",
    "scrollbar": "ctrlType.scrollBar",
    "link": "ctrlType.hyperlink",
    "text": "ctrlType.text",
    "heading": "ctrlType.header",
    "image": "ctrlType.image",
    "table": "ctrlType.table",
    "row": "ctrlType.dataItem",
    "cell": "ctrlType.dataItem",
    "toolbar": "ctrlType.toolBar",
    "statusbar": "ctrlType.statusBar",
    "group": "ctrlType.group",
    "dialog": "dialog.dialog",
    "window": "ctrlType.window",
    "pane": "ctrlType.pane",
    "separator": "ctrlType.separator",
    "grid": "ctrlType.dataGrid",
    "griditem": "ctrlType.dataItem",
    "unknown": "element.unknown",
}

_STATE_TO_JSON = {
    "checked": "state.checked",
    "unchecked": "state.unchecked",
    "partially_checked": "state.partiallyChecked",
    "expanded": "state.expanded",
    "collapsed": "state.collapsed",
    "selected": "state.selected",
    "unavailable": "state.disabled",
    "readonly": "state.readonly",
    "offscreen": "state.offscreen",
}


def role_label(role):
    return L(_ROLE_TO_JSON.get(role, "element.unknown"))


def state_label(state):
    key = _STATE_TO_JSON.get(state)
    return L(key) if key else state


# --------------------------------------------------------------------------- #
# Special characters + phonetic alphabet (ported from ScreenReaderEngine.cs)
# --------------------------------------------------------------------------- #
SPECIAL_CHARS_PL = {
    ' ': "spacja", '\n': "nowa linia", '\r': "", '\t': "tabulator", '\b': "",
    '.': "kropka", ',': "przecinek", ';': "średnik", ':': "dwukropek",
    '!': "wykrzyknik", '?': "pytajnik", '-': "minus", '_': "podkreślenie",
    '=': "równa się", '+': "plus", '*': "gwiazdka", '/': "ukośnik",
    '\\': "odwrotny ukośnik", '@': "małpa", '#': "hash", '$': "dolar",
    '%': "procent", '^': "daszek", '&': "ampersand",
    '(': "nawias otwierający", ')': "nawias zamykający",
    '[': "nawias kwadratowy otwierający", ']': "nawias kwadratowy zamykający",
    '{': "nawias klamrowy otwierający", '}': "nawias klamrowy zamykający",
    '<': "mniejszy niż", '>': "większy niż", '\'': "apostrof", '"': "cudzysłów",
    '`': "grawis", '~': "tylda", '|': "kreska pionowa",
}

SPECIAL_CHARS_EN = {
    ' ': "space", '\n': "new line", '\r': "", '\t': "tab", '\b': "",
    '.': "dot", ',': "comma", ';': "semicolon", ':': "colon",
    '!': "exclamation mark", '?': "question mark", '-': "minus", '_': "underscore",
    '=': "equals", '+': "plus", '*': "asterisk", '/': "slash",
    '\\': "backslash", '@': "at", '#': "hash", '$': "dollar",
    '%': "percent", '^': "caret", '&': "ampersand",
    '(': "left parenthesis", ')': "right parenthesis",
    '[': "left bracket", ']': "right bracket",
    '{': "left brace", '}': "right brace",
    '<': "less than", '>': "greater than", '\'': "apostrophe", '"': "quote",
    '`': "grave", '~': "tilde", '|': "vertical bar",
}

PHONETIC_PL = {
    'a': "Adam", 'ą': "Aniela", 'b': "Barbara", 'c': "Cezary", 'ć': "Celina",
    'd': "Dorota", 'e': "Edward", 'ę': "Ewa", 'f': "Franciszek", 'g': "Genowefa",
    'h': "Henryk", 'i': "Irena", 'j': "Jadwiga", 'k': "Karol", 'l': "Leon",
    'ł': "Łucja", 'm': "Maria", 'n': "Natalia", 'ń': "Nikodem", 'o': "Olga",
    'ó': "Oskar", 'p': "Paweł", 'q': "Québec", 'r': "Roman", 's': "Sylwia",
    'ś': "Śpiewak", 't': "Tomasz", 'u': "Urszula", 'v': "Violetta",
    'w': "Władysław", 'x': "Ksawery", 'y': "Yxilon", 'z': "Zofia",
    'ź': "Źrebię", 'ż': "Żaba",
}

PHONETIC_EN = {
    'a': "Alpha", 'ą': "Aniela", 'b': "Bravo", 'c': "Charlie", 'ć': "Celina",
    'd': "Delta", 'e': "Echo", 'ę': "Ewa", 'f': "Foxtrot", 'g': "Golf",
    'h': "Hotel", 'i': "India", 'j': "Juliet", 'k': "Kilo", 'l': "Lima",
    'ł': "Łucja", 'm': "Mike", 'n': "November", 'ń': "Nikodem", 'o': "Oscar",
    'ó': "Oskar", 'p': "Papa", 'q': "Quebec", 'r': "Romeo", 's': "Sierra",
    'ś': "Śpiewak", 't': "Tango", 'u': "Uniform", 'v': "Victor",
    'w': "Whiskey", 'x': "X-ray", 'y': "Yankee", 'z': "Zulu",
    'ź': "Źrebię", 'ż': "Żaba",
}


def _special_chars():
    return SPECIAL_CHARS_EN if _lang == "en" else SPECIAL_CHARS_PL


def _phonetic():
    return PHONETIC_EN if _lang == "en" else PHONETIC_PL


def phonetic_letter(ch):
    """Phonetic name for a single letter (current language)."""
    lower = ch.lower()
    phon = _phonetic().get(lower, ch)
    if ch.isupper():
        return L("char.upperPhonetic", phon)
    return phon


def character_announcement(ch, use_phonetic=False):
    """Spoken form of a single character (port of GetCharacterAnnouncement)."""
    special = _special_chars().get(ch)
    if special is not None:
        return special
    if use_phonetic and ch.isalpha():
        return phonetic_letter(ch)
    if 'A' <= ch <= 'Z':
        return L("char.upper", ch)
    return ch

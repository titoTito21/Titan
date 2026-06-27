# -*- coding: utf-8 -*-
"""Control hints for Titan Access.

Python port of the C# ``Hints/HintManager``. A hint is a short "how to use this"
sentence (e.g. *"Press Space to check or uncheck"*) spoken after the user has
rested on a control, and only when the ``General/SpeakHints`` setting is on.

The C# manager keyed its hints off the raw UIA ``ControlType`` programmatic name;
here we key off the canonical Titan Access role vocabulary (see
:mod:`titan_access.contracts`), since the provider has already mapped control
types to roles by the time we describe an element. The actual hint strings live
in ``locale/*.json`` under the ``hint.*`` keys (already present) and are resolved
through :func:`titan_access.localization.L`.

The timing side of the C# ``HintManager`` (a 2-second debounce timer) belongs to
the engine; this module is the pure role -> hint-text lookup.
"""

from typing import Optional

from titan_access.localization import L


# Canonical role key (contracts.ROLE_*) -> locale hint key. Mirrors the C#
# ``ControlHintKeys`` dictionary, re-expressed against our role vocabulary.
_ROLE_TO_HINT = {
    "button": "hint.button",
    "split_button": "hint.button",
    "checkbox": "hint.checkBox",
    "radio": "hint.radioButton",
    "edit": "hint.edit",
    "password": "hint.edit",
    "document": "hint.edit",
    "text": "hint.text",

    "list": "hint.list",
    "listitem": "hint.listItem",
    "tree": "hint.tree",
    "treeitem": "hint.treeItem",

    "combobox": "hint.comboBox",
    "menu": "hint.menu",
    "menuitem": "hint.menuItem",
    "menubar": "hint.menuBar",

    "tabcontrol": "hint.tab",
    "tab": "hint.tabItem",

    "toolbar": "hint.toolBar",
    "statusbar": "hint.statusBar",

    "slider": "hint.slider",
    "spinner": "hint.spinner",

    "link": "hint.hyperlink",
    "image": "hint.image",

    "table": "hint.table",
    "grid": "hint.dataGrid",

    "window": "hint.window",
    "pane": "hint.pane",
    "group": "hint.group",

    "scrollbar": "hint.scrollBar",
    "heading": "hint.header",
    "progressbar": "hint.progressBar",
    "separator": "hint.separator",
}


def hint_for(role: str, settings) -> Optional[str]:
    """Return the localized hint for ``role``, or ``None``.

    Returns ``None`` when hints are disabled (``settings.speak_hints`` is off) or
    when the role has no associated hint.
    """
    try:
        if not settings.speak_hints:
            return None
    except Exception:
        # If the settings object is unusable, behave as if hints are off.
        return None
    key = _ROLE_TO_HINT.get(role)
    return L(key) if key else None


def has_hint(role: str) -> bool:
    """Whether ``role`` has an associated hint (ignores the SpeakHints setting)."""
    return role in _ROLE_TO_HINT

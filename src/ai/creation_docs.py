"""Titan add-on documentation for the AI creation kit.

Grounds the generator on the REAL, authoritative Titan programming guides that
ship in ``data/docu/programming_guide/`` (the same guides a human developer
reads), plus a compact cross-cutting **core API reference** covering the shared
surfaces every add-on kind touches: accessing Titan modules, speech/TTS,
sound cues, notifications, settings, internationalisation, and the three
interface modes (GUI, Invisible UI, Klango).

Injecting the kind's full guide into the system prompt is what stops the model
from inventing wrong manifest filenames or wrong entry-point function names --
the guides are the ground truth for each kind's file layout and required API.
"""

import os

from src import platform_utils

# Kind id -> the English programming guide that documents it. Kept English on
# purpose: generated code and its user-facing strings must be English (see
# CLAUDE.md), and the English guides are the authoritative reference.
KIND_GUIDE = {
    'app':              'app_creation_guide_en.md',
    'game':             'game_creation_guide_en.md',
    'component':        'component_creation_guide_en.md',
    'launcher':         'launcher_creation_guide_en.md',
    'im_module':        'titanim_module_guide_en.md',
    'gamepad_mode':     'gamepad_mode_guide_en.md',
    'tts_engine':       'tts_engine_guide_en.md',
    'widget':           'widget_creation_guide_en.md',
    'statusbar_applet': 'statusbar_applet_guide_en.md',
    'language':         None,
}

# Guides are ~13-32 KB each; include them in full but keep a generous safety cap
# so a corrupt/huge file can never blow the request.
_MAX_GUIDE_CHARS = 60000

_GUIDE_SUBDIR = os.path.join('data', 'docu', 'programming_guide')


# --------------------------------------------------------------------------- #
# Core, cross-cutting API reference (applies to EVERY kind)
# --------------------------------------------------------------------------- #
# Hand-written from the real modules so it never drifts into invented APIs.
# Signatures verified against src/accessibility/messages.py, src/titan_core/
# sound.py, src/titan_core/translation.py, src/ui/invisibleui.py and
# src/system/klangomode.py.
CORE_API_REFERENCE = """\
# Titan Core API Reference (shared by every add-on kind)

Titan (TCE) runs the same add-on across three interface modes. Your code must
never assume a particular one is active:
- GUI      - the visual wxPython desktop (src/ui/gui.py, class TitanApp).
- IUI      - the Invisible UI, a non-visual interface for screen-reader users
             (src/ui/invisibleui.py, class InvisibleUI).
- Klango   - an audio-game style mode (src/system/klangomode.py).

## Accessing Titan modules from an add-on
Add the TCE root to sys.path, then import from the `src.*` package (this is the
one import style that works both in development and in the compiled build):

    import os, sys
    ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
    TCE_ROOT = os.path.abspath(os.path.join(ADDON_DIR, '..', '..', '..'))
    if TCE_ROOT not in sys.path:
        sys.path.insert(0, TCE_ROOT)
    # (the number of '..' depends on how deep the add-on subdir is - match the
    #  reference example and the kind's guide exactly)

## Speech and screen-reader output
    from src.accessibility.messages import speak_sr_only
    speak_sr_only("Message", interrupt=True)   # speak only when a reader is active

For Klango's positional speech:
    from src.system.klangomode import speak_klango
    speak_klango("Message", position=0.0, pitch_offset=0, interrupt=True)

## Sound cues (audio theme aware)
    from src.titan_core.sound import (play_sound, play_focus_sound,
        play_select_sound, play_error_sound)
    play_sound("core/focus.ogg", pan=None, elevation=0.0)  # path relative to sfx/<theme>/
    play_focus_sound()   # cursor moved
    play_select_sound()  # item activated
    play_error_sound()   # error

## Notifications
    from src.system.notifications import speak_notification
    speak_notification("Text", "info")   # levels: 'info', 'warning', 'error'

## Settings (per-user JSON config)
    from src.settings.settings import get_setting, set_setting
    value = get_setting('key', 'default', section='your_section')
    set_setting('key', 'value', section='your_section')

## Internationalisation (gettext)
Every user-facing string MUST go through _() and MUST be written in English.
Never put emojis in user-facing text. Provide a Polish translation alongside.
The exact _() wiring differs per kind:
- Statusbar applets and widgets: _() is auto-injected by the manager from the
  add-on's own languages/ folder - do NOT import or configure gettext yourself.
- Apps/games/components/launchers: set up gettext as the kind's guide shows
  (usually a small translation.py that calls set_language()).
    from src.titan_core.translation import set_language
    _ = set_language(get_setting('language', 'pl'))

## Registering an Invisible-UI view (components/launchers that add a screen)
    invisible_ui.register_view(view_id, label, elements_func, action_func,
                               sound="core/focus.ogg", position='after_network')

## Golden rules
- Never crash the host: wrap risky work in try/except and degrade gracefully.
- Keep hot callbacks fast (e.g. a statusbar's get_statusbar_item_text() must
  return a string in under 2 seconds and must never raise).
- Follow the kind-specific guide below for the EXACT required filenames,
  manifest keys and entry-point function names - they are authoritative.
"""


def guide_path(kind_id):
    """Absolute path to the bundled English guide for ``kind_id`` (or None)."""
    fn = KIND_GUIDE.get(kind_id)
    if not fn:
        return None
    for cand in platform_utils.iter_resource_paths(
            os.path.join(_GUIDE_SUBDIR, fn), prefer_user=False):
        if os.path.isfile(cand):
            return cand
    # Fall back to the plain resource path even if it does not exist yet.
    return platform_utils.get_resource_path(os.path.join(_GUIDE_SUBDIR, fn))


def load_guide(kind_id):
    """Return the full text of the kind's programming guide, or '' if missing."""
    path = guide_path(kind_id)
    if not path or not os.path.isfile(path):
        return ''
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            text = fh.read(_MAX_GUIDE_CHARS + 1)
    except OSError:
        return ''
    if len(text) > _MAX_GUIDE_CHARS:
        text = text[:_MAX_GUIDE_CHARS] + "\n\n... (guide truncated)\n"
    return text


def build_docs_block(kind_id):
    """The documentation section for a kind: the shared core reference plus the
    kind's own full programming guide. Returned as a single string ready to drop
    into the system prompt (empty pieces are skipped)."""
    parts = [CORE_API_REFERENCE]
    guide = load_guide(kind_id)
    if guide:
        parts.append("# Kind-specific programming guide (authoritative)\n\n"
                     + guide)
    return "\n\n".join(parts)

# -*- coding: utf-8 -*-
"""What Titan Access offers to Titan, to a macro and to the AI.

The screen reader is the one part of Titan that can answer "what is on the
screen right now" for a program that is not Titan - it already builds a flat
document out of whatever a window will tell it (UI Automation, MSAA, the raw
child windows, and the AI's reading of a picture as a last resort). Until now
that was only reachable by pressing keys. These actions expose it, so a Titan
Script can write

    set what = titan_access.read_screen kind="button"
    titan_access.click_element text="Save"

and the AI can answer a question about an application it has no other way of
seeing.

Two decisions worth stating:

* **Reading does not require the reader to be running.** The document is built
  straight from :mod:`titan_access.virtual_buffer`, so "read the screen" works
  with Titan Access switched off. Only the actions that SPEAK need the engine.
* **The AI tier is never used unless asked for.** ``use_ai=true`` is an explicit
  parameter on the actions that could reach it, because that tier sends a
  picture of the user's screen to their provider. Everything else answers from
  Windows' own accessibility, for free and offline.

Handlers run on Titan's GUI thread (that is how the in-process transport calls
them), never raise, and answer with a sentence or with ``fails(reason)``.
"""

import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_LIB = os.path.join(_HERE, "lib")
if os.path.isdir(_LIB) and _LIB not in sys.path:
    sys.path.insert(0, _LIB)

try:
    from src.titan_core.actions import fails
except Exception:                       # Titan not importable - actions unused
    def fails(reason):
        return reason


# --------------------------------------------------------------------------- #
# The document the reading actions share
# --------------------------------------------------------------------------- #
# list_elements says "3. Save, button" and click_element is then asked for "3",
# so both must be looking at the same document. Kept briefly, per window: long
# enough for one exchange, short enough that nobody acts on a screen that has
# moved on.
_DOC_TTL = 30.0
_doc_lock = threading.Lock()
_last_doc = None                        # (hwnd, built_at, VirtualDocument)

# What a caller may ask for by name. Maps onto quick navigation, so the words
# here are the same ones browse mode navigates by.
_KINDS = {
    "all": (), "any": (),
    "heading": ("heading",),
    "link": ("link",),
    "button": ("button", "split_button"),
    "edit": ("edit", "password"), "field": ("edit", "password"),
    "checkbox": ("checkbox",),
    "radio": ("radio",),
    "combobox": ("combobox",),
    "list": ("list", "listbox"),
    "listitem": ("listitem", "treeitem", "menuitem"),
    "menuitem": ("menuitem",),
    "tab": ("tab",),
    "table": ("table", "grid"),
    "cell": ("cell", "griditem"),
    "image": ("image",),
    "text": ("text",),
    "slider": ("slider", "spinner"),
    "form": ("edit", "password", "combobox", "checkbox", "radio", "button",
             "slider", "spinner"),
    "landmark": ("__landmark__",),
}

_KIND_NAMES = sorted(_KINDS)


def _buffer():
    from titan_access import virtual_buffer as vbuf
    return vbuf


def _foreground():
    return _buffer().foreground_hwnd()


def _ocr_allowed():
    """Whether the AI tier may be used at all (Titan's switch plus the reader's)."""
    try:
        from titan_access import ocr_assist
        from titan_access.settings_store import get_settings
        return bool(ocr_assist.available(get_settings()))
    except Exception:
        return False


def _document(window=0, refresh=False, use_ai=False):
    """The virtual document for a window, reused within :data:`_DOC_TTL`."""
    global _last_doc
    vbuf = _buffer()
    hwnd = int(window or 0) or _foreground()
    if not hwnd:
        return None
    with _doc_lock:
        cached = _last_doc
    if (not refresh and cached is not None and cached[0] == hwnd
            and (time.time() - cached[1]) < _DOC_TTL):
        return cached[2]
    doc = vbuf.build_for_window(hwnd, allow_ocr=bool(use_ai) and _ocr_allowed())
    with _doc_lock:
        _last_doc = (hwnd, time.time(), doc)
    return doc


def _matching(doc, kind="", contains=""):
    """The document's entries filtered by type and by what they say."""
    if doc is None:
        return []
    key = (kind or "all").strip().lower()
    roles = _KINDS.get(key)
    if roles is None:
        return None                     # unknown kind - the caller reports it
    needle = (contains or "").strip().casefold()
    out = []
    for node in doc.nodes:
        if roles == ("__landmark__",):
            if not getattr(node, "landmark_start", False):
                continue
        elif roles and node.role not in roles:
            continue
        if needle and needle not in _line(node).casefold():
            continue
        out.append(node)
    return out


def _line(node) -> str:
    """One entry as a person would read it: what it says, then what it is."""
    from titan_access import localization as loc
    text = (node.name or "").strip()
    value = (node.value or "").strip()
    if value and value != text:
        text = f"{text} {value}".strip()
    try:
        role = loc.role_label(node.role)
    except Exception:
        role = node.role
    parts = [p for p in (text, role) if p]
    if node.is_heading and node.level:
        parts.append(f"level {node.level}")
    for state in node.states:
        try:
            parts.append(loc.state_label(state))
        except Exception:
            parts.append(str(state))
    landmark = getattr(node, "landmark", "")
    if landmark and getattr(node, "landmark_start", False):
        parts.append(f"in {landmark}")
    return ", ".join(parts)


def _source_note(doc) -> str:
    return {
        "uia": "read through UI Automation",
        "ia2": "read through the browser's accessibility interface",
        "msaa": "read through the legacy accessibility interface",
        "win32": "read from the window's own controls",
        "ocr": "read by the AI from a picture of the window",
    }.get(getattr(doc, "source", ""), "")


def _engine(require_running=True):
    """The live reader engine, or None."""
    try:
        from titan_access.engine import TitanAccessEngine, get_engine
        if require_running and TitanAccessEngine.instance is None:
            return None
        return get_engine()
    except Exception:
        return None


def _bool(value, default=True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off", "")


# --------------------------------------------------------------------------- #
# Reading what is on the screen
# --------------------------------------------------------------------------- #
def action_read_screen(window=0, kind="all", limit=0, use_ai=False,
                       refresh=False):
    """Everything the foreground window says, as one readable block."""
    doc = _document(window, refresh=_bool(refresh, False), use_ai=_bool(use_ai, False))
    if doc is None or not doc.nodes:
        return fails("Nothing could be read from that window. Windows reports "
                     "no accessible content in it; pass use_ai=true to have "
                     "the AI read a picture of it instead.")
    nodes = _matching(doc, kind)
    if nodes is None:
        return fails(f"'{kind}' is not something to look for. Try one of: "
                     + ", ".join(_KIND_NAMES) + ".")
    if not nodes:
        return f"There is no {kind} in '{doc.title or 'this window'}'."
    try:
        cap = int(limit or 0)
    except (TypeError, ValueError):
        cap = 0
    shown = nodes[:cap] if cap > 0 else nodes
    lines = [f"{i + 1}. {_line(n)}" for i, n in enumerate(shown)]
    head = f"'{doc.title or 'window'}', {len(nodes)} items"
    note = _source_note(doc)
    if note:
        head = f"{head} ({note})"
    if cap > 0 and len(nodes) > cap:
        lines.append(f"... and {len(nodes) - cap} more.")
    return head + ":\n" + "\n".join(lines)


def action_list_elements(kind="all", contains="", window=0, limit=50,
                         use_ai=False, refresh=False):
    """The window's elements, numbered, so one of them can be pressed.

    The numbering is what :func:`action_click_element` takes, and both look at
    the same reading (see :data:`_DOC_TTL`), so "the third button" means the
    same thing to both.
    """
    if not str(contains or "").strip():
        return action_read_screen(window=window, kind=kind, limit=limit,
                                  use_ai=use_ai, refresh=refresh)
    doc = _document(window, refresh=_bool(refresh, False),
                    use_ai=_bool(use_ai, False))
    nodes = _matching(doc, kind, contains)
    if nodes is None:
        return fails(f"'{kind}' is not something to look for. Try one of: "
                     + ", ".join(_KIND_NAMES) + ".")
    if not nodes:
        return f"Nothing matching '{contains}' is on the screen."
    try:
        cap = int(limit or 50)
    except (TypeError, ValueError):
        cap = 50
    lines = [f"{i + 1}. {_line(n)}" for i, n in enumerate(nodes[:cap])]
    return f"{len(nodes)} matching '{contains}':\n" + "\n".join(lines)


def action_find_element(text, kind="all", window=0, use_ai=False):
    """Whether something is on the screen, and what it is."""
    if not str(text or "").strip():
        return fails("Say what to look for.")
    doc = _document(window, use_ai=_bool(use_ai, False))
    nodes = _matching(doc, kind, text)
    if nodes is None:
        return fails(f"'{kind}' is not something to look for. Try one of: "
                     + ", ".join(_KIND_NAMES) + ".")
    if not nodes:
        return f"There is no '{text}' on the screen."
    if len(nodes) == 1:
        return f"Yes: {_line(nodes[0])}."
    return (f"{len(nodes)} of them: "
            + "; ".join(_line(n) for n in nodes[:8]) + ".")


def action_click_element(text="", kind="all", number=0, window=0):
    """Press whatever the screen calls *text* (or the numbered entry).

    The same press browse mode performs on Enter, so it works whichever tier
    read the window - a UI Automation invoke, an MSAA default action, a
    ``BM_CLICK`` to an old control, or a click at the point the AI reported.
    """
    vbuf = _buffer()
    doc = _document(window)
    if doc is None or not doc.nodes:
        return fails("Nothing readable is on the screen to press.")
    node = None
    try:
        index = int(number or 0)
    except (TypeError, ValueError):
        index = 0
    if index > 0:
        pool = _matching(doc, kind)
        if pool is None:
            return fails(f"'{kind}' is not something to look for.")
        if index > len(pool):
            return fails(f"There is no item number {index}; there are "
                         f"{len(pool)}.")
        node = pool[index - 1]
    else:
        if not str(text or "").strip():
            return fails("Say what to press, either by its text or by its "
                         "number in the list.")
        node = _best_match(doc, kind, text)
        if node is None:
            return fails(f"There is no '{text}' on the screen to press.")
    if not vbuf.activate(node):
        return fails(f"'{_line(node)}' could not be pressed.")
    # What was pressed almost always changes the window, so the document that
    # described it is no longer true.
    _forget_document()
    return f"Pressed {_line(node)}."


def _best_match(doc, kind, text):
    """An exact name first, then the one that merely contains the words."""
    nodes = _matching(doc, kind) or []
    needle = str(text).strip().casefold()
    for node in nodes:
        if (node.name or "").strip().casefold() == needle:
            return node
    for node in nodes:
        if needle in _line(node).casefold():
            return node
    return None


def _forget_document():
    global _last_doc
    with _doc_lock:
        _last_doc = None


def action_read_focused():
    """What has the keyboard focus right now."""
    engine = _engine()
    obj = getattr(engine, "current_object", None) if engine is not None else None
    if obj is None:
        obj = _focused_without_engine()
    if obj is None:
        return "Nothing has the keyboard focus, or it cannot be read."
    from titan_access import localization as loc
    parts = [(obj.name or "").strip()]
    try:
        parts.append(loc.role_label(obj.role))
    except Exception:
        parts.append(obj.role)
    if (obj.value or "").strip() and obj.value != obj.name:
        parts.append(obj.value)
    for state in sorted(obj.states or ()):
        try:
            parts.append(loc.state_label(state))
        except Exception:
            parts.append(str(state))
    return ", ".join(p for p in parts if p) or "An unnamed element has focus."


def _focused_without_engine():
    """The focused element even when the reader itself is not running."""
    try:
        from titan_access import uia_focus
        return uia_focus.get_provider().get_focused_object()
    except Exception:
        return None


def action_window_title():
    """The title of the window in front."""
    title = _buffer().window_text(_foreground())
    return title or "The window in front has no title."


def action_document_info():
    """How big the current reading is and where it came from."""
    doc = _document()
    if doc is None or not doc.nodes:
        return "Nothing readable is on the screen."
    note = _source_note(doc) or "read from the window"
    return (f"'{doc.title or 'window'}': {len(doc.nodes)} items, {note}.")


def action_refresh():
    """Read the window again, from scratch."""
    _forget_document()
    doc = _document(refresh=True)
    if doc is None or not doc.nodes:
        return fails("Nothing could be read from the window.")
    return f"Read again: {len(doc.nodes)} items."


# --------------------------------------------------------------------------- #
# Speaking
# --------------------------------------------------------------------------- #
def action_say(text, interrupt=True):
    """Have the reader speak something."""
    if not str(text or "").strip():
        return fails("There is nothing to say.")
    engine = _engine(require_running=False)
    speak = getattr(engine, "speak", None) if engine is not None else None
    if not callable(speak):
        return fails("The screen reader is not available to speak.")
    try:
        speak(text, interrupt=_bool(interrupt, True))
    except Exception as e:
        return fails(f"The screen reader could not speak: {e}")
    return f"Said: {text}"


def action_stop_speech():
    """Silence the reader immediately."""
    engine = _engine()
    if engine is None:
        return "The screen reader is not running."
    try:
        engine.action_stop_speaking()
    except Exception as e:
        return fails(f"Could not stop the speech: {e}")
    return "Stopped speaking."


def action_speak_screen(kind="all", use_ai=False):
    """Read the window out loud, rather than returning it as text."""
    body = action_read_screen(kind=kind, use_ai=use_ai)
    if isinstance(body, str) and body.startswith("There is no"):
        return action_say(body)
    return action_say(str(body).replace("\n", ". "))


# --------------------------------------------------------------------------- #
# Document / scan / browse mode
# --------------------------------------------------------------------------- #
def _browse():
    engine = _engine()
    return getattr(engine, "browse", None) if engine is not None else None


def action_scan_mode(state="toggle"):
    """Turn scan mode on or off: the application read as a document."""
    browse = _browse()
    if browse is None:
        return fails("The screen reader is not running, so scan mode has "
                     "nothing to scan with. Turn it on first "
                     "(titan_access.set_enabled).")
    want = str(state or "toggle").strip().lower()
    active = bool(getattr(browse, "scan_active", False))
    if want in ("on", "true", "1", "yes") and active:
        return "Scan mode is already on."
    if want in ("off", "false", "0", "no") and not active:
        return "Scan mode is already off."
    try:
        browse.toggle_scan()
    except Exception as e:
        return fails(f"Could not change scan mode: {e}")
    return "Scan mode is on." if not active else "Scan mode is off."


def action_browse_mode(state="toggle"):
    """Switch a web page between browse mode and focus (form) mode."""
    browse = _browse()
    if browse is None:
        return fails("The screen reader is not running.")
    if not bool(getattr(browse, "is_web", False)):
        return fails("The window in front is not a web page. Use "
                     "titan_access.scan_mode for an ordinary application.")
    want = str(state or "toggle").strip().lower()
    in_focus = bool(getattr(browse, "pass_through", False))
    if want in ("browse",) and not in_focus:
        return "Already in browse mode."
    if want in ("focus", "form") and in_focus:
        return "Already in focus mode."
    try:
        browse.toggle_pass_through()
    except Exception as e:
        return fails(f"Could not change the mode: {e}")
    return "Focus mode." if not in_focus else "Browse mode."


def action_say_all():
    """Read the page or the window continuously, from the cursor."""
    engine = _engine()
    if engine is None:
        return fails("The screen reader is not running.")
    try:
        engine.action_say_all()
    except Exception as e:
        return fails(f"Could not start reading: {e}")
    return "Reading."


def action_go_to(kind="heading", backward=False):
    """Move the reading cursor to the next element of a type (quick navigation)."""
    browse = _browse()
    if browse is None:
        return fails("The screen reader is not running.")
    letter = {
        "heading": "h", "link": "k", "button": "b", "edit": "e", "field": "e",
        "checkbox": "x", "radio": "r", "combobox": "c", "list": "l",
        "listitem": "i", "table": "t", "image": "g", "landmark": "d",
        "form": "f", "separator": "s", "text": "p", "frame": "m",
    }.get(str(kind or "").strip().lower())
    if letter is None:
        return fails(f"'{kind}' is not a type to jump to. Try one of: "
                     "heading, link, button, edit, checkbox, radio, combobox, "
                     "list, listitem, table, image, landmark, form.")
    try:
        moved = browse.quick_nav_by_char(letter, backward=_bool(backward, False))
    except Exception as e:
        return fails(f"Could not move: {e}")
    if not moved:
        return f"There is no document to move through."
    return f"Moved to the {'previous' if _bool(backward, False) else 'next'} {kind}."


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
# The settings a caller is likely to name, by the words they would use. Each is
# (attribute on the settings store, what it accepts).
_SETTINGS = {
    "rate": ("rate", "a number, normally -10 to 10"),
    "volume": ("volume", "0 to 100"),
    "pitch": ("pitch", "a number, normally -10 to 10"),
    "voice": ("voice", "the name of a voice"),
    "synthesizer": ("synthesizer", "the name of a speech engine"),
    "language": ("language", "pl or en"),
    "scan mode": ("scan_mode", "on or off"),
    "ai reading": ("ai_ocr", "on or off"),
    "ai labels": ("ai_ocr_labels", "on or off"),
    "progress bars": ("progress_mode",
                      "Off, Speech, Sound, or SpeechAndSound"),
    "keyboard echo": ("keyboard_echo",
                      "None, Characters, Words, or CharactersAndWords"),
    "phonetic letters": ("phonetic_letters", "on or off"),
    "speak hints": ("speak_hints", "on or off"),
    "mute outside titan": ("mute_outside_tce", "on or off"),
    "virtual screen": ("virtual_screen", "on or off"),
    "welcome message": ("welcome_message", "what to say at startup"),
}


def _settings_store():
    from titan_access.settings_store import get_settings
    return get_settings()


def _setting_key(name):
    wanted = str(name or "").strip().lower().replace("_", " ")
    if wanted in _SETTINGS:
        return wanted
    for key, (attribute, _accepts) in _SETTINGS.items():
        if attribute == wanted.replace(" ", "_"):
            return key
    return None


def action_list_settings():
    """Every reader setting that can be read or changed by name."""
    store = _settings_store()
    lines = []
    for key in sorted(_SETTINGS):
        attribute, accepts = _SETTINGS[key]
        try:
            value = getattr(store, attribute)
        except Exception:
            value = "?"
        lines.append(f"{key}: {value} ({accepts})")
    return "Titan Access settings:\n" + "\n".join(lines)


def action_get_setting(name):
    """One reader setting."""
    key = _setting_key(name)
    if key is None:
        return fails(f"There is no reader setting called '{name}'. "
                     "titan_access.list_settings shows them all.")
    attribute, accepts = _SETTINGS[key]
    try:
        return f"{key} is {getattr(_settings_store(), attribute)} ({accepts})."
    except Exception as e:
        return fails(f"Could not read '{key}': {e}")


def action_set_setting(name, value):
    """Change one reader setting and save it."""
    key = _setting_key(name)
    if key is None:
        return fails(f"There is no reader setting called '{name}'. "
                     "titan_access.list_settings shows them all.")
    attribute, accepts = _SETTINGS[key]
    store = _settings_store()
    try:
        current = getattr(store, attribute)
    except Exception:
        current = None
    try:
        setattr(store, attribute, _coerce(value, current))
        store.save()
    except Exception as e:
        return fails(f"Could not set '{key}' to '{value}' ({accepts}): {e}")
    # A running reader holds its own copy of the settings; make it re-read them
    # so the change is heard now rather than after a restart.
    engine = _engine()
    if engine is not None:
        try:
            engine.settings.load()
        except Exception:
            pass
    return f"{key} is now {getattr(store, attribute)}."


def _coerce(value, current):
    """Give a setting the type it already has, so 'on' reaches a boolean."""
    if isinstance(current, bool):
        return _bool(value, True)
    if isinstance(current, int) and not isinstance(current, bool):
        return int(str(value).strip())
    return value


# --------------------------------------------------------------------------- #
# Reader state (kept here so init.py holds only the component lifecycle)
# --------------------------------------------------------------------------- #
_entry_module = None


def bind(module):
    """Told by ``init.py`` which module owns the reader's lifecycle.

    The component loader may import that file under any name, so it hands
    itself over rather than being looked up.
    """
    global _entry_module
    _entry_module = module


def _component():
    if _entry_module is not None:
        return _entry_module
    import init as component            # standalone / test import
    return component


def action_get_state():
    """Say whether the Titan screen reader is running."""
    return ("The Titan screen reader is running." if _component().is_active()
            else "The Titan screen reader is off.")


def action_set_enabled(enabled=True):
    """Turn the Titan screen reader on or off."""
    component = _component()
    want = _bool(enabled, True)
    if want == component.is_active():
        return "The Titan screen reader is already " + ("on." if want else "off.")
    try:
        component.start_reader() if want else component.stop_reader()
    except Exception as e:
        return fails(f"Could not change the screen reader: {e}")
    return ("The Titan screen reader is now on." if want
            else "The Titan screen reader is now off.")


def action_toggle():
    """Turn the Titan screen reader on if it is off, or off if it is on."""
    try:
        _component().toggle_reader()
    except Exception as e:
        return fails(f"Could not toggle the screen reader: {e}")
    return action_get_state()


# --------------------------------------------------------------------------- #
# The declaration
# --------------------------------------------------------------------------- #
_KIND_ENUM = _KIND_NAMES
_WINDOW_PARAM = {'type': 'integer',
                 'description': "A window handle; leave it out for the window "
                                "in front."}
_USE_AI_PARAM = {'type': 'boolean',
                 'description': "Let the AI read a picture of the window when "
                                "Windows reports nothing accessible in it. Off "
                                "by default: it sends a picture of the screen "
                                "to the configured AI provider."}

TITAN_ACTIONS = [
    # -- reading -------------------------------------------------------- #
    {'name': 'read_screen',
     'summary': "Read everything the window in front says, as text. Works "
                "even when the screen reader itself is switched off.",
     'params': {
         'kind': {'type': 'string', 'enum': _KIND_ENUM,
                  'description': "Only elements of this type."},
         'limit': {'type': 'integer',
                   'description': "At most this many items (0 = all)."},
         'window': _WINDOW_PARAM,
         'use_ai': _USE_AI_PARAM,
         'refresh': {'type': 'boolean',
                     'description': "Read the window again instead of reusing "
                                    "the last reading."},
     },
     'timeout': 90,
     'run': action_read_screen},
    {'name': 'list_elements',
     'summary': "The window's elements, numbered, optionally only those whose "
                "text contains something.",
     'params': {
         'kind': {'type': 'string', 'enum': _KIND_ENUM,
                  'description': "Only elements of this type."},
         'contains': {'type': 'string',
                      'description': "Only elements whose text contains this."},
         'limit': {'type': 'integer', 'description': "At most this many."},
         'window': _WINDOW_PARAM,
         'use_ai': _USE_AI_PARAM,
         'refresh': {'type': 'boolean', 'description': "Read the window again."},
     },
     'timeout': 90,
     'run': action_list_elements},
    {'name': 'find_element',
     'summary': "Whether something is on the screen, and what it is.",
     'params': {
         'text': {'type': 'string', 'required': True,
                  'description': "What to look for."},
         'kind': {'type': 'string', 'enum': _KIND_ENUM,
                  'description': "Only elements of this type."},
         'window': _WINDOW_PARAM,
         'use_ai': _USE_AI_PARAM,
     },
     'timeout': 90,
     'run': action_find_element},
    {'name': 'click_element',
     'summary': "Press a control in the window in front, by what it says or by "
                "its number from list_elements.",
     'params': {
         'text': {'type': 'string', 'description': "What the control says."},
         'number': {'type': 'integer',
                    'description': "Its number in the list instead."},
         'kind': {'type': 'string', 'enum': _KIND_ENUM,
                  'description': "Only elements of this type."},
         'window': _WINDOW_PARAM,
     },
     'risk': 'confirm',
     'run': action_click_element},
    {'name': 'read_focused',
     'summary': "What has the keyboard focus right now.",
     'run': action_read_focused},
    {'name': 'window_title',
     'summary': "The title of the window in front.",
     'run': action_window_title},
    {'name': 'document_info',
     'summary': "How many items the current reading has and where it came from.",
     'timeout': 90,
     'run': action_document_info},
    {'name': 'refresh',
     'summary': "Read the window in front again, from scratch.",
     'timeout': 90,
     'run': action_refresh},

    # -- speaking ------------------------------------------------------- #
    {'name': 'say',
     'summary': "Have the Titan screen reader speak a message.",
     'params': {
         'text': {'type': 'string', 'required': True,
                  'description': "What to say."},
         'interrupt': {'type': 'boolean',
                       'description': "Cut off whatever is being said (the "
                                      "default), or queue behind it."},
     },
     'run': action_say},
    {'name': 'speak_screen',
     'summary': "Read the window in front out loud.",
     'params': {'kind': {'type': 'string', 'enum': _KIND_ENUM,
                         'description': "Only elements of this type."},
                'use_ai': _USE_AI_PARAM},
     'timeout': 90,
     'run': action_speak_screen},
    {'name': 'stop_speech',
     'summary': "Silence the screen reader immediately.",
     'run': action_stop_speech},

    # -- modes ---------------------------------------------------------- #
    {'name': 'scan_mode',
     'summary': "Turn scan mode on or off - the application in front read as a "
                "document the arrow keys walk.",
     'params': {'state': {'type': 'string', 'enum': ['on', 'off', 'toggle'],
                          'description': "on, off, or toggle."}},
     'run': action_scan_mode},
    {'name': 'browse_mode',
     'summary': "Switch a web page between browse mode and focus (form) mode.",
     'params': {'state': {'type': 'string',
                          'enum': ['browse', 'focus', 'toggle'],
                          'description': "browse, focus, or toggle."}},
     'run': action_browse_mode},
    {'name': 'say_all',
     'summary': "Read the page or the window continuously, from the cursor.",
     'run': action_say_all},
    {'name': 'go_to',
     'summary': "Move the reading cursor to the next element of a type "
                "(quick navigation, as the single letters do).",
     'params': {
         'kind': {'type': 'string',
                  'enum': ['heading', 'link', 'button', 'edit', 'checkbox',
                           'radio', 'combobox', 'list', 'listitem', 'table',
                           'image', 'landmark', 'form', 'separator', 'text',
                           'frame'],
                  'description': "What to jump to."},
         'backward': {'type': 'boolean',
                      'description': "Jump to the previous one instead."},
     },
     'run': action_go_to},

    # -- the reader itself ---------------------------------------------- #
    {'name': 'get_state',
     'summary': "Say whether the Titan screen reader is running.",
     'run': action_get_state},
    {'name': 'set_enabled',
     'summary': "Turn the Titan screen reader on or off.",
     'params': {'enabled': {'type': 'boolean',
                            'description': "True to turn it on."}},
     'risk': 'confirm', 'run': action_set_enabled},
    {'name': 'toggle',
     'summary': "Turn the Titan screen reader on if it is off, or off if it is "
                "on.",
     'risk': 'confirm', 'run': action_toggle},

    # -- settings -------------------------------------------------------- #
    {'name': 'list_settings',
     'summary': "Every Titan Access setting that can be read or changed by "
                "name, with what it accepts.",
     'run': action_list_settings},
    {'name': 'get_setting',
     'summary': "One Titan Access setting.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "For example 'rate' or 'scan mode'."}},
     'run': action_get_setting},
    {'name': 'set_setting',
     'summary': "Change one Titan Access setting and save it.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "For example 'rate' or 'scan mode'."},
                'value': {'type': 'string', 'required': True,
                          'description': "The new value."}},
     'risk': 'confirm', 'run': action_set_setting},
]

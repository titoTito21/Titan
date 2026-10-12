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
    "statusbar": ("statusbar",),
    "toolbar": ("toolbar",),
    "dialog": ("dialog", "alert"),
    "progressbar": ("progressbar",),
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
# The reader's own OCR - nothing of NVDA, the add-on or Titan's AI
# --------------------------------------------------------------------------- #
def action_read_text(window=0, engine="auto"):
    """Read a window's text off its picture, with this reader's own
    recognisers: Windows' built-in OCR or the local model carried in the
    component's own folder. Nothing leaves the machine."""
    from titan_access import local_model, windows_ocr
    hwnd = int(window or 0) or _foreground()
    engine = str(engine or "auto").strip().lower()
    found = None
    if engine in ("auto", "windows"):
        found = windows_ocr.read_window(hwnd)
        if not found.get("ok") and engine == "auto":
            found = None
    if found is None:
        found = local_model.read_window(hwnd)
    if not found.get("ok"):
        return fails(found.get("text") or "Nothing could be read.")
    lines = []
    for one in found.get("lines") or []:
        if isinstance(one, list):
            lines.append(" ".join(w.get("text", "") for w in one))
        else:
            lines.append(str(one.get("text") or ""))
    lines = [line for line in lines if line.strip()]
    if not lines:
        return "The window was read and holds no text."
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# What an application script does with a program (JAWS, NVDA and SuperNova
# scripts do these all the time): put the keyboard on a control, say a
# control without going there, click a hot spot, wait for something to
# appear, read a corner of the window, watch a control for changes.
# --------------------------------------------------------------------------- #
def _say_here(text):
    """Say ``text`` in the reader's voice, when a reader is running."""
    engine = _engine()
    if engine is None or not text:
        return
    try:
        engine.speak(str(text), interrupt=False)
    except Exception:
        pass


def action_focus_element(text="", kind="all", window=0):
    """Put the keyboard focus on a control of the window in front, found
    by what it says (JAWS's SetFocus / NVDA's obj.setFocus)."""
    if not str(text or "").strip():
        return fails("Say which control to move to.")
    doc = _document(window, refresh=True)
    if doc is None or not doc.nodes:
        return fails("Nothing readable is on the screen.")
    if _matching(doc, kind) is None:
        return fails(f"'{kind}' is not something to look for.")
    node = _best_match(doc, kind, text)
    if node is None:
        return fails(f"There is no '{text}' on the screen.")
    if not _buffer().focus_node(node):
        return fails(f"The focus could not be put on '{_line(node)}'.")
    return f"The focus is on {_line(node)}."


def action_read_control(text="", kind="all", window=0, speak=True):
    """What a control says, without moving the focus there (JAWS's
    SayWindow): spoken in the reader's voice and handed back, so a script
    can `set total = titan_access.read_control text="Total"`."""
    if not str(text or "").strip() and (kind or "all") == "all":
        return fails("Say which control to read, by its text or its type.")
    doc = _document(window, refresh=True)
    if doc is None or not doc.nodes:
        return fails("Nothing readable is on the screen.")
    pool = _matching(doc, kind)
    if pool is None:
        return fails(f"'{kind}' is not something to look for.")
    node = _best_match(doc, kind, text) if str(text or "").strip() \
        else (pool[0] if pool else None)
    if node is None:
        return fails(f"There is no '{text or kind}' on the screen.")
    line = _line(node)
    if _bool(speak, True):
        _say_here(line)
    return line


def control_text(conditions, window=0):
    """The text of the first control of the window in front whose name,
    role or value meet ``conditions`` (``[(field, op, wanted)]``, a TA
    script's own), or None when there is none. For `when change`."""
    doc = _document(window, refresh=True)
    if doc is None:
        return None
    from titan_access import ta_scripts
    for node in doc.nodes:
        values = {"name": node.name or "", "role": node.role or "",
                  "value": node.value or "", "text": node.text or ""}
        try:
            from titan_access import localization as loc
            values["role_key"] = node.role or ""
            values["role"] = loc.role_label(node.role)
        except Exception:
            pass
        if ta_scripts._matches(conditions, values):
            return node.text or ""
    return None


def _window_origin(window=0):
    """The top left corner of the window in front (or ``window``)."""
    vbuf = _buffer()
    hwnd = int(window or 0) or _foreground()
    rect = vbuf.window_rect(hwnd) if hwnd else ()
    if rect and len(rect) == 4:
        return int(rect[0]), int(rect[1])
    return 0, 0


def _click_point(x, y, button="left", clicks=1):
    """A real mouse click at a screen point; the pointer is put back."""
    button = str(button or "left").lower()
    if sys.platform.startswith("win"):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        before = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(before))
        down, up = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010),
                    "middle": (0x0020, 0x0040)}.get(button, (0x0002, 0x0004))
        try:
            user32.SetCursorPos(int(x), int(y))
            for _ in range(max(1, int(clicks))):
                user32.mouse_event(down, 0, 0, 0, 0)
                user32.mouse_event(up, 0, 0, 0, 0)
                time.sleep(0.03)
        finally:
            user32.SetCursorPos(before.x, before.y)
        return True
    import shutil
    import subprocess
    if not shutil.which("xdotool"):
        return False
    number = {"left": "1", "middle": "2", "right": "3"}.get(button, "1")
    subprocess.run(["xdotool", "mousemove", "--sync", str(int(x)), str(int(y)),
                    "click", "--repeat", str(max(1, int(clicks))), number,
                    "mousemove", "restore"], timeout=5,
                   capture_output=True)
    return True


def action_click_at(x=0, y=0, button="left", clicks=1, relative="window",
                    window=0):
    """Click a hot spot - a place in the window rather than a control
    (JAWS's HotSpot Clicker, SuperNova's hotspots). ``x``/``y`` are pixels
    from the window's top left corner, or from the screen's with
    ``relative="screen"``."""
    try:
        x, y = int(x), int(y)
        clicks = max(1, min(3, int(clicks or 1)))
    except (TypeError, ValueError):
        return fails("A hot spot is two whole numbers of pixels: x and y.")
    if str(button or "left").lower() not in ("left", "right", "middle"):
        return fails("The button is left, right or middle.")
    if str(relative or "window").lower() != "screen":
        left, top = _window_origin(window)
        x, y = x + left, y + top
    if not _click_point(x, y, button, clicks):
        return fails("This machine has nothing to click with (xdotool).")
    _forget_document()
    return f"Clicked at {x}, {y}."


def action_wait_for(window_title="", text="", kind="all", seconds=10):
    """Wait until a window whose title contains ``window_title`` is in
    front, or a control saying ``text`` is on the screen - polled four
    times a second, at most ``seconds``."""
    if not str(window_title or "").strip() and not str(text or "").strip():
        return fails("Say what to wait for: a window title or a control.")
    try:
        limit = max(0.2, min(120.0, float(seconds or 10)))
    except (TypeError, ValueError):
        limit = 10.0
    vbuf = _buffer()
    deadline = time.time() + limit
    wanted_title = str(window_title or "").strip().casefold()
    while True:
        if wanted_title:
            hwnd = _foreground()
            title = vbuf.window_text(hwnd) if hwnd else ""
            if wanted_title in str(title or "").casefold():
                return f"'{title}' is in front."
        else:
            doc = _document(refresh=True)
            node = _best_match(doc, kind, text) if doc is not None else None
            if node is not None:
                return f"{_line(node)} is on the screen."
        if time.time() >= deadline:
            return fails(f"'{window_title or text}' did not appear in "
                         f"{limit:g} seconds.")
        time.sleep(0.25)


def action_read_region(x=0, y=0, width=0, height=0, window=0, speak=True):
    """Read part of the window in front off its picture, with the reader's
    own OCR - for a program that draws its text (a status area, a score).
    Pixels from the window's top left corner."""
    from titan_access import windows_ocr
    try:
        x, y, width, height = int(x), int(y), int(width), int(height)
    except (TypeError, ValueError):
        return fails("A region is four whole numbers: x, y, width, height.")
    if width <= 0 or height <= 0:
        return fails("A region needs a width and a height.")
    hwnd = int(window or 0) or _foreground()
    left, top = _window_origin(hwnd)
    found = windows_ocr.read_rect(left + x, top + y, width, height, hwnd=hwnd)
    if not found.get("ok"):
        return fails(found.get("text") or "Nothing could be read there.")
    lines = []
    for one in found.get("lines") or []:
        if isinstance(one, list):
            lines.append(" ".join(w.get("text", "") for w in one))
        else:
            lines.append(str(one.get("text") or ""))
    text = " ".join(line for line in lines if line.strip()).strip()
    if not text:
        return "There is no text there."
    if _bool(speak, True):
        _say_here(text)
    return text


# --------------------------------------------------------------------------- #
# The user's own scripts (accessibility/scripts/*.tas, Titan Script)
# --------------------------------------------------------------------------- #
def _scripts():
    from titan_access import ta_scripts
    return ta_scripts


def action_list_scripts():
    """The user's Titan Access scripts and when each one runs."""
    ta = _scripts()
    found = ta.load()
    if not found:
        return "There are no scripts. Put .tas files in %s." % ta.folder()
    lines = []
    for one in found:
        when = ", ".join(
            ('key ' + t['spec']) if t['kind'] == 'key' else t['kind']
            for t in one['triggers']) or "never"
        line = "%s: %s" % (one['name'], when)
        if one['problems']:
            line += " - does not run: " + "; ".join(one['problems'])
        lines.append(line)
    return "\n".join(lines)


def action_run_script(name):
    """Run one of the user's scripts now."""
    ta = _scripts()
    ta.load()
    script = ta.by_name(name)
    if script is None:
        return fails("There is no script called '%s'." % name)
    ok, why = ta.run(script)
    return ("Running %s." % script['name']) if ok else fails(why)


def action_check_script(name):
    """Check one script without running it: its triggers and its Titan
    Script."""
    ta = _scripts()
    ta.load()
    script = ta.by_name(name)
    if script is None:
        return fails("There is no script called '%s'." % name)
    with open(script['path'], 'r', encoding='utf-8-sig') as handle:
        problems = ta.check(handle.read())
    return "No problems." if not problems else "\n".join(problems)


def action_reload_scripts():
    """Read the scripts folder again and rebind the scripts' keys."""
    ta = _scripts()
    engine = _engine(require_running=True)
    found = ta.bind(engine) if engine is not None else ta.load()
    return "%d scripts loaded from %s." % (len(found), ta.folder())


def action_scripts_folder():
    """Where the user's scripts live."""
    return _scripts().folder()


# --------------------------------------------------------------------------- #
# NVDA add-ons installed in Titan Access (titan_access.nvda_host)
# --------------------------------------------------------------------------- #
def action_nvda_addons():
    """The NVDA add-ons installed in Titan Access."""
    from titan_access import nvda_host
    found = nvda_host.installed()
    if not found:
        return ("No NVDA add-ons are installed in Titan Access (%s)."
                % nvda_host.folder())
    lines = []
    for one in found:
        lines.append("%s %s - %s; %s; %s" % (
            one['name'], one['version'], one['summary'],
            ", ".join(one['kinds']) or "data",
            "running" if one['enabled'] else "switched off"))
    errors = nvda_host.report().get('errors') or {}
    if errors:
        lines.append("Problems: " + "; ".join(
            "%s: %s" % (key, value) for key, value in errors.items()))
    return "\n".join(lines)


def action_install_nvda_addon(path):
    """Install a .nvda-addon file (or an add-on folder) into Titan Access."""
    from titan_access import nvda_host
    ok, said = nvda_host.install(path)
    if not ok:
        return fails(said)
    if nvda_host.is_loaded():
        nvda_host.reload()
    return "%s installed in Titan Access." % said


def action_set_nvda_addon(name, enabled=True):
    """Switch an NVDA add-on on or off in Titan Access."""
    from titan_access import nvda_host
    if not nvda_host.set_enabled(name, _bool(enabled)):
        return fails("There is no NVDA add-on called '%s'." % name)
    if nvda_host.is_loaded():
        nvda_host.reload()
    return "%s is %s." % (name, "on" if _bool(enabled) else "off")


def action_migrate_nvda_addons():
    """Copy NVDA's own add-ons into Titan Access."""
    from titan_access import nvda_host
    done = nvda_host.migrate()
    if nvda_host.is_loaded():
        nvda_host.reload()
    if not done:
        return "NVDA has no add-ons to migrate."
    return "\n".join("%s: %s" % (name, "migrated" if ok else why)
                     for name, ok, why in done)


def action_external_synthesizers():
    """The synthesizers the NVDA add-ons bring (external synthesis)."""
    from titan_access import nvda_host
    found = nvda_host.synthesizers()
    if not found:
        return "No NVDA add-on brings a synthesizer."
    return "\n".join("nvda:%s - %s (%s)%s" % (
        one['name'], one['description'], one['addon'],
        " - does not load: " + one['error'] if one['error'] else "")
        for one in found)


def action_ocr_status():
    """Which of this reader's own recognisers can read here."""
    from titan_access import local_model, windows_ocr
    ok, why = windows_ocr.available()
    model = local_model.report()
    parts = ["Windows OCR: " + ("ready, language %s"
                                % (windows_ocr.report().get("language")
                                   or "?") if ok else "not here (%s)" % why)]
    if model.get("installed"):
        parts.append("Local model: installed in %s" % model.get("libraries"))
    else:
        parts.append("Local model: not installed (%s)" % model.get("why"))
    return ". ".join(parts) + "."


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


# Every setting of the reader is in `settings_schema`: the settings page,
# the walked settings and these actions are all built from it, so a setting
# added there (Browsing the web, UWP apps...) is reachable here with no
# change. The words above are kept as aliases for the names macros already
# use.
_ALIASES = {
    "rate": ("Speech", "Rate"), "volume": ("Speech", "Volume"),
    "pitch": ("Speech", "Pitch"), "voice": ("Speech", "Voice"),
    "synthesizer": ("Speech", "Synthesizer"),
    "speech system": ("Speech", "OwnVoice"),
    "scan mode": ("Reader", "ScanMode"), "ai reading": ("Reader", "UseAiOcr"),
    "ai labels": ("Reader", "AiOcrLabels"),
    "progress bars": ("Reader", "ProgressMode"),
    "keyboard echo": ("TextEditing", "KeyboardEcho"),
    "phonetic letters": ("TextEditing", "PhoneticLetters"),
    "speak hints": ("General", "SpeakHints"),
    "mute outside titan": ("General", "MuteOutsideTCE"),
    "virtual screen": ("General", "VirtualScreen"),
    "welcome message": ("General", "WelcomeMessage"),
    "read page on load": ("Browse", "SayAllOnPageLoad"),
    "page summary": ("Browse", "PageSummary"),
    "landmark start and end": ("Browse", "LandmarkStartEnd"),
    "icons": ("UWP", "Glyphs"),
    "name icon buttons": ("UWP", "NameIconControls"),
    "virtual lists": ("UWP", "VirtualLists"),
    "new list rows": ("Reader", "liveLists"),
}

#: The other way round: the English word for a setting, shown in the list
#: so a caller reading a Polish label still has a name to ask for.
_ALIAS_OF = {target: word for word, target in _ALIASES.items()}


def _schema():
    from titan_access import settings_schema
    return settings_schema


def _walk():
    from titan_access import settings_walk
    return settings_walk


def _L(key, *args):
    try:
        from titan_access.localization import L
        return L(key, *args)
    except Exception:
        return key


def _walk_entry(entry):
    return (entry.section, entry.key, entry.label, entry.kind, entry.extra,
            entry.default)


def _norm(text):
    return " ".join(str(text or "").lower().replace("_", " ")
                    .replace("/", " / ").split())


def _find_entry(name):
    """A schema entry by alias, ``Section/Key``, key, or its label's words
    (in the user's language or English); None when nothing or several
    things match."""
    schema = _schema()
    wanted = _norm(name)
    if not wanted:
        return None
    if wanted in _ALIASES:
        return schema.find(*_ALIASES[wanted])
    entries = [e for e in schema.entries() if e.key]
    for entry in entries:
        if wanted in (_norm(entry.key), _norm(f"{entry.section}/{entry.key}"),
                      _norm(f"{entry.section} {entry.key}")):
            return entry
    by_label = [e for e in entries if wanted in _norm(_L(e.label))]
    if len(by_label) == 1:
        return by_label[0]
    exact = [e for e in by_label if _norm(_L(e.label)) == wanted]
    return exact[0] if len(exact) == 1 else None


def _value_text(entry):
    walk = _walk()
    tup = _walk_entry(entry)
    try:
        value = walk.value_of(tup)
        if entry.kind == "bool":
            return "on" if _bool(value, False) else "off"
        return str(walk.value_word(tup, value, _engine()))
    except Exception as e:
        return f"? ({e})"


def _accepts(entry):
    if entry.kind == "bool":
        return "on or off"
    if entry.kind == "range":
        low, high, _step = entry.extra
        return f"{low} to {high}"
    if entry.kind == "text":
        return "any text"
    try:
        rows = _walk()._options(_walk_entry(entry), _engine())
    except Exception:
        rows = []
    if not rows:
        return "one of its options"
    return "; ".join(f"{value} ({label})" if str(value) != str(label) else
                     str(value) for value, label in rows[:30])


def _category(name):
    wanted = _norm(name)
    for sid, title, rows in _schema().SECTIONS:
        if wanted in (_norm(sid), _norm(_L(title))):
            return sid, title, rows
    return None


def action_list_setting_categories():
    """The reader's settings categories, as the settings page shows them."""
    lines = [f"{_L(title)} [{sid}], {len(rows)} settings"
             for sid, title, rows in _schema().SECTIONS]
    return "Titan Access settings categories:\n" + "\n".join(lines)


def action_list_settings(category=""):
    """Every reader setting, or one category's, with its value now."""
    sections = _schema().SECTIONS
    if category:
        found = _category(category)
        if found is None:
            return fails(f"There is no settings category called '{category}'. "
                         "titan_access.list_setting_categories names them.")
        sections = (found,)
    lines = []
    for sid, title, rows in sections:
        lines.append(f"{_L(title)} [{sid}]:")
        for entry in rows:
            if not entry.key:
                continue
            alias = _ALIAS_OF.get((entry.section, entry.key))
            named = f"{entry.section}/{entry.key}" + (
                f", '{alias}'" if alias else "")
            lines.append(f"  {_L(entry.label)} [{named}]: {_value_text(entry)}")
    return "Titan Access settings:\n" + "\n".join(lines)


def action_get_setting(name):
    """One reader setting, with what it accepts and what it does."""
    entry = _find_entry(name)
    if entry is None:
        return fails(f"No single reader setting matches '{name}'. "
                     "titan_access.list_settings shows them all with their "
                     "Section/Key names.")
    return (f"{_L(entry.label)} [{entry.section}/{entry.key}] is "
            f"{_value_text(entry)}. Accepts: {_accepts(entry)}. "
            f"{_L(entry.help)}")


def _coerce_entry(entry, value):
    """``value`` as the entry's own kind, or raise ValueError saying why."""
    text = str(value if value is not None else "").strip()
    if entry.kind == "bool":
        return _bool(text, True)
    if entry.kind == "range":
        number = int(float(text))
        low, high, _step = entry.extra
        if not low <= number <= high:
            raise ValueError(f"{number} is outside {low} to {high}")
        return number
    if entry.kind == "text":
        return text
    rows = _walk()._options(_walk_entry(entry), _engine())
    for option, label in rows:
        if _norm(option) == _norm(text) or _norm(label) == _norm(text):
            return option
    for option, label in rows:
        if _norm(text) and _norm(text) in _norm(label):
            return option
    if not rows and entry.kind in ("voices", "variants", "synthesizer"):
        return text
    raise ValueError("it is not one of: " + _accepts(entry))


def action_set_setting(name, value):
    """Change one reader setting, save it and apply it to the running
    reader - the same write the settings page and the walked settings do."""
    entry = _find_entry(name)
    if entry is None:
        return fails(f"No single reader setting matches '{name}'. "
                     "titan_access.list_settings shows them all with their "
                     "Section/Key names.")
    try:
        wanted = _coerce_entry(entry, value)
    except Exception as e:
        return fails(f"'{value}' cannot be {_L(entry.label)}: {e}.")
    try:
        _walk().set_value(_walk_entry(entry), wanted, _engine())
    except Exception as e:
        return fails(f"Could not set {_L(entry.label)}: {e}")
    return f"{_L(entry.label)} is now {_value_text(entry)}."


# --------------------------------------------------------------------------- #
# What a page has, the speech system, profiles, the program in front
# --------------------------------------------------------------------------- #
_SUMMARY = (("browse.count.links", "link"), ("browse.count.headings", "heading"),
            ("browse.count.formFields", "form"),
            ("browse.count.landmarks", "landmark"),
            ("browse.count.tables", "table"), ("browse.count.lists", "list"))


def action_page_summary(window=0):
    """How many links, headings, form fields, landmarks, tables and lists the
    page or window in front has - what the reader says when a page loads
    with "Browsing the web -> page summary" on."""
    doc = _document(window=window)
    if doc is None or not doc.nodes:
        return fails("Nothing readable is on the screen.")
    from titan_access import localization as loc
    parts = []
    for key, kind in _SUMMARY:
        count = len(_matching(doc, kind))
        if count:
            parts.append(loc.plural(key, count))
    if not parts:
        return f"'{doc.title or 'window'}' has no links, headings or fields."
    return loc.L("browse.summary", ", ".join(parts))


def action_speech_systems():
    """What the reader can speak with: the speech systems on this machine,
    the synthesizers of each, and what it is set to now."""
    from titan_access import speech_systems as ss
    system, synth, voice = ss.current(_settings_store())
    lines = [f"Now: {system}" + (f", {synth}" if synth else "")
             + (f", voice {voice}" if voice else "")]
    for sid, label in ss.systems():
        synths = ss.synthesizers(sid)
        names = ", ".join(f"{name} [{key}]" if key else name
                          for key, name in synths)
        lines.append(f"{label} [{sid}]: {names}")
    return "Speech systems:\n" + "\n".join(lines)


def action_list_voices(synthesizer=""):
    """The voices of a synthesizer (the one in use when none is named)."""
    from titan_access import speech_systems as ss
    synth = str(synthesizer or "") or ss.current(_settings_store())[1]
    if not synth:
        return ("The reader speaks with Titan's own voice; choose a speech "
                "system with titan_access.set_speech to pick a voice of its own.")
    rows = ss.voices(synth)
    if not rows:
        return fails(f"'{synth}' offers no voices (or is not installed).")
    return f"Voices of {synth}:\n" + "\n".join(
        f"{label} [{key}]" for key, label in rows)


def _pick(rows, wanted, what):
    wanted_n = _norm(wanted)
    for key, label in rows:
        if _norm(key) == wanted_n or _norm(label) == wanted_n:
            return key
    near = [key for key, label in rows if wanted_n and wanted_n in _norm(label)]
    if len(near) == 1:
        return near[0]
    raise ValueError(f"no {what} called '{wanted}'; there are: "
                     + ", ".join(label for _k, label in rows[:20]))


def action_set_speech(system, synthesizer="", voice=""):
    """Choose what the reader speaks with - the same three levels as the
    speech system dialog (Insert+Ctrl+S)."""
    from titan_access import speech_systems as ss
    try:
        sid = _pick(ss.systems(), system, "speech system")
        synths = ss.synthesizers(sid)
        synth = _pick(synths, synthesizer, "synthesizer") if synthesizer \
            else (synths[0][0] if synths else "")
        chosen = _pick(ss.voices(synth), voice, "voice") \
            if voice and synth else ""
    except Exception as e:
        return fails(str(e))
    ss.choose(_settings_store(), sid, synth, chosen, engine=_engine())
    return action_speech_systems().splitlines()[1]


def action_list_profiles():
    """The programs that have settings of their own."""
    from titan_access import profiles
    names = profiles.programs()
    if not names:
        return "No program has settings of its own."
    lines = []
    for name in names:
        lines.append(f"{name}: {len(profiles.overrides(name))} settings")
    active = profiles.active()
    tail = f"\nIn force now: {active}." if active else ""
    return "Programs with their own settings:\n" + "\n".join(lines) + tail


def action_remove_profile(program):
    """Throw a program's own settings away; it then uses the general ones."""
    from titan_access import profiles
    if str(program) not in profiles.programs():
        return fails(f"'{program}' has no settings of its own.")
    if not profiles.remove(str(program)):
        return fails(f"The settings of '{program}' could not be removed.")
    return f"'{program}' uses the general settings now."


def action_app_info():
    """The program in front: its executable, whether it is a UWP (Store)
    app, and the profile in force for it."""
    from titan_access import uwp, profiles
    hwnd = _foreground()
    if not hwnd:
        return fails("No window is in front.")
    pid = uwp.app_pid(hwnd) if uwp.IS_WINDOWS else 0
    exe = uwp.executable(pid) if pid else ""
    title = _buffer().window_text(hwnd)
    parts = [f"'{title or 'untitled'}'"]
    if exe:
        parts.append(f"program {exe}")
    if uwp.is_uwp_window(hwnd):
        parts.append("a UWP app (its frame is ApplicationFrameHost; "
                     "the settings under 'UWP apps' apply)")
    program = profiles.program_in_front()
    if program and program in profiles.programs():
        parts.append(f"has its own settings ({program})")
    return ", ".join(parts) + "."


def action_braille_status():
    """Whether braille is on, which table and display, and whether the
    display is connected."""
    from titan_access import braille
    report = braille.report()
    store = _settings_store()
    on = store.get_bool("Braille", "Enabled", False)
    display = store.get("Braille", "Display", "none") or "none"
    table = store.get("Braille", "Table", "") or "automatic"
    if not on:
        return "Braille is off."
    words = [f"Braille is on, table {table}, display {display}"]
    words.append("connected" if report.get("display") else
                 ("not connected" if display != "none" else "shown in the viewer"))
    if not report.get("available"):
        words.append("liblouis is not available, so nothing can be translated")
    return ", ".join(words) + "."


def tce_processes():
    """Titan's own process and every process it started, by pid - what the
    reader counts as TCE (`engine._is_tce_foreground` walks the same tree
    the other way)."""
    found = [os.getpid()]
    try:
        import psutil
        found += [child.pid for child in
                  psutil.Process().children(recursive=True)]
    except Exception:
        pass
    return found


def action_reader_policy():
    """For ANOTHER screen reader: whether Titan Access reads TCE by itself
    and leaves the rest of the system to it ("Mute outside TCE"), and which
    processes are TCE. The NVDA add-on asks this and sleeps in exactly
    those processes, so inside TCE only Titan Access speaks and outside it
    only the system's reader does. Answered as JSON, because a program
    reads it."""
    import json
    engine = _engine()
    running = bool(engine is not None and getattr(engine, "running", False))
    try:
        from titan_access.settings_store import get_settings
        mute = bool(get_settings().mute_outside_tce)
    except Exception:
        mute = False
    return json.dumps({"running": running, "mute_outside_tce": mute,
                       "reads_tce_alone": running and mute,
                       "tce_pids": tce_processes() if running else []})


def action_diagnostics():
    """What the reader is made of right now - threads, the keyboard hook,
    the supervisor's counts, the last things said. For finding out why
    something is not heard."""
    engine = _engine()
    if engine is None:
        return fails("The Titan screen reader is not running.")
    try:
        found = engine.diagnostics()
    except Exception as e:
        return fails(f"The reader could not describe itself: {e}")
    lines = [f"running: {found.get('running')}",
             f"threads: {found.get('threads')}",
             f"keyboard hook: {found.get('hook')}",
             f"supervisor: {found.get('supervisor')}"]
    spoken = found.get("spoken") or []
    if spoken:
        lines.append("last said: " + " | ".join(str(x) for x in spoken[-8:]))
    return "\n".join(lines)


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
# What a script - or the AI - does with the reader itself
# --------------------------------------------------------------------------- #
def _speak_out(text):
    """Say ``text`` in the reader's voice; answer the text or a failure."""
    text = str(text or "").strip()
    if not text:
        return fails("There is nothing to say.")
    engine = _engine(require_running=False)
    speak = getattr(engine, "speak", None) if engine is not None else None
    if not callable(speak):
        return fails("The screen reader is not available to speak.")
    try:
        speak(text, interrupt=True)
    except Exception as e:
        return fails(f"The screen reader could not speak: {e}")
    return text


def _focused():
    engine = _engine()
    obj = getattr(engine, "current_object", None) if engine is not None else None
    return obj if obj is not None else _focused_without_engine()


def _status_bar_text():
    engine = _engine()
    if engine is None or not hasattr(engine, "_status_bar_children"):
        return ""
    words = []
    try:
        for _key, child in engine._status_bar_children():
            name = str(getattr(child, "name", "") or "").strip()
            if name and name not in words:
                words.append(name)
    except Exception:
        return ""
    return ", ".join(words)


def _selection_text():
    engine = _engine()
    editable = getattr(engine, "editable", None) if engine is not None else None
    if editable is None:
        return None
    try:
        return editable._selection_text()
    except Exception:
        return None


#: What `read_aloud` can say, and how it is found.
_READ_ALOUD = ("focus", "title", "value", "last", "screen", "position",
               "selection", "status", "time", "date")


def action_read_aloud(what="focus"):
    """Say one thing in the reader's voice and answer what was said."""
    what = str(what or "focus").strip().lower()
    if what not in _READ_ALOUD:
        return fails(f"'{what}' is not something to read; one of: "
                     + ", ".join(_READ_ALOUD) + ".")
    if what == "focus":
        return _speak_out(action_read_focused())
    if what == "title":
        return _speak_out(action_window_title())
    if what == "screen":
        return action_speak_screen()
    if what == "time":
        return _speak_out(time.strftime("%H:%M"))
    if what == "date":
        return _speak_out(time.strftime("%Y-%m-%d"))
    if what == "last":
        said = _spoken()
        return _speak_out(said[-1]) if said else fails("Nothing has been said yet.")
    obj = _focused()
    if what == "value":
        value = str(getattr(obj, "value", "") or "").strip() if obj else ""
        return _speak_out(value) if value else fails(
            "The control in focus holds no value.")
    if what == "position":
        index = int(getattr(obj, "pos_in_set", 0) or 0) if obj else 0
        count = int(getattr(obj, "size_of_set", 0) or 0) if obj else 0
        if not (index and count):
            return fails("The control in focus is not in a counted list.")
        return _speak_out(_L("element.positionOf", index, count))
    if what == "selection":
        chosen = _selection_text()
        if chosen is None:
            return fails("The control in focus has no text to select in.")
        return _speak_out(chosen) if chosen.strip() else _speak_out(
            _L("edit.noSelection"))
    status = _status_bar_text()
    return _speak_out(status) if status else fails(
        "The window in front has no status bar the reader can read.")


def _spoken():
    try:
        from titan_access import speech_adapter
        return [str(x) for x in speech_adapter.spoken()]
    except Exception:
        return []


def action_last_spoken(count=5):
    """The last things the reader said, newest last (at most twenty)."""
    said = _spoken()
    if not said:
        return "The reader has not said anything yet."
    count = max(1, min(int(count or 5), 20))
    return "\n".join(said[-count:])


def action_beep(frequency=880, duration=60, pan=0.0):
    """A tone through the reader's own sound: frequency in Hz, length in ms,
    pan -1 (left) to 1 (right)."""
    engine = _engine(require_running=False)
    sound = getattr(engine, "sound", None) if engine is not None else None
    try:
        frequency = max(40.0, min(float(frequency), 8000.0))
        duration = max(5, min(int(float(duration)), 3000))
        pan = max(-1.0, min(float(pan or 0), 1.0))
    except Exception:
        return fails("A beep wants a frequency in Hz and a length in ms.")
    if sound is None:
        try:
            from titan_access.sound_manager import SoundManager
            sound = SoundManager()
        except Exception as e:
            return fails(f"The reader has no sound: {e}")
    try:
        sound.play_tone(frequency=frequency, duration_ms=duration, pan=pan)
    except Exception as e:
        return fails(f"The tone could not be played: {e}")
    return f"Beep, {int(frequency)} Hz, {duration} ms."


def _cue_names():
    folder = os.path.join(_HERE, "sfx")
    try:
        return sorted(name[:-4] for name in os.listdir(folder)
                      if name.lower().endswith(".ogg"))
    except OSError:
        return []


def action_play_cue(name):
    """One of the reader's own sounds (cursor, edge, clicked...), placed where
    the control in focus is."""
    wanted = str(name or "").strip()
    if wanted.lower().endswith(".ogg"):
        wanted = wanted[:-4]
    names = _cue_names()
    match = [one for one in names if one.lower() == wanted.lower()]
    if not match:
        return fails(f"The reader has no sound called '{name}'. It has: "
                     + ", ".join(names) + ".")
    engine = _engine(require_running=False)
    if engine is None or not hasattr(engine, "play"):
        return fails("The screen reader is not available to play a sound.")
    engine.play(match[0], getattr(engine, "current_object", None))
    return f"Played {match[0]}."


def action_braille(text):
    """Show text on the braille display (or the braille viewer)."""
    text = str(text or "").strip()
    if not text:
        return fails("There is nothing to show.")
    try:
        from titan_access import braille
        braille.show_text(text)
    except Exception as e:
        return fails(f"Braille could not show it: {e}")
    return f"Shown in braille: {text}"


def action_pass_key(key):
    """Press a key for the program, marked so the reader does not take it
    again - what `pass` in a reader script does with the key that started it."""
    spec = str(key or "").strip().lower()
    parts = [part for part in spec.split("+")
             if part and part not in ("insert", "nvda", "ta", "capslock")]
    if not parts:
        return fails("Say which key to pass on, like 'ctrl+s'.")
    try:
        from titan_access import keyboard_hook
        ok = keyboard_hook.send_combo("+".join(parts))
    except Exception as e:
        return fails(f"The key could not be pressed: {e}")
    return ("Passed " + "+".join(parts) + ".") if ok else fails(
        f"'{key}' is not a key the reader can press.")


def action_label_control(label=""):
    """Give the control in focus a name of its own (kept for both readers,
    per program); an empty label takes the name away again."""
    obj = _focused()
    if obj is None:
        return fails("Nothing has the keyboard focus.")
    try:
        from titan_access import nvda_shape
        from titan_access.portable import labels
        adapted = nvda_shape.adapt(obj)
    except Exception as e:
        return fails(f"Names cannot be kept here: {e}")
    label = str(label or "").strip()
    if not label:
        labels.remove(adapted)
        return "The control's own name is used again."
    if not labels.put(adapted, label, source="user"):
        return fails("This control cannot be told apart from its "
                     "neighbours, so a name for it would not stay on it.")
    return f"This control is now called {label}."


def action_list_labels(program=""):
    """The names given to controls, for one program or the one in front."""
    try:
        from titan_access.portable import labels
        from titan_access import profiles
    except Exception as e:
        return fails(f"Names cannot be read here: {e}")
    program = str(program or "").strip() or profiles.program_in_front() or ""
    if not program:
        return fails("Say which program.")
    try:
        rows = labels.for_application(program)
    except Exception as e:
        return fails(f"The names of '{program}' could not be read: {e}")
    if not rows:
        return f"No control of '{program}' has a name of its own."
    lines = []
    for key, row in sorted(rows.items()):
        said = row.get("label") if isinstance(row, dict) else row
        if said:
            lines.append(f"{said} ({key})")
    return f"Names given in {program} ({len(lines)}):\n" + "\n".join(lines)


def _shortcut_rows(engine):
    rows = []
    for binding in getattr(getattr(engine, "gestures", None), "_bindings",
                           None) or ():
        action = str(getattr(binding, "action_id", "") or "")
        if not action:
            continue
        try:
            key = engine._shortcut_key_text(binding)
        except Exception:
            key = str(getattr(binding, "key_spec", "") or "")
        name = str(getattr(binding, "name", "") or action)
        rows.append((action, name, key, binding))
    return rows


def action_list_shortcuts(contains=""):
    """Every key of the running reader with the command it runs - the
    command's id is what run_command and `command` in a script take."""
    engine = _engine()
    if engine is None:
        return fails("The Titan screen reader is not running.")
    grouped, order = {}, []
    for action, name, key, _binding in _shortcut_rows(engine):
        if action not in grouped:
            grouped[action] = (name, [])
            order.append(action)
        if key and key not in grouped[action][1]:
            grouped[action][1].append(key)
    wanted = _norm(contains)
    lines = []
    for action in order:
        name, keys = grouped[action]
        line = f"{action}: {', '.join(keys)}" + (
            f" ({name})" if name != action else "")
        if wanted and wanted not in _norm(line):
            continue
        lines.append(line)
    if not lines:
        return "No command matches." if wanted else "The reader has no keys."
    return f"Titan Access commands ({len(lines)}):\n" + "\n".join(lines)


def action_run_command(name):
    """Run one of the reader's own commands, exactly as its key would."""
    engine = _engine()
    if engine is None:
        return fails("The Titan screen reader is not running.")
    wanted = _norm(name)
    rows = _shortcut_rows(engine)
    found = [row for row in rows if _norm(row[0]) == wanted] or \
        [row for row in rows if _norm(row[1]) == wanted] or \
        [row for row in rows if wanted and wanted in _norm(row[1])]
    if not found:
        return fails(f"The reader has no command '{name}'. "
                     "titan_access.list_shortcuts names them.")
    if len({row[0] for row in found}) > 1:
        return fails("Several commands match: "
                     + ", ".join(sorted({row[0] for row in found}))
                     + ". Say which one.")
    action, label, _key, binding = found[0]
    # A command may open a window or wait for speech: never on the thread
    # that called (Titan's GUI thread, for an action).
    threading.Thread(target=binding.handler, daemon=True,
                     name="TitanAccessCommand").start()
    return f"Ran {label}."


def action_list_speech_schemes():
    """The speech schemes (how each kind of control is announced) and the
    one in use."""
    try:
        from titan_access.portable import speechSchemes
    except Exception as e:
        return fails(f"Speech schemes are not here: {e}")
    active = speechSchemes.active()
    lines = []
    for key in speechSchemes.names():
        mark = " (in use)" if key == active else ""
        lines.append(f"{speechSchemes.label_of(key)} [{key}]{mark}")
    return "Speech schemes:\n" + "\n".join(lines)


def action_set_speech_scheme(name):
    """Use another speech scheme."""
    try:
        from titan_access.portable import speechSchemes
    except Exception as e:
        return fails(f"Speech schemes are not here: {e}")
    wanted = _norm(name)
    keys = list(speechSchemes.names())
    match = [k for k in keys if _norm(k) == wanted or
             _norm(speechSchemes.label_of(k)) == wanted] or \
        [k for k in keys if wanted and wanted in _norm(speechSchemes.label_of(k))]
    if len(match) != 1:
        return fails(f"No single speech scheme matches '{name}'. "
                     + action_list_speech_schemes())
    speechSchemes.use(match[0])
    return f"The speech scheme is now {speechSchemes.label_of(match[0])}."


# --------------------------------------------------------------------------- #
# Writing the user's scripts
# --------------------------------------------------------------------------- #
def _script_path(name):
    ta = _scripts()
    clean = "".join(ch for ch in str(name or "").strip()
                    if ch not in '\\/:*?"<>|').strip()
    if clean.lower().endswith(ta.EXTENSION):
        clean = clean[:-len(ta.EXTENSION)]
    if not clean or clean.startswith("."):
        return None, ""
    return os.path.join(ta.folder(), clean + ta.EXTENSION), clean


def action_script_language(language="en"):
    """The Titan Access script language (.tas) - what a reader script may
    say beyond Titan Script, read out of the reader itself."""
    return _scripts().language_text(language or "en")


def action_read_script(name):
    """The text of one of the user's reader scripts."""
    path, clean = _script_path(name)
    if not path or not os.path.isfile(path):
        return fails(f"There is no script called '{name}'.")
    with open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read()


def action_write_script(name, text, overwrite=False):
    """Write a reader script, checked first: a script with a problem is not
    saved, and the problems are the answer. Loaded at once."""
    ta = _scripts()
    path, clean = _script_path(name)
    if not path:
        return fails("A script needs a name.")
    body = str(text or "").replace("\r\n", "\n")
    if not body.strip():
        return fails("The script is empty.")
    if os.path.exists(path) and not _bool(overwrite, False):
        return fails(f"There is already a script called '{clean}'. "
                     "Pass overwrite=true to replace it.")
    problems = ta.check(body)
    if problems:
        return fails(f"'{clean}' was not saved:\n" + "\n".join(problems))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body if body.endswith("\n") else body + "\n")
    engine = _engine()
    ta.bind(engine) if engine is not None else ta.load()
    return f"Saved and loaded {clean}."


def action_delete_script(name):
    """Delete one of the user's reader scripts."""
    ta = _scripts()
    path, clean = _script_path(name)
    if not path or not os.path.isfile(path):
        return fails(f"There is no script called '{name}'.")
    os.remove(path)
    engine = _engine()
    ta.bind(engine) if engine is not None else ta.load()
    return f"Deleted {clean}."


# --------------------------------------------------------------------------- #
# What Titan Access is - for Titan's AI, read out of the reader as it is now
# --------------------------------------------------------------------------- #
def _component_version():
    path = os.path.join(_HERE, "__component__.TCE")
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            for line in handle:
                key, _sep, value = line.partition("=")
                if key.strip().lower() == "version":
                    return value.strip()
    except OSError:
        pass
    return ""


def briefing(with_actions=True):
    """What Titan Access is and can do, built from the code as it stands -
    its description, its settings categories, its script language and its
    actions - so Titan's AI is never told about an older reader."""
    parts = [TITAN_DESCRIPTION]
    version = _component_version()
    if version:
        parts.append(f"Version {version}.")
    try:
        sections = ", ".join(f"{_L(title)} [{sid}]"
                             for sid, title, _rows in _schema().SECTIONS)
        parts.append(f"Settings categories: {sections}.")
    except Exception:
        pass
    try:
        statements = ", ".join(what.split(" - ")[0].split(" ")[0]
                               for _p, _t, what in _scripts().STATEMENTS)
        kinds = []
        for trigger in _scripts().TRIGGERS:
            word = trigger[0].split()[1]
            if word not in kinds:
                kinds.append(word)
        triggers = "when " + ", ".join(kinds)
        parts.append("Reader scripts (.tas, in the user's accessibility/"
                     "scripts folder) are Titan Script plus the reader's own "
                     f"triggers ({triggers}), statements ({statements}) and "
                     "JAWS-like control rules; titan_access.script_language "
                     "is the full reference and write_script saves one "
                     "checked.")
    except Exception:
        pass
    if with_actions:
        names = ", ".join(entry["name"] for entry in TITAN_ACTIONS)
        parts.append(f"Its actions: {names}.")
    return " ".join(parts)


#: Titan's AI asks this for what the reader is (src/ai/action_tools.py).
TITAN_AI_BRIEFING = briefing


def action_about():
    """What Titan Access is and can do right now, read out of the reader -
    the place to look before telling the user anything about it."""
    lines = [briefing(with_actions=False), "", "Actions:"]
    for entry in TITAN_ACTIONS:
        lines.append(f"  {entry['name']} - {entry['summary']}")
    engine = _engine()
    lines.append("")
    lines.append("The reader is " + ("running." if engine is not None
                                     else "off (reading the screen still "
                                          "works)."))
    return "\n".join(lines)


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

#: What Titan Access is, for the AI's listing of add-ons (Titan reads it
#: as the add-on's description, the Python twin of a manifest's).
TITAN_DESCRIPTION = (
    "Titan's own screen reader (Insert or CapsLock is its modifier). It "
    "reads ANY program's window - UI Automation, MSAA, IAccessible2, Java, "
    "AT-SPI, the raw controls, or its own OCR - even while the reader is "
    "off, and presses what it found. Pages and apps are read as a document "
    "(browse/scan mode, quick navigation, page summary); UWP apps get icons "
    "said as words; notifications are read. It speaks through Titan TTS, "
    "SAPI 5, eSpeak or NVDA add-on synthesizers, shows braille (liblouis, "
    "BRLTTY), keeps settings per program, speech schemes, names given to "
    "controls and the user's reader scripts (.tas). titan_access.about "
    "says what it can do NOW.")

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

    {'name': 'read_text',
     'summary': "Read a window's text off its picture with the reader's own "
                "OCR (Windows' built-in recogniser or the local model).",
     'params': {
         'window': _WINDOW_PARAM,
         'engine': {'type': 'string', 'enum': ['auto', 'windows', 'model'],
                    'description': "Which recogniser; auto tries Windows' "
                                   "first."},
     },
     'needs_gui': False,
     'timeout': 120,
     'run': action_read_text},
    {'name': 'focus_element',
     'summary': "Put the keyboard focus on a control of the window in front, "
                "by what it says.",
     'params': {
         'text': {'type': 'string', 'required': True,
                  'description': "What the control says."},
         'kind': {'type': 'string', 'enum': _KIND_ENUM,
                  'description': "Only elements of this type."},
         'window': _WINDOW_PARAM,
     },
     'timeout': 60,
     'run': action_focus_element},
    {'name': 'read_control',
     'summary': "Say what a control says without moving the focus there, "
                "and hand it back.",
     'params': {
         'text': {'type': 'string',
                  'description': "What the control says (or part of it)."},
         'kind': {'type': 'string', 'enum': _KIND_ENUM,
                  'description': "Only elements of this type; alone, the "
                                 "first of them."},
         'window': _WINDOW_PARAM,
         'speak': {'type': 'boolean',
                   'description': "Say it in the reader's voice (default "
                                  "yes)."},
     },
     'timeout': 60,
     'run': action_read_control},
    {'name': 'click_at',
     'summary': "Click a hot spot: a place in the window in front, in pixels "
                "from its top left corner.",
     'params': {
         'x': {'type': 'integer', 'required': True,
               'description': "Pixels from the left edge."},
         'y': {'type': 'integer', 'required': True,
               'description': "Pixels from the top edge."},
         'button': {'type': 'string', 'enum': ['left', 'right', 'middle'],
                    'description': "Which mouse button (default left)."},
         'clicks': {'type': 'integer',
                    'description': "1 for a click, 2 for a double click."},
         'relative': {'type': 'string', 'enum': ['window', 'screen'],
                      'description': "From the window's corner (default) or "
                                     "the screen's."},
         'window': _WINDOW_PARAM,
     },
     'risk': 'confirm',
     'run': action_click_at},
    {'name': 'wait_for',
     'summary': "Wait until a window comes to the front or a control "
                "appears on the screen.",
     'params': {
         'window_title': {'type': 'string',
                          'description': "Part of the window's title."},
         'text': {'type': 'string',
                  'description': "What the control says."},
         'kind': {'type': 'string', 'enum': _KIND_ENUM,
                  'description': "Only elements of this type."},
         'seconds': {'type': 'number',
                     'description': "How long to wait at most (default 10)."},
     },
     # Never on Titan's own thread: it waits, and Titan would wait with it.
     'needs_gui': False,
     'timeout': 130,
     'run': action_wait_for},
    {'name': 'read_region',
     'summary': "Read part of the window in front off its picture with the "
                "reader's own OCR.",
     'params': {
         'x': {'type': 'integer', 'required': True,
               'description': "Pixels from the window's left edge."},
         'y': {'type': 'integer', 'required': True,
               'description': "Pixels from the window's top edge."},
         'width': {'type': 'integer', 'required': True,
                   'description': "Width in pixels."},
         'height': {'type': 'integer', 'required': True,
                    'description': "Height in pixels."},
         'window': _WINDOW_PARAM,
         'speak': {'type': 'boolean',
                   'description': "Say it in the reader's voice (default "
                                  "yes)."},
     },
     'needs_gui': False,
     'timeout': 60,
     'run': action_read_region},
    {'name': 'nvda_addons',
     'summary': "The NVDA add-ons installed in Titan Access.",
     'needs_gui': False,
     'run': action_nvda_addons},
    {'name': 'install_nvda_addon',
     'summary': "Install a .nvda-addon file into Titan Access.",
     'params': {'path': {'type': 'string', 'required': True,
                         'description': "The .nvda-addon file or folder."}},
     'risk': 'confirm',
     'needs_gui': False,
     'run': action_install_nvda_addon},
    {'name': 'set_nvda_addon',
     'summary': "Switch an NVDA add-on on or off in Titan Access.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The add-on's name."},
                'enabled': {'type': 'boolean',
                            'description': "On (true) or off (false)."}},
     'needs_gui': False,
     'run': action_set_nvda_addon},
    {'name': 'migrate_nvda_addons',
     'summary': "Copy NVDA's own add-ons into Titan Access.",
     'needs_gui': False,
     'run': action_migrate_nvda_addons},
    {'name': 'external_synthesizers',
     'summary': "The synthesizers NVDA add-ons bring to Titan Access.",
     'needs_gui': False,
     'run': action_external_synthesizers},
    {'name': 'list_scripts',
     'summary': "The user's Titan Access scripts and when each one runs.",
     'needs_gui': False,
     'run': action_list_scripts},
    {'name': 'run_script',
     'summary': "Run one of the user's Titan Access scripts now.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The script's name, without .tas."}},
     'needs_gui': False,
     'run': action_run_script},
    {'name': 'check_script',
     'summary': "Check a Titan Access script without running it.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The script's name, without .tas."}},
     'needs_gui': False,
     'run': action_check_script},
    {'name': 'reload_scripts',
     'summary': "Read the scripts folder again and rebind their keys.",
     'needs_gui': False,
     'run': action_reload_scripts},
    {'name': 'scripts_folder',
     'summary': "Where the user's Titan Access scripts live.",
     'needs_gui': False,
     'run': action_scripts_folder},
    {'name': 'ocr_status',
     'summary': "Which of the reader's own recognisers can read here.",
     'needs_gui': False,
     'timeout': 60,
     'run': action_ocr_status},

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
    {'name': 'list_setting_categories',
     'summary': "The Titan Access settings categories (Speech, Browsing the "
                "web, UWP apps, Braille...), as the settings page shows them.",
     'run': action_list_setting_categories},
    {'name': 'list_settings',
     'summary': "Every Titan Access setting with its value now and its "
                "Section/Key name, or only one category's.",
     'params': {'category': {'type': 'string',
                             'description': "A category id or name, e.g. "
                                            "'web' or 'uwp'; leave it out "
                                            "for all of them."}},
     'run': action_list_settings},
    {'name': 'get_setting',
     'summary': "One Titan Access setting: its value, what it accepts and "
                "what it does.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "Its Section/Key (e.g. "
                                        "'Browse/PageSummary'), its key, or "
                                        "words from its label ('rate', "
                                        "'page summary', 'scan mode')."}},
     'run': action_get_setting},
    {'name': 'set_setting',
     'summary': "Change one Titan Access setting, save it and apply it to "
                "the running reader - the same as changing it in the "
                "settings page or the walked settings.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "Its Section/Key, key or label words, "
                                        "as for get_setting."},
                'value': {'type': 'string', 'required': True,
                          'description': "on/off, a number, or an option's "
                                         "value or label."}},
     'risk': 'confirm', 'run': action_set_setting},
    {'name': 'list_profiles',
     'summary': "The programs that have Titan Access settings of their own.",
     'run': action_list_profiles},
    {'name': 'remove_profile',
     'summary': "Throw away a program's own reader settings, so it uses the "
                "general ones.",
     'params': {'program': {'type': 'string', 'required': True,
                            'description': "The program, as list_profiles "
                                           "names it."}},
     'risk': 'confirm', 'run': action_remove_profile},

    # -- speech ---------------------------------------------------------- #
    {'name': 'speech_systems',
     'summary': "What the reader can speak with (Titan's voice, Titan TTS, "
                "SAPI 5, eSpeak, NVDA add-on synthesizers...) and what it "
                "uses now.",
     'run': action_speech_systems},
    {'name': 'list_voices',
     'summary': "The voices of a synthesizer of the reader.",
     'params': {'synthesizer': {'type': 'string',
                                'description': "A synthesizer id from "
                                               "speech_systems; leave it out "
                                               "for the one in use."}},
     'run': action_list_voices},
    {'name': 'set_speech',
     'summary': "Choose the reader's speech system, synthesizer and voice "
                "(the same as Insert+Ctrl+S).",
     'params': {'system': {'type': 'string', 'required': True,
                           'description': "A speech system's id or name."},
                'synthesizer': {'type': 'string',
                                'description': "Its synthesizer; the first "
                                               "when left out."},
                'voice': {'type': 'string',
                          'description': "A voice's id or name; the "
                                         "synthesizer's own when left out."}},
     'risk': 'confirm', 'run': action_set_speech},

    # -- what is in front ------------------------------------------------ #
    {'name': 'page_summary',
     'summary': "How many links, headings, form fields, landmarks, tables "
                "and lists the page or window in front has.",
     'params': {'window': _WINDOW_PARAM},
     'run': action_page_summary},
    {'name': 'app_info',
     'summary': "The program in front: its executable, whether it is a UWP "
                "(Store) app, and whether it has reader settings of its own.",
     'run': action_app_info},
    {'name': 'braille_status',
     'summary': "Whether braille is on, its table and display, and whether "
                "the display is connected.",
     'run': action_braille_status},
    {'name': 'reader_policy',
     'summary': "For another screen reader (JSON): whether Titan Access is "
                "running with 'mute outside TCE', so it reads TCE alone, and "
                "the pids of TCE's processes.",
     'needs_gui': False,
     'run': action_reader_policy},
    {'name': 'diagnostics',
     'summary': "What the running reader is made of right now (threads, the "
                "keyboard hook, restarts, the last things said) - for finding "
                "out why something is not heard.",
     'run': action_diagnostics},
    # -- what the reader is, for the AI ------------------------------------ #
    {'name': 'about',
     'summary': "What Titan Access is and can do right now - its settings "
                "categories, its script language and every action, read out "
                "of the reader itself. Ask this before telling the user "
                "anything about the reader.",
     'run': action_about},

    # -- the reader's own voice, sounds and keys -------------------------- #
    {'name': 'read_aloud',
     'summary': "Say one thing in the reader's voice: the focused control, "
                "the window title, its value, the last thing said, the "
                "screen, the place in the list, the selected text, the "
                "status bar, the time or the date.",
     'params': {'what': {'type': 'string', 'enum': list(_READ_ALOUD),
                         'description': "What to say."}},
     'run': action_read_aloud},
    {'name': 'last_spoken',
     'summary': "The last things the reader said, newest last - what the "
                "user just heard.",
     'params': {'count': {'type': 'integer',
                          'description': "How many (1 to 20)."}},
     'run': action_last_spoken},
    {'name': 'beep',
     'summary': "Play a tone through the reader's sound.",
     'params': {'frequency': {'type': 'number', 'description': "Hz."},
                'duration': {'type': 'integer', 'description': "Ms."},
                'pan': {'type': 'number',
                        'description': "-1 left to 1 right."}},
     'run': action_beep},
    {'name': 'play_cue',
     'summary': "Play one of the reader's own sounds (cursor, edge, "
                "clicked...), placed where the focused control is.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The sound's name."}},
     'run': action_play_cue},
    {'name': 'braille',
     'summary': "Show text on the braille display (or the braille viewer).",
     'params': {'text': {'type': 'string', 'required': True,
                         'description': "What to show."}},
     'run': action_braille},
    {'name': 'pass_key',
     'summary': "Press a key for the program, so the reader does not take "
                "it again.",
     'params': {'key': {'type': 'string', 'required': True,
                        'description': "Like 'ctrl+s' or 'f5'."}},
     'run': action_pass_key},
    {'name': 'list_shortcuts',
     'summary': "Every key of the running reader and the command it runs.",
     'params': {'contains': {'type': 'string',
                             'description': "Only commands whose id, name "
                                            "or key has this."}},
     'run': action_list_shortcuts},
    {'name': 'run_command',
     'summary': "Run one of the reader's own commands (say all, the virtual "
                "window, the command palette...) exactly as its key would.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "Its id or name, as list_shortcuts "
                                        "names it."}},
     'run': action_run_command},
    {'name': 'list_speech_schemes',
     'summary': "The speech schemes (how each kind of control is announced) "
                "and the one in use.",
     'run': action_list_speech_schemes},
    {'name': 'set_speech_scheme',
     'summary': "Use another speech scheme.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "Its name or id."}},
     'risk': 'confirm', 'run': action_set_speech_scheme},
    {'name': 'label_control',
     'summary': "Give the control in focus a name of its own, kept for "
                "that program; an empty label takes it away.",
     'params': {'label': {'type': 'string',
                          'description': "The name; empty to remove it."}},
     'risk': 'confirm', 'run': action_label_control},
    {'name': 'list_labels',
     'summary': "The names given to controls of a program (the one in "
                "front when none is named).",
     'params': {'program': {'type': 'string',
                            'description': "The program, without .exe."}},
     'run': action_list_labels},

    # -- the user's reader scripts, written -------------------------------- #
    {'name': 'script_language',
     'summary': "The Titan Access script language (.tas): its triggers, "
                "conditions, variables, statements and control rules. Read "
                "it before writing a reader script.",
     'params': {'language': {'type': 'string', 'enum': ['en', 'pl'],
                             'description': "en (the default) or pl."}},
     'run': action_script_language},
    {'name': 'read_script',
     'summary': "The text of one of the user's reader scripts.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The script, as list_scripts names "
                                        "it."}},
     'run': action_read_script},
    {'name': 'write_script',
     'summary': "Write a reader script (.tas). It is checked first - a "
                "script with a problem is not saved and the problems are "
                "the answer - and loaded at once.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The script's name."},
                'text': {'type': 'string', 'required': True,
                         'description': "The whole script."},
                'overwrite': {'type': 'boolean',
                              'description': "Replace a script of that "
                                             "name."}},
     'risk': 'confirm', 'run': action_write_script},
    {'name': 'delete_script',
     'summary': "Delete one of the user's reader scripts.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The script."}},
     'risk': 'confirm', 'run': action_delete_script},
]

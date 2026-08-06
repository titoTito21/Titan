# -*- coding: utf-8 -*-
"""AI OCR as a source for the screen reader.

Some programs answer nothing: no UI Automation, no MSAA, not even child windows
worth reading - a game menu, a custom-drawn installer, a kiosk. Titan already
knows how to deal with that: :mod:`src.ai.ocr` photographs the window, has the
AI read it into a structured :class:`~src.ai.ocr.model.Screen`, and clicks the
real control for a chosen entry. This module is the thin bridge that lets
**Titan Access** use it as one more source of a virtual document
(:mod:`titan_access.virtual_buffer`) and as a way to *label* controls the app
never named.

Two entry points matter:

* :func:`build_nodes` - the whole window as buffer nodes, used only after the
  accessibility tiers came back empty.
* :func:`label_for` - the text that sits on/next to a rectangle, used to give a
  nameless button or edit field a name.

Everything is gated: AI features must be on, a vision provider must be
configured, and the reader's own "use AI OCR" setting must be enabled - a scan
sends a picture of the user's screen to their provider, so it never happens by
accident. Every function degrades to "nothing" instead of raising, because the
caller is a screen reader and a failed reading must never be a crash.

# LOCALE KEYS TO ADD: ocr.reading = Reading the screen
# LOCALE KEYS TO ADD: ocr.unavailable = AI reading is not available: {0}
# LOCALE KEYS TO ADD: ocr.nothing = Nothing could be read on this screen
# LOCALE KEYS TO ADD: ocr.readWithAi = read with AI
"""

import threading
import time

_DBG = __import__("os").environ.get("TITAN_ACCESS_DEBUG")

# How long a reading stays usable for labelling / activation before the window
# is photographed again.
CACHE_SECONDS = 25.0

# src.ai.ocr role -> Titan role key. Anything unknown becomes text, which is
# readable but not actionable -- the safe direction to be wrong in.
_OCR_ROLE_TO_ROLE = {
    "button": "button",
    "menuitem": "menuitem",
    "listitem": "listitem",
    "tab": "tab",
    "checkbox": "checkbox",
    "radio": "radio",
    "link": "link",
    "edit": "edit",
    "combobox": "combobox",
    "slider": "slider",
    "progress": "progressbar",
    "heading": "heading",
    "image": "image",
    "text": "text",
    "other": "unknown",
}

_lock = threading.Lock()
_cache = {}          # hwnd -> (screen, timestamp)


# --------------------------------------------------------------------------- #
# Availability
# --------------------------------------------------------------------------- #
def unavailable_reason(settings=None) -> str:
    """Why an AI reading cannot run, or '' when it can.

    Checks, in the order the user would ask them: does the reader want this at
    all, are Titan's AI features on, and is there a key to use.
    """
    if settings is not None and not _reader_wants_ocr(settings):
        return "off"
    try:
        from src.ai import ai_provider
    except Exception as e:
        return f"AI features are not installed: {e}"
    try:
        return ai_provider.vision_unavailable_reason() or ""
    except Exception as e:
        return str(e)


def available(settings=None) -> bool:
    return not unavailable_reason(settings)


def _reader_wants_ocr(settings) -> bool:
    """The reader's own switch (Settings -> Titan Access), default on.

    The gate that actually protects the user is Titan's AI-features switch;
    this one exists so somebody who has AI on for everything else can still
    keep their screen out of it.
    """
    if settings is None:
        return True
    for attr in ("ai_ocr", "use_ai_ocr"):
        value = getattr(settings, attr, None)
        if value is not None:
            return bool(value)
    try:
        raw = settings.get("Reader", "UseAiOcr")
    except Exception:
        return True
    if raw in (None, ""):
        return True
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def read_window(hwnd, force=False, on_status=None, settings=None):
    """Read *hwnd* with the AI and return a ``Screen`` (or None).

    A recent reading of the same window is reused (``CACHE_SECONDS``) unless
    ``force``; the recogniser itself also answers from its previous reading
    when the picture has not changed, so a second call on a static screen costs
    nothing.
    """
    reason = unavailable_reason(settings)
    if reason:
        if _DBG:
            print(f"[TitanAccess][ocr] unavailable: {reason}", flush=True)
        return None
    hwnd = int(hwnd or 0)
    previous = None
    if not force:
        cached = _cached(hwnd)
        if cached is not None:
            return cached
    with _lock:
        entry = _cache.get(hwnd)
        previous = entry[0] if entry else None
    try:
        from src.ai.ocr import recognizer
    except Exception as e:
        print(f"[TitanAccess] ocr_assist: recogniser unavailable: {e}")
        return None
    try:
        screen = recognizer.read_screen(scope="window", hwnd=hwnd,
                                        previous=previous, on_stage=on_status)
    except Exception as e:
        print(f"[TitanAccess] ocr_assist: reading failed: {e}")
        return None
    if screen is None:
        return None
    with _lock:
        _cache[hwnd] = (screen, time.time())
    return screen


def _cached(hwnd):
    with _lock:
        entry = _cache.get(hwnd)
    if not entry:
        return None
    screen, when = entry
    if (time.time() - when) > CACHE_SECONDS:
        return None
    return screen


def forget(hwnd=None):
    """Drop cached readings (all of them, or one window's)."""
    with _lock:
        if hwnd is None:
            _cache.clear()
        else:
            _cache.pop(int(hwnd), None)


# --------------------------------------------------------------------------- #
# Nodes for the virtual buffer
# --------------------------------------------------------------------------- #
def build_nodes(hwnd, node_cls, on_status=None, settings=None, force=False):
    """Read *hwnd* and return its controls as ``node_cls`` buffer nodes.

    ``node_cls`` is passed in (rather than imported) so this module never
    imports :mod:`titan_access.virtual_buffer`, which imports it.

    Rectangles come back in SCREEN pixels: the model answers in the pixels of
    the picture it was shown, and the ``Capture`` is the only thing that knows
    how to convert them -- so the conversion happens here, once, and nothing
    downstream ever has to think about the scale factor.
    """
    screen = read_window(hwnd, force=force, on_status=on_status,
                         settings=settings)
    if screen is None:
        return []
    shot = getattr(screen, "capture", None)
    nodes = []
    for region in getattr(screen, "regions", []) or []:
        region_name = (getattr(region, "label", "") or "").strip()
        if region_name and len(region.elements or []) > 1:
            nodes.append(node_cls(name=region_name, role="heading", level=1,
                                  source="ocr", hwnd=hwnd,
                                  rect=_screen_rect(shot, getattr(region, "rect", None))))
        for element in region.elements or []:
            node = _node_for(element, shot, hwnd, node_cls)
            if node is not None:
                nodes.append(node)
    if _DBG:
        print(f"[TitanAccess][ocr] built {len(nodes)} nodes for {hwnd}", flush=True)
    return nodes


def _node_for(element, shot, hwnd, node_cls):
    name = (getattr(element, "name", "") or "").strip()
    body = (getattr(element, "text", "") or "").strip()
    if not name and not body:
        return None
    role = _OCR_ROLE_TO_ROLE.get(getattr(element, "role", "text"), "text")
    states = []
    state_text = (getattr(element, "state", "") or "").lower()
    if "disabled" in state_text:
        states.append("unavailable")
    checked = getattr(element, "checked", None)
    if checked is True:
        states.append("checked")
    elif checked is False:
        states.append("unchecked")
    if "selected" in state_text and "unchecked" not in states:
        states.append("selected")
    return node_cls(
        name=name or body,
        role=role,
        value=(getattr(element, "value", "") or "").strip(),
        states=tuple(states),
        rect=_screen_rect(shot, getattr(element, "rect", None)),
        source="ocr",
        hwnd=hwnd,
        ocr_ref=element,
        level=1 if role == "heading" else 0,
    )


def _screen_rect(shot, rect):
    """OCR image rect ``[x, y, w, h]`` -> screen ``(l, t, r, b)``, or ()."""
    if shot is None or not rect:
        return ()
    try:
        left, top, width, height = shot.rect_to_screen(rect)
        return (int(left), int(top), int(left + width), int(top + height))
    except Exception:
        return ()


# --------------------------------------------------------------------------- #
# Labelling a control the program never named
# --------------------------------------------------------------------------- #
def label_for(hwnd, rect, settings=None, max_distance=220):
    """The text that names the control occupying *rect* (screen pixels).

    This is the "make labels" half: a nameless button or edit field is given
    the caption printed on or beside it. Preference order matches how a sighted
    person reads a form: text INSIDE the control, then immediately to its left,
    then immediately above it. Returns '' when nothing plausible is near.
    """
    if not rect or len(rect) != 4:
        return ""
    screen = _cached(int(hwnd or 0))
    if screen is None:
        screen = read_window(hwnd, settings=settings)
    if screen is None:
        return ""
    shot = getattr(screen, "capture", None)
    if shot is None:
        return ""
    left, top, right, bottom = rect
    mid_y = (top + bottom) / 2.0
    inside = best_left = best_above = None
    for element in screen.elements:
        text = (getattr(element, "name", "") or getattr(element, "text", "") or "").strip()
        if not text or len(text) > 120:
            continue
        other = _screen_rect(shot, getattr(element, "rect", None))
        if not other:
            continue
        o_left, o_top, o_right, o_bottom = other
        centre_x = (o_left + o_right) / 2.0
        centre_y = (o_top + o_bottom) / 2.0
        if left <= centre_x <= right and top <= centre_y <= bottom:
            if inside is None or len(text) > len(inside):
                inside = text
            continue
        if o_bottom >= top and o_top <= bottom and o_right <= left + 8:
            distance = left - o_right
            if distance <= max_distance and (best_left is None or distance < best_left[0]):
                best_left = (distance, text)
        elif o_bottom <= top + 4 and abs(o_left - left) < 120:
            distance = top - o_bottom
            if distance <= 80 and (best_above is None or distance < best_above[0]):
                best_above = (distance, text)
    del mid_y
    if inside:
        return inside
    if best_left:
        return best_left[1]
    if best_above:
        return best_above[1]
    return ""


# --------------------------------------------------------------------------- #
# Acting
# --------------------------------------------------------------------------- #
def activate(node, screen=None):
    """Press the real control an OCR node stands for. False if it cannot."""
    element = getattr(node, "ocr_ref", None)
    if element is None:
        return False
    if screen is None:
        screen = _cached(int(getattr(node, "hwnd", 0) or 0))
    if screen is None:
        return False
    try:
        from src.ai.ocr import actions
    except Exception as e:
        print(f"[TitanAccess] ocr_assist: actions unavailable: {e}")
        return False
    try:
        if getattr(element, "role", "") in ("checkbox", "radio"):
            actions.toggle(screen, element)
        else:
            actions.activate(screen, element)
        return True
    except Exception as e:
        if _DBG:
            print(f"[TitanAccess][ocr] activate refused: {e}", flush=True)
        return False


def can_act() -> bool:
    """Whether pressing controls read by AI OCR is allowed at all."""
    try:
        from src.ai.ocr import actions
        return bool(actions.can_act())
    except Exception:
        return False


def summary(hwnd, settings=None) -> str:
    """One sentence about what the AI saw, for an announcement."""
    screen = _cached(int(hwnd or 0)) or read_window(hwnd, settings=settings)
    if screen is None:
        return ""
    text = (getattr(screen, "summary", "") or "").strip()
    if text:
        return text
    return (getattr(screen, "title", "") or "").strip()

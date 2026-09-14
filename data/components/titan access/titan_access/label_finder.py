# -*- coding: utf-8 -*-
"""A name for a control the program never named.

Three places to look, in the order a sighted person reads a form and in the
order of what each costs:

1. **UI Automation** - the static text beside the control: the caption
   printed on it, immediately to its left, or immediately above it, read
   off the control's own siblings. In-process COM, a few milliseconds,
   private and free; it answers for most Win32 and WinUI forms.
2. **The local recogniser** - the words of the window as a picture, read by
   the model on THIS machine (`ocr_assist.local_lines`: Titan's own tier,
   nothing sent anywhere). Seconds, so it runs off the focus path and the
   window's reading is kept for a while, which makes every other unnamed
   control in that window instant.
3. **The AI** - what `ocr_assist.label_for` already did, and only when the
   user has AI OCR on: a picture of the screen at a provider.

A name found by 2 or 3 is remembered in the shared label store
(`portable/labels.py`, the same file the NVDA add-on reads), so a control
is asked about once in its life and named in both readers.
"""

import threading
import time

_LOCK = threading.RLock()
#: hwnd -> (time, [(text, (left, top, right, bottom))])
_readings = {}
#: How long a window's local reading is kept.
READING_KEPT = 12.0
#: A caption further away than this is somebody else's.
MAX_LEFT = 220
MAX_ABOVE = 80
_counted = {'uia': 0, 'ocr': 0, 'ai': 0, 'stored': 0}


def report():
    with _LOCK:
        return dict(_counted)


def forget():
    with _LOCK:
        _readings.clear()
        _counted.update({'uia': 0, 'ocr': 0, 'ai': 0, 'stored': 0})


def _text(value):
    return str(value or '').strip()


def nearest(rect, candidates):
    """The text that names *rect*: inside it, else to its left, else above.

    ``candidates`` is ``[(text, (left, top, right, bottom))]``. The rule is
    the one `ocr_assist.label_for` applies to an AI reading, kept in one
    place so every tier picks the same caption.
    """
    if not rect or len(rect) != 4:
        return ''
    left, top, right, bottom = rect
    inside = best_left = best_above = None
    for text, other in candidates:
        text = _text(text)
        if not text or len(text) > 120 or not other:
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
            if distance <= MAX_LEFT and (best_left is None
                                         or distance < best_left[0]):
                best_left = (distance, text)
        elif o_bottom <= top + 4 and abs(o_left - left) < 120:
            distance = top - o_bottom
            if distance <= MAX_ABOVE and (best_above is None
                                          or distance < best_above[0]):
                best_above = (distance, text)
    if inside:
        return inside
    if best_left:
        return best_left[1]
    if best_above:
        return best_above[1]
    return ''


# --------------------------------------------------------------------------- #
# 1. UI Automation: the text beside it
# --------------------------------------------------------------------------- #
def _rect_of(control):
    try:
        r = control.BoundingRectangle
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:                                # noqa: BLE001
        return None


def from_uia(obj, limit=80):
    """The caption beside the control, out of its parent's children."""
    native = getattr(obj, 'native', None)
    rect = getattr(obj, 'bounds', None)
    if native is None or not rect:
        return ''
    try:
        parent = native.GetParentControl()
        children = list(parent.GetChildren() or []) if parent is not None \
            else []
    except Exception:                                # noqa: BLE001
        return ''
    candidates = []
    for child in children[:limit]:
        try:
            kind = child.ControlTypeName
        except Exception:                            # noqa: BLE001
            continue
        if kind not in ('TextControl', 'GroupControl'):
            continue
        name = ''
        try:
            name = _text(child.Name)
        except Exception:                            # noqa: BLE001
            name = ''
        if not name:
            continue
        other = _rect_of(child)
        if other:
            candidates.append((name.rstrip(':').strip(), other))
    found = nearest(tuple(rect), candidates)
    if found:
        with _LOCK:
            _counted['uia'] += 1
    return found


# --------------------------------------------------------------------------- #
# 2. The local recogniser: the window as a picture, read here
# --------------------------------------------------------------------------- #
def _reading(hwnd, read=None):
    """The window's words with their rectangles, kept for a while."""
    hwnd = int(hwnd or 0)
    if not hwnd:
        return []
    now = time.time()
    with _LOCK:
        kept = _readings.get(hwnd)
    if kept and now - kept[0] < READING_KEPT:
        return kept[1]
    if read is None:
        try:
            from titan_access import ocr_assist
            read = ocr_assist.local_lines
        except Exception:                            # noqa: BLE001
            return []
    try:
        lines = read(hwnd) or []
    except Exception:                                # noqa: BLE001
        lines = []
    found = []
    for one in lines:
        try:
            left = int(one['left'])
            top = int(one['top'])
            found.append((_text(one.get('text')),
                          (left, top, left + int(one['width']),
                           top + int(one['height']))))
        except Exception:                            # noqa: BLE001
            continue
    with _LOCK:
        _readings[hwnd] = (now, found)
    return found


def cached_reading(hwnd):
    """The kept reading of a window, or None when there is none."""
    with _LOCK:
        kept = _readings.get(int(hwnd or 0))
    if kept and time.time() - kept[0] < READING_KEPT:
        return kept[1]
    return None


def from_local_ocr(obj, hwnd, read=None, cached_only=False):
    """The caption beside the control, out of the window's picture."""
    rect = getattr(obj, 'bounds', None)
    if not rect or not hwnd:
        return ''
    if cached_only:
        words = cached_reading(hwnd)
        if words is None:
            return ''
    else:
        words = _reading(hwnd, read)
    found = nearest(tuple(rect), words)
    if found:
        with _LOCK:
            _counted['ocr'] += 1
    return found


# --------------------------------------------------------------------------- #
# Remembering
# --------------------------------------------------------------------------- #
def remember(adapted, label, source='ai'):
    """Keep a found name in the shared store, both readers' own."""
    if adapted is None or not _text(label):
        return False
    try:
        from .portable import labels
        ok = bool(labels.put(adapted, label, source=source))
    except Exception:                                # noqa: BLE001
        ok = False
    if ok:
        with _LOCK:
            _counted['stored'] += 1
    return ok

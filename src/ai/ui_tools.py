"""Screen-element and scrolling tools for the Titan AI Agent and the assistant.

:mod:`src.ai.agent_tools` can already click at raw coordinates, which is enough
when the AI can see the screen. What it could NOT do is the thing a sighted
person does without thinking: *scroll a panel and check that it actually
scrolled*, and *click a control by its name only when that control is really
there and really enabled*.

That gap makes some dialogs impossible for a blind user. The licence agreement
of a game such as Cyberpunk 2077 is the classic case: the Accept button stays
disabled until the licence text has been scrolled all the way to the end, and
nothing announces either fact. This module gives the AI the missing pieces:

* :func:`list_elements`   - what is on screen, with each control's ENABLED /
  disabled state, its coordinates, and every scrollable area with its scroll
  position ("License text: 0% scrolled, 30% of it visible").
* :func:`scroll`          - turn the mouse wheel over a point or over a named
  area, then VERIFY the view really moved (UI Automation scroll percentage
  when the app exposes one, otherwise a before/after pixel comparison) and say
  so plainly.
* :func:`scroll_to_end`   - keep scrolling until the view stops moving, i.e.
  the classic "you must read the whole licence" gate, then report which
  buttons became enabled.
* :func:`click_element`   - click a control BY NAME. If it is disabled the tool
  refuses and explains why (with the scroll-to-the-end hint) instead of
  silently clicking nothing; if it is scrolled out of view it scrolls it into
  view first.
* :func:`drag_mouse`      - press, move and release: dragging a scrollbar thumb
  is the fallback when an app ignores the wheel.

Everything degrades gracefully: without UI Automation (custom-rendered game
UIs) the tools fall back to Win32 child windows and to pixel comparison, and
when even the screen capture comes back blank - normal for an exclusive
full-screen game - they say the scroll could not be verified rather than
claiming success.

Tool result strings are plain English (untranslated), matching
:mod:`src.ai.agent_tools`; the human-readable, translated action descriptions
used for narration and confirm dialogs live in ``agent_tools.describe_action``.
"""

import atexit
import gc
import queue
import threading
import time

from src.ai.agent_tools import _tool


# --------------------------------------------------------------------------- #
# UI Automation plumbing
# --------------------------------------------------------------------------- #
# Control types (UIA_*ControlTypeId) we care to name.
_CONTROL_TYPES = {
    50000: 'button', 50001: 'calendar', 50002: 'check box', 50003: 'combo box',
    50004: 'edit', 50005: 'link', 50006: 'image', 50007: 'list item',
    50008: 'list', 50009: 'menu', 50010: 'menu bar', 50011: 'menu item',
    50012: 'progress bar', 50013: 'radio button', 50014: 'scroll bar',
    50015: 'slider', 50016: 'spinner', 50017: 'status bar', 50018: 'tab',
    50019: 'tab item', 50020: 'text', 50021: 'toolbar', 50022: 'tooltip',
    50023: 'tree', 50024: 'tree item', 50025: 'custom', 50026: 'group',
    50027: 'thumb', 50028: 'data grid', 50029: 'data item', 50030: 'document',
    50031: 'split button', 50032: 'window', 50033: 'pane', 50034: 'header',
    50035: 'header item', 50036: 'table', 50037: 'title bar',
    50038: 'separator', 50039: 'semantic zoom', 50040: 'app bar',
}

# Controls worth offering to the model as "things you can click".
_INTERACTIVE = {
    'button', 'check box', 'combo box', 'edit', 'link', 'list item',
    'menu item', 'radio button', 'slider', 'spinner', 'tab item', 'tree item',
    'split button', 'data item', 'custom',
}

# Pattern ids (UIA_*PatternId).
_P_INVOKE = 10000
_P_VALUE = 10002
_P_SCROLL = 10004
_P_EXPAND_COLLAPSE = 10005
_P_SELECTION_ITEM = 10010
_P_TOGGLE = 10015
_P_SCROLL_ITEM = 10017
_P_LEGACY = 10018

# ScrollPattern reports this percentage when an axis cannot scroll at all.
_NO_SCROLL = -1.0

# ToggleState_Off / _On / _Indeterminate.
_TOGGLE_STATES = ('unchecked', 'checked', 'partly checked')

_uia = None
_uia_failed = False


def _co_init():
    """Join the multi-threaded apartment (falling back to whatever this thread
    already is). UI Automation clients are supposed to run MTA, and it is also
    what keeps us safe: an interface pointer created in the MTA may be used and
    released by ANY thread in it, whereas releasing a single-threaded-apartment
    proxy from another thread - which is exactly what Python's garbage
    collector eventually does - is an access violation that takes the whole
    process down."""
    try:
        import comtypes
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except Exception:
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# All UIA work happens on one dedicated MTA thread
# --------------------------------------------------------------------------- #
# Reasons: (1) the apartment stays alive for the whole session, so the cached
# automation object never dangles; (2) no COM pointer ever escapes to the wx GUI
# thread; (3) we can time out a window that stops responding without hanging the
# agent. The worker collects garbage after every call so that the elements a
# call created are released HERE, inside the apartment that made them.
class _UiaWorker(threading.Thread):

    def __init__(self):
        super().__init__(daemon=True, name='titan-ai-uia')
        self.jobs = queue.Queue()

    def run(self):
        _co_init()
        while True:
            fn, box, done = self.jobs.get()
            try:
                box['result'] = fn()
            except Exception as e:
                box['error'] = e
            finally:
                try:
                    gc.collect()
                except Exception:
                    pass
                done.set()


_worker = None
_worker_lock = threading.Lock()


def _uia_call(fn, timeout=90):
    """Run ``fn`` on the UIA thread and return its (plain, non-COM) result."""
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = _UiaWorker()
            _worker.start()
        worker = _worker
    box, done = {}, threading.Event()
    worker.jobs.put((fn, box, done))
    if not done.wait(timeout):
        with _worker_lock:  # retire the stuck worker; the next call gets a fresh one
            if _worker is worker:
                _worker = None
        return ("The window stopped responding, so this action timed out. Try "
                "again, or work from a screenshot and click by coordinates.")
    err = box.get('error')
    if err is not None:
        return f"Error: {err}"
    return box.get('result')


@atexit.register
def _release_uia():
    """Drop the cached automation object from inside the apartment that created
    it - releasing it from the exiting main thread crashes on the way out."""
    global _uia
    if _uia is None:
        return

    def _drop():
        global _uia
        _uia = None
    try:
        _uia_call(_drop, timeout=5)
    except Exception:
        pass


def _get_uia():
    """A cached IUIAutomation instance, or None when UIA is unavailable."""
    global _uia, _uia_failed
    if _uia is not None or _uia_failed:
        return _uia
    try:
        import comtypes.client
        _co_init()
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
        _uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
    except Exception as e:
        print(f"[ui_tools] UI Automation unavailable: {e}")
        _uia_failed = True
    return _uia


def _valid(el):
    """Is this a real element? UI Automation signals "no such element" (no
    child, no parent, nothing at that point) with a NULL interface pointer,
    which comtypes hands back as a pointer OBJECT, not as None. Keeping one of
    those alive is fatal: the garbage collector later calls Release on a null
    vtable and the process dies with an access violation."""
    try:
        return el is not None and bool(el)
    except Exception:
        return False


def _pattern(el, pattern_id, interface_name):
    """Get a control pattern of ``el`` as its own interface, or None.

    Via QueryInterface, NEVER via ``comtypes.cast``: comtypes re-exports
    ctypes' cast, which reinterprets the raw pointer WITHOUT taking a
    reference, so the two Python objects wrapping it each call Release and the
    second one corrupts the heap."""
    try:
        raw = el.GetCurrentPattern(pattern_id)
        if not _valid(raw):
            return None
        from comtypes.gen import UIAutomationClient as U
        pattern = raw.QueryInterface(getattr(U, interface_name))
        return pattern if _valid(pattern) else None
    except Exception:
        return None


def _foreground_hwnd():
    try:
        import win32gui
        return win32gui.GetForegroundWindow()
    except Exception:
        return 0


def _window_rect(hwnd):
    """(left, top, right, bottom) of a window, clipped to the primary screen."""
    try:
        import win32gui
        import win32api
        import win32con
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        l, t = max(0, l), max(0, t)
        r, b = min(sw, r), min(sh, b)
        if r - l < 8 or b - t < 8:
            return 0, 0, sw, sh
        return l, t, r, b
    except Exception:
        return None


def _foreground_element():
    """The UIA element of the foreground window, or None."""
    uia = _get_uia()
    hwnd = _foreground_hwnd()
    if uia is None or not hwnd:
        return None
    try:
        _co_init()
        el = uia.ElementFromHandle(hwnd)
        return el if _valid(el) else None
    except Exception:
        return None


def _el_name(el):
    try:
        return (el.CurrentName or '').strip()
    except Exception:
        return ''


def _el_type(el):
    try:
        return _CONTROL_TYPES.get(el.CurrentControlType, 'element')
    except Exception:
        return 'element'


def _el_enabled(el):
    try:
        return bool(el.CurrentIsEnabled)
    except Exception:
        return True


def _el_offscreen(el):
    try:
        return bool(el.CurrentIsOffscreen)
    except Exception:
        return False


def _el_rect(el):
    try:
        r = el.CurrentBoundingRectangle
        return int(r.left), int(r.top), int(r.right), int(r.bottom)
    except Exception:
        return None


def _el_point(el):
    """Where to click this element: its clickable point, else its centre."""
    try:
        got = el.GetClickablePoint()
        pt, ok = (got if isinstance(got, tuple) else (got, True))
        if ok and pt is not None:
            return int(pt.x), int(pt.y)
    except Exception:
        pass
    rect = _el_rect(el)
    if not rect:
        return None
    l, t, r, b = rect
    if r <= l or b <= t:
        return None
    return (l + r) // 2, (t + b) // 2


def _el_value(el):
    """The text value of an edit/combo, if it exposes one."""
    val = _pattern(el, _P_VALUE, 'IUIAutomationValuePattern')
    if val is None:
        return ''
    try:
        return (val.CurrentValue or '').strip()
    except Exception:
        return ''


def _walk_elements(root, max_nodes=1200, time_budget=4.0):
    """Breadth-first walk of the control view under ``root`` (capped in both
    node count and wall time, so a huge tree never stalls the agent)."""
    uia = _get_uia()
    if uia is None or root is None:
        return []
    try:
        walker = uia.ControlViewWalker
    except Exception:
        return []
    out = []
    pending = [root]
    deadline = time.time() + time_budget
    while pending and len(out) < max_nodes and time.time() < deadline:
        node = pending.pop(0)
        try:
            child = walker.GetFirstChildElement(node)
        except Exception:
            child = None
        while _valid(child) and len(out) < max_nodes:
            out.append(child)
            pending.append(child)
            try:
                child = walker.GetNextSiblingElement(child)
            except Exception:
                break
    return out


# --------------------------------------------------------------------------- #
# Matching elements by name
# --------------------------------------------------------------------------- #
def _norm(text):
    """Fold a label for matching: lowercase, drop accelerators, ellipses and
    punctuation, so 'A&ccept...' matches 'accept'."""
    s = (text or '').replace('&', '').lower()
    return ''.join(ch for ch in s if ch.isalnum() or ch.isspace()).strip()


def _score(label, needle):
    """How well ``label`` matches ``needle``: 3 exact, 2 starts-with,
    1 contains, 0 no match."""
    a, b = _norm(label), _norm(needle)
    if not a or not b:
        return 0
    if a == b:
        return 3
    if a.startswith(b) or b.startswith(a):
        return 2
    return 1 if b in a else 0


def _find_elements(name, role=None, root=None):
    """All elements under the foreground window matching ``name``, best first.
    Returns a list of (score, element)."""
    root = root if root is not None else _foreground_element()
    if root is None:
        return []
    hits = []
    for el in _walk_elements(root):
        etype = _el_type(el)
        if role and _norm(role) not in _norm(etype):
            continue
        best = 0
        for label in (_el_name(el), _el_value(el)):
            best = max(best, _score(label, name))
        try:
            if not best and _score(el.CurrentAutomationId or '', name) == 3:
                best = 3
        except Exception:
            pass
        if best:
            # Prefer interactive controls over the static text that labels them.
            hits.append((best + (1 if etype in _INTERACTIVE else 0), el))
    hits.sort(key=lambda h: -h[0])
    return hits


def _find_win32_children(name):
    """Fallback for apps without UIA: child windows whose text matches, as
    (score, hwnd, text, rect)."""
    try:
        import win32gui
    except Exception:
        return []
    hwnd = _foreground_hwnd()
    if not hwnd:
        return []
    hits = []

    def _cb(child, _acc):
        try:
            text = win32gui.GetWindowText(child)
            if not text.strip():
                return
            sc = _score(text, name)
            if sc and win32gui.IsWindowVisible(child):
                hits.append((sc, child, text.strip(), win32gui.GetWindowRect(child)))
        except Exception:
            pass
    try:
        win32gui.EnumChildWindows(hwnd, _cb, None)
    except Exception:
        pass
    hits.sort(key=lambda h: -h[0])
    return hits


def _describe_element(el, index=None):
    """One human line for an element: name, type, state, coordinates."""
    name = _el_name(el) or _el_value(el) or '(no name)'
    etype = _el_type(el)
    bits = []
    if not _el_enabled(el):
        bits.append('DISABLED')
    if _el_offscreen(el):
        bits.append('scrolled out of view')
    toggle = _pattern(el, _P_TOGGLE, 'IUIAutomationTogglePattern')
    if toggle is not None:
        try:
            bits.append(_TOGGLE_STATES[toggle.CurrentToggleState])
        except Exception:
            pass
    point = _el_point(el)
    where = f"at ({point[0]}, {point[1]})" if point else 'no on-screen position'
    state = ', '.join(bits) if bits else 'enabled'
    prefix = f"{index}. " if index is not None else ''
    return f"{prefix}\"{name}\" [{etype}] - {state}, {where}"


# --------------------------------------------------------------------------- #
# Scroll containers and scroll verification
# --------------------------------------------------------------------------- #
def _scroll_pattern(el):
    sp = _pattern(el, _P_SCROLL, 'IUIAutomationScrollPattern')
    if sp is None:
        return None
    try:  # A pattern that can scroll on neither axis is of no use to us.
        if not (sp.CurrentVerticallyScrollable or sp.CurrentHorizontallyScrollable):
            return None
    except Exception:
        return None
    return sp


def _scroll_percent(sp, horizontal=False):
    try:
        pct = (sp.CurrentHorizontalScrollPercent if horizontal
               else sp.CurrentVerticalScrollPercent)
        pct = float(pct)
        return None if pct == _NO_SCROLL or pct < 0 else pct
    except Exception:
        return None


def _scrollable_at(x, y):
    """The nearest scrollable container at a screen point: (element, pattern)."""
    uia = _get_uia()
    if uia is None:
        return None, None
    try:
        _co_init()
        from ctypes.wintypes import POINT
        el = uia.ElementFromPoint(POINT(int(x), int(y)))
    except Exception:
        el = None
    if not _valid(el):
        return None, None
    try:
        walker = uia.ControlViewWalker
    except Exception:
        walker = None
    node, depth = el, 0
    while _valid(node) and depth < 12:
        sp = _scroll_pattern(node)
        if sp is not None:
            return node, sp
        if walker is None:
            break
        try:
            node = walker.GetParentElement(node)
        except Exception:
            break
        depth += 1
    return None, None


def _list_scrollables(root=None):
    """Every scrollable area under the foreground window, as human lines."""
    lines = []
    root = root if root is not None else _foreground_element()
    if root is None:
        return lines
    for el in [root] + _walk_elements(root, max_nodes=400, time_budget=2.5):
        sp = _scroll_pattern(el)
        if sp is None:
            continue
        v = _scroll_percent(sp)
        h = _scroll_percent(sp, horizontal=True)
        parts = []
        if v is not None:
            try:
                view = float(sp.CurrentVerticalViewSize)
            except Exception:
                view = 100.0
            at_end = ' (at the very end)' if v >= 99.5 else (
                ' (at the very top)' if v <= 0.5 else '')
            parts.append(f"vertical {v:.0f}% scrolled, {view:.0f}% of it visible{at_end}")
        if h is not None:
            parts.append(f"horizontal {h:.0f}% scrolled")
        if not parts:
            continue
        point = _el_point(el)
        where = f" at ({point[0]}, {point[1]})" if point else ''
        name = _el_name(el) or _el_type(el)
        lines.append(f'- scrollable area "{name}"{where}: ' + '; '.join(parts))
        if len(lines) >= 8:
            break
    return lines


def _capture_fingerprint(rect):
    """A small downscaled copy of a screen region, for before/after comparison.
    Returns (array, blank) - ``blank`` when the capture came back empty, which
    is what happens with exclusive full-screen games."""
    if not rect:
        return None, True
    l, t, r, b = rect
    try:
        import numpy as np
        from src.ai.agent_tools import _capture_rect
        arr = _capture_rect(l, t, r - l, b - t)
        small = arr[::4, ::4].astype(np.int16)
        # An all-black / perfectly uniform grab tells us nothing.
        return small, bool(small.std() < 1.0)
    except Exception:
        return None, True


def _fingerprints_differ(before, after, threshold=0.004):
    """Did the captured region visibly change? (fraction of changed pixels)"""
    try:
        import numpy as np
        if before is None or after is None or before.shape != after.shape:
            return None
        changed = np.count_nonzero(np.abs(before - after) > 12)
        # A plain bool, not numpy's: callers compare with ``is True`` / ``is False``.
        return bool((changed / float(before.size)) > threshold)
    except Exception:
        return None


def _root_window_at(x, y):
    """The top-level window under a screen point - the one the mouse wheel will
    actually reach, whether or not it is the foreground window."""
    try:
        import ctypes
        import win32gui
        hwnd = win32gui.WindowFromPoint((int(x), int(y)))
        if not hwnd:
            return 0
        return ctypes.windll.user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
    except Exception:
        return 0


class _ScrollTarget:
    """Where we scroll and how we tell whether it worked."""

    def __init__(self, x, y, label, element=None, pattern=None, rect=None):
        self.x, self.y = x, y
        self.label = label
        self.element = element
        self.pattern = pattern
        self.rect = rect
        # The window we are aiming at, so a repeated scroll notices at once if
        # it closes or another window takes its place under the pointer - we
        # must never keep spinning the wheel over somebody else's window.
        self.hwnd = _root_window_at(x, y)

    def moved_away(self):
        now = _root_window_at(self.x, self.y)
        return bool(self.hwnd) and bool(now) and now != self.hwnd

    def percent(self, horizontal=False):
        return _scroll_percent(self.pattern, horizontal) if self.pattern else None

    def fingerprint(self):
        return _capture_fingerprint(self.rect)


def _resolve_target(target=None, x=None, y=None):
    """Work out the point to scroll over and the container that should move."""
    hwnd = _foreground_hwnd()
    win_rect = _window_rect(hwnd)
    element = None
    label = ''
    if target:
        hits = _find_elements(target)
        if hits:
            element = hits[0][1]
            label = _el_name(element) or target
            point = _el_point(element)
            if point:
                x, y = point
    if x is None or y is None:
        if win_rect:
            l, t, r, b = win_rect
            x, y = (l + r) // 2, (t + b) // 2
        else:
            x, y = 640, 400
        if not label:
            try:
                import win32gui
                label = win32gui.GetWindowText(hwnd) or 'the window'
            except Exception:
                label = 'the window'
    elif not label:
        label = f"({int(x)}, {int(y)})"

    container, pattern = _scrollable_at(x, y)
    if pattern is None and element is not None:
        sp = _scroll_pattern(element)
        if sp is not None:
            container, pattern = element, sp
    rect = _el_rect(container) if container is not None else None
    if not rect or rect[2] - rect[0] < 8 or rect[3] - rect[1] < 8:
        rect = win_rect
    return _ScrollTarget(int(x), int(y), label, container, pattern, rect)


def _wheel(direction, amount, x, y):
    """Turn the mouse wheel ``amount`` notches over (x, y)."""
    from pynput.mouse import Controller
    m = Controller()
    m.position = (int(x), int(y))
    time.sleep(0.05)
    d = str(direction or 'down').lower()
    dx, dy = 0, 0
    if d in ('down', 'd'):
        dy = -int(amount)
    elif d in ('up', 'u'):
        dy = int(amount)
    elif d in ('right', 'r'):
        dx = int(amount)
    elif d in ('left', 'l'):
        dx = -int(amount)
    else:
        dy = -int(amount)
    m.scroll(dx, dy)


def _keys_scroll(direction, amount):
    """Keyboard scrolling, for areas that ignore the wheel."""
    from src.ai.agent_tools import press_keys
    key = {'down': 'pagedown', 'up': 'pageup',
           'right': 'right', 'left': 'left'}.get(str(direction).lower(), 'pagedown')
    for _i in range(max(1, int(amount))):
        press_keys(key)
        time.sleep(0.05)


def _do_scroll(direction, amount, target, method):
    """One scroll step. Returns (moved, detail) where ``moved`` is True/False,
    or None when it could not be verified."""
    horizontal = str(direction).lower() in ('left', 'right', 'l', 'r')
    before_pct = target.percent(horizontal)
    before_img, blank = target.fingerprint()

    if str(method).lower() == 'keys':
        _keys_scroll(direction, amount)
    else:
        _wheel(direction, amount, target.x, target.y)
    time.sleep(0.35)  # let the app repaint / finish its smooth-scroll animation

    after_pct = target.percent(horizontal)
    if before_pct is not None and after_pct is not None:
        moved = abs(after_pct - before_pct) > 0.4
        edge = ''
        if after_pct >= 99.5:
            edge = ' - this is the very END of the content'
        elif after_pct <= 0.5:
            edge = ' - this is the very BEGINNING of the content'
        return moved, (f"the view is now {after_pct:.0f}% scrolled "
                       f"(was {before_pct:.0f}%){edge}")

    after_img, blank_after = target.fingerprint()
    if blank or blank_after:
        return None, ("the screen capture came back blank, which is normal for a "
                      "full-screen game, so the scroll could not be verified")
    differ = _fingerprints_differ(before_img, after_img)
    if differ is None:
        return None, "the scroll could not be verified"
    return differ, ("the content on screen changed" if differ
                    else "the content on screen did NOT change")


def _button_states(limit=10):
    """Buttons and check boxes of the foreground window with their state - what
    you want to know right after scrolling a licence to the end."""
    root = _foreground_element()
    if root is None:
        return []
    out = []
    for el in _walk_elements(root, max_nodes=600, time_budget=2.5):
        if _el_type(el) not in ('button', 'check box', 'split button', 'radio button'):
            continue
        name = _el_name(el)
        if not name:
            continue
        out.append(f'"{name}" [{_el_type(el)}] - '
                   f'{"enabled" if _el_enabled(el) else "DISABLED"}')
        if len(out) >= limit:
            break
    return out


def _with_screenshot(text):
    """Attach a fresh screenshot to a tool result, so the model can SEE what the
    action did - the only verification left in a UI that exposes no controls at
    all (a game's own licence screen, for instance)."""
    try:
        from src.ai.agent_tools import screenshot as _shot
        shot = _shot()
        if isinstance(shot, dict) and shot.get('image_png'):
            return {'text': f"{text} {shot['text']}", 'image_png': shot['image_png']}
    except Exception:
        pass
    return text


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
# Every public tool runs its body on the UIA thread (see _uia_call): the body
# may create COM element pointers, and those must live and die in one apartment.
def list_elements(filter=None, all=False, max_items=60, **kw):
    """List the controls of the focused window with their state and position."""
    return _uia_call(lambda: _list_elements_impl(filter, all, max_items))


def click_element(name, role=None, button="left", method="auto", **kw):
    """Click a control by its visible name, if it is really there and enabled."""
    return _uia_call(lambda: _click_element_impl(name, role, button, method))


def scroll(direction="down", amount=3, x=None, y=None, target=None,
           method="wheel", see=False, **kw):
    """Scroll with the mouse wheel and verify that the view really moved."""
    return _uia_call(lambda: _scroll_impl(direction, amount, x, y, target,
                                          method, see))


def scroll_to_end(direction="down", target=None, x=None, y=None, max_scrolls=40,
                  method="wheel", see=False, **kw):
    """Scroll an area all the way to its end, then report the buttons' state."""
    return _uia_call(lambda: _scroll_to_end_impl(direction, target, x, y,
                                                 max_scrolls, method, see),
                     timeout=150)


def _list_elements_impl(filter=None, all=False, max_items=60, **_):
    """List the controls of the focused window with their state, position and
    the scroll position of every scrollable area."""
    try:
        root = _foreground_element()
        title = ''
        try:
            import win32gui
            title = win32gui.GetWindowText(_foreground_hwnd())
        except Exception:
            pass
        lines = [f"Window: {title!r}"] if title else []

        if root is None:
            hits = _find_win32_children(filter or '')
            if not hits:
                return ("\n".join(lines) + "\nThis window exposes no readable "
                        "elements (a custom-drawn or game UI). Take a screenshot "
                        "to see it, then click by coordinates.").strip()
            lines.append("Controls (basic Win32 read, no accessibility data):")
            for i, (_sc, _hwnd, text, rect) in enumerate(hits[:int(max_items)], 1):
                cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
                lines.append(f"{i}. \"{text}\" - at ({cx}, {cy})")
            return "\n".join(lines)

        shown = 0
        items = []
        for el in _walk_elements(root):
            etype = _el_type(el)
            if not bool(all) and etype not in _INTERACTIVE:
                continue
            name = _el_name(el) or _el_value(el)
            if not name:
                continue
            if filter and not _score(name, filter):
                continue
            shown += 1
            items.append(_describe_element(el, shown))
            if shown >= int(max_items):
                break
        if items:
            lines.append("Controls:")
            lines.extend(items)
        else:
            lines.append("No matching controls found." if filter
                         else "No named controls found; this may be a "
                              "custom-drawn UI - use a screenshot instead.")
        scrollables = _list_scrollables(root)
        if scrollables:
            lines.append("Scrollable areas:")
            lines.extend(scrollables)
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing elements: {e}"


def _click_element_impl(name, role=None, button="left", method="auto", **_):
    """Click a control by its visible name, but only when it is really enabled;
    scroll it into view first if needed."""
    try:
        hits = _find_elements(name, role=role)
        if not hits:
            win32_hits = _find_win32_children(name)
            if win32_hits:
                _sc, _hwnd, text, rect = win32_hits[0]
                cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
                from src.ai.agent_tools import click as _click
                _click(cx, cy, button)
                return f'Clicked "{text}" at ({cx}, {cy}).'
            available = []
            root = _foreground_element()
            if root is not None:
                for el in _walk_elements(root, max_nodes=400, time_budget=2.5):
                    if _el_type(el) in _INTERACTIVE and _el_name(el):
                        available.append(f'"{_el_name(el)}" [{_el_type(el)}]')
                    if len(available) >= 15:
                        break
            hint = (" Controls I can see: " + ", ".join(available)) if available else (
                " This window exposes no named controls - take a screenshot and "
                "click by coordinates instead.")
            return f'No control named "{name}" in the focused window.' + hint

        el = hits[0][1]
        label = _el_name(el) or name
        etype = _el_type(el)

        # Out of view? Ask the container to bring it in before doing anything.
        if _el_offscreen(el):
            item = _pattern(el, _P_SCROLL_ITEM, 'IUIAutomationScrollItemPattern')
            if item is not None:
                try:
                    item.ScrollIntoView()
                    time.sleep(0.3)
                except Exception:
                    pass

        if not _el_enabled(el):
            return (f'Found "{label}" [{etype}] but it is DISABLED, so I did not '
                    f'click it. A control is usually disabled because a condition '
                    f'has not been met yet - in a licence or terms dialog the '
                    f'Accept button only becomes clickable after the text has been '
                    f'scrolled all the way to the END, and sometimes a "I agree" '
                    f'check box must be ticked first. Scroll the text area to the '
                    f'end (scroll_to_end) and/or tick the box, then try again.')

        if _el_offscreen(el):
            return (f'Found "{label}" [{etype}] but it is scrolled out of view and '
                    f'could not be brought into view. Scroll the area that contains '
                    f'it, then try again.')

        point = _el_point(el)

        # Physical mouse click when asked for, or when there is no usable pattern.
        if str(method).lower() != 'mouse':
            invoke = _pattern(el, _P_INVOKE, 'IUIAutomationInvokePattern')
            if invoke is not None:
                try:
                    invoke.Invoke()
                    return f'Clicked "{label}" [{etype}].'
                except Exception:
                    pass
            if etype in ('check box', 'radio button'):
                toggle = _pattern(el, _P_TOGGLE, 'IUIAutomationTogglePattern')
                if toggle is not None:
                    try:
                        toggle.Toggle()
                        state = _TOGGLE_STATES[
                            toggle.CurrentToggleState]
                        return f'Ticked "{label}" [{etype}] - it is now {state}.'
                    except Exception:
                        pass
                sel = _pattern(el, _P_SELECTION_ITEM, 'IUIAutomationSelectionItemPattern')
                if sel is not None:
                    try:
                        sel.Select()
                        return f'Selected "{label}" [{etype}].'
                    except Exception:
                        pass
            if etype in ('list item', 'tree item', 'tab item', 'data item'):
                sel = _pattern(el, _P_SELECTION_ITEM, 'IUIAutomationSelectionItemPattern')
                if sel is not None:
                    try:
                        sel.Select()
                        return f'Selected "{label}" [{etype}].'
                    except Exception:
                        pass

        if not point:
            return (f'Found "{label}" [{etype}] but it has no on-screen position '
                    f'to click.')
        from src.ai.agent_tools import click as _click
        _click(point[0], point[1], button)
        return f'Clicked "{label}" [{etype}] at ({point[0]}, {point[1]}).'
    except Exception as e:
        return f"Error clicking element: {e}"


def _scroll_impl(direction="down", amount=3, x=None, y=None, target=None,
                 method="wheel", see=False, **_):
    """Scroll with the mouse wheel over a point or a named area, and verify
    that the view really moved."""
    try:
        t = _resolve_target(target, x, y)
        moved, detail = _do_scroll(direction, amount, t, method)
        where = f'over "{t.label}" at ({t.x}, {t.y})'
        head = f"Scrolled {direction} {int(amount)} step(s) {where}: "
        if moved is True:
            msg = head + detail + "."
        elif moved is False:
            msg = (head + detail + ". Either it is already at the end in that "
                   "direction, or this area does not react to the mouse wheel - "
                   "try scrolling over a different point (e.g. inside the text "
                   "itself), or use the keyboard instead (method='keys', which "
                   "sends Page Down/Page Up), or drag its scrollbar.")
        else:
            msg = head + detail + "."
            if not see:
                msg += " Take a screenshot to check the result yourself."
        return _with_screenshot(msg) if see else msg
    except Exception as e:
        return f"Error scrolling: {e}"


def _scroll_to_end_impl(direction="down", target=None, x=None, y=None,
                        max_scrolls=40, method="wheel", see=False, **_):
    """Keep scrolling until the view stops moving - the 'you must read the whole
    licence' gate - then report which buttons are now enabled."""
    try:
        t = _resolve_target(target, x, y)
        horizontal = str(direction).lower() in ('left', 'right', 'l', 'r')
        steps = 0
        unverified = 0
        still = 0
        left_window = False
        deadline = time.time() + 60

        # Fast path: a container that exposes a scroll percentage can be sent
        # straight to the end. We still turn the wheel for real first and once
        # again afterwards, because a dialog that unlocks its Accept button
        # watches for scrolling, and a silent jump might not wake it up.
        if t.pattern is not None and t.percent(horizontal) is not None:
            _do_scroll(direction, 3, t, method)
            steps += 1
            goal = 0.0 if str(direction).lower() in ('up', 'left') else 100.0
            try:
                if horizontal:
                    t.pattern.SetScrollPercent(goal, _NO_SCROLL)
                else:
                    t.pattern.SetScrollPercent(_NO_SCROLL, goal)
                time.sleep(0.3)
                _do_scroll(direction, 1, t, method)
                steps += 1
            except Exception:
                pass  # not settable - fall through to plain wheel scrolling

        limit = max(1, min(int(max_scrolls), 200))
        while steps < limit and time.time() < deadline:
            moved, detail = _do_scroll(direction, 5, t, method)
            steps += 1
            if t.moved_away():
                # The window we were scrolling closed or another one covered it;
                # every further notch would go to somebody else's window.
                left_window = True
                break
            pct = t.percent(horizontal)
            if pct is not None and ((not horizontal and direction != 'up' and pct >= 99.5)
                                    or (str(direction).lower() == 'up' and pct <= 0.5)):
                break
            if moved is False:
                still += 1
                if still >= 2:
                    break
            elif moved is None:
                unverified += 1
                still = 0
                if unverified >= 12:  # unverifiable UI: do a generous fixed run
                    break
            else:
                still = 0

        pct = t.percent(horizontal)
        if left_window:
            state = ("I stopped: the window I was scrolling is no longer under "
                     "the pointer (it closed, or another window came to the "
                     "front), and I will not scroll a different window. Check "
                     "what is on screen now.")
        elif pct is not None:
            state = (f"The area is now {pct:.0f}% scrolled"
                     + (" - the very END of the content." if pct >= 99.5
                        else (" - the very BEGINNING." if pct <= 0.5 else ".")))
        elif unverified:
            state = ("The scrolling could not be verified (custom-drawn or "
                     "full-screen UI), so I scrolled generously; take a "
                     "screenshot to confirm you are at the end.")
        else:
            state = "The content stopped changing, so this is the end."
        msg = (f'Scrolled {direction} to the end over "{t.label}" at '
               f'({t.x}, {t.y}) in {steps} step(s). {state}')
        buttons = [] if left_window else _button_states()
        if buttons:
            msg += (" Buttons in this window now: " + "; ".join(buttons)
                    + ". If the one you need is enabled, click it now.")
        elif not see and not left_window:
            msg += (" This window exposes no readable buttons, so take a "
                    "screenshot to see what is now on screen.")
        return _with_screenshot(msg) if see else msg
    except Exception as e:
        return f"Error scrolling to the end: {e}"


def drag_mouse(x, y, to_x, to_y, button="left", steps=20, **_):
    """Press the mouse at (x, y), move to (to_x, to_y) and release - use it to
    drag a scrollbar thumb when an app ignores the wheel."""
    try:
        from pynput.mouse import Controller, Button
        m = Controller()
        btn = {'left': Button.left, 'right': Button.right,
               'middle': Button.middle}.get(str(button), Button.left)
        x, y, to_x, to_y = int(x), int(y), int(to_x), int(to_y)
        n = max(1, min(int(steps), 200))
        m.position = (x, y)
        time.sleep(0.08)
        m.press(btn)
        try:
            for i in range(1, n + 1):
                m.position = (int(x + (to_x - x) * i / n), int(y + (to_y - y) * i / n))
                time.sleep(0.01)
            time.sleep(0.08)
        finally:
            m.release(btn)
        return f"Dragged from ({x}, {y}) to ({to_x}, {to_y})."
    except Exception as e:
        return f"Error dragging: {e}"


# --------------------------------------------------------------------------- #
# Tool registry
# --------------------------------------------------------------------------- #
def get_ui_tools():
    """Screen-element and scrolling tools. All observation / ordinary operating,
    so all 'auto' risk - the same tier as click and press_keys."""
    S = {'type': 'string'}
    N = {'type': 'number'}
    B = {'type': 'boolean'}
    return [
        _tool('list_elements',
              "List the controls of the focused window with their name, type, "
              "ENABLED/disabled state and screen position, plus every scrollable "
              "area and how far it is scrolled. Use this before clicking, and to "
              "find out WHY a button does nothing (it may be disabled).",
              list_elements,
              properties={'filter': dict(S, description="Only controls whose name matches this text."),
                          'all': dict(B, description="Include non-interactive controls (text, groups) too."),
                          'max_items': dict(N, description="Maximum controls to list (default 60).")}),
        _tool('click_element',
              "Click a control of the focused window BY NAME (e.g. 'Accept'). "
              "Scrolls it into view if needed, and REFUSES to click when the "
              "control is disabled, explaining why - use this instead of blind "
              "coordinate clicks whenever the control has a name.",
              click_element,
              properties={'name': dict(S, description="Visible name of the control, e.g. 'Accept'."),
                          'role': dict(S, description="Optional control type, e.g. 'button', 'check box'."),
                          'button': dict(S, description="left, right or middle (default left)."),
                          'method': dict(S, description="'auto' (accessibility action, default) or "
                                                        "'mouse' to force a real mouse click.")},
              required=['name']),
        _tool('scroll',
              "Scroll with the mouse wheel over a point or over a named area, "
              "then report whether the view ACTUALLY moved and how far it is "
              "scrolled. direction: down, up, left or right.",
              scroll,
              properties={'direction': dict(S, description="down, up, left or right (default down)."),
                          'amount': dict(N, description="Wheel notches (default 3)."),
                          'x': dict(N, description="Screen X to scroll over (default: the area named in target, else the middle of the window)."),
                          'y': dict(N, description="Screen Y to scroll over."),
                          'target': dict(S, description="Name of the area to scroll, e.g. 'License'."),
                          'method': dict(S, description="'wheel' (default) or 'keys' (Page Down/Page Up) "
                                                        "for areas that ignore the wheel."),
                          'see': dict(B, description="Also return a screenshot of the result - use it "
                                                     "for game or custom UIs that expose no controls.")}),
        _tool('scroll_to_end',
              "Scroll an area all the way to the end (or back to the top) and "
              "report the buttons' state afterwards. This is what unlocks "
              "licence / terms dialogs whose Accept button stays disabled until "
              "the whole text has been scrolled through.",
              scroll_to_end,
              properties={'direction': dict(S, description="down (default) or up."),
                          'target': dict(S, description="Name of the area to scroll, e.g. 'License'."),
                          'x': dict(N, description="Screen X to scroll over (optional)."),
                          'y': dict(N, description="Screen Y to scroll over (optional)."),
                          'max_scrolls': dict(N, description="Safety cap on scroll steps (default 40)."),
                          'method': dict(S, description="'wheel' (default) or 'keys'."),
                          'see': dict(B, description="Also return a screenshot of the result - use it "
                                                     "for game or custom UIs that expose no controls.")}),
        _tool('drag_mouse',
              "Press the mouse at one point, drag to another and release - for "
              "dragging a scrollbar thumb or a slider when the wheel is ignored.",
              drag_mouse,
              properties={'x': N, 'y': N, 'to_x': N, 'to_y': N,
                          'button': dict(S, description="left (default), right or middle."),
                          'steps': dict(N, description="Intermediate move steps (default 20).")},
              required=['x', 'y', 'to_x', 'to_y']),
    ]

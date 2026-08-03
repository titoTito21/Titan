# -*- coding: utf-8 -*-
"""Taking the picture, and remembering how to get back from it to the screen.

The single most important thing in this whole package is the coordinate
transform. The model is shown a downscaled PNG and answers in *image* pixels;
pressing a control means clicking a point on the *real* screen. Getting that
wrong does not produce a wrong answer - it produces a click somewhere else,
in somebody else's application.

So the model is never asked to do arithmetic. It reports rectangles in the
image it was given, and :class:`Capture` - which knows the scale factor and the
origin the image was taken from - is the only thing that converts them. The
model is told the image size and nothing about the screen at all.

The GDI capture helpers themselves are reused from :mod:`src.ai.agent_tools`
rather than re-written, so the AI agent and AI OCR always see the same screen
(including the PrintWindow fallback that is the only way to get a picture out
of a hardware-composited window).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

# The longest side of the picture we send. Matches agent_tools.screenshot():
# beyond this the providers downscale it themselves anyway, and every extra
# pixel is tokens the user pays for.
MAX_SIDE = 1568

# Below this a capture is all one colour - what a desktop grab of an exclusive
# full-screen game returns, and worth saying out loud rather than analysing.
BLANK_STD = 1.0


@dataclass
class Capture:
    """One picture of the screen plus everything needed to act on it.

    ``png``          the encoded image actually sent to the model
    ``width/height`` its size in image pixels (what the model measures in)
    ``factor``       how much it was downscaled (1 = native)
    ``origin``       the screen point image pixel (0, 0) corresponds to
    ``source``       'window' or 'screen' - what was captured
    ``title``        the captured window's title, when there is one
    ``blank``        True when the capture carries no picture at all
    """

    png: bytes
    width: int
    height: int
    factor: int = 1
    origin: Tuple[int, int] = (0, 0)
    source: str = 'screen'
    title: str = ''
    hwnd: int = 0
    blank: bool = False
    screen_size: Tuple[int, int] = (0, 0)
    fingerprint: str = ''
    _thumb: List[int] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------ geometry
    def to_screen(self, x: float, y: float) -> Tuple[int, int]:
        """Image pixel -> real screen point. The only conversion there is."""
        return (int(round(x * self.factor)) + self.origin[0],
                int(round(y * self.factor)) + self.origin[1])

    def rect_to_screen(self, rect: Sequence[float]) -> Tuple[int, int, int, int]:
        """Image ``[x, y, w, h]`` -> screen ``(left, top, width, height)``."""
        x, y, w, h = (float(v) for v in rect)
        left, top = self.to_screen(x, y)
        return (left, top,
                max(1, int(round(w * self.factor))),
                max(1, int(round(h * self.factor))))

    def centre_of(self, rect: Sequence[float]) -> Tuple[int, int]:
        """Where to click for an image-space rectangle."""
        left, top, width, height = self.rect_to_screen(rect)
        return (left + width // 2, top + height // 2)

    def contains_rect(self, rect: Optional[Sequence[float]]) -> bool:
        """Is this a rectangle that could plausibly be in this picture?

        A model that loses track of the image size answers with coordinates
        from some other picture; clicking those would be a click at random.
        """
        if not rect or len(rect) != 4:
            return False
        try:
            x, y, w, h = (float(v) for v in rect)
        except (TypeError, ValueError):
            return False
        if w <= 0 or h <= 0:
            return False
        if x < -2 or y < -2:
            return False
        # A little tolerance for a model that rounds the far edge outwards.
        return (x + w) <= self.width + 4 and (y + h) <= self.height + 4

    # -------------------------------------------------------- change check
    def looks_like(self, other: Optional['Capture'],
                   max_cell: int = 10, max_mean: float = 2.0) -> bool:
        """Is this the same screen as ``other``, near enough to skip a request?

        Live mode would otherwise send a picture every few seconds whether or
        not anything happened, and a watched window left open would quietly
        cost money all afternoon.

        The comparison is a coarse greyscale grid compared by *brightness*
        rather than by a hash of it. An average hash was the obvious choice and
        the wrong one: it thresholds each cell against the image mean, so on a
        near-uniform screen every cell sits on the boundary and noise flips
        dozens of bits, while on a busy screen a real change can flip none.
        Comparing the values directly has neither failure.

        Deliberately strict - a single cell moving by ``max_cell`` is enough to
        count as changed. Spending a request the user did not strictly need is
        a much smaller failure than not telling them their health bar dropped.
        """
        if other is None or not self._thumb or not other._thumb:
            return False
        if len(self._thumb) != len(other._thumb):
            return False
        worst = 0
        total = 0
        for mine, theirs in zip(self._thumb, other._thumb):
            difference = abs(mine - theirs)
            total += difference
            if difference > worst:
                worst = difference
        if worst > max_cell:
            return False
        return (total / float(len(self._thumb))) <= max_mean


# --------------------------------------------------------------------------- #
# Capturing
# --------------------------------------------------------------------------- #
def _prepare(rgb, origin, source, title='', hwnd=0, screen_size=(0, 0)) -> Capture:
    """Downscale, encode and fingerprint one raw RGB array."""
    from src.ai.agent_tools import _encode_png, _looks_blank

    h0, w0 = rgb.shape[0], rgb.shape[1]
    factor = max(1, math.ceil(max(w0, h0) / float(MAX_SIDE)))
    small = rgb[::factor, ::factor] if factor > 1 else rgb
    height, width = small.shape[0], small.shape[1]

    return Capture(
        png=_encode_png(small), width=width, height=height, factor=factor,
        origin=origin, source=source, title=title, hwnd=hwnd,
        blank=bool(_looks_blank(small)), screen_size=screen_size,
        fingerprint=_fingerprint(small), _thumb=_thumbnail_bits(small))


GRID = 32          # cells per side of the change-detection grid


def _thumbnail_bits(rgb) -> List[int]:
    """A GRID x GRID greyscale summary of the picture, 0..255 per cell.

    Each cell is the *average* of the block it covers, not a sample of one
    pixel: sampling would make the comparison hostage to a single antialiased
    edge, while an average moves only when something in that part of the screen
    really changed.
    """
    try:
        import numpy as np
        height, width = rgb.shape[0], rgb.shape[1]
        if height < GRID or width < GRID:
            return []
        grey = rgb.mean(axis=2)
        rows = np.array_split(grey, GRID, axis=0)
        cells = []
        for band in rows:
            for block in np.array_split(band, GRID, axis=1):
                cells.append(int(block.mean()))
        return cells
    except Exception:
        return []


def _fingerprint(rgb) -> str:
    """A short, comparable id for a picture - only for logs and diagnostics."""
    cells = _thumbnail_bits(rgb)
    if not cells:
        return ''
    import hashlib
    return hashlib.sha1(bytes(value & 0xFF for value in cells)).hexdigest()


def capture_screen() -> Capture:
    """The whole primary monitor."""
    from src.ai.agent_tools import _capture_primary_screen
    rgb, screen_w, screen_h = _capture_primary_screen()
    return _prepare(rgb, (0, 0), 'screen', title='',
                    screen_size=(screen_w, screen_h))


def capture_window(hwnd: int = 0) -> Optional[Capture]:
    """One window, by handle (or the foreground one when no handle is given).

    Two routes, in an order that depends on where the window is:

    * **Cut it out of the desktop grab.** The most faithful picture there is -
      but only of what is actually *visible*, so anything sitting on top of the
      window is in it. That is the normal case for the mimic, whose own window
      is in front by the time it scans.
    * **Ask the window to render itself** (``PrintWindow`` with
      ``PW_RENDERFULLCONTENT``). Draws the window's own content whatever is
      covering it, which is exactly what is needed for a background target -
      it is the same mechanism Windows' own Alt+Tab previews use. Some
      hardware-composited windows report success and draw nothing, which is
      why it is not simply always used.

    ``None`` means neither produced a picture.
    """
    try:
        import win32gui
        from src.ai.agent_tools import _capture_rect, _looks_blank
    except Exception:
        return None

    try:
        hwnd = int(hwnd) or win32gui.GetForegroundWindow()
        if not hwnd or not win32gui.IsWindow(hwnd):
            return None
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        title = win32gui.GetWindowText(hwnd) or ''
    except Exception:
        return None

    if width < 8 or height < 8:
        return None

    screen_size = _screen_size()
    in_front = _is_foreground(hwnd)

    def _from_desktop():
        # Off-screen parts of a window (a dialog half past the edge) would come
        # back as desktop, so clip to what is really on the monitor.
        clip_left, clip_top = max(0, left), max(0, top)
        clip_right = min(screen_size[0], right) if screen_size[0] else right
        clip_bottom = min(screen_size[1], bottom) if screen_size[1] else bottom
        if clip_right - clip_left < 8 or clip_bottom - clip_top < 8:
            return None
        try:
            rgb = _capture_rect(clip_left, clip_top,
                                clip_right - clip_left, clip_bottom - clip_top)
        except Exception:
            return None
        if _looks_blank(rgb):
            return None
        return _prepare(rgb, (clip_left, clip_top), 'window', title=title,
                        hwnd=hwnd, screen_size=screen_size)

    def _from_window():
        rgb = _print_window(hwnd, width, height)
        if rgb is None:
            return None
        return _prepare(rgb, (left, top), 'window', title=title, hwnd=hwnd,
                        screen_size=screen_size)

    routes = (_from_desktop, _from_window) if in_front else (_from_window, _from_desktop)
    for route in routes:
        shot = route()
        if shot is not None:
            return shot
    return None


def _print_window(hwnd: int, width: int, height: int):
    """Render a window's own content, covered or not. RGB array, or None."""
    try:
        import ctypes
        import numpy as np
        import win32gui
        import win32ui
        from src.ai.agent_tools import _looks_blank
    except Exception:
        return None

    hwnd_dc = mfc_dc = save_dc = bmp = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bmp)
        # 3 = PW_CLIENTONLY | PW_RENDERFULLCONTENT: the second flag is what
        # makes this work for DirectComposition/Chromium-style windows.
        ok = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
        bits = bmp.GetBitmapBits(True)
        arr = np.frombuffer(bits, dtype=np.uint8).reshape(height, width, 4)
        rgb = arr[:, :, [2, 1, 0]].copy()
        if not ok or _looks_blank(rgb):
            return None
        return rgb
    except Exception:
        return None
    finally:
        try:
            if bmp is not None:
                win32gui.DeleteObject(bmp.GetHandle())
            if save_dc is not None:
                save_dc.DeleteDC()
            if mfc_dc is not None:
                mfc_dc.DeleteDC()
            if hwnd_dc is not None:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass


def _is_foreground(hwnd: int) -> bool:
    try:
        import win32gui
        return int(win32gui.GetForegroundWindow()) == int(hwnd)
    except Exception:
        return False


def capture(scope: str = 'window', hwnd: int = 0) -> Capture:
    """Take the picture the user asked for, degrading rather than failing.

    ``hwnd`` is the window the *user* was in, remembered before the mimic
    opened. Without it "the window in front" would be the mimic itself the
    moment it has focus, and every scan would photograph Titan reading Titan.

    ``scope='window'`` falls back to the whole screen when the window cannot be
    captured, because a picture of the screen is still useful and "I could not
    take a picture" is not.
    """
    if scope == 'window':
        window = capture_window(hwnd)
        if window is not None and not window.blank:
            return window
        screen = capture_screen()
        if window is not None and screen.blank:
            return window
        return screen
    return capture_screen()


def _screen_size() -> Tuple[int, int]:
    try:
        import win32api
        import win32con
        return (win32api.GetSystemMetrics(win32con.SM_CXSCREEN),
                win32api.GetSystemMetrics(win32con.SM_CYSCREEN))
    except Exception:
        return (0, 0)


def foreground_window() -> Tuple[int, str]:
    """(handle, title) of whatever is in front right now.

    Called *before* the mimic window exists, and the answer is kept for the
    lifetime of that mimic: the whole feature is about one particular program,
    and "whichever window happens to be in front when the timer fires" is not
    that program once Titan's own window is on screen.
    """
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return 0, ''
        return int(hwnd), win32gui.GetWindowText(hwnd) or ''
    except Exception:
        return 0, ''


def foreground_window_title() -> str:
    return foreground_window()[1]


def window_alive(hwnd: int) -> bool:
    """Is this handle still a real window? A closed target must be noticed."""
    if not hwnd:
        return False
    try:
        import win32gui
        return bool(win32gui.IsWindow(hwnd))
    except Exception:
        return False

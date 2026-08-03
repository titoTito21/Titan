# -*- coding: utf-8 -*-
"""Pressing a control in the real application.

The mimic is not a report - Enter on a row has to actually press the thing.
That is the part of this package that touches somebody else's program, so it is
the part with the rules:

* **Only where the user pointed.** A click is sent to the centre of the
  rectangle of the row the user activated. There is no automation loop, no
  "and then click Next"; each action is one keypress by one person.
* **Only into the window that was read.** The target window is raised first and
  the click is refused if the point is not inside it any more. The screen the
  mimic is showing is a photograph, possibly seconds old; between the photo and
  the click the user may have alt-tabbed, and a click aimed at a button in a
  game must never land in whatever took its place.
* **Only when allowed.** Settings, AI features has a switch; with it off the
  mimic reads and never touches.

The mouse is put back where it was afterwards, because a pointer parked in a
game's viewport can be a stuck camera.
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

from src.ai import ai_provider

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010


class ActionRefused(RuntimeError):
    """The action was not performed; the message is meant to be spoken."""


def can_act() -> bool:
    return ai_provider.get_ocr_can_act()


def _require_action() -> None:
    if not can_act():
        raise ActionRefused(
            "Pressing controls is switched off. Turn on 'Let AI OCR press "
            "controls' in Settings, AI features.")


def _require_shot(screen):
    shot = getattr(screen, 'capture', None)
    if shot is None:
        raise ActionRefused("This reading is too old to press anything in.")
    return shot


def _require_keyboard():
    try:
        import keyboard
    except Exception as exc:
        raise ActionRefused(
            f"The keyboard library is unavailable: {exc}") from exc
    return keyboard


def activate(screen, element, button: str = 'left') -> str:
    """Press ``element``. Returns a short English sentence describing what happened."""
    _require_action()
    if element is None or element.rect is None:
        raise ActionRefused("This entry has no position on screen, so it "
                            "cannot be pressed. It can only be read.")
    if not element.enabled:
        raise ActionRefused(f"{element.name or 'This control'} is disabled.")

    shot = _require_shot(screen)
    x, y = shot.centre_of(element.rect)
    _focus_target(shot)
    _check_point_belongs(shot, x, y)
    _click(x, y, button)
    return f"Pressed {element.name or element.spoken()}"


def set_text(screen, element, text: str) -> str:
    """Replace the contents of a text field with ``text``.

    Click into it, select everything, type. Select-all-then-type rather than
    "clear then type" because a field with an input mask (a date, an IP
    address) rejects an empty state, and because Backspace-in-a-loop is exactly
    the kind of thing that goes wrong in somebody else's program.
    """
    _require_action()
    if element is None or element.rect is None:
        raise ActionRefused("This field has no position on screen, so nothing "
                            "can be typed into it.")
    if not element.enabled:
        raise ActionRefused(f"{element.name or 'This field'} is disabled.")

    shot = _require_shot(screen)
    keyboard = _require_keyboard()
    x, y = shot.centre_of(element.rect)
    _focus_target(shot)
    _check_point_belongs(shot, x, y)
    _click(x, y, 'left', restore_cursor=False)
    time.sleep(0.12)
    try:
        keyboard.send('ctrl+a')
        time.sleep(0.05)
        if text:
            keyboard.write(text, delay=0.005)
        else:
            keyboard.send('delete')
    except Exception as exc:
        raise ActionRefused(f"Could not type into the field: {exc}") from exc
    finally:
        _restore_cursor()
    return f"Typed into {element.name or 'the field'}"


def toggle(screen, element) -> str:
    """Tick or untick a checkbox, or select a radio button, by clicking it."""
    _require_action()
    if element is None or element.rect is None:
        raise ActionRefused("This control has no position on screen, so it "
                            "cannot be changed.")
    if not element.enabled:
        raise ActionRefused(f"{element.name or 'This control'} is disabled.")
    shot = _require_shot(screen)
    x, y = shot.centre_of(element.rect)
    _focus_target(shot)
    _check_point_belongs(shot, x, y)
    _click(x, y)
    return f"Changed {element.name or 'the control'}"


def set_slider(screen, element, value: float) -> str:
    """Move a slider to ``value``, which must be inside the element's range.

    Clicking a point along the track is how a slider is set with a mouse in
    every common toolkit, and unlike dragging the thumb it needs no knowledge
    of where the thumb currently is. The track is taken to be the long axis of
    the element's rectangle, inset by half a thumb at each end - without that
    inset the extremes are unreachable, because the thumb's centre never gets
    to the very edge.
    """
    _require_action()
    if element is None or element.rect is None:
        raise ActionRefused("This slider has no position on screen.")
    if not element.enabled:
        raise ActionRefused(f"{element.name or 'This slider'} is disabled.")
    if not element.has_range:
        raise ActionRefused(
            "The range of this slider is not known, so it cannot be set to a "
            "value. Use the left and right arrow keys to nudge it instead.")

    shot = _require_shot(screen)
    low, high = element.minimum, element.maximum
    value = max(low, min(high, float(value)))
    fraction = (value - low) / float(high - low)

    left, top, width, height = shot.rect_to_screen(element.rect)
    horizontal = width >= height
    inset = min(8, (width if horizontal else height) // 6)
    if horizontal:
        span = max(1, width - 2 * inset)
        x = left + inset + int(round(fraction * span))
        y = top + height // 2
    else:
        # A vertical slider's maximum is at the TOP, so the fraction runs the
        # other way. Getting this backwards would silently set the opposite.
        span = max(1, height - 2 * inset)
        x = left + width // 2
        y = top + inset + int(round((1.0 - fraction) * span))

    _focus_target(shot)
    _check_point_belongs(shot, x, y)
    _click(x, y)
    return f"Set {element.name or 'the slider'} to {value:g}"


def nudge(screen, element, direction: int) -> str:
    """Move a slider one step with the keyboard: click it, then press an arrow.

    The fallback for a slider whose range nobody knows, and the safer route in
    general - the application decides what one step means.
    """
    _require_action()
    if element is None or element.rect is None:
        raise ActionRefused("This control has no position on screen.")
    shot = _require_shot(screen)
    keyboard = _require_keyboard()
    x, y = shot.centre_of(element.rect)
    _focus_target(shot)
    _check_point_belongs(shot, x, y)
    _click(x, y, restore_cursor=False)
    time.sleep(0.1)
    try:
        keyboard.send('right' if direction > 0 else 'left')
    except Exception as exc:
        raise ActionRefused(f"Could not nudge it: {exc}") from exc
    finally:
        _restore_cursor()
    return ("Nudged {name} up".format(name=element.name or 'the slider')
            if direction > 0
            else "Nudged {name} down".format(name=element.name or 'the slider'))


def send_key(screen, key: str) -> str:
    """Send one key to the window that was read (Escape, Enter, Tab, arrows).

    A custom-drawn menu often responds to the keyboard even when it exposes
    nothing readable, so this is frequently the safer way in - no coordinates
    involved at all.
    """
    _require_action()
    shot = getattr(screen, 'capture', None)
    if shot is not None:
        _focus_target(shot)
    keyboard = _require_keyboard()
    try:
        keyboard.send(key)
    except Exception as exc:
        raise ActionRefused(f"Could not send {key}: {exc}") from exc
    return f"Sent {key}"


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _focus_target(shot) -> None:
    """Bring the window that was read back to the front, and wait for it.

    Without this the click would land on a window that is merely *at* those
    coordinates rather than the one the user is looking at in the mimic.
    """
    hwnd = getattr(shot, 'hwnd', 0)
    if not hwnd:
        return
    try:
        import win32gui
        if not win32gui.IsWindow(hwnd):
            raise ActionRefused(
                "The window this reading came from has been closed.")
        if win32gui.GetForegroundWindow() == hwnd:
            return
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            # Windows refuses the call from a background process often enough
            # that failing here would make the feature unreliable; the
            # ownership check below is what actually keeps the click safe.
            pass
        # Give the target a moment to come up before aiming at it.
        for _attempt in range(20):
            if win32gui.GetForegroundWindow() == hwnd:
                break
            time.sleep(0.02)
    except ActionRefused:
        raise
    except Exception:
        pass


def _check_point_belongs(shot, x: int, y: int) -> None:
    """Refuse to click when the point is no longer inside the read window."""
    hwnd = getattr(shot, 'hwnd', 0)
    if not hwnd or getattr(shot, 'source', '') != 'window':
        return
    try:
        import win32gui
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        return
    if not (left <= x <= right and top <= y <= bottom):
        raise ActionRefused(
            "That control is no longer where it was when the screen was read. "
            "Press F5 to look again.")
    try:
        import win32gui
        at_point = win32gui.WindowFromPoint((int(x), int(y)))
        root = win32gui.GetAncestor(at_point, 2)      # GA_ROOT
        if root and root != hwnd:
            raise ActionRefused(
                "Something else is now covering that control. Press F5 to look "
                "again.")
    except ActionRefused:
        raise
    except Exception:
        pass


# Where the pointer was before we borrowed it. A pointer left parked in a
# game's viewport is a stuck camera, so it always goes back - but only once the
# whole action is over, which is why a click that is followed by typing defers
# the restore to its caller.
_parked_cursor = None


def _click(x: int, y: int, button: str = 'left',
           restore_cursor: bool = True) -> None:
    global _parked_cursor
    import ctypes
    user32 = ctypes.windll.user32
    if _parked_cursor is None:
        _parked_cursor = _cursor_position()
    down, up = ((MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if button == 'right'
                else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
    try:
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.03)
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(up, 0, 0, 0, 0)
    finally:
        if restore_cursor:
            time.sleep(0.05)
            _restore_cursor()


def _restore_cursor() -> None:
    global _parked_cursor
    previous, _parked_cursor = _parked_cursor, None
    if previous is None:
        return
    try:
        import ctypes
        ctypes.windll.user32.SetCursorPos(previous[0], previous[1])
    except Exception:
        pass


def _cursor_position() -> Optional[Tuple[int, int]]:
    try:
        import ctypes
        from ctypes import wintypes
        point = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return int(point.x), int(point.y)
    except Exception:
        return None

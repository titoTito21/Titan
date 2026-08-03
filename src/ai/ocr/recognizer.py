# -*- coding: utf-8 -*-
"""Picture in, Screen out.

The whole pipeline lives here, in the order it runs:

1. **Capture** the window (or the screen) - :mod:`src.ai.ocr.capture`.
2. **Skip** the request entirely when the picture has not meaningfully changed
   since the last one. Live mode is only affordable because of this step: a
   static menu costs one request no matter how long it is watched.
3. **Ask** the model to read it, with a prompt whose whole job is to stop the
   two failure modes that matter - inventing controls that are not there, and
   guessing rectangles.
4. **Merge** in what UI Automation knows, which overrides the model on geometry
   and state wherever both describe the same control.
5. **Validate** - anything positioned outside the picture loses its rectangle
   and becomes read-only rather than clickable.

Everything is synchronous and thread-safe; the caller runs it on a worker
thread and marshals the result back with ``wx.CallAfter``. Nothing here imports
wx, so the recogniser can also be driven from a component, a gamepad mode or a
test.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from src.ai import ai_provider
from src.ai.ocr import capture as capture_mod
from src.ai.ocr import model as model_mod
from src.ai.ocr import uia_snapshot

# How many elements the model has to have found before we accept that the
# window really is that empty, rather than that the reading went wrong and
# UI Automation should be asked to fill the gaps.
_SPARSE_THRESHOLD = 4

SYSTEM_PROMPT = (
    "You are the eyes of a blind user who is running a program that gives a "
    "screen reader nothing to read - a game menu, a custom-drawn installer, a "
    "kiosk interface. You are shown a picture of it. Your job is to turn that "
    "picture into an exact, structured description that another program will "
    "render as an accessible list and use to click things for the user.\n\n"
    "Rules, in order of importance:\n"
    "1. TRANSCRIBE, DO NOT INTERPRET. Every label must be the text that is "
    "actually written, character for character, in its original language. "
    "Never translate, never tidy up, never expand an abbreviation.\n"
    "2. NEVER INVENT. If you cannot read something, leave it out and say so in "
    "warnings. A missing entry is a nuisance; an entry that is not really "
    "there sends the user's click somewhere unpredictable.\n"
    "3. RECTANGLES ARE IN THE PIXELS OF THE PICTURE YOU WERE GIVEN, measured "
    "from its top-left corner. Do not scale them, do not normalise them to 0-1 "
    "or 0-1000, do not convert them to anything. Give the rectangle of the "
    "clickable control itself (the button), not of the group around it. If you "
    "are not confident where something is, omit rect rather than guessing.\n"
    "4. Report state you can actually see: greyed-out text means disabled, a "
    "tick means checked, a highlight means selected or focused.\n"
    "5. Group elements into regions the way the screen is laid out, and list "
    "them in reading order - the order a sighted person's eye takes them in.\n"
    "6. Answer with JSON only. No prose before or after it, no code fence."
)


class RecognitionError(RuntimeError):
    """Something stopped the reading; the message is meant to be spoken."""


def read_screen(scope: str = 'window', previous: Optional[model_mod.Screen] = None,
                use_uia: Optional[bool] = None,
                on_stage: Optional[Callable[[str], None]] = None,
                question: str = '', hwnd: int = 0,
                shot: Optional[capture_mod.Capture] = None) -> model_mod.Screen:
    """Read the screen once and return a :class:`Screen`.

    ``hwnd`` is the window to read - remembered by the caller before its own
    window took the focus. ``previous`` lets an unchanged screen be answered
    from the last reading without spending a request; the returned Screen is
    then the previous one with a fresh ``taken_at`` and ``unchanged`` marked in
    its warnings. ``question`` is an optional free-text instruction from the
    user ("is there a Skip button?"), appended to the prompt.

    ``shot`` is a picture the caller has already taken. The overlay takes its
    own, on the UI thread, in the one instant its controls are invisible -
    letting this function take it instead would either photograph the overlay
    or keep the overlay hidden for the whole vision call.

    Raises :class:`RecognitionError` with a speakable message when it cannot.
    """
    def stage(text):
        if on_stage:
            try:
                on_stage(text)
            except Exception:
                pass

    reason = ai_provider.vision_unavailable_reason()
    if reason:
        raise RecognitionError(reason)

    if scope == 'window' and hwnd and not capture_mod.window_alive(hwnd):
        raise RecognitionError(
            "The window this was reading has been closed. Use 'Read a "
            "different window' to pick another one.")

    if shot is None:
        stage('capturing')
        shot = capture_mod.capture(scope, hwnd)
    if shot is None:
        raise RecognitionError("The screen could not be captured.")
    if shot.blank:
        raise RecognitionError(
            "The capture came back empty. This usually means the program is "
            "running in exclusive full-screen mode, which cannot be "
            "photographed. Switch it to windowed or borderless mode and try "
            "again.")

    if previous is not None and previous.capture is not None and not question:
        if shot.looks_like(previous.capture):
            refreshed = previous
            refreshed.taken_at = time.time()
            refreshed.capture = shot
            if 'unchanged' not in refreshed.warnings:
                refreshed.warnings = list(refreshed.warnings) + ['unchanged']
            return refreshed

    stage('reading')
    prompt = _build_prompt(shot, question)
    try:
        answer = ai_provider.generate_vision(SYSTEM_PROMPT, prompt, [shot.png],
                                             max_tokens=8000)
    except Exception as exc:
        raise RecognitionError(f"The model could not read the screen: {exc}") from exc

    screen = model_mod.from_ai(answer, capture=shot)
    if not screen.title:
        screen.title = shot.title or 'Screen'

    if use_uia is None:
        use_uia = ai_provider.get_ocr_use_uia()
    # Only when the target really is the window in front: the UIA snapshot
    # reads the *foreground* window, so merging it into a picture of some other
    # window would move controls to positions from an entirely different app.
    if use_uia and shot.source == 'window' and _is_foreground(shot.hwnd):
        stage('checking')
        try:
            known = uia_snapshot.snapshot()
        except Exception as exc:
            known = []
            print(f"[AI OCR] UI Automation unavailable: {exc}")
        if known:
            matched = uia_snapshot.merge(screen, shot, known)
            if len(screen.elements) < _SPARSE_THRESHOLD:
                added = uia_snapshot.add_missing(screen, shot, known,
                                                 'Reported by Windows')
                if added:
                    screen.warnings.append(
                        f"{added} control(s) came from Windows itself, not from "
                        f"the picture")
            if matched:
                screen.warnings.append(
                    f"{matched} control position(s) confirmed against Windows")
    return screen


def _is_foreground(hwnd: int) -> bool:
    if not hwnd:
        return False
    try:
        import win32gui
        return int(win32gui.GetForegroundWindow()) == int(hwnd)
    except Exception:
        return False


def _build_prompt(shot, question: str) -> str:
    where = ("the window the user is working in" if shot.source == 'window'
             else "the whole screen")
    lines = [
        f"This picture is {where}."
        + (f" Its title bar says: {shot.title!r}." if shot.title else ""),
        f"The picture is {shot.width} pixels wide and {shot.height} pixels tall. "
        f"Every rect you give must be inside those bounds, in these pixels.",
    ]
    if shot.source != 'window':
        # A whole-screen shot has Titan's own reader window in it, and listing
        # its controls back to the user would be a mirror, not a reading.
        lines.append(
            "Ignore any window titled 'AI OCR' - that is the accessibility "
            "tool doing the reading, not part of what the user is working on.")
    lines += ["", "Answer with exactly this JSON shape:", model_mod.SCHEMA_TEXT]
    if question:
        lines += ["",
                  "The user also asked, and this takes priority over covering "
                  "everything: " + question]
    return '\n'.join(lines)


# --------------------------------------------------------------------------- #
# Background reading
# --------------------------------------------------------------------------- #
class Reader:
    """Runs readings on a worker thread, one at a time.

    A scan takes seconds. Two overlapping scans would cost two requests to
    answer one question and could deliver their results out of order, so a
    request that arrives while one is running is dropped rather than queued -
    the answer to "what is on screen now" is not worth waiting in line for.
    """

    def __init__(self):
        self._busy = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self.last: Optional[model_mod.Screen] = None

    @property
    def busy(self) -> bool:
        return self._busy.locked()

    def read(self, on_done: Callable[[Optional[model_mod.Screen], str], None],
             scope: str = 'window', reuse_previous: bool = True,
             on_stage: Optional[Callable[[str], None]] = None,
             question: str = '', hwnd: int = 0,
             shot: Optional[capture_mod.Capture] = None) -> bool:
        """Start a reading. ``on_done(screen, error)`` runs on the worker thread.

        Returns False when a reading was already in flight.
        """
        if not self._busy.acquire(blocking=False):
            return False

        def _work():
            screen, error = None, ''
            try:
                screen = read_screen(
                    scope=scope, hwnd=hwnd, shot=shot,
                    previous=self.last if reuse_previous else None,
                    on_stage=on_stage, question=question)
                self.last = screen
            except RecognitionError as exc:
                error = str(exc)
            except Exception as exc:
                error = f"Reading the screen failed: {exc}"
            finally:
                self._busy.release()
            try:
                on_done(screen, error)
            except Exception as exc:
                print(f"[AI OCR] result handler failed: {exc}")

        self._thread = threading.Thread(target=_work, daemon=True,
                                        name='ai-ocr-reader')
        self._thread.start()
        return True

    def forget(self) -> None:
        """Drop the cached reading, so the next scan really re-reads."""
        self.last = None

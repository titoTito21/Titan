# -*- coding: utf-8 -*-
"""The frame a Klango application runs in: its pace, and its way out.

`k_LoopWithRawInput` is Klango's central function and it is an ordinary `while`
loop - `BeginFrame()`, read the input, call the application's step,
`EndFrame()`, again. Everything the platform does about *time* is done in those
two calls, and Cling answered both with `True`:

- **so the game ran as fast as the interpreter could go.** A Klango game's
  clock is real time (`LLib_Time_Game`), so a mole that should be up for two
  seconds still was - but the loop around it spun a whole processor core to
  find that out, thousands of frames for every one Klango would have run, and
  every `loopstep` in the library ran with it.
- **and there was no way out.** `app:loop()` does not return until the game
  ends, so a window that is closed - or a Titan that is shutting down - had
  nothing to interrupt: `KlangoSession.stopping` was set by the engine and read
  by nobody. `Stopped` is raised out of `EndFrame`, which is inside the loop
  and outside every `pcall` the library uses (Cling's `pcall` catches
  `LuaError`, and this is deliberately not one), so it unwinds the whole
  application exactly the way closing its window means it should.

The rate is Klango's own: `_Sys_GetFPS` has always answered 60 here, and an
application asks for it to decide how much it may do in one frame, so running
at a different one would make it wrong about itself.
"""

import time


class Stopped(Exception):
    """The application was asked to stop, from outside its own loop."""


class Frames(object):
    """The clock `_Sys_BeginFrame` / `_Sys_EndFrame` keep."""

    #: Frames a second. `_Sys_GetFPS` answers with this, so the two cannot
    #: disagree about what the application is being told.
    RATE = 60.0

    #: A frame that has already overrun by more than this is not slept off at
    #: all, and the next one starts from now: a game that has been paused by
    #: its window - or by a debugger - must not then run a thousand frames
    #: back to back to "catch up".
    MAX_LAG = 0.25

    def __init__(self, should_stop=None, interpreter=None):
        self.should_stop = should_stop or (lambda: False)
        #: The interpreter whose step budget this frame resets, if any.
        #:
        #: The budget is there so an application's own runaway loop cannot
        #: take the desktop with it, and it was counted over the whole RUN -
        #: which is fine for a script and wrong for a game: Dice Poker
        #: reached it after three thousand frames and stopped in the middle
        #: of a hand. A frame is the right unit. A loop that never finishes
        #: never reaches `EndFrame`, so it still trips the ceiling; a game
        #: played for an hour never does.
        self.interpreter = interpreter
        self.period = 1.0 / self.RATE
        self.frames = 0
        self.slept = 0.0
        self._next = 0.0
        #: What else happens once per frame. A Klango sequence schedules its
        #: sounds ahead of time and something has to start them when their
        #: moment comes; the frame is where the platform already yields, so
        #: it is where that is done rather than on a thread of its own.
        self.callbacks = []

    def on_frame(self, callback):
        self.callbacks.append(callback)

    def begin(self):
        self.frames += 1
        if self.should_stop():
            raise Stopped()
        if self.interpreter is not None:
            self.interpreter.steps = 0
        for callback in self.callbacks:
            callback()
        return True

    def end(self, immediately=False):
        """Wait out what is left of this frame, unless asked not to.

        `EndFrame(1)` - Klango's own "no delay" - is used where the library
        wants a frame to happen and not to cost anything, so it is honoured;
        the deadline still moves on, or the next ordinary frame would sleep
        for a frame it never had.
        """
        if self.should_stop():
            raise Stopped()
        now = time.time()
        if not self._next:
            self._next = now
        self._next += self.period
        if immediately:
            if self._next < now - self.MAX_LAG:
                self._next = now
            return True
        remaining = self._next - now
        if remaining > 0:
            time.sleep(min(remaining, self.period))
            self.slept += remaining
        elif remaining < -self.MAX_LAG:
            self._next = now
        return True

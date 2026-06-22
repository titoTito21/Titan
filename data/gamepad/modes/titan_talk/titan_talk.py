"""
Titan Talk - talking gamepad (joystick-driven screen reader)
============================================================

An external gamepad mode that turns the controller into a screen reader. The
left stick (and d-pad) walk *spatially* between on-screen controls, A activates
the current control, B goes back. The control list is an in-memory BUFFER,
navigated and spoken like a screen reader's browse mode - there is no separate
visible window.

A short bumper TAP switches the navigation scope (a "tab"); HOLDING a bumper
still changes the controller mode at the host level. Scopes:

  * Window switcher  - move between open windows, A focuses one
  * Window controls  - native controls of the focused window via UI Automation
  * Audio game       - games with no accessibility, read by Gemini vision/OCR

Controls speak respecting the host sound positioning mode (none / stereo / 3D):
the stereo pan follows each control's position on screen, and the control's
name is spoken in a slightly lower tone so it stands out from spoken help.

Dependencies are vendored in ``lib/`` (uiautomation, Pillow, google-
generativeai); ``pywinctl`` for the window switcher is already a core Titan
dependency.
"""

import time

from src.controller.gamepad_mode_api import GamepadMode

from tt_core import (_, Control, speak, speak_segments, pitched_speech_active,
                     play_mode_sound, play_positioned, foreground_window,
                     role_label, state_label, pan_for_x,
                     NAME_PITCH, ROLE_PITCH, STATE_PITCH,
                     SND_CURSOR, SND_EDGE, SND_WINDOW)
from tt_scope_windows import WindowSwitcherScope
from tt_scope_uia import UIAScope
from tt_scope_gemini import GeminiScope

# Scope classes in bumper-cycle order.
_SCOPE_CLASSES = [WindowSwitcherScope, UIAScope, GeminiScope]


class TitanTalkMode(GamepadMode):
    name = "Titan Talk"

    def __init__(self):
        self.scopes = []
        self.scope_index = 0
        # Last announced grouping container, to detect entering / leaving one.
        self._last_container = None
        # Foreground-window monitor state.
        self._last_fg_hwnd = 0
        self._fg_active = False
        self._fg_timer = None
        self._fg_announced_at = 0.0

    # -- scope management --------------------------------------------------- #
    def _build_scopes(self):
        self.scopes = []
        for cls in _SCOPE_CLASSES:
            try:
                scope = cls(self)
                if scope.available():
                    self.scopes.append(scope)
            except Exception as e:
                print(f"[TitanTalk] could not build scope {cls.__name__}: {e}")

    def current_scope(self):
        if 0 <= self.scope_index < len(self.scopes):
            return self.scopes[self.scope_index]
        return None

    def _enter_scope_index(self, idx, sound=True):
        if not self.scopes:
            return
        old = self.current_scope()
        if old is not None:
            try:
                old.on_leave()
            except Exception:
                pass
        self.scope_index = idx % len(self.scopes)
        self._last_container = None
        if sound:
            play_mode_sound(SND_WINDOW)
        try:
            self.current_scope().on_enter()
        except Exception as e:
            print(f"[TitanTalk] scope enter failed: {e}")

    def _switch_scope(self, step):
        if len(self.scopes) < 2:
            play_mode_sound(SND_EDGE)
            return
        self._enter_scope_index(self.scope_index + step)

    def refresh_current_scope(self, delay_ms=0):
        """Re-read the current scope's buffer (e.g. after activating a control
        that opened a new window or navigated a menu). Re-enters the SAME scope
        so its on_enter rescans the now-foreground window and announces it."""
        idx = self.scope_index

        def do():
            # If the foreground window changed, the foreground monitor owns the
            # announcement - skip so we don't double up. Also skip if it just
            # announced a window change.
            hwnd, _t = foreground_window()
            if hwnd and hwnd != self._last_fg_hwnd:
                return
            if time.time() - self._fg_announced_at < 0.8:
                return
            self._enter_scope_index(idx, sound=False)
        if delay_ms > 0:
            try:
                import wx
                wx.CallLater(delay_ms, do)
                return
            except Exception:
                pass
        do()

    def switch_to_scope(self, scope_id, delay_ms=0):
        """Jump to the scope with the given id (e.g. a window-switcher A press
        moving you into that window's controls). A small delay lets the focus
        change settle before the UIA scope reads the now-foreground window."""
        idx = next((i for i, s in enumerate(self.scopes)
                    if s.id == scope_id), None)
        if idx is None:
            return False
        if delay_ms > 0:
            try:
                import wx
                wx.CallLater(delay_ms, self._enter_scope_index, idx)
                return True
            except Exception:
                pass
        self._enter_scope_index(idx)
        return True

    # -- foreground window monitor ------------------------------------------ #
    # A screen reader announces the new window when you Alt+Tab (or any app
    # brings a window to the front). We poll the foreground window on the wx
    # main thread; on a change we announce "<title>, window, <first control>"
    # and refresh the buffer to that window's controls. This also covers our
    # own window-switcher A press and controls that open a new window, so those
    # paths don't announce it themselves (they leave it to this monitor).
    def _start_fg_monitor(self):
        self._fg_active = True
        self._fg_tick()

    def _stop_fg_monitor(self):
        self._fg_active = False
        if self._fg_timer is not None:
            try:
                self._fg_timer.Stop()
            except Exception:
                pass
            self._fg_timer = None

    def _fg_tick(self):
        try:
            self._check_foreground()
        finally:
            if self._fg_active:
                try:
                    import wx
                    self._fg_timer = wx.CallLater(500, self._fg_tick)
                except Exception:
                    self._fg_active = False

    def _check_foreground(self):
        if not self.scopes:
            return
        hwnd, title = foreground_window()
        if not hwnd or hwnd == self._last_fg_hwnd:
            return
        self._last_fg_hwnd = hwnd
        if not title.strip():
            return  # nameless / transient window
        self._announce_foreground(title)

    def _announce_foreground(self, title):
        """Announce a newly focused window and read its controls."""
        self._fg_announced_at = time.time()
        play_mode_sound(SND_WINDOW)
        idx = next((i for i, s in enumerate(self.scopes)
                    if s.id == 'uia'), None)
        if idx is None:
            self.announce_control(Control(name=title, role='window'))
            return
        old = self.current_scope()
        if old is not None and old is not self.scopes[idx]:
            try:
                old.on_leave()
            except Exception:
                pass
        self.scope_index = idx
        self._last_container = None
        scope = self.current_scope()
        try:
            scope.refresh()
            scope.index = 0 if scope.controls else -1
        except Exception as e:
            print(f"[TitanTalk] foreground refresh failed: {e}")
        # "window name, window, first control" - the window itself is announced
        # as the prefix (name + the 'window' role), then the first control.
        win_label = "{}, {}".format(title, role_label('window'))
        self.announce_control(scope.current(), prefix=win_label)

    # -- announcements ------------------------------------------------------ #
    def announce_control(self, ctrl, prefix=''):
        """Announce a control. With Titan TTS the name / type / state are spoken
        at different pitches; with the accessible_output3 fallback (no pitch
        control) they are spoken as one plain line."""
        if ctrl is None:
            speak(prefix or _("Empty"))
            return
        name = ctrl.name or _("Unnamed")
        role = role_label(ctrl.role)
        state_bits = []
        if ctrl.value:
            state_bits.append(ctrl.value)
        if ctrl.state:
            state_bits.append(state_label(ctrl.state))
        state = ", ".join(state_bits)
        pos = pan_for_x(ctrl.cx)

        if pitched_speech_active():
            segments = []
            if prefix:
                segments.append((prefix, NAME_PITCH, pos))
            segments.append((name, NAME_PITCH, pos))          # name: normal tone
            segments.append((role, ROLE_PITCH, pos))          # type: lower tone
            if state:
                segments.append((state, STATE_PITCH, pos))    # state: higher tone
            speak_segments(segments)
        else:
            line = ", ".join(p for p in (prefix, name, role, state) if p)
            speak(line, position=pos)

    def announce_current(self, prefix=''):
        scope = self.current_scope()
        self.announce_control(scope.current() if scope else None, prefix)

    def _container_transition(self, ctrl):
        """Speak-prefix for entering / leaving a grouping container.

        Compares the control's container with the last one and returns e.g.
        "out of Application list, in Toolbar" - announced like a screen reader
        when the spatial cursor crosses a list / menu / group boundary.
        """
        new = getattr(ctrl, 'container', None) if ctrl else None
        new_key = new[0] if new else None
        old = self._last_container
        old_key = old[0] if old else None
        bits = []
        if new_key != old_key:
            if old_key is not None:
                bits.append(_("out of {name}").format(name=old[1]))
            if new_key is not None:
                bits.append(_("in {name}").format(name=new[1]))
        self._last_container = new
        return ", ".join(bits)

    def announce_current_moved(self):
        """Announce after a cursor move, including any container transition."""
        scope = self.current_scope()
        ctrl = scope.current() if scope else None
        context = self._container_transition(ctrl)
        self.announce_control(ctrl, prefix=context)

    def announce_scope_enter(self, scope):
        """Default scope-entry announcement (scope name + first control)."""
        self._last_container = None
        name = scope.display_name()
        ctrl = scope.current()
        context = self._container_transition(ctrl)
        prefix = "{}, {}".format(name, context) if context else name
        if ctrl is None:
            speak("{name}, {empty}".format(name=name, empty=_("empty")))
        else:
            self.announce_control(ctrl, prefix=prefix)

    # -- API hooks ---------------------------------------------------------- #
    def on_activate(self, manager):
        self._build_scopes()
        if not self.scopes:
            speak(_("Titan Talk has no available scopes."))
            return
        self.scope_index = 0
        self._last_container = None
        scope = self.current_scope()
        try:
            scope.on_enter(announce=False)
        except Exception as e:
            print(f"[TitanTalk] initial scope enter failed: {e}")
        speak(_("Titan Talk. Left stick reads controls, A activates, B goes "
                "back, bumpers switch scope. Scope: {name}.").format(
                    name=scope.display_name()))
        # Start watching for foreground-window changes (Alt+Tab etc.).
        self._last_fg_hwnd = foreground_window()[0]
        self._start_fg_monitor()

    def on_deactivate(self, manager):
        self._stop_fg_monitor()

    def _move(self, dx, dy):
        scope = self.current_scope()
        if scope is None:
            return True
        if scope.navigate(dx, dy):
            play_positioned(SND_CURSOR, scope.current())
            self.announce_current_moved()
        else:
            play_positioned(SND_EDGE, scope.current())
        return True

    def handle_axis(self, axis_id, value):
        # Left stick only: axis 0 = X (left/right), axis 1 = Y (up/down).
        if axis_id == 0:
            return self._move(-1 if value < 0 else 1, 0)
        if axis_id == 1:
            return self._move(0, -1 if value < 0 else 1)
        return False

    def handle_hat(self, x, y):
        if x != 0:
            return self._move(-1 if x < 0 else 1, 0)
        if y != 0:
            # pygame hat: +1 = up -> dy -1 (smaller screen y)
            return self._move(0, -1 if y > 0 else 1)
        return False

    def handle_button(self, button_id):
        scope = self.current_scope()
        if scope is None:
            return False
        if button_id == 0:  # A -> activate
            if not scope.activate():
                play_mode_sound(SND_EDGE)
            return True
        if button_id == 1:  # B -> back
            scope.back()
            return True
        if button_id == 3:  # Y -> rescan the current scope
            try:
                scope.refresh()
                scope.index = 0 if scope.controls else -1
            except Exception:
                pass
            self._last_container = None
            play_mode_sound(SND_WINDOW)
            self.announce_current_moved()
            return True
        if button_id == 2:  # X -> repeat the current control
            self.announce_current()
            return True
        return False

    def handle_bumper(self, is_left):
        self._switch_scope(-1 if is_left else 1)
        return True

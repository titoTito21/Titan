# -*- coding: utf-8 -*-
"""The overlay: accessible controls hooked *into* the inaccessible window.

A list of what is on a screen is a report. This is the interface itself. Every
control the reading found becomes a real wx control placed at exactly the
coordinates of the real one - control over control, window over window - and
the whole thing is then **parented into the target window itself**, so there is
no second window in the way. What the user gets is the program they were
already in, except that it now has an accessible surface a screen reader can
read and a keyboard can drive.

How it is hooked on, best first. Whatever succeeds decides how the overlay then
behaves, and the user is told which one they got:

``child``   ``SetParent`` into the target's own ``HWND`` with ``WS_CHILD``.
            The controls become part of that window: Windows moves them with
            it, clips them to it, minimises and restores them with it, and puts
            them away when it closes. Nothing follows anything - there is only
            one window, and it is the program's. Keyboard focus needs the two
            threads' input queues attached, which is what ``_attach_input``
            does.
``owned``   The frame stays a window but is *owned* by the target: no taskbar
            button, always directly above its owner, hidden and restored with
            it. What a cross-process ``SetParent`` refusal falls back to.
``float``   A plain always-on-top frame that follows the target with a timer.
            The last resort, and the only mode that works when the target is
            not a normal window at all.

Two things make it work rather than merely exist:

* **Cloaking.** The controls sit on the exact pixels the next reading has to
  photograph and at the exact points a click has to reach. So before either
  happens the overlay goes fully transparent *and* click-through
  (``WS_EX_TRANSPARENT``), and comes back after. Without it AI OCR would read
  its own controls and click its own buttons.
* **Re-reading after everything.** Every press, tick and typed field is
  followed by a fresh reading, and the controls are rebuilt from it. The
  overlay therefore shows what the program did, never what the user asked for.
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional, Sequence, Tuple

import wx

from src.ai import ai_provider
from src.ai.ocr import actions as actions_mod
from src.ai.ocr import capture as capture_mod
from src.ai.ocr import controls as controls_mod
from src.ai.ocr.model import Element, Screen
from src.ai.ocr.recognizer import Reader
from src.network.im_ui_common import _, apply_skin_tree, speak_notification, speak_titannet

# How see-through the overlay is while it is doing nothing. Not opaque: a
# sighted person has to be able to see the program underneath it, and the user
# has to be able to tell which is which.
ALPHA = 232

# How often the target is checked. In ``child`` and ``owned`` mode this only
# watches for a resize and for the window closing - Windows does the moving.
FOLLOW_MS = 300

# A resize has to hold still this many ticks before it costs a reading, or a
# window dragged by its corner would spend a vision request per tick.
RESIZE_SETTLE = 3

GWL_STYLE = -16
GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8

WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080

SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
HWND_TOP = 0


# --------------------------------------------------------------------------- #
# One surface of the overlay
# --------------------------------------------------------------------------- #
class OverlaySurface(wx.Frame):
    """The controls of one area, hooked onto the real window.

    A frame to begin with because that is the only thing wx will create with no
    parent; a moment later it is usually not a window any more but a child of
    somebody else's, and it spends the rest of its life as part of that window.
    """

    def __init__(self, owner: 'ScreenOverlay', title: str,
                 rect: Tuple[int, int, int, int]):
        super().__init__(None, title=title, pos=(rect[0], rect[1]),
                         size=(rect[2], rect[3]),
                         style=(wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP
                                | wx.BORDER_NONE))
        self.owner = owner
        self.screen_rect = tuple(rect)      # where it is, in screen pixels
        self.origin = (rect[0], rect[1])
        self.panel = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        self.panel.SetSize(rect[2], rect[3])
        self.controls: List[wx.Window] = []
        self.attached_to = 0                # the HWND we became part of
        # How many of our pixels one of the target's pixels is worth. Not 1
        # when the target is DPI-aware and Titan is not (or the other way
        # round) - see _adopt_geometry, which measures it rather than trusting
        # anybody's idea of what the DPI is.
        self.scale = 1.0
        self._elements: Sequence[Element] = ()
        self._shot = None
        self._cloaked = False

        self.SetTransparent(ALPHA)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    # ----------------------------------------------------------------- layout
    def place(self, elements: Sequence[Element], shot) -> int:
        """Build this area's controls where the real ones are."""
        self.clear()
        self._elements, self._shot = list(elements), shot
        width = int(round(self.screen_rect[2] * self.scale))
        height = int(round(self.screen_rect[3] * self.scale))
        self.panel.SetSize(width, height)

        positioned: List[Tuple[Tuple[int, int, int, int], Element]] = []
        loose: List[Element] = []
        for element in elements:
            box = self._box_for(element, shot, width, height)
            if box is None:
                loose.append(element)
            else:
                positioned.append((box, element))

        # Reading order, banded: sorting by y alone interleaves two controls
        # that are side by side but a pixel apart, and Tab would zig-zag.
        positioned.sort(key=lambda item: (item[0][1] // 24, item[0][0]))
        positioned = controls_mod.cluster_radio_runs(
            positioned, element_of=lambda item: item[1])

        # Option buttons are grouped by the order they are built in, so the
        # flags have to be worked out over the final, sorted order.
        starts = controls_mod.group_starts([element for _box, element in positioned])
        for (box, element), first in zip(positioned, starts):
            control = controls_mod.build_control(self.panel, element,
                                                 self.owner.act, first)
            if control is None:
                continue
            control.SetSize(box[0], box[1], box[2], box[3])
            self.controls.append(control)

        if loose:
            self._place_loose(loose, width, height)
        return len(self.controls)

    def _box_for(self, element: Element, shot, width: int,
                 height: int) -> Optional[Tuple[int, int, int, int]]:
        """This element's control, in this surface's own coordinates."""
        if element.rect is None or shot is None:
            return None
        left, top, w, h = shot.rect_to_screen(element.rect)
        # Into this surface's own coordinates, and then into whatever
        # coordinates the window we are part of is measured in.
        x = int(round((left - self.origin[0]) * self.scale))
        y = int(round((top - self.origin[1]) * self.scale))
        w = max(controls_mod.MIN_WIDTH, int(round(w * self.scale)))
        h = max(controls_mod.MIN_HEIGHT, int(round(h * self.scale)))
        # Reported outside this area entirely: it belongs to some other part of
        # the screen, so it goes to the loose strip rather than being dragged
        # to an edge it was never at.
        if x < -w // 2 or y < -h // 2 or x > width or y > height:
            return None
        x = max(0, min(x, max(0, width - w)))
        y = max(0, min(y, max(0, height - h)))
        return (x, y, w, h)

    def _place_loose(self, elements: List[Element], width: int,
                     height: int) -> None:
        """Controls the reading could not place, in a strip along the bottom.

        An element with no rectangle is still real - the model read it, it just
        could not say where. Dropping it would hide a control from the user;
        putting it at a guessed position would send a click somewhere
        unpredictable. The strip is reachable and obviously not claiming to be
        anywhere in particular.
        """
        row_height = controls_mod.MIN_HEIGHT + 6
        x, y = 4, max(0, height - row_height)
        starts = controls_mod.group_starts(elements)
        for element, first in zip(elements, starts):
            control = controls_mod.build_control(self.panel, element,
                                                 self.owner.act, first)
            if control is None:
                continue
            box_width = min(240, max(120, width - x - 4))
            if x + box_width > width - 4:
                x, y = 4, y - row_height
                if y < 0:
                    control.Destroy()
                    break
            control.SetSize(x, y, box_width, controls_mod.MIN_HEIGHT)
            self.controls.append(control)
            x += box_width + 4

    def clear(self) -> None:
        for control in self.controls:
            try:
                control.Destroy()
            except Exception:
                pass
        self.controls = []

    # ---------------------------------------------------------------- hooking
    def hook_onto(self, target_hwnd: int) -> str:
        """Become part of ``target_hwnd``. Returns the mode that worked."""
        handle = int(self.GetHandle() or 0)
        if not handle or not target_hwnd:
            return 'float'

        if _make_child(handle, target_hwnd):
            self.attached_to = target_hwnd
            self._adopt_geometry(handle, target_hwnd)
            return 'child'

        if _make_owned(handle, target_hwnd):
            self.attached_to = target_hwnd
            return 'owned'
        return 'float'

    def _adopt_geometry(self, handle: int, target_hwnd: int) -> None:
        """Sit exactly over the target, in the target's own coordinates.

        A child's position is relative to its parent's client area, and the
        coordinates in the reading are screen pixels - but that is only half of
        it. When the target's process is DPI-aware and Titan's is not (which is
        the normal case for a game or a launcher on a scaled display, and
        exactly what REDlauncher does at 125%), Windows scales our window on the
        way into the target's world: ask for 870 wide and 696 arrives, every
        control shrinking and creeping up-left with it.

        Rather than trying to work the ratio out from two DPI values and two
        awareness contexts, it is *measured*: place the surface, read back what
        actually happened, and scale everything by the difference. That is
        correct whatever the reason for the mismatch, including none at all.
        """
        client_x, client_y = _client_origin(target_hwnd)
        x = self.origin[0] - client_x
        y = self.origin[1] - client_y
        width, height = self.screen_rect[2], self.screen_rect[3]
        _move_child(handle, x, y, width, height)

        scale = _measured_scale(handle, width, height)
        if abs(scale - 1.0) <= 0.01:
            return
        self.scale = scale
        _move_child(handle, int(round(x * scale)), int(round(y * scale)),
                    int(round(width * scale)), int(round(height * scale)))
        if self._shot is not None:
            # The controls were built in the coordinates we thought we had;
            # build them again in the ones we turned out to be given.
            self.place(self._elements, self._shot)

    def unhook(self) -> None:
        """Come back off the target before being destroyed.

        A child window is destroyed by Windows together with its parent, and wx
        would later try to destroy a handle that no longer exists. Detaching
        first means the overlay owns its own lifetime again whatever the target
        does next.
        """
        handle = int(self.GetHandle() or 0)
        if handle and self.attached_to:
            _detach(handle)
        self.attached_to = 0

    def move_to(self, x: int, y: int) -> None:
        """Only used in ``float`` mode; the other two are moved by Windows."""
        self.origin = (x, y)
        self.SetPosition((x, y))

    # ------------------------------------------------------------------ focus
    def focus_first(self) -> bool:
        for control in self.controls:
            if controls_mod.focusable(control):
                self.take_focus(controls_mod.focus_target(control))
                return True
        return False

    def take_focus(self, window: wx.Window) -> None:
        """Focus a control, including when we are a child of another process.

        Focus belongs to a thread's input queue, and as a child of somebody
        else's window we are not in the queue that has it - so wx's SetFocus
        alone is quietly ignored. ``_attach_input`` joins the two queues for as
        long as the overlay is up, and the Win32 call is what actually moves
        the focus once they are joined.
        """
        try:
            window.SetFocus()
        except Exception:
            return
        if not self.attached_to:
            return
        try:
            import ctypes
            ctypes.windll.user32.SetFocus(int(window.GetHandle()))
        except Exception:
            pass

    def focus_key(self) -> str:
        window = self.FindFocus()
        while window is not None and window is not self:
            element = getattr(window, '_ocr_element', None)
            if element is not None:
                return element.key
            window = window.GetParent()
        return ''

    def focus_by_key(self, key: str) -> bool:
        for control in self.controls:
            element = getattr(control, '_ocr_element', None)
            if element is not None and element.key == key \
                    and controls_mod.focusable(control):
                self.take_focus(controls_mod.focus_target(control))
                return True
        return False

    def focused_element(self) -> Optional[Element]:
        window = self.FindFocus()
        while window is not None and window is not self:
            element = getattr(window, '_ocr_element', None)
            if element is not None:
                return element
            window = window.GetParent()
        return None

    # --------------------------------------------------------------- cloaking
    def cloak(self, hidden: bool) -> None:
        """Invisible to the camera and to the mouse, or back to normal.

        Not ``Hide()``: hiding takes the focus away and gives it to whatever is
        behind, so a re-reading would drop the user into the program every few
        seconds. Fully transparent keeps the focus exactly where it is while
        contributing nothing to the picture, and ``WS_EX_TRANSPARENT`` takes it
        out of hit testing so a click aimed at the real control goes through.
        """
        if hidden == self._cloaked:
            return
        self._cloaked = hidden
        try:
            self.SetTransparent(0 if hidden else ALPHA)
        except Exception:
            pass
        _set_click_through(int(self.GetHandle() or 0), hidden)

    # ------------------------------------------------------------------- keys
    def _on_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        modifiers = event.GetModifiers()

        if code == wx.WXK_ESCAPE:
            self.owner.close()
            return
        if code == wx.WXK_F5:
            self.owner.rescan()
            return
        if code == wx.WXK_F6:
            self.owner.focus_next_surface(self)
            return
        if code == wx.WXK_F10 or (code == wx.WXK_MENU and not modifiers):
            self.owner.open_menu_bar(self)
            return
        if modifiers == wx.MOD_CONTROL and code == ord('R'):
            self.owner.speak_focused(self)
            return
        if modifiers == wx.MOD_CONTROL and code == ord('S'):
            self.owner.speak_summary()
            return
        if modifiers == wx.MOD_CONTROL and code == ord('H'):
            self.owner.toggle_cloak()
            return
        event.Skip()

    def _on_close(self, event: wx.CloseEvent) -> None:
        self.owner.close()
        event.Skip()


# --------------------------------------------------------------------------- #
# The overlay
# --------------------------------------------------------------------------- #
class ScreenOverlay:
    """Every surface of one overlay, and everything that keeps it true."""

    def __init__(self, screen: Screen, scope: str = 'window',
                 target_hwnd: int = 0, reader: Optional[Reader] = None,
                 on_closed: Optional[Callable[[], None]] = None,
                 target_title: str = ''):
        self.screen = screen
        self.scope = scope or 'window'
        self.target_hwnd = int(target_hwnd or getattr(screen.capture, 'hwnd', 0) or 0)
        self.target_title = target_title or getattr(screen.capture, 'title', '') or ''
        self.reader = reader or Reader()
        self.on_closed = on_closed

        self.surfaces: List[OverlaySurface] = []
        self.root: Optional[OverlaySurface] = None
        self.mode = 'float'
        self._timer: Optional[wx.Timer] = None
        self._target_rect: Optional[Tuple[int, int, int, int]] = None
        self._resize_ticks = 0
        self._input_attached = False
        self._scanning = False
        self._closing = False
        self._acting = False
        self._user_cloaked = False
        # Put away by the user with the AI OCR shortcut: the controls stay
        # built and stay hooked on, but they are out of the window and out of
        # the keyboard until the same shortcut brings them back.
        self.hidden = False
        self._was_in_front = True
        # Set while something is cloaking, capturing or re-placing the
        # controls. The follow timer keeps its hands off during those.
        self._busy = False
        self._pending_focus = ''

    # ------------------------------------------------------------------- open
    def open(self) -> bool:
        """Build the surfaces and hook them on. False when there is nothing."""
        if self.screen is None or self.screen.capture is None:
            speak_notification(_("There is no reading to build an overlay from. "
                                 "Read the screen first."), 'warning')
            return False

        built = self._build()
        if not built:
            self._destroy_surfaces()
            speak_notification(
                _("Nothing on this screen could be placed where it really is, "
                  "so there is nothing to overlay. Use the reading list "
                  "instead."), 'warning')
            return False

        self._target_rect = _window_rect(self.target_hwnd)
        self._show_all()
        self._hook()
        self._focus_top()
        self._start_following()
        speak_titannet(self._opening_words(built))
        return True

    def _opening_words(self, count: int) -> str:
        return _("{title}: {n} controls, where the real ones are. Tab moves "
                 "between them, Enter presses, F5 reads the screen again, "
                 "Escape removes the overlay.").format(
                     title=self._surface_title(), n=count)

    def _build(self) -> int:
        """(Re)create every surface from the current reading. Returns the count."""
        shot = self.screen.capture
        self._destroy_surfaces()

        # A region that is a window in its own right - a dialog, a popup, a
        # message box - gets a surface of its own, over the real one, focused
        # first. Everything else belongs to the surface over the whole target.
        dialogs = [region for region in self.screen.regions
                   if region.is_window and region.rect is not None]
        dialog_ids = {id(region) for region in dialogs}
        rest: List[Element] = []
        for region in self.screen.regions:
            if id(region) not in dialog_ids:
                rest.extend(region.elements)

        self.root = OverlaySurface(self, self._surface_title(),
                                   self._root_rect(shot))
        self.surfaces.append(self.root)
        total = self.root.place(rest, shot)

        for region in dialogs:
            left, top, width, height = shot.rect_to_screen(region.rect)
            # A dialog's own name is its title; only when the reading did not
            # give it one does it borrow the window's.
            surface = OverlaySurface(
                self, region.name or self._surface_title(),
                (left, top, max(80, width), max(60, height)))
            self.surfaces.append(surface)
            total += surface.place(region.elements, shot)
        return total

    def _root_rect(self, shot) -> Tuple[int, int, int, int]:
        """Exactly the area the picture covers - what the reading's coordinates
        are measured against."""
        return (shot.origin[0], shot.origin[1],
                max(120, shot.width * shot.factor),
                max(80, shot.height * shot.factor))

    def _surface_title(self) -> str:
        """The window's own title, and nothing else.

        The overlay is not a thing *about* the program - it is the program's
        window, made readable. Anything Titan adds to the title ("Accessible
        controls: ...") is a label on a window the user did not open, and it is
        what a screen reader would announce on every switch.
        """
        return (self.screen.title or getattr(self.screen.capture, 'title', '')
                or self.target_title or _("Screen"))

    def _show_all(self) -> None:
        for surface in self.surfaces:
            apply_skin_tree(surface)
            surface.Show()

    def _hook(self) -> None:
        """Hook every surface onto the target and remember what worked."""
        if not self.target_hwnd or self.scope != 'window':
            # A reading of the whole screen has no one window to belong to.
            self.mode = 'float'
            return
        modes = {surface.hook_onto(self.target_hwnd) for surface in self.surfaces}
        self.mode = ('child' if modes == {'child'}
                     else 'owned' if 'float' not in modes else 'float')
        if self.mode == 'child':
            self._input_attached = _attach_input(self.target_hwnd, True)

    # ----------------------------------------------------------------- acting
    def act(self, kind: str, element: Element, value) -> None:
        """A rebuilt control was used: do it to the real one underneath.

        The overlay is standing on the exact pixels the click has to land on,
        so it steps out of the way for the length of the action and comes back.
        """
        if self._acting or self._closing:
            return
        self._acting = True
        self._pending_focus = element.key
        self._cloak(True)
        try:
            if kind == 'press':
                result = actions_mod.activate(self.screen, element)
            elif kind == 'toggle':
                result = actions_mod.toggle(self.screen, element)
            elif kind == 'text':
                result = actions_mod.set_text(self.screen, element, value or '')
            elif kind == 'slider':
                result = actions_mod.set_slider(self.screen, element, value)
            elif kind == 'nudge':
                result = actions_mod.nudge(self.screen, element, int(value))
            else:
                return
        except actions_mod.ActionRefused as exc:
            speak_notification(str(exc), 'warning')
            # The overlay is now showing what the user asked for rather than
            # what the program has - put it back.
            self._rebuild_from(self.screen)
            return
        except Exception as exc:
            speak_notification(_("Could not do that: {error}").format(error=exc),
                               'error')
            return
        finally:
            self._acting = False
            if not self._user_cloaked:
                self._cloak(False)

        speak_titannet(result)
        # Pressing something changes the screen underneath, so read it again and
        # rebuild from what the program actually did.
        wx.CallLater(900, self.rescan, True)

    # --------------------------------------------------------------- scanning
    def rescan(self, quiet: bool = False) -> None:
        """Read the real window again and rebuild every control from it."""
        if self._scanning or self._closing:
            return
        reason = ai_provider.vision_unavailable_reason()
        if reason:
            speak_notification(reason, 'error')
            return

        self._scanning = True
        if not quiet:
            speak_titannet(_("Reading the screen again..."))
        self._pending_focus = self._pending_focus or self._focus_key()

        # The picture is taken here, on the main thread, while the overlay is
        # cloaked - rather than inside the reader's worker - so the moment the
        # controls are invisible lasts milliseconds instead of the whole
        # vision call.
        self._cloak(True)
        wx.CallLater(60, self._capture_and_read, quiet)

    def _capture_and_read(self, quiet: bool) -> None:
        if self._closing:
            return
        shot = None
        try:
            shot = capture_mod.capture(self.scope, self.target_hwnd)
        except Exception as exc:
            print(f"[AI OCR] overlay capture failed: {exc}")
        finally:
            if not self._user_cloaked:
                self._cloak(False)
        self._read(shot, quiet)

    def _read(self, shot, quiet: bool) -> None:
        """Hand a picture to the reader and rebuild from what comes back."""
        self._scanning = True

        def _done(screen, error):
            wx.CallAfter(self._read_finished, screen, error, quiet)

        if not self.reader.read(_done, scope=self.scope, hwnd=self.target_hwnd,
                                reuse_previous=False, shot=shot):
            self._scanning = False

    def _read_finished(self, screen: Optional[Screen], error: str,
                       quiet: bool) -> None:
        self._scanning = False
        if self._closing:
            return
        if error:
            speak_notification(error, 'error')
            return
        self._rebuild_from(screen, quiet=quiet)

    def _rebuild_from(self, screen: Optional[Screen], quiet: bool = True) -> None:
        if screen is None or self._closing:
            return
        remembered = self._pending_focus or self._focus_key()
        self._pending_focus = ''
        self.screen = screen
        self.target_hwnd = int(getattr(screen.capture, 'hwnd', 0) or self.target_hwnd)

        count = self._build()
        self._target_rect = _window_rect(self.target_hwnd)
        self._show_all()
        self._hook()
        if not (remembered and self._focus_by_key(remembered)):
            self._focus_top()
        if not quiet:
            speak_titannet(_("{n} controls").format(n=count))

    # -------------------------------------------------------------- following
    def _start_following(self) -> None:
        if self.root is None:
            return
        self._timer = wx.Timer(self.root)
        self.root.Bind(wx.EVT_TIMER, lambda e: self._follow(), self._timer)
        self._timer.Start(FOLLOW_MS)

    def _follow(self) -> None:
        """Keep the overlay true to the window it is part of.

        In ``child`` and ``owned`` mode Windows already moves, clips, hides and
        restores it with the target, so all that is left here is noticing the
        two things Windows cannot do for us: the window being resized (the
        controls inside have moved, and only a new reading knows where to) and
        the window going away.
        """
        if self._closing or self._acting or self._busy or not self.target_hwnd:
            return
        if not capture_mod.window_alive(self.target_hwnd):
            speak_notification(_("The window this overlay was part of has been "
                                 "closed."), 'warning')
            self.close()
            return

        # Alt+Tab back into the program: the controls come with it, and the
        # user lands *in* them rather than in the window they cannot read.
        in_front = self._ours_or_target_in_front() and not _is_minimised(self.target_hwnd)
        if in_front and not self._was_in_front:
            self._returned_to_front()
        self._was_in_front = in_front

        current = _window_rect(self.target_hwnd)
        if current is None:
            return
        if self._target_rect is None:
            self._target_rect = current
            return

        old_left, old_top, old_width, old_height = self._target_rect
        left, top, width, height = current
        if (width, height) != (old_width, old_height):
            self._resize_ticks += 1
            self._target_rect = current
            if self._resize_ticks >= RESIZE_SETTLE and not self._scanning:
                self._resize_ticks = 0
                speak_titannet(_("The window changed size, reading it again."))
                self.rescan(quiet=True)
            return
        self._resize_ticks = 0

        if self.mode == 'float':
            if (left, top) != (old_left, old_top):
                # Moved only: the controls are where they were *within* the
                # window, so shifting by the same amount is exact and free.
                delta_x, delta_y = left - old_left, top - old_top
                for surface in self.surfaces:
                    surface.move_to(surface.origin[0] + delta_x,
                                    surface.origin[1] + delta_y)
            self._float_visibility()
        self._target_rect = current

    def _float_visibility(self) -> None:
        """Float mode only: get out of the way of whatever else is in front.

        A hooked overlay is hidden by Windows along with its target. A floating
        one would otherwise stay on top of a program it has nothing to do with.
        """
        if self.hidden or _is_minimised(self.target_hwnd) \
                or not self._ours_or_target_in_front():
            self._show_frames(False)
            return
        self._show_frames(True)

    def _returned_to_front(self) -> None:
        """The user came back to this program - hand them its controls.

        Switching to a window whose overlay is up should land in the overlay,
        not in the unreadable window behind it; that is the whole point of the
        controls being part of that window.

        Whether they are still *true* is checked the cheap way: a picture is
        taken and compared with the one the reading came from, locally and for
        nothing. Only a screen that actually changed while the user was away
        costs a request.
        """
        if self.hidden or self._closing or self._busy:
            return
        self._busy = True
        try:
            self._come_back()
        finally:
            self._busy = False

    def _come_back(self) -> None:
        self._show_frames(True)
        if not (self._pending_focus and self._focus_by_key(self._pending_focus)):
            self._focus_top()
        speak_titannet(self._surface_title())

        if self._scanning or self.screen is None or self.screen.capture is None:
            return
        self._cloak(True)
        shot = None
        try:
            shot = capture_mod.capture(self.scope, self.target_hwnd)
        except Exception:
            shot = None
        finally:
            if not self._user_cloaked:
                self._cloak(False)
        # Only when the two pictures can really be compared. "I could not tell"
        # must mean "leave it alone": the alternative is a vision request every
        # time the user alt-tabs back, which is the one way this feature could
        # quietly cost somebody money.
        comparable = bool(getattr(shot, '_thumb', None)
                          and getattr(self.screen.capture, '_thumb', None))
        if shot is not None and comparable and not shot.looks_like(self.screen.capture):
            speak_titannet(_("This screen changed while you were away, reading "
                             "it again."))
            self._read(shot, quiet=True)

    def _show_frames(self, visible: bool) -> None:
        for surface in self.surfaces:
            if visible and not surface.IsShown():
                try:
                    surface.ShowWithoutActivating()
                except Exception:
                    surface.Show()
            elif not visible and surface.IsShown():
                surface.Hide()

    def _ours_or_target_in_front(self) -> bool:
        try:
            import win32gui
            front = int(win32gui.GetForegroundWindow() or 0)
        except Exception:
            return True
        if not front or front == int(self.target_hwnd):
            return True
        for surface in self.surfaces:
            try:
                if int(surface.GetHandle()) == front:
                    return True
            except Exception:
                pass
        return False

    # ------------------------------------------------------------------ focus
    def _focus_top(self) -> None:
        # Last built is topmost, and a dialog over a window is what the user has
        # to deal with first - exactly as in the real program.
        for surface in reversed(self.surfaces):
            if surface.focus_first():
                return
        if self.root is not None:
            self.root.SetFocus()

    def _focus_key(self) -> str:
        for surface in self.surfaces:
            key = surface.focus_key()
            if key:
                return key
        return ''

    def _focus_by_key(self, key: str) -> bool:
        return any(surface.focus_by_key(key) for surface in self.surfaces)

    def focus_next_surface(self, current: OverlaySurface) -> None:
        """F6: move between the overlay's areas (a dialog and what is behind it)."""
        if len(self.surfaces) < 2:
            speak_titannet(_("This overlay has only one area."))
            return
        index = (self.surfaces.index(current) + 1) % len(self.surfaces)
        surface = self.surfaces[index]
        surface.focus_first()
        speak_titannet(surface.GetTitle())

    # --------------------------------------------------------------- speaking
    def speak_focused(self, surface: OverlaySurface) -> None:
        element = surface.focused_element()
        if element is None:
            speak_titannet(surface.GetTitle())
            return
        parts = [element.spoken()]
        if element.text and element.text != element.name:
            parts.append(element.text)
        if element.hint:
            parts.append(element.hint)
        speak_titannet('. '.join(parts))

    def speak_summary(self) -> None:
        if self.screen is None:
            return
        parts = [self.screen.title, self.screen.summary,
                 _("{n} controls, read {seconds} seconds ago").format(
                     n=sum(len(surface.controls) for surface in self.surfaces),
                     seconds=max(0, int(time.time() - self.screen.taken_at)))]
        speak_titannet('. '.join(part for part in parts if part))

    def open_menu_bar(self, surface: 'OverlaySurface') -> None:
        """F10: the window's menu bar, as a real menu.

        A menu bar is reached by a key, not by Tab, and it is the one part of a
        window where a list of buttons is not good enough - so the menu titles
        that were read are put into a real wx.Menu. Choosing one presses the
        real menu title, and the drop-down it opens is read and given a surface
        of its own on the next reading.
        """
        elements = controls_mod.menu_bar_elements(self.screen)
        if not elements:
            speak_titannet(_("This window has no menu bar that could be read."))
            return
        menu = controls_mod.build_menu(elements, self.act)
        if menu is None:
            return
        speak_titannet(_("Menu bar"))
        try:
            surface.panel.PopupMenu(menu)
        finally:
            menu.Destroy()

    def toggle_hidden(self) -> None:
        """Put the overlay away, or bring it back. The AI OCR shortcut does this.

        Hidden means gone: the controls are not shown, not focusable and not in
        the way, so the program is exactly as it was before AI OCR touched it -
        which is what a user needs when something has to be done to the real
        window, or when the reading turned out to be wrong. Nothing is thrown
        away and nothing is re-read, so coming back is instant and free.
        """
        self.hidden = not self.hidden
        if self.hidden:
            self._show_frames(False)
            _focus_window(self.target_hwnd)
            speak_titannet(_("Overlay hidden. Press the AI OCR shortcut again "
                             "to bring it back."))
            return
        self._show_frames(True)
        if not (self._pending_focus and self._focus_by_key(self._pending_focus)):
            self._focus_top()
        speak_titannet(_("{title}: the controls are back.").format(
            title=self._surface_title()))

    def toggle_cloak(self) -> None:
        """Ctrl+H: put the overlay out of the way without closing it.

        For the moments when the program underneath has to be seen or clicked
        as it really is - a captcha, a drag, a sighted person taking over for a
        second. Everything stays where it is and comes back on the next Ctrl+H.
        """
        self._user_cloaked = not self._user_cloaked
        self._cloak(self._user_cloaked)
        speak_titannet(_("Overlay out of the way") if self._user_cloaked
                       else _("Overlay back"))

    # ------------------------------------------------------------------ close
    def _cloak(self, hidden: bool) -> None:
        for surface in self.surfaces:
            surface.cloak(hidden)
        if hidden:
            # Let Windows compose the desktop without us in it, or a picture
            # taken a millisecond later still has us in it. Deliberately a
            # sleep and not wx.SafeYield(): yielding here runs the event loop
            # in the middle of cloaking, which lets the follow timer fire and
            # re-enter the very thing that is cloaking - once observed as a
            # hang. Nothing of ours needs repainting for the alpha to apply.
            time.sleep(0.03)

    def close(self) -> None:
        global _overlay
        if self._closing:
            return
        self._closing = True
        # Escape closes an overlay without going through close_overlay(), and a
        # module still pointing at a destroyed one is how the shortcut ends up
        # hiding windows that no longer exist.
        if _overlay is self:
            _overlay = None
        if self._timer is not None:
            try:
                self._timer.Stop()
            except Exception:
                pass
            self._timer = None
        if self._input_attached:
            _attach_input(self.target_hwnd, False)
            self._input_attached = False
        self._destroy_surfaces()
        if self.on_closed is not None:
            try:
                self.on_closed()
            except Exception as exc:
                print(f"[AI OCR] overlay close handler failed: {exc}")

    def _destroy_surfaces(self) -> None:
        for surface in self.surfaces:
            try:
                surface.unhook()
                surface.clear()
                surface.Destroy()
            except Exception:
                pass
        self.surfaces = []
        self.root = None


# --------------------------------------------------------------------------- #
# Win32: hooking a window of ours onto a window of theirs
# --------------------------------------------------------------------------- #
def _user32():
    """user32, with the signatures these calls actually need declared.

    Not optional bookkeeping: a window style is a DWORD, and ctypes' default
    signature is a signed C int, so ``WS_POPUP`` (0x80000000) round-trips into
    a Python integer that no longer fits - which is exactly how the first live
    run of this failed, with ``SetParent`` never being reached at all.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    if getattr(user32, '_titan_ocr_ready', False):
        return user32

    long_ptr = ctypes.c_ssize_t
    getter = getattr(user32, 'GetWindowLongPtrW', None) or user32.GetWindowLongW
    setter = getattr(user32, 'SetWindowLongPtrW', None) or user32.SetWindowLongW
    getter.restype = long_ptr
    getter.argtypes = [wintypes.HWND, ctypes.c_int]
    setter.restype = long_ptr
    setter.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
    user32._titan_ocr_get_long = getter
    user32._titan_ocr_set_long = setter

    user32.SetParent.restype = wintypes.HWND
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_uint]
    user32.SetFocus.restype = wintypes.HWND
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD,
                                         wintypes.BOOL]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                ctypes.POINTER(wintypes.DWORD)]
    user32._titan_ocr_ready = True
    return user32


def _get_long(handle: int, index: int) -> int:
    """A window style, as the unsigned 32-bit value it really is."""
    value = int(_user32()._titan_ocr_get_long(int(handle), int(index)))
    return value & 0xFFFFFFFF if index in (GWL_STYLE, GWL_EXSTYLE) else value


def _set_long(handle: int, index: int, value: int) -> None:
    if index in (GWL_STYLE, GWL_EXSTYLE):
        # Back into the signed range the API is declared with, without losing
        # the top bit that WS_POPUP and friends live in.
        value &= 0xFFFFFFFF
        if value >= 0x80000000:
            value -= 0x100000000
    _user32()._titan_ocr_set_long(int(handle), int(index), int(value))


def _make_child(handle: int, parent_hwnd: int) -> bool:
    """Turn our window into a child of theirs. False when Windows refuses.

    Cross-process parenting is allowed and is what makes this an overlay rather
    than another window - but it is refused for some window kinds, and there is
    no way to know which except to try, so the caller has fallbacks.
    """
    try:
        style = _get_long(handle, GWL_STYLE)
        _set_long(handle, GWL_STYLE, (style & ~WS_POPUP) | WS_CHILD)
        ex_style = _get_long(handle, GWL_EXSTYLE)
        _set_long(handle, GWL_EXSTYLE,
                  (ex_style & ~WS_EX_APPWINDOW) | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
        if not _user32().SetParent(int(handle), int(parent_hwnd)):
            # Put back what we changed, so the fallbacks start from a normal
            # top-level window rather than from a child of nothing.
            _set_long(handle, GWL_STYLE, style)
            _set_long(handle, GWL_EXSTYLE, ex_style)
            return False
        return True
    except Exception as exc:
        print(f"[AI OCR] could not parent the overlay into the window: {exc}")
        return False


def _make_owned(handle: int, owner_hwnd: int) -> bool:
    """Make our window owned by theirs: above it, hidden with it, no taskbar."""
    try:
        _set_long(handle, GWLP_HWNDPARENT, owner_hwnd)
        return True
    except Exception as exc:
        print(f"[AI OCR] could not give the overlay an owner: {exc}")
        return False


def _detach(handle: int) -> None:
    """Back to a plain top-level window of our own."""
    try:
        _user32().SetParent(int(handle), 0)
        style = _get_long(handle, GWL_STYLE)
        _set_long(handle, GWL_STYLE, (style & ~WS_CHILD) | WS_POPUP)
        _set_long(handle, GWLP_HWNDPARENT, 0)
    except Exception:
        pass


def _move_child(handle: int, x: int, y: int, width: int, height: int) -> None:
    try:
        _user32().SetWindowPos(int(handle), HWND_TOP, int(x), int(y),
                               int(width), int(height),
                               SWP_FRAMECHANGED | SWP_SHOWWINDOW)
    except Exception:
        pass


def _measured_scale(handle: int, wanted_width: int, wanted_height: int) -> float:
    """What one of our pixels turned into, once the window was placed.

    1.0 when the two processes agree about pixels, which is most of the time.
    Anything wilder than a quarter or four times is not a DPI difference but a
    window manager doing something else entirely, and is ignored.
    """
    rect = _window_rect(handle)
    if not rect or rect[2] < 2 or rect[3] < 2:
        return 1.0
    scale_x = wanted_width / float(rect[2])
    scale_y = wanted_height / float(rect[3])
    scale = (scale_x + scale_y) / 2.0
    if not 0.25 <= scale <= 4.0:
        return 1.0
    return scale


def _client_origin(hwnd: int) -> Tuple[int, int]:
    """Where a window's client area starts, in screen pixels."""
    try:
        import win32gui
        return win32gui.ClientToScreen(int(hwnd), (0, 0))
    except Exception:
        rect = _window_rect(hwnd)
        return (rect[0], rect[1]) if rect else (0, 0)


def _attach_input(target_hwnd: int, attach: bool) -> bool:
    """Join our thread's input queue to the target's, or let it go again.

    Keyboard focus is a property of an input queue, not of a process, so a
    child window of another process's window cannot be focused until the two
    queues are one. This is the same mechanism the Titan Access screen reader
    and every focus-stealing utility on Windows uses.
    """
    try:
        import ctypes
        user32 = _user32()
        process_id = ctypes.c_ulong()
        target_thread = user32.GetWindowThreadProcessId(int(target_hwnd),
                                                        ctypes.byref(process_id))
        if not target_thread:
            return False
        our_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        if our_thread == target_thread:
            return False
        return bool(user32.AttachThreadInput(our_thread, target_thread,
                                             bool(attach)))
    except Exception as exc:
        print(f"[AI OCR] could not attach to the window's input queue: {exc}")
        return False


def _set_click_through(handle: int, enabled: bool) -> None:
    """Take the overlay out of (or back into) mouse hit testing.

    ``WS_EX_TRANSPARENT`` is what lets a click aimed at the real control reach
    it, and - just as importantly - what makes ``WindowFromPoint`` answer with
    the real window, which is the check :mod:`src.ai.ocr.actions` uses to refuse
    a click that has ended up somewhere unexpected.
    """
    if not handle:
        return
    try:
        style = _get_long(handle, GWL_EXSTYLE)
        if enabled:
            style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
        else:
            style &= ~WS_EX_TRANSPARENT
        _set_long(handle, GWL_EXSTYLE, style)
    except Exception as exc:
        print(f"[AI OCR] could not change the overlay's click-through: {exc}")


def _window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    if not hwnd:
        return None
    try:
        import win32gui
        left, top, right, bottom = win32gui.GetWindowRect(int(hwnd))
        return (left, top, right - left, bottom - top)
    except Exception:
        return None


def _focus_window(hwnd: int) -> None:
    """Give the real window the focus back (when the overlay steps aside)."""
    try:
        import win32gui
        if hwnd and win32gui.IsWindow(int(hwnd)):
            win32gui.SetForegroundWindow(int(hwnd))
    except Exception:
        pass


def _is_minimised(hwnd: int) -> bool:
    try:
        import win32gui
        return bool(win32gui.IsIconic(int(hwnd)))
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
_overlay: Optional[ScreenOverlay] = None


def show_overlay(screen: Screen, scope: str = 'window', target_hwnd: int = 0,
                 reader: Optional[Reader] = None,
                 on_closed: Optional[Callable[[], None]] = None,
                 target_title: str = '') -> Optional[ScreenOverlay]:
    """Hook an overlay onto the window ``screen`` was read from.

    Only one exists at a time: two overlays on one window would be two sets of
    controls claiming the same pixels.
    """
    global _overlay
    close_overlay()

    overlay = ScreenOverlay(screen, scope=scope, target_hwnd=target_hwnd,
                            reader=reader, on_closed=on_closed,
                            target_title=target_title)
    if not overlay.open():
        return None
    _overlay = overlay
    return overlay


def close_overlay() -> None:
    global _overlay
    if _overlay is not None:
        current, _overlay = _overlay, None
        try:
            current.close()
        except Exception:
            pass


def get_overlay() -> Optional[ScreenOverlay]:
    return _overlay

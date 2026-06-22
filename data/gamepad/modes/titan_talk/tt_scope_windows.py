"""
Titan Talk - Window Switcher scope
==================================

Lists the open top-level windows. Left/right (and up/down) move between them,
A focuses the selected window, B re-announces it. Uses ``pywinctl`` which is
already a core Titan dependency, so this scope needs nothing from ``lib/``.
"""

from tt_core import Scope, Control, _, play_positioned, SND_CLICK

try:
    import pywinctl
    _PYWINCTL = True
except Exception as e:  # pragma: no cover
    print(f"[TitanTalk] pywinctl unavailable: {e}")
    _PYWINCTL = False


class WindowSwitcherScope(Scope):
    id = 'windows'

    def display_name(self):
        return _("Window switcher")

    def available(self):
        return _PYWINCTL

    def refresh(self):
        self.controls = []
        if not _PYWINCTL:
            return
        own_title = _("Titan Talk")
        try:
            windows = pywinctl.getAllWindows()
        except Exception as e:
            print(f"[TitanTalk] getAllWindows failed: {e}")
            return
        for w in windows:
            try:
                title = (w.title or '').strip()
                if not title or title == own_title:
                    continue
                if not w.isVisible:
                    continue
                box = w.box  # Rect(left, top, width, height)
                if box.width <= 0 or box.height <= 0:
                    continue
                cx = box.left + box.width / 2.0
                cy = box.top + box.height / 2.0
                self.controls.append(
                    Control(name=title, role='window', cx=cx, cy=cy, payload=w))
            except Exception:
                continue
        # Stable left-to-right order so the spatial walk feels predictable.
        self.controls.sort(key=lambda c: (round(c.cx), round(c.cy)))

    def navigate(self, dx, dy):
        # Window list is effectively one dimension: treat any horizontal OR
        # vertical flick as prev/next through the ordered list.
        if not self.controls:
            return False
        step = -1 if (dx < 0 or dy < 0) else 1
        new = self.index + step
        if new < 0 or new >= len(self.controls):
            return False
        self.index = new
        return True

    def activate(self):
        cur = self.current()
        if cur is None or cur.payload is None:
            return False
        try:
            cur.payload.activate(wait=False)
        except Exception as e:
            print(f"[TitanTalk] window activate failed: {e}")
            try:
                cur.payload.activate()
            except Exception:
                return False
        play_positioned(SND_CLICK, cur)
        # The foreground-window monitor announces the newly focused window and
        # its first control once the focus change lands, and switches the buffer
        # to that window's controls - so we don't announce it here.
        return True

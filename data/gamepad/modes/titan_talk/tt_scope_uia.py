"""
Titan Talk - Window controls scope (UI Automation)
==================================================

Reads the native controls of the foreground window through Microsoft UI
Automation (the ``uiautomation`` package, vendored in ``lib/``). Spatial arrow
navigation walks between controls; A invokes / toggles / focuses the current
control depending on its type; B sends Escape. Supported types map onto the UIA
control patterns:

    button   -> InvokePattern.Invoke()
    check box-> TogglePattern.Toggle()   (announces checked / not checked)
    edit     -> SetFocus()               (then type with the screen keyboard)
    slider   -> RangeValuePattern        (value announced; focus on A)

plus radio buttons, combo boxes, menu items, list items, tabs and links.
"""

from tt_core import (Scope, Control, _, speak, play_mode_sound, play_positioned,
                     SND_CLICK, SND_EDGE)
from src.controller.controller_modes import _press, _release

try:
    import uiautomation as auto
    _UIA = True
except Exception as e:  # pragma: no cover - degrades to "scope unavailable"
    print(f"[TitanTalk] uiautomation unavailable: {e}")
    auto = None
    _UIA = False

# Limits so enumerating a huge window never stalls the poll loop.
_MAX_DEPTH = 14
_MAX_CONTROLS = 250

# UIA ControlTypeName -> our role key. Only these are collected as navigable.
_TYPE_TO_ROLE = {
    'ButtonControl': 'button',
    'SplitButtonControl': 'button',
    'EditControl': 'edit',
    'DocumentControl': 'edit',
    'SliderControl': 'slider',
    'CheckBoxControl': 'checkbox',
    'RadioButtonControl': 'radio',
    'ComboBoxControl': 'combobox',
    'MenuItemControl': 'menuitem',
    'ListItemControl': 'listitem',
    'TabItemControl': 'tab',
    'HyperlinkControl': 'link',
    'TextControl': 'text',
}


def _toggle_state_to_key(state):
    try:
        if state == auto.ToggleState.On:
            return 'checked'
        return 'unchecked'
    except Exception:
        return None


# Ancestor types that count as a "container" worth announcing on enter / leave.
_CONTAINER_TYPES = {
    'ListControl': 'list',
    'TreeControl': 'tree',
    'DataGridControl': 'grid',
    'TableControl': 'table',
    'TabControl': 'tab list',
    'ToolBarControl': 'toolbar',
    'MenuControl': 'menu',
    'MenuBarControl': 'menu bar',
    'GroupControl': 'group',
}


def _container_label(kind):
    return {
        'list': _("list"),
        'tree': _("tree"),
        'grid': _("grid"),
        'table': _("table"),
        'tab list': _("tab list"),
        'toolbar': _("toolbar"),
        'menu': _("menu"),
        'menu bar': _("menu bar"),
        'group': _("group"),
    }.get(kind, kind)


def _container_of(ctrl):
    """Nearest ancestor container as ``(key, label)``, or None.

    Walks up the UIA tree until it meets a list / tree / toolbar / tab / group /
    menu / grid. The key is the container's RuntimeId (so entering and leaving
    the same container is detectable); the label is its accessible name, falling
    back to the kind ("list", "menu", ...).
    """
    try:
        node = ctrl.GetParentControl()
    except Exception:
        return None
    depth = 0
    while node is not None and depth < 10:
        try:
            kind = _CONTAINER_TYPES.get(node.ControlTypeName)
        except Exception:
            kind = None
        if kind:
            try:
                rid = tuple(node.GetRuntimeId() or ())
            except Exception:
                rid = ()
            if not rid:
                try:
                    r = node.BoundingRectangle
                    rid = (r.left, r.top, r.right, r.bottom)
                except Exception:
                    rid = (id(node),)
            try:
                name = (node.Name or '').strip()
            except Exception:
                name = ''
            return ("{}:{}".format(kind, rid), name or _container_label(kind))
        try:
            node = node.GetParentControl()
        except Exception:
            return None
        depth += 1
    return None


class UIAScope(Scope):
    id = 'uia'

    def display_name(self):
        return _("Window controls")

    def available(self):
        return _UIA

    # -- enumeration -------------------------------------------------------- #
    def refresh(self):
        self.controls = []
        if not _UIA:
            return
        try:
            # GetForegroundWindow() returns an HWND (int) in uiautomation; the
            # navigable root is the Control for the foreground window.
            window = auto.GetForegroundControl()
            if window is None:
                hwnd = auto.GetForegroundWindow()
                window = auto.ControlFromHandle(hwnd) if hwnd else None
        except Exception as e:
            print(f"[TitanTalk] foreground control failed: {e}")
            return
        if not window:
            return
        try:
            for ctrl, _depth in auto.WalkControl(window, includeTop=False,
                                                 maxDepth=_MAX_DEPTH):
                role = _TYPE_TO_ROLE.get(ctrl.ControlTypeName)
                if role is None:
                    continue
                try:
                    if ctrl.IsOffscreen or not ctrl.IsEnabled:
                        continue
                    rect = ctrl.BoundingRectangle
                    if rect.width() <= 0 or rect.height() <= 0:
                        continue
                except Exception:
                    continue
                name = (ctrl.Name or '').strip()
                if role == 'text':
                    # Skip static text that is empty or only icon-font glyphs
                    # (private use area, e.g. ''); it is noise to read.
                    visible = ''.join(ch for ch in name
                                      if not (0xE000 <= ord(ch) <= 0xF8FF))
                    if not visible.strip():
                        continue
                control = Control(
                    name=name, role=role,
                    cx=rect.xcenter(), cy=rect.ycenter(), payload=ctrl,
                    container=_container_of(ctrl))
                self._fill_state(control, ctrl)
                self.controls.append(control)
                if len(self.controls) >= _MAX_CONTROLS:
                    break
        except Exception as e:
            print(f"[TitanTalk] UIA walk failed: {e}")
        # Reading order: top-to-bottom, then left-to-right.
        self.controls.sort(key=lambda c: (round(c.cy / 8), round(c.cx)))

    def _fill_state(self, control, ctrl):
        """Resolve checkbox/radio state and slider value for the announcement."""
        try:
            if control.role in ('checkbox', 'radio'):
                tp = ctrl.GetTogglePattern()
                if tp is not None:
                    control.state = _toggle_state_to_key(tp.ToggleState)
            elif control.role == 'slider':
                rp = ctrl.GetRangeValuePattern()
                if rp is not None:
                    control.value = str(rp.Value)
        except Exception:
            pass

    # -- actions ------------------------------------------------------------ #
    def activate(self):
        cur = self.current()
        if cur is None or cur.payload is None:
            return False
        ctrl = cur.payload
        try:
            if cur.role in ('checkbox', 'radio'):
                return self._toggle(cur, ctrl)
            if cur.role == 'edit':
                ctrl.SetFocus()
                play_positioned(SND_CLICK, cur)
                speak(_("Editing {name}").format(name=cur.name or _("edit field")))
                return True
            if cur.role == 'slider':
                ctrl.SetFocus()
                play_positioned(SND_CLICK, cur)
                speak(cur.value or _("slider"))
                return True
            if cur.role == 'combobox':
                if self._expand(ctrl):
                    play_positioned(SND_CLICK, cur)
                    speak(_("Expanded"))
                    self.mode.refresh_current_scope(delay_ms=450)
                    return True
            # button / link / menuitem / listitem / tab: invoke or select.
            ok = self._invoke(cur, ctrl)
            if ok:
                # The action may have opened a new window or navigated a menu;
                # re-read the buffer so it reflects the now-foreground window.
                self.mode.refresh_current_scope(delay_ms=450)
            return ok
        except Exception as e:
            print(f"[TitanTalk] activate failed: {e}")
            return False

    def _invoke(self, cur, ctrl):
        for getter in ('GetInvokePattern', 'GetSelectionItemPattern',
                       'GetExpandCollapsePattern'):
            try:
                pattern = getattr(ctrl, getter)()
            except Exception:
                pattern = None
            if pattern is None:
                continue
            try:
                if getter == 'GetInvokePattern':
                    pattern.Invoke()
                elif getter == 'GetSelectionItemPattern':
                    pattern.Select()
                else:
                    pattern.Expand()
                play_positioned(SND_CLICK, cur)
                return True
            except Exception:
                continue
        # Last resort: focus and press Enter.
        try:
            ctrl.SetFocus()
            _press('enter'); _release('enter')
            play_mode_sound(SND_CLICK)
            return True
        except Exception:
            return False

    def _toggle(self, cur, ctrl):
        try:
            tp = ctrl.GetTogglePattern()
            if tp is None:
                return self._invoke(cur, ctrl)
            tp.Toggle()
            new_state = _toggle_state_to_key(tp.ToggleState)
            cur.state = new_state
            play_positioned(SND_CLICK, cur)
            from tt_core import state_label
            speak("{name}, {state}".format(
                name=cur.name or _("check box"),
                state=state_label(new_state) if new_state else ''))
            return True
        except Exception:
            return self._invoke(cur, ctrl)

    @staticmethod
    def _expand(ctrl):
        try:
            ep = ctrl.GetExpandCollapsePattern()
            if ep is not None:
                ep.Expand()
                return True
        except Exception:
            pass
        return False

    def back(self):
        play_positioned(SND_EDGE, self.current())
        _press('escape'); _release('escape')
        return True

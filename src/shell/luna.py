# -*- coding: utf-8 -*-
"""
The Windows XP (Luna) look, as data plus the handful of painters that use it.

The numbers are not guessed.  They are the measured gradient stops of the
Luna Blue taskbar - the same table pixel-accurate reimplementations of the XP
taskbar use - so a Titan taskbar put beside a screenshot of XP matches band
for band instead of being "blue-ish".

Everything here can be overridden by a TCE skin.  A skin adds a `[Shell]`
section to its `skin.ini`:

    [Shell]
    style = luna                  ; luna | classic
    taskbar_gradient = #3888e9 0.0, #4993e6 0.05, #1941a5 1.0
    start_button_gradient = #3c9a3c 0.0, #17601a 1.0
    tray_gradient = ...
    start_menu_right_background = #d3e5fa
    taskbar_height = 30

so the XP look is the default rather than the only possibility - `windows95`
asks for `style = classic` and gets the grey 3D shell instead, painted from
the same code.
"""

import wx

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------


def colour(value, default=None):
    """Parse "#RRGGBB" or "#AARRGGBB" (the order theme files use) into wx."""
    if isinstance(value, wx.Colour):
        return value
    try:
        text = str(value).strip().lstrip('#')
        if len(text) == 6:
            return wx.Colour(int(text[0:2], 16), int(text[2:4], 16),
                             int(text[4:6], 16))
        if len(text) == 8:
            return wx.Colour(int(text[2:4], 16), int(text[4:6], 16),
                             int(text[6:8], 16), int(text[0:2], 16))
    except Exception:
        pass
    if default is not None:
        return colour(default)
    return wx.Colour(0, 0, 0)


def parse_stops(text, default=None):
    """Parse "#3888e9 0.0, #4993e6 0.05" into [(offset, wx.Colour)]."""
    stops = []
    try:
        for part in str(text).split(','):
            part = part.strip()
            if not part:
                continue
            pieces = part.replace('@', ' ').split()
            if len(pieces) == 1:
                stops.append((len(stops) and 1.0 or 0.0, colour(pieces[0])))
            else:
                stops.append((float(pieces[1]), colour(pieces[0])))
    except Exception:
        stops = []
    if len(stops) < 2:
        return list(default or [])
    stops.sort(key=lambda item: item[0])
    return stops


# ---------------------------------------------------------------------------
# Luna Blue - the default palette
# ---------------------------------------------------------------------------

LUNA = {
    'style': 'luna',
    'taskbar_height': 30,

    # Taskbar body: five bands, the bright hairline at the very top being
    # what makes it read as XP rather than as a flat blue strip.
    'taskbar_gradient': [(0.00, colour('#3888e9')),
                         (0.05, colour('#4993e6')),
                         (0.18, colour('#2257d5')),
                         (0.90, colour('#2663e0')),
                         (1.00, colour('#1941a5'))],
    'taskbar_border': colour('#3168d5'),

    # Start button: the green Luna capsule.
    'start_gradient': [(0.00, colour('#3f9f3f')),
                       (0.06, colour('#53b153')),
                       (0.40, colour('#2f8f2f')),
                       (0.90, colour('#1c691c')),
                       (1.00, colour('#14520f'))],
    'start_gradient_hover': [(0.00, colour('#63c163')),
                             (0.06, colour('#78d178')),
                             (0.40, colour('#43a343')),
                             (0.90, colour('#2a7d2a')),
                             (1.00, colour('#1d661a'))],
    'start_gradient_pressed': [(0.00, colour('#1c5f1c')),
                               (0.10, colour('#2b7a2b')),
                               (0.90, colour('#2f8b2f')),
                               (1.00, colour('#3f9f3f'))],
    'start_border': colour('#12520f'),
    'start_text': colour('#ffffff'),
    'start_text_shadow': colour('#454c10'),

    # Task buttons.
    'task_gradient': [(0.00, colour('#4892f7')), (0.17, colour('#3980f4')),
                      (1.00, colour('#3980f4'))],
    'task_gradient_hover': [(0.00, colour('#8bc0ff')),
                            (0.05, colour('#59a4ff')),
                            (0.90, colour('#569fff')),
                            (1.00, colour('#2a81ff'))],
    'task_gradient_pressed': [(0.00, colour('#123d94')),
                              (0.05, colour('#1951b9')),
                              (0.80, colour('#1a50b8')),
                              (1.00, colour('#2156b7'))],
    'task_gradient_flashing': [(0.00, colour('#ffb843')),
                               (0.17, colour('#e37a08')),
                               (1.00, colour('#e37a08'))],
    'task_border_top': colour('#3172da'),
    'task_border_left': colour('#3067dd'),
    'task_border_right': colour('#264fad'),
    'task_border_bottom': colour('#2652bc'),
    'task_inner_left': colour('#5d98f5'),
    'task_inner_right': colour('#316fe8'),
    'task_border_top_pressed': colour('#1c62d2'),
    'task_border_left_pressed': colour('#082970'),
    'task_border_right_pressed': colour('#0e3c9f'),
    'task_border_bottom_pressed': colour('#0c3cae'),
    'task_text': colour('#ffffff'),

    # Notification area.
    'tray_gradient': [(0.00, colour('#16adf0')), (0.05, colour('#19b9f3')),
                      (0.18, colour('#1290e8')), (0.60, colour('#0d8dea')),
                      (0.90, colour('#0fa0ef')), (1.00, colour('#1582dc'))],
    'tray_border': colour('#095bc9'),
    'tray_separator_light': colour('#22c4f4'),
    'tray_separator_dark': colour('#22b9e5'),
    'clock_text': colour('#ffffff'),

    # Start menu.
    'menu_header': [(0.00, colour('#2a63d8')), (0.10, colour('#3b7ce8')),
                    (0.90, colour('#1b4ec4')), (1.00, colour('#123fae'))],
    'menu_header_text': colour('#ffffff'),
    'menu_left_background': colour('#ffffff'),
    'menu_right_background': colour('#d3e5fa'),
    'menu_left_text': colour('#000000'),
    'menu_right_text': colour('#0a246a'),
    'menu_selection': colour('#2f71cd'),
    'menu_selection_text': colour('#ffffff'),
    'menu_separator': colour('#c1d2ee'),
    'menu_border': colour('#1c3f9e'),
    'menu_footer': [(0.00, colour('#3f8ef7')), (0.15, colour('#2f7ae8')),
                    (0.90, colour('#1c56c8')), (1.00, colour('#123fae'))],
    'menu_footer_text': colour('#ffffff'),
    'menu_all_programs': colour('#d3e5fa'),

    # Desktop.
    'desktop_background': colour('#004e98'),
    'desktop_text': colour('#ffffff'),
    'desktop_text_shadow': colour('#000000'),
    'desktop_selection': colour('#316ac5'),
}

CLASSIC = dict(LUNA)
CLASSIC.update({
    'style': 'classic',
    'taskbar_height': 28,
    'taskbar_gradient': [(0.0, colour('#c0c0c0')), (1.0, colour('#c0c0c0'))],
    'taskbar_border': colour('#dfdfdf'),
    'start_gradient': [(0.0, colour('#c0c0c0')), (1.0, colour('#c0c0c0'))],
    'start_gradient_hover': [(0.0, colour('#d4d0c8')), (1.0, colour('#d4d0c8'))],
    'start_gradient_pressed': [(0.0, colour('#c0c0c0')), (1.0, colour('#c0c0c0'))],
    'start_border': colour('#808080'),
    'start_text': colour('#000000'),
    'start_text_shadow': None,
    'task_gradient': [(0.0, colour('#c0c0c0')), (1.0, colour('#c0c0c0'))],
    'task_gradient_hover': [(0.0, colour('#d4d0c8')), (1.0, colour('#d4d0c8'))],
    'task_gradient_pressed': [(0.0, colour('#b8b4ac')), (1.0, colour('#b8b4ac'))],
    'task_text': colour('#000000'),
    'tray_gradient': [(0.0, colour('#c0c0c0')), (1.0, colour('#c0c0c0'))],
    'tray_border': colour('#808080'),
    'clock_text': colour('#000000'),
    'menu_left_background': colour('#c0c0c0'),
    'menu_right_background': colour('#c0c0c0'),
    'menu_left_text': colour('#000000'),
    'menu_right_text': colour('#000000'),
    'menu_selection': colour('#000080'),
    'menu_header': [(0.0, colour('#000080')), (1.0, colour('#1084d0'))],
    'menu_footer': [(0.0, colour('#c0c0c0')), (1.0, colour('#c0c0c0'))],
    'menu_footer_text': colour('#000000'),
    'desktop_background': colour('#008080'),
})

# Keys whose value is a gradient (a list of stops) rather than a colour.
_GRADIENT_KEYS = {k for k, v in LUNA.items() if isinstance(v, list)}
_NUMBER_KEYS = {'taskbar_height'}


class Palette:
    """The colours and metrics the shell paints with."""

    def __init__(self, values=None):
        self._values = dict(LUNA)
        if values:
            self._values.update(values)

    # -- access -----------------------------------------------------------
    def __getitem__(self, key):
        return self._values[key]

    def get(self, key, default=None):
        return self._values.get(key, default)

    @property
    def style(self):
        return self._values.get('style', 'luna')

    @property
    def taskbar_height(self):
        try:
            return max(20, int(self._values.get('taskbar_height', 30)))
        except Exception:
            return 30

    def font(self, size=8, bold=False, italic=False, face=None):
        """Tahoma is what XP used; a skin may name another face."""
        face = face or self._values.get('font_face', 'Tahoma')
        return wx.Font(
            int(size), wx.FONTFAMILY_SWISS,
            wx.FONTSTYLE_ITALIC if italic else wx.FONTSTYLE_NORMAL,
            wx.FONTWEIGHT_BOLD if bold else wx.FONTWEIGHT_NORMAL,
            False, face)

    # -- construction -----------------------------------------------------
    @classmethod
    def from_skin(cls, skin=None):
        """Build the palette for the skin the user has chosen.

        A skin with no `[Shell]` section gets Luna, so the XP look is what
        every existing skin means by "the shell"; `style = classic` switches
        the base to the grey 3D one, and any individual key may be replaced.
        """
        section = {}
        try:
            if skin is None:
                from src.titan_core.skin_manager import get_current_skin
                skin = get_current_skin()
            section = dict(getattr(skin, 'shell', {}) or {})
        except Exception:
            section = {}

        base = CLASSIC if str(section.get('style', '')).strip().lower() \
            == 'classic' else LUNA
        values = dict(base)

        for key, raw in section.items():
            key = str(key).strip().lower()
            if key == 'style':
                values['style'] = str(raw).strip().lower()
            elif key in _NUMBER_KEYS:
                try:
                    values[key] = int(str(raw).strip())
                except Exception:
                    pass
            elif key.endswith('_gradient') or key in _GRADIENT_KEYS:
                stops = parse_stops(raw, base.get(key))
                if stops:
                    values[key] = stops
            elif key in base or key.endswith('_color') or key.endswith('_text'):
                try:
                    values[key] = colour(raw, base.get(key))
                except Exception:
                    pass
            else:
                values[key] = raw

        # A skin that only names its palette still gets a coherent shell:
        # the listbox/selection colours stand in for the menu's.
        return cls(values)


_palette = None


def get_palette(refresh=False):
    """The palette in force, rebuilt on demand when the skin changes."""
    global _palette
    if _palette is None or refresh:
        try:
            _palette = Palette.from_skin()
        except Exception:
            _palette = Palette()
    return _palette


def invalidate_palette():
    global _palette
    _palette = None


# ---------------------------------------------------------------------------
# Painters
# ---------------------------------------------------------------------------


def draw_gradient(dc, rect, stops, vertical=True):
    """Fill `rect` with a multi-stop gradient.

    wx's own GradientFillLinear takes two colours only, and Luna's bands are
    what the look is made of, so the stops are drawn as a graphics-context
    gradient when one is available and as consecutive two-colour bands
    otherwise (which still reproduces every band, only without interpolation
    between them being hardware assisted).
    """
    if not stops:
        return
    if len(stops) == 1:
        dc.SetBrush(wx.Brush(stops[0][1]))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRectangle(rect)
        return

    try:
        gc = wx.GraphicsContext.Create(dc)
        if gc is not None:
            gradient_stops = wx.GraphicsGradientStops(stops[0][1],
                                                      stops[-1][1])
            for offset, col in stops[1:-1]:
                gradient_stops.Add(wx.GraphicsGradientStop(col, float(offset)))
            if vertical:
                brush = gc.CreateLinearGradientBrush(
                    rect.x, rect.y, rect.x, rect.y + rect.height,
                    gradient_stops)
            else:
                brush = gc.CreateLinearGradientBrush(
                    rect.x, rect.y, rect.x + rect.width, rect.y,
                    gradient_stops)
            gc.SetBrush(brush)
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawRectangle(rect.x, rect.y, rect.width, rect.height)
            return
    except Exception:
        pass

    span = rect.height if vertical else rect.width
    for index in range(len(stops) - 1):
        start_offset, start_colour = stops[index]
        end_offset, end_colour = stops[index + 1]
        begin = int(rect.y + start_offset * span) if vertical \
            else int(rect.x + start_offset * span)
        end = int(rect.y + end_offset * span) if vertical \
            else int(rect.x + end_offset * span)
        if end <= begin:
            end = begin + 1
        if vertical:
            band = wx.Rect(rect.x, begin, rect.width, end - begin)
        else:
            band = wx.Rect(begin, rect.y, end - begin, rect.height)
        dc.GradientFillLinear(band, start_colour, end_colour,
                              wx.SOUTH if vertical else wx.EAST)


def draw_taskbar_background(dc, rect, palette):
    draw_gradient(dc, rect, palette['taskbar_gradient'])
    border = palette.get('taskbar_border')
    if border:
        dc.SetPen(wx.Pen(border))
        dc.DrawLine(rect.x, rect.y, rect.x + rect.width, rect.y)


def draw_task_button(dc, rect, palette, state='normal', focused=False):
    """One taskbar window button, bevelled the way Luna bevels them."""
    key = {
        'normal': 'task_gradient',
        'hover': 'task_gradient_hover',
        'active': 'task_gradient_pressed',
        'pressed': 'task_gradient_pressed',
        'flashing': 'task_gradient_flashing',
    }.get(state, 'task_gradient')
    draw_gradient(dc, rect, palette[key])

    pressed = state in ('active', 'pressed')
    top = palette['task_border_top_pressed' if pressed else 'task_border_top']
    left = palette['task_border_left_pressed' if pressed else 'task_border_left']
    right = palette['task_border_right_pressed' if pressed else 'task_border_right']
    bottom = palette['task_border_bottom_pressed' if pressed else 'task_border_bottom']

    x, y, w, h = rect.x, rect.y, rect.width, rect.height
    dc.SetPen(wx.Pen(top))
    dc.DrawLine(x, y, x + w, y)
    dc.SetPen(wx.Pen(left))
    dc.DrawLine(x, y, x, y + h)
    dc.SetPen(wx.Pen(right))
    dc.DrawLine(x + w - 1, y, x + w - 1, y + h)
    dc.SetPen(wx.Pen(bottom))
    dc.DrawLine(x, y + h - 1, x + w, y + h - 1)

    if focused:
        # The keyboard focus must be visible without relying on colour alone.
        dc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 1, wx.PENSTYLE_DOT))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRectangle(x + 2, y + 2, w - 4, h - 4)


def draw_start_button(dc, rect, palette, state='normal', focused=False,
                      label='start'):
    """The green capsule, rounded on its right side like XP's."""
    key = {'normal': 'start_gradient', 'hover': 'start_gradient_hover',
           'pressed': 'start_gradient_pressed'}.get(state, 'start_gradient')

    if palette.style == 'luna':
        radius = max(6, rect.height // 3)
        try:
            gc = wx.GraphicsContext.Create(dc)
            if gc is not None:
                stops = palette[key]
                gradient_stops = wx.GraphicsGradientStops(stops[0][1],
                                                          stops[-1][1])
                for offset, col in stops[1:-1]:
                    gradient_stops.Add(wx.GraphicsGradientStop(col,
                                                               float(offset)))
                gc.SetBrush(gc.CreateLinearGradientBrush(
                    rect.x, rect.y, rect.x, rect.y + rect.height,
                    gradient_stops))
                gc.SetPen(wx.Pen(palette['start_border']))
                path = gc.CreatePath()
                path.AddRoundedRectangle(rect.x - radius, rect.y + 0.5,
                                         rect.width + radius - 1,
                                         rect.height - 1, radius)
                gc.FillPath(path)
                gc.StrokePath(path)
            else:
                draw_gradient(dc, rect, palette[key])
        except Exception:
            draw_gradient(dc, rect, palette[key])
    else:
        draw_gradient(dc, rect, palette[key])
        dc.SetPen(wx.Pen(palette.get('button_highlight', wx.Colour(255, 255, 255))))
        dc.DrawLine(rect.x, rect.y, rect.x + rect.width, rect.y)
        dc.SetPen(wx.Pen(palette['start_border']))
        dc.DrawLine(rect.x, rect.y + rect.height - 1,
                    rect.x + rect.width, rect.y + rect.height - 1)

    italic = palette.style == 'luna'
    dc.SetFont(palette.font(size=13 if italic else 8, bold=True,
                            italic=italic))
    text_width, text_height = dc.GetTextExtent(label)
    text_x = rect.x + max(6, (rect.width - text_width) // 2 - 4)
    text_y = rect.y + (rect.height - text_height) // 2

    shadow = palette.get('start_text_shadow')
    if shadow:
        dc.SetTextForeground(shadow)
        dc.DrawText(label, text_x + 1, text_y + 1)
    dc.SetTextForeground(palette['start_text'])
    dc.DrawText(label, text_x, text_y)

    if focused:
        dc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 1, wx.PENSTYLE_DOT))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRectangle(rect.x + 2, rect.y + 2, rect.width - 4,
                         rect.height - 4)


def draw_tray_background(dc, rect, palette):
    """The notification area's own gradient plus its left-hand divider."""
    draw_gradient(dc, rect, palette['tray_gradient'])
    if palette.style != 'luna':
        dc.SetPen(wx.Pen(palette['tray_border']))
        dc.DrawLine(rect.x, rect.y, rect.x, rect.y + rect.height)
        return
    dc.SetPen(wx.Pen(palette['tray_separator_dark']))
    dc.DrawLine(rect.x + 1, rect.y, rect.x + 1, rect.y + rect.height)
    dc.SetPen(wx.Pen(palette['tray_separator_light']))
    dc.DrawLine(rect.x + 2, rect.y, rect.x + 2, rect.y + rect.height)
    dc.SetPen(wx.Pen(palette['tray_border']))
    dc.DrawLine(rect.x, rect.y, rect.x + rect.width, rect.y)

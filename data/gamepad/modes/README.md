# Custom gamepad modes

A custom gamepad mode is a **folder**, exactly like a component. Drop it here to
add a new mode to Titan's controller mode cycle: with a gamepad connected,
**HOLD a bumper for about a second** to switch modes (LB = previous, RB = next).
The built-in modes (System, Controller, Screen reader, Screen keyboard) come
first, then every custom mode found here.

You can also drop modes in the per-user overlay so they survive updates:
`%APPDATA%/titosoft/Titan/data/gamepad/modes/`. A user folder overrides a
bundled folder with the same name.

## Folder layout

```
data/gamepad/modes/my_mode/
    __mode__.TCE        # config (INI, [mode] section)
    my_mode.py          # subclass of GamepadMode
    languages/          # the mode's own translations (gettext)
        my_mode.pot
        pl/LC_MESSAGES/my_mode.po  (+ .mo)
        en/LC_MESSAGES/my_mode.po  (+ .mo)
```

### `__mode__.TCE`

```ini
[mode]
name = My Mode
name_pl = Moj tryb
name_en = My Mode
main = my_mode.py
domain = my_mode
description = What the mode does
status = 0
```

- `status` - `0` = enabled (loaded), anything else = disabled.
- `name` / `name_<lang>` - the label announced when the mode is selected.
  The loader picks `name_<currentlang>`, then `name_en`, then `name`.
- `main` - the Python file with the mode class (defaults to the only `*.py`).
- `domain` - the gettext domain used by `languages/` (defaults to folder name).

## The mode class

```python
from src.controller.gamepad_mode_api import (
    GamepadMode, setup_mode_translations, tap, speak)

_ = setup_mode_translations(__file__, 'my_mode')  # loads ./languages

class MyMode(GamepadMode):
    name = "My Mode"          # fallback label (config name wins)

    def handle_button(self, button_id):
        if button_id == 0:    # A on an Xbox pad
            speak(_("Hello"))
            return True
        return False
```

The loader instantiates any `GamepadMode` subclass defined in the main module.

## Hooks (override what you need)

| Method | Called when | Return |
|--------|-------------|--------|
| `on_activate(manager)` | the mode becomes active | - |
| `on_deactivate(manager)` | switching away | - |
| `handle_button(button_id)` | a button is pressed (once per press) | `True` if handled |
| `handle_axis(axis_id, value)` | an analog stick flicks past the dead-zone (debounced) | `True` if handled |
| `handle_hat(x, y)` | the d-pad changes direction (edge-detected) | `True` if handled |
| `handle_bumper(is_left)` | a bumper is **tapped** (short press) | `True` if handled |

Bumpers do double duty: a short **tap** is delivered to `handle_bumper`
(`is_left` = True for LB, False for RB), while **HOLDING** a bumper for ~1s still
changes the controller mode. A mode that ignores bumpers just returns False.

Numbering (standard Xbox / XInput layout):

- Buttons: `0`=A, `1`=B, `2`=X, `3`=Y, `6`=Back/View, `7`=Start/Menu,
  `8`=left-stick press, `9`=right-stick press, `10`=Guide.
  Bumpers `4`/`5` are reserved for mode switching and never reach a mode.
- Axes: `0`=left X, `1`=left Y, `2`=right X, `3`=right Y.
  Negative = up / left, positive = down / right.
- Hat: `x` is `-1`/`0`/`1` (left/centre/right), `y` is `1`/`0`/`-1` (up/centre/down).

## Helper functions (`from src.controller.gamepad_mode_api import ...`)

- `setup_mode_translations(__file__, domain)` - load the mode's own gettext domain
- `tap(key)` / `press(key)` / `release(key)` - simulate keystrokes
- `tap_combo(*keys)` - simulate a chord, e.g. `tap_combo('ctrl', 'c')`
- `type_text(text)` - type a string
- `speak(text)` - send text to the screen reader / stereo speech
- `play_mode_sound(path)` - play a TCE sound effect (default `joystick/ui2.ogg`)
- `get_clipboard_text()` - read the clipboard (Windows)
- `get_focused_window_text()` - read the focused control's full text, read-only
  via `WM_GETTEXT` (no keystrokes / caret movement); good for grabbing a
  document into a virtual buffer (Windows)
- `is_edit_field_focused()` - `True` when a text caret is present (Windows)

Key names for `tap`/`press` include single characters plus: `enter`, `escape`,
`backspace`, `tab`, `space`, `shift`, `ctrl`, `alt`, `win`, `insert`, `delete`,
`home`, `end`, `pageup`, `pagedown`, `up`, `down`, `left`, `right`, `capslock`,
`num0`..`num9`.

## Translations

Author the `languages/<domain>.pot` template and per-language
`languages/<lang>/LC_MESSAGES/<domain>.po` files, then compile to `.mo`:

```bash
python -m babel.messages.frontend compile \
    -d data/gamepad/modes/my_mode/languages -D my_mode
```

See the `document_reader` folder for a complete, working example.

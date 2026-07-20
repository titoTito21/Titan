# Titan Gamepad Mode Creation Guide

## Introduction

Custom gamepad modes are folders under `data/gamepad/modes/`, exactly like a
component, that plug into Titan's controller mode cycle. With a gamepad
connected, **holding a bumper for about a second** switches modes (LB =
previous, RB = next) — the built-in modes (System, Controller, Screen
reader, Screen keyboard) come first, then every custom mode found here.
While a custom mode is active it receives the controller's button /
analog-stick / d-pad / bumper-tap events through `handle_*` hooks, and can
speak, play sounds, or simulate keystrokes in response.

The canonical API reference lives in `src/controller/gamepad_mode_api.py`
(read its module docstring), and `data/gamepad/modes/README.md` documents
it for third-party authors. `data/gamepad/modes/document_reader/` is a
complete, working worked example.

## Gamepad Mode System Architecture

### Mode Location

All custom modes are located in `data/gamepad/modes/` (bundled) and the
per-user overlay `%APPDATA%/titosoft/Titan/data/gamepad/modes/`. Each mode
is a separate directory containing:
- `__mode__.TCE` — mode configuration file (INI format)
- a Python file with a `GamepadMode` subclass (referenced by `main=` in the
  config, or the only `*.py` file in the folder if `main=` is omitted)
- optionally a `languages/` folder with the mode's own gettext domain
- optionally a `lib/` folder with vendored third-party dependencies

### Mode Lifecycle

1. **Discovery** — `load_custom_modes()` scans both mode directories at
   startup, reads `__mode__.TCE`, and skips disabled/broken folders
2. **Instantiation** — the `GamepadMode` subclass found in the main module
   is instantiated once and added to the mode cycle
3. **Activation** — `on_activate(manager)` is called when the user cycles
   into this mode (hold a bumper for ~1s)
4. **Input handling** — `handle_button`/`handle_axis`/`handle_hat`/
   `handle_bumper` are called for each discrete input event while the mode
   is active
5. **Deactivation** — `on_deactivate(manager)` is called when switching away

## Configuration File Structure

### `__mode__.TCE`

INI file with a `[mode]` section:

```ini
[mode]
name = My Mode
name_pl = Mój tryb
name_en = My Mode
main = my_mode.py
description = What the mode does
libs = lib
status = 0
```

**Parameters:**
- `status` — **`0` = enabled (loaded), anything else = disabled** (same
  convention as components)
- `name` / `name_<lang>` — the label announced when the mode is selected.
  The loader picks `name_<current_lang>`, then `name_en`, then `name`,
  then falls back to the folder name.
- `main` — the Python file containing the `GamepadMode` subclass. If
  omitted, the loader picks the alphabetically-first `*.py` file in the
  folder.
- `libs` (optional) — comma-separated dirs under the mode folder added to
  `sys.path` before the mode loads (default `lib`), so the mode can vendor
  its own third-party dependencies without polluting the host environment.
  See `data/gamepad/modes/titan_talk/lib/` for a real example (vendors
  `uiautomation` and `Pillow`).
- **There is no `domain=` config key.** The gettext domain is determined
  entirely by the string literal you pass to
  `setup_mode_translations(__file__, 'my_mode')` in the mode's own `.py`
  file — that call is the only place the domain is actually decided.
- **IMPORTANT**: Include a blank line at end of file

## The Mode Class

```python
from src.controller.gamepad_mode_api import (
    GamepadMode, setup_mode_translations, speak, play_mode_sound,
    tap, tap_combo,
)

# Loads this mode's own languages/ folder (gettext domain "my_mode")
_ = setup_mode_translations(__file__, 'my_mode')


class MyMode(GamepadMode):
    name = "My Mode"  # fallback label; __mode__.TCE name(_lang) wins

    def on_activate(self, manager):
        """Called when this mode becomes active."""
        speak(_("My Mode activated."))

    def on_deactivate(self, manager):
        """Called when switching away from this mode. Optional cleanup."""
        pass

    def handle_button(self, button_id):
        """Button press (0=A, 1=B, 2=X, 3=Y, 6=Back, 7=Start, 8=LS, 9=RS, 10=Guide)."""
        if button_id == 0:  # A
            play_mode_sound('joystick/ui1.ogg')
            speak(_("A pressed"))
            return True
        return False

    def handle_axis(self, axis_id, value):
        """Analog-stick flick, debounced (0=left X, 1=left Y, 2=right X, 3=right Y).
        value is negative for up/left, positive for down/right."""
        return False

    def handle_hat(self, x, y):
        """D-pad movement, edge-detected. x: -1/0/1 left/centre/right,
        y: 1/0/-1 up/centre/down."""
        return False

    def handle_bumper(self, is_left):
        """Bumper TAP only (holding a bumper still switches modes).
        is_left True = LB, False = RB."""
        return False
```

The loader instantiates any `GamepadMode` subclass defined in the main
module — subclass it and override only the hooks you need; all have safe
no-op defaults.

## Hooks Reference

| Method | Called when | Return |
|--------|-------------|--------|
| `on_activate(manager)` | the mode becomes active | — |
| `on_deactivate(manager)` | switching away from this mode | — |
| `handle_button(button_id)` | a button is pressed (once per press, not release) | `True` if handled |
| `handle_axis(axis_id, value)` | an analog stick flicks past the dead-zone (debounced — one call per discrete flick) | `True` if handled |
| `handle_hat(x, y)` | the d-pad changes direction (edge-detected) | `True` if handled |
| `handle_bumper(is_left)` | a bumper is **tapped** (short press+release, not a hold) | `True` if handled |

Bumpers (buttons 4/5) never reach `handle_button` — they're reserved for
mode switching. A **tap** (press+release under the hold threshold) is
delivered to `handle_bumper` instead; **holding** a bumper for ~1s still
changes the controller mode regardless of what the active mode returns.

## Button / Axis / Hat Numbering

Standard Xbox / XInput layout:

- **Buttons**: `0`=A, `1`=B, `2`=X, `3`=Y, `6`=Back/View, `7`=Start/Menu,
  `8`=left-stick press, `9`=right-stick press, `10`=Guide. `4`/`5`
  (bumpers) never reach `handle_button`.
- **Axes**: `0`=left X, `1`=left Y, `2`=right X, `3`=right Y. Negative =
  up/left, positive = down/right.
- **Hat**: `x` is `-1`/`0`/`1` (left/centre/right), `y` is `1`/`0`/`-1`
  (up/centre/down) — pygame's hat convention.

## Helper Functions

All importable from `src.controller.gamepad_mode_api`:

- `setup_mode_translations(__file__, domain)` — load the mode's own
  gettext domain from its `languages/` folder; falls back to identity if
  missing
- `speak(text, position=0.0, interrupt=True, pitch_offset=0)` — send text
  to the active screen reader / Titan TTS (stereo pan + pitch aware)
- `play_mode_sound(path='joystick/ui2.ogg', pan=None, elevation=0.0)` —
  play a TCE sound effect from the current sfx theme
- `tap(key, hold=0.04)` / `press(key)` / `release(key)` — simulate a
  single keystroke (pynput-backed, falls back to the `keyboard` package on
  Windows) — cross-platform
- `tap_combo(*keys, hold=0.04)` — simulate a chord, e.g.
  `tap_combo('ctrl', 'c')`
- `type_text(text)` — type a string character by character
- `get_clipboard_text()` — read current clipboard text (**Windows only**,
  `''` on other platforms)
- `get_focused_window_text()` — read the focused control's full text via
  `WM_GETTEXT`, read-only — no keystrokes, no caret movement (**Windows
  only**, `''` elsewhere); good for grabbing a document into a virtual
  buffer
- `is_edit_field_focused()` — `True` when a text caret is present
  (**Windows only**; returns `True` on other platforms so modes stay
  usable)

Key names for `tap`/`press`/`release`: single characters plus `enter`,
`escape`, `backspace`, `tab`, `space`, `shift`, `ctrl`, `alt`, `win`,
`insert`, `delete`, `home`, `end`, `pageup`, `pagedown`, `up`, `down`,
`left`, `right`, `capslock`, `num0`..`num9`.

## Design Principles

1. **Never silently drive the focused app** — prefer read-only inspection
   (`get_focused_window_text`, `get_clipboard_text`) over keystroke
   injection unless the mode's whole purpose is to act as a remote control
2. **Always give audio feedback** — every handled event should `speak()`
   or `play_mode_sound()` something; a silent gamepad mode is unusable for
   a blind user
3. **Announce yourself on activation** — `on_activate` should briefly
   explain the controls so the user doesn't need to look anything up
4. **Return `True` only when you actually handle the event**
5. **Keep `handle_*` fast** — these run on the controller polling thread;
   don't block on network/disk I/O inside them

## Complete Example: Media Control Mode

A simple mode mapping face buttons to media playback, with audio feedback
on every action.

**File: `data/gamepad/modes/media_control/__mode__.TCE`**
```ini
[mode]
name = Media Control
name_pl = Sterowanie mediami
name_en = Media Control
main = media_control.py
description = Control media playback with face buttons: A play/pause, B next, X previous, Y mute.
status = 0
```

**File: `data/gamepad/modes/media_control/media_control.py`**
```python
"""
Media Control - custom gamepad mode for TCE.

Controls:
  * A (0) - Play / Pause
  * B (1) - Next track
  * X (2) - Previous track
  * Y (3) - Mute / Unmute
"""

from src.controller.gamepad_mode_api import (
    GamepadMode, setup_mode_translations, speak, play_mode_sound,
)

_ = setup_mode_translations(__file__, 'media_control')


class MediaControlMode(GamepadMode):
    name = "Media Control"

    def on_activate(self, manager):
        speak(_("Media control. A play pause, B next, X previous, Y mute."))

    def handle_button(self, button_id):
        if button_id == 0:  # A
            play_mode_sound('joystick/ui1.ogg')
            speak(_("Play / Pause"))
            return True
        if button_id == 1:  # B
            play_mode_sound('joystick/ui1.ogg')
            speak(_("Next track"))
            return True
        if button_id == 2:  # X
            play_mode_sound('joystick/ui1.ogg')
            speak(_("Previous track"))
            return True
        if button_id == 3:  # Y
            play_mode_sound('joystick/ui1.ogg')
            speak(_("Mute"))
            return True
        return False
```

## Reference Examples

- **document_reader** (`data/gamepad/modes/document_reader/`): Read-only
  virtual-buffer reader — captures the focused text field or clipboard
  into its own buffer and navigates it line-by-line / char-by-char without
  ever touching the real caret. Full translation support (`languages/`).
- **titan_talk** (`data/gamepad/modes/titan_talk/`): Heavier example that
  vendors third-party dependencies (`uiautomation`, `Pillow`) via `lib/` —
  a joystick-driven screen reader.

## Translation Setup

```bash
# 1. Create languages/ directory inside the mode folder
mkdir data/gamepad/modes/my_mode/languages

# 2. Extract translatable strings
pybabel extract -o languages/my_mode.pot --no-default-keywords --keyword=_ \
    data/gamepad/modes/my_mode/my_mode.py

# 3. Initialize languages
pybabel init -l pl -d data/gamepad/modes/my_mode/languages \
    -i data/gamepad/modes/my_mode/languages/my_mode.pot -D my_mode
pybabel init -l en -d data/gamepad/modes/my_mode/languages \
    -i data/gamepad/modes/my_mode/languages/my_mode.pot -D my_mode

# 4. Compile
pybabel compile -d data/gamepad/modes/my_mode/languages
```

## Packaging as `.TCD` (Optional)

Instead of shipping a directory, a gamepad mode can be distributed as a
single `.tcd` file — same content, including any bundled `lib/` native
dependencies. Purely optional and additive.

```bash
python src/scripts/pack_addon.py data/gamepad/modes/my_mode --kind gamepad_mode -o my_mode.tcd
```

- `.tcd` is a custom compressed container (magic header + LZMA payload),
  deliberately not a real zip/7z — 7-Zip and Windows Explorer refuse to
  open it as an archive.
- No code changes needed: the payload is byte-identical to the directory,
  so `__mode__.TCE` and the main `.py` file still resolve the same way
  once extracted, and vendored `lib/` dependencies work unmodified.
- Drop the `.tcd` into `data/gamepad/modes/` (bundled or per-user overlay)
  and it's discovered identically to a directory-based mode.

See `src/titan_core/titan_package.py` for the format implementation.

## Multiplatform Requirements

Gamepad modes run inside TCE's controller polling loop on **Windows,
macOS, and Linux**.

- `speak()`, `play_mode_sound()`, `tap()`/`press()`/`release()`/
  `tap_combo()` are already cross-platform (pynput-backed) — use them
  freely
- `get_clipboard_text()`, `get_focused_window_text()`,
  `is_edit_field_focused()` are **Windows-only** — they return safe
  defaults (`''` / `True`) on macOS and Linux; a mode that depends on them
  should announce gracefully when the returned value is empty rather than
  assuming Windows
- Do not import `win32com`, `winreg`, or other Windows-only modules at
  module level without a `try/except` or `sys.platform == 'win32'` guard

## Testing Your Mode

1. Create the mode folder under `data/gamepad/modes/`
2. Add `__mode__.TCE` and the main `.py` file with a `GamepadMode` subclass
3. Restart TCE with a gamepad connected
4. Hold LB/RB for ~1 second to cycle to the new mode; confirm it announces
   itself on activation
5. Test every button/stick/d-pad/bumper-tap control you implemented
6. Check console output for `[GamepadMode] loaded mode '...'` — if it's
   missing, check `status = 0` and that the main file has a `GamepadMode`
   subclass

## Key Tips

1. **Always give audio feedback** — sounds and/or TTS for every handled
   event
2. **Announce controls on activation** — don't make the user guess
3. **Never assume Windows** — use the multiplatform guards above
4. **Keep input handlers fast** — they run on the controller polling
   thread
5. **Prefer read-only inspection over keystroke injection** unless the
   mode is explicitly a remote control

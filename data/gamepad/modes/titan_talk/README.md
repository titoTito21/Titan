# Titan Talk - talking gamepad (joystick screen reader)

An external gamepad mode that turns the controller into a screen reader. Switch
to it by HOLDING a bumper until the mode cycle reaches **Titan Talk**.

## Controls

- **Left stick / D-pad** - move spatially between on-screen controls (the control
  list is an in-memory buffer, navigated and spoken like a screen reader's
  browse mode; there is no separate window).
- **A** - activate the current control (invoke a button, toggle a check box,
  focus an edit field / slider, click a menu option).
- **B** - back / Escape.
- **X** - repeat the current control.
- **Y** - rescan the current scope.
- **Bumper TAP (LB / RB)** - switch scope. (HOLDING a bumper still changes the
  controller mode at the host level.)

## Scopes (bumper tabs)

1. **Window switcher** - move between open windows; A focuses one. Uses
   `pywinctl` (already a core Titan dependency).
2. **Window controls** - native controls of the focused window via UI
   Automation: button, edit field, slider, check box, radio, combo box, menu
   item, list item, tab, link. Announces grouping containers (list / menu /
   group) on enter / leave.
3. **Audio game** - games / apps with no accessibility, read by Google Gemini
   vision (OCR). Screenshots the foreground window, finds the readable text and
   controls, A clicks the selected one.

## Speech

Each control is announced as **name** (normal pitch), **type** (lower pitch) and
**state / value** (higher pitch), panned to its on-screen position when stereo
or 3D sound positioning is on. When Titan TTS is off (accessible_output3
fallback, which has no pitch control) the three parts are spoken as one plain
line instead.

## Gemini API key

The audio game scope needs a Google Gemini API key. Set it in the settings file
(`bg5settings.ini`) under:

```
[titan_talk]
api_key=YOUR_KEY
```

The model is chosen automatically over the network once a key is present
(`list_models` -> a multimodal "flash" model), so there are no "model not found"
errors. Override with `[titan_talk] model=...` if you ever need a specific one.

## Dependencies (vendored in `lib/`)

`lib/` is pip-installed and git-ignored. Rebuild it with:

```
pip install --target "data/gamepad/modes/titan_talk/lib" --no-deps uiautomation Pillow
```

`comtypes` (used by uiautomation) and `google-generativeai` come from the core
Titan environment.

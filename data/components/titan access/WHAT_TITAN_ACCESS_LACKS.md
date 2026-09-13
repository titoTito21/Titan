# What Titan Access has not got, measured against the NVDA add-on

Read out of both trees on 2026-09-13, by asking which of the modules the
two readers share (`titan_access/portable/`, vendored from
`nvda-addon/addon/globalPlugins/titanEnhancements/` by
`src/scripts/vendor_reader_modules.py`) are actually REACHED by Titan
Access's own engine, and which of the add-on's NVDA-only modules have an
equivalent here. A module that is vendored and called by nothing is the
silent kind of gap: it imports, it passes the suite, and the user has no
way to reach it.

## Done in this pass

- **Polish for every shared sentence.** The shared modules say
  `_('Top left')` with the English as the key; `portable/i18n.py` looked
  for a `translate` in `localization.py` and there was none, so Titan
  Access walked its lists in English on a Polish Titan. `localization.
  translate` exists now, and `vendor_reader_modules.py` carries the
  add-on's Polish for every shared sentence into `locale/pl.json` on each
  run (704 sentences the first time). `--check` fails when one is missing.
- **The three layouts, the named corners and Right into a submenu** in
  the virtual window, the palette and a message: `engine._walked_key`
  answers Numpad 7/9/1/3 (corners), Numpad 4/6 (layout), Shift and
  Control with Left/Right, and `on_walked_numpad` is asked BEFORE object
  navigation so those keys reach a walked list with NumLock off.
- **The sound scheme is applied** where Titan Access turns a control's
  states into words (`accessible._state_segment` ->
  `portable/schemes.answer`), so a state given a sound under either
  reader is a sound here too. Sounds of every source play through
  Titan's own mixer in-process (`icons.play_titan` finds
  `src.titan_core.sound` when it runs inside Titan), including `.ogg`.
- **The walked reader manager** - markers, programs, procedures, names,
  monitors, the auditory icons, the sound scheme, the voices - on
  Insert+Shift+J (`action_reader_manager`), the key the add-on has it on.

## Still missing, in the order they are worth doing

1. **Touch gestures.** `portable/trackpad.py` reads the pad and hands the
   contacts to NVDA's `touchTracker`; Titan Access has no recogniser, so
   the toggle turns the pad on and nothing turns a drag into a flick.
   `portable/touchWalk.py` is vendored and ready - it needs a gesture
   source that calls `touchWalk.handle(action, x, y)` with NVDA's action
   names (`flickleft`, `2finger_flickup`, `hover`, `double_tap`). The
   honest way is a small recogniser of our own over the contacts
   `trackpad.feed` already produces (a tap, a double tap, a flick by the
   velocity of the last tenth of a second, the finger count).
2. **Auditory icons on the focus path.** `portable/icons.py` plays in the
   walked lists; nothing plays `icons.for_focus(obj)` when the focus
   moves in an ordinary program. `sound_manager.py` has its own cursor
   cues; the icon (WHAT it is) and the cue (WHERE it is) are different
   things and the add-on plays both.
3. **Voice classes.** `portable/classes.py` holds which semantic class
   has which pitch, rate and volume, and the manager shows them; Titan
   Access's `speech_adapter` never asks. The add-on's `voices.py` is
   NVDA speech commands and is not portable; the port is the same idea
   on `stereo_speech` (pitch offset, rate) per segment.
4. **Dialog kinds.** `portable/dialog_kind.py` recognises a question, a
   warning, an error from the icon a dialog holds; Titan Access announces
   the kind only when Titan TELLS it (`host_bridge.dialog_kind`). Asking
   `dialog_kind.kind_of(hwnd)` on a new foreground dialog is one call.
5. **Reader modules.** `portable/readerModules/` (JAWS-style app modules
   as data: which column names the kind of a row, which pane is live)
   is loaded by nothing here; `app_modules/` is Titan Access's own,
   hand-written set. Reading the same JSON where an app module is chosen
   would give both readers one set of modules.
6. **Markers, monitors, procedures, labels.** All portable, all listed by
   the manager now, none acted on: a marker cannot be jumped to, a monitor
   is not watched, a procedure is not run, a label the user gave a
   control is not read (`labels.py` IS used by `context_presenter`). Each
   is a small hook in `engine.py` on the focus path or a command.
7. **Live regions, busy and attention states, the terminal review, the
   drawn-window watcher, the guest reader** - NVDA-only modules with no
   equivalent here (`live.py`, `states.py`, `terminal.py`, `surface.py`
   is portable but unwired, `guest.py`). Titan Access has its own
   terminal app module and its own OCR (`ocr_assist.py`); the guest
   reading (`localOcr` + `virtualInput`, both portable) is reachable
   through `ocr_assist` but not driven by the arrow keys as in the add-on.
8. **The managers as forms** (`managerGui.py`, `classManager.py`) are
   NVDA's own wx windows. Titan has wx too; a Titan Access form would be
   the same dialogs on Titan's main frame.
9. **A settings page for the shared switches.** `icons.switched_on()`
   and `schemes.wanted()` read the add-on's `configSpec`, which is not
   here, so both answer "on" and cannot be turned off from Titan Access's
   own settings panel.

Every item above is one feature; none of them is a rewrite. The rule that
keeps this list honest: a feature may require Titan, and none of them may
require Titan Access - so what is added here must go on the same shared
module where the add-on has it, and be vendored, or it is a fork.

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

## Done in the second pass (2026-09-13)

- **Touch gestures.** `portable/touchRecognizer.py` turns the pad's raw
  contacts into NVDA's own gesture names (tap, double tap, flicks with
  the finger count, hover) where there is no NVDA tracker;
  `trackpad.feed` falls back to it, and `engine._on_touch` hands the
  gesture to a walked list first (`touchWalk`) and reads the control
  under the finger otherwise (`provider.object_from_point`).
- **Auditory icons on the focus path** (`engine._auditory_icon` ->
  `icons.for_focus`), with Titan Access's role names aliased into the
  icon table. Behind the `auditoryIconsEverywhere` switch, off.
- **Voice classes** - the pitch a user gave a class (name, kind, state,
  detail) is what `accessible.describe` speaks; rate and volume are not
  applied yet (Titan's segments carry a pitch only).
- **Dialog kinds** for every dialog on the machine
  (`dialog_kind.kind_of_window(hwnd)`, once per dialog window, said the
  way Titan's own kinds are).
- **Busy and attention** (`portable/states.py`, started and stopped with
  the engine).
- **Markers** by the control's place on the screen: Insert+Shift+K marks,
  Insert+K lists them and reads what is there now.
- **The reader's own switches on the settings page** (Reader section:
  auditory icons, everywhere, sound scheme, dialog kinds, busy,
  attention), through `portable/switchboard.py`, which asks NVDA's spec
  in the add-on and Titan Access's store here - one name per switch in
  both readers.

## Done in the third pass (2026-09-13)

- **One seam for what a module asks of the reader** (`portable/readerApi.py`):
  the window in front, the focus, what is at a point, focus this, do
  this, press this key. Markers, monitors and procedures ask it instead
  of NVDA's `api`; `titan_access/nvda_shape.py` installs the answers for
  this reader (`Hooks`) and gives every Titan Access object NVDA's
  attribute names (`Adapted`: `role.name`, `windowClassName`,
  `UIAAutomationId`, `location`, `children`, `parent`, `appModule`,
  `doAction`, `setFocus`), so every shared module reads this reader's
  controls without knowing it. A marker keyed by automation id here is
  the same marker under NVDA.
- **Markers, procedures and monitors act.** Insert+Shift+K / Insert+K
  (`markers.mark` / `markers.go`), Insert+Shift+R records and stops,
  Insert+R runs a procedure (keys through the `keyboard` library, a
  control's own UI Automation pattern for a press), Insert+Shift+W
  watches a control; `monitors.start()` runs the shared watcher.
- **Reader modules** match this reader's windows (`readerModules.for_object`
  on the adapted object) and add the kind of a row from the column the
  module names and a name for an unnamed pane (`engine._shared_layers`).
- **Live status bars**: the status bar of the window in front is read on a
  slow tick and handed to `live.changed`, which says once what changed.
- **The drawn-window watcher and the guest reader** are vendored
  (`surface`, `guest`, `guestNative`, `vgaFont`, `vmware`, `drawnText`)
  and told about every window that comes to the front
  (`engine._window_arrived`); a guest's arrow keys are read a moment
  after the guest has moved.
- **The agent channel** (`agentLink`) is vendored and started behind the
  `agentLink` switch (off).
- **The managers as forms**: `managerGui` and `classManager` are on
  `portable/wxkit.py` (NVDA's `guiHelper` where it exists, plain wx
  elsewhere) and open from the walked manager's "as a form" row.
- **Volume per voice class**: a class's volume offset travels as the fifth
  element of a segment and Titan's concatenated speech applies it as a
  gain on that part. The rate is still not applied.
- Every switch the shared modules ask about is on the settings page's
  Reader section, through the switchboard.

## Done in the fourth pass (2026-09-13)

- **A web page as a virtual window** (the ZDSR shape): `virtualWindow.
  document_rows` is a hook the reader underneath fills - Titan Access from
  its virtual buffer (`engine._document_rows`), NVDA from its tree
  interceptor - so a page is its lines in reading order, each with the
  control's role for quick navigation and its rectangle for a click.
- **Categories inside the category**: Titan's settings window nests
  (`register_category(..., parent=)`, children indented under their
  parent and registered under full names such as "Titan Access: Speech"),
  and the reader registers one child per section: Speech, General,
  Verbosity, Navigation, Dial, Reader, Sounds and switches, Text editing.
- **A voice of the reader's own**: Settings -> Titan Access: Speech ->
  "Give the reader a voice of its own" with engine, voice, rate, pitch
  and volume on a PRIVATE `StereoSpeech` (`tce_speech.
  get_private_reader_engine`), never the engine Titan's apps speak through.
- **The IA2 proxy**: `ia2.ensure_proxy()` finds a registered proxy or
  registers one already on the machine for this process, the way NVDA
  does. See `NVDA_NATIVE_MODULES.md` for every native piece of NVDA and
  what stands in for it here.
- **Sounds per reader event**, shared with the add-on: every kind of
  control the focus lands on and every event of the reader (a menu
  closing, a dialog, the end of a list, busy, attention, a marker, a
  procedure, the trackpad, Titan connecting) is a row of its own with its
  own sound and source.

## Done in the fifth pass (2026-09-13)

- **Rate per voice class.** `StereoSpeech.set_rate` remembers what it was
  set to, and `speak_concat` renders a part that carries a rate (the
  fourth element of a segment) with the engine set to base + offset and
  put back straight after, so "3 of 10" can be faster than the name in
  front of it. `accessible._part` carries the class's rate and volume
  beside its pitch.
- **The smart OCR cursor and the picture kinds** (`portable/smart.py`,
  `portable/graphics.py`) are vendored and reached: while a drawn window
  is being read, Tab / Shift+Tab / Up / Down walk the controls the model
  read, Enter presses, Escape gives the keys back (`engine._walked_key`,
  Left and Right never taken); a picture is said as an icon, a photograph,
  an animation or a chart at the control-type tone (`announce_object`).
  The shared speech shim gained NVDA's `speech.speak(sequence)` - the
  strings of a sequence as one line - which is what the cursor speaks
  through here.
- **The class manager lists Titan's engines and their voices** where NVDA's
  synthesizers are not, through `tce_speech`.
- **A proxy DLL of our own**: `helper/ia2proxy/` holds the BSD IA2 IDL,
  `merge_idl.py` and `build.bat` (vcvars64 + midl + cl + link), and
  `lib/IAccessible2Proxy.dll` is the result - the first candidate
  `ia2.ensure_proxy()` tries. `_register_in_process` asks the DLL's class
  object for `IPSFactoryBuffer` (a proxy/stub DLL's class object is that,
  not `IClassFactory`) and tries each IA2 interface id as the class id;
  measured here: registered, 18 interfaces.
- **Java Access Bridge** (`titan_access/jab.py`): `WindowsAccessBridge-64.dll`
  through ctypes, started on the engine's own message-pumping thread
  (`Windows_run` needs one). A Java window's focused control is read
  through the bridge where UI Automation answered a pane and nothing in
  it (`engine._java_focus`), and the virtual buffer asks a `jab` tier
  first (`jab.nodes`, breadth first) before UIA. Without a Java on the
  machine every answer is None and nothing changes.

## Done in the sixth pass (2026-09-13): speech schemes, and the arrows

- **Speech schemes, as JAWS has them** (`portable/speechSchemes.py`,
  shared): per KIND of control - buttons, check boxes, edit fields, list
  items, links, headings, tables, pictures, windows... - which parts are
  said (name, type, state, value, description, place), in what order, in
  which voice class each part, what the type is called, whether a sound
  stands for the type word (any reader event or a file of the user's
  own), and how it is shown in braille (the type's abbreviation or
  nothing, and which parts). Four ship - Classic, Terse, Sounds instead
  of type words, Verbose - and the user's own are copies, changed; one
  file for both readers, so a scheme made under NVDA is the scheme here.
  Applied in `accessible.describe` (the parts are built into slots and
  `speechSchemes.arrange` orders them) and the sound played in
  `announce_object`; Insert+Shift+S is the next scheme, and the schemes
  are a page of the walked manager (Insert+Shift+J) where every rule is
  edited with Enter (`portable/schemeWalk.py`). The braille half is
  written for NVDA's renderer; **Titan Access has no braille display
  yet**, and the rules wait for one.
- **Two more reader sounds**: the start of a gesture (the first finger
  down) and the start of exploration (the first finger that moves),
  noticed on the trackpad's raw contacts so both recognisers report them.
- **A walked list ends when its window is left.** The add-on ends a
  review whose window has gone from `event_gainFocus`; nothing here did,
  so a virtual window turned on in one program kept the arrow keys in
  the next - `engine._walkers_follow_the_focus` asks `left_the_window`
  of the virtual window, the OCR review and the palette on every focus
  change, the smart OCR cursor's keys are taken only while its window
  is in front, and `virtualWindow._foreground` asks the seam rather than
  NVDA's `api` (which answered None here, so the handle it kept was 0).

## Done in the seventh pass (2026-09-13): the list is closed

- **A display model** - the text a program DREW, read from the model
  rather than photographed. `portable/drawnText.read_window` (already
  vendored) is now a `drawn` tier of the virtual buffer, between the
  accessibility tiers and OCR (`virtual_buffer.build_drawn` ->
  `_nodes_from_reading`, a node per line with the character rectangles, so
  a line is pressed by a real screen rectangle). It is exact and free for
  a window whose process has an injected reader helper (one NVDA also
  reads); a window that draws its text another way, or has nothing of a
  reader in it, answers nothing and falls through to OCR - which is the
  honest boundary an out-of-process reader has, and why OCR stays.
- **Braille** (`titan_access/braille.py`): the focused control shown in
  cells. Translated with **liblouis** BUNDLED in the component's own
  `lib` (`liblouis.dll` + `lib/louis/tables`, so it works with no NVDA at
  all; an installed NVDA's copy is only a fall-back), the table chosen for
  Titan's language (computer 8-dot
  by default, the grade tables the machine's liblouis carries offered),
  the output real Unicode braille cells. Shaped by the speech scheme's
  braille rule (which parts, and the type's abbreviation). Sent to a
  display through **BRLTTY's BrlAPI** when one is running, and shown in a
  **viewer** window otherwise, so braille works with no hardware.
  Verified here: liblouis 3.39 translates "Save" and "Zapisz" to real
  cells, and `line_for` a button under a scheme is "Zapisz prz". A
  **Braille** section on the settings page (a reader section) switches it
  on, picks the table and the viewer. Off by default; a lookup and one
  liblouis call on the focus path when on.
- **The reader's sections are a second list.** Titan's settings window
  shows a category's sub-categories in a SECOND list beneath the settings
  categories, revealed only when a category that has sections is selected
  (the reader's) - `settingsgui`'s `child_order`, `subcategory_list` and
  `_show_subcategories`, so the top list stays the settings categories.

## The gap list is closed

Every module the two readers share is reached from Titan Access's engine,
every NVDA-only feature has an equivalent or an honest stand-in
(`NVDA_NATIVE_MODULES.md`), and the reader's own settings, sounds, voices,
speech schemes and braille are all here. What remains is not a gap but the
boundary of an out-of-process reader: a display model needs an injected
helper in the target process (a window that has one is read exactly; one
that has none falls through to OCR), and the Java bridge is unverified
because there is no Java on this machine (`jab.report()` says so).
2. The Java bridge is written against Oracle's documented ABI and has not
   been run against a live Java program on this machine (no Java here);
   `jab.report()` says whether it loaded and what it read.


## Sync pass (2026-09-14): every add-on feature reached or accounted for

Audited each module the two readers share against what the Titan Access
engine wires. Result: every APPLICABLE add-on feature is now reached here.

- **Wired this pass**: `windowKind` - an unrecognised top-level window is
  named an application, a game, a dialog or the desktop (through the seam's
  adapted object) instead of "unknown", the way the add-on's `elements`
  does; `draft` - "Write a reader module for this window" is a row of the
  walked manager in BOTH readers now (it reads the window through the seam
  and asks Titan's AI, so it works out of NVDA's process too).
- **Already reached** (shared modules the engine drives): speech schemes
  and their voices/pauses/earcon-kit/output-mode/sound-scheme switching,
  the sound scheme (states as sound/word/both by the scheme's output),
  auditory icons, dialog kinds, busy/attention, live regions, monitors,
  markers, procedures, the drawn-window watcher and guest reader, touch,
  graphics (picture kinds), smart OCR cursor, reader modules, braille,
  `perProgram` (used inside `surface`/`monitors`). The walked speech-scheme
  editor and the class-manager form are reached through the walked manager.
- **Not applicable by architecture** (NVDA-only, no Titan Access
  equivalent needed): `semantics` and `ancestry` - the app-module and
  focus-ancestry layers built on NVDA's object model and `titan.processes`;
  Titan Access has its own `context_presenter` and reads any window through
  its virtual buffer. `appReview` / `widgetReview` - NVDA-side walked
  reviews of a TCE application or widget; Titan Access reads those windows
  natively through the buffer, so it needs no separate review. The OCR
  review (`ocrReview`) is the add-on's screen-OCR walked list; Titan
  Access's equivalent is the virtual buffer's OCR tier and scan mode.

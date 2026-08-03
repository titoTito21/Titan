# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Installation and Setup
```bash
pip install -r requirements.txt
```

### Running the Application
```bash
python main.py
```

### Compilation to Executable
```bash
python compiletorelease.py
```
This uses PyInstaller to compile the application to a standalone executable in the `dist` directory. Requires PyInstaller: `pip install pyinstaller`

### Packaging Add-ons (.TCA / .TCD)

Any app, game, component, launcher, Titan IM module, gamepad mode, TTS
engine, widget/applet, or statusbar applet can OPTIONALLY be packaged into a
single compressed file instead of shipping as a directory — `.TCA` for
applications/games, `.TCD` for every other kind. This is purely additive:
directory-based add-ons keep working unchanged, and the packaged file, once
placed in the right `data/<subdir>/` folder, is discovered and used
identically (see `src/titan_core/titan_package.py` for the format itself).

```bash
# Pack (or convert) an existing add-on directory into a package
python src/scripts/pack_addon.py data/applications/tcalc --kind app -o tcalc.tca

# --kind is inferred from the source path if omitted (data/<subdir>/... ->
# app/game/component/launcher/im_module/gamepad_mode/tts_engine/widget/statusbar_applet)
python src/scripts/pack_addon.py data/components/mycomponent

# Inspect/unpack a package for debugging (does not touch the original file)
python src/scripts/pack_addon.py --unpack tcalc.tca -o /tmp/tcalc_inspect
```

Key properties:
- Custom binary container (magic `TCPK` + raw LZMA payload) — deliberately
  NOT a real zip/7z, so 7-Zip and Windows Explorer refuse to open it as an
  archive. This is obfuscation, not encryption.
- The payload, once read, is byte-identical to the source directory
  (including that add-on kind's own existing manifest file — `__app.TCE`,
  `__component__.TCE`, etc.) — no separate package manifest schema exists.
- The package file itself is permanent and never deleted or converted into
  a directory. `src/platform_utils.py`'s `discover_data_entries()` (the
  shared discovery function used by every one of the 9 add-on kinds)
  transparently extracts a package into a transient runtime cache
  (`%APPDATA%/titosoft/Titan/pkg_cache/`) on demand — this cache is purely
  a performance detail, never user-managed data.
- Windows: double-clicking a `.tca`/`.tcd` in Explorer (once
  `src/system/file_association.py` has registered the association, done
  automatically at startup) launches Titan with `--install-package <path>`,
  which copies the file into the correct per-user overlay `data/<subdir>/`
  directory and then launches it (apps/games) or lets normal startup pick it
  up (other kinds) — see `src/titan_core/package_install.py`.
- Can be uploaded to/downloaded from the Titan-Net app repository (see
  "Titan-Net Messaging System" below) the same way as any other repository
  file.

### Translation Management (Modular System)

The translation system uses modular .po/.mo files organized by domain (gui, settings, network, etc.)

```bash
# Extract, update, and compile all modular translations (recommended)
python src/scripts/extract_translations.py

# Or manually for a specific domain (e.g., 'gui'):
# Extract translatable strings to .pot file
pybabel extract -o languages/gui.pot --no-default-keywords --keyword=_ src/ui/gui.py

# Initialize new language (first time only)
pybabel init -l pl -d languages -i languages/gui.pot -D gui

# Update existing .po files
pybabel update -l pl -d languages -i languages/gui.pot -D gui
pybabel update -l en -d languages -i languages/gui.pot -D gui

# Compile all translations to .mo files
pybabel compile -d languages
```

**Translation Domains:**
- `gui` - Main GUI (src/ui/gui.py)
- `invisibleui` - Invisible UI (src/ui/invisibleui.py)
- `settings` - Settings (src/settings/settings.py, src/ui/settingsgui.py)
- `menu` - Menu system (src/ui/menu.py)
- `main` - Main program (main.py)
- `apps` - Application manager (src/titan_core/app_manager.py)
- `games` - Game manager (src/titan_core/game_manager.py)
- `components` - Component manager (src/titan_core/component_manager.py, src/ui/componentmanagergui.py)
- `notifications` - Notifications (src/system/notifications.py, src/ui/notificationcenter.py)
- `network` - Network/messengers (src/network/messenger_gui.py, src/network/telegram_gui.py, etc.)
- `titannet` - Titan-Net (src/network/titan_net.py, src/network/titan_net_gui.py)
- `system` - System (src/titan_core/tce_system.py, src/system/system_monitor.py, src/system/updater.py)
- `controller` - Controllers (src/controller/controller_ui.py, src/controller/controller_modes.py)
- `help` - Help (src/ui/help.py)
- `sound` - Sound (src/titan_core/sound.py)
- `accessibility` - Accessibility messages (src/accessibility/messages.py)
- `window_switcher` - Window Switcher (src/ui/window_switcher.py)

## Project Architecture

**TCE Launcher** is an accessible desktop environment/launcher written in wxPython with a modular architecture:

### Directory Structure
```
TCE Launcher/
├── main.py                    # Entry point
├── src/                       # Main source code (modular organization)
│   ├── ui/                    # User interface components
│   │   ├── gui.py            # Main wxPython GUI with TitanApp class
│   │   ├── invisibleui.py    # Alternative non-visual interface for screen readers
│   │   ├── menu.py           # MenuBar implementation
│   │   ├── settingsgui.py    # Settings GUI
│   │   ├── componentmanagergui.py  # Component manager GUI
│   │   ├── classic_start_menu.py   # Classic start menu
│   │   ├── shutdown_question.py    # Shutdown confirmation dialog
│   │   ├── help.py           # Help system
│   │   └── notificationcenter.py   # Notification center UI
│   ├── settings/              # Configuration management
│   │   ├── settings.py       # Settings handler (JSON-based)
│   │   └── titan_im_config.py # Messaging configuration
│   ├── network/               # Network and messaging
│   │   ├── titan_net.py      # Titan-Net WebSocket client
│   │   ├── titan_net_gui.py  # Titan-Net chat GUI
│   │   ├── telegram_client.py, telegram_gui.py, telegram_windows.py, telegram_voice.py
│   │   ├── messenger_client.py, messenger_gui.py, messenger_webview.py
│   │   ├── whatsapp_client.py, whatsapp_webview.py
│   │   └── run_messenger.py  # Messenger launcher
│   ├── titan_core/            # Core TCE functionality
│   │   ├── app_manager.py    # Application management
│   │   ├── game_manager.py   # Game management
│   │   ├── component_manager.py  # Component system
│   │   ├── tce_system.py     # System hooks and integration
│   │   ├── tce_system_net.py # Network system functions
│   │   ├── translation.py    # i18n system (gettext-based)
│   │   ├── sound.py          # Audio system with theme support
│   │   ├── tsounds.py        # TCE system sounds
│   │   └── stereo_speech.py  # Stereo audio speech
│   ├── system/                # System functions and utilities
│   │   ├── system_monitor.py # System resource monitoring
│   │   ├── system_tray_list.py  # System tray management
│   │   ├── notifications.py  # System notifications
│   │   ├── updater.py        # Auto-updater
│   │   ├── lockscreen_monitor_improved.py  # Lock screen detection
│   │   ├── klangomode.py     # Alternative Klango mode
│   │   ├── com_fix.py, fix_com_cache.py  # COM error handling
│   │   ├── key_blocker.py    # Keyboard input blocker
│   │   └── wifi_safe_wrapper.py  # WiFi utilities
│   ├── controller/            # Controller/gamepad support
│   │   ├── controller_ui.py  # Controller UI navigation
│   │   ├── controller_modes.py  # Controller mode management
│   │   └── controller_vibrations.py  # Haptic feedback
│   └── scripts/               # Utility scripts
│       ├── extract_translations.py  # Translation extraction
│       └── migrate_translations.py  # Translation migration
├── data/                      # Application data
│   ├── applications/          # Bundled applications
│   ├── components/            # System components (plugins)
│   ├── applets/               # UI widgets
│   └── Titan/                 # Titan system data
├── languages/                 # Translation files (.po/.mo)
├── sfx/                       # Audio themes
└── titan-net server/          # Titan-Net server
    ├── server.py             # WebSocket server (port 8001)
    ├── http_server.py        # HTTP API
    ├── models.py             # Database models
    └── config.py             # Server configuration
```

### Core System
- `main.py`: Entry point, handles startup, language initialization, command-line arguments
- `src/ui/gui.py`: Main wxPython GUI with `TitanApp` class, taskbar integration, application/game lists
- `src/ui/invisibleui.py`: Alternative non-visual interface for screen readers
- `src/ui/menu.py`: MenuBar implementation for system menus

### Plugin System
- **Applications**: Located in `data/applications/`, each has `__app.TCE` config file defining name, description, main file
- **Components**: Located in `data/components/`, each has `__component__.TCE` config file, loaded by `ComponentManager`
- **Applets**: Located in `data/applets/`, UI widgets for taskbar and desktop
- Applications use format: `name_pl=`, `name_en=`, `openfile=`, `shortname=`
- Components use INI format with `[component]` section
- Every plugin kind above (plus games, launchers, Titan IM modules, gamepad
  modes, TTS engines, and statusbar applets) can also ship as a single
  packaged `.TCA`/`.TCD` file instead of a directory — see "Packaging
  Add-ons" under Development Commands and `src/titan_core/titan_package.py`

### Core Managers
- `src/titan_core/app_manager.py`: Handles loading/running applications from `data/applications/`
- `src/titan_core/game_manager.py`: Manages games directory and game launching
- `src/titan_core/component_manager.py`: Loads and manages components, provides menu integration hooks
- `src/titan_core/titan_package.py`: `.TCA`/`.TCD` packaged add-on format — build/read/extract
- `src/titan_core/package_install.py`: Installs a package file into the correct per-user `data/<subdir>/` (used by the Explorer file-association flow)
- `src/system/file_association.py`: Registers `.tca`/`.tcd` double-click handling in Windows (`HKCU`, no admin needed)

### System Features
- `src/titan_core/sound.py`: Audio system with theme support, uses `accessible_output3` for TTS
- `src/titan_core/translation.py`: Modular i18n support using gettext with multiple translation domains, defaults to Polish (`pl`)
- `src/settings/settings.py`: Configuration management with JSON settings file
- `src/system/notifications.py`: System notifications and status monitoring
- `src/network/titan_net.py`: Network functionality and server communication

### Audio Themes
Located in `sfx/` directory with multiple theme folders (`default`, `longhorn`, `ubuntu_emacspeak`, etc.)

### Titan-Net Messaging System
- **Server location**: `titan-net server/` directory
  - `server.py`: Main WebSocket server (port 8001) for real-time messaging
  - `http_server.py`: HTTP API server (if needed)
  - `models.py`: Database models for users and messages
  - Requires `logs/` directory for server logging
- **Client**: `src/network/titan_net.py` - WebSocket client with async messaging capabilities
- `src/network/titan_net_gui.py`: Standalone chat GUI (optional)
- Integrated into main GUI with private messages, online users, chat history
- Audio notifications from `sfx/*/titannet/` directory
- SQLite database for users and messages
- Server runs on `ws://0.0.0.0:8001`, client connects to `ws://localhost:8001` by default
- **Remote UI (server-defined screens and whole services)**: the server
  describes a screen as declarative JSON and every client renders it with one
  generic renderer, so a new Titan-Net GUI never requires users to update
  Titan. Nothing executable crosses the wire — the client renders data and
  skips what it does not recognise, which is what keeps old clients working.
  - Two screen kinds:
    - `dialog` — a form (fields + buttons), shown modally
    - `view` — a **service**: a window with a menu bar, tab bar, list and
      controls. Views nest, so a service is a tree of them
  - Server: `titan-net server/remote_ui.py` (schema, validation, handler
    registry, result builders `view` / `refresh` / `back` / `goto` / `close`
    / `error` / `update`), `remote_screens` +
    `remote_screen_submissions` tables, WS messages `list_remote_screens` /
    `open_remote_screen` / `remote_screen_action`, HTTP `/api/remote-screens/*`
  - A service author drops a handler in `titan-net server/remote_ui_handlers/`
    (auto-imported at startup) — `example_server_report.py` is a form,
    `example_service.py` is a full service (tabs, menus, drill-down, search,
    per-row actions); each has a matching `.json`
  - Handler contract: `ctx.action` is `'open'` first, then the fired
    row/button/menu id, or the built-ins `'refresh'` (F5 + auto-refresh) and
    `'tab'`. `ctx.item` / `ctx.row` give the focused row, `ctx.values` the
    controls. `ctx.rows(...)` / `ctx.fill(...)` inject live data at open time
  - Publish with `python remote_ui_admin.py save <file.json> --slug <slug>
    --handler <handler>` or `POST /api/remote-screens`. The CLI runs from any
    machine: it WS-logs-in as staff and drives the HTTP API, and never opens
    the database directly (a second `Database()` next to the live server
    corrupts SQLCipher — the PID lock enforces this). Same commands manage
    sounds (`sounds`, `add-sound`, `play --to <user>`, `del-sound`) and can
    `push` a screen at somebody
  - Client: `src/network/remote_ui.py` — `RemoteScreenDialog` for forms,
    `RemoteServiceFrame` for services. Interaction is deliberately identical
    to `gui.py` / `feedback_hub.py`: row 0 is the tab bar, Left/Right cycles
    it, Enter opens, Escape goes back one level then closes, F5 refreshes,
    with the same stereo focus cues. Screens appear in Titan-Net's **Server**
    menu
  - Navigation state is a stack the server also keeps (it validates against
    its own copy of the screen); the client pops instantly and notifies via
    the reserved `__back__` action
  - The server can push a screen at a user unprompted (`push_remote_screen`,
    `POST /api/remote-screens/<slug>/push`)
- **Server sounds**: audio uploaded to the server once, then played at one
  user, a role, a room, or everybody.
  - Server: `server_sounds` table, files under `server_sounds/`, HTTP
    `/api/sounds/*` (upload / list / download / delete /
    `<name>/play`), WS `list_server_sounds` / `play_server_sound`,
    `TitanNetServer.push_server_sound(name, target)` for component code
  - Client: `src/network/server_sounds.py` caches by sha256 and plays through
    the normal TCE pipeline; `src/network/server_sounds_gui.py` is the
    moderator manager (Server menu -> Server Sounds)
  - Users can refuse server audio: Settings -> Titan-Net -> "Allow sounds
    sent by the server"; pushes are rate limited per recipient
- **App repository**: generic upload/browse/download catalog for distributable
  content (apps, components, games, and now `.TCA`/`.TCD` packages of any
  add-on kind), backed by the `app_repository` table (`titan-net server/models.py`),
  HTTP endpoints in `titan-net server/http_server.py` (`/api/repository/*`),
  web UI (`titan-net server/web/repository.html`), and the desktop client's
  Upload Package / Package Folder and Upload dialogs (`src/network/titan_net_gui.py`)

### Titan IM: WhatsApp and Messenger (web as backend)

WhatsApp Web and messenger.com are **engines, not interfaces**. A WebView2 host
lives offscreen, an injected JavaScript agent talks to the page and *pushes*
structured events, and Titan renders them in its own accessible client - the
same interaction as Titan-Net / Elten / the Feedback Hub. The user never has to
touch Meta's UI; the raw page is brought on screen only on request (a Messenger
login checkpoint, a captcha, diagnostics).

- **Engine layer** (`src/network/im_web/`):
  - `bridge.py` - offscreen `wx.Frame` (parked at -32000,-32000, shown with
    `ShowWithoutActivating`), `AddUserScript` at document start so the agent
    survives reloads/SPA navigation, `AddScriptMessageHandler` for push events,
    `RunScriptAsync` envelopes with ids/timeouts/queueing-until-ready.
    Sets `WEBVIEW2_USER_DATA_FOLDER` to
    `%APPDATA%/titosoft/Titan/IM COOKIES/WebView2` (cookies/session in user
    data, never next to the exe) plus the flags that stop Chromium throttling
    an "occluded" window. Called at import time - it must run before any
    WebView2 in the process.
  - `base.py` - the service-agnostic contract: `Chat` / `Message` / `Contact` /
    `CallState`, events (`ready`, `auth_state`, `chats`, `chat_updated`,
    `messages`, `message_new`, `message_updated`, `typing`, `presence`, `call`,
    `media_ready`, `error`) and commands (`list_chats`, `load_history`,
    `send_text`, `reply_to`, `react`, `edit_message`, `delete_message`,
    `mark_read`, `search`, `list_participants`, `send_attachment`,
    `download_media`, `start_call`, ...). Attachments travel as base64 in
    bounded chunks through the `__blob_*` commands. Media received over a CDN
    URL is fetched in Python when the page cannot read it cross-origin.
  - `js_bridge.py` / `js_whatsapp.py` / `js_messenger.py` - the agents, kept as
    Python strings like `call_detection_js.py` (no extra PyInstaller `datas`).
    WhatsApp is **store-first**: the page's own module registry
    (`window.require('__debug').modulesMap`, or the webpack chunk-push trick)
    gives real collections and actions, discovered by *shape* rather than by
    module name, with a `MutationObserver` DOM fallback. Messenger has no
    readable store, so it is DOM-first (real thread ids come from the
    `/t/<id>/` row links) with `fetch`/`XHR`/`WebSocket` wrapped at document
    start purely as a "something changed, re-read now" hint.
  - **Capabilities**: the agent reports what the live page actually supports;
    clients hide tabs and menu items for anything missing, which is how the
    whole thing degrades instead of raising when Meta reshuffles its internals.
  - Calls reuse `src/network/call_detection_js.py` unchanged - its state machine
    is what fixed the phantom "incoming call" - and only drain its event queue
    into the bridge, so nothing polls the page from wx any more.
- **Clients**: `whatsapp_titan_gui.py` (`show_whatsapp_client`) and
  `messenger_titan_gui.py` (`show_messenger_client`) are deliberately separate
  windows with their own tabs, menus and login flows. Shared plumbing lives in
  `im_ui_common.py` (row 0 = virtual tab bar, Left/Right cycling, stereo focus
  cues, F5, Escape-one-level), `im_client_base.py`, `im_conversation.py`
  (Messages / Media / Files / Links / Participants) and `im_call_ui.py`.
- **Login without a QR code**: WhatsApp asks for the 8-character link-device
  pairing code and Titan reads it out; Messenger fills its own form from a
  Titan dialog and only offers the page for a checkpoint/2FA/captcha.
  Remembered phone number / e-mail go into the encrypted `titan.IM` file
  (`src/settings/titan_im_config.py`, `get_web_im_value` / `set_web_im_value`).
- **Sounds** come from the Titan-Net set via `src/network/titanim_sound_api.py`.
- **Buffers**: `IMBackend._emit` pushes into the Titan Buffer System
  (`register_whatsapp` / `register_messenger` in `src/buffers/defaults.py`:
  `pm`, `groups`, `calls`, `notifications`, plus `channels` when reported), from
  the *backend* - so buffers keep filling while the client window is closed.
- The legacy visible windows (`messenger_webview.py`, `whatsapp_webview.py`)
  are still in the tree and importable, but every entry point (`gui.py`,
  `invisibleui.py`, `klangomode.py`, `launcher_manager.py`,
  `messenger_client.py`, `whatsapp_client.py`, `src/ai/titan_tools.py`) now
  opens the accessible clients instead.

### AI OCR: an accessible mimic of an inaccessible program

Some programs cannot be read at all - a game's custom-drawn menu, an installer
that paints its own widgets, an app that exposes no accessibility tree. AI OCR
photographs the window, has the AI **read** it into a structured description,
and renders that as an ordinary accessible Titan window whose rows press the
real controls. It lives in `src/ai/ocr/`.

- **The pipeline** (`recognizer.py`): capture -> skip if the picture has not
  changed -> vision call -> merge with UI Automation -> validate. Step 2 is
  what makes watching a screen affordable; step 4 is what makes clicking safe.
- **Coordinates** (`capture.py`): the model is shown a downscaled PNG and
  answers in *image* pixels, and `Capture` - which alone knows the scale factor
  and the origin - is the only thing that converts them to screen points. The
  model is never asked to do arithmetic, and a rectangle that cannot be inside
  the picture loses its position (the entry stays readable, but unpressable).
- **The Screen model** (`model.py`): `Screen` -> `Region` -> `Element`, which
  maps one-to-one onto Titan's tab-bar-and-list interaction. `from_ai` never
  raises: prose, a bare array, a missing `regions` key and unknown role names
  all still produce the best Screen that can be salvaged, plus a warning.
- **The UIA merge** (`uia_snapshot.py`): where Windows *can* answer, its answer
  is exact, so a control matched by name takes Windows' rectangle and enabled
  state over the model's guess. On a genuinely inaccessible window this returns
  nothing and costs nothing.
- **Acting** (`actions.py`): one click per keypress, only into the window that
  was read (raised first, ownership re-checked at the point), only when
  "Let AI OCR press controls" is on; the mouse is put back afterwards. Whole
  keys (Escape, arrows, Enter) can be sent instead, which needs no coordinates
  at all.
- **The overlay** (`overlay.py`, Ctrl+O in the mimic; what the AI OCR shortcut
  opens by default): the reading rendered **onto the real window** instead of
  into a window of Titan's - every control a real wx control at the exact
  coordinates of the real one, control over control, window over window (a
  region read as a dialog gets its own surface over the real dialog, focused
  first). There is no second window: the surface is `SetParent`-ed into the
  target's own `HWND` as a `WS_CHILD`, so Windows moves, clips, minimises and
  closes it with the target, and `AttachThreadInput` is what lets a child of
  another process take keyboard focus. It falls back to an *owned* window and
  then to a floating always-on-top one that follows with a timer. Two details
  carry it: **cloaking** (fully transparent plus `WS_EX_TRANSPARENT` while a
  picture is taken or a click is sent, so AI OCR never reads its own controls
  or clicks its own buttons - Ctrl+H does it on demand), and **a measured
  scale** (a DPI-aware target adopting a DPI-unaware Titan window silently
  rescales it, so the surface is placed, read back, and everything scaled by
  the difference). A surface is titled with the **window's own title** and
  nothing else - the overlay is that window made readable, not a Titan window
  about it.
  - **Every control appears as itself**: text and headings as read-only
    (focusable) text boxes, fields as `wx.TextCtrl`, tick boxes as `wx.CheckBox`
    (three-state when the reading could not tell), option buttons as real
    *groups* of `wx.RadioButton` (`controls.py`'s `cluster_radio_runs` +
    `group_starts` keep a region's options contiguous and give the first
    `RB_GROUP`, because wx groups by creation order), sliders as `wx.Slider`
    when the range is known and Less/More buttons when it is not, meters as
    `wx.Gauge`, combo boxes as a button that opens the real one, and the
    **menu bar** as a real `wx.Menu` on F10 (plus its titles in place).
  - **Alt+Tab brings the controls with the window**: the follow timer notices
    the target coming back to the front, shows the surfaces, puts the focus on
    the control the user left, and only re-reads if a *locally* compared
    picture says the screen changed while they were away (never a request just
    for switching windows).
  - **The AI OCR shortcut hides and restores the overlay** once one is up
    (`toggle_hidden`), so the real window can always be used as it is; Escape
    removes it for good, Ctrl+H puts it out of the way without hiding it.
  - Keys: Tab/Enter as anywhere, F5 re-read, F6 next surface, F10 menu bar,
    Ctrl+R read this control, Ctrl+S the summary, Escape back to the list.
  - Settings -> AI features -> "Where the controls appear" picks this or the
    list; the shortcut opens this by default.
- **Two in-window views** (Ctrl+M, and a fresh reading picks one by itself):
  - the **reading list** (`mimic.py`): `TabbedListFrame` from `im_ui_common`,
    reused rather than copied so the interaction cannot drift from the rest of
    Titan. Regions are tabs (plus **Everything** and **Summary**), Enter
    presses, F5 re-reads, Ctrl+L watches and announces only the *diff*, Ctrl+F
    asks a free-text question. Best for menus and walls of text.
  - the **rebuilt controls** (`form_view.py`): the screen re-created out of
    real wx widgets - `wx.TextCtrl` for a field, `wx.Slider` for a slider,
    `wx.CheckBox` for a tick box, `wx.Gauge` for a meter, buttons for the rest
    - reachable with Tab and announced like any Titan dialog. Changing one
    changes the real control. A screen with editable controls opens here.
    Rules: a control appears **as itself or not at all** (a slider with no
    known range becomes Less/More buttons rather than an invented 0-100 scale;
    a closed combo box becomes a button that opens it and re-reads); nothing is
    sent until the user commits (Enter or leaving a field, slider release);
    every change is followed by a re-read so the form shows what the program
    actually did. Escape goes back to the list before it closes.
- **Vision calls** go through `ai_provider.generate_vision()` (all three
  providers, non-streaming, temperature 0), and the provider is resolved by
  `resolve_vision_provider()` **the same way the voice assistant resolves
  its own** - the assistant's key first, then the configured provider, then any
  provider with a key. The "communication method" radio is deliberately ignored
  (it is about the creation kit, and a CLI cannot carry a picture), so a user
  whose assistant already works has nothing more to configure.
  `vision_unavailable_reason()` is what the UI says when nothing is set up.
- **Switching it on**: Settings -> AI features -> "Enable AI OCR", which also
  carries the scope, the two shortcuts (global and Titan-UI, registered by
  `src/ai/ocr/hotkeys.py` exactly like the assistant's), the live interval and
  the two safety switches. Off by default: a scan sends a picture of the user's
  screen to their provider. Also in Program -> AI OCR (read this screen).
- The `titan_talk` gamepad mode does a much simpler Gemini-only flat-list
  version of the same idea for audio games; this package is the general one.

### Key Dependencies
- wxPython for GUI
- accessible_output3 for screen reader output
- pygame for audio
- Nuitka for compilation
- babel for internationalization
- websockets for real-time messaging
- requests for HTTP API calls

The system is designed for accessibility with extensive screen reader support and keyboard navigation.

## Code Guidelines

### Notifications and Messages
- All notification messages and UI text MUST be in English
- Use translation support with gettext (_() function) for multilingual support
- Never use emojis in notifications or messages
- All user-facing text should use the translation system for proper localization
- Debug messages (print statements) can remain in any language - ignore debug formatting
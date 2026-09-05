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
engine, widget/applet, statusbar applet, shell add-on or settings interface
can OPTIONALLY be packaged into a
single compressed file instead of shipping as a directory — `.TCA` for
applications/games, `.TCD` for every other kind. This is purely additive:
directory-based add-ons keep working unchanged, and the packaged file, once
placed in the right `data/<subdir>/` folder, is discovered and used
identically (see `src/titan_core/titan_package.py` for the format itself).

```bash
# Pack (or convert) an existing add-on directory into a package
python src/scripts/pack_addon.py data/applications/tcalc --kind app -o tcalc.tca

# --kind is inferred from the source path if omitted (data/<subdir>/... ->
# app/game/component/launcher/im_module/gamepad_mode/tts_engine/widget/
# statusbar_applet/shell_addon/settings_interface)
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
  shared discovery function used by every one of the 11 add-on kinds)
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

### Programming Guides (data/docu/programming_guide/)

The guides a developer reads, one `_en.md` + `_pl.md` pair per add-on kind,
and the HTML made of them:

```bash
# Regenerate every HTML page and both index pages from the Markdown
python data/docu/programming_guide/convert_to_html.py
```

A new guide is a new pair of `.md` files plus four lines in
`convert_to_html.py` (`guides_pl` / `guides_en` in `generate_navigation` and
in `create_index_page`) - without them the page is still converted but does
not appear in the sidebar or on the index. The English guides are also what
`src/ai/creation_docs.py` injects into the AI creation kit's prompts, which
is why they are the authoritative copy.

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
│   │   ├── ui_model.py       # Every setting, read out of the settings window
│   │   ├── interfaces.py     # data/settings interfaces/ - the chosen window
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

### Startup: what Titan does on the way to its window

Measured on this machine before this work: `import main` **2827 ms**, then
building a Settings window nobody had asked for **2149 ms**, and then a flat
**`time.sleep(2)`** so the startup sound could play - three seconds and more
of a program that has been started and shows nothing. After: `import main`
**~810 ms**, the Settings window built after Titan's own is on the screen, and
the startup sound's two seconds SPENT loading rather than slept through.

- **Modules imported because Titan MIGHT need them are imported when it does**
  (`src/lazy_import.py`). Starting Titan imported the whole of Telegram,
  Messenger and WhatsApp - telethon, pytgcalls, aiohttp, requests - before the
  window appeared, whether or not the user has ever signed in to any of them:
  `src.network.telegram_client` alone was 723 ms and
  `src.network.messenger_client` another 762 ms. They cannot simply be deleted
  from the top of `gui.py` (about thirty places read
  `telegram_client.something`), so `lazy_import` binds the NAME at once and
  imports the module the first time something is read off it. `LazyModule` is
  a real `types.ModuleType` and the first attribute read makes it *become* the
  module, so after that there is no indirection left. Used for
  `telegram_client`, `telegram_windows`, `messenger_webview`,
  `whatsapp_webview` (`gui.py`), `telegram_client`, `messenger_client`
  (`invisibleui.py`) and `settingsgui` / `componentmanagergui` (the windows the
  Invisible UI opens).
  - **`if telegram_client:` must not import it.** The Invisible UI asks that
    while building its menu, in `InvisibleUI.__init__`, on every startup - so
    `__bool__` answers with `importlib.util.find_spec` (the file is found, the
    module is not run). A module that is installed but broken is now an entry
    that reports the failure when pressed rather than one that is silently
    absent, which for a program whose users cannot see a missing entry is the
    better of the two.
  - **The trap**: nothing static points at a lazily imported module any more,
    so PyInstaller cannot see it. Every name given to `lazy_import` is in
    `compiletorelease.py`'s hidden imports and in `Titan.spec`, and
    `tests/test_startup.py` fails if a new one is not.
- **`Auto()` is never built at import time.** `accessible_output3.outputs.auto`
  locates each backend's library by walking the entire current call stack
  (`inspect.getouterframes`), which at import time - with every one of Titan's
  modules on that stack - measured 300 ms, and importing the library itself is
  another 211 ms. `src/accessibility/lazy_speaker.py` already existed for this;
  `main.py`, `window_switcher.py` and `notificationcenter.py` were each making
  their own anyway, and now share the one `LazySpeaker`. The library import
  moved inside `get_shared_speaker()` as well.
- **The Settings window is built after Titan's own is shown.** It costs 2149 ms
  - it enumerates the SAPI voices over COM, loads every Titan TTS engine and
  probes for the speech subprocess bridge with a `subprocess.run` - and it is a
  window the user has not asked for. `build_settings_window()` runs on a
  `wx.CallAfter` after `frame.Show()` and **before** `init_components_delayed`,
  because that is when the components register their categories into it.
  Nothing earlier needs it: the Settings menu entry reads it off the frame when
  it is pressed, and if the user is quick enough to press it first, the menu
  builds the window and the deferred builder registers into THAT one rather
  than making a second.
- **The startup sound gets its two seconds; nothing sleeps through them.**
  `_start_startup_quiet(2.0)` marks the deadline and everything that follows -
  the component manager, the IM modules, the window, the menu bar - happens
  inside it; `_await_startup_quiet()` just before `frame.Show()` waits out
  whatever is LEFT, which on any real machine is nothing at all.
- **The update check may not hold a window that does not exist yet.** It runs
  before the GUI (an update is mandatory), and its version probe asked for
  `timeout=10` - ten seconds of a program that appears not to have started, on
  a machine that is offline or behind a captive portal.
  `updater.STARTUP_CHECK_TIMEOUT` is `(3.05, 4.0)` and a failed probe means
  "start normally". The DOWNLOAD keeps its long timeout: by then there is a
  window and a progress dialog to wait in. `src.system.updater` is also
  imported inside the call rather than at the top of `main.py` - it brings
  `requests` with it, for one call that happens once.
- Tests: `tests/test_startup.py` (run it directly; 17 tests).

### Plugin System
- **Applications**: Located in `data/applications/`, each has `__app.TCE` config file defining name, description, main file
- **Components**: Located in `data/components/`, each has `__component__.TCE` config file, loaded by `ComponentManager`
- **Applets**: Located in `data/applets/`, UI widgets for taskbar and desktop
- Applications use format: `name_pl=`, `name_en=`, `openfile=`, `shortname=`
- Components use INI format with `[component]` section
- **Shell add-ons**: `data/shell addons/`, each with `__shell_addon__.TCE` —
  they add to (or replace parts of) the Titan shell; see "Shell add-ons" below
- **Settings interfaces**: `data/settings interfaces/`, each with
  `__settings_ui__.TCE` — a window of their own onto Titan's settings; see
  "Settings interfaces" below
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

### The sound follows the headphones

`src/titan_core/audio_devices.py`. SDL opens ONE audio stream when Titan starts
and keeps it for the life of the process, and on Windows that stream belongs to
whichever endpoint was the default at that moment. So unplugging the headphones
left Titan talking into an endpoint that was not there - and plugging them back
in did not bring it back, because Windows moves the DEFAULT, not an open
stream. For a program whose entire interface is spoken, that is not a degraded
experience: it is a program that has disappeared.

- **Nothing noticed, because nothing was looking.** `pygame.mixer.get_init()`
  goes on reporting an initialised mixer the whole time, which is why every
  "was the mixer torn down externally" check in `sound.py` looked right and
  heard nothing. The module watches the endpoints instead: Windows' own
  `IMMNotificationClient` (through pycaw) says the moment it happens, and a
  2-second poll is the safety net that DECIDES - reading the endpoints costs
  about 0.9 ms, so being certain is cheaper than trusting a callback that
  cannot be tested on every machine.
- **The apartment is the trap.** The notification client is registered from a
  thread of Titan's own in the MULTI-threaded apartment, because a client
  registered in an STA is only called back from a message pump this thread has
  not got - and *importing comtypes is itself a CoInitializeEx into an STA*, so
  `start()` imports it on the CALLING thread and the watcher asks for its
  apartment before anything else COM happens on it. Get that wrong and
  everything still works, silently one poll slower, for ever.
- **What counts as a change is deliberately narrow**: the default endpoint is a
  different one, or the endpoint Titan was using is no longer active. A second
  sound card appearing, or a monitor with speakers being switched on, is not
  about us, and re-opening the mixer for it would cut whatever was being said
  mid-word.
- **Moving the sound is `sound.reopen_audio()`** - `pygame.mixer.quit()` then
  `init()` on the device that is default now, the channel count, the
  reservation and the four dedicated channels re-made by `initialize_sound()`,
  the background loop started again, and the format read back off the live
  mixer so re-opening cannot quietly resample every voice from now on. It runs
  on the watcher's thread on purpose: closing a device that has been physically
  removed is Windows' work, not something to do on the GUI thread. Anything
  holding a pygame Sound built on the old mixer can hear about it through
  `add_reopen_listener`.
- **OpenAL is opened the same way and gets stuck the same way**, so 3D
  positioning is given up too (`spatial_audio.reopen()`): the context, its
  sources and its buffers all belong to the old device, and `_init()` opens the
  current one for the next sound. The decoded-PCM cache survives - it is bytes
  from files.
- **The race is with speech.** Re-opening is a moment with no mixer at all, and
  every playback path in `stereo_speech.py` used to answer that moment by
  opening one of its OWN - one of them mono, at eSpeak's sample rate - and
  whichever spoke first decided what the whole program sounded like from then
  on. They all go through `_ensure_mixer()` now, which asks Titan's own
  initialiser first.
- **The watch starts before the mixer**, at the top of `initialize_sound()`: a
  Titan started with every playback device unplugged cannot open one at all,
  and the watch is then the only thing that will notice the headphones
  arriving. `gui.py` stops it before it quits the mixer, because that path ends
  in `os._exit()` and runs no atexit handler.
- Windows only (PulseAudio and CoreAudio both move a running stream
  themselves). `pycaw.callbacks` is imported by nothing else, so it is in
  `compiletorelease.py`'s hidden imports and in `Titan.spec`.
- Tests: `tests/test_audio_device_switch.py` (run it directly; 33 tests, and
  none of them plays a sound). Live-verified by really moving the default
  endpoint with `IPolicyConfig` and putting it back: noticed in ~1.0 s, both
  ways.

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
- **Titan Mail: three ways to read one message, and Escape leaves all three**
  (`src/network/mail_gui.py`). The reading list (rows, links, details,
  source), the **page view** (the HTML as the page it was written as) and the
  **plain text** (`MailTextFrame`: the whole message in one read-only
  `wx.TextCtrl`, so the reader's own cursor, say-all, find and Ctrl+C all
  work on it). Ctrl+W the list, Ctrl+T the text, Ctrl+P the page, and Ctrl+T
  on a message in the mailbox opens it as text straight away.
  - **In the page view, Escape did nothing and only Alt+F4 closed the
    window.** A WebView2 keeps every keystroke that happens inside its
    document: the frame's `EVT_CHAR_HOOK` never sees it and a menu
    accelerator never fires. So the document - which is Titan's own, built by
    `_sealed_document` - carries a small script that hands those keys back
    through `titan:key/<nonce>/<name>`, vetoed and acted on in
    `EVT_WEBVIEW_NAVIGATING`. Same trick as the HTML settings interface, for
    the same reason: it works on every WebView backend, with no bridge and no
    local server.
  - **A mail body is markup written by a stranger**, so allowing one script
    at all is done carefully. The policy names a per-window **nonce**
    (`script-src 'nonce-...'`), which only Titan's script carries; the URL
    carries the same nonce and `hmac.compare_digest` checks it, so a message
    cannot press Titan's keys (open a composer, hand itself to the real
    browser where its tracking pixels WOULD load, close the window under the
    reader); `scrub_message_html` takes the message's own `<script>`,
    `<base>` and `<meta>` policy/refresh out before it is put in the
    document; and a link is opened only when it is `http`, `https` or
    `mailto` - `javascript:`, `file:` and `data:` are ways of running
    something on this machine, and a confirmation dialog does not make them
    safe.
  - Tests: `tests/test_mail_reading.py` (16) and `tests/test_mail_window.py`
    (9). Neither shows a window, raises a dialog or speaks.
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

### Cerberus and Blackwall: the ban has to be true in the kernel

`titan-net server/cerberus.py` counts (failures per IP, distinct usernames,
IPs per account, IPs per /24) and `dangerous_cerberus.py` enforces. A threat
report showed both halves failing in ways a ban list cannot see: addresses
"already on the ban list" whose attacks carried on, and accounts locked over
and over by an attacker nothing was counting any more.

- **An SSH brute force was never blocked.** `FirewallManager` only ever
  blocked ports 8000 and 8001, while `auth_log_monitor.py` feeds it the
  machine's OWN SSH failures - so an address banned for hammering `root` over
  SSH was blocked on two ports it had never touched. Worse, a blanket
  `--dport 22 -j ACCEPT` sat at the top of INPUT, so a port-22 DROP appended
  below it would never have been reached anyway. Rules now live in a
  dedicated **`CERBERUS` chain that INPUT enters as its first rule**, above
  that ACCEPT; `record_failed_login(..., source='ssh')` and the honeypot mark
  an address as an SSH offender, and its ban (and every permaban) covers
  **every port**. Three guards keep the operator in: a whitelisted address is
  never touched, a private/loopback one is never blocked past the Titan-Net
  ports, and an address with a **live logged-in SSH session** (read from
  `who`) never has port 22 dropped.
- **A ban was believed rather than checked.** `block_ip` returned early on
  its own in-memory set, so a rule flushed by a firewall reload, a reboot or
  another tool was gone and nothing noticed. Every rule is now asked of the
  kernel (`iptables -C`) before it is added - which also ends the duplicate
  rules that once accumulated 144 copies of the SSH ACCEPT - `verify_ban()`
  repairs one, and a **reconciliation thread** walks every ban every five
  minutes. Traffic from a banned address is itself a signal
  (`note_banned_activity`): re-verify the block, and permaban an address that
  keeps talking through one.
- **`ban_ip()` reached nothing.** It added two set memberships, so a
  moderator's ban and - far worse - the risk engine's own escalation of the
  highest-scoring attacker on the dashboard never touched the firewall or the
  ban database, and were forgotten at the next restart. It goes through
  `_set_ip_threat` now, and the risk engine **re-escalates** at every doubling
  of a score instead of once, permanently past three times the threshold (an
  address had reached 261 against a threshold of 60 with nothing further
  happening to it).
- **A locked account hid the attacker.** The protective lock is rejected
  before `record_failed_login` is reached, so whoever tripped it became
  invisible to every per-IP detector - "persistently attempting to bypass
  account lockouts", seen from the outside. `record_locked_account_attempt()`
  counts those attempts and bans, an IP that drives **two accounts** into
  lockout is banned, and a reserved name is **never locked at all** (there is
  no owner to protect, and locking `root` only bought the attacker
  invisibility).
- **A default-account sweep is certain sooner than a count.** Two DIFFERENT
  system accounts from one address (`ubuntu` then `debian`) is a list being
  walked - nobody mistypes their way between them - so it bans at two, and
  names a real user could plausibly have chosen (`user`, `guest`, `support`)
  count only once that address has already asked for a certain one.
- **Blackwall** (`blackwall.py`) is the layer above all that, named for
  NetWatch's Blackwall in Cyberpunk 2077 - which is not a firewall but an AI
  wearing ICE, whose job is to recognise what is on the other side. Cerberus
  counts what an attacker can stay under; Blackwall recognises **behaviour**:
  a fingerprint (which accounts, in what order, at what rhythm, against which
  service), a **campaign** when several addresses share one fingerprint (they
  are banned as one, however quiet each was alone), a **memory** of past
  campaigns in `database/blackwall_memory.json` so a returning script is
  refused on its third packet rather than its fortieth, and a **posture**
  that pulls Cerberus' own thresholds in while an attack is live and gives
  them back in full when it stops.
  - **It answers the attacker, in text.** There is no audio anywhere: a
    Titan-Net client gets a `blackwall` message, and somebody at a terminal
    gets plain 7-bit ASCII as the SSH banner the tar pit
    (`hackback.py`) drips at them, or as the honeypot's parting words
    (`honeypot.py`, said at the END of the session so the trap keeps working
    while they are in it). The tone escalates over four stages and it is
    **only ever said to a source that is provably attacking** - a user who got
    their own password wrong is never spoken to.
  - **It writes the lines itself.** The sentences in `VOICE` are the floor,
    not the voice: with a model available Blackwall composes what it says
    about *this* actor, following on from what it already told them - "I see
    your four attempts against root, ubuntu, debian, and admin. Your activity
    is being logged. Stop." Three things make that safe to ship. Nothing is
    generated **on the attack path** (a login attempt must not wait on a
    provider, and an attacker able to make the server call an API once per
    attempt has found a way to spend its money): lines are written ahead of
    time on Blackwall's own thread, capped per hour, with the written ones
    standing in until one arrives. Every line is **checked** before it is said
    (`_sanitise`) - plain 7-bit ASCII, one paragraph, 40 to 320 characters, no
    link, path, markup, model-refusal or threat beyond this server. And it may
    only claim what has **actually happened** (`_is_true`): the first live run
    announced "your access is now terminated, this address is permanently
    blocked" as a *second warning* to somebody who was not blocked at all, so
    a line asserting a block before there is one is thrown away.

  - **Everything it says is written down** (`_record_utterance`): into the
    intrusion log as `BLACKWALL_SPOKE`, into `logs/blackwall_transcript.log`,
    and back into both AI prompts - the Cerberus analyst is told what the wall
    said, and Blackwall's own telemetry carries how often each actor was
    warned, because an actor who was told to stop and carried on is a
    different actor from one who was never addressed.
  - **The model half decides and acts, inside guardrails it cannot argue
    past**: only addresses that appear in Titan-Net's own telemetry (an
    invented one is discarded and counted), never a whitelisted address, a
    confidence floor for a ban and a higher one for a permaban, at most twenty
    actions per deliberation, and it may lift **only a ban Blackwall itself
    imposed** - never a moderator's. `BLACKWALL_AUTONOMOUS=0` makes it
    advisory. It uses the Cerberus analyst's **existing** Gemini key
    (`BLACKWALL_KEY` falls back to `CERBERUS_AI_KEY`), and everything above
    the model layer runs with no key and no network at all.
  - Moderator access: `blackwall_deliberate` over WebSocket, and
    `blackwall` inside `cerberus_status`.
- **A ban that says nothing had nobody to say it to.** A threat report read
  "two coordinated campaigns, seven addresses, all recognised and locked down -
  the Blackwall transcript is empty, so the actors were not addressed
  directly". Blackwall had been doing its job in total silence, for two
  reasons that were both structural rather than accidental:
  - **Every attacker was on SSH, and Blackwall's channels went somewhere
    else.** It could speak into a Titan-Net client (an SSH brute-forcer has
    none), the honeypot (2222) and the tar pit (2223) - and they were all
    attacking the real sshd on 22, where a ban is a `DROP`, which is silence
    by construction. So a banned SSH offender's port 22 is now **answered
    rather than dropped**: `FirewallManager.open_answer_channel()` puts a
    `nat PREROUTING REDIRECT --to-ports 2223` in front of them, so their next
    connection lands in the tar pit - Blackwall's one channel to somebody
    sitting at a terminal - and wastes their time while it talks. The ban is
    untouched: the blanket `DROP` stays exactly where it was, and the ACCEPT
    that lets the redirected packet reach the tar pit is inserted at the
    **top** of the `CERBERUS` chain, because appended below that address's own
    DROP it would never be reached. Three refusals: a whitelisted or private
    address, an address holding a **live SSH session** (that is the operator,
    and sending their next login into a tar pit is how somebody loses their
    own server), and a host with **no nat table** - there the ACCEPT would be
    a hole punched through the ban for a channel that does not exist, so the
    ban simply stays silent, which is what it was before. The channel is
    verified with the ban (`verify_ban`), restored with it (`restore_bans`,
    for every all-ports ban - those are exactly the ones that are silent on
    the service being attacked) and removed with it (`unblock_ip`).
    `BLACKWALL_ANSWER_SSH=0` turns it off.
  - **Blackwall only ever spoke about its OWN bans, and almost no ban is
    Blackwall's.** Cerberus is the counter, and counting is what catches a
    brute force, so the bans in that report were all Cerberus'.
    `CerberusProtocol.on_ban` now fires on every LOCKDOWN+ ban and
    `Blackwall.note_ban()` answers it.
  - **What it wants to say is now separate from having a way to say it.**
    `hold()` composes the line at the moment the decision is made and parks
    it against the address; the next channel that reaches that address -
    tar pit, honeypot, Titan-Net client - delivers it, before whatever that
    channel would have said on its own. The transcript still records **only
    what was delivered**, with the channel: something Blackwall merely wanted
    to say is not something it said. `status()["unsaid"]` is how many lines
    are waiting, which growing without bound is the dashboard's way of saying
    the answering channel is reaching nobody. Holding is **debounced** (one
    escalation through ALERT -> LOCKDOWN -> CERBERUS is three bans and one
    piece of news), and somebody who arrives through the answering channel is
    spoken to at **stage 3** - they are already blocked, and stage 0 would be
    talking to them as though nothing had happened.
- **Cerberus is a character too, and says what it did in its own words.**
  Everything it decided used to be announced with one fixed sentence about
  intrusion detection, identical for a brute force, a lockout evasion and a
  lockdown. `persona.py` holds both voices and the rules they share
  (`sanitise_line` - plain 7-bit ASCII, one paragraph, 40-320 characters, no
  link, path, markup, model-refusal or threat beyond this server - and the one
  place Gemini is called). They are deliberately **different characters**,
  because an operator reading a log should know instantly which layer is
  talking: Cerberus is the gate, old and procedural and impersonal; Blackwall
  is what stands in front of it, personal and cold and specific about what
  you did.
  - `CerberusVoice` has three registers and each one is a channel that really
    delivers - `shut_out`, `lockout_evasion`, `lockdown`. A fourth for the
    honeypot was written and taken out again: the honeypot speaks at the END
    of a session so the trap keeps working, and a line nothing delivers is
    the bug this whole change is about, written down twice.
  - Its words go into `reason`, because that is the field the client actually
    reads aloud; the machine-readable cause moves to `cause`, where the logs
    and the dashboard still have it. Saying it into a key nothing renders
    would be the same mistake as banning in silence.
  - Never generated on the calling thread (a websocket being closed is the
    attack path): a pool per register is filled on a worker of the voice's
    own, capped per hour, and the written floor stands in until one arrives.
    Same key as the analyst; `CERBERUS_VOICE_AI=0` turns the model half off.
  - Everything Cerberus says is written down (`say()` / `said()`), into the
    intrusion log as `CERBERUS_SPOKE` and into `cerberus_status`.
- **The analyst reports in the first person, because it is not describing the
  system - it IS the system.** The old report read "Automated defenses have
  successfully identified these campaigns": a description of a server written
  by nobody, about a third party, when the thing writing it had made every
  decision in it. `CerberusAI.PERSONA` now has it say I, say what it did and
  what it merely suspects, be specific (an address, an account, a count), and
  say plainly when it does not know - which is the part an operator cannot get
  from the passive voice. It is handed **both** transcripts (`MY_OWN_WORDS`
  and `BLACKWALL_TRANSCRIPT`) and told that an EMPTY one is a fault to report,
  not good behaviour: an attack nobody was told about means a channel was
  missing. New JSON keys are all optional so the existing client renders
  unchanged - `verdict` (one sentence, for reading aloud), `confidence`,
  `unknowns` - and `verdict` falls back to the summary's first sentence.
- **Starting again from nothing**: `cerberus_reset.py` (bans, logs, Blackwall
  memory, and with `--firewall` the kernel rules), which never touches
  `cerberus_whitelist.txt` or `titannet.db`; `remote_cerberus_reset.py` runs
  it on production through `update.py`'s own connection, service stopped.
- Tests (run them directly): `test_cerberus_hardening.py` (30),
  `test_cerberus_enforcement.py` (32, against a fake iptables so they need no
  root and can flush the kernel mid-test, and a fake nat table for the
  answering channel), `test_blackwall.py` (85, with the
  model replaced by a fixed answer - the only way to test that a wrong answer
  is refused: an invented address, a low-confidence verdict, a line that lies
  about a block, a request made while an attacker is waiting).


### The Titan-Net website: everything the server can do, in a browser

`titan-net server/web/` is the whole of Titan-Net without Titan. Every
WebSocket message type the server answers and every HTTP route it serves is
reachable from it — chat and rooms, private messages, voice and push to
talk, the forum, groups, Titan Mail, the repository (browsing **and**
uploading), extensions, the Feedback Hub, interactive games (playing,
speaking into, and writing one), the server's own remote-UI services, the
account (recovery email, blocked people, your own sounds, connected
services, your page elsewhere) and the whole moderation panel including the
Cerberus and Blackwall dashboard.

- **It is accessible because it is native.** A dialog is `<dialog>` (the
  browser owns the focus trap, Escape and the inert background), a tab bar
  is a real `role="tablist"` with arrow keys and one Tab stop, a menu is
  `<details>`/`<summary>` (the platform says "collapsed"/"expanded" itself,
  so no word is written into the label), a progress bar is `<progress>`, a
  sound is `<audio controls>`. `src/…`-style hand-rolled widgets are the
  thing this deliberately does not have.
  - `js/ui.js` is the shared kit: dialogs that give the focus **back** to
    whatever opened them (the part the browser does not do), a tablist, two
    live regions (polite for updates, assertive for errors), per-field
    errors wired through `aria-describedby`, and `focusHeading` for the
    navigations that have no page load behind them.
  - Colour never carries meaning alone: a selected tab is reversed AND
    bold AND underlined, `aria-current="page"` marks the nav entry, and
    `@media (forced-colors: active)` keeps all of it when the palette is
    replaced.
  - CSS generated content is read out by screen readers, so a separator is
    **drawn** (a border) rather than written (a guillemet in `::before`).
- **One socket per tab, not per page.** The server only knows who you are
  inside a WebSocket session, so every page needs its own login.
  `js/session.js` holds the credentials for the tab's lifetime and hands
  every page the same connected socket — before this, the SECOND page a
  user opened found the one-shot credential already consumed and bounced
  them back to the login form. It also re-logs in after a dropped
  connection, or every request after a hiccup answers "Not authenticated".
- **The navigation is one list** (`js/app.js`), built at run time, with the
  moderation entry shown only to staff. Fifteen pages each carrying their
  own copy is how a page ends up missing an entry.
- **A role decides what is OFFERED; the server decides what is allowed.**
  Every gated call is checked again server-side against the signed token,
  so a user who edits their own storage gains a menu entry that answers
  "permission denied".
- **Both languages, always.** `js/i18n.js` holds English and Polish; a key
  that is missing does not fail, it renders the key name to the user, so
  the sweep below checks every key a page asks for.
- Checks, run from `titan-net server/web/`: a static accessibility sweep
  (every control named, no heading skipped, no dangling `aria-*` reference,
  no `role="button"` on a div), a translation-key sweep (every key used
  exists in both languages), and a dependency sweep (every page loads the
  modules its scripts use).

### Interactive games: the server is what remembers

A game on Titan-Net is narrated. The creator writes the rules, the server
takes one turn per player message against Gemini
(`titan-net server/gemini_game_worker.py`), and what the model does reaches
the players as messages their client already knows: `game_ai_text`,
`game_ai_audio`, `game_menu`, `game_play_sound`, `game_turn_changed`. The
clients are `src/network/interactive_games.py` +
`interactive_game_session.py` (desktop) and `titan-net server/web/games.html`
(web).

- **A turn is one ordinary request, not a websocket.** The Live API is a
  VOICE api, and measured on this server's own key that is all it is:
  every one of its six bidi models refuses `response_modalities=["TEXT"]`
  with 1007, and the persistent 'live' models the candidate list still
  hopes for are not on the key at all. So a session always landed on the
  native-audio class, which composes the SPEECH before it parts with the
  words and closes the socket after every turn - 20 to 30 seconds a turn,
  several hundred relayed PCM messages inside one of them, and the
  creator's whole ruleset back up the wire on every reconnect. That last
  part is what "the server jams when I give it a big prompt with the
  rules" was.
  - `generateContent` takes TEXT, the same tool declarations and a system
    instruction of any size. Measured against a 117 KB (~42 000-token)
    prompt on `gemini-3.7-flash`: **1.34 s and 1.14 s** for two turns,
    the tool called correctly, and 36 829 tokens served out of Gemini's
    implicit cache the second time - a LONGER ruleset costs less per turn
    here, not more.
  - The Live path is kept whole for a key that does have a text-mode Live
    model, and `GAMES_TEXT_ENGINE=0` forces every session back onto it.
    `_pick_text_models()` asks the key what it has; an empty answer is the
    one honest reason to fall back.
  - What is given up is the model hearing a player mid-sentence. A spoken
    turn is gathered up and sent as one piece of audio when the player
    stops talking (`VOICE_GAP_S`), because nothing is streaming any more
    and there is no voice activity detection at the far end.
  - **Every call a step needs goes in ONE answer.** Asked one at a time,
    setting a board game up is thirty round trips with the whole ruleset
    read again each time - which is also what made a game hit its own
    token cap in two turns (measured: 200 475 for two turns of Czarny
    Stol). The prompt asks for them side by side, `MAX_TOOL_ROUNDS` is
    the ceiling for when it does not, and the **last round is asked with
    no tools at all** so a turn can never end with the table having heard
    nothing.
  - **What a turn is charged is what Google bills**: the prompt minus
    whatever came out of the cache, plus what the model wrote - not
    `total_token_count`, which counts the creator's rules once per
    REQUEST. `Database.GAME_DEFAULT_MAX_TOKENS` is 1 500 000 for the same
    reason; 200 000 was the figure from when a session was one connection.
- **The game opens itself.** A narrated game that says nothing until
  somebody types at it reads as a game that has not started, and to a
  player who cannot see the window an empty room is indistinguishable
  from a broken one. `_open_the_game()` takes the first turn
  `OPENING_DELAY_S` after the session is up - late enough that the host's
  client has said whether it can narrate, since that first line is what
  sets whose voice the game has - and stands down the moment anybody
  speaks first. It names **who is at the table**: without the roster the
  model invents a character for the player it was never introduced to
  (measured: a full sheet for a "Gracz" while the real player had none).

- **The prompt is the creator's, sealed as data.** `build_system_prompt`
  puts `rules_text` and every attached `.txt`/`.md`/`.json` inside
  `<GAME_RULES_DATA>`, with a folder becoming a labelled catalogue section
  (`objects/`, `classes/`, `quests/`) so the model looks an entity up
  instead of inventing it. `sanitize_creator_prompt` redacts the obvious
  "ignore all previous" attempts; the envelope is what actually stops an
  override. The API key is decrypted server-side and never enters the
  prompt.
  - **An attachment that cannot be decrypted is SKIPPED, never passed
    through.** Rule files are Fernet-encrypted at rest, and a worker
    without the key used to put the *ciphertext* into the system prompt -
    a wall of base64 where the rules should be, which costs tokens,
    teaches the model nothing, and looks like a working game right up
    until it ignores every rule it was given.
- **The RPG layer exists because the model cannot keep a number.** It will
  say "twelve arrows", let a player fire three, and say eleven two turns
  later. So arithmetic and possession are the server's:
  - **world variables** - `state_set` / `state_get`, dotted keys nest
  - **statistics** - `set_stat` / `change_stat` / `get_stats`. `change_stat`
    takes a delta, so damage, healing and spending are one atomic step; the
    server clamps (hit points and gold cannot go below zero, healing stops
    at the maximum) and answers with the value it ended on
  - **inventory** - `give_item` / `take_item` / `list_inventory`.
    Quantities stack, and `take_item` **refuses** when they have not got
    that many, so the model finds out instead of narrating a spent arrow
    nobody had
  - **equipment** - `equip_item` / `unequip_item` / `list_equipment`. A
    slot holds one thing; equipping into a full slot puts the old one back
    in the pack, and losing an item takes it off
  - **checks** - `skill_check` rolls, adds the statistic, compares with the
    difficulty and says whether it passed. The *server* decides, because a
    model asked to roll and judge in one breath decides first and rolls
    afterwards. Every check goes into the session log.
  - **A character the GAME plays gets a sheet too** - the computer
    opponent in a two-hander, a rival, a hireling. Pass its NAME as
    `target_username` and the server keeps its numbers exactly as a
    player's. It used to be refused (a name that was not a logged-in
    player resolved to nobody), so the model kept the opponent's hit
    points and position in its head, which is the one thing this layer
    exists to stop: Czarny Stol's "Komputer" was given four statistics,
    none was written down, and its position was narrated from memory from
    then on. A player's sheet lives on their `game_session_players` row;
    a character with nobody behind it lives in the session's own state
    under `__characters__`, through `Database.mutate_session_state` - the
    same read-modify-write inside the same writer lock, so the two cannot
    drift apart. At a table with exactly ONE player, a tool that names
    nobody means them.
  - **`set_turn_order` takes usernames.** It used to take numeric ids
    only - which the same system prompt tells the model it never has and
    must never invent - so the one tool a turn-based game cannot do
    without was the one it could not call. A name that is nobody at the
    table stays a name, and takes its turn like anybody else;
    `game_turn_changed` carries `active_character` beside
    `active_user_id`.
  - A sheet is one JSON object per player -
    `{"stats": {"hp": {"value": 9, "max": 12}}, "inventory": [...],
    "equipment": {...}}` - and every change is one read-modify-write inside
    the database writer lock (`Database.mutate_character_state`), so two
    changes in one turn cannot lose each other.
  - **The sheet is rendered as words, never as JSON.** `json.dumps` put
    braces, quotes and the word "value" into a line a screen reader then
    read character by character; both clients spell it out ("hp: 7 of 12",
    "arrow, 12", "hand: sword").
  - Every change broadcasts `game_state_changed` (which every client
    already refreshes on, so an older one keeps working) **and**
    `game_character_changed`, which says what actually moved.
- **A player's words reach the model prefixed `[username] `**, which is the
  only identifier it is ever given - it never sees numeric ids, and the
  tools that target somebody take `target_username` back. A hallucinated
  id degrades to the whole table rather than being dropped, because a menu
  nobody sees is a stuck game.
- **One AI turn is one line.** Gemini ships text a token at a time; the
  receive loop buffers to `turn_complete` and de-duplicates, so a player
  hears one sentence rather than thirty fragments. Audio streams through
  as it arrives.
- **A reconnect recaps the players' actions, not the model's replies.** A
  recorded model turn holds the words but not the function calls that went
  with them, and feeding that half back is what produced 1011 errors on
  the next message.
- **Asking for AUDIO is not the same as giving up the host's voice**, and
  it used to be treated as though it were. Titan asks Gemini for TEXT
  precisely so the host's own Titan TTS narrates the table; a key with no
  text-mode Live model fell back to AUDIO and the room was told the AI
  would speak in its own voice instead. Two things were wrong with that:
  - **The fallback was reached over models that were never asked.** The
    connect loop rotated to the next candidate only on `1008` / "not
    found" / "not supported for bidi" - and a native-audio model handed
    `response_modalities=["TEXT"]` refuses with a message about the
    MODALITY, which matches none of the three. So the loop gave up at the
    first candidate and never reached `gemini-2.0-flash-live-001`, the
    persistent 'live' model further down the list that would have taken
    TEXT happily. It now rotates on anything but an unusable key
    (`_connect_error_is_fatal`), which is the only failure the next model
    cannot fix.
  - **The fallback keeps the host anyway.** `output_audio_transcription`
    is on the config, so the model captions its own speech: the line
    still arrives as text and the host narrates it exactly as on the TEXT
    path. What is really lost is the head start - the model composes the
    speech before it answers - which is what the room is now told. The
    model's own PCM is dropped **while a host is narrating**
    (`_host_narrating()`, asked per turn because audio streams before
    `turn_complete`); relaying both is the same sentence in two voices a
    beat apart. A table with no host voice still hears Gemini, and a host
    who leaves mid-game gives Gemini its voice back on the next turn.
- **The rules are read once per CONNECTION, not once per turn.** They are
  the `system_instruction`, so the model holds them for every turn on a
  persistent 'live' model. A reconnect re-sends them - and the
  native-audio class closes the socket after every turn, so on that class
  a long ruleset is paid for once a turn, which is the other reason
  reaching a persistent model matters. The prompt's size is logged at
  session start so this is measured rather than guessed. The game's
  *state* is never in the model's context at all: statistics, inventory,
  equipment and world variables live on the server, which is why a
  reconnect loses wording and never loses the game.
- Tests (run them directly; no API key, no network, no audio device):
  `titan-net server/test_interactive_games.py` (164) and
  `test_game_text_engine.py` (38). The model is a scripted stand-in
  speaking the SDK's own shapes, which is the only way to test the answers
  a real model gets *wrong* - an invented user id, a menu aimed at nobody,
  an arrow that was never carried, a model this key has not got, a turn
  that is nothing but the model thinking out loud, two players typing at
  the same moment, a conversation trimmed across a tool call.
  Live-verified by playing Czarny Stol end to end (the real worker, the
  real tools, a real key): the board persisted, both characters kept their
  own statistics and inventory, the turn rotated between a player and a
  character the game plays, and a turn took 8 s.

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

### Titan Shell: Windows XP as the system interface

`src/shell/` is what the existing **"Modify system interface"** setting
(`environment.windows_e_hook`) now opens onto. That mode always owned the
Windows key; with **Settings -> Titan shell -> "Replace the desktop, taskbar
and Start menu"** on as well, Titan also puts up its own **desktop, taskbar,
notification area and Start menu**, shaped like Windows XP (Luna Blue), and
hides Explorer's bar while it is there. Off by default; both switches must
agree (`shell_manager.desktop_shell_enabled()`).

**The look is data, not drawing code** (`luna.py`). The palette holds the
*measured* Luna gradient stops - the taskbar's five bands
(`#3888e9 0.0 ... #1941a5 1.0`), the task-button and notification-area
gradients, the Start capsule - so the bar matches a screenshot band for band
rather than being blue-ish. Any skin overrides any of it through a `[Shell]`
section in its `skin.ini` (`skins/windows_xp/skin.ini` is the reference and
the full list); `style = classic` swaps the base for the grey 3D shell,
which is what `windows95` and `retro` now ask for. A skin change repaints a
running shell (`skin_manager.load_skin` -> `refresh_shell`).

**It never speaks.** The shell replaces the system interface, so a screen
reader is already announcing every focus change in it - a Titan announcement
on top would say each button twice. Accessibility is instead *native*: every
painted control is a real focusable `wx.Window` answering MSAA with a name, a
role and a state (`a11y.ShellAccessible` + `AccessibleMixin`, `controls.py`),
raising its own focus event. The only sound is Titan's non-speech focus cue,
panned to where the control is, and it has a setting.

**Mouse and keyboard are equals.** The keyboard model is XP's own: **Tab and
Shift+Tab step between the bar's groups** - Start, quick launch, the window
buttons, the notification area (the clock belongs to it) - and the **arrows
move inside** whichever group has the focus, with Home/End for its ends and
the group remembering where it was left. Shift+F10 opens a window's menu
(Restore / Minimise / Maximise / Close), **Escape gives the keyboard back to
the window the user came from** (remembered when the bar was activated, not a
jump onto the desktop), F5 rebuilds; the mouse gets XP's tooltips, hover
states, middle-click-to-close, the taskbar's own menu (Cascade, Tile, Show the
Desktop, Task Manager, Properties) and the Start button's.

**None of that works until the bar is the foreground window.** `SetFocus`
only moves the focus *within* the window Windows already considers active, so
a bar put up with `ShowWithoutActivating` swallowed every key: Tab did
nothing, the window buttons and the notification area could not be reached at
all, and it read as a taskbar with no windows on it. `win_shell.take_foreground()`
(attach to the foreground thread's input queue, then `SetForegroundWindow`) is
what every way into the bar and the desktop - Windows+B, Windows+T, Windows+D,
Windows+M, `focus_tray()`, `focus_icons()` - now goes through first.

- `win_shell.py` - the Windows side: the **appbar** (so a maximised window
  stops above the bar), the **shell hook** (`RegisterShellHookWindow`, so
  window changes arrive as messages instead of being polled for), the window
  list/drive calls, desktop folders, wallpaper, file icons, the Recycle Bin,
  `CascadeWindows`/`TileWindows`. Two traps live here, both found by
  measurement: **the appbar answers in real pixels** while Titan runs
  DPI-unaware, so a 30 px bar reserved 152 px until the rectangle was scaled
  (`physical_screen_size()`, `dpi_scale()`); and hiding Explorer's taskbar
  with `ShowWindow` leaves its reservation standing, so
  `set_explorer_taskbar_reserved()` puts it into auto-hide (`ABM_SETSTATE`)
  and Explorer's bar must go before ours docks.
- `desktop.py` - a real `SysListView32` in icon mode (`wx.LC_ICON`), which is
  what the Windows desktop is: rubber-band selection, first-letter jumping
  and screen-reader support come from the control. Titan adds the shell
  behaviour - real Windows icons (`SHGetFileInfo`), Enter/F2/Delete/F5,
  Alt+Enter for the properties, both context menus, dragging icons to
  remembered positions, the wallpaper drawn by the list itself
  (`LVM_SETBKIMAGE`, transparent labels). It is a **grid, not a list**:
  `LVS_ALIGN_LEFT` fills a column from the top of the screen downwards before
  starting the next one, `LVS_EX_SNAPTOGRID` and a 76x88 cell
  (`LVM_SETICONSPACING`) keep every icon on the grid however it was dragged,
  and anything the user has never moved is arranged by the control. With
  wxWidgets' default `LC_ALIGN_TOP` the icons ran across the top of the
  screen in one line instead.
- `taskbar.py` - Start button, window buttons (reused across refreshes so the
  focus survives), notification area, clock whose accessible name carries the
  date. Tray buttons are reused the same way, keyed on UI Automation's
  runtime id rather than on the name - a tray icon is renamed every few
  seconds (the battery percentage, the volume), and rebuilding the button to
  say so would throw the keyboard out of the notification area each time. The
  tray is re-read on a slow tick of its own (~30 s, and F5), because reading
  it is a walk of Windows' accessibility tree and costs about 60 ms.
- **The notification area is read from the Windows the user actually has**
  (`src/system/tray_icons.py`, which `system_tray_list.py` now re-exports).
  Windows 11 has no `ToolbarWindow32` under `TrayNotifyWnd` at all - the
  taskbar is XAML - so the twenty-year-old `TB_*` route found nothing and the
  tray came up empty. It now reads **UI Automation** over `Shell_TrayWnd`,
  where every icon is a `SystemTray.*Button` named with the text the hover tip
  shows, and matches on that class *prefix* so a renamed one appears rather
  than vanishing. Hidden icons live in a XAML flyout that is only built when
  it is shown: "Show hidden icons" (recognised by **where it is** - first in
  the area, before the applications' own `NotifyItemIcon` buttons - since
  nothing else tells it apart in any language) opens it, reads it and puts
  those icons into the bar beside the visible ones, and a hidden icon whose
  flyout has since closed re-opens it to find its element again instead of
  clicking a stale rectangle. Pressing goes through UIA `Invoke` first,
  because with Explorer's bar auto-hidden the icons are off the screen and a
  synthesised click would land on whatever is underneath. The legacy toolbar
  is kept for Windows 10 and earlier and is **fixed**: its text and rectangles
  have to be read out of Explorer's own address space (`VirtualAllocEx` +
  `ReadProcessMemory`), which is why every icon used to come back called
  "System Icon 1" and why clicking any of them clicked the first.
- `start_menu.py` - `XPStartMenu(ClassicStartMenu)`: the XP two-pane face on
  the existing menu, inheriting everything that finds programs, runs a Titan
  app or game, opens Run or asks about shutting down. "All Programs" drills
  down **inside** the left column (Backspace/Escape step out) instead of
  cascading flyouts a keyboard cannot follow.
- Windows' own shortcuts drive it (`tce_system.py`): Windows or **Ctrl+Esc**
  = Start menu, Win+D = show desktop, Win+M = minimise all, Win+B =
  notification area, Win+T = the window buttons, Win+E, Win+R, Win+F,
  Win+Pause, and Win+L still locks.
  - **Control is asked of Windows; the Windows key can only be
    remembered** - and the two are opposites for one measured reason: a
    key SUPPRESSED in a low-level hook never reaches the system, so
    `GetAsyncKeyState` reports the Windows key up the whole time the user
    holds it, while Control (which the hook lets through) it answers about
    correctly. Asking Windows about the held Windows key makes every
    Windows+<key> shortcut pass through and do nothing.
    `keyboard.is_pressed('ctrl')` was the bug on the other side: it
    answers out of a table the library fills from the events its own hook
    saw, and events DO go missing - the lock screen (Win+L is one of these
    shortcuts), Ctrl+Alt+Del and a UAC prompt each take the key UP on
    their own desktop, where no hook of Titan's runs. One Control left
    "held" that way made `_win_passthrough` true for every Windows key
    press from then on: the Windows key opened WINDOWS' Start menu and not
    one Titan shortcut fired again until Titan was restarted. So Control
    goes through `_key_physically_down(VK_CONTROL)`, and the tracked
    Windows key heals itself by time instead - a press nothing has
    refreshed for `_WIN_HELD_STALE` is a key up that never arrived (a flag
    stuck DOWN turns an ordinary "d" into Windows+D mid-sentence), and a
    press more than `_WIN_REPEAT_GAP` after the last one is a new press
    rather than auto-repeat, which is what re-reads Control after a lost
    key up.
  - **The shell never holds a modifier the user has let go of**, and two
    mechanisms of Titan's own said otherwise. `keyboard.add_hotkey(...,
    suppress=True)` - one suppressed HOTKEY, `ctrl+esc` - switches on the
    library's modifier state machine **for every key event in the
    session**: it holds a modifier back and replays it as a synthetic
    press once it knows what followed, keyed on scan codes that outlive
    the events that set them, so Control key downs were swallowed and
    injected by hand and a Control left in its `suppressed` state made the
    shell press Control on its own. `_add_combination` is now a
    suppressing **key** hook on `esc` that asks Windows whether Control is
    physically down (`_make_combination_hook`), which leaves that
    machinery switched off entirely - measured: with no suppressed hotkey
    `blocking_hotkeys` stays empty and nothing touches a modifier. The
    other is **`AttachThreadInput`**: `take_foreground()` merges this
    thread's input queue with another program's, and the queue is where
    the per-thread key state `wxKeyEvent::ShiftDown()` answers from, so a
    Shift held across that stays latched there - Tab moved backwards for
    ever, F10 opened a context menu, and an Escape that arrived as
    Shift+Escape silently stopped closing windows (`modifiers ==
    MOD_NONE`). `src/system/key_state.py` asks `GetAsyncKeyState` instead:
    `shift_down(event)` believes the event only when the hardware agrees,
    and `modifiers(event)` drops a phantom Shift while leaving Control and
    Alt exactly as reported. Used by every shell key handler, by the mail
    windows and by `gui.py`'s global F4 (which read the same stale answer
    out of `keyboard.is_pressed`).
- **Action API**: a built-in `shell` provider (`shell_actions.py`,
  `actions/builtin.py`) - `status`, `start`/`stop`, `open_start_menu`,
  `show_desktop`, `list_windows`, `activate_window` / `minimize_window` /
  `close_window`, `arrange_windows`, `list_desktop`, `open_desktop_item`,
  `list_tray`, `activate_tray_icon`, `get_time`, `list_settings`,
  `set_setting`. The window and desktop ones answer with the shell switched
  off too (they read Windows, not the taskbar), an ambiguous title *asks*
  rather than guessing, and nothing here needs AI.
- **Read out of ReactOS' Explorer, control for control.** The parts added
  after the first round are each a rebuild of a named piece of
  `base/shell/explorer` or of the shell32/msgina dialog it calls:
  - `quick_launch.py` - `CQuickLaunchBand`: the real
    `%APPDATA%/Microsoft/Internet Explorer/Quick Launch` folder, each
    shortcut with the icon `SHGetFileInfo` gives it. The two Windows puts
    there itself (Show Desktop, Window Switcher) are left out, matched on
    the *file* name because the displayed one is translated - Titan has
    both already.
  - `run_dialog.py` - shell32's `RunFileDlg` (`IDD_RUN`): the paragraph, the
    Open combo, OK / Cancel / Browse. The history is Explorer's own
    `HKCU\...\Explorer\RunMRU`, so it is shared with Windows' Run box, and
    what is typed goes through `ShellExecuteW` (`os.startfile` cannot run a
    bare `notepad`, a command with arguments, or anything resolved through
    App Paths). It replaced `rundll32 shell32.dll,#61`, which put up
    Explorer's window - unskinned, unannounceable, and the wrong window on a
    machine whose shell Titan is replacing.
  - `shutdown_dialog.py` - msgina's `IDD_SHUTDOWN`, which is what
    `ExitWindowsDialog` actually shows: one list, one description of the
    chosen entry, OK and Cancel. Every string is `IDS_SHUTDOWN_*` verbatim.
    Sleep and hibernate appear only where the machine will take them, read
    from `GetPwrCapabilities` **including its `AoAc` flag** - modern standby
    machines report S1/S2/S3 absent and `IsPwrSuspendAllowed` says no, so
    asking the old way hides Sleep on most laptops made this decade.
  - `taskbar_properties.py` - `trayprop.cpp`'s three pages (Taskbar / Start
    Menu / Notification Area), opened by the taskbar's own **Properties**.
    The rule applied throughout: a control is there only if it does
    something, so ReactOS' own two commented-out switches (group similar
    buttons, small icons) are absent rather than dead.
- **The bar goes on any of the four edges**, hides itself and can be locked
  (`taskbar_position` / `taskbar_auto_hide` / `taskbar_locked`, plus
  `taskbar_on_top`, `show_quick_launch`, `show_clock`,
  `show_desktop_button`, `start_menu_style`). Auto-hide uses ReactOS' own
  timings (2000 ms to go, 50 ms to come back, a 10 ms animation that creeps
  out and snaps in) and leaves a sliver behind; a bar standing on its side
  is not a horizontal one turned round - the window buttons stack and the
  notification area sits at the bottom of the column. **Show Desktop is the
  last thing on the bar**, inside the notification area, which is where
  `CTrayShowDesktopButton` is and where Shift+Tab from the desktop arrives.
- **The desktop is a grid, worked out rather than left to the control.**
  `CDefView::CreateList` gives the desktop view `LVS_ALIGNLEFT` +
  `LVS_AUTOARRANGE` + `LVS_EX_SNAPTOGRID`; wxWidgets translates neither
  auto-arrange nor anything else it was not given at construction, and the
  icons are read in *before* the desktop has the screen, when a column is a
  few pixels tall and holds one icon - which is what put them in a row along
  the top. `layout_grid()` places them column-first from the screen's own
  size and the system icon spacing, keeping whatever the user dragged
  somewhere and giving everything else the free slots.
- **Tab is a round trip.** From the desktop, Tab goes to Start and Shift+Tab
  to the notification area; off either end of the bar is the desktop again.
- **The notification area is read from the XAML island, not from
  `Shell_TrayWnd`.** On Windows 11 the taskbar's contents live in a
  `Windows.UI.Composition.DesktopWindowContentBridge` child window with a UI
  Automation tree **of its own**: walking down from `Shell_TrayWnd` reaches
  `TrayNotifyWnd` and `MSTaskSwWClass` and stops, which is why the tray came
  up empty even after it was moved to UIA. `_tray_roots()` asks the island
  first. Windows' own clock and Show Desktop button are then left out of
  Titan's strip while Titan draws its own (`is_clock`, matched on the class
  plus the time in the name because the name is translated;
  `is_show_desktop`, matched on its class) - otherwise the bar carried two
  of each. Icons show their real picture where Windows will part with one
  (`WM_GETICON`, then the window class'), which on Windows 11 is nowhere,
  since a notification icon's bitmap never leaves the process that
  registered it; the fallback is the first letter, never a character
  standing in for a picture.
- **Switching windows never pulls the keyboard onto the bar.**
  `wx.Frame.Raise()` calls `SetForegroundWindow` on Windows, and the bar
  called it from the appbar's `ABN_FULLSCREENAPP` notification - which
  Windows sends on ordinary Alt+Tabs - so switching windows kept dropping
  the user on the taskbar. The z-order is now set with `SetWindowPos` and
  `SWP_NOACTIVATE`; going behind everything gives up topmost first, since a
  topmost window sent to the bottom is still in front of everything that is
  not.
- **No character ever stands in for a picture or a word.** A list item's
  text *is* its accessible name, so an arrow after a folder's name was read
  out as the arrow: a Start-menu folder now says "<name>, submenu" in words
  (`start_menu.py`), and the classic menu's separators, which were thirteen
  box-drawing dashes, say "Separator" - what a screen reader says for a real
  menu separator.
- **Titan's own function keys are Titan's only while Titan is an
  application.** With the shell up Titan IS the desktop, so bare **F4 no
  longer opens Titan's window switcher** (`gui.shell_owns_the_keyboard`):
  there F4 is Windows' key - the file browser's address band - and
  switching windows is what the taskbar and Alt+Tab are for. Windows+W and
  Windows+F2 still open the switcher, and so does the taskbar's own menu.
  **F4 arrives by four routes and all four had to be asked**: `gui.py`'s
  `on_key_down`, both of Klango mode's key handlers (the wx one and the
  pygame one), and - the one that kept firing after the others were shut -
  a **global hotkey** registered through the keyboard library
  (`_global_f4_handler`), which fires whenever any TCE window is in the
  foreground and never goes through a key handler at all. The shell's
  desktop, taskbar, Start menu and browser are all TCE windows, so gating
  the key handlers did nothing for it.
- **The shell's windows are furniture, not applications.** The desktop, the
  bar and the Start menu are taken out of Alt+Tab and off every taskbar
  (`win_shell.hide_from_alt_tab`, `WS_EX_TOOLWINDOW` set on the window,
  because wx only offers the style on a frame that also draws a caption) -
  otherwise Titan's own shell is three more "programs" to tab past.
- **The bar lives in the background** (`taskbar_on_top` now defaults off).
  Not topmost is a *place in the z-order*, not a style bit: a window that
  was topmost and is merely told it is not stays where it was, so
  `send_to_background()` sends the bar to the bottom and puts the desktop
  back underneath it, all with `SWP_NOACTIVATE`. It comes forward to be
  used and goes back the moment it is deactivated. The appbar keeps the
  strip reserved either way, so nothing covers it.
- **A group of the bar announces itself, to the screen reader only.** Tab
  between the groups says "Start", "Dock", "Open windows", "System tray"
  through `accessibility.messages.announce_shell_group` - the same
  mechanism as a Titan window's virtual tab bar (Titan Access first, then
  `speak_sr_only`), so with no reader running nothing is said and the shell
  still never speaks through the platform TTS. The arrows inside a group
  say nothing extra.
- **The desktop list is called "Desktop"** and nothing longer: the list *is*
  the desktop, and "Desktop / Desktop icons" said the word twice.
- **The keyboard really lands on the icons.** `SetForegroundWindow` makes
  the frame active, but the `WM_ACTIVATE` behind it is processed *after* the
  call returns and wxWidgets answers it by focusing the frame - undoing the
  `SetFocus` just made on the list. Windows' focus was therefore on the
  frame and the icons could only be reached with object navigation. So
  `focus_icons()` sets it now **and** again once the activation has been
  through the queue, `focus_list()` sets it with Windows' own `SetFocus` on
  the list's HWND and gives an icon the focused state (a list view with no
  focused item reads as an empty container), and `EVT_ACTIVATE` does the
  same whenever the desktop becomes the active window - unless a rename is
  in progress, where the keyboard belongs to the edit box.
- **The desktop does what Explorer's does**: open, open file location
  (a shortcut resolves to its *target's* folder), cut / copy / paste
  (CF_HDROP plus the "Preferred DropEffect" format, without which a cut
  quietly behaves as a copy), create shortcut, rename, delete, and Windows'
  own property sheet - given the desktop as its owner window, or the sheet
  comes up behind a shell that has hidden Explorer's bar. **Alt+F4 on the
  desktop opens the Shut Down dialog**, as it does on Windows.
- **The Shut Down dialog has one entry that is Titan's**: "Turn off TCE"
  closes Titan and gives the desktop and the taskbar back to Windows,
  beside msgina's own log off / shut down / restart / sleep / hibernate.
  It is deliberately **not a second kind of exit** (`exit_titan` ->
  `titan_main_window()`): it hands the exit to whichever face of Titan is
  running - Klango mode's own `exit_program()`, or the main window's
  `Close()`, which is what the menu's Exit, the Invisible UI's Exit and the
  title bar go through - so the confirmation the user asked for
  (`shutdown_question`, Settings -> General -> "Confirm exit from Titan")
  still appears, cancelling it still cancels, and one teardown runs. The
  search skips the shell's own windows on purpose: they refuse to close, so
  closing one would put this dialog up again. Titan's shutdown now **stops
  the shell before its own goodbye sound** (`gui.py` and `klangomode.py`,
  `stop_shell(quiet=quick_start, wait=True)`, idempotent because
  `stop_system_hooks()` stops it too; only the way out waits for the
  clip - turning the shell off in the settings would otherwise sit
  there for its length), so logging out of the shell is heard first, the way Windows
  plays its logoff sound before it goes.
- **The Start menu is one ring of real controls** (`start_menu.py`): the
  user's name is a `UserButton` (a focusable, named control - a painted
  strip is nothing to a screen reader) that opens their own folder, then a
  **search box** over everything the menu can start (Titan applications and
  games, the **Titan IM modules**, the **macros**, the settings and the
  whole Windows Start Menu, indexed once per open, names that *start* with
  what was typed first), the two columns, and Lock / Log Off / Turn Off
  Computer.
- **The menu says what it is by being CALLED it.** Its window title is
  "Start menu", and a screen reader reads the name of a window it has just
  entered by itself - Titan Access from `context_presenter` (which already
  emits "<name>, window" for a newly entered window), NVDA from the
  foreground change. Titan saying it as well was a second copy of the
  title, and one that had to be protected from being cut off (a focus event
  makes a reader cancel what it is saying), which meant holding the
  keyboard back from the window the user had just opened. The title does
  the work; there is deliberately no "announce this window" helper in
  `accessibility.messages`.
- **The keyboard is handed over exactly once, and from the activation**
  (`_focus_pending` -> `_hand_over_focus`, `FOCUS_FALLBACK_MS` for when no
  activation arrives). Twice is what a reader says as the control twice,
  and there are two ways to get there: wxWidgets answers WM_ACTIVATE by
  focusing the FRAME, so a focus set before the window has finished
  becoming active is undone and then put back; and **inside the shell there
  is a second activation** - the bar is deactivated when the menu takes the
  foreground, answers that with `send_to_background()`, and re-shuffling
  the z-order bounces the activation back onto the menu. That is why the
  double focus happened in the shell and nowhere else. So: an activation
  that finds the keyboard already in the menu is ignored (`IsDescendant`),
  and `focus_now` never re-focuses what is already focused.
- **The left column is a tree, not a chain of submenus** (`MenuTree`). A
  flyout is a menu a keyboard cannot follow, and the word "submenu" written
  into an entry is a word the screen reader then reads out - a tree control
  has both solved: the arrows open and close a branch and the reader says
  "collapsed" / "expanded" from the control's own state, so nothing is put
  into the text. Branches fill themselves the first time they are opened
  (`_children_of`), because reading the Windows Start Menu, every add-on
  and every macro up front is most of a second the user would wait for.
  The branches are Applications, Games, **Titan IM** (the five services
  Titan brings itself - Telegram, Messenger, WhatsApp, Titan-Net,
  EltenLink, each opened through the main window's *own* flow so the menu
  never has a second opinion about who is logged in - and then the
  installed modules), **Macros** (read from the macro manager component
  itself, so the list and the shortcuts are its own), **Settings** - where
  Titan's own settings now live, with the Control Panel, the taskbar
  properties and the display settings, so "where do I change something"
  has one answer - **Windows apps** and All Programs.
- **UWP apps are in the menu and in the search** (`win_shell.installed_apps`,
  `launch_app_id`). `shell:AppsFolder` is what the Windows Start menu is
  made of and the only place a packaged app exists at all: there is no
  shortcut on disk to find, only an Application User Model ID, which is
  also the only way to start one (`explorer.exe shell:appsFolder\<id>`).
  The walk costs over a second, so it is cached for five minutes and read
  **on a background thread** when the menu opens (`prefetch`, which warms
  the search index too, with its own COM apartment) - the first keystroke
  in the search box must not be the one that waits for it.
- **A native control's name has to be given to MSAA, not to wx**
  (`a11y.name_control` / `NamedAccessible`). `SetName` on a `wx.ListCtrl`
  is wx's own name and never reaches a screen reader: a list view answers
  with its own IAccessible, whose name comes from window text these
  controls have none of. That is why the desktop list stayed unnamed
  however many times it was called "Desktop". `NamedAccessible` answers the
  name for the control itself and `wxACC_NOT_IMPLEMENTED` for everything
  else, so every item, state and position still comes from the native
  control. Measured through `AccessibleObjectFromWindow` afterwards: name
  "Pulpit", role 33 (list). Used for the desktop list, both Start-menu
  columns and the search field.
- **Search results are a list, not the tree**: results want columns (the
  name, and where it came from) and a tree cannot have them, so the two
  controls swap places in the same slot and `left_column()` is whichever
  is up - which is also what the focus ring walks. **The results read like Windows' own**: the list
  grows a second column, so a reader says "Notepad, Accessories" for a row,
  the count goes into the column heading (which is the list's accessible
  name), and `accessibility.messages.announce_search_results` says it to
  the screen reader 400 ms after the typing stops - the one control where
  what changed is not where the focus is. The window is called the **Start
  menu**, not "Titan Menu". Tab walks that ring and Shift+Tab comes back -
  handled in the frame's char hook, because both columns ask wx for
  `WANTS_CHARS` (that is what gives them first-letter jumping) and a
  control that wants the characters is given Tab as well. The number found
  goes into the column's *name*, not into speech. **Escape closes onto the
  Start button** - which is how the taskbar is asked for, bringing a hidden
  bar back out - and Escape there hands the keyboard back to the window the
  user came from.
- **Windows+D and Windows+M put the desktop up, not just the focus on it**
  (`DesktopFrame.bring_up`): shown if it was hidden, back at the bottom
  where a desktop belongs, re-read only when the folder's timestamp says
  something changed, and then focused with an icon selected so there is
  something for the reader to say.
- **The Windows shortcuts land where they say, with or without the shell's
  own windows.** `shell_manager.focus_desktop()` falls back to Windows' own
  desktop list view (`win_shell.windows_desktop_hwnd()`, `Progman` or a
  `WorkerW`), Windows+D minimises everything and follows the windows down,
  and Windows+B lands in the notification area.
- **The whole system interface is one settings category.** "Modify system
  interface" is the FIRST control of Settings -> Titan shell, not a checkbox
  under Environment, and the category is listed like any other: a switch
  kept inside a category that only appeared once the switch was ticked was
  a switch nobody could find, and the panel it was hidden behind was never
  actually hidden - `ShowCategory` only hides the panel it is showing, so a
  panel built for an unregistered category (the Titan shell one, and the
  Game controller one whenever no pad is plugged in) was drawn on top of
  every category the user really opened.  Both are hidden the moment they
  are built now, and everything below the switch is enabled and disabled
  with it (`_update_shell_controls`).  The setting itself is unchanged -
  still `environment/windows_e_hook` - so nothing that reads it moved.  The
  options are **grouped** into real `wx.StaticBox` groups - the system
  interface, the desktop, the taskbar, Sounds, and the shortcuts Titan takes
  over - because a static box is a grouping Windows itself knows about, so a
  screen reader says which group the keyboard has entered instead of the
  panel being twenty checkboxes to count through.
- **Starting the shell must not stop the machine** - measured, then fixed.
  `start_shell()` cost **4240 ms on the GUI thread**; it now costs **214
  ms**, with the desktop's icons, the notification area, the appbar and the
  user's startup programs all arriving afterwards. This matters more than
  ordinary startup time: with the appbar registered and the shell hook
  installed, every broadcast Windows sends to top-level windows goes
  through this process, so a GUI thread busy for a second is a second of a
  system that feels stuck, not merely a slow Titan. What was where:
  - `ABM_SETSTATE` (Explorer's bar into auto-hide) **2416 ms** and
    `ABM_NEW` (ours registered) **849 ms**. Neither is Titan's doing - a
    bare wx application with no shell at all stalls **2407 ms** while the
    first one happens, because Explorer moves the work area and tells every
    window in the session about it. They are Windows IPC touching no wx, so
    both now run on workers, chained through a `threading.Event` (ours must
    not claim the strip until Explorer's has given it up), and
    `set_explorer_taskbar_reserved()` asks `ABM_GETSTATE` first so a second
    start makes neither call. **Explorer's bar is put away last**, once the
    shell's own windows are up: while that transition is happening, any
    window this thread creates and any message it sends across the session
    waits for it - the same taskbar took 76 ms to build before the change
    and 2.6 seconds during it.
  - The desktop was **550 ms of shell calls** (a display name and a
    `SHGetFileInfo` icon per item, 64 of them). `DesktopFrame(defer=True)`
    reads them on a worker - with its own COM apartment, because
    `SHGetFileInfo` reaches into shell extensions - and only the `wx.Bitmap`
    conversion comes back to the GUI thread: 322 ms -> **31 ms**, the icons
    arriving about half a second later. Both the icons and the display names
    are then cached against the file's own timestamp, so a re-read (F5, a
    rename, the shell's `refresh` action) is 269 ms -> **33 ms**, and
    `file_type_name` is gone from the read entirely - it was another call
    per item and nothing on the desktop shows it (`item_type()` asks for it
    if anything ever wants it).
  - The notification area is UI Automation into Explorer's own windows, so
    it is read **after** the strip has changed hands, and an empty answer is
    treated as "not yet" and tried again - asked during the transition,
    Explorer answers nothing at all.
  - The user's **startup programs run on a worker** 1.5 s later, staggered:
    `ShellExecute` on a program that puts a window up takes seconds, and
    every one of them used to be seconds of a shell that had stopped
    answering Windows.
  - **The shell never `SendMessage`s another program**
    (`win_shell.send_message_timeout`, `SMTO_ABORTIFHUNG`): a window's icon
    is fetched with `WM_GETICON`, and a program that has hung would
    otherwise hold the bar - and therefore the machine - for as long as it
    is hung. A window that answers no icon is also not asked again for 30
    seconds rather than on every poll.
  - The **Start menu is built 2.5 s after startup** rather than on the first
    press of the Windows key (about 150 ms), and its slow lists (packaged
    apps, the Windows Start Menu) are warmed by `prefetch()` on a thread.
- **The shell has three sounds of its own**, in `sfx/<theme>/shell/`:
  `shell_startup.ogg` when the shell is up and complete, `shell_shutdown.ogg`
  when it goes away (never waited for: the goodbye is something to hear on
  the way out, not something to hold the program up, and Titan's own
  shutdown takes long enough that most of the clip is heard anyway -
  `play_shell_sound` cannot block at all any more), and `shell_start.ogg` on every navigation in the file
  browser - Explorer's own "Start Navigation". They say what the shell is
  *doing*, which is a different thing from the focus cues, so they have a
  switch of their own: Settings -> Titan shell -> Sounds -> "Play the shell's
  own sounds" (`shell_sounds`, also `shell.set_setting`). `a11y.shell_sound`
  is the one way in and `sound.play_shell_sound` / `sound.shell_sound_path`
  resolve them - the user's theme first, then the **default set even when
  the user never opted into theme fallback**, because these belong to the
  feature rather than to a theme. Still not speech: the shell says nothing
  through TTS. They are also **unpanned**: the shell starting, going away
  or opening a folder happens to the whole desktop rather than at a place
  on it, so it belongs in both channels - and an unpanned sound is the
  only one at full volume in both, `sound.py`'s pan law being linear.
  Where the shell DOES mean a place (the focus cues, panned to where the
  control is), `a11y.mixer_pan` converts: the shell says -1 (left), 0
  (centre), 1 (right) while `sound.py` has always taken 0, 0.5, 1, so
  handing one straight to the other put everything from the centre
  leftwards into the left speaker alone - the same bug the Titan Script
  `play` statement had, here making the shell's own sounds left-channel
  only and squeezing the taskbar's cues into half the stereo image.
- **Alt+F4 anywhere in the shell means Shut Down, not a closed shell**
  (`shutdown_dialog.shell_alt_f4`). The bar, the desktop and the Start menu
  are furniture: they have no document to close, and letting wx destroy one
  left `TitanShell` holding a dead frame - which crashed on the next repaint.
  So every one of them routes the key to msgina's dialog (the desktop always
  did), and their `EVT_CLOSE` **vetoes** any close that is not the shell's
  own teardown (`allow_close()`, called from `TitanShell.stop()`). The
  classic Start menu does the same, but only while the shell is running -
  on its own it is a Titan window and Alt+F4 closes it. The file browser is
  the one shell window Alt+F4 really closes, because it *is* a window with
  something in it.
- **The file browser: an accessible Explorer, rebuilt from ReactOS**
  (`explorer.py`). A folder used to drop the user into Explorer's own
  window - the one thing on the screen Titan cannot make readable - so the
  shell now has its own, taken from `browseui`'s `CShellBrowser` (the menu
  bar, the Back / Forward / Up / Folders / Views band, the address band, the
  status bar and the Folders bar) and shell32's `CDefView` (the view, its
  four modes, its columns, the menus on an item). My Computer lists the
  drives with their size and free space (`win_shell.list_drives`, new), a
  folder lists Name / Size / Type / Date Modified, and everything Explorer
  does is there: open, new folder, create shortcut, rename, delete to the
  Recycle Bin, cut / copy / paste (`fileops.py`, shared with the desktop so
  the "Preferred DropEffect" format has one implementation), Windows' own
  property sheet, sorting by a column header, and the address band that
  navigates or runs what was typed.
  - **It is accessible because it is native.** The folders bar is a
    `SysTreeView32`, the view a `SysListView32`, and the menu bar, toolbar
    and status bar are Windows' own, so a reader already knows how to read
    them; `a11y.name_control` gives the tree, the list and the address field
    the MSAA name a native control does not have. Measured with
    `AccessibleObjectFromWindow`: the list answers with the folder's name and
    role 33 (list), the tree "Folders" / role 35, the address "Address" /
    role 46. Navigating is the one change that is not where the focus is, so
    `accessibility.messages.announce_shell_location` says the new folder and
    its count to the screen reader alone.
  - **The keys are answered where the keyboard actually is** - the char
    hook, not menu accelerators. An accelerator fires wherever the focus
    happens to be, so a Del written into the File menu would delete the
    selected files while the user was typing in the address field or over an
    icon; Enter would open the selection instead of going where the address
    says. So Enter / Delete / F2 / Backspace / Ctrl+X,C,V,A are routed by
    `text_focus()`, `editing_label()` and `tree_has_focus()` - in the address
    field they are the field's own keys, during a rename they belong to the
    edit box, and in the folders bar they act on that folder. Alt+Left /
    Alt+Right / Alt+Up, F5, F6 (next pane), F4 and Alt+D (the address),
    Alt+Enter and Alt+F4 are the rest of Explorer's set.
  - **Everything that opens a folder comes here**: the desktop (a folder, or
    a shortcut whose target is one), the Start menu's File manager, My
    Computer, My Documents, My Pictures and My Music, and Windows+E while
    the desktop shell is on (`tce_system._handle_file_manager`; with the
    shell off it stays Titan's own file manager application). One window is
    reused unless another is asked for, and it appears on the taskbar and in
    Alt+Tab like any program - it is not shell furniture.
  - **A folder opens in milliseconds, however many files are in it.**
    Measured on a folder of 3 060 files before this: opening it **5 951 ms**,
    sorting a column 1 054 ms, Ctrl+A **37 717 ms** and F5 with everything
    selected **51 624 ms**. After, on the same machine and folder:
    **~30 ms**, ~35 ms, **0 ms**, **~25 ms**.
    Four separate versions of one mistake - asking Windows about every file,
    or asking the list control about every row, when neither had to be asked:
    - **Details is a VIRTUAL list** (`FileListCtrl`, `wx.LC_VIRTUAL` =
      `LVS_OWNERDATA`, which is what Explorer's own view uses): the control
      is told how many rows there are and asks for a row's text and icon when
      it paints it, so only the thirty rows on the screen cost anything.
      It is the same native `SysListView32` answering MSAA the same way -
      which is exactly why the virtual list is worth having rather than a
      list Titan draws itself. wxWidgets offers virtual mode in report view
      only, so the three icon views are filled a block at a time
      (`FILL_CHUNK`, with the message loop run between blocks and
      `_finish_fill()` for anything that needs every row).
    - **A file's type is asked of Windows once per EXTENSION** (`_TYPE_NAMES`)
      and its icon once per extension or per program (`IconCache`, now owned
      by the WINDOW rather than rebuilt on every fill, and asked only for the
      size the view is actually showing - it used to fetch both).
      `SetImageList`, never `AssignImageList`: a control that owned the cache
      would destroy it when the view changed.
    - **The status bar is worked out once per burst** (`deferred.Coalesced`).
      Selecting a thousand files fires a thousand selection events, and each
      one walked the whole selection to count it - the Ctrl+A number above.
    - **A selection is put back in one pass** (`_select_paths`), not by
      searching the folder once per selected file, and the folders bar reads
      only the directories (`subfolders`) instead of filtering a full listing.
  - **The read is on a worker, and the window waits only `READ_WAIT` for it.**
    `os.path.isdir` and `os.scandir` on a share that has gone away take as
    long as Windows' own timeouts, and this process is the shell - the appbar
    and the shell hook make it the thing every other program's broadcasts go
    through, so a GUI thread parked in a file system call is a machine that
    has stopped rather than a Titan that is thinking. An ordinary folder
    still fills in before `navigate` returns; a slow one says "Working..." in
    the status bar and fills itself in when the answer comes. A newer
    navigation makes an older answer stale (`_read_token`), and one
    navigation runs at a time (`_navigating`).
- **Action API**: the `shell` provider is now 36 actions - the originals
  plus `focus_tray`, `desktop_item_properties`, `desktop_item_target`,
  `open_item_location`, `rename_desktop_item`, `delete_desktop_item`,
  `create_desktop_shortcut`, `search_programs` / `run_program` (the Start
  Menu read straight off the disk, so they answer with no window open) and
  `power_options` / `power` (`always_confirm`, and `exit_titan` is one of
  the choices), plus the browser's three: `open_explorer` (at My Computer
  or at a folder), `list_drives` (size and free space) and `list_folder`
  (a folder, or "My Computer", listed the way the browser shows it).
  `focus_desktop` no longer needs the shell.
- **Both Start menus open at once, and "Windows apps" means the Store apps.**
  Measured before this: the classic menu took **60.7 ms** to open and the XP
  one **58.2 ms**, and the Windows apps branch **897 ms** the first time it
  was opened. After: **~15 ms**, **~14 ms**, **0 ms**. Four things were
  wrong, all in `src/ui/start_menu_content.py` unless said otherwise:
  - **`shell:AppsFolder` is not a list of apps.** It holds the packaged
    (UWP / Store) applications, which exist nowhere else on the machine -
    there is no shortcut on disk, only an Application User Model ID - AND
    every desktop program's shortcut, `steam://` URL and auto-generated
    entry besides. Measured here: 309 entries, 60 of them packaged. Listing
    all 309 made "Windows apps" a second, worse copy of All Programs with
    the Store apps buried in it, so the branch now keeps only the packaged
    ones (`win_shell.is_packaged_app`: an AUMID is
    `PackageFamilyName!ApplicationId`, and a family name is
    `Name_PublisherId` - no drive letter, no backslashes). Everything else
    is where the user already looks for it: Programs / All Programs.
  - **The branch never waits for Windows to answer.** Reading the Apps
    folder is about a second, so `installed_apps(wait=False)` shows whatever
    is known at once and reads the rest on a thread
    (`read_installed_apps_async`, which REMEMBERS the callers waiting rather
    than refusing them while a read is under way); a branch opened before
    the first read has finished says "Reading..." and fills itself in where
    it stands (`MenuTree.refill`) when the answer arrives.
  - **The top of a menu is not rebuilt for nothing.** A menu rebuilds on
    every open so that an application, macro or module installed since the
    last one is on it - but that is what the BRANCHES read, and the ten
    items of the top level never change. Putting them back into a tree
    control measured 14 ms per open, so `MenuTree.matches` asks whether
    anything changed and `reset_branches` throws away only what the opened
    branches read (~0.5 ms). The Windows Start Menu itself is walked once
    per open (`windows_programs()`) instead of once for All Programs and
    again for the search index.
  - **Building a menu is not the user moving through one.** Emptying the
    tree moves the selection off each item in turn and putting the first
    item back selects it, so the classic menu played its focus cue **ten
    times on every open**. `MenuTree.rebuilding()` is what `on_tree_select`
    now asks before cueing.
- **A Titan window in front means the keys are that window's**
  (`keyboard_handover.py`). The Invisible UI answers every key in the session
  while Titan UI mode is on - right while Titan is an application the user has
  put away, wrong the moment a window of Titan's own is in front of them. The
  main window has always known it (`temporarily_disable_titan_ui`); the
  shell's windows did not, and under the shell that is the COMMON case:
  Windows+M minimises Titan, `on_minimize` answers by putting it in the tray
  and starting the Invisible UI listening, and the same shortcut then puts the
  keyboard on the desktop - where every arrow key went to the Invisible UI
  instead of to the list of icons, so the desktop read as though it had gone
  and only a key the Invisible UI understood brought anything back. Now the
  desktop, the bar, both Start menus and the file browser all say so from
  their own `EVT_ACTIVATE` (`follows_activation`), under ONE name - they hand
  the keyboard between themselves constantly and must not each undo the last
  one's hand-over.
- **Minimising and restoring behave identically with the shell up.** The
  first answer to the bug above was to keep the Invisible UI switched off
  under the shell - which also took Titan's own non-visual interface away
  from the users most likely to want it, since a user who has replaced
  Windows' desktop with Titan's has not asked to lose Titan UI. The
  hand-over above is what answers it, so `gui.on_minimize` has no shell
  case at all; `minimize_to_tray` asks `shell_window_in_front()` once,
  because at the moment the Invisible UI starts listening there is no
  activation left to wait for. Three more things were unequal:
  - **Minimising after a restore was not minimising.** `restore_from_tray`
    bound a SECOND `EVT_ICONIZE` handler (`_on_window_minimize`) to hand the
    keyboard back, so both handlers ran - `minimize_to_tray` twice, a second
    tray icon, the sound twice, and the extra one ignored `minimize_action`.
    The hand-back is now a line in `on_minimize` (`_give_the_keyboard_back`),
    and `minimize_to_tray` is idempotent.
  - **The shell showed Titan by hand.** `shell_manager.show_titan_window`
    and `tce_system`'s Titan-window toggle did `Iconize(False)` / `Show()` /
    `Raise()`, which leaves the tray icon in the notification area and the
    Invisible UI still answering every key. Both go through
    `restore_from_tray`, which is the one way back for everything.
  - `restore_from_tray` plays its sound only when the window really was
    away, so asking for a window that is already there is silent.
- **Nothing queued may fire into a window that has gone** (`deferred.py`).
  The shell queues constantly - a taskbar button asks Windows to activate a
  window and rebuilds the bar 120 ms later, the appbar answers on a worker,
  the notification area is re-read four hundred milliseconds after Explorer
  has moved the work area - and every one of those held a bound method of a
  frame the shell destroys the moment it is switched off, Titan exits or the
  Shut Down dialog is answered. wxPython calls it anyway, the C++ object is
  gone, and the first attribute touched raises `RuntimeError` *inside wx's
  event loop*, where nothing catches it. That was the shell's most frequent
  crash, and it needed only for a window to close within the delay of
  anything it had queued. So `call_later` / `call_after` ask whether the
  window is still there **at the moment the call fires**, `Coalesced` turns a
  burst of asks into one piece of work, and a test walks every shell module
  to make sure no bare `wx.CallLater` / `wx.CallAfter` on a window of its own
  has crept back in. `TitanShell.window(name)` does the same for the shell's
  own three windows - a destroyed one is forgotten rather than called into.
- **Windows holds the ADDRESS of a callback Python can collect.**
  `ShellHook` subclasses the taskbar's window procedure with a ctypes
  callback; a bar destroyed without `undock()` (Titan exiting takes its
  children with it) left that subclass in place with nothing keeping the
  callback alive, so the next message Windows sent - including the
  WM_NCDESTROY of its own destruction - called into freed memory. A hard
  crash with no traceback. Installed hooks are now held in
  `win_shell._INSTALLED_HOOKS` until they are removed, and the bar undocks
  from `EVT_WINDOW_DESTROY` as well, so the appbar reservation and the
  subclass can never outlive it.
- **A drive with nothing in it is a blank size, never a modal dialog.**
  Reading My Computer asks every drive its label and free space, and Windows
  answers an empty card reader with "There is no disk in drive D:" - a modal
  system dialog over a shell that only wanted to fill in a column.
  `win_shell.quiet_media_errors` (`SetThreadErrorMode`, this thread's and not
  the whole of Titan's) is what `list_drives` reads inside.
- **Titan's settings are parsed when the FILE changes, not when they are
  asked for** (`src/settings/settings.py`). `get_setting` opened, read and
  parsed the whole of `bg5settings.ini` on every call - invisible in a
  settings dialog, ruinous in a shell that asks on every paint (is there a
  clock? a Show Desktop button?), on every layout, on every focus cue, once a
  second for the clock's format and **ten times a second** while the taskbar
  decides whether to slide away. Measured: a thousand reads of one setting,
  **169 ms before and 1 ms after**. The parse is kept and thrown away when
  `os.stat` says the file moved (checked at most every `STAT_INTERVAL`);
  `save_settings` puts what it has just written straight into the cache, so a
  setting read immediately after being set can never see the old value
  through a file system whose timestamps have not caught up; and
  `load_settings()` still hands back a copy, because the settings wizard and
  the controller modes keep the dictionary and change it.
- **The clock is told the time every second and changes once a minute.**
  `TextControl.set_text` compares the accessible name as well as the text, so
  the bar no longer repaints itself and tells MSAA its clock was renamed
  sixty times for every one time either was true. The notification area is
  likewise only laid out again when the strip has changed shape, not when an
  icon has merely been renamed (the battery percentage, the volume).
- Translation domain: **`shell`**.
- **A key pressed in a shell window is that window's key.** Every shell
  window - the desktop, the bar, the Start menu, the file browser - is a
  frame whose PARENT is Titan's main window, and `EVT_CHAR_HOOK` is not
  confined to the window it is bound to: it travels up the parent chain.
  So `gui.py`'s own char hook was answering keys pressed in the shell, and
  answering them first: a full stop or a comma typed into the browser's
  address band was read as the Buffer System's "next element" and never
  reached the field, F1 opened Titan's help over the shell and F4 the
  window switcher. `TitanApp._key_belongs_to_this_window()` now compares
  the event's own window's top-level parent against the frame and skips
  anything from another one - which is what the Buffer System's "no global
  hook, hosts wire these into their own windows" was supposed to mean.
- **The shell can be added to**: `data/shell addons/` contributes to the
  Start menu, the file browser, the taskbar and the desktop, or replaces
  the Start menu or the browser outright - see "Shell add-ons" below.
- Tests: `tests/test_shell.py` (run it directly; 323 tests).

### Cling: Klango applications, running inside Titan

Klango was a whole desktop for blind users, and the applications written for it
- Mole No More, Klango Piano, the typing course, the Zawisza Czarny soundscape -
are still on people's disks. They are not Windows programs: an application is a
folder of texts, sounds, levels and a topology, and it needs a platform
underneath it that speaks, plays a sound at a PLACE, owns the keyboard and keeps
a score. `data/components/cling/` is that platform.

- **An application is a folder in `data/cling/`, unedited.** `kni.txt`,
  `lang/<locale>/default/*.txt`, `skin/<skin>/{levels,themes,events}` - Klango's
  own layout, read as it stands. Discovery is `platform_utils.discover_data_
  entries`, so the user's overlay wins over the bundled copy and a packaged
  `.TCD` is found exactly like a directory. **Settings -> Cling -> Install a
  Klango application** copies a folder (or a whole `apps/` tree) in; the user's
  Klango installation is never modified, moved or written to.
- **The package is `clingkit`, not `cling`.** The component manager registers
  a component as `sys.modules['<folder name>']` **before** it executes it, so a
  package sharing the folder's name is shadowed by a half-built module and
  every `from cling import ...` fails with "cannot import name" - which is a
  component that does not load at all, and therefore a subsystem that is simply
  absent from the window. `init.py` re-exports the public names, so another
  add-on still says `import cling; cling.engines.register(...)`.
- **The voice is Titan's, and the sound is placed whatever the user's stereo
  setting says.** `stereo_speech.speak_stereo` for every word. For sound,
  Titan's `sound_mode` decides whether TITAN's own interface sounds are panned
  and is off by default - but a Klango board is not drawn, it is heard, and a
  player aims by where a mole sounds. Panning only when a global preference
  happens to be on would not make Cling quieter, it would make it unplayable,
  so Cling places its own sounds itself, always: `spatial_audio` when the user
  has turned 3D on, an ordinary channel with the pan law otherwise.
  `sound.play_sound_file` is the last resort, because it drops the pan when
  `sound_mode` is `none` and has no gain at all. Reading that setting as "make
  no sound" is the bug this replaced - measured live, Cling was completely
  silent on a default installation.
  A topology's `x`/`y`/`z`/`f` are converted **once**, in `topology.py`, into a field that knows its own `pan` (-1..1), `pan01`
  (`sound.py`'s 0..1 - the two disagree, and handing one to the other is the bug
  that put the shell's own sounds in the left speaker), `azimuth`, `elevation`,
  `gain` and `pitch`. A mole on the left of the board is heard on the left, and
  the far row is quieter and a semitone lower because the level file says so.
- **The account is Titan-Net's** (`account.py`). Klango applications ask for a
  Klango account for their scores and their chats; there is no such thing here
  and the user already has an identity on this desktop, so that is the one they
  are given. Saves and scores are kept per Titan-Net user name - two people
  sharing a machine keep their own - the sign-in is the headless one the user
  already saved, and nobody signed in plays under `local`, which works offline
  and loses nothing. A score is written locally **first and unconditionally**;
  the shared table (`extension_data_*`, slug `cling`) is best effort, so a
  server that is not there costs a sentence and never a score.
- **The rules come from the data where the data has them.** Five engines, one
  per genre, each chosen from what the directory really holds:
  - `grid_hunt` - `skin/*/levels/*.lev`. The level file IS the rules
    (`hit_target`, `nmole_time`, `max_nmoles`, `smole_time_bonus`), the `.top`
    is where every field is, the theme is what a mole sounds like. Mole No More
    plays through all thirteen levels on this.
  - `soundscape` - `spec.txt`, Klango's own place-description language
    (`start`, `Location`, `BkgVolume`, `links`, `fx` with `fxangle` /
    `fxtimestart` / `fxtimedelta` / `fxvol`). An arc written `300, 60` crosses
    the FRONT of the listener and is taken the short way round; taking it the
    long way would put the sound exactly where it is not.
  - `instrument` - a folder of samples whose file NAME is the key that plays
    them, `_l` marking the ones that loop (a switch, not a note).
  - `typing` - KTouch lecture files, read into levels and lines. A wrong key
    says the character that was WANTED: a learner who cannot see the line needs
    to be told where to go.
  - `reader` - the floor. An application Cling cannot play still ships every
    word it says, and a subsystem that answered such an application with
    nothing would be hiding what is really there.
- **`.lev`, `.top` and `kni.txt` are Lua, and are parsed as DATA**
  (`klango_lua.py`). Klango embeds a whole interpreter to read them; Cling must
  not, because these files come from wherever the user got them and running one
  as a program would mean a level file can open a socket.
- **An application may bring its own logic, and needs nothing installed.**
  `main.lua` runs on the Lua 5.1 interpreter this component CARRIES
  (`cling/lua/`: lexer, parser, tree-walking interpreter, the standard library
  and a full port of Lua's pattern matcher from `lstrlib.c`). Closures,
  metatables, multiple returns, varargs, `pcall`, `string.format`, `gsub` -
  what real code is written with. A native `lupa` dropped into
  `data/components/cling/lib/` is preferred and an application cannot tell the
  difference. There is no `io`, no `loadfile` and no `require` outside the
  application's own folder.
- **Cling ships logic for applications whose own code it cannot have**
  (`logic/<appname>.pag`, matched by `appname` then `appid`). Puzzle, Skeet,
  Long Jump, Dice Poker and the Wikipedia browser are written from each
  application's OWN texts - `readme.txt` for Long Jump is a specification of the
  run-up, `cantroll.txt` gives Dice Poker its three rolls - and run against that
  application's own sounds, words and skin. The application's folder is never
  touched: it is the user's copy of somebody else's work, and a file written
  into it would be gone at the next reinstall.
- **`.pag`, and the boundary Cling is honest about** (`pag.py`). A Klango
  installation is not a tree of folders: `apps/simplegames/mole/` holds one
  file, `km.pag`, two megabytes of it, and that file IS the game. So `.pag` is
  what a Cling application ships as too - LZMA over a JSON index, its own
  signature (`CLPG`), written by `src/scripts/pack_cling.py`, discovered in
  `data/cling/` exactly like a folder, with a folder of the same name winning so
  that work in progress overrides what was shipped.
  - **Klango's own are read.** The concealment was recovered by disassembling
    `bin/klangoplayer.exe` - not `klango.exe`, which is only the launcher -
    walking MSVC RTTI from `.?AVLuaConcealStream@@` to its vftable, where slots
    13 and 23 are the read and write halves. It is one line:
    `plain[i] = cipher[i] ^ ((i + 0xFC) & 0xFF) ^ 0xC6`, an eight-bit counter
    of the stream position exclusive-or'd with a constant. Under it is a
    container: a zlib-compressed directory of `(name, md5, offset, size,
    compressed)` records with the file contents beside it, every offset
    measured from `plain[4]`. **Each record carries the MD5 of the
    uncompressed content**, so extraction is checked rather than hoped for -
    measured across six packages including `llib.pag` (24 784 entries),
    24 028 files came out with every digest matching and no failures. What
    made it findable first was that `bytes[0:3] XOR (file size as u24 LE)` is
    the same three bytes in every package, which proves a fixed keystream
    before anything is decoded.
  - **None of that is needed to play an application.** A Klango `.pag` sitting
    beside its data folder is remembered as that application's original package;
    one with no folder beside it is still LISTED, and says in one sentence why
    it will not start. `llib` is not offered at all - it is the runtime.
- **An application's OWN Klango code is what Cling runs** (`clingkit/klango/`,
  engine `klango`). The engines above re-create a genre from an application's
  data - they are Cling's rules, not Klango's - and they are now the FALLBACK,
  for an application with no code of its own and for a machine where Klango's
  platform library is not installed. What an application gets by default is
  emulation: its own Lua, out of its own package, running Klango's own `main()`.
  Measured: **17 of 21** installed applications are emulated; opening one from
  Titan's window loads 63 files of Klango's own library and code.
  - What made it possible is that **Klango is mostly written in Lua**: of the
    146 Lua files in an installation, 103 are the platform library, and it
    implements 534 of the 693 `k_*` functions applications call. Cling's parser
    reads **146 of 146** of them and the 2.3 MB library parses in 0.7 s.
  - **The native surface is 310 functions, counted rather than guessed**, in
    families - `_Gfx_` 77 (the screen), `_Sys_` 54, `_Snd_` 19, `_Inp_` 16,
    `_Voice_` 13, `_Dir_` 7, `_Res_` 3, `_Net_` 1 - plus the 120 the engine
    exposes with no prefix at all (`k_*`, `urlencode`), which are the ones a
    reader looking for a family would never think to check. Sound, keys and speech go to the same places
    everything else in Cling uses, so an emulated application is heard in the
    user's own voice, through their own sound theme, positioned the way Cling
    positions everything. The graphics answer and paint nothing - Klango ships
    its own `klangonogfx.bat`, and the games are entirely in sound.
  - **The file system is a mount table, not a search path** - `/llib` the
    library, `/user` writable, `/` the application, and `/apps/cling/<id>`
    because Klango finds applications by walking `/apps`. A mount appears in
    its parent's listing or the walk cannot reach it. Resolved by searching
    instead, the library asks for its own texts and is handed the
    application's, which is where every application used to stop.
  - **`lpeg` is Cling's own** (`klango/lpeg.py`): a real PEG engine with the
    `* + - ^ /` operators as metamethods, grammars that carry their own rules,
    and a **capture tree** rather than a capture list, because `Ca` has to hand
    each function capture what the one before it produced. Seven of the
    library's modules build parsers with it at load time.
  - **It runs on a thread of its own, and that is not an optimisation.**
    `app:loop()` does not return - it IS the game - so calling it from the
    window's thread would freeze Titan for as long as somebody was playing.
    The window feeds it keys and reads what it has said.
  - **Klango's network is Titan-Net's.** A KRPC call named `SendHS`/`GetHS`
    goes to Cling's own Titan-Net scoreboard - the same one its engines use -
    and everything else answers "finished, nothing", which is what "klango.net
    has been gone for years" honestly means. What it must never answer is nil:
    the caller asks the answer whether it is `done()` on the next line.
  - Klango's own licence and anti-tamper calls (`__PecuniaNonOlet`,
    `__CPUCacheCrazyKiller`) answer "this is fine": the user already has the
    application, and a licence server that no longer exists cannot say yes.
  - `cling.emulate <name>` loads an application's own code and reports how far
    it got and which primitives it asked for that Cling has not written.

#### The emulated applications really play

Measured before this: of 17 emulated applications **one** said a word, three
hung, four stopped with a Lua error, and none of them ever reached a menu.
After: **17 of 17 start, speak, play their sounds and stop cleanly**, and Mole
No More can be played through - the menu, the level, the moles, the board.
Every one of these was a platform primitive that answered a constant where
Klango answers something:

- **klango.net said whether the application could run at all**, and its answer
  was "no server". `llib_appsession.lua` asks three questions before `main()`
  reaches a line of its own - who is signed in (`_login`), may this start
  (`_StartAppSession`), is this still the only session (`pingAppSession`) -
  and every application did the correct thing with a refusal: `main()`
  returned before the menu was built. `appsession.py` answers them, as
  Cling: the account is the Titan-Net one, the session is this process's.
  (It had been written and never wired to anything.) `__CPUCacheCrazyKiller`
  goes there too - it is not a licence check despite the name but klango.net's
  general-purpose call, and answering `True` to all of it handed the caller a
  boolean where a table belonged.
- **`k_VoiceIsSpeaking` IS `_Voice_GetStatus(v) == 0`**, and Cling answered 0
  for ever - a platform that is always speaking, so a sequence never reaches
  its second element. Every application froze on its welcome. `engine.Speaking`
  is the one estimator now, shared with `_Snd_IsPlaying`, using the heuristic
  Titan already uses everywhere else (`0.28 + characters / 16`).
- **A frame is where the platform yields** (`frames.py`). `_Sys_BeginFrame` /
  `_Sys_EndFrame` both answered `True`, so a game's own loop ran as fast as
  the interpreter could go, and `KlangoSession.stopping` was set by the engine
  and read by nobody. Frames are paced at 60 Hz - the rate `_Sys_GetFPS` has
  always claimed - and `frames.Stopped` is raised out of `EndFrame`, inside
  `k_LoopWithRawInput` and outside every `pcall` the library uses (Cling's
  `pcall` catches `LuaError`, and this deliberately is not one).
- **The keyboard is four shapes at once and they are different numbers**
  (`keyboard.py`): a DirectInput *scan* code in the raw buffer and the held
  set, a Windows *virtual* key in the messages. A queue of key names could
  never have worked. Three things had to be exactly right: Alt arrives as
  WM_SYSKEYUP with virtual key 18, which is the only way a menu opens; Escape
  is scan code 1 in `inp.keyboard` for a menu and virtual key 27 in a message
  for the shell; and **a released key must be reported as released**, because
  the library clears its own held-frame count only when told a key is at zero
  - left to grow, Enter chose a menu item once and then never again.
- **A sequence is a list of sounds with DELAYS** (`sounds.py`), scheduled by
  `_Snd_Create(name, spec, {delay = seconds})` and built from
  `_Snd_GetProperty(name, "sampleTime")`. Ignoring the third argument played a
  whole menu inside forty milliseconds; a length of zero collapsed the
  schedule before it was built. A **group** is what `k_SoundPlay` hands back
  and what `k_SoundIsPlaying` is then asked about, so `_Snd_GroupCreate`
  answering 1 every time made every sequence in the program the same one. And
  `play` is a repeat count - 0 once, -1 for ever, n for n+1 times - not a
  boolean.
- **`pos3d` and `freq` are where the sound is**, and they were ignored: every
  sound on Mole No More's board came out of the middle, which for a game aimed
  at by ear is the game not working. `engine._placement` turns Klango's own
  listener-relative vector into a pan, an elevation and a distance gain, and
  `freq` (hundredths of a semitone - `3x3.top` uses 0, -100, -200 for its
  three ROWS) into a real resample, so a grid is heard as a grid.
- **A sample is found in the application's own file system**, not in Cling's
  skin reader. Klango names one `//skin/default/themes/default/t_move`, with
  the extension left off; every sound Mole No More has was found this way and
  none of them was played. And **a `.txt` where a sample was asked for is
  text to speak**: Klango's own `speechexts` is `.wav .ogg .spx .txt .mp3` - a
  text file among the sound formats - which is how a menu item with no
  recording gets said. Without it every application's menu played its earcons
  and said nothing.
- **`k_Run` is `dofile`, not `require`, and not only for `.lua`.** It runs the
  file again every time, because that is how an application loads its next
  level; and appending `.lua` to a name that already had an extension is how
  `skin/default/levels/std_level_01.lev` came back "is not there". What is
  guarded against is a file running itself.
- **A library function ignores arguments it was not expecting.** Lua expands a
  multi-value call in the last argument position, so
  `string.lower(name:gsub("_", "-"))` passes two arguments - ordinary Lua that
  every one of Cling's fixed-arity natives refused. `stdlib._lenient` trims
  them, and a native handed the wrong number now reports the LUA line that
  called it rather than a lambda inside a factory function.
- **Klango's tracing is as cheap as what receives it.** `pr` and `tpr` are
  `FormatElement(value, name, depth)` handed to `_DBG0` / `_Sys_TransientLog`,
  and in Cling both of those discard it - but the formatting is a recursive
  walk written in Lua. `mediaset:speech` calls `tpr(self.usetabs, ..., 33)` on
  every speech file it cannot find, and a Polish application misses 32 of the
  library's own: **19.6 seconds** of Dice Poker's startup, building strings
  nothing reads. The platform now starts in 0.64 s for every application
  (Mole was 3.1 s, Dice Poker 22.0 s). `CLING_TRACE=1` shows what an
  application's own `pr(...)` says.
- **A package is unpacked once, not once per run.** The mount folder's name
  was `hash()` of the package's path, and Python salts string hashing per
  PROCESS - so no two runs agreed on the folder, every boot re-extracted the
  whole of `llib.pag` (23 571 files), and the cache grew a directory per run
  for ever. A digest of the path is the same number in every process, a stamp
  file makes the cache survive a restart, and the other copies are pruned.
  The Cling suite went from 105 s to 8 s on this alone.
- Refused, and recorded rather than silently absent: `k_DaemonRegHotKey` and
  the rest of Klango's daemon mode, which takes SYSTEM-WIDE hotkeys each
  carrying a string of Lua to run when it fires. Titan owns the desktop's
  shortcuts. `k_NewHttp` and `k_NewIcyStream` answer a real object that has
  reached nothing, so an application says it is offline instead of stopping on
  `attempt to call a nil value`.

#### Every Klango application, not just the games

Measured after the round above: 17 of 17 started and spoke. What that did not
say is whether they could be USED - and several could not, because the parts
of the platform they reach for once a game or a screen really begins were not
there. All of these are one gap each:

- **An application is not always in ONE place.** Its code arrives in its
  `.pag`; the folder beside it in `data/cling/` may be an unpacked copy of
  the DATA only - which is what the German distribution ships - and may have
  things the package has not. Typing Lessons keeps its code, texts and skin
  in `ktypist.pag` and its **lessons** in the folder, so the emulator
  answered "the collection is empty" and the application had nothing to
  teach. A mount is now a LIST of real folders, tried in order and listed
  together: Klango sees one tree and so does Cling.
- **The library's own mediaset was never registered as THE one.**
  `_k_GetGlobalMediaSet()` answers a file-local of `llib.lua` that only
  Klango's shell assigns, and every mediaset made afterwards reads it to
  decide where to copy `globalsnd` from. Left nil, an application's own
  mediaset believed it WAS the library, registered nothing, and the first
  widget to reach for one of the platform's sounds indexed a nil - which is
  what the Wikipedia browser does the moment a search result is opened. The
  epilogue sets it, after `_k_suiinit` has filled it and before any
  application asks.
- **`_Gfx_TxtEdit_*` is not decoration** (`klango/textedit.py`). Everything
  else `_Gfx_` does is drawing and rightly answers nothing, but the text
  control is where a search term, a message or a name is typed: without one,
  `attempt to call a nil value '_Gfx_TxtEdit_Init'` ends the Wikipedia
  browser, the chat and every application with a field. Klango's own is a
  Windows rich edit that has the keyboard and edits itself - the application
  is only TOLD what was typed - so Cling's is a buffer with a caret and a
  selection, and `Editors.apply` types into it from `_Inp_KeySys_Refresh`,
  which is where Windows would have. Two of Klango's details are not
  negotiable: a line ends with `\r` (the library searches for one), and
  `GetCurrentPos` answers a PAIR. `SetText2` is the rich one and is handed
  RTF, so `_rtf_to_text` turns it into words - storing it as it arrived made
  a text browser read `rtf1 ansi ansicpg1252 colortbl red255` aloud before a
  word of the article.
- **The web, for the applications that ARE the web** (`klango/web.py`). The
  Wikipedia browser is a search box and an article reader; Mastodon, the
  Twitter client and the translator are the same shape, and an emulator that
  refuses the network is one on which they cannot work at all. So `k_NewHttp`
  really fetches: `http`/`https` only, capped at 8 MB, timed out, and on a
  thread of its own so the game keeps running while it waits - which is what
  Klango's own client did and what its progress dialog is for.
  `GetStatusCode` is 0 for a connection that never happened and -1 for one
  the application cancelled, because that is what `k_GetHTTPResponseError`
  reads to tell the three apart. It sends a user-agent that says what it is:
  Wikipedia answers 403 without one, and the application reads that as an
  article that is not there.
- **A primitive nobody wrote answers nothing rather than being nil.** A name
  that is nil is not a function, so `attempt to call a nil value
  '_Sys_CharIs_'` ends the run wherever it happens - for the Wikipedia
  browser, the moment somebody typed into its search box. The globals table
  now has an `__index` that hands back a recording no-op for the six native
  families (`_Sys_ _Gfx_ _Snd_ _Inp_ _Voice_ _Dir_`), so the application
  carries on being wrong about one thing instead of stopping, and `report()`
  names what is missing. Deliberately narrow: an ordinary Lua global that was
  never assigned is still nil, because Klango's own code tests plenty of
  those.
- Written properly rather than caught by that net: `_Sys_CharIs_` /
  `_Sys_CharTo_` (the C runtime's character classes, which Python's string
  methods already know for every alphabet) and `urlencode` / `urldecode` -
  one of Klango's engine functions with no `_Sys_` prefix, which the library
  itself calls and never defines.
- **`/common` is mounted.** It is Klango's shared area - `/common/extras/`
  is where a user's own replacement texts and skins go - and its absence had
  a second effect: `_k_GetMyKlangoOptions` reads
  `/common/myklango/myklango.cfg` and then asks `k_TableSize(nil) > 0` about
  the answer, which ends the application. The file is there and empty, which
  is what "no branded installer" is.
- **Two different packages may be called `wiki.pag`** - Cling ships one in
  `logic/` and the user has another - and the mount cache pruned by NAME, so
  mounting one deleted the other's folder while it was in use. It prunes by
  the stamp now: a folder without one was made by the old `hash()` scheme and
  is the only kind thrown away.

#### Played through, not merely started

Starting and speaking is not working. Each of these was found by playing an
application from its first word to its last - the menu, the game, the score,
the way out - and each of them is one line:

- **`math.random(5)` answered 5 every single time.** `llib_math.lua` replaces
  `math.random` with Klango's own `_Sys_Random`, so `_Sys_Random` takes LUA's
  arguments: none is a fraction, ONE is `1..m`, two are `a..b`. Reading one as
  "from m to m" is a generator that never generates. Dice Poker draws until it
  gets one of the shake sounds it actually has and looped for ever on its
  first roll; and everything else about every application was as random as
  this was - where a mole appears, where a clay pigeon flies, how a board is
  shuffled.
- **A sound can TRAVEL.** `k_SoundAction(sid, {pos3dSlide = {-20,1,0,
  20,1,0, t}})` is how Skeet throws a clay pigeon: the disc really crosses
  the listener, and aiming at where it has got to is the game. Ignoring the
  slide left every disc hanging where it was thrown from. The journey is
  stepped by the FRAME - the same clock everything else runs on - so a paused
  game pauses the flight, and a sound that is still travelling is still
  playing, whatever the mixer thinks of the clip. Measured: from hard left at
  gain 0.10, swelling to 0.89 as it passes, away to the right.
- **`dmin`/`dmax` belong to the SAMPLE**, and are given when it is prepared.
  Skeet's clay pigeon is `1, 10` and is thrown from twenty units away; the
  platform's own speech is `1, 3`. One figure for both makes a wide board
  sound flat and a near sound distant.
- **Speech is placed, because Klango places it.** `k_VoiceSpeak` renders a
  line to a stream, loads it as a sample and plays it with
  `k_SoundPlay(playargs)` - so a spoken line gets the `pos3d`, `freq` and
  `vol` the caller asked for, and only falls through to `_Voice_Speak` when
  there is no stream. Cling answered nil to `_Voice_SpeakToStream`, so every
  spoken line took the second path and came out dead centre: Dice Poker says
  each of its five dice at its own place on the table (`pos3d = {active - 3,
  0.5, 0}`) and all five sounded like one. The "stream" is not audio - Titan's
  engines speak rather than handing back a buffer - it is a note saying what
  to say, which the sound layer already knows how to place.
- **The step ceiling is per FRAME.** It exists so an application's own runaway
  loop cannot take the desktop with it, and counting it over the whole RUN is
  right for a script and wrong for a game: Dice Poker reached forty million
  after three thousand frames and stopped in the middle of a hand. A loop that
  never finishes never reaches `EndFrame`, so it still trips; a game played
  for an hour never does. And the error now says WHERE.
- **A path is looked for once.** Klango's mediaset resolves a name by asking
  whether it exists with each of five extensions in each of two directories,
  and `_k_Background_Run` does that once a FRAME. The answer is remembered
  until something is written.
- **The score is sent under the name the application uses.** `SendHS` is Mole
  No More's and Long Jump's; Skeet says `save_score` and four spellings of
  `get_hiscores`. A name that is not recognised answers "finished, nothing",
  which the game reads out as "Network Error: Score wasn't saved". And the
  answer to a submission is the player's PLACE on the table, wrapped as
  `{result = n}` like every other KRPC answer - a bare `true` made Long Jump
  index a boolean the moment it had a score to send.
- **`os.date("*t")` answers a TABLE.** Lua's does, and code reads `now.year`
  straight off it; answering a string made Shopping with Klango stop with
  "attempt to compare nil with number" while building its request timestamp.
  `os.time(table)` is the other half.
- **The other 52 engine functions.** Klango's engine exposes that many more
  with no `_Sys_` prefix that its library calls and never defines, and every
  one of them was nil. They are read out of the library itself rather than
  guessed - `tests/test_cling.py`'s `EveryEnginePrimitive` parses all 104
  files and fails if a single one would be nil when an application called it.
  Written properly: `k_Base64Encode`/`Decode`, `k_HexEncode`, `k_HMAC`,
  `k_SplitString`, `k_FileRemove`/`Rename`, `k_RmDir`, `k_GetWinPath`,
  `k_MIMEProbe`, `k_GetKniInfo`, `k_GetUnixTimestamp`, `_Sys_CharIs_` /
  `_Sys_CharTo_`, `urlencode` / `urldecode`, the `S` registry pair. Refused
  and recorded: running a program, installing one, taking a shortcut or an
  autostart entry, recording from the microphone, reading the clipboard.
- **A refusal has to answer ANYTHING that is asked of it.** Naming the
  methods a refused object might be sent is not enough: the chat calls
  `k_NewP2PSession()` and then `session:GetState()`, and a name that is not
  in the list is nil, which is where the application stops. So the object
  answers every method - the few that must give a number do, the rest give
  nothing, which is what "there is no network" means.
- **Every number a game sends with its score is kept.** Klango's server knew
  each game's own columns and Cling cannot: Skeet sends `(user, score,
  level)`, Mole No More sends `(user, fails, normal, special, total, level,
  version)`. So the whole list goes on the row, the largest is the score, and
  a game reading `j.normal_moles` off the table it gets back finds what it
  sent.

#### The interface was in the middle, and the piano was silent

Three more, each of them one condition, and each of them heard rather than
read - the applications reached their menus and played their games with all
three wrong:

- **`pos3d` is written two ways and Cling read one.** An application says
  `pos3d = {-20, 2, 0}`; the platform library says
  `pos3d = {x = -1, y = 0.5, z = 0}`, because `LLib_Math_AngleDist_To_3dPos`
  returns a NAMED table. Klango's engine takes both; `_placement` read only
  the array, so everything the library places came out dead centre - and the
  library places the whole interface. `menu:recalcpositions` lays a menu's
  items out from **-60 to +60 degrees** at a distance of 1, so moving through
  a Klango menu moves the sound across the listener and a menu ANNOUNCES its
  own shape by pinging each item at its place; the help channel is at
  `{x=-1, y=0.5}` and the information channel at `{x=0.5, y=0.5}`; a forum
  post is at its author's place; and every ambient sound
  `k_BackgroundPrepare` scatters is at an angle and distance of its own.
  Measured after: a five-item menu at -0.87, -0.50, 0.00, +0.50, +0.87, with
  each item's name spoken from where the item is.
- **A relative name with no extension is the ordinary case.**
  `k_DirectoryRead`'s `name` field is the file name with the extension taken
  OFF (`k_SplitFileName`, `llib_files.lua`), and Klango Piano builds every
  key's sample out of it - `sounds/<model>/<key>`, no leading slash, no
  extension, which is also how `_l` (the loop marker) can be the last two
  characters of the name. Cling asked its own file system only about names
  beginning with `/`, so every one of the piano's twenty-three keys resolved
  to nothing: the application started, spoke, took the keys, called
  `k_SoundPlay` for each one and made no sound at all.
- **Klango's sound groups are a TREE, and volume and pause run down it.**
  Every `k_SoundPlay` creates a group and plays the sequence inside it
  (`s.gid = _Snd_GroupCreate(5)`, `llib_snd.lua`), so `LLib_GID_Otoczenie`
  holds no sounds of its own - it holds the groups made under it. Cling's
  groups were flat, and a group action looked only at sounds whose group id
  IS that group, so it reached nothing and **none of the platform's volume
  work happened at all**: `k_BackgroundPlay` fades the ambience in with
  `volMulSlide = {0, 1, speed}`, every dialog ducks it to a fifth and pauses
  the game's whole group (`{pause = 1, volMul = 0}`), and `k_BackgroundStop`
  fades it out. What that sounded like is a game still going on at full
  volume underneath every dialog, over the words. Now: `group_create`
  remembers the parent, `of_group` is the subtree, `group_factor` is the
  product along the chain to the master (group 0), a slide is stepped in
  `pump()`, and a paused sound is held - including its journey, so a clay
  pigeon paused under a dialog is where it was when the dialog goes.
  Measured on Skeet: the ambience fades 0 to 0.10 over its second, ducks to
  0.02 while the menu is open, comes back, and fades out when the game
  starts.

- **`replay = -1` did not loop where the sound actually goes.**
  `spatial_audio.play_file` had no looping at all - nothing in Titan had
  needed it, because the only 3D sounds were Titan's own one-shot cues - and
  3D is exactly what a Cling user has on. So every Klango loop played once:
  the background music, Skeet's flight, Zawisza's beds, a piano key held
  down. `play_pcm` takes `loop` and sets `AL_LOOPING`, `pause_source` holds
  one where it is (`AL_PAUSED`), and `_reap` stops collecting a source that
  is paused rather than finished. Cling calls both through a wrapper that
  drops the argument if it is talking to an older `spatial_audio`, because an
  application should lose the looping rather than the sound. Measured: a 2 s
  clip still playing after 3 s, paused, resumed and stopped.
- **`vel3d` is Klango asking for the Doppler shift, and it was thrown away.**
  Skeet works the vector out itself (`x_d = 40/tile_f`, with the comment
  saying what it is for) and hands it over with the clay pigeon. OpenAL
  computes the shift continuously from `AL_VELOCITY`, which is the one thing
  that cannot be done to a clip already playing by any other means, so
  `spatial_audio.set_velocity` gives it to the source and `_placement` reads
  `vel3d` in either of its two shapes. The stereo path has no Doppler and
  keeps none. Measured: OpenAL reads back 5.06 on a flight sound still
  playing.
- **The pan law is constant power, because in Cling a sound MOVES.** The
  stereo fallback split a channel linearly, so a sound crossing the listener
  is 3 dB quieter exactly as it passes the middle - the moment it is closest
  and the distance model is making it loudest. The two fight, and a clay
  pigeon dips as it goes by. `cos`/`sin` of a quarter turn keeps
  `left^2 + right^2` at 1 wherever it is, which is also what a menu spread
  from -60 to +60 degrees needs: the same loudness for every item. (The 3D
  path was never affected - OpenAL does its own.)
- **Every `k_SoundPlay` leaves a group behind.** The library creates one per
  sequence and destroys none, so a game played for an hour would carry tens
  of thousands - all of them walked whenever a parent is ducked. The subtree
  is a walk down `group_children` rather than a sweep of every group there
  has ever been, and `pump()` sweeps up the empty ones every `TIDY_EVERY`
  frames.

Played through afterwards, with the real window and the real mixer: Klango
Piano sounds every key (`c.wav` 2.005 s through OpenAL), Skeet's disc is
thrown from the left, crosses in 7.9 s and is hit at 4.17 s for 54 points
with the hit placed to the right because the shot was late, Long Jump's
run-up alternates hard left and hard right and answers the arrows, and Dice
Poker says each of five dice at -0.97, -0.89, 0.00, +0.89, +0.97.

#### Not every file Klango ships is UTF-8, and one has no newlines at all

`clingkit/textio.py` is the one place text is read now, and it exists because
of two things that are invisible until they are not:

- **11 of the platform library's 104 Lua files are Windows-1250**, the Polish
  code page Klango was written on, and so are texts inside applications.
  Reading one as UTF-8 with `errors='replace'` puts U+FFFD where every Polish
  letter was - in a comment that is invisible, in a string literal it is a
  word with holes in it that the synthesiser then reads out, and in
  `p_radiopresets.lua` it is a character the lexer refuses outright. Four
  encodings are tried in turn, ending with `latin-1`, which cannot fail: there
  is no such thing here as a file that cannot be read.
- **`llib_s4tb.lua` ends its 1961 lines with a bare `\r`** - Mac line endings,
  in a file from 2008 - and a lexer that treats `\r` as whitespace lets the
  first `--` comment swallow the whole file. It loaded without a word of
  complaint and defined nothing, so `_k_WidgetPrepare_S4TB` was missing from
  every application that started. Line endings are normalised on the way
  through.

#### Cling follows Titan's language

`host.texts.locale` is the best locale an application actually SHIPS, which
is a different question from what language the platform runs in - and reading
the second off the first made the whole of Klango's own interface English on
a Polish Titan whenever the application had no Polish (Mole No More has only
`en-us`). `ClingHost.locale` is Titan's language in Klango's spelling
(`pl` -> `pl-pl`), and it is what `k_GetWindowsLocale`, `k_GetLangName` and
the voice list are built from.

**`/user/app/lang` is written on every run, not only the first.** The library
keeps the language it settled on in that key and reads it back at the next
start; in Cling's own store that meant an application opened once in one
language stayed in it for ever, whatever the user later chose in Titan. The
library still falls back on its own when it has nothing in that language -
that is `langIsOk`'s job and not Cling's.

**One voice, offered for every language that can be asked for.**
`k_VoiceEnum(lang, fulllang)` filters by language, and an empty answer is not
a degraded voice: `setSynth` calls `killklangobecauseoflang()` and the
application is over. So Titan's voice is offered once for Titan's language,
once for the application's, and once for English - the library's own fallback
- each with a `regpath` of its own, because that is what a choice is
remembered by.

**Cling's own Polish had no Polish letters in it.** Its `.po` said "juz",
"sa", "ktorym", "Szczegoly", "Pejzaze dzwiekowe"; the demo application's
texts were the same. Both are written properly now. (The applications' own
texts were never the problem - every `.txt` in every `.pag` is UTF-8 and
always was.)

#### Klango's Settings and Help are Titan's

`klango/titan_bridge.py`. An emulated application's menu offered a language
picker, a voice picker and an audio-theme picker that **changed nothing** - a
Cling application speaks through Titan's TTS and reads Titan's language and
theme, so Klango's screens let the user choose and then went on exactly as
before - plus a knowledge base, a terms-of-service page and a feedback form
that all talked to klango.net. So the platform's screens are Titan's:
Settings opens Titan's settings (through whichever settings interface the
user chose, like every other way in), Help opens Titan's help, and feedback
goes to the Feedback Hub.

**Settings and Help are ONE entry each.** Redirecting the screens behind
Klango's submenus was not enough: the user still walked into "Settings" and
found four items - theme, language, synthesiser, interface - every one of
which now did the same thing. The submenu is recognised by what is INSIDE it
(`__!setskin!__`, `__!helpkeys!__`) rather than by its name, because the name
is in the user's language.

What is deliberately NOT redirected is everything that belongs to the
APPLICATION: its own help text (F1), its own readme and changelog, its own
version, its own exit. And a window that did not open is never reported as
open - Titan's own openers report a failure by answering nothing and printing
to a console nobody using this can see.

#### The interface sounds are Titan's too

Moving through a menu, choosing something, reaching the end of a list, a
dialog opening: an emulated application makes exactly the same noises Titan
makes for exactly the same things, so it makes TITAN's - the user chose a
sound theme and this is their desktop. `engine.TITAN_CUES` is the map, and it
is only ever applied to `/llib/skin/` - a mole's hello is the game, not the
interface, and Titan has nothing to say about it. A name Titan's theme has
not got falls through to Klango's own file, so nothing is lost by mapping
one.

#### The window is its title and its keyboard

`ClingSurface` used to carry a multi-line text box holding everything the
application had said. That is a control a screen reader offers to review,
arrow through and search: a second interface, in the way of the one the
application actually has, on top of a program that is already talking. The
window is now its title - `<application> - Cling` - and a panel that holds
the keyboard, and nothing else.

**A key is HELD until it comes back up**, and there are three ways it can be
let go. `k_KeyJustPressed` is "held for exactly one frame" and
`k_KeyJustReleased` is "the raw buffer said up this frame", and the two only
mean what they say if a key the user is holding is held here too: Klango
Piano starts a loop on the way down and stops it on the way up, so a key
released a frame after it was pressed could never sustain a note. Every key
used to be a press for one frame, which is why it could not. DirectInput's
buffer carries no auto-repeat either, so a repeat only says the key is still
down rather than pressing it again - holding an arrow in a Klango menu moves
one item, as it does in Klango.

The reason it was a press is real and had to be answered rather than
reverted: **a release can be lost** - the key comes up wherever the keyboard
is by then, which after Alt+Tab, a dialog or a focus change is somewhere
else - and one that never arrives leaves the key held for ever and the
application answering nothing at all. So a key is let go by its own
`EVT_KEY_UP`, by this window losing the keyboard (`_let_go`), or by
`KEY_STALE` (1.5 s, longer than Windows' longest auto-repeat delay) passing
with no repeat to say it is still down. The modifiers stay a press, because
Klango watches for Alt coming back UP with nothing pressed in between - that
is how a menu opens.

Opening the Cling window says **"Cling is ready"** ("Cling gotowy"): it reads
what is installed, unpacks a package it has not seen and looks for Klango's
library before the list is a list, so "it is open" and "it is ready" are not
the same moment - and the second is the one worth saying to somebody who
cannot see the window.

#### Closing the window closes the application, and its sound

An emulated application runs on a thread of its own and is a frame - or a
long Lua call - away from noticing that it has been asked to stop, so
`KlangoEngine.stop()` **closes the host first** and waits for the thread
afterwards: what is playing stops now, and nothing the application asks for
later is answered, however late it arrives. Three things were wrong before:
`Mixer.stop_all` tracked only the LOOPS, so a one-shot still going outlived
the window; a sound the application had SCHEDULED and not yet started was
begun after the close by the next frame; and the wait came first, so a game
kept playing its background music for those two seconds - and a game that
never reached a frame kept playing it for ever. Measured on Mole No More with
the board up and six sounds playing: `stop()` returns in **0.02 s**, nothing
is audible afterwards, and the thread is gone.

#### A sound that has started can still be moved and made louder

Everything Klango's sound layer does after a sound has STARTED goes through
one call, `Mixer.set_gain` - and it refused a 3D handle outright, which is
the path a Cling user is on, because a Klango board is aimed at by ear and
Cling asks for HRTF whenever the user has 3D on. So on the path that
matters, nothing ever moved and nothing ever changed volume:

- **An ambience is started at NOTHING and faded in.** `k_BackgroundPlay` does
  `_Snd_Action(bkgGID, {volMul = 0})`, starts the loop, and then
  `volMulSlide = {0, 1, speed}`. With the slide reaching nothing, Dice
  Poker's, Long Jump's and Simple Puzzle's backgrounds were started, looped
  and held at the zero they were started at for the whole run: playing,
  correct, and completely silent.
- **Skeet's clay pigeon is thrown and then set moving** -
  `k_SoundAction(sid, {pos3dSlide = {-20,1,0, 20,1,0, t}})` on a sound that
  is already playing. `_step_journey` worked out the pan and the gain
  perfectly, every frame, and handed them to a call that answered False: the
  disc sat in the middle of the room at full volume for its whole flight.
  Measured after: pan -1.00 at 13.1 s, -0.09 as it passes at 17.1 s, +1.00 at
  21.0 s, with the gain swelling 0.10 -> 1.00 -> 0.10.
- `src/titan_core/spatial_audio.set_gain(src_id, gain)` is the missing half -
  `AL_GAIN` on a live source, beside the `move_source` and `set_velocity` that
  were already there - and `Mixer.set_gain` now moves the source as well as
  re-gaining it, because a `pos3dSlide` is a PLACE, not a volume. It is asked
  for by name (`getattr`), so a Cling packaged beside an older Titan loses the
  fade rather than the sound.
- The height travels too: `_elevation_of` is its own function and
  `set_gain(handle, pan, gain, elevation)` carries it, because a sound that
  travels moves in three axes and re-placing two of them is the same mistake
  one axis smaller.

#### Cling ships Klango's library

`data/components/cling/apps/llib.pag`. Everything else about Cling already
lived inside the component; the platform library did not, so the emulator -
**seventeen of the twenty-one** installed applications - worked only on a
machine that happened to have a Klango installation. A subsystem whose whole
claim is "your Klango applications run here" cannot depend on the user having
Klango. `find_library()` looked in the component's own `apps/` all along; it
is now the last place looked, so the user's own `data/cling/llib.pag` still
wins for anybody with a newer or a patched copy, and `llib` is never LISTED
as something to play - it is the runtime.

#### A text field is where an application is actually used

Four faults, each one line, and between them they made the Wikipedia browser
useless and every multiline field unreadable:

- **The space bar was not a key.** `canonical(' ')` trimmed the name before
  looking it up, which for a single space leaves nothing at all, so
  `press(' ')` answered False and typed nothing. Every other letter went in,
  so a search box read back as what was typed with the spaces missing - and
  the Wikipedia browser answered "I could not find anything matching your
  query" to a title that is on the front page. It is the same in every chat,
  note and name field there is. The trim is now for a name with room around
  it; a name that IS whitespace keeps itself.
- **`urlencode` wrote `+` for a space.** That is PHP's, and the far end of
  every URL Klango itself built was PHP - but what an APPLICATION builds with
  it is a PATH, and in a path `+` is a literal plus. The Wikipedia browser
  encodes a title into `/wiki/<title>`, takes it back out and asks for
  `Special:Export/<title>`, escaping any `+` it finds to `%2B` on the way
  (`object.lua`'s `downloadPage`) - so every article whose title is more than
  one word was fetched as a title with a plus sign in it. Measured on
  `pl.wikipedia.org`: `Kot%2Bdomowy` answers **200 with no `<text>` element at
  all**, which the browser reads as "the page does not exist" and says so,
  having just found and offered the article. It is `rawurlencode` (RFC 3986)
  now, which is right in a query string as well.
- **A document put in with `\n` was one line.** A rich edit stores a paragraph
  break as `\r` and normalises what it is given, and `\r` is the only
  separator the library ever looks for (`_Gfx_TxtEdit_Find(richedit, "\r")`,
  `GetCurrentLine`, `GetNumberOfLines`, Up and Down). `SetText` / `SetText2`
  stored what they were handed, so the article view held a whole Wikipedia
  page as a single line: Up and Down moved nowhere and it buzzed at both ends
  of it. `TextEdit.set_text` is the one way in now and `as_lines` is what puts
  the control's own separator in - `LoadFile` and everything typed as well.
- **`GetCurrentLine` answered one value; the library reads two.** The second
  is which line the caret is on, from zero, and a textarea reads it on every
  arrow (`local _, l = ...`) to find out whether it has reached the top or the
  bottom and buzz. Left nil, a multiline field never said it had stopped.
- **`_Gfx_TxtEdit_SetFocus(handle, f)`'s flag is not decoration**: 1 takes the
  keyboard, **0 gives it up**, and the library says 0 the moment a control is
  built and again when the user leaves it (`llib_suitexted2.lua` does both;
  `llib_suigfx.lua` remembers `HasFocus` across a dialog to put it back).
  Reading the handle and ignoring the flag gave the keyboard TO whichever
  control had most recently been built or left, so the arrows, the letters and
  the backspace went to a buffer nobody was looking at.

Live-verified end to end on a Polish Titan: "Szukaj - pl.wikipedia.org", a
two-word title typed with its space, "Kot domowy" found and opened, the
article read out, and Down and Up moving through its sections with the buzz at
the ends.

#### Cling is a portable component

Everything Cling ships is inside `data/components/cling/`: its applications in
`apps/`, Klango's own platform library beside them as `apps/llib.pag`, its
written-here logic in `logic/`, its Lua in `clingkit/lua/`, its languages in
`languages/`. `data/cling/` is the USER's - the applications they installed,
and their own copy of Klango's library if they have one - and is created on
demand rather than shipped. So the component can be copied to another Titan,
or packaged as a `.TCD`, and still be whole. The user's own copy of an
application still wins over the one Cling ships, which is the overlay rule the
other eleven add-on kinds already follow.
- **All three faces, like the macro manager**: a view in the main window, a
  **Cling** category in the Invisible UI, a **Cling** submenu in Klango mode, an
  entry in the Components menu, a settings category, and seven actions
  (`cling.list_applications`, `run`, `details`, `scores`, `install`, `account`,
  `status`).
- The window is `TabbedListFrame` - the class Titan IM and the Titan-Net
  services already are - so row 0 is the tab bar, Left/Right cycle the
  categories and Escape leaves. A running application gets a window that is
  its TITLE and nothing else - `<application> - Cling` - and a panel that
  holds the keyboard. A Klango application is heard, not read, so a transcript
  beside it was a control the user had to leave to play and a second thing for
  a screen reader to find; what the window is for is owning the keyboard,
  driving the engine's clock, and being what Alt+F4 closes.
- Translation domain: **`cling`** (the component's own `languages/`).
- Guide: `data/docu/programming_guide/cling_guide_{en,pl}.md`.
- Tests: `tests/test_cling.py` (run it directly; 320 tests). Nothing in them
  opens a window, plays a sound, speaks or reaches the network - the score
  publisher is stubbed for the whole file, because a game records a score at the
  end of every run and a suite that left that alone would sign in to a real
  server once per test. The engines are given a clock the test moves by hand, so
  a whole game is played through in a millisecond; that is why an engine never
  reads the clock and never touches wx.
- **And a sweep that really plays them.** A test suite proves the parts; what
  proves the whole is a harness that opens each of the 17 emulated
  applications in turn, waits for it to settle, presses Alt for its menu,
  walks it, starts what it finds and plays for a while - then reports the
  frames, the lines spoken, the sounds heard and anything the application
  stopped on. Every fault in this section was found that way and by nothing
  else: they all reach their menu on the first run, and every one of them
  needed playing before it went wrong. All 17 come back clean.

### The Elten API bridge: EltenLink's applications, running inside Titan

`data/components/elten_bridge/`. EltenLink is a social network for blind
people with a desktop client of its own, and applications are written FOR
that client - games, a file manager, a media catalogue, a podcast player -
each shipped as one signed `.eltenapp`. They are **Ruby**, and they expect a
platform underneath them that speaks, plays sounds, draws lists and forms,
keeps their files and translates their strings. This is that platform.

**This component is GPL-3.0** (`data/components/elten_bridge/LICENSE`) and
the rest of Titan is not. That is deliberate: Elten 3 is GPL-3.0, the bridge
is built against its documented API and shares its terms, and keeping the
boundary at one component is what keeps the question answerable.

- **The applications are found where Elten put them.** The user installs
  through Elten - its repository, its updates, its account, none of which is
  Titan's to re-do - and runs here. `%APPDATA%/elten/apps/src/*.eltenapp` is
  read exactly as Elten leaves it (one level into a folder as well, which is
  where an application that ships a readme beside itself lives), so an
  application installed five minutes ago is in the list when the window is
  next opened. Nothing is imported and nothing is copied. Titan's own
  `data/eltenapps/` and the component's `apps/` are looked in FIRST, which is
  what makes the user's own installation win a name collision.
- **Their saved games are the same files.** `data_path` is Elten's own
  `apps/data/<app>/`. Somebody who plays in Elten and then opens the same
  application here finds their game where they left it; a bridge that kept a
  second copy would lose whichever half was written last.
- **The list is called "Aplikacje Elten API"**, in the main window beside
  applications and games, in the Components menu, and as four actions
  (`list_applications`, `details`, `run`, `status`).

#### `.eltenapp`, read from the bytes

The container is not documented anywhere; it was worked out here by reading
one. `src/scripts` has no packer for it - Titan only ever READS these.

    "EltenPKSignature" u8 major u8 minor u32 cert_len u32 sig_len
    <DER X.509 certificate>          issuer: Elten / Program Signing
    <RSA signature>
    "Elten3AppPackage" u32 manifest_len  <zstd: the manifest, as JSON>
    records: u8 kind
      1 source     u16 namelen, name, u32 len, zstd
      2 asset      u16 namelen, name, u32 len, THE BYTES AS THEY ARE
      3 catalogue  2 bytes of language code, u32 len, zstd -> a gettext .mo

Three things about it are each a way to get it wrong:

- **An asset is not compressed.** Every asset in every application installed
  here is an `.ogg` or an `.mp3` - already compressed - so the builder stores
  them whole. A reader that runs zstd over every record parses the first few
  source files and throws on the first sound: four of the eleven applications
  came back with **zero files in them** before this was understood.
- **A catalogue's name is two bytes with no length in front of it**, and what
  is inside is a GNU gettext `.mo` - a format Titan already speaks, so `_()`
  is one lookup and nothing is parsed in Ruby.
- **The signature is a signature, not encryption.** Nothing is concealed. The
  certificate is in front of the payload so a reader can say who built the
  package; Elten's key is not public, so the bridge can verify and never
  mint, which is the right way round. An **unsigned** package still opens:
  Elten's own builder makes them (`--unsigned`), the user may well be the
  author, and refusing over a signature Titan was never going to trust would
  be theatre.

#### The bridge is a process, and that is the first half of "safe"

The application runs in a Ruby process of its own; everything it asks the
platform for arrives as one line of JSON on stdout, and events go back on
stdin. An application that loops for ever, exhausts its stack or segfaults a
gem takes down a subprocess, not Titan - and closing the window kills it,
which is a guarantee no in-process interpreter can make.

- **stdout belongs to the protocol and nothing else.** An application WILL
  `puts` - Elten's own do it constantly - and one stray line corrupts the
  stream and takes the application down with a parse error that reads like a
  Titan bug. So the real stdout is taken away at boot, kept privately, and
  `$stdout` is pointed at stderr, where Titan collects it as the log.
- **The dispatch table IS the security boundary** (`eltenkit/bridge.py`'s
  `OPERATIONS`). An operation exists or it does not: there is no way for an
  application to name a Python attribute, a module, a file outside its roots
  or a method nobody wrote down. Every call is answered **exactly once**,
  including the ones that raise and the ones that do not exist - an
  application written against a newer Elten finds out instead of hanging on a
  reply that is never coming.
- **Three roots and no way out of them** (`host.Paths`). `asset` is the
  unpacked package, `data` is Elten's own, `cache` is losable. `resolve`
  refuses anything that leaves its root **after `realpath`, not before**,
  because `..` is only the obvious way out: a symbolic link, a Windows
  junction or a name that normalises to something else all end up somewhere
  the application did not name, and checking the string it was given passes
  every one of them. A name with `..` in it is not written on extraction
  either.
- **A handle is a number in a table this side owns.** An invented one
  answers false; there is one table per running application, so one cannot
  reach another's sounds. Every list is bounded, every string that reaches a
  widget goes through `_text`/`_label`, and a line longer than `MAX_LINE`
  ends the application rather than making Titan buffer without bound.

#### The interface is Titan's, the voice is Titan's, the mixer is Titan's

Elten has no graphical interface at all - it is entirely self-voicing, a
single-threaded polling loop that reads the keyboard and speaks. That is a
real design and not Titan's, so the three edges are swapped:

- **UI**: an application's `ListBox`, `EditBox`, `Button`, `CheckBox` and
  `Form` are real wx widgets in a real Titan window (`eltenkit/ui.py`), which
  a screen reader already knows how to read. This is the part that matters
  most for "will an application work": the installed ones build their own
  screens out of these, 138 call sites across every one of them, and so will
  anything written later. `Form#wait` blocks the Ruby caller exactly as
  Elten's does; what fills the time is one event at a time off the bridge
  instead of a poll per frame, dispatched to whichever control it named.
- **Speech**: `stereo_speech.speak_stereo` - the user's engine, their rate,
  positioned - falling back to the messenger, which is `accessible_output3`
  and therefore their screen reader when one is running. A user who reads
  this desktop with NVDA hears an Elten application through NVDA, with
  nothing to configure.
- **Sound**: Titan's mixer, with the theme volume and the stereo-or-HRTF
  preference, held sounds and a fire-and-forget pool with a voice ceiling
  (a game that plays a click per keypress asks for thirty a second on a held
  arrow, and a mixer given all of them runs out of channels and goes silent).

**`alert` is speech, not a dialog**, and that is the correction worth
remembering. Elten's own is `alert(text, wait=true)` which calls `speak`;
Solitaire calls `alert(position_label, false)` after **every arrow key** to
say where the cursor is. Modelled as a message box - which is what guessing
from call sites produced - it would put a modal window on the screen on every
key press and make the board unplayable. The signatures here come from
Elten's own `src/ui/dialogs.rb` and `src/eapi/speech.rb`, not from what the
call sites looked like they meant.

#### The rest of the API, and what each installed application needed

All eleven installed applications start and run. Getting from four to eleven
was not one big piece of work but eleven small named ones, each found by
running the real application and reading what it stopped on - which is the
only way this can be done, because the API is 130 KB of `program.rb` plus
180 KB of controls and no summary of it is trustworthy.

- **`Menu`** (`skeet`) - `Menu.new(header, :returning)`, `option(label) {}`,
  `open`. The `:returning` type is the whole behaviour and it is Elten's own
  `close if @type != :returning`: an option runs and the menu **comes back**,
  and only `menu.close` inside one ends it. That is what "opens the way Elten
  opens them" means concretely.
- **`TableBox`** (`klangoarchive`) - a list with columns, so a row reads as
  "group, forums, threads, posts". A `wx.ListCtrl` in report mode, which is
  what a screen reader announces column by column.
- **`FilesTree`** (`filemanager`, `youtube`) - answered with the PLATFORM's
  own file and folder picker rather than a tree of Titan's, because somebody
  choosing where to save a download should get the dialog they already know,
  with their recent places in it.
- **`display_text`** (`solitaire` and most others) - a page to READ: help,
  rules, a changelog. A read-only `wx.TextCtrl` and deliberately not a
  message box, so the reader's own cursor, say-all and Ctrl+C work on it.
- **`MediaFinders` / `MediaEncoders`** (`youtube`, `ffmpeg`) - these two
  applications are nothing BUT a registration: ffmpeg registers five audio
  encoders and returns, youtube registers a finder and an extractor. The
  registries are real, because an application that registers into nothing
  has done nothing.
- **`ChildProc`** (`youtube`, `ffmpeg`) - running `yt-dlp`, `deno`,
  `ffmpeg.exe`. Worth being plain about: an `.eltenapp` is Ruby in a real
  interpreter with the user's privileges and can already spawn a process by
  itself, so this is not a hole being opened - it is Elten's own interface
  onto something the process can do anyway, and withholding it would only
  break the applications that ask politely.
- **`server_app` / `leaderboard` / `server_table`** (`skeet`,
  `audiomemory`, `MileByMile`) - declared at CLASS level, so an application
  that calls one will not even load without it. Backed by a real table in the
  application's own `data_path`: a game's high scores work, survive restarts
  and are shared with Elten's copy, but they are this machine's scores.
  `available?` answers honestly, which is the contract Elten's own
  `Leaderboard` documents for a server it cannot reach.
- **`EltenLink.*`** (`mcp`, the media catalogue) - **not stubbed**: Titan is
  already signed in to EltenLink through Titan IM, so this uses
  `src/eltenlink_client/` with the session the user already has. Three rules
  make that safe to hand somebody else's code: the application never sees a
  credential, the reachable calls are an explicit table (`eltenlink.py`'s
  `CALLS`) and never `getattr` on a name the application supplied, and
  **nothing that publishes is in it** - an `.eltenapp` cannot post to
  somebody's forum in their name because it was opened. What is not in the
  table raises `EltenLink::Error`, which is what these applications already
  rescue, 24 times over.

Three of the fixes were general rather than per-application, and those are
the ones worth remembering:

- **Only openable applications are listed.** `ffmpeg` and `mcp` declare
  `menu: {hidden: true}` in their manifests - they are plug-ins that give
  every OTHER application something and Elten does not put them in its menu.
  Listing them offers the user a row that opens, works for a fraction of a
  second and closes, which reads as an application that is broken.
- **A control shown on its own has to show itself.** In Elten there is one
  screen and building a control puts it on it. Here a control usually
  arrives inside a `Form` - but the file manager builds a `FilesTree`, shows
  it, and drives it from a `Runner` with no form anywhere, so it came up
  running and completely invisible. A control with no form now makes itself
  one the first time `update` asks it to be visible.
- **Either loop may be the one running.** There are two event loops in this
  API, `Form#wait` and `Runner#run`, and a click can arrive while either is
  in charge - the file manager's tree proves it. So an open form is in a
  registry (`EltenForms`) and both loops route control events through it,
  rather than each loop knowing only its own controls.

And two bugs that were mine, both worth keeping in mind because neither
looked like a bug from the outside: overriding **`Class#name`** to answer the
application's display name made every error message name a class that does
not exist (`undefined method for class Katalog mediów`), and building the
lifetime registry in `Program#initialize` meant an application that defines
its own `initialize` without `super` ran correctly and then died on
`undefined method 'close_all' for nil` on the way out. Anything the platform
needs to have must be able to make itself.

#### Playing them, not just starting them

"It started" is not "it works". A second sweep answers each application's
screens - picks an option, presses a button, activates a row - and walks it,
which is the only thing that finds the faults below. All nine openable
applications now run with no errors; `ffmpeg` and `mcp` finish at once
because they are plug-ins with no screen, which is what they are for.

- **The interface sounds are Titan's** (`eltenkit/cues.py`). Moving onto a
  row, choosing it, a branch opening, the end of a list, a dialog: Elten
  names each and Titan already has a sound for it, so `play_sound` maps
  Elten's name onto the user's own theme. Only the PLATFORM's cues - a card
  being dealt or a clay pigeon is the application, not the interface, and
  falls through to the package's own `Audio/` untouched, so a mapping can
  replace a sound and never lose one. A test asserts every mapping names a
  file the default theme really has, because a mapping to a missing file is
  silence.
- **The windows wear the skin.** Every Titan skin carries `icons/*.png`, and
  an Elten application's screen is a Titan window: the frame takes the
  skin's colours and its window icon, a list and a button are passed through
  `apply_to_listbox` / `apply_to_button`, and a button gets the picture its
  own label suggests - matched on what it SAYS, in the user's language as
  well as English, since that is what the label is.
- **`Tasks.run` yields TWO values.** Elten's shape is
  `Tasks.run(label) { |progress, token| }` and applications hand that token
  straight down into their own fetching code. Yielding only the progress
  made every one of those calls pass nil and stop on `raise_if_cancelled!`
  for nil. `CancellationToken#sleep` is PUBLIC for the same reason:
  applications call it with an explicit receiver, and inheriting the private
  `Kernel#sleep` answers `private method 'sleep' called for ...`.
- **A keyword this build does not act on must still be accepted.**
  `Runner.new(frame_interval:)`, `on_action(..., phase:, cooldown:,
  initially_blocked_for:)` - refusing one is refusing an application for
  asking precisely. `cooldown:` also takes an already-built `Cooldown`,
  which is what Skeet passes.
- **A control answers a property it does not act on.** Elten's controls
  carry a long tail about how much they say of themselves - `silent=`,
  `speech=`, `autosayoption=`, `border_sound=`. On Titan's side that is the
  screen reader's business, so they are remembered and answered rather than
  acted on. Answering is the point: stopping an application over a property
  about announcements is the worst possible trade.
- **A board's events carry where the cursor is.** AudioMemory's `GridBox`
  binds `:move` and reads `pos[0]`/`pos[1]` off it, so a control says what
  its events are CALLED (`event_name`) and what they CARRY (`event_args`) -
  a list's `changed` is a `changed`, a board's is a `move` with `[x, y]`.

Two more of mine, both found by running Titan rather than the bridge:
**`_on_view_activate` was reading its argument as an index** and Titan's view
system calls it with a `wx.KeyEvent`, so opening anything raised
`'<=' not supported between instances of 'int' and 'KeyEvent'`, which the GUI
swallowed - nothing opened and nothing said why. What is selected is a
question for the list, and the row now carries the application itself as
client data rather than being matched by position. And **`TitanApp` IS a
`wx.Frame`** - it does not have a `.frame` - so asking for one raised inside
the same handler.

#### An application is constructed with NO arguments

`klass.new(manifest)` looked harmless and was the worst bug in the bridge.
An Elten application's `initialize` is its OWN - the file manager's is
`initialize(startpath = false, mode: :files)` - and Elten constructs it with
nothing, so `startpath` is empty and it opens on the user's home folder.
Handing it the manifest as its first positional argument made `startpath` a
JSON document: the file manager opened on a folder called
`{"id" => "8c8d86ce-...` which does not exist, and showed one row saying
"Up one level". **Every application that defines its own `initialize` was
being given the same thing**, and the earlier `close_all for nil` crash was
the same cause wearing a different hat.

So `Program` has no `initialize` at all, the manifest lives on the class, and
everything the base class needs makes itself lazily. Anything the platform
needs to have must be able to make itself, because the application owns its
own constructor.

#### A game needs a window, because a window is what owns the keyboard

Purrposterous drives a `Runner` and nothing else - hold Left and Right to
move, Space to feed - and a `Runner` with no form had no window at all, so
not one key ever reached it. The game ran, ticked and could not be played;
which is also why it was silent, because nothing in it ever happened.

`Runner#run` now asks for a window (`open_keyboard`), and Titan gives it the
equivalent of Elten's own screen: a real Titan window whose job is to hold
the focus and report keys. It is deliberately almost empty - a game is heard,
not read - but it is a real window with a real accessible name, and the
control in it is what a reader lands on. Losing the focus releases every held
key, or a game walks into a wall for ever because Left never came up.

**A letter is two names.** Elten writes `hold: [:key_left, :a]`, so `a` and
`key_a` are the same key; `key_held?` answers about both, or half a game's
controls do nothing.

#### Everything is named for a screen reader

`SetName` alone is wx's own name and never reaches a reader for a native
control - a list view answers with its own IAccessible, whose name comes from
window text these controls have none of. Titan already learned this building
the shell, and `a11y.name_control` is the one way in: it names the control
for wx AND for MSAA. Every list, table, field and game surface goes through
it. Without it an Elten application's list is an unnamed box, which for the
people these applications are written for is the whole interface missing.

The file tree puts the folder it is showing in its own header, so the name a
reader announces follows where the user is, and a folder is announced as one
("Documents, folder") rather than being a name in a list of names.

#### `FilesTree` is a list of a folder, not a button

The file manager's whole screen is one, so it cannot be a button that opens a
picker. Ruby reads the directory itself - it has `Dir` and `File`, and the
application expects exactly their answers (`filetype` is decided by
extension, `selected` is a real path) - and Titan draws the list. One trap:
the `rescue` must be **per entry**. A Windows home directory is full of
things that raise when asked about - the "Application Data" junction loops,
OneDrive placeholders are not there until fetched - and one rescue around the
whole loop means the FIRST such entry ends the listing.

#### Sound: the keywords are not optional

`create_sound_from_asset(name, sample:, loop:, effect_buffer:, ...)` -
Purrposterous asks for its background music with `loop: true` and wraps the
call in `rescue Exception`, so a signature that did not take `loop:` did not
raise where anybody could see it: the game logged one line and played in
complete silence. A keyword this bridge cannot act on (`effect_buffer` is
Elten's own DSP) is ACCEPTED and ignored, which is the difference between a
game with no reverb and a game with no sound. `loop` belongs to the SOUND, so
an application sets it up once and then just calls `play`.

#### The libraries Elten's applications use

Installed into the component's own Ruby, from Elten's `Gemfile`: **nokogiri,
sqlite3, rubyzip, base62, http-2**, on top of what CRuby 4.0.6 already
carries (json, openssl, net-http, fiddle, bigdecimal, ostruct, win32ole,
digest, uri, socket). They live in `ruby/lib/ruby/gems/4.0.0/`, so the
component stays portable.

Two are NOT working yet and are the honest exceptions: `ruby-xz` and
`zstd-ruby` are native-extension gems whose compiled artefacts did not
survive being moved into the component (`gem install --install-dir` cannot
write to the OneDrive path, so they are installed to the user's gem
directory and copied). Neither is reached by any installed application -
Titan reads `.eltenapp` zstd in Python - but an application that needs them
will find them missing.

#### It has to sound and behave like Elten, because it is Elten

"It runs" is not "it works", and neither is "it is on the screen". This
round was driven by using the applications - inside a real Titan, with the
real mixer and the real speech - and every one of these was found that way.

- **Moving through a list made no sound at all.** Elten's controls are
  self-voicing and play their own cue as the cursor moves; the controls
  here are real wx controls that move natively, so nothing in Ruby runs on
  an arrow key and the whole interface was silent - the one place on this
  desktop where a list did not answer. The WIDGETS cue now (`ui._cue_for`,
  `_spread`), through the user's own theme and panned by how far down the
  list the cursor is: focus, select, end of list, a tick box, a button, a
  menu opening and closing, a dialog. Measured inside a real Titan:
  `core/FOCUS.ogg` at 0.33, 0.0, 0.33, 0.67, 1.0 across a menu, then
  `ui/endoflist.ogg` at the end and `core/SELECT.ogg` on the choice.
  - **A control that says it is silent is silent.** AudioMemory sets
    `grid.silent = true` because the game already sounds every square, and
    cueing over that is two sounds for one move. `silent`, `border_sound`,
    `speech` and `quiet` travel with the control - in its spec and again
    once the form is really open (`announce_sound_properties`) - and
    `set_control` is the ONE place that reads them, because every kind of
    control has the question and none of them should each answer it.
  - **A file's KIND is a sound.** Elten's file manager plays one as the
    cursor moves and it is not decoration: it is how somebody who cannot
    see the folder knows a folder from a song from a document before the
    name has been read. Five of Titan's own, panned.
- **The keyboard was on the window, not on anything in it.** A `wx.Dialog`
  focuses its first control by itself and a `wx.Frame` does not, so a form
  built here left the arrows going to a panel - which from the outside is
  exactly "down and right do not work": the board was on the screen,
  correct, named, and could not be moved about. A form focuses its first
  control that will take it, and every widget that holds its control
  inside a panel focuses the CONTROL (a `wx.grid.Grid` is a wrapper around
  the window that actually has the keys).
  - **And a modal dialog never gave it back.** Windows returns the
    keyboard to the frame when a dialog closes, not to the control inside
    it, so after any menu, confirmation or page of text the arrows went
    nowhere again. Everything modal goes through `WxUI._modal`, which
    remembers and restores, falling back to the open form and then to the
    keyboard surface, so there is always somewhere for the next key.
- **A menu has no Ok and no Cancel**, because Elten's has not. Enter
  chooses and Escape leaves - `wx.Dialog` answers both itself - and two
  buttons underneath are two more things to tab past on the way to
  nowhere. `_ChoiceDialog` is Titan's own for this reason and one other:
  `wx.SingleChoiceDialog`'s list is silent, and that dialog is the front
  screen of nearly every application.
- **A game with no form got no keys.** Purrposterous is a `Runner` and
  nothing else - hold Left and Right, Space to feed - with no control
  anywhere in it, so there was no window to have the keyboard and not one
  key reached it: a game that made noises and had no game in it.
  `open_keyboard` existed and nothing called it; the FRAME calls it now
  (`EltenLoop.ensure_somewhere_for_keys`), because every loop goes through
  a frame, and only when no form is open.
  - **A form's keys have to reach a `Runner` too.** The file manager is a
    `FilesTree` driven from one, and a Runner asks `key_pressed?`, which
    is filled by the key stream and not by a control's events. A form
    reports both now - the control first, so a list still owns its own Up
    and Down.
- **The file manager is Elten's, key for key**: Right goes into a folder,
  Left comes back out, Space plays an audio file or READS a text one,
  Shift+Left/Right seek in what is playing and Shift+Space pauses it. Copy,
  paste, rename and delete are real, and the last two ask first - a real
  change to somebody's disk made by an application they merely opened goes
  through them.
- **`bind_context` reached nothing.** An application puts commands on a
  control with it - the media catalogue's "add to favourites", the file
  manager's whole file menu - and the block was recorded and never called,
  so those commands could be reached by nothing at all. It is a real
  Windows menu now, opened by the Applications key, Shift+F10, the right
  mouse button and Alt, because a menu is a thing Windows itself knows
  about: a reader announces it as a menu, counts it, follows the arrows
  into a submenu and closes on Escape, with none of that written here.
  Elten's three (`bind_filesmenu`, `bind_createmenu`, `bind_menu`) keep
  their own headings rather than being poured into one list.
- **A board is a board and moves like one.** `wx.grid.Grid` reports a real
  table to MSAA - a row, a column and a cell, so a reader says all three,
  where a list box said "item 7 of 16" for a square that is row 2, column
  3. Verified live: up is up, down is down, left is left, right is right;
  an arrow into the wall reports a `:border` carrying its direction (which
  is what AudioMemory reads off `pos[2]`); Enter AND Space choose, because
  Elten binds both.
- **`ChoiceListBox` rows could be read and never changed.** MileByMile's
  whole setup screen is three of them - card set, distance, decks - and
  rendered as a list a row was just a row, so the form could only ever
  start the game it opened with. Each row is a real `wx.Choice` now, the
  control Titan's own settings window uses for exactly this: the arrows
  change the value and the reader announces the new one itself. A row's
  third element is which choice it STARTS on, and dropping it silently
  reset every setting the player had made last time.
- **`readurl` answers through a BLOCK, on a thread.** Mine fetched the page
  synchronously and returned the body, which looks correct, runs, fetches
  the right page and never calls the block: the media catalogue pushes into
  a queue from inside it and polls that queue, so it said "Loading..." and
  stayed there for ever - every screen behind the first was unreachable. A
  failure calls the block with `:error`, because a block that is never
  called is a hang, which is the worst way to report that a page could not
  be fetched.
- **`input_text` is Elten's signature or it is nothing.** Elten's
  `display_text` is BUILT on it (read-only plus multiline), so an
  application asking to SHOW a page arrives there; a signature taking
  `default:`/`multiline:` answered `unknown keywords: :escapable, :text`
  and ended the application on the screen it was trying to put up.
  `set_text`'s second argument is positional too.
- **`Player` is a radio station or a podcast episode, on a form.** The
  media catalogue is nothing else. Elten plays a stream with the BASS
  stack it ships; Titan's mixer plays files, so what sits between a URL and
  this desktop's sound is the decoding - `host.Stream` opens the container
  with PyAV, resamples to whatever format the LIVE mixer is in, and hands
  Titan's mixer a second at a time on a channel of its own. Doing it that
  way rather than opening an output device of its own is the point: the
  user's theme volume, their output device and Titan's own stop all apply,
  and a radio station is not the one thing on this desktop that is louder
  than everything else. Elten's keys exactly - Left and Right five
  seconds, Up and Down the volume, Home and End the ends, Space plays and
  pauses. What is deliberately NOT there is Elten's tempo and pitch: Titan's
  mixer plays a sound, it does not resample one, and a key that pretended
  to change the speed would be worse than a key that is not there.
  - `sound` answers an object with Elten's own `opened?`, `position`,
    `length` and `closed?`, because the catalogue asks `@player.sound&.
    opened?` before it shows a player at all - a nil `sound` meant every
    station reported "the station could not be played".
  - A live stream has no length and cannot be sought; a file has both.
    `duration` answering None is what an application reads to tell them
    apart, and it is answered honestly rather than guessed.
- **A place is `[x, y, z]` and crosses the wire unconverted.** Turning it
  into a pan in Ruby threw the height and the distance away before anything
  could use them, and divided x by a fixed two - so Skeet, which hands over
  a pan it has already worked out, could only ever reach half the stereo
  image. `host._place` does it on Titan's side, which is the only side that
  knows what Titan's mixer is: an angle, an elevation, and a distance gain.
- **A sound that has started can still be moved, paused and re-gained.**
  Skeet's clay target is thrown and then told where it has got to on every
  frame, and every one of those calls raised `NoMethodError` on a `closed?`
  that was not there - caught by the game's own `rescue Exception` and
  answered with `stop_flight`. The disc went silent one frame after every
  throw, for the whole game. `EltenSound` carries Elten's spatial surface
  in full (`spatial_position`, `spatial_position_slide`, `closed?`,
  `pause`, `effects_latency_ms`, `effect_playback_seconds_at`) because an
  application ASKS before it uses it, and a method that is merely missing
  does not degrade - it raises.
- **`Session` and `Configuration` are read directly by applications.** The
  ELTEN Game Room asks `Session.name` thirty times to know whose table it
  is looking at, and a constant that is not there is a `NameError` before
  anything is drawn. `Session` answers with the EltenLink account Titan
  already has, from the encrypted `titan.IM` and without reaching the
  network - `whoami` reads the saved NAME, never a token, so it works
  with no live session at all and costs nothing when it is asked thirty
  times. `Configuration` answers Titan's own preference where Titan has
  one and nil where it has not, rather than raising: an application
  reading a setting it will then default is doing the right thing.
- **`Form#show` means "unhide that control".** Elten's pair is
  `hide(index_or_field)` / `show(index_or_field)`, and the Game Room hides
  a button rather than rebuilding the screen every time what you can do
  with the row changes. Titan's own "put this window up" is `present`, and
  a hidden control is really gone from the screen and out of the tab order
  - a hidden button that can still be tabbed to is a control that answers
  nothing.
- **An application may reach its own server storage two ways.**
  `Program.server_table` was backed already; `EltenLink::Apps.table(client,
  uuid, name)` was not there at all, and the Game Room uses that one - so
  it came up saying "the operation failed" before it had listed anything.
  Both end at the same real table in the application's own data folder,
  which is the honest limit: an application's data survives restarts and
  is shared with nothing. A lobby works; the other players are not in it.
  The alternative - publishing to somebody's EltenLink account because
  they opened an application - is the one thing this bridge does not do.
- **`loop_update` is the frame, defined once, on Kernel.** A zero-arity
  stub of it inside `EltenAPI` shadowed the real one for every class that
  includes it - which is the Runner, every Program and every control - so a
  vendored Runner's frame did nothing and anything asking for a frame of a
  stated length got `wrong number of arguments (given 1, expected 0)`.

#### The whole API, read out of Elten's own source

The API was written from what the installed applications call, which finds
everything they use and nothing they do not - and "everything a NEW Elten
application uses" is a different set. So it is now written against Elten's
own source: `https://github.com/dawidpieper/elten3` (branch **main**;
`Elten-Client` is Elten 2 and the wrong repository). The same code is
embedded in the installed client as one zstd frame inside `elten-x64.exe`,
which is how to check what the user is actually running against the repo.

`tests/test_elten_bridge.py` carries the method lists read out of
`src/eapi/program.rb`, and fails if one is missing - because of what a
missing method DOES in somebody else's program: `NoMethodError`, usually
inside their own `rescue Exception`, where it becomes a feature quietly not
working rather than an error anybody sees.

- **A change to a window never reached it.** `control_set` and `form_close`
  are sent with `notify` - an application changing its own screen is not
  something it waits for - and a message with no id is looked up in
  `NOTIFICATIONS` and nowhere else. They were only in `OPERATIONS`, so every
  one of them was read off the wire and dropped on the floor. That is
  everything an application does to a window it has already put up: a list
  whose rows are replaced, a board dealt again, a header that should follow
  the folder, a button relabelled mid-form. The file manager listed its
  first folder and then showed that folder for ever whatever the user
  pressed, and AudioMemory's board stayed the empty one it was built with.
  A test now reads every `EltenBridge.notify` out of the Ruby and fails if
  one is answered by nobody.
- **A block is handed ONE argument: the list.** Elten's `FormBase#trigger`
  ends in `e[4].call(a)` where `a` is the whole parameter array, and Ruby's
  own auto-splat is what then makes both shapes an application writes work -
  `on(:move) { |pos| pos[0] }` gets the pair, `on(:action) { |name, source,
  x, y| }` gets them apart. Splatting instead gave the first shape the first
  number on its own, and `pos[0]` on an Integer is a BIT of it: AudioMemory
  read a column out of a number that was already the column.
- **A key is also its NUMBER.** Elten's own code asks `key_pressed?(0x09)`
  for Tab and `key_held?(0x10)` for Shift, and so do applications - the file
  manager's Ctrl+D is `runner.on_key(0x44)` guarded by `key_held?(0x11)`.
  Those are Windows virtual key codes, a third spelling of the same key, and
  comparing them as strings against a table of names matched nothing: every
  shortcut written that way did nothing at all, which is most of them,
  because a control key has no letter to be written as.
- **A change made before the window exists is still a change.** `to_spec`
  was the hash the constructor made, so anything an application did between
  building a control and showing it was lost - and AudioMemory does exactly
  that, dealing the board and only then calling `grid.focus`. Every change
  is folded into the spec now, so a window is built from what the control IS
  rather than from what it was.
- **The two flag sets were wrong, and wrong in the way that hurts.**
  `ListBox::Flags::AnyDir` was 1 and `MultiSelection` IS 1, so every
  application asking for a list of things to tick got one that could not be
  ticked. `EditBox::Flags` had MultiLine and ReadOnly the other way round,
  so a box to write a message in came up read-only and one line, and a page
  to READ came up editable - `display_text` worked only because Elten builds
  it out of both and the two wrongs added to the same number.
- **A multi-selection list is Titan's own tick list** (`src/ui/check_list.py`),
  because that is a native list-view check box MSAA reports as a check box
  with a state, where `wx.CheckListBox` is owner-drawn and reports a list
  item that says nothing about whether it is ticked.
- **Speech that fails must not end the application.** `alert` is called from
  the middle of a game, and a `RemoteError` there travelled all the way out
  of `program_main`: a voice that hiccuped closed the game. The line is
  lost, which is bad; the game is not, which is what matters. Same for a
  sound that will not play.

#### A board and a file tree are driven by the FRAME

Two controls are not like the others: an application creates them and then
drives them from its own loop - `runner.on_tick { grid.update }`,
`runner.on_tick { @tree.update }` - and expects `update` to be where the
cursor moves, where the edge is reported and where a bound key fires. A
`wx.grid.Grid` moving its own cursor as well is a board that jumps two
squares per key, so every key those two would act on is handed to the
control in Ruby by name and comes back as a position to show. Titan still
draws them and still announces them - the reader says the cell as the cursor
lands - and everything an application asked for happens where it asked for
it. `EltenControl#frame_driven?` says which ones need this, and `Form#wait`
updates them on every frame the way Elten's own form does.

- **`GridBox` is Elten's, method for method** (`ui/controls/grid_box.rb`):
  `labels`, `set_cell`, `set_cells`, `replace_cells(resize:)`,
  `update_cells`, `cell_label`, `coordinate_label` ("B3"), `resize`,
  `move_by`, `border_direction`, `lpos`, `key_processed`, and
  `bind_action(:flag, key: [:f, :shift])` with `:action` carrying the name,
  the source and the square - without which a game whose interaction is
  "press F to flag this square" could not be played at all. `value` is
  `[x, y]`, which is where the cursor is and not what is under it.
  - **A board that grows really grows.** AudioMemory deals a bigger board
    every round and a `wx.grid.Grid` keeps whatever shape it was created
    with, so the extra squares existed in Ruby and nowhere the player could
    reach. `_reshape` appends and deletes rows and columns.
  - **`grid.x = 0` moves the cursor on the screen.** They were a plain
    `attr_accessor`, so AudioMemory's reset between rounds moved nothing and
    Ruby and the window disagreed about where the cursor was.
- **`FilesTree` is Elten's file manager, key for key** (`ui/controls/
  files_tree.rb`). **An empty path is the top of the MACHINE**, not the home
  folder: every drive (`EltenSystemHelpers.logical_drives`, asked of
  Windows through `GetLogicalDriveStringsW`) and then Desktop, Documents and
  Music. Answering it with the home folder is a file manager that can never
  reach another drive, because Left from a drive root had nowhere to go.
  Right goes in, Left comes back out (to the drive list from a root), Space
  previews an audio file or reads a text one, and Shift with the arrows
  drives whatever is being previewed. A file-type sound is played once per
  move, which is how somebody who cannot see the folder knows a folder from
  a song before the name has been read.
  - **It carries THREE menus, not one.** `bind_filesmenu`, `bind_editmenu`
    and `bind_createmenu` are separate bindings and become separate
    submenus - File, Edit and Create - each with the tree's own commands
    already in it. Pouring them into one context menu put "New text file"
    next to "Paste" under a heading that said File.
  - **A double click is Enter.** Elten has no mouse at all, so there is
    nothing to copy - but a file manager on this desktop that can be walked
    with the mouse and not opened with it is half a file manager. The key
    goes on the application's own stream (`EltenLoop.inject`), so whatever
    the application bound Enter to is what happens.
- **The row the user is on comes back.** What the user did to a widget was
  written into the control by a chain of `is_a?` tests, and what it did not
  test for was the file tree - it is not a `ListBox`, so a row selected with
  the arrows or the mouse never reached it and `@index` stayed at 0: the
  file manager renamed, deleted, played and opened whatever was at the TOP
  of the folder. Every control answers for itself now
  (`apply_wire_change`), so a new one cannot be forgotten.
- **A list owns its own movement, and that is more than Up and Down.** Home,
  End and the page keys were being taken from every `ListBox` and reported
  as control events, so a folder of three thousand files could only be
  walked one row at a time.

#### An application's own settings

`eapi/settings.rb` is Elten's `src/eapi/program_settings.rb` ported onto
this bridge: the same `Builder` (`boolean` / `integer` / `text` / `choice` /
`multi_choice` / `action`), the same `Store` (a `settings.json` in the
application's OWN data folder, so a setting made here is the setting Elten
reads and the other way round), and the same `Dialog` - a title, the fields,
then Apply, OK and Cancel with Apply saving without closing. What is
different is only what it is made of: every field is a real Titan control on
a real Titan form.

- **A Monitor, not a Mutex.** `transaction` holds the lock and the setters
  it calls go through `set`, which takes it again; Ruby's Mutex is not
  reentrant, so with one of those an Apply that saved anything at all
  deadlocked the application.
- **A choice's TYPE is its list of options**, which reads like a mistake and
  is Elten's own shape (`ListBox.new(setting.type, header: setting.label)`).
- `Program.show_settings` and the instance method both exist, because Elten
  defines both.
- **An extension's `tick` really ticks.** `extension(:name) { |service|
  service.tick(interval: 0.1) { ... } }` is the file manager's background
  playlist, and with nothing calling it the playlist advanced to its next
  track and stopped there for good. One frame hook per application
  (`EltenLoop.every_frame`), started when the first extension is declared
  and stopped on the way out, where the file manager closes its playlist
  down. `service.settings` feeds the same collector as `show_settings`.
- **A name is a name in the application's own data folder.** The instance
  methods always resolved it that way; the CLASS-level `read_json` /
  `write_json` did not, so the file manager's `activate` - which reads its
  playlists before any instance exists - wrote beside Titan and read back
  from wherever Titan had been started.

#### The scores are on the server

`server_table` and `leaderboard` were a JSON file beside the application, so
a game's "Best scores" was a scoreboard with one player on it. They are rows
in a real table on EltenLink now, belonging to the application's own uuid
and written as whoever is signed in - `Programs::ServerTable`, over
`/api/v1/apps/<uuid>/tables/<name>/rows`, which is Elten's own `AppTable`.

- **The account comes from wherever the user already signed in.** Titan IM's
  EltenLink account first, and then **Elten's own installation**:
  `%APPDATA%/elten/login.dat` is Elten's own format and holds the account
  name and an auto-login key, and a user who has Elten installed and logged
  in should not have to sign in a second time to play their own games here.
  The key is DPAPI-protected, so it can be read back only by this Windows
  account on this machine - the same property Titan's own secret store
  relies on. A key protected with a PIN is deliberately NOT used: the PIN is
  not on the disk, and asking for one because a game wanted a scoreboard is
  not something to do unprompted. `eltenkit/elten_account.py`.
- **A session is asked for rather than borrowed.** Titan's own client talks
  to the legacy endpoint and the app tables are the v1 API; assuming one
  token serves both is the kind of assumption that works until it does not.
  `POST /api/v1/session` with the auto-login key, or with the password Titan
  IM saved, and a 401 is one retry with a fresh token rather than a game
  told its score could not be shared.
- **The local copy stays.** A score is written HERE first and
  unconditionally and shared afterwards, so a server that is not there, or a
  user who has not signed in, costs a sentence and never a score. Reading
  falls back the same way, so a scoreboard read offline is the player's own
  history rather than an error.
- **A PROTECTED table is refused, and that is correct.** A protected app
  table is signed with a launcher stamp - an HMAC whose key is compiled into
  Elten's official launcher binary (`launcher/src/stamp.cpp`, "the launcher
  was built without a private key"). It exists so that only the genuine
  Elten client can write those rows: it is an authenticity control on
  somebody else's server, the key is deliberately not public, and forging a
  stamp is exactly what it is there to stop. So an application whose tables
  are protected (AudioMemory, Skeet, Purrposterous, the Game Room) keeps its
  scores on this machine and says plainly why they are not shared, and the
  table remembers the refusal so the game stops offering. Everything
  unprotected - the media catalogue's favourites, read and write - works,
  and reading is not stamped at all.
- `EltenLink::Apps.table`, `.register`, `.update` and `.info` all end at the
  same place, because applications reach for their own data both ways.

- **A protected game gets a REAL, shared scoreboard - Titan's, on
  Titan-Net.** Titan does not mint the launcher stamp, so it cannot write
  to Elten's protected leaderboards - but "people can still play" is a fair
  point, and the honest answer is a scoreboard that is Titan's rather than a
  forged row on Elten's. When Elten refuses a table as protected, the score
  goes to a Titan-Net shared table (`eltenkit/titannet_scores.py`, slug
  `elten_apps`, keyed per game uuid + table), written as the Titan-Net
  account the user already has and read by every Titan player of that game -
  exactly the mechanism Cling's games use. The server registers the
  `elten_apps` extension slug like Cling's (`titan-net server/models.py`
  `BUILTIN_EXTENSIONS`), which the production server picks up on its next
  restart. `available?` stays true after a protected refusal because there
  is still the Titan-Net board to share to, so the game still offers; a
  local copy is kept underneath either way.

#### A window that a game can be played in twice

Purrposterous's second game could not be controlled at all. A `Runner` with
no form has no window, so the frame asks for one (`open_keyboard`) - and it
asked only when it believed the answer had changed. A modal dialog is what
makes it change: Windows gives the keyboard back to the FRAME when a dialog
closes, not to whatever was in it, and the menu between two games is a
modal. So every modal call invalidates that belief (`MODAL_OPS`), and
`open_keyboard` now reuses a surface that is still there rather than
rebuilding it - rebuilding would lose the focus and the title, and a game
between two rounds needs neither lost.

- **A key that is never released stays held for ever.** A form fed the key
  stream on the way down and nothing on the way up, so `key_held?` answered
  yes about a key the user let go of minutes ago - for a game, walking into
  a wall that is not there.
- **A key a control acted on still goes on the key stream.** A control event
  tells the CONTROL what was pressed; a `Runner` asks `key_pressed?`, which
  is a different question. The file manager is both at once - a `FilesTree`
  whose Right and Left are the control's, driven by a Runner whose Escape
  and Ctrl+O are the application's - so a key that reached one and not the
  other was half the program not answering.
- **A dead window is not somewhere to put the keyboard.** Asking a destroyed
  wx object anything raises, inside wx's own event loop where nothing
  catches it, so everything that remembers a window across a dialog asks
  `_alive` first.

#### The sound an application actually asks for

- **`basefrequency` is what a sound was sampled at**, and it is the number a
  game changes the pitch RELATIVE to: Purrposterous reads it when a cat is
  born and then pitches the meow up as the cat gets hungrier. Missing, it
  ended the game on the first cat - inside the game's own `rescue`, so what
  the user saw was a game that started and stopped. With it come
  `frequency`, `pitch`, `tempo`, `length`, `position`, `pause`, `resume`,
  `paused?`, `stopped?`, `opened?`, `status` and `wait`.
- **`sound_pool(max_voices:)` is a real pool.** It answered `self` - the
  Program - so `pool.play(sound)` reached a method of the application's that
  took no arguments, and every one-shot Purrposterous plays (a step, a jump,
  a wall) ended in `ArgumentError` inside its own rescue: a game that walked
  in silence. What a pool is FOR is the ceiling: a game that plays a click
  per keypress asks for thirty a second on a held arrow, and a mixer given
  all of them runs out of channels and goes quiet.
- **`read_url` is what an application calls before it has a screen.** The
  YouTube client asks for its update manifests from `activate`, and a
  missing one is `NoMethodError` at class level, before anything is on the
  screen to say so. `eapi/network.rb` is Elten's own `src/eapi/network.rb` -
  `read_url` (a Hash body is a multipart form, and the caller's `headers`
  hash is FILLED IN with the response's), `download_file`, `html_decode`,
  `html_encode`.

#### More real-window gaps: a button's Space, a process, a form's header

Found by using the applications, each one line and each an application that
stopped or a control that would not answer:

- **Space presses a focused button.** A wx button is activated by Space,
  but the form's own char hook was intercepting Space (a navigation key)
  and sending it to the application as a keystroke, so the button never
  fired: a screen of buttons could be reached and not pressed with the
  space bar. Space and Enter on a focused button now press it.
- **`ChildProc` speaks Elten's own method names.** The YouTube client's
  whole search loop is `process.running?` / `process.avail` /
  `process.avail_err` / `process.terminate`, and ours had `alive?` /
  `read` / `kill` - so every one of those was a `NoMethodError` and the
  search ended before yt-dlp had said a word. They are there now (verified
  by driving the real yt-dlp through the app's own read loop), and
  `avail`/`avail_err` report the bytes waiting so a poll never blocks.
- **`Form#header=`.** Elten's `FormBase` has `attr_accessor :header` and
  applications set it after building the form - the media catalogue's
  Options screen does `form.header = _("Options")`. Missing, it ended the
  application on the screen it was opening, which is what "I pick Options
  and the app closes" was.

#### The Game Room: FormTimer and the form's own timers

The Game Room refreshes its lobby with a repeating timer -
`form.add_timer(FormTimer.new(interval, repeat: true) { ... })` - and
neither `FormTimer` nor a real `add_timer` was here, so it stopped on an
uninitialized constant before its screen was up. `FormTimer` is Elten's own
(`ui/form.rb`): a one-shot or repeating timer a form ticks every frame.
`Form#add_timer` / `delete_timer` hold them and `Form#wait` ticks them
alongside the frame-driven controls. Also added the three Form methods the
Game Room calls that were missing - `wait_without_announcement` (its own
`wait`, since the marker is Titan's focus cue anyway), `keyboard_idle_frame?`
and `game_shortcut_keys`.

#### Every application's menu is flat - no menu-bar oddities

Elten's `context` takes a `submenu` flag: true wraps each binding under a
heading (which is what a menu BAR wants), false pours the options straight
in (which is what a context menu is). Titan opened the menu as a menu bar
for Alt and flat for the Applications key - and these applications have no
menu bar in Titan, so the menu-bar path only ever added an oddity. An
unnamed bound menu became a literal "Context menu" entry you had to open to
reach anything; the file tree became "<folder> - File tree". So
`open_context_menu` now builds FLAT whichever key opened it - Applications
key, Shift+F10, right mouse button, Alt all give the same clean menu, which
is what a menu is on this desktop. A control's own named menus stay distinct
where they are genuinely distinct (the file tree's File / Edit / Create, the
player's flat list); nothing wears a "Context menu" heading any more. Tests:
`EveryAppsMenuIsFlat`.

#### The player is Elten's player, keys and all - and a mouse too

Elten's `Player` (a radio station or a podcast episode - the media
catalogue's whole screen, and what the YouTube app plays through) is a
control you drive by ear, and every key it answers is here now, each doing
a thing Titan's mixer really carries out (`host.Stream`):

- **Space** plays and pauses; **Left/Right** seek five seconds; **Up/Down**
  are the volume; **Home/End** the ends; **Page Up/Down** step through the
  file's chapters.
- **Shift+Left/Right** is the pan and **Shift+Up/Down** the pitch;
  **Ctrl+Up/Down** is the tempo; **Backspace** puts volume, pan, pitch and
  tempo all back. Pitch and tempo are real: the decoded frames go through a
  small PyAV filter graph (`asetrate` for the pitch, chained `atempo` for
  the speed) before they reach the mixer, so "faster and higher" and
  "faster, same pitch" both actually happen - the earlier note that Titan
  could not resample is no longer true.
- The **context menu** is Elten's, flat (not wrapped in a submenu the way
  the file tree's is): Play/pause, the position, the duration, the track
  info read from the file's own tags, the chapters, Jump to position, and -
  for a URL - Save file, which downloads it to a folder the user picks.
- **The mouse is an equal**, which Elten (entirely by ear) has no
  equivalent of and this desktop should: a draggable **seek bar** that
  shows where the sound is and seeks where it is let go (never fighting the
  playback clock while it is held), a **volume bar**, **Play/Pause** and
  **Stop** buttons, and the whole player menu on a **right-click**.
- Tests: `test_the_player_keys_are_eltens`, `test_the_seek_bar_seeks_where_
  it_is_dragged`, `test_a_right_click_opens_the_player_menu` in the real-wx
  class fire real wx events at the real control; the Stream's own
  seek/volume/pan/pitch/tempo/reset are exercised against a real file.

#### Tested in the REAL window, not a double

The headless harness runs an application with a scripted stand-in for the
UI - no wx at all - which is exactly why it misses a class of bug: anything
that only happens in the real wx widgets. Two of those shipped and were
caught only by driving the genuine `WxUI`:

- **The board could not be moved because reporting an arrow key raised.**
  The grid reported `control=` (the Control modifier) and `send_event`
  already binds `control` (which control it is), so every arrow key threw
  `TypeError` inside the wx handler, where nothing catches it - AudioMemory
  put a board on the screen that answered no key at all. The modifier is
  `ctrl` now, and the Control MODIFIER is read from `ctrl` on the Ruby side
  too (it had been reading the routing index and thinking Control was
  always down).
- **Escape on a form-hosted control did the form's back and nothing else.**
  It sent the `escape` control event and returned WITHOUT putting
  `key_escape` on the key stream, so a `Runner` that binds Escape never
  heard it. AudioMemory shows its board on a form and asks "abort the
  game?" from `runner.on_key(:key_escape)`; Escape on the board did
  nothing, and the game could be left only by closing the window. Escape
  now goes to both, so the form backs out AND the runner's handler fires -
  and at a top-level menu Escape cancels the modal, which ends the
  application and closes the window, the way Elten leaves an app.

So the suite now drives the REAL widgets with REAL wx events - a grid arrow
and its choose key, a listbox move and its Space, a tick box, a button, and
Escape - against the REAL `send_event`, and asserts the application heard
what it should and that nothing raised. `EveryWidgetReallyBuilds` builds one
of each control for real (which is how `wx.TextValidator`, a class wxPython
does not wrap, was caught turning a settings form with a number in it into a
screen that would not open). Audio preview is verified end to end: the
`Player`'s stream opens a real file with PyAV, resamples to the live mixer's
format and plays it through Titan's own mixer - Space on a song in the file
manager really plays it.

#### Played, not just started

What proves the parts is the suite; what proves the whole is a harness that
opens each application with the UI replaced by a scripted double - no wx at
all, nothing drawn, nothing spoken - answers its menus and presses its keys,
and reports what it stopped on. Every fault in the four sections above was
found that way and by nothing else: they all reached their first screen, and
every one of them needed playing before it went wrong. All eleven installed
applications now open, run and stop cleanly, and AudioMemory, Purrposterous,
Skeet and the file manager have been played end to end.

#### The Ruby is carried

`ruby/` is CRuby 4.0.6 (RubyInstaller, 46 MB pruned of docs and headers,
`LICENSE.txt` kept), so the bridge works on a machine that has never had Ruby
and never had Elten. `ELTEN_BRIDGE_RUBY` points it at another interpreter,
and one on `PATH` is the last resort. `RUBYOPT` and `RUBYLIB` are cleared for
an application's process: whatever the machine's own Ruby wants loaded into
every interpreter is not something an Elten application asked for, and a `-r`
in there is code running inside somebody else's program.

- Tests: `tests/test_elten_bridge.py` (run it directly; 143 tests). Nothing
  opens a window, plays a sound, speaks or reaches the network - the
  real-widget tests build and drive one of every control for real (real wx
  events into the real `send_event`) and never show a window. The Ruby half
  is exercised with the interpreter the component carries - a program that
  runs, one that raises, `alert`'s two-argument signature, a `Runner`
  answering keys, the confinement refused from inside Ruby, an application
  writing to stdout without corrupting the wire, and `_()` answering out of
  the package's own `.mo`. The applications under test are BUILT by the
  tests, byte for byte in the real layout, so they do not need Elten
  installed; the ones that do read the user's own skip themselves instead.
  The later ones ask the REAL platform on the REAL interpreter what it
  answers to - a sound asked `closed?` before it is used, `input_text`
  handed Elten's own keywords, a board asked which wall it walked into, a
  choice row asked where it starts - because every one of those was an
  application that stopped, and a signature guessed from call sites is an
  `ArgumentError` inside somebody else's program.

### The same menus in all three interfaces

`src/ui/program_menu.py` names what the menu bar can do, once. The graphical
Titan had the lot; the Invisible UI's **Menu** category and Klango mode's
**Program** submenu had four entries between them, so the AI Agent, both AI
Assistants, AI OCR, the creation kit and Install data package could be
reached only from the graphical window - by the users least likely to be
looking at one.

- **They arrive as the same GROUPS, and a group nests where groups already
  nest.** The graphical Titan has Program, AI and Programmer; sixteen more
  lines in one menu is a longer menu rather than the same one.
  `extra_groups()` hands back the menus a face without a menu bar was missing
  whole - **AI** (the Agent, both Assistants, AI OCR) and **Programmer** (the
  creation kit) - and `program_entries()` is the little that merges into the
  Program menu each face already has (Install data package). Each face then
  nests them where its own groups already nest:
  - The Invisible UI's **Menu** card is the menu bar, so its elements are the
    menu bar's MENUS - **Program** (Component Manager, Program settings,
    Install data package, Help, Back to graphical interface, Exit), **AI** and
    **Programmer** - and each opens as a **subcategory**, in the place the
    card occupies, with **Back** at the top of it. That is exactly what a
    game platform does inside the Games card, and it is the same code:
    `InvisibleUI.expand_subcategory` / `collapse_subcategory` is the
    game-platform machinery generalised, with `expand_game_platform` /
    `collapse_game_platform` left as thin wrappers so the two interactions
    cannot drift apart.
  - Klango mode's **Menu** card is the same thing one level down: it holds
    **Program** (Settings, Component Manager, Install data package, Help,
    Exit), **AI** and **Programmer**, each a submenu of its own, exactly as a
    game platform is a submenu of Games. Its cards are now three lists
    spliced together, so a card's index is not a way to find one and
    `load_components` asks `_menu_card(name)` instead of `main_menu[5]`.
- Each entry is `{'id', 'label', 'icon', 'action'}` with a no-argument
  callable, and each face renders it its own way: `wx.MenuItem`s with skin
  icons, an element of an Invisible UI category, a `{"name", "type":
  "action"}` item in Klango's.
- Availability is decided in the one place - AI features off means the AI
  group is not returned at all, developer tools off means Programmer is not,
  and AI OCR keeps its own switch on top of that.
- What is deliberately NOT shared is Component Manager / settings / Help /
  Exit: each face already has its own, and those know things this module does
  not (standing Titan UI down for a modal dialog, Klango's own exit).
- Opening one of these from a non-graphical face brings Titan back through
  `restore_from_tray`, never `Show()`.
- Translation domain: `menu`.

### Shell add-ons: the parts of the shell somebody else wrote

`data/shell addons/` is the tenth add-on kind, and it exists because the
Titan shell - the desktop, the taskbar, the notification area, the Start menu
and the file browser - was entirely Titan's own code. A user who wanted one
more button on the bar, a column of their own in the file browser, an entry
on the desktop's menu, or **their own Start menu**, had to change Titan.

- **It copies what is already here rather than inventing a tenth way.**
  Discovery is `platform_utils.discover_data_entries`, so an add-on ships as
  a directory OR as a packaged `.TCD` (`KIND_SHELL_ADDON = 10`); the manifest
  is `__shell_addon__.TCE` with a `[shell addon]` section and `status = 0`
  meaning enabled, which is the component convention; the code is `init.py`,
  loaded the way a launcher's is; and a contribution is a
  `{'id', 'label', 'action'}` dict, the shape `program_menu.py` established.
- **Two kinds of add-on, and the difference is the whole design.** A
  **contributor** adds to what is there and any number apply at once. A
  **provider** (`provides = start_menu` / `explorer`) REPLACES that part -
  and replaces a *window*, not the shell, so everything else carries on.
- **Five surfaces, each asked where it is built** (`src/shell/addons.py`):
  - `start_menu` - `start_menu_items` goes through
    `src/ui/start_menu_content.py`, so an add-on writes it once and it is on
    the XP menu, the classic menu **and in the search box**. An entry with
    `children` becomes a branch instead of a line - and the search box then
    looks inside it, because a BRANCH is not something a list of results can
    open (`_build_search_index` drops every folder, rightly), so a branch
    searched as itself was a line the box could never find and whose commands
    were not indexed at all. `_searchable_branches()` expands it into its
    children, the same rule as everywhere else here: what somebody typing
    three letters wants is the command, not the branch it lives under.
  - `explorer` - `explorer_menu_items` (they make the browser's **Tools**
    menu, which exists only when there is something in it),
    `explorer_toolbar_items`, `explorer_context_items(where, selection)` -
    Windows' context-menu handler, so a command can be about THIS file - and
    `explorer_columns`, which is a column handler: asked **once per folder**
    (`_read_columns` on navigation) and its `value` called per row out of the
    entry already in hand, because the view is a virtual list and a column
    that asked Windows something per row would undo what makes a folder of
    three thousand files open in 30 ms.
  - `taskbar` - `taskbar_bands` is Windows' deskband: the add-on's control is
    built **in the notification area**, so it is a real child window of the
    bar - focusable with Tab and the arrows, and named, so a reader says what
    it is. Built once with the bar, never on a tray refresh (the tray is
    re-read every thirty seconds and rebuilding somebody's control that often
    would throw the keyboard out of it). Plus `taskbar_menu_items`.
  - `desktop` - `desktop_menu_items(where, entry)` for the icon menu and the
    background one.
  - `shell` - `setup`, `on_shell_start`, `on_shell_stop`. They are loaded and
    told on a **worker**, because `start_shell` costs 214 ms and this process
    owns the appbar and the shell hook.
- **Which Start menu you use is chosen where XP chooses it**: the taskbar and
  Start menu properties sheet (`taskbar_properties.py`), where every
  installed provider is a third radio button beside Titan's two, with its
  manifest description as the line under it. `shell_manager._addon_start_menu`
  only asks for one when `start_menu_style == 'addon'`, so offering a Start
  menu does not take the Windows key - being chosen does. An add-on chosen
  and since uninstalled means **Titan's own menu**, never a different add-on
  silently promoted. It is asked **in Settings -> Titan shell as well**, as a
  labelled list right under the shell's own switches: a user who came here to
  turn the shell on should not have to find a context menu on a bar to say
  which Start menu it puts up. One setting, two places that write it - both
  write `start_menu_style` + `provider_start_menu` at once (not on Save, which
  is what the properties sheet does) and throw the built menu away, and the
  settings window puts the same values into its own copy of the settings,
  since Save writes that copy back over the whole file. Switching an add-on
  on or off in the tick list below re-reads the list of menus at once.
- **Nothing an add-on does may take the shell down.** Every call out goes
  through `_safe`; a hook that is missing, raises, or answers something that
  is not a list of entries contributes nothing and the surface carries on.
  An entry is real if it has something to DO (`action`), something to SHOW
  (`control`, `value`) or something to OPEN (`children`) - anything else is a
  menu item with no words or nothing behind it, and is dropped with a reason
  printed.
- An add-on's own name and description are the author's words, not Titan's
  translatable strings - so the manifest takes `name_pl` / `description_pl`
  beside `name` / `description`, which is what `__app.TCE` has always done
  rather than a second answer to the same question.
- Switched on in **Settings -> Titan shell -> Shell add-ons** (a tick list of
  real check boxes - see "A tick list a screen reader can read" below -
  written to the add-on's own manifest at once) and through the Action API:
  `shell.list_addons`, and per add-on `status` / `enable` / `disable` from
  `actions/generic.py`'s `shell_addon` kind.
- Examples: `data/shell addons/example_shell_addon/` (one function per
  surface, the reference) and `simple_start_menu/` (a Start menu provider -
  one search box, one list). Both ship **off**.
- Guide: `data/docu/programming_guide/shell_addon_guide_{en,pl}.md` (and the
  HTML the converter makes of them, `html/shell_addon_guide_*.html`) - the
  manifest, every hook with its signature, the entry shape, the five
  surfaces, both provider contracts, the accessibility rules and the
  packaging.
- **The AI creation kit writes them** (Programmer -> AI -> Create Shell
  Add-on / Create Settings Interface), and what it writes is checked against
  Titan itself before it is saved - `ai_creation_kit.check_shell_addon` /
  `check_settings_interface`, run by the same auto-fix loop as every other
  kind. The failure being prevented is the invisible one: an add-on whose
  functions are ALMOST right loads, is listed, can be ticked, and
  contributes nothing. So a hook name that is not one Titan calls is refused
  with the one it meant (`start_menu_entries` -> `start_menu_items`), a hook
  with the wrong number of parameters is refused with the number it is
  called with, and so are a manifest key nobody reads, a surface that does
  not exist, `provides = start_menu` with no `open_start_menu`, an
  `api.something` the real API object does not have, and a settings
  interface importing `set_setting` to write the ini itself.
  - **Every one of those checks reads Titan, never a copy**: `addons.HOOKS`
    / `HOOK_SIGNATURES` (from which `HOOK_ARGS` is derived), `SURFACES`,
    `PROVIDABLE`, `MANIFEST_KEYS`, `interfaces.ENTRY_POINT`, and the API
    classes themselves - `_public_attributes` BUILDS one, because `api.id`
    and `api.path` are assigned in `__init__` and `dir(cls)` does not have
    them. The prompt is written out of the same tables, so the kit cannot
    teach a Titan that does not exist.
  - The four add-ons Titan ships are run through the same check by
    `tests/test_creation_kit_kinds.py` (29 tests), and
    `tests/test_shell_addons.py` parses `src/shell` to prove every hook in
    the table is really asked for, with the arity documented - so renaming a
    hook in the shell fails a test rather than producing add-ons that pass
    every check and do nothing.
- Tests: `tests/test_shell_addons.py` (run it directly; 26 tests).

### A tick list a screen reader can read

`src/ui/check_list.py`. Every list of tick boxes in the settings window - the
shell add-ons, the add-ons the AI may drive (its actions), the startup
categories - said the name of the entry and nothing about whether it was
switched on. `wx.CheckListBox` on Windows is an **owner-drawn list box**:
wxWidgets paints the little square itself, so there is no check box there for
the platform to report. Measured with `AccessibleObjectFromWindow` on a
`wx.CheckListBox` whose first item is ticked, and on the same list built as a
report-mode `wx.ListCtrl` with `EnableCheckBoxes()` (`LVS_EX_CHECKBOXES`, the
native list-view check box Explorer itself uses):

    wx.CheckListBox   item 1 role 34 (list item) state 0x300004  UIA toggle: no
    CheckList         item 1 role 44 (check box) state 0x300010  UIA toggle: 1

So the fix is the shell's own rule applied to a Titan window - **it is
accessible because it is native**. NVDA and JAWS read the state out of MSAA,
Titan Access out of the UIA toggle pattern it already reads for every check
box (`uia_focus._read_states`), and Titan says nothing: what it used to do was
*speak* "checked" / "unchecked" itself half a second after the row was read,
through the readers it can speak through and no others.
`announce_checklist_item_toggle` / `_navigation` keep the earcon and take
`speak=False`, which is all that is left for Titan to do.

- It keeps `wx.CheckListBox`'s interface (`Set`, `Check`, `IsChecked`,
  `GetString`, `GetCount`, `SetName`, `SetLabel`) and fires
  `wx.EVT_CHECKLISTBOX` and `wx.EVT_LISTBOX` with the row index in
  `GetSelection()`, so the windows around it did not change.
- **A change Titan made is not the user ticking something**: `CheckItem`
  fires the event whoever called it, so filling the list or putting a refused
  toggle back happens inside `_Quiet` and is silent - no earcon, no handler.
- **The name goes to MSAA, not to wx**: a native list view has no window
  text, so `SetName` alone reaches nothing that reads the screen and
  `a11y.name_control` is what names it - the same helper the shell's native
  controls use.
- `ui_model.py` describes it as `multi` beside `wx.CheckListBox`, so the
  settings interfaces render it unchanged - and setting one now fires **one
  event per row that really changed, carrying which row**, because the
  window's handler acts on the item the event names (a shell add-on is
  switched on in its own manifest) and an event with no index applied every
  change to the first entry.
- Tests: `tests/test_check_list.py` (run it directly; 16 tests) - it asks
  Windows itself, through MSAA and UI Automation, rather than asking wx what
  it thinks it built.

### Settings interfaces: Titan's settings, in a window somebody else wrote

`data/settings interfaces/` answers "I would rather have the settings as a
web page / in Qt / on a console / one question at a time". It is shaped like
`data/launchers/` because it is the same idea one level down - a launcher
replaces Titan's main window, a settings interface replaces its settings
window - and it is **chosen**, in Settings -> Interface -> "Settings
interface", where Titan's own window is called **Classic**.

**The interface never learns what a setting is**, and that is what makes the
whole thing possible. `src/settings/ui_model.py` reads the description out of
**Titan's own settings window**: its categories are the categories, its
controls are the settings, their labels are the labels - the same `_("...")`
strings, already translated. So:

- **A setting is added once.** A new checkbox in `settingsgui.py` appears in
  every installed interface, in the user's language, with none of them
  changed. There is deliberately no second table of settings to keep in step.
- **Component categories are there too** - the Macro Manager's, Titan
  Access's forty, the AI's - because `register_settings_category` hands the
  frame a panel and this walks whatever is on it.
  `interfaces.ensure_component_categories()` makes sure they are registered
  even when the window was built without a component manager, so an interface
  shows exactly what the classic window shows. Measured here: 11 categories
  alone, **14 with the components**, ~147 settings.
- **The values are live** - the voices, skins, sound themes and TTS engines
  are lists Titan fills in at run time, and reading the control is reading
  what the user would see.
- **Saving is Titan's own save** (`OnSave`), with everything that hangs off
  it: the SAPI registration, restarting the system monitor, re-hooking the
  shell, rebuilding the menu bar. An interface that wrote the ini file itself
  would set the value and change nothing.
- `kind` is what the CONTROL is (`bool`, `choice`, `number`, `text`,
  `secret`, `command`, `list`, `multi`, `info`), so an interface renders what
  Titan renders instead of guessing from a key name; a `wx.Choice` is
  labelled by the static text in front of it (that is how every wx program is
  built), a control nobody named is not offered rather than shown as a
  nameless box, and setting a value **fires the control's own event**,
  because that is where Titan applies things live.
- **The settings can never be the thing an add-on takes away**: an interface
  that is uninstalled, switched off, has no `open_settings()`, raises, or
  opens nothing means Titan's own window opens instead, said plainly.
- **Every way into the settings goes through `interfaces.open_settings()`** -
  the menu bar, the Invisible UI, both Klango classes, both Start menus, the
  desktop's menu, the shell, and `titan.open_settings` - which is what makes
  choosing one mean anything. (`titan_open_settings` used to build a SECOND
  `SettingsFrame`, one the components had never registered into.)
- An interface's own loop (a console, a server) runs on its own thread and
  reaches the settings through `api.call(...)`, which marshals onto the GUI
  thread and waits: the settings are wx controls.
- A settings interface ships `status = 0` (it is one of the choices, and
  changes nothing until it is picked), unlike a shell add-on, which starts
  doing things the moment it is switched on.
- An interface's name in the list is its manifest's, so it takes `name_pl` /
  `description_pl` beside `name` / `description`, as `__app.TCE` does.
- Actions: `settings.settings_interfaces`, `settings.use_settings_interface`,
  and per interface `status` / `use`.
- Examples, both installed and neither in use until chosen: `html_settings`
  (the whole settings as one HTML page in a `wx.html2` window; the page talks
  back by setting `location.href` to a `titan:` URL and Python vetoes the
  navigation - the oldest trick there is, and the one that works on every
  WebView backend with no bridge and no local server) and `console_settings`
  (`AllocConsole`, a numbered list, one question at a time).
- Guide: `data/docu/programming_guide/settings_interface_guide_{en,pl}.md`
  (plus the generated HTML) - the manifest, `open_settings(api)`, the whole
  API, the `kind` table and how to render each, threading through
  `api.call`, and the rule that the settings can never be what an add-on
  takes away.
- Tests: `tests/test_settings_interfaces.py` (run it directly; 40 tests -
  the last four are the settings window's own: one category on the screen
  at a time, and the shell's master switch inside the shell's category).

### Titan Access: one document over the web, over any app, over anything

`data/components/titan access/` is Titan's own screen reader. Two ideas carry
the parts added most recently.

**Everything the reader says is queued** (`titan_access/speech_adapter.py`).
Titan's TTS engines have no queue of their own - every `speak`/`speak_async`
stops what is playing - so a second announcement used to erase the first, and a
multi-part one (name / role / state) lost everything after the part that
happened to be speaking. The adapter now owns an utterance queue drained by one
pump thread: `interrupt=True` clears it, `interrupt=False` really does mean
"after this one", and each utterance is waited out (TTS channel -> engine
`is_speaking` -> length estimate) before the next starts.
`StereoSpeech.speak_concat` - which joins the pitched parts into ONE clip, so no
part can be cut off by the next - was **SAPI5-only**; it now works for every
engine that can render to memory via `_synthesize_segment()` (eSpeak, `say`, and
every TitanTTS plugin: Supertonic, SMP, Eloquence, DECtalk, BestSpeech,
ElevenLabs, Milena...). An engine that cannot (spd-say, no pydub) speaks the
parts as one joined line - pitch lost, nothing dropped.

**A flat virtual document, from whatever the window will answer**
(`titan_access/virtual_buffer.py`). Browse mode made a *web page* into a list
the arrows and quick-navigation letters walk; nothing about that is web-specific.
`build_for_window()` tries, in descending order of trust: `uia` (modern apps),
`msaa` (legacy Win32 / VB6 / Delphi - Windows proxies the standard controls, so
a program from 1998 still reports its buttons and their state), `win32` (the raw
child-window tree: class -> role, window text -> name, and a nameless Edit
labelled from the Static beside it), and `ocr` (the picture, read by the AI - see
below). Every node is a `VNode` with the same shape, so navigation,
quick navigation, announcement and activation (`activate()` - UIA patterns, MSAA
`accDoDefaultAction`, `BM_CLICK`, or an OCR click) are written once, and
`quick_nav.ROLE_MATCH` matches on Titan role keys so `b` finds a button whatever
built the document.

- **`browse_mode.py` is now both modes.** In a web document it behaves as
  before (auto browse/focus switching, IA2 fallback for Chromium/Gecko), plus a
  staleness check that notices a page replaced under the same document element.
  Anywhere else, **the reader modifier + Space toggles SCAN mode**: the app's
  interface becomes that same document. Arrows, Home/End, Ctrl+Home/End,
  PageUp/Down, Ctrl+Left/Right by word, Enter to press, F5 to rebuild, Escape to
  leave, Tab left to the application (the cursor follows the focus), and scan
  mode ends by itself when the user changes window.
- **AI OCR fills the gap when a window answers nothing**
  (`titan_access/ocr_assist.py` over `src/ai/ocr`). Two uses: the whole window as
  buffer nodes (only after the accessibility tiers came back empty, and only when
  explicitly asked for - turning scan mode on, or F5), and `label_for()`, which
  gives a control the program never named the caption printed on or beside it -
  from a cached reading on the focus path, or spoken behind the announcement when
  a fresh reading was needed (possible at all because speech now queues). Gated by
  Titan's AI-features switch AND Settings -> Titan Access -> scan mode / AI
  reading / AI labels.
- **Progress bars** (`titan_access/progress_monitor.py`) are NVDA's, positioned:
  the pitch curve and throttles are taken from NVDA's own
  `NVDAObjects/behaviors.py` (`110 * 2 ** (percent / 25)`, 40 ms, a beep per 1%
  of movement, the value spoken per 10%), and the beep is **panned 0% hard left
  to 100% hard right**, so the progress is heard travelling across the stereo
  image. Foreground window only, one slow thread, Settings -> Titan Access ->
  Progress bars (`Reader/ProgressMode` + the two intervals).
- **The NVDA controller bridge answers 32-bit applications too**
  (`helper/`). The RPC layer always was bitness-agnostic; what was wrong is that
  the endpoint `NvdaCtlr.<session>.<desktop>` is ONE name whose first registrant
  receives every application's calls - and the helper reported "server active"
  even when it had lost that race, so a conflict looked like "the bridge does not
  work with my program" (most visibly for 32-bit ones, since Titan's own 64-bit
  code speaks through the engine directly and never goes near RPC). The helper
  now reports ownership (`TitanAccessHelper_ownsEndpoint`), keeps trying to take
  the endpoint over while somebody else holds it (`retryEndpoint`, so closing
  NVDA is enough - no Titan restart), and counts served calls. `nvda_probe32.exe`
  / `nvda_probe64.exe` (built by `helper/build.bat`, which pins `/protocol dce`
  precisely so an ndr64-only stub can never lock 32-bit clients out) bind to the
  endpoint exactly as an application does; Insert+C -> "Test the NVDA controller
  bridge" runs one per bitness and says whether the call reached **Titan Access**
  or another screen reader.
**Every UIA property used to be its own cross-process call**
(`titan_access/uia_cache.py`). That, and not the logic, was the whole of "it
lags on web pages and in UWP apps": a focus announcement made about thirty
round trips, and a browse-mode buffer about ten per element over thousands of
elements. UI Automation's answer is the one NVDA and JAWS use - a **cache
request** - and it is now used in both places. `AddFocusChangedEventHandler`
is given one, so a focus event arrives with everything already filled in;
`FindAllBuildCache` returns a whole page WITH its properties in a single call.
Measured on this machine: a focus snapshot 9.6 ms -> 0.43 ms (22x, identical
output), a Chromium page 2088 ms -> 448 ms, and reading fourteen properties of
every element back out of the cache 7 ms. Two traps the module hides: an
unsupported property answers with its TYPE DEFAULT (an element with no toggle
pattern reports ToggleState 2, "partially checked"), so every pattern value is
gated on its cached `Is<Pattern>PatternAvailable`; and
`GetCachedPropertyValue(BoundingRectangle)` answers width/height while
`CachedBoundingRectangle` answers right/bottom.

**A page is read the way NVDA reads it - flat, with no group lines.** Chromium
wraps almost everything in a `GroupControl` and every landmark is one too, so
browse mode used to make the user arrow past "navigation, group" on the way
into the navigation, and the focus context presenter said "group" on the way
into anything. Now: `build_uia(..., web=True)` emits no grouping entries at
all, `_flatten_web` recovers the regions from the source elements and stamps
them onto the content by geometry (`landmark` / `landmark_start` on `VNode`),
quick navigation `d` / `n` jumps between the entries that BEGIN a region, and
the region is spoken once as the cursor crosses into it. An application in scan
mode keeps its captioned group boxes - there a group is a real division. In the
context presenter, group context is skipped entirely in web content
(`_is_web_content`, by FrameworkId) and an unnamed group is never announced
anywhere.

**A navigation key never waits for a rebuild.** The staleness check ran on
every arrow key and resolved the page's document element to do it - a walk of
the browser's UIA tree, sometimes a breadth-first search of thousands of
elements - and then a stale buffer was rebuilt synchronously, half a second
before the key was answered. Now the per-key check is `(foreground window,
title)` and nothing else, the resolved content document is cached against those
two, and a buffer that has gone stale is refreshed **on its own thread** while
the keystroke that noticed navigates the buffer already in hand (one refresh at
a time; the cursor is put back on the same entry by name and role). Only the
first build of a document is synchronous. Browse mode also no longer moves the
real keyboard focus onto every entry the cursor passes - NVDA does not, because
it scrolls the page, fires focus events back at the reader and can start typing
into a field the cursor merely went past; the page is scrolled behind the
announcement instead, and the announcement itself is assembled from the cached
node with no COM call at all.

**Titan Access is reachable from the Action API and from Titan Script**
(`titan_access_actions.py`, 21 actions under the add-on id `titan_access`; the
component's `init.py` hands its lifecycle over with `bind()` and re-exports
`TITAN_ACTIONS`). It is the only part of Titan that can answer "what is on the
screen right now" for a program that is not Titan, so that is what most of them
do: `read_screen` / `list_elements` / `find_element` / `click_element` (by text
or by the number `list_elements` gave), `read_focused`, `window_title`,
`document_info`, `refresh`; `say` / `speak_screen` / `stop_speech`;
`scan_mode` / `browse_mode` / `say_all` / `go_to` (quick navigation);
`get_state` / `set_enabled` / `toggle`; and `list_settings` / `get_setting` /
`set_setting` by the words a user would use ("rate", "scan mode", "progress
bars"). **Reading does not need the reader to be running** - it builds the
document itself - and the AI tier is never reached unless a caller passes
`use_ai=true`, because that tier sends a picture of the screen to the user's
provider. Example: `data/macros/screen_reader_demo/`.
- Tests: `tests/test_titan_access_speech_queue.py`,
  `tests/test_titan_access_document_mode.py`,
  `tests/test_titan_access_actions.py` (run them directly - `tests/` has no
  `__init__.py`).

### Titan Action API: any part of Titan calling into any add-on

`src/titan_core/actions/` is how one piece of Titan asks another to do
something. It is a **titan-core capability, not an AI one** - the AI agent and
voice assistant are just its first consumers, and a component, widget, macro,
launcher, gamepad mode or another application uses the identical calls.

```python
from src.titan_core import actions
actions.list_addons()                        # what is installed and reachable
actions.run('tedit', 'open_file', path=...)  # do it (never raises; result.ok / result.text)
```

Before this, reaching an add-on meant writing code *about* it inside
`src/ai/` - the tMedia integration is ~1100 lines of exactly that (it reads
tMedia's private data files and drives it through a startup argument). That
does not scale and breaks whenever the add-on changes. Now the add-on
**declares** what it can do and Titan discovers it:

- `data/applications/tEdit/__actions.json` - the declaration (id, label,
  per-action `summary`, typed `params`, `risk`, `mode`, `promote`)
- `data/applications/tEdit/tedit_actions.py` - the handlers

All eleven add-on kinds use the same file, and because discovery goes through
`platform_utils.discover_data_entries()`, a packaged `.TCA`/`.TCD` add-on is
picked up exactly like a directory. An in-process add-on may skip the JSON and
declare `TITAN_ACTIONS` in Python with real callables.

**Two transports**, because add-ons live in two places:
- `inproc` (`inproc.py`) - components, widgets, statusbar applets, TTS engines,
  gamepad modes, launchers, Titan IM modules are already loaded, so an action
  is a direct call marshalled onto the GUI thread. Handlers resolve against the
  *already-loaded* module, so they act on the add-on's live state.
- `process` (`process.py`) - applications and games. A `headless` action runs
  in a short-lived subprocess printing one JSON object; a `live` action goes to
  the running instance over the **Action Bus**; `any` (the default) uses the
  open instance when there is one and stays out of the user's way otherwise.

**The Action Bus** (`bus.py`) is one named pipe, `\\.\pipe\TitanActions`,
started from `main.py`. An add-on joins with a single call:

```python
from src.titan_core.titan_actions import serve
serve({'open_file': open_file, 'save': save}, id='tedit', label='Text Editor')
```

`src/titan_core/titan_actions.py` is deliberately **standalone and
standard-library only** (it imports nothing from `src`), because the add-on
importing it may be a wx app, a Tk launcher or a console script. `bus.py`
imports `PipeChannel` *from it*, so there is exactly one definition of the wire
behaviour. Handles are OVERLAPPED and not by accident: a synchronous pipe
handle serialises all I/O on the file object, so a thread parked in ReadFile
blocks the WriteFile answering it - which collapses the connection on the first
call.

The bus is **bidirectional**: an application can ask Titan to run *another*
add-on's action (`titan_actions.call(...)` / `list_addons()`), which is how an
add-on in its own process reaches components and other applications. Both ends
dispatch on worker threads so a handler that calls back cannot deadlock.

**Titan's own subsystems are providers too** (`builtin.py`), so an add-on never
reimplements Titan: `titan` (settings, components, add-ons, TTS engines),
`settings` (find a setting by what it does), `system` (volume, playback device,
brightness, power plan, theme, Wi-Fi, autostart), `gamepad` (list/read/set/cycle
the modes), `titannet`, `elten`, `im`, `ocr`, `memory`, and — so that
"everything Titan can do" is true of the API and not only of the agent —
**`desktop`** (the open windows, the keyboard and mouse, files, launching
programs; `agent_tools.get_desktop_tools()`, split out of `get_tools()` for
exactly this), **`ui`** (any window's controls by name, via Windows' own
accessibility) and **`web`** (the user's browser). These are **adapted, not
rewritten**: `builtin._addon_from_tools()` turns the tool tables in `src/ai/`
and `src/ai/tools/` into ActionSpecs with the callable attached, so there is one
implementation with two audiences. An installed add-on can never shadow one of
these ids - it is registered as `<id>_addon` with a warning instead.

**An action is gated on the AI only if a model actually does it.** `ActionSpec`
carries `needs_ai` (manifests may declare `"needs_ai": true`), `dispatch.run()`
refuses such an action when AI features are off with one plain sentence rather
than letting it fail inside a provider with no key, and `describe()` marks it
`[needs AI]` so a macro author can choose the way that still works. The list is
deliberately per *action*, not per provider: today it is exactly
`ocr.read_window` and `ocr.ask`, because pressing and typing into what AI OCR
already read is ordinary UI Automation and the memory tools are a file of
notes. Living in `src/ai/` is not the same as calling a model.

**`live` is the last resort.** An action must not require the add-on's window
just because that is where the code was written - "write a note, then read it
out in my ElevenLabs voice" cannot mean opening two applications first. So
`any` is the default and the rule is: does the action need the *window*, or
only the add-on's *data*? The API key, the download folder and the saved files
are all on disk, and the window does not own them. ElevenLabs (`speak`,
`save_speech`, `list_voices`) and tDownloader (`download`, folder settings) are
written this way - they prefer the open window so the result joins its history
and list, and work fully without it. `live` is left only for things like "save
the document I have open" or "what is selected right now". Two supports for
this: a per-action `"timeout"` in the manifest (an action that legitimately
takes minutes is not killed at 45s), and **detached** work for anything that
outlives the answer - audio playback, a large download - so the short-lived
process can return at once. `titan.speak` reads text through Titan's own TTS,
in Titan's process, so no add-on needs a voice or a window of its own.

**Three outcomes, not two** (`interaction.py`). A handler returns a sentence
when it worked, `fails(reason)` when it could not, and `needs(name, prompt,
options=...)` when it must ask. Prose alone was not enough: a composite command
cannot tell "there is no such note" from success and carries on to the step
that assumed otherwise - which is exactly what the first `run_sequence` test
exposed. A question is a *pending* result (`result.pending`,
`result.question`), not a failure; `run_interactive()` runs the whole
ask-and-retry loop, through a Titan dialog by default. A **required parameter
that was not supplied becomes a question automatically**, built from its
manifest `description`, so every action is askable without its author writing
anything.

**Composite commands** (`sequence.py`). `run_sequence(steps)` runs actions in
order; `{{n}}` in a string argument is what step n returned; the run stops at
the first step that fails or asks and the transcript names every step. Over the
bus that is `titan_actions.call_sequence()`, and the AI has it as
`titan_run_actions`. The **agent window can now ask too** - `get_tools(ask_user=)`
adds the assistant's `ask_user` tool and `ai_agent_gui._ask_user` speaks the
question and shows a dialog, so a half-specified request becomes a conversation
instead of a guess.

**Components declare actions without any manifest.** `zegarynka` (say the time,
turn the chime on/off, change the interval), `macros` (list, run, **create**,
read, **edit**, delete a macro and set its shortcut - "write me a macro" ends
with a macro in the macro manager, not a script file on the disk, and "change
it" changes that one), `titan access` (21 actions: reading the screen of any
program, pressing what it finds, the reader's modes and its settings - see
"Titan Access" above), `tips` (search Titan's own written help, say one, change the
interval), `TTerm` (run a shell command and return its output - the last resort
for anything with a command line but no API) and `TArticle` (fetch a page and
return the article as readable text, or open it in the reader) each ship a
`TITAN_ACTIONS` list in Python with real callables, found on the module
`ComponentManager` already loaded - which is why `initialize_components()` ends
with `actions.invalidate()`, or the registry would hold a snapshot taken before
any component existed. `inproc.candidate_owners()` also matches by the add-on's
name in `sys.modules` and compares paths case-insensitively, because a manager
and discovery spelling the same directory differently used to make a
component's actions silently invisible.

### Titan Script (.TCS) - a mini language made of Titan actions

A `.macro` replays keystrokes and knows nothing about Titan. A **Titan Script**
names actions instead, so it can do anything Titan can. It lives in the Macro
Manager component (`data/components/macros/init.py`), is plain text, and Edit
opens it in tEdit like any other script.

```
when time = "11:45"                 startup / time / every

set total = 60 - number(now("%M"))  + - * / , upper lower trim length text
ask who = "Your name?" default="Anna"   number round replace now today
set greeting = "Hello, " + upper(who)
titan.speak "{{greeting}}"          any action of any add-on, by name
set chime = zegarynka.get_settings
if chime contains "on"              contains / is / is more than / is empty...
    say "the chime is on"
end
dialog "Write a note"               one window, one variable per control
    field title = "Title"
    multiline body = "Text"
    choice importance = "How important?" options "normal", "high"
    check speak_it = "Read it back"
    buttons pressed = "Save", "Save and read", "Cancel"
end
if pressed = "Cancel"               by what it says, or `= "3"` by which
    stop                            option it was; `=` needs no spaces
end
tnotes.create_note title="{{title}}" text="{{body}}"
macros.run_macro name="My other macro"      every action the assistant has
message "Done, {{who}}." title="Example"    also warn / error / confirm / choose
play "done.ogg" position=-0.8 wait=true     a sound shipped beside the script
run "helper.tcs"                            another script in the same folder
voice engine="supertonic" rate=2            borrowed FOR THIS SCRIPT ONLY
say "one at a time" wait=true               also interrupt=true; `speak` too
say "one" position=-1 rate=-6 pitch=2       where the voice is, how fast, how
                                            high - for that line only
return "what the caller gets"               ends this script, hands that back
repeat 2
    wait 1s
end
```

- **Resolution is forgiving, never a guess**: `titan.tts.speak`, `titan.speak`
  and `titan.speak("x")` all reach the same action; an ambiguous or unknown
  name is an error that names the candidates.
- **Checked before it runs** (`check_tcs`, action `macros.check_macro`): unknown
  actions, wrong argument names, wrong arity, unclosed blocks **and numbers
  outside what a setting takes** (`voice rate=100` - the ranges live in
  `_TCS_RANGES`) are reported at write time, not at a quarter to twelve.
  `macros.create_macro` with `kind: 'tcs'` refuses to save a script that would
  not run. The Macro Manager offers the same check on any .tcs macro (context
  menu -> Check script, GUI and Invisible UI), and its **Titan Script** tab is
  the language reference itself.
- **Checking is a review, not a parse** (`review_tcs` -> `check_tcs` +
  `review_warnings` + `review_with_ai`). "The macro is fine" is a promise, and
  parsing cannot make it: a script can name only real actions and still be
  wrong. The warning pass compares the script against the *documented* language
  and against what each action *declares* - a variable never set or **used
  before the line that sets it** (order-aware, and it trusts only straight-line
  code, so a loop or an `on` block using what it sets later is not a false
  positive), a word from another language that quietly became pseudocode
  (`_TCS_FOREIGN_WORDS`: while/for/print/var/sleep/exit...), an `on` block for a
  button that is not there, a value outside an action's declared `enum`, a line
  after `stop`, an AI-backed action while AI features are off. With AI features
  on, `review_with_ai` then has a model read the script *with the reference in
  front of it* for what neither can prove - reported separately and always
  labelled advisory, never turned into a refusal, and never asked at all about a
  script that does not parse. Live-checked: it caught "the note is created on
  line 2 using title and body before they are asked for on lines 3 and 4".
  `create_macro` / `edit_macro` append the warnings to their success message, so
  the AI that wrote a macro is told what is suspicious in it.
- **The review then mends what it found** (`fix_with_ai`, `macros.fix_macro`,
  and the Macro Manager's own question after a check). The AI is handed the
  findings and the reference, corrects the script, and **its correction is
  reviewed the same way**, up to three rounds, stopping the moment a round comes
  back clean. A macro that was already right costs nothing: no request is made
  and nothing changes. A correction that comes back *worse* than the original is
  discarded, and nothing is ever written without being asked for - the GUI asks
  before saving, and `fix_macro` only writes with `apply=true`. Live-verified:
  a macro that created a note before asking for its title came back with the
  `ask` lines moved above the action, clean in two rounds.
- **The review is written in the user's language** - `_tcs_line()` /
  `_tcs_line_prefixes()` and the macro component's own catalogue (`macros`
  domain, *not* `languages/ai.po`), so a Polish Titan says
  "linia 4: 'greting' jest używane, ale nigdy nie ustawione". The AI reviewer is
  told which language to answer in and which word to anchor each finding with,
  and both spellings are accepted when its answer is read back - which is also
  why `ai_creation_kit.check_titan_script` matches `- <word> <n>:` by shape
  rather than by the English word.
- **The reference is in the user's own language.** `_MACRO_LANGUAGE` /
  `_MACRO_LANGUAGE_PL` and `_macro_language_text()`: a Polish Titan shows the
  Polish reference, and `_tcs_template()` writes a Polish template into a new
  script. `macros.macro_language language="en"` asks for the English one -
  which is what `creation_docs` grounds the model on, like every other guide.
  A document this size is a second text rather than one 140-line msgid that a
  one-word change in the English would invalidate wholesale.
- **Expressions are parsed, never `eval`'d** - a script is a file on disk and
  must not be able to run arbitrary Python.
- **Dialogs are real wx controls** on the GUI thread, parented to Titan (so
  Windows closes them with it), and closing one **ends the script** rather than
  continuing with an empty answer. A dialog may name its **own buttons**
  (`buttons pressed = "Save", "Save and read", "Cancel"`, up to six): each is a
  real `wx.Button` ending the dialog with its own id, so a form can offer
  several instructions instead of only OK - which is what "a macro for
  automation" actually needs. Escape and the close box still cancel.
  `data/macros/form_demo/` is the whole thing.
- **An answer picked from options knows which option it was** (`_AIChoice`, a
  `str` subclass carrying `number` + `options`, returned by `choose`, by a
  dialog's `choice` and by `buttons`). `_ai_compare` consults it for
  `is`/`=`/`==`/`is not`/`!=`, so `if answer = "yes"` and `if answer = "1"` are
  the same option - the wording of a button changes, its position does not.
  Everything else sees a plain string, so `{{answer}}` still writes the text.
- **Comparisons may be written tight**: `if option="tak"` is a comparison, not
  a syntax error. `_ai_tight_operator` scans for the symbol operators outside
  quotes and brackets, so `if x = "a=b"` and `if tnotes.count(kind="x")>0`
  still split where they should. Word operators are matched first, as before.
- **It speaks in the user's own voice.** `say` is `titan.speak`, so there is one
  answer to "what does Titan sound like". `voice engine=... name=... rate=...`
  borrows a different one **for that script only**: applied to the live engine,
  never written to settings, and put back in a `finally` however the script ends
  - finished, stopped, cancelled or broken. A called script restores its own
  before returning, since it holds its own copy of the run state.
- **Where the voice is, how fast and how high it is, are part of the language.**
  `say "one" position=-1 rate=-6 pitch=2` renders that line through
  `stereo_speech.speak(text, position, pitch_offset)`, which Titan already had:
  position -1 (left) to 1 (right), rate and pitch -10 to 10. `rate` belongs to
  the line it is on - the rate in force comes back straight after, so such a
  line is spoken synchronously (restoring it mid-utterance would give the next
  line's rate to this one). The same three arguments are on the `titan.speak`
  action, so any add-on has them too. Without this, "count to ten moving from
  left to right, getting faster" could only be *described* to the AI - which is
  exactly the pseudocode a generated macro must not contain.
  `data/macros/voice_demo/` is that script, written out.
- **Its own sounds and its own helpers.** `play "ding.ogg"` and
  `run "helper.tcs"` look for a bare name *next to the script*, so a macro
  folder carries everything it needs anywhere. A called script gets its own
  variables, hands back `{{last}}`, shares the caller's step budget, and cannot
  call round in a circle (chain + depth guard).
- **Sound goes through Titan's mixer**, not an audio device of the script's own:
  the new `titan.play_sound` / `titan.stop_sounds` actions wrap
  `sound.play_sound_file` with the user's theme volume and stereo/3D
  positioning, and any add-on can use them.
- **A sound can be placed, and can travel while it plays.**
  `play "ding.ogg" position=-1 to=1 duration=3s` (plus `elevation` /
  `to_elevation` in 3D). `sound._start_sound_file()` now hands back whatever is
  playing - an OpenAL source or a pygame channel - and
  `sound.play_sound_file_moving()` steps it on one daemon thread
  (`spatial_audio.move_source()` for HRTF, `channel.set_volume()` for stereo).
  Both backends could always do this; nothing had ever asked them to.
  **The static case was also wrong**: everything Titan exposes says -1..1 while
  `sound.py` has always taken 0..1, and `titan_play_sound` passed one straight
  into the other - so every position left of centre, *including the centre*,
  came out hard left. It converts now (`(position + 1) / 2`).
- **A macro's window carries the macro's name, and the name is editable.**
  `_tcs_running` (a `threading.local`, since a trigger can fire while the user
  runs another macro) holds the title and `_tcs_title()` uses it for any window
  the script does not title itself - "Voice demo", not the word "Macro". The
  script changes it at any point with `title "..."`, a statement takes its own
  `title=`, and `macros.edit_macro new_name=` renames the macro itself. A
  script opened by double-clicking is named after its own file.
- **A button can do work while its window stays open.** `on "<button>"` blocks
  inside a `dialog` (`kind: 'handler'`) run on the GUI thread inside the
  button's event, with the controls as they stand injected into the script's
  variables; a button with no block closes the window and answers with the
  values as before. `_ai_form`'s `on_press(label, number, values)` is called
  once with `values=None` per button to ask whether it has a block at all - that
  is what decides whether pressing it closes the window. A handler that fails
  or says `stop` is carried back to the script's own thread rather than raised
  into wx's event loop. This is what makes a macro a small application instead
  of a form that can only be submitted.
- **Anything Titan can reach is callable, including things with no add-on.**
  `keys "ctrl+s"` / `type "text"` (`desktop.press_keys` / `desktop.type_text`,
  so there is one implementation for the agent and for a macro), plus
  `desktop.*`, `ui.*` and `web.*` as ordinary actions - so a program with no
  actions of its own is driven with focus_window + keys/type + click_element.
- **The action itself may come from a variable**: `{{app}}.open_file` -
  `_ai_call` fills the path before resolving it, `_ai_looks_like_call` accepts
  `{{name}}` segments, and `check_tcs` leaves such a line for run time. A macro
  that has just asked which application the user meant can act on the answer
  instead of needing one branch per possibility.
- **Pseudocode needs AI features on, everything else does not.** A line that
  does not name an action (or an explicit `do "..."`) is handed to the AI, which
  translates it into the same action steps and runs them through
  `run_sequence` - a translation, not an agent. With AI off such a line is an
  error, and it is an error **before the macro runs**: `run_tcs_text` takes the
  pseudocode census (`pseudocode_lines`) first and reports every line by number
  rather than half-running the script and stopping at the first one. A parse
  error is spoken with its line too (it used to fail silently, which is the
  worst possible answer for a macro).
- **A macro written FOR somebody is made of real actions.** Pseudocode is fine
  in a script a person writes for themselves; a generated one made of it stops
  working the moment AI features go off, and usually means its author never
  looked for the action that already existed. So `macros.create_macro` and
  `macros.edit_macro` refuse a line written in words (`_tcs_write_problems`),
  naming it, unless `allow_pseudocode` is set - and a refusal comes back with
  `_TCS_WRITE_RULES`, so the model is corrected with the real language rather
  than guessing again.
- **Editing is a first-class action.** `macros.edit_macro` (name, script, keys,
  append, hotkey) changes the macro the user already has - checked before it is
  written, shadow-copying a bundled macro into the user overlay first - so "make
  it also do X" ends with their macro doing X, not a second macro beside it.
  `create_macro` on an existing name now points at it.
- **Triggers**: `TCSScheduler` (one slow-ticking thread, started only if some
  script asks for a trigger) fires `when startup` / `when time` / `when every`.
- **Titan opens a .TCS directly**, compiled or from source:
  `main.py --run-script <path>` (and a bare `titan foo.tcs`), registered for
  double-click by `src/system/file_association.py` alongside `.tca`/`.tcd`. The
  path is parked in `src/titan_core/script_launch.py` and run at the end of
  `ComponentManager.initialize_components()` - the first moment every action a
  script can name exists, and the one place all three startup modes pass
  through. Without the Macro Manager component it says so plainly.
- **The AI creation kit builds them too** (Programmer -> AI -> Macro (Titan
  Script)). The kind writes `__macro__.TCE` + a `.tcs` into the user's
  `data/macros/`, is told to write **no Python and no pseudocode**, and is
  grounded on documentation read live from the macro manager itself
  (`creation_docs.load_macro_docs()` -> `macros.macro_language` +
  `macros.macro_actions`) rather than on a guide file that could drift. Every
  generated `.tcs` goes through `check_titan_script()` in `static_check`, so the
  kit's existing auto-fix loop corrects invented statements, actions and
  out-of-range numbers by line number before the user ever sees them; saving
  ends with `macros.reload` so the macro is in the list at once.
- Actions: `macros.macro_language` (the grammar), `macros.macro_actions` (what
  can be called), `macros.check_macro`, `macros.edit_macro`, `macros.reload`.
  Examples: `data/macros/example_script/` (everything), `voice_demo/`
  (positioned, speeding-up speech), `form_demo/` (a form with its own buttons,
  branching on the option by text and by number, a travelling sound).
- **"Do not use the AI" has to be distinguishable from "you did not say".**
  `macros.check_macro use_ai=false` sent the script to a model anyway: an
  action's arguments arrive as strings over the bus, so "not given" is the
  empty string - and `str(value or '')` cannot tell `False` from `''`, because
  `False or ''` IS `''`.  The call fell through to "whatever the AI-features
  setting says" and made a request the caller had just refused, which offline
  is a TCP connect timeout with the Macro Manager waiting on it (measured: one
  test run took 329 seconds).  `_ai_given()` is what decides now - None and a
  blank string mean unanswered, everything else including `False` is an
  answer - and `tests/test_tcs_macros.py` replaces `ai_provider.generate` for
  the whole file with one that raises, so a test reaching a real model is a
  failure rather than a slow, flaky, billable pass.  That file went from 8-330
  seconds a run to **0.45 s**.
  Tests: `tests/test_tcs_macros.py` (run it directly - `tests/` has no
  `__init__.py`; 101 tests).

**Every add-on is reachable, declaration or not** (`actions/generic.py`). Most
kinds share one Python interface with every other add-on of that kind, so the
*kind* declares the obvious actions and each installed add-on gets them for
free - a user's own TTS engine installed yesterday is drivable without its
author writing anything:

- `tts_engine` - `status`, `list_voices`, `set_voice`, `list_settings`,
  `get_setting`, `set_setting`, `use`
- `component` - `status`, `enable`, `disable`
- `im_module` - `status`, `open`
- `statusbar_applet` - `read`, `activate`
- `widget` - `info`
- `gamepad_mode` - `status`, `activate`
- `launcher` - `status`, `use`

An add-on that declares an action of the same name keeps its own. This is also
what answers "the settings exist but the AI says there is no API key": a TTS
engine's configuration fields *are* its settings, so `list_settings` /
`set_setting` let the AI find the field, say where it goes and fill it in,
instead of reporting a dead end.

**Secrets are encrypted and never leave the machine in a tool result**
(`src/titan_core/secret_store.py`, formerly `src/ai/secret_store.py`, which
re-exports it). `looks_secret()` decides once, for the whole program, whether a
setting is confidential - whole-word matching, so `api_key` is a secret and
`titan_ui_key` and `assistant_hotkey` are not. `store_value()` / `load_value()`
encrypt on the way to disk (DPAPI: readable only by that Windows account) and
decrypt on the way back, and `describe_value()` is what may be shown - a key is
reported as "set, N characters, kept encrypted" and never rendered, because a
tool result is sent to the model provider verbatim. The engine settings panel,
`stereo_speech`'s loader, `titan_set_setting` and the generic
`tts_engine.set_setting` all go through it.

**Credentials the user already gave Titan are used, not asked for again.**
`titannet_tools._client()` signs in headlessly with the username and password
saved in the encrypted `titan.IM` file when "log me in automatically" is
ticked, so Titan-Net actions work with no window open; `titan_im_login` with no
username does the same, and falls back to the saved Telegram number. The
ElevenLabs actions look for the key in the client's own ini *and* in Titan's
ElevenLabs speech engine, and a key saved through them goes to the encrypted
one.

**There is no permission wall between add-ons.** The Settings gate applies only
to the AI (`action_tools.allowed()`); `dispatch.run()` is ungated, so any
add-on reaches anything any other add-on declares, and Titan's own subsystems
too. That is the point: nothing should ship its own editor, browser, file
manager or downloader. An add-on that only wants to *call* others uses
`titan_actions.connect()` rather than `serve()`.

The AI's view of all this is `src/ai/action_tools.py`: `titan_list_actions` and
`titan_run_action` always exist, and an action marked `"promote": true` becomes
a first-class tool (capped at `PROMOTED_BUDGET`), which keeps the tool list
bounded however many add-ons are installed. Gated by Settings -> AI features
("Let the AI use the functions add-ons offer", plus a per-add-on list).

**Bundled apps that ship a manifest**: tEdit (live edit/save + headless file
read/write), TFM (headless file operations + live navigation), tWeb (opens
pages in the browser the user actually has open, plus bookmarks/history),
tNotes and tReminder (pure data, no app change needed), tDownloader and the
ElevenLabs client (live). tMedia is deliberately still driven by the older
bespoke code in `src/ai/titan_tools.py` - it is live-tested and migrating it
buys nothing until the generic layer has been used in anger.

Guide: `data/docu/programming_guide/action_api_guide_{en,pl}.md`, injected into
every AI creation-kit prompt by `src/ai/creation_docs.py`.

### Titan's own subsystems exposed to the AI

`src/ai/tools/` is the other half: Titan's built-in services are not add-ons
and have no manifest, so each gets a hand-written tool module over the Python
API Titan already has. `get_subsystem_tools()` collects them, and a module that
cannot import is skipped rather than taking the toolset down.

- `settings_tools.py` - a schema over Titan's settings (what each one means,
  what it accepts, words a user might use), because the settings file only
  contains keys already changed and a model cannot find `alt_f4_action` from
  "what should Alt+F4 do". Search with `titan_find_setting`.
- `system_tools.py` - the *computer's* settings: volume, playback device
  (via the undocumented `IPolicyConfig`, the only way to switch it), brightness,
  power plan, light/dark theme, Wi-Fi, whether Titan starts with Windows.
  Deliberately scoped: read anything, change the ordinary things, and open the
  right `ms-settings:` page for everything else.
- `titannet_tools.py` - forum topics and replies, mail, groups, rooms, private
  messages. Everything that publishes is `always_confirm`. Mail is the whole
  client: the user's own address, inbox / unread / sent, read (Markdown and
  HTML reduced to readable text by `mail_format`, the same renderer the Mail
  window uses), send in text / Markdown / HTML with the plain-text alternative
  beside it, reply (to the sender, with the subject, quoting), and delete.
- `elten_tools.py` - Elten messages, forums, blogs; signs itself in from the
  credentials saved in the encrypted `titan.IM` file.
- `im_tools.py` - one bridge for every web-backed messenger, because
  `IMBackend` is already service-agnostic and capability-gated. Never starts an
  engine the user did not open.
- `ocr_tools.py` - AI OCR as something the agent reaches for when
  `read_focused_window` comes back empty: read the window, ask one question
  about it, press/type/toggle, or hand it to the user as the real overlay.

### The AI creation kit: nothing it writes is invented

`src/ai/ai_creation_kit.py` (Programmer -> AI) writes a complete add-on of
any of its **twelve kinds** from a description. The model is not the problem
- it writes valid Python readily - **invention** is: a function Titan never
calls, a module that does not exist, an argument nobody reads, an action no
add-on declares. All of it imports cleanly, none of it raises where the user
can see, and the add-on simply does nothing.

So everything a generated add-on claims is checked against the running
program before it is saved, by the same auto-fix loop that already fixed
syntax errors (`src/ai/creation_check.py`, `static_check(files, kind)`):

- **`from src...` must be real** - the module has to exist in the source
  tree and the name has to be in it (read with `ast`; nothing is imported).
  This is the big one: `from src.titan_core.speech import say` and
  `sound.play_notification(...)` are what a model writes when it is guessing.
- **an attribute read off a Titan module** must be one that module defines
  (including names created by `global x` in a function), and a local
  variable that shadows the import is not mistaken for it (`actions = []`
  then `actions.append(...)`).
- **an action named on one of Titan's own providers** must exist -
  `actions.run('titan', 'open_the_settings')` comes back as "did you mean
  open_settings?". An add-on the user may not have installed is never
  second-guessed.
- **a manifest key or section** must be one that kind's manager reads,
  learned from the add-ons of that kind that already work plus the ini/json
  block in that kind's own guide - so there is no table here to drift. It
  also knows which manifests have no `[section]` at all (`__app.TCE` is a
  plain list of `key = value`, and a model adds `[app]` to it constantly).
- **no emoji in the text** - string literals and manifests, not comments,
  and deliberately not arrows: Titan's own apps write "File -> Settings".
- **the two kinds with a hook contract** (shell add-ons, settings
  interfaces) are checked against their live hook tables and API classes -
  see the shell add-on section above.

The false-positive guard is the important half: **every add-on Titan ships
is run through the same checks by `tests/test_creation_kit_kinds.py`** (45
tests, two of which press Generate with the model stubbed out - the auto-fix
loop is a closure in a worker thread, where a name that is not defined is
not a syntax error but a message box after the user has waited for a
generation), because a wrong report is the expensive mistake - the auto-fix loop
would ask the model to "correct" something that was already right. That
sweep found one real invention in shipped code: `data/components/macros`
falls back to `from src.titan_core.sound import speaker`, which has never
existed.

### The creation kit builds things that take longer than one sitting

A statusbar applet is one round trip. An application with its own file
format, a component with four screens, a launcher, is not - and closing the
dialog used to lose all of it.

- **Questions are a real form** (`QuestionnaireDialog`). The model may ask up
  to 24, and they arrive as `text`, `longtext`, `choice`, `multichoice`,
  `boolean`, `number` (a spin control with a range), `path` and `folder`
  (a field and a Browse button) - each the control it deserves, because a
  control a screen reader already knows how to read needs no explaining.
  Three things make that many questions bearable: a **`section`** per
  question, rendered as a `wx.StaticBox` (a grouping Windows itself knows,
  so a reader says which part of the form the keyboard entered); a **`help`**
  sentence shown under the question and given to the control as its
  description; and **follow-ups** (`depends_on` / `depends_value`) that are
  hidden until the answer they depend on is given - hidden rather than
  disabled, so a form covering every branch of an add-on does not make the
  user tab past the branches they are not building. A `required` question is
  refused empty; a question depending on one that does not exist is dropped
  rather than being invisible for ever.
- **A project is the whole session on disk** (`src/ai/creation_project.py`,
  `%APPDATA%/titosoft/Titan/ai projects/<name>/`): the kind, the
  description, every question and answer, the plan, the conversation and the
  files. Reopen it and the next Generate carries on - the model still has
  the conversation, so "now add a settings page" means what it says. The
  files are written as **real files** under `files/`, so a half-finished
  add-on can be opened in an editor or copied into `data/` by hand and is
  never trapped in a format only this dialog can read.
  - Saved from the wizard's **Save project**, reopened from its **Open
    project...** (the projects of the kind it is building) or from
    **Programmer -> AI -> Projects (continue building)...**, which lists
    every project of every kind and opens the right wizard for the one
    chosen.
  - A named project is **written again after every generation**: an hour of
    work must not depend on the user remembering to press a button.
- **A question has a sound of its own**: `ui/statusbar.ogg` - the status-bar
  cue, deliberately NOT an error sound and not `ai/agent_question.ogg`, which
  reads as one; every theme carries its own, so the cue sounds like the theme
  the user chose. It is played wherever the AI asks something - the creation kit's questionnaire,
  the agent's and the assistant's follow-up questions, and an action that
  needs an answer before it can run (`ai_speech.SOUND_QUESTION` /
  `play_question_sound`, the one place it is named). The question usually
  arrives while the user is listening to a transcript, so the cue is what
  tells them a dialog is there at all.
  - `SOUND_QUESTION` is the whole switch: a name inside `ai/` goes through
    `play_ai_sound` (the feature's own set), anything else is an ordinary
    theme sound played as one, so the cue is changed by changing that string.
  - `play_ai_sound` / `feature_sound_path`, used for the AI's own set, is
    also what `shell_sound_path` is now built on: **the user's own theme
    always wins** (a theme is free to ship its own `ai/` set), and the
    default set fills in only when the user has ticked Settings -> Sounds ->
    "Use equivalent from default theme when a sound is unavailable in the
    selected sound theme" (`sound/fallback_to_default_theme`, read by
    `default_theme_fallback_allowed`). Somebody who turned that off has said
    they do not want sounds their theme has not got, and that answer is not
    the AI's to overrule. The shell's own three sounds keep
    `allow_default=True`, which is the rule they were built with.
  - The assistant's three existing cues (`initialized`, `ui1`, `ui2`) live
    in the same folder and were reached with plain `play_sound`, so on any
    theme but `default` they were silent unless that box was ticked; they go
    the same way now.
- **A test never puts a window in front of whoever runs it.** Both suites
  replace `wx.MessageBox` with a recorder: `load_project` reports a failure
  with a message box, and a test that raises one leaves a modal dialog on
  the user's own desktop waiting for a click nobody knows to give. It was
  read from here as a suite gone slow (55 s), and by the user as Titan
  telling them "That project could not be read" - measured after the guard:
  **0.5 s**. Titan's own speech is stubbed in the same place, for the same
  reason (the SAPI subprocess bridge).
- Tests: `tests/test_creation_projects.py` (40 tests) - the question types,
  the sections, the follow-ups, the answers, the question sound, a project
  round trip through the real wizard, and that **everything `list_projects`
  shows really opens**: the name in the list is the project's own
  (`project.json`), the folder is `safe_name()` of what was typed, and
  `find_project` is what makes the two meet - by the obvious path, then by
  folder name, then by what a project calls itself.

### AI memory across runs

`src/ai/memory.py`. The agent and assistant each began every run with an empty
history, so "and now save it" had nothing to refer to. Two stores under
`%APPDATA%/titosoft/Titan/ai/`: `conversation.jsonl` (recent exchanges replayed
verbatim, older ones surviving as a one-line digest of subjects) and
`notes.jsonl` (facts the user asked to keep, injected in full). `run_agent`
takes `remember=True` and `memory_source`, and the agent and the voice
assistant **share** the memory - one person, one conversation. Tools:
`ai_remember`, `ai_recall`, `ai_list_notes`, `ai_forget`. Settings -> AI
features has the switch, the number of exchanges, and a Forget button.

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
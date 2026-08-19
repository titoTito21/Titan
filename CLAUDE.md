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
    `children` becomes a branch instead of a line.
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
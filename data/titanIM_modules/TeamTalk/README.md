# TeamTalk Titan IM Module

This module adds a Titan-styled TeamTalk entry to Titan IM.

## Supported Now

- Titan IM external module loading through `__im.TCE`
- Titan skin application for module windows and dialogs
- Titan IM sound API for connection, messages, push-to-talk, and errors
- Saved TeamTalk server profiles in the encrypted Titan IM config
- Import of `.tt` files and `tt://` links
- Opening `.tt` files passed to `main.py` as a command-line/file-association argument
- Channels, nested user list, channel text chat, per-user private messages
- File transfer (upload / download / delete) per channel
- Push-to-talk, mute microphone, mute speakers, per-user mute and volume
- Channel admin actions: join, leave, create, delete, kick, ban, move
- Recording: mix the channel's voice into a single WAV or MP3 file
- Media: stream an audio file into the channel, or play one to yourself only
- Server administration (admin accounts): edit server properties, create /
  edit / delete server user accounts, view and remove bans, view server
  statistics, and save the server configuration
- Six-tab right pane (Channel chat / Server log / Private messages / Files /
  Recording and media / Administration) using the Titan-Net row-0 tab bar
  convention; `Ctrl+1`..`Ctrl+6` switch tabs, `Ctrl+R` toggles recording

## Architecture

The `TeamTalkSdkClient` class is the proven event-cache SDK wrapper carried
over from the previous version (connect / login, audio device init, channel
and user caches, voice, files). It is extended here with recording, media
streaming / local playback, and the full administration command set
(`DoUpdateServer`, `DoListUserAccounts`, `DoNewUserAccount`,
`DoDeleteUserAccount`, `DoListBans`, `DoUnbanUserEx`, `DoSaveConfig`,
`DoQueryServerStats`). The UI layer adds the Recording and Administration
tabs plus their dialogs on top of the existing titan-net styled frame.

## TeamTalk SDK

The BearWare TeamTalk 5 SDK Standard Edition v5.22a for Windows x64 is bundled
for this module's runtime integration:

- `lib/TeamTalk5.py` - Python binding (loaded via `libs = lib, sdk` in `__im.TCE`)
- `TeamTalk_DLL/TeamTalk5.dll` - native library on Windows
- `TeamTalk_DLL/TeamTalk.h`
- `TeamTalk_DLL/TeamTalk5.lib`
- `lib/License.txt`

On macOS the binding loads `libTeamTalk5.dylib`; on Linux it loads
`libTeamTalk5.so`. Place those next to `lib/TeamTalk5.py` (the upstream
binding searches `..\\TeamTalk_DLL` only on Windows).

BearWare states that SDK downloads are trial versions that expire after 30 days,
and an end-user application requires a purchased license. See `lib/License.txt`.

Restart Titan and open Titan IM > TeamTalk after updating SDK files.

## Translations

The module ships its own `.po`/`.mo` catalogs under `languages/<lang>/LC_MESSAGES/`
(domain `TeamTalk`). Per TCE policy, every user-facing string is sourced in
English and translated to all available languages (currently `en`, `pl`).

Recompile after editing `.po`:

```
python -m babel.messages.frontend compile \
    -d data/titanIM_modules/TeamTalk/languages -D TeamTalk -f
```

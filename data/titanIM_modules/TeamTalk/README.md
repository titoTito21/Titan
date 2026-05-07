# TeamTalk Titan IM Module

This module adds a Titan-styled TeamTalk entry to Titan IM.

## Supported Now

- Titan IM external module loading through `__im.TCE`
- Titan skin application for module windows and dialogs
- Titan IM sound API for connection, messages, push-to-talk, and errors
- Saved TeamTalk server profiles in the encrypted Titan IM config
- Import of `.tt` files and `tt://` links
- Opening `.tt` files passed to `main.py` as a command-line/file-association argument

## TeamTalk SDK

The BearWare TeamTalk 5 SDK Standard Edition v5.22a for Windows x64 is included
for this module's runtime integration:

- `lib/TeamTalk5.py`
- `TeamTalk_DLL/TeamTalk5.dll`
- `TeamTalk_DLL/TeamTalk.h`
- `TeamTalk_DLL/TeamTalk5.lib`
- `lib/License.txt`

BearWare states that SDK downloads are trial versions that expire after 30 days,
and an end-user application requires a purchased license. See `lib/License.txt`.

Restart Titan and open Titan IM > TeamTalk after updating SDK files.

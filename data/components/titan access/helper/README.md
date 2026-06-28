# titan_access_helper.dll — NVDA controller server

This native helper lets **any application built against the unmodified
`nvdaControllerClient*.dll`** — including `accessible_output3`'s NVDA backend,
which is what the TCE launcher uses to detect a screen reader — drive **Titan
Access** exactly as it would drive NVDA (`speakText`, `cancelSpeech`,
`brailleMessage`, `testIfRunning`).

It implements the same RPC interface NVDA exposes:

* interface UUID `DFF50B99-F7FD-4ca7-A82C-DAEB3E025295`, version 1.0;
* protocol sequence `ncalrpc`, endpoint `NvdaCtlr.<sessionId>.<desktopName>`
  (identical to NVDA, so the stock client binds without modification);
* world + AppContainer access, `RPC_IF_AUTOLISTEN`.

The Python side (`titan_access/nvda_controller_server.py`) loads this DLL, hands
it speak/cancel/braille callbacks that route into the engine, and starts/stops
it with the reader. **Without this DLL the reader still runs** — only the
NVDA-compatibility bridge is disabled.

## Building

You need the **Windows SDK** (for `midl.exe`) and **MSVC** (`cl.exe`), e.g. from
Visual Studio Build Tools. Open a *“x64 Native Tools Command Prompt for VS”*
(64-bit, because Titan ships a 64-bit Python) and run:

```bat
build.bat
```

That runs MIDL on `nvdaController.idl` to generate the server stub, compiles it
with `titan_access_helper.c`, and produces `titan_access_helper.dll` in this
folder. The reader searches the component root, this `helper/` folder, and
`lib/` for it, so no copy step is required.

## Files

* `nvdaController.idl` — the interface (must match NVDA's byte-for-byte).
* `titan_access_helper.c` — RPC registration + manager routines + exports.
* `build.bat` — MIDL + CL build.
* generated at build time: `nvdaController.h`, `nvdaController_s.c`.

## Notes

* If real NVDA is already running it owns the endpoint; our registration backs
  off cleanly (`RPC_S_DUPLICATE_ENDPOINT`) and the reader logs it.
* Disable the bridge without removing the DLL via the setting
  `General/NvdaControllerServer = false`.

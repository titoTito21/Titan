# titan_access_helper.dll — NVDA controller server (plus the two probes)

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

## 32-bit applications

The bridge is bitness-agnostic and **must stay that way**: a 32-bit application
loads `nvdaControllerClient32.dll`, a 64-bit one loads `...64.dll`, and both
reach this 64-bit server over the same local RPC endpoint. Two things protect
that, and both are easy to break:

1. **The stubs are built `/protocol dce`** (see `build.bat`). An x64 MIDL stub
   built `ndr64`-only rejects every 32-bit client with
   `RPC_S_UNSUPPORTED_TRANS_SYN` (1734) — 64-bit apps would work, 32-bit apps
   would not, which is precisely the failure this bridge must never have.
2. **Ownership of the endpoint is checked, reported and retried.** The endpoint
   is a single name: whoever registers it first receives every application's
   calls and everybody else receives none. When another controller (real NVDA,
   or an earlier Titan that has not exited) holds it, the reader now says so
   instead of claiming to be active, and keeps trying — so closing the other
   reader hands the bridge over without restarting Titan.

`nvda_probe32.exe` / `nvda_probe64.exe` are what make this checkable rather than
believable: each binds to the endpoint and calls it exactly as an application
does. The reader runs them from **Screen reader menu (Insert+C) → Test the NVDA
controller bridge**, comparing the helper's call counter before and after, so
the verdict is not "somebody answered" but "**Titan Access** answered, at this
bitness". Run them by hand the same way:

```bat
nvda_probe32.exe "hello from 32 bit"
nvda_probe64.exe "hello from 64 bit"
rem optional second argument: a private endpoint, for testing beside a real reader
```

Each prints one line: `PROBE bits=32 bind=0 test=0 speak=0` — 0 is success,
1722 means nothing is listening, 1734 means a transfer-syntax mismatch (see
point 1 above), 1717 an unknown interface.

## Building

You need the **Windows SDK** (for `midl.exe`) and **MSVC** (`cl.exe`) with both
the x64 and x86 toolsets, e.g. from Visual Studio Build Tools. From an ordinary
command prompt:

```bat
build.bat
```

It calls `vcvarsall.bat` itself for each target (set `VSDEVCMD` to override the
search), runs MIDL on `nvdaController.idl`, and produces
`titan_access_helper.dll`, `nvda_probe64.exe` and `nvda_probe32.exe` in this
folder. The reader searches the component root, this `helper/` folder and `lib/`
for the DLL, so no copy step is required.

## Files

* `nvdaController.idl` — the interface (must match NVDA's byte-for-byte).
* `titan_access_helper.c` — RPC registration + manager routines + exports
  (`start`, `stop`, `lastClientPid`, `callCount`, `ownsEndpoint`,
  `retryEndpoint`, `endpoint`).
* `nvda_probe.c` — the client probe, built for both bitnesses.
* `build.bat` — MIDL + CL build for all three binaries.
* generated at build time: `nvdaController.h`, `nvdaController_s.c`,
  `nvdaController_c.c`.

## Notes

* Disable the bridge without removing the DLL via the setting
  `General/NvdaControllerServer = false`.
* The helper never speaks by itself: it only calls the three Python callbacks,
  so everything an application says goes through Titan's own TTS pipeline.

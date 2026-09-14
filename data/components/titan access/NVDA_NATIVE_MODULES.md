# NVDA's native modules, and what Titan Access has in their place

Read on 2026-09-13 out of NVDA's own `nvdaHelper/readme.md` and the IA2
project's notes (sources at the end), to answer one question: which of the
DLLs and C++ that make NVDA work on the whole of Windows does Titan Access
need, which can it have, and which does it answer another way.

## What NVDA ships that is not Python

| Component | What it does | Runs in |
|---|---|---|
| `nvdaHelperLocal.dll` | RPC client/server stubs, hooking of platform DLLs, text utilities | NVDA's process |
| `nvdaHelperLocalWin10.dll` | OneCore speech and the Windows OCR service (C++/WinRT) | NVDA's process |
| `nvdaHelperRemote.dll` (x86, x64, arm64) | **Injected into every application** on a foreground/focus winEvent; in-process winEvent hooks, the display model (GDI text-out hooks), the virtual buffer backends, and per-process registration of the COM proxies | every application |
| Virtual buffer backends (Gecko/IA2, MSHTML, Adobe, Lotus, ...) | Build and cache an in-process representation of a document - what browse mode walks | the browser's process |
| `UIARemote.dll` | UI Automation remote operations (Windows 11): several UIA reads compiled into one cross-process call | NVDA's process |
| `IAccessible2Proxy.dll` | The COM proxy/stub built from the IA2 IDL, without which an IA2 call across processes cannot be marshalled | registered per process |
| `ISimpleDOM.dll` | The same for Mozilla's ISimpleDOM (maths in Firefox and Chrome) | registered per process |
| MinHook (third party) | The API hooking the display model is built on | inside nvdaHelperRemote |

All of it is GPL-2 (NVDA), so none of it can be shipped inside Titan Access,
which is not. What follows is what Titan Access does instead, piece by
piece, and what is honestly still missing.

## Piece by piece

- **In-process injection and the display model.** NVDA hooks GDI text
  drawing inside every process to know what a program painted where. Titan
  Access injects nothing: the same question is answered by Windows' own OCR
  of the window (`portable/localOcr.py`, `drawnText.py`) and, where a window
  draws its own interface, by the drawn-window watcher (`surface.py`) and
  AI OCR. Slower than a hook and never wrong about licensing.
- **Virtual buffers.** NVDA renders a document inside the browser's process
  and walks the cache. Titan Access builds its buffer from OUTSIDE
  (`virtual_buffer.py`: UI Automation with a cache request, then IA2, MSAA,
  win32, OCR), and with this pass the same document is the **virtual window
  of a web page** - the ZDSR shape: the page's lines, in reading order, each
  knowing the control it starts with (`engine._document_rows`, and the same
  in the NVDA add-on through NVDA's own tree interceptor).
- **The IA2 proxy.** Needed by both readers for an IA2 call into Chromium or
  Gecko. Titan Access now asks the registry first (an installed NVDA or
  Firefox has registered one system-wide) and otherwise registers a proxy
  DLL already on the machine for its own process - `ia2.ensure_proxy()`,
  the way NVDA does it: `DllGetClassObject`, `CoRegisterClassObject`,
  `CoRegisterPSClsid` for every IA2 interface, no registry write, nothing
  copied. Candidates: **this repository's own `lib/IAccessible2Proxy.dll`**
  first (built from the BSD IA2 IDL by `helper/ia2proxy/build.bat` -
  MIDL, then `cl` and `link` with `dlldata.c`, `*_p.c` and `*_i.c`), then
  NVDA's `IAccessible2Proxy.dll` and Firefox's `ia2marshal.dll` /
  `AccessibleMarshal.dll`. A proxy/stub DLL's class object is an
  `IPSFactoryBuffer`, not an `IClassFactory`, and is asked for by one of
  the interface ids it marshals - measured here: registered in-process,
  18 interfaces. With none, IA2 is silently unavailable and UI Automation
  - which needs no proxy and which Chromium and Firefox both expose now -
  is what the reader has.
- **ISimpleDOM.** Not used by Titan Access; maths in a browser is read as
  text.
- **UIARemote.** Titan Access batches its UIA reads through a cache request
  (`uia_cache.py`), which is the same saving in Python where remote
  operations are not available.
- **OneCore speech and Windows OCR** (`nvdaHelperLocalWin10.dll`). Titan
  Access speaks through Titan's own engines, with a voice of its own when
  asked (Settings -> Titan Access: Speech), and reads through Windows' OCR
  via WinRT from Python.
- **Java Access Bridge.** Oracle's `WindowsAccessBridge-64.dll` is an
  out-of-process API - it needs no injection, only a thread that pumps
  messages - so `titan_access/jab.py` reaches it from Python with ctypes:
  `Windows_run` on the engine's own thread, `isJavaWindow`,
  `getAccessibleContextWithFocus`, `getAccessibleContextInfo`, the
  children, the accessible text and the accessible actions. A Java window's
  focus and its tree come through it (the virtual buffer's `jab` tier),
  with Java's role and state names mapped onto Titan Access's.
- **The whole of Windows.** What NVDA's injection buys beyond the above is
  in-process access to a program's own objects (the legacy console's
  buffer, Excel's object model). Titan Access has UIA, MSAA/IA2, JAB,
  win32 and OCR from outside, and app modules where a program needs one.

## Still missing, honestly

1. The legacy console's own buffer.
2. ISimpleDOM (maths).
3. The Java bridge has not been run against a live Java program on this
   machine (there is no Java here); it is written against Oracle's
   documented ABI and answers None for everything without the DLL.

## The display model, and braille, are here now

- **The display model** (`portable/drawnText.py`, the `drawn` buffer
  tier): NVDA's own `getWindowTextInRect`, read for a window whose process
  has an injected reader helper - exact and free, with a rectangle per
  character. It is between the accessibility tiers and OCR; a window that
  draws its text another way, or that has nothing of a reader in it,
  answers nothing and falls through to OCR. That fall-through is the honest
  limit of a reader that does not inject: item 1 above is no longer "read
  by OCR" everywhere, only where a window is genuinely a picture.
- **Braille** (`titan_access/braille.py`): liblouis for the translation
  (NVDA's `liblouis.dll` or a copy in `lib`), the table for Titan's
  language, BRLTTY's BrlAPI for a display and a viewer window otherwise.
  The braille half of a speech scheme applies here.

Sources: [nvdaHelper readme](https://github.com/nvaccess/nvda/blob/master/nvdaHelper/readme.md),
[IA2 COM proxy DLL](https://wiki.linuxfoundation.org/accessibility/iaccessible2/comproxydll),
[NVDA PR 7535: registering proxies per process](https://github.com/nvaccess/nvda/pull/7535),
[Mozilla bug 431480: Firefox's IA2 proxy](https://bugzilla.mozilla.org/show_bug.cgi?id=431480),
[registering a proxy DLL without the registry](https://lists.linux-foundation.org/pipermail/accessibility-ia2/2008-March/000452.html).

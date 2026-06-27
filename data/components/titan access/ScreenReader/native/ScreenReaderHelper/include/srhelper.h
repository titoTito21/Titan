/*
 * ScreenReaderHelper.dll - native low-level helper for the Polish screen reader.
 *
 * This DLL owns the genuinely low-level surface that previously lived as P/Invoke
 * scattered across the managed code:
 *   - global low-level keyboard / mouse hooks (WH_KEYBOARD_LL / WH_MOUSE_LL)
 *   - the foreground-window event hook (SetWinEventHook)
 *   - input synthesis (SendInput)
 *   - window / cursor helpers
 *
 * The hooks run on a dedicated native thread with its own message loop, so hook
 * latency is not affected by managed GC pauses or the WinForms message pump.
 * Callbacks are invoked on that native thread; the managed side must be
 * thread-safe (it already is).
 *
 * All exported functions use the C ABI (cdecl) so they map cleanly to C#
 * [DllImport]. Keep this header and Native/NativeHelper.cs in sync.
 */
#ifndef SRHELPER_H
#define SRHELPER_H

#include <stdint.h>

#ifdef SRHELPER_EXPORTS
#define SRH_API __declspec(dllexport)
#else
#define SRH_API __declspec(dllimport)
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ---- callback signatures ------------------------------------------------ */

/*
 * Keyboard hook callback. Receives the already-decoded KBDLLHOOKSTRUCT fields
 * so the managed side never has to marshal native structs.
 *   isKeyDown: 1 for WM_KEYDOWN/WM_SYSKEYDOWN, 0 for key-up.
 * Return 1 to swallow the key (do not pass to the rest of the system), 0 to
 * let it through.
 */
typedef int (__stdcall *SrhKeyboardCallback)(int vkCode, int scanCode, int flags, int isKeyDown);

/*
 * Mouse hook callback.
 *   message:   WM_MOUSEMOVE / WM_LBUTTONDOWN / ... (raw window message id)
 *   x, y:      screen coordinates
 *   mouseData: high word holds wheel delta for WM_MOUSEWHEEL
 * Return 1 to swallow the event, 0 to let it through.
 */
typedef int (__stdcall *SrhMouseCallback)(int message, int x, int y, int mouseData);

/*
 * WinEvent callback (SetWinEventHook). Receives the full event tuple so a
 * single native hook surface can serve foreground-change tracking, live-region
 * monitoring, dialog detection, etc.
 *   eventType: EVENT_* constant
 *   hwnd:      window the event originates from
 *   idObject:  OBJID_* / object id from the event
 *   idChild:   child id from the event (CHILDID_SELF when not applicable)
 */
typedef void (__stdcall *SrhWinEventCallback)(uint32_t eventType, void *hwnd,
                                              int32_t idObject, int32_t idChild);

/* ---- lifecycle ---------------------------------------------------------- */

/* Starts the dedicated hook thread + message loop. Returns 1 on success. */
SRH_API int __cdecl SrhInitialize(void);

/* Removes every hook and stops the hook thread. Safe to call repeatedly. */
SRH_API void __cdecl SrhShutdown(void);

/* DLL build version, for a sanity check from managed code. */
SRH_API int __cdecl SrhGetVersion(void);

/* ---- hooks -------------------------------------------------------------- */

SRH_API int  __cdecl SrhKeyboardHookInstall(SrhKeyboardCallback cb);
SRH_API void __cdecl SrhKeyboardHookUninstall(void);

SRH_API int  __cdecl SrhMouseHookInstall(SrhMouseCallback cb);
SRH_API void __cdecl SrhMouseHookUninstall(void);

/*
 * Installs a WinEvent hook for the [eventMin, eventMax] range on the dedicated
 * hook thread. Multiple hooks can be installed concurrently (e.g. one for
 * foreground changes, one for live-region/name/value changes); each gets its
 * own callback. Returns a hook id >= 1 on success, or 0 on failure (invalid
 * args, no free slot, or SetWinEventHook failed).
 */
SRH_API int  __cdecl SrhWinEventHookInstall(SrhWinEventCallback cb,
                                            uint32_t eventMin, uint32_t eventMax);

/* Removes the WinEvent hook with the given id. Safe to call with a stale id. */
SRH_API void __cdecl SrhWinEventHookUninstall(int hookId);

/* ---- input synthesis ---------------------------------------------------- */

/* Press (down != 0) or release a single virtual key via SendInput. */
SRH_API void __cdecl SrhSendKey(uint16_t vk, int down);

/*
 * Sends a chord: presses vks[0..count-1] in order, then releases them in
 * reverse order. Used for Alt+Tab, Win+D, etc.
 */
SRH_API void __cdecl SrhSendKeyCombo(const uint16_t *vks, int count);

/* Types a single Unicode character via SendInput (KEYEVENTF_UNICODE). */
SRH_API void __cdecl SrhSendUnicode(uint16_t ch);

/* Absolute mouse move (screen pixels) via SendInput. */
SRH_API void __cdecl SrhMouseMove(int x, int y);

/* button: 0 = left, 1 = right, 2 = middle. isDouble != 0 sends two clicks. */
SRH_API void __cdecl SrhMouseClick(int button, int isDouble);

SRH_API int  __cdecl SrhSetCursorPos(int x, int y);
SRH_API int  __cdecl SrhGetCursorPos(int *x, int *y);

/* Non-toggling async key state read (GetAsyncKeyState high bit). */
SRH_API int  __cdecl SrhIsKeyPressed(int vk);

/* ---- window / cursor helpers ------------------------------------------- */

SRH_API void *__cdecl SrhGetForegroundWindow(void);

/*
 * Writes the lower-cased executable name (no path, no extension) of the
 * process that owns hwnd into buf (UTF-16). Returns the number of characters
 * written, or 0 on failure.
 */
SRH_API int  __cdecl SrhGetWindowProcessName(void *hwnd, uint16_t *buf, int bufLen);

SRH_API int  __cdecl SrhGetWindowRect(void *hwnd, int *left, int *top, int *right, int *bottom);

/* Returns 1 if the window is currently maximized. */
SRH_API int  __cdecl SrhIsWindowMaximized(void *hwnd);
SRH_API int  __cdecl SrhMaximizeWindow(void *hwnd);
SRH_API int  __cdecl SrhRestoreWindow(void *hwnd);

/* Confines the cursor to hwnd's bounds; SrhClipCursorClear() releases it. */
SRH_API void __cdecl SrhClipCursorToWindow(void *hwnd);
SRH_API void __cdecl SrhClipCursorClear(void);

/* ---- GDI display model -------------------------------------------------- */

/*
 * Starts the GDI display model. Publishes this process's PID in a named
 * section and installs a global WH_GETMESSAGE hook whose DLL is srremote.dll,
 * which Windows then maps into every GUI process. srremote.dll IAT-hooks
 * ExtTextOutW there and records on-screen text into a per-process shared
 * section. srremote.dll must sit next to ScreenReaderHelper.dll.
 * Returns 1 on success, 0 on failure. Idempotent.
 */
SRH_API int  __cdecl SrhDisplayModelStart(void);

/* Stops the display model: removes the injection hook, unpublishes the PID,
 * and unloads srremote.dll from the host process. Safe to call repeatedly. */
SRH_API void __cdecl SrhDisplayModelStop(void);

/*
 * Reads the recorded on-screen text for hwnd into buf (UTF-16). Text runs are
 * de-duplicated by position, ordered top-to-bottom then left-to-right, and
 * joined with newlines. Returns the number of characters written (excluding
 * the null terminator), or 0 if nothing is recorded for that window's process.
 */
SRH_API int  __cdecl SrhDisplayModelGetText(void *hwnd, uint16_t *buf, int bufLen);

#ifdef __cplusplus
}
#endif

#endif /* SRHELPER_H */

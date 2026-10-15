/*
 * ScreenReaderHelper.dll - implementation.
 *
 * Design: SrhInitialize() spins up one dedicated "hook thread" that creates a
 * message-only window and runs a GetMessage loop. Low-level hooks
 * (WH_KEYBOARD_LL, WH_MOUSE_LL) and the WinEvent hook are all installed *from*
 * that thread, because the OS delivers their callbacks to the thread that
 * installed them and that thread must pump messages.
 *
 * The public install/uninstall functions are called from managed threads; they
 * forward the request to the hook thread via SendMessage to the message-only
 * window, which makes the operation synchronous and lets us return a result.
 */
#define WIN32_LEAN_AND_MEAN
#define SRHELPER_EXPORTS
#include "srhelper.h"
#include "srdisplay_shared.h"

#include <windows.h>
#include <psapi.h>
#include <string>
#include <algorithm>
#include <cstdio>

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "kernel32.lib")

/* ---- shared state ------------------------------------------------------- */

namespace {

HANDLE  g_hookThread       = nullptr;
DWORD   g_hookThreadId     = 0;
HWND    g_msgWindow        = nullptr;
HANDLE  g_readyEvent       = nullptr;   /* signalled once the hook thread is up */

HHOOK   g_keyboardHook     = nullptr;
HHOOK   g_mouseHook        = nullptr;

SrhKeyboardCallback g_kbCallback    = nullptr;
SrhMouseCallback    g_mouseCallback = nullptr;

/*
 * WinEvent hooks. Several consumers (foreground tracking, live-region
 * monitoring, dialog detection) each install their own hook for a different
 * event range, so we keep a small fixed table of slots. The slot index + 1 is
 * the hook id handed back to managed code.
 */
constexpr int SRH_MAX_WINEVENT_HOOKS = 16;
struct WinEventSlot {
    HWINEVENTHOOK       hook = nullptr;
    SrhWinEventCallback cb   = nullptr;
};
WinEventSlot g_winSlots[SRH_MAX_WINEVENT_HOOKS] = {};

/* GDI display model: global injection hook + the host-PID section. */
HHOOK   g_getMsgHook       = nullptr;   /* WH_GETMESSAGE hook that injects srremote */
HMODULE g_srRemote         = nullptr;   /* loaded srremote.dll in the host process */
HANDLE  g_hostPidSection   = nullptr;   /* publishes our PID so srremote skips us */

/* Staging slots for the next install/uninstall request handled on the hook
 * thread. Safe to share because every request is synchronous (SendMessage). */
void    *g_pendingCallback = nullptr;
uint32_t g_pendingEventMin = 0;
uint32_t g_pendingEventMax = 0;
int      g_pendingHookId   = 0;

/* Custom messages dispatched to the hook thread's message-only window. */
constexpr UINT SRH_MSG_KB_INSTALL    = WM_APP + 1;
constexpr UINT SRH_MSG_KB_UNINSTALL  = WM_APP + 2;
constexpr UINT SRH_MSG_MOUSE_INSTALL = WM_APP + 3;
constexpr UINT SRH_MSG_MOUSE_UNINSTALL = WM_APP + 4;
constexpr UINT SRH_MSG_WIN_INSTALL   = WM_APP + 5;
constexpr UINT SRH_MSG_WIN_UNINSTALL = WM_APP + 6;
constexpr UINT SRH_MSG_DM_INSTALL    = WM_APP + 7;
constexpr UINT SRH_MSG_DM_UNINSTALL  = WM_APP + 8;

/* ---- hook procedures (run on the hook thread) --------------------------- */

LRESULT CALLBACK KeyboardProc(int nCode, WPARAM wParam, LPARAM lParam) {
    if (nCode == HC_ACTION && g_kbCallback) {
        const KBDLLHOOKSTRUCT *k = reinterpret_cast<const KBDLLHOOKSTRUCT *>(lParam);
        const int isKeyDown = (wParam == WM_KEYDOWN || wParam == WM_SYSKEYDOWN) ? 1 : 0;
        const int swallow = g_kbCallback(
            static_cast<int>(k->vkCode),
            static_cast<int>(k->scanCode),
            static_cast<int>(k->flags),
            isKeyDown);
        if (swallow)
            return 1;
    }
    return CallNextHookEx(g_keyboardHook, nCode, wParam, lParam);
}

LRESULT CALLBACK MouseProc(int nCode, WPARAM wParam, LPARAM lParam) {
    if (nCode == HC_ACTION && g_mouseCallback) {
        const MSLLHOOKSTRUCT *m = reinterpret_cast<const MSLLHOOKSTRUCT *>(lParam);
        const int swallow = g_mouseCallback(
            static_cast<int>(wParam),
            m->pt.x,
            m->pt.y,
            static_cast<int>(m->mouseData));
        if (swallow)
            return 1;
    }
    return CallNextHookEx(g_mouseHook, nCode, wParam, lParam);
}

void CALLBACK WinEventProc(HWINEVENTHOOK hHook, DWORD event, HWND hwnd,
                           LONG idObject, LONG idChild, DWORD, DWORD) {
    if (hwnd == nullptr)
        return;
    /* The OS gives us the originating hook handle; match it to a slot so the
     * right consumer's callback fires. */
    for (const WinEventSlot &slot : g_winSlots) {
        if (slot.hook == hHook && slot.cb) {
            slot.cb(static_cast<uint32_t>(event), hwnd,
                    static_cast<int32_t>(idObject), static_cast<int32_t>(idChild));
            return;
        }
    }
}

/* ---- message-only window on the hook thread ----------------------------- */

LRESULT CALLBACK MsgWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
    case SRH_MSG_KB_INSTALL: {
        if (g_keyboardHook) return 1;
        g_kbCallback = reinterpret_cast<SrhKeyboardCallback>(g_pendingCallback);
        g_keyboardHook = SetWindowsHookExW(WH_KEYBOARD_LL, KeyboardProc,
                                           GetModuleHandleW(nullptr), 0);
        return g_keyboardHook ? 1 : 0;
    }
    case SRH_MSG_KB_UNINSTALL: {
        if (g_keyboardHook) {
            UnhookWindowsHookEx(g_keyboardHook);
            g_keyboardHook = nullptr;
        }
        g_kbCallback = nullptr;
        return 1;
    }
    case SRH_MSG_MOUSE_INSTALL: {
        if (g_mouseHook) return 1;
        g_mouseCallback = reinterpret_cast<SrhMouseCallback>(g_pendingCallback);
        g_mouseHook = SetWindowsHookExW(WH_MOUSE_LL, MouseProc,
                                        GetModuleHandleW(nullptr), 0);
        return g_mouseHook ? 1 : 0;
    }
    case SRH_MSG_MOUSE_UNINSTALL: {
        if (g_mouseHook) {
            UnhookWindowsHookEx(g_mouseHook);
            g_mouseHook = nullptr;
        }
        g_mouseCallback = nullptr;
        return 1;
    }
    case SRH_MSG_WIN_INSTALL: {
        int slot = -1;
        for (int i = 0; i < SRH_MAX_WINEVENT_HOOKS; ++i) {
            if (g_winSlots[i].hook == nullptr) { slot = i; break; }
        }
        if (slot < 0)
            return 0; /* no free slot */
        HWINEVENTHOOK h = SetWinEventHook(
            g_pendingEventMin, g_pendingEventMax,
            nullptr, WinEventProc, 0, 0, WINEVENT_OUTOFCONTEXT);
        if (!h)
            return 0;
        g_winSlots[slot].hook = h;
        g_winSlots[slot].cb   = reinterpret_cast<SrhWinEventCallback>(g_pendingCallback);
        return slot + 1; /* hook id */
    }
    case SRH_MSG_WIN_UNINSTALL: {
        int idx = g_pendingHookId - 1;
        if (idx >= 0 && idx < SRH_MAX_WINEVENT_HOOKS && g_winSlots[idx].hook) {
            UnhookWinEvent(g_winSlots[idx].hook);
            g_winSlots[idx].hook = nullptr;
            g_winSlots[idx].cb   = nullptr;
        }
        return 1;
    }
    case SRH_MSG_DM_INSTALL: {
        if (g_getMsgHook) return 1;
        HOOKPROC proc = reinterpret_cast<HOOKPROC>(g_pendingCallback);
        if (!proc || !g_srRemote) return 0;
        /* Global WH_GETMESSAGE hook: Windows maps srremote.dll into every GUI
         * process that pumps messages, which is what runs the GDI hooks. */
        g_getMsgHook = SetWindowsHookExW(WH_GETMESSAGE, proc, g_srRemote, 0);
        return g_getMsgHook ? 1 : 0;
    }
    case SRH_MSG_DM_UNINSTALL: {
        if (g_getMsgHook) {
            UnhookWindowsHookEx(g_getMsgHook);
            g_getMsgHook = nullptr;
        }
        return 1;
    }
    default:
        return DefWindowProcW(hwnd, msg, wParam, lParam);
    }
}

DWORD WINAPI HookThreadMain(LPVOID) {
    /* A message-only window is enough to receive our control messages and to
     * give the LL hooks a thread with a pumped message queue. */
    WNDCLASSEXW wc = {};
    wc.cbSize        = sizeof(wc);
    wc.lpfnWndProc   = MsgWndProc;
    wc.hInstance     = GetModuleHandleW(nullptr);
    wc.lpszClassName = L"ScreenReaderHelperHookWnd";
    RegisterClassExW(&wc);

    g_msgWindow = CreateWindowExW(0, wc.lpszClassName, L"", 0,
                                  0, 0, 0, 0, HWND_MESSAGE,
                                  nullptr, wc.hInstance, nullptr);

    /* Ensure this thread has a message queue before anyone posts to it. */
    MSG msg;
    PeekMessageW(&msg, nullptr, WM_USER, WM_USER, PM_NOREMOVE);
    SetEvent(g_readyEvent);

    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    if (g_msgWindow) {
        DestroyWindow(g_msgWindow);
        g_msgWindow = nullptr;
    }
    UnregisterClassW(wc.lpszClassName, wc.hInstance);
    return 0;
}

/* Sends a control message synchronously to the hook thread. */
LRESULT CallHookThread(UINT msg, void *pendingCallback) {
    if (!g_msgWindow)
        return 0;
    g_pendingCallback = pendingCallback;
    return SendMessageW(g_msgWindow, msg, 0, 0);
}

void SendOneKey(uint16_t vk, bool down) {
    INPUT in = {};
    in.type       = INPUT_KEYBOARD;
    in.ki.wVk     = vk;
    in.ki.dwFlags = down ? 0 : KEYEVENTF_KEYUP;
    SendInput(1, &in, sizeof(INPUT));
}

} /* anonymous namespace */

/* ---- exported lifecycle ------------------------------------------------- */

extern "C" SRH_API int __cdecl SrhInitialize(void) {
    if (g_hookThread)
        return 1;

    g_readyEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!g_readyEvent)
        return 0;

    g_hookThread = CreateThread(nullptr, 0, HookThreadMain, nullptr, 0, &g_hookThreadId);
    if (!g_hookThread) {
        CloseHandle(g_readyEvent);
        g_readyEvent = nullptr;
        return 0;
    }

    WaitForSingleObject(g_readyEvent, 5000);
    return g_msgWindow ? 1 : 0;
}

extern "C" SRH_API void __cdecl SrhShutdown(void) {
    if (!g_hookThread)
        return;

    SrhDisplayModelStop();
    CallHookThread(SRH_MSG_KB_UNINSTALL, nullptr);
    CallHookThread(SRH_MSG_MOUSE_UNINSTALL, nullptr);
    for (int i = 0; i < SRH_MAX_WINEVENT_HOOKS; ++i) {
        g_pendingHookId = i + 1;
        CallHookThread(SRH_MSG_WIN_UNINSTALL, nullptr);
    }

    if (g_hookThreadId)
        PostThreadMessageW(g_hookThreadId, WM_QUIT, 0, 0);

    WaitForSingleObject(g_hookThread, 5000);
    CloseHandle(g_hookThread);
    g_hookThread   = nullptr;
    g_hookThreadId = 0;

    if (g_readyEvent) {
        CloseHandle(g_readyEvent);
        g_readyEvent = nullptr;
    }
}

extern "C" SRH_API int __cdecl SrhGetVersion(void) {
    return 1;
}

/* ---- exported hooks ----------------------------------------------------- */

extern "C" SRH_API int __cdecl SrhKeyboardHookInstall(SrhKeyboardCallback cb) {
    return static_cast<int>(CallHookThread(SRH_MSG_KB_INSTALL, reinterpret_cast<void *>(cb)));
}
extern "C" SRH_API void __cdecl SrhKeyboardHookUninstall(void) {
    CallHookThread(SRH_MSG_KB_UNINSTALL, nullptr);
}
extern "C" SRH_API int __cdecl SrhMouseHookInstall(SrhMouseCallback cb) {
    return static_cast<int>(CallHookThread(SRH_MSG_MOUSE_INSTALL, reinterpret_cast<void *>(cb)));
}
extern "C" SRH_API void __cdecl SrhMouseHookUninstall(void) {
    CallHookThread(SRH_MSG_MOUSE_UNINSTALL, nullptr);
}
extern "C" SRH_API int __cdecl SrhWinEventHookInstall(SrhWinEventCallback cb,
                                                      uint32_t eventMin, uint32_t eventMax) {
    if (!cb)
        return 0;
    g_pendingEventMin = eventMin;
    g_pendingEventMax = eventMax;
    return static_cast<int>(CallHookThread(SRH_MSG_WIN_INSTALL, reinterpret_cast<void *>(cb)));
}
extern "C" SRH_API void __cdecl SrhWinEventHookUninstall(int hookId) {
    g_pendingHookId = hookId;
    CallHookThread(SRH_MSG_WIN_UNINSTALL, nullptr);
}

/* ---- exported input synthesis ------------------------------------------ */

extern "C" SRH_API void __cdecl SrhSendKey(uint16_t vk, int down) {
    SendOneKey(vk, down != 0);
}

extern "C" SRH_API void __cdecl SrhSendKeyCombo(const uint16_t *vks, int count) {
    if (!vks || count <= 0 || count > 8)
        return;
    for (int i = 0; i < count; ++i)
        SendOneKey(vks[i], true);
    for (int i = count - 1; i >= 0; --i)
        SendOneKey(vks[i], false);
}

extern "C" SRH_API void __cdecl SrhSendUnicode(uint16_t ch) {
    INPUT in[2] = {};
    in[0].type       = INPUT_KEYBOARD;
    in[0].ki.wScan   = ch;
    in[0].ki.dwFlags = KEYEVENTF_UNICODE;
    in[1] = in[0];
    in[1].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
    SendInput(2, in, sizeof(INPUT));
}

extern "C" SRH_API void __cdecl SrhMouseMove(int x, int y) {
    const int sw = GetSystemMetrics(SM_CXSCREEN);
    const int sh = GetSystemMetrics(SM_CYSCREEN);
    if (sw <= 0 || sh <= 0)
        return;
    INPUT in = {};
    in.type       = INPUT_MOUSE;
    in.mi.dx      = static_cast<LONG>(x * 65535.0 / sw);
    in.mi.dy      = static_cast<LONG>(y * 65535.0 / sh);
    in.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    SendInput(1, &in, sizeof(INPUT));
}

extern "C" SRH_API void __cdecl SrhMouseClick(int button, int isDouble) {
    DWORD down, up;
    switch (button) {
    case 1:  down = MOUSEEVENTF_RIGHTDOWN;  up = MOUSEEVENTF_RIGHTUP;  break;
    case 2:  down = MOUSEEVENTF_MIDDLEDOWN; up = MOUSEEVENTF_MIDDLEUP; break;
    default: down = MOUSEEVENTF_LEFTDOWN;   up = MOUSEEVENTF_LEFTUP;   break;
    }
    const int clicks = isDouble ? 2 : 1;
    for (int i = 0; i < clicks; ++i) {
        INPUT in[2] = {};
        in[0].type = INPUT_MOUSE; in[0].mi.dwFlags = down;
        in[1].type = INPUT_MOUSE; in[1].mi.dwFlags = up;
        SendInput(2, in, sizeof(INPUT));
    }
}

extern "C" SRH_API int __cdecl SrhSetCursorPos(int x, int y) {
    return SetCursorPos(x, y) ? 1 : 0;
}

extern "C" SRH_API int __cdecl SrhGetCursorPos(int *x, int *y) {
    POINT p;
    if (!GetCursorPos(&p))
        return 0;
    if (x) *x = p.x;
    if (y) *y = p.y;
    return 1;
}

extern "C" SRH_API int __cdecl SrhIsKeyPressed(int vk) {
    return (GetAsyncKeyState(vk) & 0x8000) ? 1 : 0;
}

/* ---- exported window helpers ------------------------------------------- */

extern "C" SRH_API void *__cdecl SrhGetForegroundWindow(void) {
    return GetForegroundWindow();
}

extern "C" SRH_API int __cdecl SrhGetWindowProcessName(void *hwnd, uint16_t *buf, int bufLen) {
    if (!hwnd || !buf || bufLen <= 0)
        return 0;

    DWORD pid = 0;
    GetWindowThreadProcessId(static_cast<HWND>(hwnd), &pid);
    if (!pid)
        return 0;

    HANDLE proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!proc)
        return 0;

    wchar_t path[MAX_PATH] = {};
    DWORD len = MAX_PATH;
    const BOOL ok = QueryFullProcessImageNameW(proc, 0, path, &len);
    CloseHandle(proc);
    if (!ok || len == 0)
        return 0;

    /* strip directory */
    const wchar_t *name = path;
    for (const wchar_t *p = path; *p; ++p)
        if (*p == L'\\' || *p == L'/')
            name = p + 1;

    /* strip extension + lower-case into buf */
    int out = 0;
    for (const wchar_t *p = name; *p && *p != L'.' && out < bufLen - 1; ++p, ++out)
        buf[out] = static_cast<uint16_t>(towlower(*p));
    buf[out] = 0;
    return out;
}

extern "C" SRH_API int __cdecl SrhGetWindowRect(void *hwnd, int *left, int *top,
                                                int *right, int *bottom) {
    RECT r;
    if (!hwnd || !GetWindowRect(static_cast<HWND>(hwnd), &r))
        return 0;
    if (left)   *left   = r.left;
    if (top)    *top    = r.top;
    if (right)  *right  = r.right;
    if (bottom) *bottom = r.bottom;
    return 1;
}

extern "C" SRH_API int __cdecl SrhIsWindowMaximized(void *hwnd) {
    WINDOWPLACEMENT wp = {};
    wp.length = sizeof(wp);
    if (!hwnd || !GetWindowPlacement(static_cast<HWND>(hwnd), &wp))
        return 0;
    return wp.showCmd == SW_SHOWMAXIMIZED ? 1 : 0;
}

extern "C" SRH_API int __cdecl SrhMaximizeWindow(void *hwnd) {
    if (!hwnd)
        return 0;
    return ShowWindow(static_cast<HWND>(hwnd), SW_MAXIMIZE) ? 1 : 0;
}

extern "C" SRH_API int __cdecl SrhRestoreWindow(void *hwnd) {
    if (!hwnd)
        return 0;
    return ShowWindow(static_cast<HWND>(hwnd), SW_RESTORE) ? 1 : 0;
}

extern "C" SRH_API void __cdecl SrhClipCursorToWindow(void *hwnd) {
    RECT r;
    if (hwnd && GetWindowRect(static_cast<HWND>(hwnd), &r))
        ClipCursor(&r);
}

extern "C" SRH_API void __cdecl SrhClipCursorClear(void) {
    ClipCursor(nullptr);
}

/* ---- exported GDI display model ---------------------------------------- */

namespace {

/* Builds the full path to srremote.dll, assumed to sit next to this DLL. */
bool BuildSrRemotePath(wchar_t *out, size_t cap) {
    HMODULE self = GetModuleHandleW(L"ScreenReaderHelper.dll");
    if (!self)
        return false;
    wchar_t path[MAX_PATH] = {};
    if (GetModuleFileNameW(self, path, MAX_PATH) == 0)
        return false;
    /* strip the file name */
    wchar_t *slash = nullptr;
    for (wchar_t *p = path; *p; ++p)
        if (*p == L'\\' || *p == L'/')
            slash = p;
    if (slash)
        *(slash + 1) = 0;
    else
        path[0] = 0;
    int n = _snwprintf_s(out, cap, _TRUNCATE, L"%ssrremote.dll", path);
    return n > 0;
}

} /* anonymous namespace */

extern "C" SRH_API int __cdecl SrhDisplayModelStart(void) {
    if (g_getMsgHook)
        return 1; /* already running */

    /* Publish our PID so srremote.dll knows to stay inert in the host process. */
    if (!g_hostPidSection) {
        g_hostPidSection = CreateFileMappingA(
            INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE,
            0, sizeof(DWORD), SRD_HOSTPID_SECTION);
        if (!g_hostPidSection)
            return 0;
        if (auto *p = static_cast<DWORD *>(
                MapViewOfFile(g_hostPidSection, FILE_MAP_WRITE, 0, 0, sizeof(DWORD)))) {
            *p = GetCurrentProcessId();
            UnmapViewOfFile(p);
        }
    }

    if (!g_srRemote) {
        wchar_t remotePath[MAX_PATH] = {};
        if (!BuildSrRemotePath(remotePath, MAX_PATH))
            return 0;
        g_srRemote = LoadLibraryW(remotePath);
        if (!g_srRemote)
            return 0;
    }

    void *proc = reinterpret_cast<void *>(GetProcAddress(g_srRemote, "SrRemoteHookProc"));
    if (!proc)
        return 0;

    g_pendingCallback = proc;
    return static_cast<int>(CallHookThread(SRH_MSG_DM_INSTALL, proc)) ? 1 : 0;
}

extern "C" SRH_API void __cdecl SrhDisplayModelStop(void) {
    if (g_getMsgHook)
        CallHookThread(SRH_MSG_DM_UNINSTALL, nullptr);

    if (g_srRemote) {
        FreeLibrary(g_srRemote);
        g_srRemote = nullptr;
    }
    if (g_hostPidSection) {
        CloseHandle(g_hostPidSection);
        g_hostPidSection = nullptr;
    }
}

extern "C" SRH_API int __cdecl SrhDisplayModelGetText(void *hwnd, uint16_t *buf, int bufLen) {
    if (!hwnd || !buf || bufLen <= 0)
        return 0;
    buf[0] = 0;

    DWORD pid = 0;
    GetWindowThreadProcessId(static_cast<HWND>(hwnd), &pid);
    if (!pid)
        return 0;

    char secName[64], mtxName[64];
    sprintf_s(secName, SRD_SECTION_FMT, pid);
    sprintf_s(mtxName, SRD_MUTEX_FMT, pid);

    HANDLE section = OpenFileMappingA(FILE_MAP_READ, FALSE, secName);
    if (!section)
        return 0;

    HANDLE mutex = OpenMutexA(SYNCHRONIZE, FALSE, mtxName);
    auto *shared = static_cast<SrdSharedHeader *>(
        MapViewOfFile(section, FILE_MAP_READ, 0, 0, sizeof(SrdSharedHeader)));

    int written = 0;
    if (shared && shared->magic == SRD_MAGIC) {
        if (mutex)
            WaitForSingleObject(mutex, 100);

        /* Copy the records for this window out of the (live) ring. */
        static SrdRecord snapshot[SRD_RING_CAPACITY];
        int n = 0;
        uint64_t target = reinterpret_cast<uint64_t>(hwnd);
        for (uint32_t i = 0; i < SRD_RING_CAPACITY; ++i) {
            const SrdRecord &r = shared->records[i];
            if (r.seq != 0 && r.hwnd == target && r.text[0] != 0)
                snapshot[n++] = r;
        }

        if (mutex)
            ReleaseMutex(mutex);

        /* De-duplicate by position, keeping the newest record per (left, top):
         * redraws of the same spot pile up many identical records. */
        std::sort(snapshot, snapshot + n, [](const SrdRecord &a, const SrdRecord &b) {
            if (a.left != b.left) return a.left < b.left;
            if (a.top  != b.top)  return a.top  < b.top;
            return a.seq > b.seq; /* newest first within a position */
        });
        int unique = 0;
        for (int i = 0; i < n; ++i) {
            if (i > 0 &&
                snapshot[i].left == snapshot[unique - 1].left &&
                snapshot[i].top  == snapshot[unique - 1].top)
                continue; /* older duplicate of a position already kept */
            snapshot[unique++] = snapshot[i];
        }

        /* Reading order: top-to-bottom, then left-to-right. */
        std::sort(snapshot, snapshot + unique, [](const SrdRecord &a, const SrdRecord &b) {
            if (a.top != b.top) return a.top < b.top;
            return a.left < b.left;
        });

        for (int i = 0; i < unique && written < bufLen - 1; ++i) {
            if (i > 0 && written < bufLen - 1)
                buf[written++] = L'\n';
            for (const uint16_t *p = snapshot[i].text; *p && written < bufLen - 1; ++p)
                buf[written++] = *p;
        }
        buf[written] = 0;
    }

    if (shared)  UnmapViewOfFile(shared);
    if (mutex)   CloseHandle(mutex);
    CloseHandle(section);
    return written;
}

/* ---- DllMain ------------------------------------------------------------ */

BOOL APIENTRY DllMain(HMODULE, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_DETACH)
        SrhShutdown();
    return TRUE;
}

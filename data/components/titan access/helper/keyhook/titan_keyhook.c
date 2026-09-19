/*
 * titan_keyhook.c -- the keyboard the reader cannot lose.
 *
 * Titan Access reads the keyboard with a WH_KEYBOARD_LL hook whose callback
 * is Python. Windows gives a low-level hook a few hundred milliseconds
 * (LowLevelHooksTimeout) to answer each key; a callback that is late once
 * too often is UNHOOKED, silently, and the reader goes on believing it has
 * the keyboard while every key goes past it. That is the worst failure a
 * screen reader can have: it looks exactly like "the arrows stopped
 * working" and nothing in the reader says why.
 *
 * This DLL owns the hook instead, on a thread of its own, and answers
 * Windows within a deadline whatever Python is doing:
 *
 *   * the hook procedure hands the key to a DECIDER thread and waits for
 *     its answer at most `timeoutMs`; the decider calls Python (which may
 *     take the interpreter lock, speak, read a window). A late answer is
 *     thrown away and the key goes through to the application - a key the
 *     reader wanted to keep is lost once, which is a smaller loss than the
 *     whole keyboard;
 *   * a WATCHDOG thread notices input Windows saw and the hooks did not
 *     (GetLastInputInfo against the hooks' own clock) and installs them
 *     again - which is the recovery Windows never offers;
 *   * a mouse hook rides beside it, for the watchdog's clock and for a
 *     reader that wants the pointer later.
 *
 * Also here, because it is the same subject - a reader that must survive
 * other processes: `TitanHook_IsWindowResponding`, which asks a window
 * with a deadline (IsHungAppWindow, then SendMessageTimeout of WM_NULL)
 * before the reader spends seconds of COM on a window that will never
 * answer.
 *
 * Build: helper/keyhook/build.bat (MSVC x64) -> lib/titan_keyhook.dll.
 * Python: titan_access/native_hook.py. Without the DLL the reader keeps its
 * own Python hook, exactly as before.
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#define WM_TITAN_REHOOK (WM_APP + 41)
#define WM_TITAN_STOP   (WM_APP + 42)

typedef int (__stdcall *TitanHookDecider)(unsigned vk, unsigned scan,
                                          unsigned flags, unsigned isDown,
                                          unsigned __int64 extra);

typedef struct TitanHookStatus {
    unsigned installed;        /* both hooks are in */
    unsigned events;           /* keys seen by the hook procedure */
    unsigned swallowed;        /* keys the decider kept */
    unsigned passed;           /* keys handed on to the application */
    unsigned late;             /* keys passed on because the decider was late */
    unsigned reinstalls;       /* times the watchdog put the hooks back */
    unsigned mouseEvents;      /* mouse events seen (the watchdog's clock) */
    unsigned lastKeyTick;      /* GetTickCount of the last key seen */
    unsigned lastInputTick;    /* GetLastInputInfo at the last watchdog check */
    unsigned timeoutMs;        /* the deadline the decider is held to */
    unsigned longestWaitMs;    /* the longest the hook waited for a decision */
} TitanHookStatus;

static HHOOK g_keyboard = NULL;
static HHOOK g_mouse = NULL;
static HINSTANCE g_module = NULL;
static TitanHookDecider g_decider = NULL;
static HANDLE g_hookThread = NULL;
static HANDLE g_deciderThread = NULL;
static HANDLE g_watchdogThread = NULL;
static DWORD g_hookThreadId = 0;
static HANDLE g_request = NULL;   /* a key is waiting for a decision */
static HANDLE g_reply = NULL;     /* a decision is waiting for the key */
static HANDLE g_stop = NULL;      /* everything goes home */
static volatile LONG g_running = 0;
static CRITICAL_SECTION g_lock;
static TitanHookStatus g_status;

/* The key on the table between the hook procedure and the decider. */
static struct {
    volatile LONG seq;          /* which key this is */
    KBDLLHOOKSTRUCT key;
    unsigned isDown;
} g_asked;
static struct {
    volatile LONG seq;          /* which key this answers */
    volatile LONG decision;
} g_answered;

static void note_key_seen(void)
{
    g_status.events++;
    g_status.lastKeyTick = GetTickCount();
}

/* ----------------------------------------------------------------------- */
/* The hook procedures                                                     */
/* ----------------------------------------------------------------------- */
static LRESULT CALLBACK keyboard_proc(int nCode, WPARAM wParam, LPARAM lParam)
{
    if (nCode != HC_ACTION || g_decider == NULL || !g_running)
        return CallNextHookEx(g_keyboard, nCode, wParam, lParam);

    KBDLLHOOKSTRUCT *kb = (KBDLLHOOKSTRUCT *)lParam;
    LONG mine;
    DWORD started, waited, timeout;
    int decision = 0;

    EnterCriticalSection(&g_lock);
    note_key_seen();
    mine = ++g_asked.seq;
    g_asked.key = *kb;
    g_asked.isDown = (wParam == WM_KEYDOWN || wParam == WM_SYSKEYDOWN);
    timeout = g_status.timeoutMs;
    LeaveCriticalSection(&g_lock);

    ResetEvent(g_reply);
    SetEvent(g_request);
    started = GetTickCount();
    if (WaitForSingleObject(g_reply, timeout) == WAIT_OBJECT_0
            && g_answered.seq == mine) {
        decision = g_answered.decision;
    } else {
        EnterCriticalSection(&g_lock);
        g_status.late++;
        LeaveCriticalSection(&g_lock);
        decision = 0;
    }
    waited = GetTickCount() - started;
    EnterCriticalSection(&g_lock);
    if (waited > g_status.longestWaitMs)
        g_status.longestWaitMs = waited;
    if (decision)
        g_status.swallowed++;
    else
        g_status.passed++;
    LeaveCriticalSection(&g_lock);

    if (decision)
        return 1;
    return CallNextHookEx(g_keyboard, nCode, wParam, lParam);
}

static LRESULT CALLBACK mouse_proc(int nCode, WPARAM wParam, LPARAM lParam)
{
    if (nCode == HC_ACTION) {
        EnterCriticalSection(&g_lock);
        g_status.mouseEvents++;
        g_status.lastKeyTick = GetTickCount();   /* the watchdog's clock */
        LeaveCriticalSection(&g_lock);
    }
    return CallNextHookEx(g_mouse, nCode, wParam, lParam);
}

/* ----------------------------------------------------------------------- */
/* The threads                                                             */
/* ----------------------------------------------------------------------- */
static void install_hooks(void)
{
    if (g_keyboard) UnhookWindowsHookEx(g_keyboard);
    if (g_mouse) UnhookWindowsHookEx(g_mouse);
    g_keyboard = SetWindowsHookExW(WH_KEYBOARD_LL, keyboard_proc, g_module, 0);
    g_mouse = SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, g_module, 0);
    EnterCriticalSection(&g_lock);
    g_status.installed = (g_keyboard != NULL && g_mouse != NULL) ? 1u : 0u;
    LeaveCriticalSection(&g_lock);
}

static DWORD WINAPI hook_thread(LPVOID unused)
{
    MSG msg;
    (void)unused;
    /* A message queue of our own, so PostThreadMessage can reach us. */
    PeekMessageW(&msg, NULL, WM_USER, WM_USER, PM_NOREMOVE);
    install_hooks();
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        if (msg.message == WM_TITAN_STOP)
            break;
        if (msg.message == WM_TITAN_REHOOK) {
            install_hooks();
            EnterCriticalSection(&g_lock);
            g_status.reinstalls++;
            LeaveCriticalSection(&g_lock);
            continue;
        }
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    if (g_keyboard) UnhookWindowsHookEx(g_keyboard);
    if (g_mouse) UnhookWindowsHookEx(g_mouse);
    g_keyboard = NULL;
    g_mouse = NULL;
    EnterCriticalSection(&g_lock);
    g_status.installed = 0;
    LeaveCriticalSection(&g_lock);
    return 0;
}

static DWORD WINAPI decider_thread(LPVOID unused)
{
    HANDLE waits[2];
    (void)unused;
    waits[0] = g_stop;
    waits[1] = g_request;
    for (;;) {
        DWORD which = WaitForMultipleObjects(2, waits, FALSE, INFINITE);
        if (which == WAIT_OBJECT_0)
            break;
        if (which != WAIT_OBJECT_0 + 1)
            continue;
        LONG seq;
        KBDLLHOOKSTRUCT key;
        unsigned isDown;
        int decision = 0;
        EnterCriticalSection(&g_lock);
        seq = g_asked.seq;
        key = g_asked.key;
        isDown = g_asked.isDown;
        LeaveCriticalSection(&g_lock);
        if (g_decider != NULL && g_running) {
            __try {
                decision = g_decider(key.vkCode, key.scanCode, key.flags,
                                     isDown, (unsigned __int64)key.dwExtraInfo);
            } __except (EXCEPTION_EXECUTE_HANDLER) {
                decision = 0;
            }
        }
        g_answered.decision = decision ? 1 : 0;
        g_answered.seq = seq;
        SetEvent(g_reply);
    }
    return 0;
}

static DWORD WINAPI watchdog_thread(LPVOID unused)
{
    (void)unused;
    while (WaitForSingleObject(g_stop, 1000) == WAIT_TIMEOUT) {
        LASTINPUTINFO info;
        DWORD lastKey, now;
        info.cbSize = sizeof(info);
        if (!GetLastInputInfo(&info))
            continue;
        now = GetTickCount();
        EnterCriticalSection(&g_lock);
        g_status.lastInputTick = info.dwTime;
        lastKey = g_status.lastKeyTick;
        LeaveCriticalSection(&g_lock);
        /* Windows saw input more than two seconds after the last input the
         * hooks saw, and that input is itself at least two seconds old, so
         * it is not a race with a key arriving this instant: the hooks are
         * gone. Put them back. */
        if (info.dwTime > lastKey + 2000 && now > info.dwTime + 2000
                && g_hookThreadId) {
            PostThreadMessageW(g_hookThreadId, WM_TITAN_REHOOK, 0, 0);
            EnterCriticalSection(&g_lock);
            g_status.lastKeyTick = now;   /* one reinstall per silence */
            LeaveCriticalSection(&g_lock);
        }
    }
    return 0;
}

/* ----------------------------------------------------------------------- */
/* The API                                                                 */
/* ----------------------------------------------------------------------- */
__declspec(dllexport) int __stdcall TitanHook_Install(TitanHookDecider decider,
                                                      unsigned timeoutMs)
{
    if (g_running)
        return 1;
    if (decider == NULL)
        return 0;
    InitializeCriticalSection(&g_lock);
    ZeroMemory(&g_status, sizeof(g_status));
    g_status.timeoutMs = timeoutMs ? timeoutMs : 150;
    g_decider = decider;
    g_request = CreateEventW(NULL, FALSE, FALSE, NULL);
    g_reply = CreateEventW(NULL, TRUE, FALSE, NULL);
    g_stop = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!g_request || !g_reply || !g_stop)
        return 0;
    g_running = 1;
    g_deciderThread = CreateThread(NULL, 0, decider_thread, NULL, 0, NULL);
    g_hookThread = CreateThread(NULL, 0, hook_thread, NULL, 0, &g_hookThreadId);
    g_watchdogThread = CreateThread(NULL, 0, watchdog_thread, NULL, 0, NULL);
    if (!g_deciderThread || !g_hookThread || !g_watchdogThread) {
        g_running = 0;
        return 0;
    }
    /* Give the hook thread a moment to install, so a caller that asks the
     * status straight after gets an answer that is true. */
    {
        int tries = 50;
        while (tries-- > 0 && !g_status.installed)
            Sleep(10);
    }
    return g_status.installed ? 1 : 0;
}

__declspec(dllexport) void __stdcall TitanHook_Uninstall(void)
{
    if (!g_running)
        return;
    g_running = 0;
    SetEvent(g_stop);
    if (g_hookThreadId)
        PostThreadMessageW(g_hookThreadId, WM_TITAN_STOP, 0, 0);
    if (g_hookThread) { WaitForSingleObject(g_hookThread, 2000); CloseHandle(g_hookThread); }
    if (g_deciderThread) { WaitForSingleObject(g_deciderThread, 2000); CloseHandle(g_deciderThread); }
    if (g_watchdogThread) { WaitForSingleObject(g_watchdogThread, 2000); CloseHandle(g_watchdogThread); }
    g_hookThread = g_deciderThread = g_watchdogThread = NULL;
    g_hookThreadId = 0;
    if (g_request) CloseHandle(g_request);
    if (g_reply) CloseHandle(g_reply);
    if (g_stop) CloseHandle(g_stop);
    g_request = g_reply = g_stop = NULL;
    g_decider = NULL;
    DeleteCriticalSection(&g_lock);
}

__declspec(dllexport) int __stdcall TitanHook_SetTimeout(unsigned timeoutMs)
{
    if (!g_running || timeoutMs == 0 || timeoutMs > 1000)
        return 0;
    EnterCriticalSection(&g_lock);
    g_status.timeoutMs = timeoutMs;
    LeaveCriticalSection(&g_lock);
    return 1;
}

__declspec(dllexport) int __stdcall TitanHook_Status(TitanHookStatus *out)
{
    if (out == NULL)
        return 0;
    if (!g_running) {
        ZeroMemory(out, sizeof(*out));
        return 1;
    }
    EnterCriticalSection(&g_lock);
    *out = g_status;
    LeaveCriticalSection(&g_lock);
    return 1;
}

__declspec(dllexport) int __stdcall TitanHook_Rehook(void)
{
    if (!g_running || !g_hookThreadId)
        return 0;
    return PostThreadMessageW(g_hookThreadId, WM_TITAN_REHOOK, 0, 0) ? 1 : 0;
}

/* 1 = answering, 0 = hung or gone, -1 = not a window. Asked with a
 * deadline, so the reader never waits on a window that will not answer. */
__declspec(dllexport) int __stdcall TitanHook_IsWindowResponding(HWND hwnd,
                                                                 unsigned timeoutMs)
{
    DWORD_PTR result = 0;
    if (hwnd == NULL || !IsWindow(hwnd))
        return -1;
    if (IsHungAppWindow(hwnd))
        return 0;
    if (!SendMessageTimeoutW(hwnd, WM_NULL, 0, 0,
                             SMTO_ABORTIFHUNG | SMTO_BLOCK,
                             timeoutMs ? timeoutMs : 300, &result))
        return 0;
    return 1;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}

/*
 * copilothook.dll - Low-level keyboard hook for remapping the Copilot key
 *
 * Two Copilot key variants:
 *   - Legacy (pre-24H2): scancode 0xE6 or VK_LAUNCH_APP2 (single key)
 *   - Modern (24H2+):    LWin + Shift + F23/F24 (atomic firmware burst)
 *
 * Strategy: BUFFER+REPLAY. LWin↓ and following Shift↓ are suppressed
 * (held in our state machine, never reach the OS). If F23/F24 ↓ arrives
 * within the buffered window — that's Copilot, send the replacement key
 * and eat the firmware's trailing modifier UPs. If anything else arrives
 * (E↓, S↓, Win↑, etc.) we synthesize the buffered events plus the current
 * one in a single SendInput batch and suppress the original — preserving
 * key order so Win+E, Win+Shift+S, Win-tap (Start Menu) all work normally.
 *
 * Because Win/Shift never reach apps during Copilot, there is no Start
 * Menu glitch and no spurious Shift modifier — the apps see only the
 * replacement key (RControl by default).
 *
 * Build (MSVC):
 *   cl /LD /O2 copilothook.c user32.lib advapi32.lib /Fe:copilothook.dll
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#define COPILOT_SC_E6       0x00E6
#define COPILOT_VK_LAUNCH   0x00B7
#define VK_F23              0x86
#define VK_F24              0x87

#define EXTRA_INFO_MAGIC    ((ULONG_PTR)0xC09110AAUL)

#define ST_IDLE             0
#define ST_LWIN_BUF         1   /* LWin↓ buffered (not sent to OS) */
#define ST_LWIN_SHIFT_BUF   2   /* LWin↓ + Shift↓ buffered         */
#define ST_COPILOT_HELD     3   /* replacement key currently held   */

static HHOOK       g_hook          = NULL;
static int         g_replacementVK = VK_RCONTROL;
static HINSTANCE   g_hInst         = NULL;

static volatile LONG g_copilotSeen = 0;

/* Single-threaded — LL hook serializes per installing thread */
static int  g_state        = ST_IDLE;
static WORD g_bufferedShift = VK_LSHIFT;  /* which Shift was buffered */
static int  g_eatShiftUp   = 0;
static int  g_eatLWinUp    = 0;
static int  g_copilotHeld  = 0;

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        g_hInst = (HINSTANCE)hModule;
        DisableThreadLibraryCalls(hModule);
    }
    return TRUE;
}

static BOOL IsExtendedVK(WORD vk)
{
    switch (vk) {
    case VK_LWIN: case VK_RWIN: case VK_APPS:
    case VK_RCONTROL: case VK_RMENU:
    case VK_INSERT: case VK_DELETE: case VK_HOME: case VK_END:
    case VK_PRIOR: case VK_NEXT:
    case VK_UP: case VK_DOWN: case VK_LEFT: case VK_RIGHT:
    case VK_DIVIDE: case VK_NUMLOCK:
        return TRUE;
    }
    return FALSE;
}

static void FillKey(INPUT *inp, WORD vk, BOOL keyUp)
{
    inp->type           = INPUT_KEYBOARD;
    inp->ki.wVk         = vk;
    inp->ki.wScan       = (WORD)MapVirtualKeyW(vk, MAPVK_VK_TO_VSC);
    inp->ki.dwFlags     = keyUp ? KEYEVENTF_KEYUP : 0;
    if (IsExtendedVK(vk))
        inp->ki.dwFlags |= KEYEVENTF_EXTENDEDKEY;
    inp->ki.time        = 0;
    inp->ki.dwExtraInfo = EXTRA_INFO_MAGIC;
}

static void SendKey(WORD vk, BOOL keyUp)
{
    INPUT inp;
    ZeroMemory(&inp, sizeof(inp));
    FillKey(&inp, vk, keyUp);
    SendInput(1, &inp, sizeof(INPUT));
}

/* Replay buffered events plus current one — preserves key ordering */
static void ReplayWithCurrent(int prevState, WORD curVk, BOOL curIsUp)
{
    INPUT batch[3];
    int n = 0;
    ZeroMemory(batch, sizeof(batch));
    if (prevState == ST_LWIN_BUF || prevState == ST_LWIN_SHIFT_BUF) {
        FillKey(&batch[n++], VK_LWIN, FALSE);
    }
    if (prevState == ST_LWIN_SHIFT_BUF) {
        FillKey(&batch[n++], g_bufferedShift, FALSE);
    }
    FillKey(&batch[n++], curVk, curIsUp);
    SendInput(n, batch, sizeof(INPUT));
}

static LRESULT CALLBACK LowLevelKeyboardProc(int nCode, WPARAM wParam,
                                              LPARAM lParam)
{
    if (nCode != HC_ACTION)
        return CallNextHookEx(g_hook, nCode, wParam, lParam);

    const KBDLLHOOKSTRUCT *kb = (const KBDLLHOOKSTRUCT *)lParam;

    /* Skip injected events — fast path */
    if (kb->flags & LLKHF_INJECTED)
        return CallNextHookEx(g_hook, nCode, wParam, lParam);

    BOOL isDown = (wParam == WM_KEYDOWN || wParam == WM_SYSKEYDOWN);
    BOOL isUp   = (wParam == WM_KEYUP   || wParam == WM_SYSKEYUP);
    WORD vk     = (WORD)kb->vkCode;

    /* Legacy Copilot — single key remap */
    if (kb->scanCode == COPILOT_SC_E6 || vk == COPILOT_VK_LAUNCH) {
        InterlockedExchange(&g_copilotSeen, 1);
        SendKey((WORD)g_replacementVK, isUp);
        return 1;
    }

    switch (g_state) {

    case ST_IDLE:
        /* Buffer LWin DN, wait to see if Copilot follows */
        if (vk == VK_LWIN && isDown) {
            g_state = ST_LWIN_BUF;
            return 1;
        }
        /* Eat trailing burst-end UPs that arrived after Copilot release */
        if (isUp && g_eatShiftUp &&
            (vk == VK_LSHIFT || vk == VK_SHIFT || vk == VK_RSHIFT)) {
            g_eatShiftUp = 0;
            return 1;
        }
        if (isUp && g_eatLWinUp && vk == VK_LWIN) {
            g_eatLWinUp = 0;
            return 1;
        }
        break;   /* pass through */

    case ST_LWIN_BUF:
        /* LWin auto-repeat — stay buffered */
        if (vk == VK_LWIN && isDown) {
            return 1;
        }
        /* Shift DN — extend buffer (could be part of Copilot burst) */
        if (isDown && (vk == VK_LSHIFT || vk == VK_SHIFT || vk == VK_RSHIFT)) {
            g_bufferedShift = (vk == VK_RSHIFT) ? VK_RSHIFT : VK_LSHIFT;
            g_state = ST_LWIN_SHIFT_BUF;
            return 1;
        }
        /* F23/F24 DN without Shift — odd but treat as Copilot anyway */
        if (isDown && (vk == VK_F23 || vk == VK_F24)) {
            g_state = ST_COPILOT_HELD;
            g_copilotHeld = 1;
            g_eatLWinUp   = 1;
            InterlockedExchange(&g_copilotSeen, 1);
            SendKey((WORD)g_replacementVK, FALSE);
            return 1;
        }
        /* Anything else — flush buffered LWin↓ + replay current event */
        {
            int prev = g_state;
            g_state = ST_IDLE;
            ReplayWithCurrent(prev, vk, isUp);
            return 1;
        }

    case ST_LWIN_SHIFT_BUF:
        /* F23/F24 DN — Copilot confirmed */
        if (isDown && (vk == VK_F23 || vk == VK_F24)) {
            g_state = ST_COPILOT_HELD;
            g_copilotHeld = 1;
            g_eatShiftUp  = 1;
            g_eatLWinUp   = 1;
            InterlockedExchange(&g_copilotSeen, 1);
            SendKey((WORD)g_replacementVK, FALSE);
            return 1;
        }
        /* Auto-repeat on buffered modifiers — eat */
        if (isDown && (vk == VK_LWIN || vk == VK_LSHIFT ||
                       vk == VK_SHIFT || vk == VK_RSHIFT)) {
            return 1;
        }
        /* Anything else — flush buffered + replay current */
        {
            int prev = g_state;
            g_state = ST_IDLE;
            ReplayWithCurrent(prev, vk, isUp);
            return 1;
        }

    case ST_COPILOT_HELD:
        /* F23/F24 auto-repeat — eat */
        if (isDown && (vk == VK_F23 || vk == VK_F24)) {
            return 1;
        }
        /* F23/F24 UP — release replacement */
        if (isUp && (vk == VK_F23 || vk == VK_F24)) {
            g_state = ST_IDLE;
            g_copilotHeld = 0;
            SendKey((WORD)g_replacementVK, TRUE);
            return 1;
        }
        /* Eat trailing real Shift UP from firmware burst end */
        if (isUp && g_eatShiftUp &&
            (vk == VK_LSHIFT || vk == VK_SHIFT || vk == VK_RSHIFT)) {
            g_eatShiftUp = 0;
            return 1;
        }
        /* Eat trailing real LWin UP from firmware burst end */
        if (isUp && g_eatLWinUp && vk == VK_LWIN) {
            g_eatLWinUp = 0;
            return 1;
        }
        break;   /* pass through other keys (user can use replacement+other) */
    }

    return CallNextHookEx(g_hook, nCode, wParam, lParam);
}

/* Detection */

__declspec(dllexport) BOOL __cdecl DetectCopilotKey(void)
{
    if (InterlockedCompareExchange(&g_copilotSeen, 0, 0))
        return TRUE;

    HKEY hKey;
    if (RegOpenKeyExW(HKEY_CURRENT_USER,
            L"Software\\Microsoft\\Windows\\Shell\\Copilot",
            0, KEY_READ, &hKey) == ERROR_SUCCESS) {
        RegCloseKey(hKey);
        return TRUE;
    }
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE,
            L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\CopilotKey",
            0, KEY_READ, &hKey) == ERROR_SUCCESS) {
        RegCloseKey(hKey);
        return TRUE;
    }
    {
        HKEY ntKey;
        if (RegOpenKeyExW(HKEY_LOCAL_MACHINE,
                L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion",
                0, KEY_READ, &ntKey) == ERROR_SUCCESS) {
            WCHAR build[32] = {0};
            DWORD sz = sizeof(build);
            if (RegQueryValueExW(ntKey, L"CurrentBuildNumber", NULL, NULL,
                                  (LPBYTE)build, &sz) == ERROR_SUCCESS) {
                int b = _wtoi(build);
                if (b >= 26100) {
                    RegCloseKey(ntKey);
                    HKEY chKey;
                    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE,
                            L"SYSTEM\\CurrentControlSet\\Control\\SystemInformation",
                            0, KEY_READ, &chKey) == ERROR_SUCCESS) {
                        WCHAR chassis[64] = {0};
                        DWORD csz = sizeof(chassis);
                        if (RegQueryValueExW(chKey, L"ChassisTypes", NULL, NULL,
                                              (LPBYTE)chassis, &csz) == ERROR_SUCCESS) {
                            for (WCHAR *p = chassis; *p; ++p) {
                                int ct = _wtoi(p);
                                if (ct == 8 || ct == 9 || ct == 10 || ct == 14) {
                                    RegCloseKey(chKey);
                                    return TRUE;
                                }
                                while (*p && *p != L',') ++p;
                                if (!*p) break;
                            }
                        }
                        RegCloseKey(chKey);
                    }
                    return FALSE;
                }
            }
            RegCloseKey(ntKey);
        }
    }
    return FALSE;
}

/* Public API */

__declspec(dllexport) BOOL __cdecl InstallHook(int replacementVK)
{
    if (g_hook != NULL) return TRUE;
    g_replacementVK = replacementVK;
    g_state         = ST_IDLE;
    g_eatLWinUp     = 0;
    g_eatShiftUp    = 0;
    g_copilotHeld   = 0;
    g_hook = SetWindowsHookExW(WH_KEYBOARD_LL, LowLevelKeyboardProc,
                                g_hInst, 0);
    return (g_hook != NULL);
}

__declspec(dllexport) void __cdecl UninstallHook(void)
{
    if (g_hook != NULL) {
        UnhookWindowsHookEx(g_hook);
        g_hook = NULL;
        if (g_copilotHeld) {
            SendKey((WORD)g_replacementVK, TRUE);
            g_copilotHeld = 0;
        }
        g_state = ST_IDLE;
    }
}

__declspec(dllexport) void __cdecl SetReplacementKey(int vk)
{
    g_replacementVK = vk;
}

__declspec(dllexport) int __cdecl GetReplacementKey(void)
{
    return g_replacementVK;
}

__declspec(dllexport) BOOL __cdecl WasCopilotPressed(void)
{
    return (BOOL)InterlockedCompareExchange(&g_copilotSeen, 0, 0);
}

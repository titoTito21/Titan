/*
 * srremote.dll - injected GDI display-model writer.
 *
 * This DLL is injected into every GUI process by ScreenReaderHelper.dll's
 * global WH_GETMESSAGE hook. Inside each target process it IAT-hooks
 * gdi32!ExtTextOutW across all currently-loaded modules and records every text
 * draw (text + bounding rect + owning HWND) into a per-process shared-memory
 * ring buffer. ScreenReaderHelper.dll reads that ring back by PID.
 *
 * The injected code never does cross-process IPC on the draw path - it only
 * writes to local shared memory guarded by a named mutex - so a busy
 * application is never blocked waiting on the screen reader process.
 *
 * Scope (v1): IAT hooking catches ExtTextOutW calls made through a module's
 * import table. It does not catch GetProcAddress-resolved calls, calls from
 * within gdi32 itself, modules loaded after injection, or text rendered into a
 * memory DC and then BitBlt'd (common in double-buffered apps - WindowFromDC
 * returns NULL there, so those records are stored with hwnd 0).
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <cstdio>
#include <cstring>

#include "srdisplay_shared.h"

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "kernel32.lib")

namespace {

/* ---- shared state (per target process) --------------------------------- */

HANDLE  g_section      = nullptr;
HANDLE  g_mutex        = nullptr;
SrdSharedHeader *g_shared = nullptr;
bool    g_active       = false;   /* true once hooks are installed */

typedef BOOL (WINAPI *ExtTextOutW_t)(HDC, int, int, UINT, const RECT *,
                                     LPCWSTR, UINT, const INT *);
ExtTextOutW_t g_realExtTextOutW = nullptr;

/* Every IAT slot we patched, so PROCESS_DETACH can restore it. */
struct PatchedSlot {
    void **slot;        /* address of the IAT entry */
    void  *original;    /* value to restore */
};
constexpr int   SRD_MAX_PATCHES = 1024;
PatchedSlot     g_patches[SRD_MAX_PATCHES];
int             g_patchCount = 0;

/* ---- shared section ----------------------------------------------------- */

bool OpenSharedSection() {
    char secName[64], mtxName[64];
    DWORD pid = GetCurrentProcessId();
    sprintf_s(secName, SRD_SECTION_FMT, pid);
    sprintf_s(mtxName, SRD_MUTEX_FMT, pid);

    g_mutex = CreateMutexA(nullptr, FALSE, mtxName);
    if (!g_mutex)
        return false;

    g_section = CreateFileMappingA(
        INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE,
        0, sizeof(SrdSharedHeader), secName);
    if (!g_section)
        return false;

    bool firstCreate = (GetLastError() != ERROR_ALREADY_EXISTS);

    g_shared = static_cast<SrdSharedHeader *>(
        MapViewOfFile(g_section, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(SrdSharedHeader)));
    if (!g_shared)
        return false;

    if (firstCreate) {
        /* MapViewOfFile zero-fills new sections; just stamp the header. */
        g_shared->magic       = SRD_MAGIC;
        g_shared->version     = SRD_VERSION;
        g_shared->writeIndex  = 0;
        g_shared->totalWrites = 0;
    }
    return true;
}

void CloseSharedSection() {
    if (g_shared)  { UnmapViewOfFile(g_shared); g_shared = nullptr; }
    if (g_section) { CloseHandle(g_section);    g_section = nullptr; }
    if (g_mutex)   { CloseHandle(g_mutex);      g_mutex   = nullptr; }
}

/* Appends one text-draw record to the ring buffer. */
void RecordTextDraw(HWND hwnd, int left, int top, int right, int bottom,
                    LPCWSTR str, UINT count) {
    if (!g_shared || !str || count == 0)
        return;

    if (WaitForSingleObject(g_mutex, 50) != WAIT_OBJECT_0)
        return; /* never block the drawing thread for long */

    uint32_t idx = g_shared->writeIndex % SRD_RING_CAPACITY;
    SrdRecord &rec = g_shared->records[idx];

    rec.hwnd   = reinterpret_cast<uint64_t>(hwnd);
    rec.left   = left;
    rec.top    = top;
    rec.right  = right;
    rec.bottom = bottom;
    rec.seq    = ++g_shared->totalWrites;

    UINT n = count < (SRD_MAX_TEXT - 1) ? count : (SRD_MAX_TEXT - 1);
    memcpy(rec.text, str, n * sizeof(uint16_t));
    rec.text[n] = 0;

    g_shared->writeIndex = (idx + 1) % SRD_RING_CAPACITY;

    ReleaseMutex(g_mutex);
}

/* ---- the hook ----------------------------------------------------------- */

BOOL WINAPI HookedExtTextOutW(HDC hdc, int x, int y, UINT options,
                              const RECT *lprc, LPCWSTR str, UINT count,
                              const INT *dx) {
    BOOL result = g_realExtTextOutW
        ? g_realExtTextOutW(hdc, x, y, options, lprc, str, count, dx)
        : ExtTextOutW(hdc, x, y, options, lprc, str, count, dx);

    if (g_active && str && count > 0) {
        /* Compute a bounding rect. ExtTextOutW's (x, y) is the reference point;
         * for the common TA_TOP|TA_LEFT alignment that is the top-left corner.
         * Text-align nuances and DC transforms are ignored in v1. */
        SIZE sz = {};
        GetTextExtentPoint32W(hdc, str, count, &sz);

        int left   = x;
        int top    = y;
        int right  = x + sz.cx;
        int bottom = y + sz.cy;

        /* If a clip/opaque rect was supplied, prefer it when it looks valid. */
        if (lprc && (options & (ETO_CLIPPED | ETO_OPAQUE)) &&
            lprc->right > lprc->left && lprc->bottom > lprc->top) {
            left   = lprc->left;
            top    = lprc->top;
            right  = lprc->right;
            bottom = lprc->bottom;
        }

        HWND hwnd = WindowFromDC(hdc);
        RecordTextDraw(hwnd, left, top, right, bottom, str, count);
    }

    return result;
}

/* ---- IAT hooking -------------------------------------------------------- */

/* Patches one module's import of gdi32!ExtTextOutW to point at our hook. */
void PatchModuleIat(HMODULE module) {
    if (!module)
        return;

    auto base = reinterpret_cast<BYTE *>(module);
    auto dos  = reinterpret_cast<IMAGE_DOS_HEADER *>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE)
        return;

    auto nt = reinterpret_cast<IMAGE_NT_HEADERS *>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE)
        return;

    DWORD importRva = nt->OptionalHeader
        .DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (importRva == 0)
        return;

    auto importDesc = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR *>(base + importRva);

    for (; importDesc->Name; ++importDesc) {
        const char *dllName = reinterpret_cast<const char *>(base + importDesc->Name);
        if (_stricmp(dllName, "gdi32.dll") != 0 &&
            _stricmp(dllName, "gdi32full.dll") != 0)
            continue;

        auto thunk = reinterpret_cast<IMAGE_THUNK_DATA *>(base + importDesc->FirstThunk);
        auto origThunk = importDesc->OriginalFirstThunk
            ? reinterpret_cast<IMAGE_THUNK_DATA *>(base + importDesc->OriginalFirstThunk)
            : thunk;

        for (; origThunk->u1.AddressOfData; ++origThunk, ++thunk) {
            if (origThunk->u1.Ordinal & IMAGE_ORDINAL_FLAG)
                continue; /* imported by ordinal - no name to match */

            auto importByName = reinterpret_cast<IMAGE_IMPORT_BY_NAME *>(
                base + origThunk->u1.AddressOfData);
            if (strcmp(importByName->Name, "ExtTextOutW") != 0)
                continue;

            void **slot = reinterpret_cast<void **>(&thunk->u1.Function);
            if (*slot == reinterpret_cast<void *>(HookedExtTextOutW))
                break; /* already patched */

            /* Remember the genuine ExtTextOutW from the first slot we see. */
            if (!g_realExtTextOutW)
                g_realExtTextOutW = reinterpret_cast<ExtTextOutW_t>(*slot);

            DWORD oldProtect = 0;
            if (VirtualProtect(slot, sizeof(void *), PAGE_READWRITE, &oldProtect)) {
                if (g_patchCount < SRD_MAX_PATCHES) {
                    g_patches[g_patchCount].slot     = slot;
                    g_patches[g_patchCount].original = *slot;
                    ++g_patchCount;
                }
                *slot = reinterpret_cast<void *>(HookedExtTextOutW);
                VirtualProtect(slot, sizeof(void *), oldProtect, &oldProtect);
            }
            break; /* one ExtTextOutW slot per module */
        }
    }
}

/* Patches every module currently loaded in this process. */
void PatchAllModules() {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, 0);
    if (snap == INVALID_HANDLE_VALUE)
        return;

    MODULEENTRY32W me = {};
    me.dwSize = sizeof(me);
    if (Module32FirstW(snap, &me)) {
        do {
            PatchModuleIat(me.hModule);
        } while (Module32NextW(snap, &me));
    }
    CloseHandle(snap);
}

/* Restores every IAT slot we patched. */
void UnpatchAll() {
    for (int i = 0; i < g_patchCount; ++i) {
        void **slot = g_patches[i].slot;
        DWORD oldProtect = 0;
        if (VirtualProtect(slot, sizeof(void *), PAGE_READWRITE, &oldProtect)) {
            *slot = g_patches[i].original;
            VirtualProtect(slot, sizeof(void *), oldProtect, &oldProtect);
        }
    }
    g_patchCount = 0;
}

/* ---- host detection ----------------------------------------------------- */

/* Returns true if this process is the screen reader process itself, which the
 * host advertises by publishing its PID in a named section. If the section is
 * absent the display model is not running, so we also stay inert. */
bool ShouldSkipThisProcess() {
    HANDLE sec = OpenFileMappingA(FILE_MAP_READ, FALSE, SRD_HOSTPID_SECTION);
    if (!sec)
        return true; /* host hasn't started the display model - do nothing */

    bool skip = true;
    auto hostPid = static_cast<DWORD *>(MapViewOfFile(sec, FILE_MAP_READ, 0, 0, sizeof(DWORD)));
    if (hostPid) {
        skip = (*hostPid == GetCurrentProcessId());
        UnmapViewOfFile(hostPid);
    }
    CloseHandle(sec);
    return skip;
}

} /* anonymous namespace */

/* ---- exports ------------------------------------------------------------ */

/*
 * The WH_GETMESSAGE hook procedure. Its only job is to exist: installing it as
 * a global hook is what makes Windows map srremote.dll into every GUI process.
 * The actual work happens in DllMain when the DLL is mapped.
 */
extern "C" __declspec(dllexport)
LRESULT CALLBACK SrRemoteHookProc(int code, WPARAM wParam, LPARAM lParam) {
    return CallNextHookEx(nullptr, code, wParam, lParam);
}

/* ---- DllMain ------------------------------------------------------------ */

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    switch (reason) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(module);
        if (ShouldSkipThisProcess())
            return TRUE; /* host process, or display model not running */
        if (!OpenSharedSection()) {
            CloseSharedSection();
            return TRUE; /* stay inert rather than fail the host's LoadLibrary */
        }
        PatchAllModules();
        g_active = true;
        break;

    case DLL_PROCESS_DETACH:
        if (g_active) {
            g_active = false;
            UnpatchAll();
            CloseSharedSection();
        }
        break;
    }
    return TRUE;
}

/* Titan Access -- NVDA controller probe (built as nvda_probe32.exe and
 * nvda_probe64.exe).
 *
 * WHY THIS EXISTS. "Titan Access speaks in 64-bit applications but not in
 * 32-bit ones" is a claim nothing inside Titan can check: Titan is a 64-bit
 * process, and an in-process test only ever exercises the 64-bit path. Worse, a
 * successful controller call proves only that SOME screen reader answered -- if
 * real NVDA (or an earlier Titan that has not exited) owns the ncalrpc
 * endpoint, an application's speech goes there and Titan Access looks broken
 * for reasons that have nothing to do with the application.
 *
 * So the check is made from the outside, from a real process of each bitness,
 * exactly the way an application does it:
 *
 *   1. bind to  ncalrpc:[NvdaCtlr.<session>.<desktop>]  -- the endpoint NVDA's
 *      own client computes,
 *   2. call nvdaController_testIfRunning, then nvdaController_speakText,
 *   3. print one machine-readable line for the Python side to read.
 *
 * The caller (titan_access/nvda_controller_server.py) reads the helper DLL's
 * call counter before and after running this, which is what turns "somebody
 * answered" into "TITAN ACCESS answered" -- per bitness.
 *
 * Output (one line, always):
 *   PROBE bits=<32|64> bind=<rpc status> test=<rpc status> speak=<rpc status>
 *
 * A status of 0 is success; anything else is an RPC error code (1717 =
 * unknown interface, 1734 = unsupported transfer syntax, 1722 = server
 * unavailable -- no controller is listening at all).
 */

#include <windows.h>
#include <rpc.h>
#include <stdio.h>
#include <stdlib.h>
#include "nvdaController.h"   /* MIDL client stub header */

#pragma comment(lib, "rpcrt4.lib")
#pragma comment(lib, "user32.lib")

/* The implicit handle the generated client stub marshals through. */
handle_t nvdaControllerBindingHandle = NULL;

void* __RPC_USER MIDL_user_allocate(size_t size) { return malloc(size); }
void  __RPC_USER MIDL_user_free(void* p) { free(p); }

/* Identical to the helper's and to NVDA's own generateDesktopSpecificNamespace:
 * "<sessionId>.<desktopName>" after the "NvdaCtlr." prefix. */
static void buildEndpoint(wchar_t* out, size_t cch)
{
    DWORD sessionId = 0;
    wchar_t deskName[64];
    HDESK hDesk;

    deskName[0] = L'\0';
    ProcessIdToSessionId(GetCurrentProcessId(), &sessionId);
    hDesk = GetThreadDesktop(GetCurrentThreadId());
    if (hDesk) {
        DWORD needed = 0;
        GetUserObjectInformationW(hDesk, UOI_NAME, deskName,
                                  (DWORD)sizeof(deskName), &needed);
    }
    if (deskName[0] == L'\0')
        wcscpy_s(deskName, 64, L"Default");
    _snwprintf_s(out, cch, _TRUNCATE, L"NvdaCtlr.%u.%s", sessionId, deskName);
}

int wmain(int argc, wchar_t** argv)
{
    wchar_t endpoint[160];
    wchar_t bindingStr[256];
    const wchar_t* text = (argc > 1) ? argv[1] : L"Titan Access controller probe";
    RPC_STATUS bindStatus, testStatus = (RPC_STATUS)-1, speakStatus = (RPC_STATUS)-1;
    int bits = (int)(sizeof(void*) * 8);

    /* An explicit endpoint (argv[2]) is a test hook: it lets the bridge be
     * verified against a server on a private endpoint while a real screen
     * reader owns the shared one. Applications always use the default. */
    if (argc > 2 && argv[2][0]) {
        wcscpy_s(endpoint, 160, argv[2]);
    } else {
        buildEndpoint(endpoint, 160);
    }
    _snwprintf_s(bindingStr, 256, _TRUNCATE, L"ncalrpc:[%s]", endpoint);

    bindStatus = RpcBindingFromStringBindingW((RPC_WSTR)bindingStr,
                                              &nvdaControllerBindingHandle);
    if (bindStatus == RPC_S_OK) {
        RpcTryExcept
        {
            testStatus = (RPC_STATUS)nvdaController_testIfRunning();
            speakStatus = (RPC_STATUS)nvdaController_speakText(text);
        }
        RpcExcept(1)
        {
            RPC_STATUS code = (RPC_STATUS)RpcExceptionCode();
            if (testStatus == (RPC_STATUS)-1) testStatus = code;
            speakStatus = code;
        }
        RpcEndExcept
        RpcBindingFree(&nvdaControllerBindingHandle);
    }

    wprintf(L"PROBE bits=%d bind=%ld test=%ld speak=%ld\n",
            bits, (long)bindStatus, (long)testStatus, (long)speakStatus);
    fflush(stdout);
    return (bindStatus == RPC_S_OK && testStatus == 0 && speakStatus == 0) ? 0 : 1;
}

/* What real NVDA does when it starts (nvda.pyw, terminateRunningNVDA):
 * look for an "NVDA" window, post it WM_QUIT, wait for its PROCESS, then
 * TerminateProcess it. Waits `delay` ms first (NVDA reaches the check after
 * importing much of itself). Prints what it did. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char** argv)
{
    int delay = argc > 1 ? atoi(argv[1]) : 300;
    HWND h;
    DWORD pid = 0;
    HANDLE p;
    Sleep(delay);
    h = FindWindowW(L"wxWindowClassNR", L"NVDA");
    if (!h) { printf("NVDA-LIKE: no NVDA window - starting normally\n"); return 0; }
    GetWindowThreadProcessId(h, &pid);
    printf("NVDA-LIKE: found an NVDA window in pid %lu - terminating it\n", pid);
    PostMessageW(h, WM_QUIT, 0, 0);
    p = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (p) {
        if (WaitForSingleObject(p, 4000) == WAIT_OBJECT_0) {
            printf("NVDA-LIKE: it exited\n");
            CloseHandle(p);
            return 1;
        }
        CloseHandle(p);
    }
    p = OpenProcess(PROCESS_TERMINATE, FALSE, pid);
    if (!p) { printf("NVDA-LIKE: could not open it\n"); return 2; }
    TerminateProcess(p, 1);
    CloseHandle(p);
    printf("NVDA-LIKE: TERMINATED pid %lu\n", pid);
    return 3;
}

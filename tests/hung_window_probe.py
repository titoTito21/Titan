# A window that stops answering. Prints its handle, then its thread sleeps
# without pumping messages, so Windows calls it hung after five seconds.
#   python tests/hung_window_probe.py [seconds] [visible "title"]
# Default: off-screen and never shown. "visible": a small window shown at
# the top left and brought to the front first (used by the live check).
import ctypes, sys, time
from ctypes import wintypes
u = ctypes.windll.user32
u.CreateWindowExW.restype = wintypes.HWND
u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                              wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.HWND,
                              wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 40
visible = len(sys.argv) > 2 and sys.argv[2] == 'visible'
title = sys.argv[3] if len(sys.argv) > 3 else 'Hung probe'
if visible:
    # WS_OVERLAPPEDWINDOW | WS_VISIBLE, a plain STATIC class
    h = u.CreateWindowExW(0, "STATIC", title, 0x00CF0000 | 0x10000000,
                          40, 40, 360, 160, None, None, None, None)
    u.ShowWindow(h, 5)
    u.SetForegroundWindow(h)
    # Pump briefly so it is really up and in front, then stop answering.
    msg = wintypes.MSG()
    end = time.time() + 1.0
    while time.time() < end:
        while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            u.TranslateMessage(ctypes.byref(msg)); u.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.02)
else:
    h = u.CreateWindowExW(0, "STATIC", title, 0x80000000, -32000, -32000,
                          200, 100, None, None, None, None)
print(int(h), flush=True)
time.sleep(seconds)

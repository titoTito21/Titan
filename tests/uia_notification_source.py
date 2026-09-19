# -*- coding: utf-8 -*-
"""Raise a UI Automation notification the way a program does: from a
window of this process's own that answers WM_GETOBJECT with its provider.
Usage: raise_notification.py <text> [kind] [processing]"""
import ctypes, sys, time
from ctypes import wintypes
import comtypes, comtypes.client
from comtypes.automation import VARIANT
uia = comtypes.client.GetModule("UIAutomationCore.dll")
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
core = ctypes.windll.LoadLibrary("UIAutomationCore.dll")
WM_GETOBJECT = 0x003D
UiaRootObjectId = -25
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
core.UiaReturnRawElementProvider.restype = LRESULT
core.UiaReturnRawElementProvider.argtypes = [wintypes.HWND, wintypes.WPARAM, wintypes.LPARAM, ctypes.POINTER(uia.IRawElementProviderSimple)]
core.UiaHostProviderFromHwnd.restype = ctypes.c_long
core.UiaHostProviderFromHwnd.argtypes = [wintypes.HWND, ctypes.POINTER(ctypes.POINTER(uia.IRawElementProviderSimple))]
core.UiaRaiseNotificationEvent.restype = ctypes.c_long
core.UiaRaiseNotificationEvent.argtypes = [ctypes.POINTER(uia.IRawElementProviderSimple), ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p, ctypes.c_wchar_p]

state = {'hwnd': None, 'provider': None}

class Provider(comtypes.COMObject):
    _com_interfaces_ = [uia.IRawElementProviderSimple]
    def IRawElementProviderSimple__get_ProviderOptions(self, this, out):
        out[0] = uia.ProviderOptions_ServerSideProvider
        return 0
    def IRawElementProviderSimple_GetPatternProvider(self, this, patternId, out):
        out[0] = None
        return 0
    def IRawElementProviderSimple_GetPropertyValue(self, this, propertyId, out):
        v = VARIANT()
        if propertyId == 30005:
            v.value = "Titan notification source"
        elif propertyId == 30003:      # ControlType
            v.value = 50033             # Pane
        out[0] = v
        return 0
    def IRawElementProviderSimple__get_HostRawElementProvider(self, this, out):
        p = ctypes.POINTER(uia.IRawElementProviderSimple)()
        core.UiaHostProviderFromHwnd(state['hwnd'], ctypes.byref(p))
        out[0] = p
        return 0

def wndproc(hwnd, msg, wparam, lparam):
    if msg == WM_GETOBJECT and ctypes.c_long(lparam & 0xFFFFFFFF).value == UiaRootObjectId and state['provider'] is not None:
        return core.UiaReturnRawElementProvider(hwnd, wparam, lparam, state['provider'])
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

class WNDCLASSW(ctypes.Structure):
    _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
                ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]
proc = WNDPROC(wndproc)
wc = WNDCLASSW(); wc.lpfnWndProc = proc; wc.lpszClassName = 'TitanNotificationSource'
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
wc.hInstance = kernel32.GetModuleHandleW(None)
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW(ctypes.byref(wc))
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
hwnd = user32.CreateWindowExW(0, 'TitanNotificationSource', 'Titan notification source', 0, 0, 0, 10, 10, None, None, wc.hInstance, None)
assert hwnd, ctypes.get_last_error()
state['hwnd'] = hwnd
state['provider'] = Provider()

def pump(seconds):
    msg = wintypes.MSG(); end = time.time() + seconds
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.02)

text = sys.argv[1] if len(sys.argv) > 1 else "Skopiowano do schowka"
kind = int(sys.argv[2]) if len(sys.argv) > 2 else 2
processing = int(sys.argv[3]) if len(sys.argv) > 3 else 0
user32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE: an element clients can find
pump(0.5)
hr = core.UiaRaiseNotificationEvent(state['provider'], kind, processing, text, "titan.test")
print("listening", bool(core.UiaClientsAreListening()), "hr", hex(hr & 0xFFFFFFFF), flush=True)
pump(2.5)
user32.DestroyWindow(hwnd)

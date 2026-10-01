"""Being told that the machine's network addresses changed.

``iphlpapi``'s ``NotifyAddrChange`` signals an event when the IPv4 address
table changes - a cable plugged in, a Wi-Fi network joined or left, an
adapter switched off - which is exactly the question the network monitor
used to answer by asking psutil for every interface's addresses every
second (measured: 33 ms a time). :class:`AddressChange` waits on that
event on a thread of its own and sets a Python event of the caller's, so a
monitor can sleep for as long as nothing happens.

Nothing here raises: on a machine where the call is refused ``available``
is False and the caller polls as it always did.
"""
import ctypes
import sys
import threading
from ctypes import wintypes

IS_WINDOWS = sys.platform == 'win32'

_ERROR_IO_PENDING = 997
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF


class _Overlapped(ctypes.Structure):
    _fields_ = [('Internal', ctypes.c_void_p), ('InternalHigh', ctypes.c_void_p),
                ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                ('hEvent', wintypes.HANDLE)]


class AddressChange:
    """Sets ``wake`` whenever the IPv4 address table changes."""

    def __init__(self, wake):
        self.wake = wake
        self.available = False
        self._stop = threading.Event()
        self._thread = None
        self._event = None
        self._overlapped = None
        self._handle = wintypes.HANDLE()
        if not IS_WINDOWS:
            return
        try:
            self._ip = ctypes.WinDLL('iphlpapi')
            self._k32 = ctypes.WinDLL('kernel32')
            self._ip.NotifyAddrChange.argtypes = [ctypes.POINTER(wintypes.HANDLE),
                                                  ctypes.POINTER(_Overlapped)]
            self._ip.NotifyAddrChange.restype = wintypes.DWORD
            self._ip.CancelIPChangeNotify.argtypes = [ctypes.POINTER(_Overlapped)]
            self._ip.CancelIPChangeNotify.restype = wintypes.BOOL
            self._k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self._k32.WaitForSingleObject.restype = wintypes.DWORD
            self._k32.CreateEventW.restype = wintypes.HANDLE
            self._k32.SetEvent.argtypes = [wintypes.HANDLE]
            self._k32.CloseHandle.argtypes = [wintypes.HANDLE]
            self._event = self._k32.CreateEventW(None, False, False, None)
            if not self._event:
                return
            self._overlapped = _Overlapped()
            self._overlapped.hEvent = self._event
            if not self._arm():
                return
        except Exception:
            return
        self.available = True
        self._thread = threading.Thread(target=self._run, name='TitanAddrChange',
                                        daemon=True)
        self._thread.start()

    def _arm(self):
        code = self._ip.NotifyAddrChange(ctypes.byref(self._handle),
                                         ctypes.byref(self._overlapped))
        return code in (0, _ERROR_IO_PENDING)

    def _run(self):
        while not self._stop.is_set():
            result = self._k32.WaitForSingleObject(self._event, _INFINITE)
            if self._stop.is_set():
                break
            if result != _WAIT_OBJECT_0:
                break
            try:
                self.wake.set()
            except Exception:
                pass
            if not self._arm():
                break
        self.available = False

    def close(self):
        """Stop waiting; safe to call twice."""
        self._stop.set()
        if self._overlapped is not None:
            try:
                self._ip.CancelIPChangeNotify(ctypes.byref(self._overlapped))
            except Exception:
                pass
        if self._event:
            try:
                self._k32.SetEvent(self._event)
            except Exception:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(2.0)
        if self._event:
            try:
                self._k32.CloseHandle(self._event)
            except Exception:
                pass
            self._event = None

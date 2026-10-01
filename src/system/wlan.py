"""The wireless connection, read from Windows' own WLAN API.

Titan used to ask ``netsh wlan show interfaces`` - a console process - for
the status bar every five seconds and for the network monitor **every
second**, and then parse its text for the English words ``State``,
``SSID`` and ``Signal``. Measured on this machine: 159 ms per call, so the
monitor alone was about a sixth of a processor core, for the life of the
program, spawning a process a second; and on a Windows whose interface
language is not English the words are not there and the status bar read
"Unknown" for ever.

``wlanapi.dll`` answers the same question in microseconds and in no
language at all: :func:`current_connection` is the interface's state, the
SSID and the signal quality as Windows keeps them. Everything here answers
None rather than raising - a machine with no wireless interface, no WLAN
service (Server editions, some virtual machines) or no ``wlanapi.dll`` is
an ordinary case, and the callers keep their old ``netsh`` fallback for
it.
"""
import ctypes
import sys
import threading
from ctypes import wintypes

IS_WINDOWS = sys.platform == 'win32'

#: WLAN_INTERFACE_STATE, spelled the way ``netsh`` spells it in English -
#: which is what the network monitor has always compared against.
STATES = {
    0: 'not ready',
    1: 'connected',
    2: 'ad hoc network formed',
    3: 'disconnecting',
    4: 'disconnected',
    5: 'associating',
    6: 'discovering',
    7: 'authenticating',
}

#: The states in which Windows is on its way to a network.
CONNECTING = ('associating', 'discovering', 'authenticating')

_OPCODE_CURRENT_CONNECTION = 7
_ERROR_INVALID_STATE = 5023
_CLIENT_VERSION = 2

_lock = threading.Lock()
_handle = None
_dll = None
_unavailable = ''


class _GUID(ctypes.Structure):
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]


class _InterfaceInfo(ctypes.Structure):
    _fields_ = [('InterfaceGuid', _GUID),
                ('strInterfaceDescription', wintypes.WCHAR * 256),
                ('isState', wintypes.DWORD)]


class _InterfaceInfoList(ctypes.Structure):
    _fields_ = [('dwNumberOfItems', wintypes.DWORD),
                ('dwIndex', wintypes.DWORD),
                ('InterfaceInfo', _InterfaceInfo * 1)]


class _Dot11Ssid(ctypes.Structure):
    _fields_ = [('uSSIDLength', wintypes.ULONG), ('ucSSID', ctypes.c_char * 32)]


class _AssociationAttributes(ctypes.Structure):
    _fields_ = [('dot11Ssid', _Dot11Ssid),
                ('dot11BssType', wintypes.DWORD),
                ('dot11Bssid', ctypes.c_ubyte * 6),
                ('dot11PhyType', wintypes.DWORD),
                ('uDot11PhyIndex', wintypes.ULONG),
                ('wlanSignalQuality', wintypes.ULONG),
                ('ulRxRate', wintypes.ULONG),
                ('ulTxRate', wintypes.ULONG)]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [('bSecurityEnabled', wintypes.BOOL),
                ('bOneXEnabled', wintypes.BOOL),
                ('dot11AuthAlgorithm', wintypes.DWORD),
                ('dot11CipherAlgorithm', wintypes.DWORD)]


class _ConnectionAttributes(ctypes.Structure):
    _fields_ = [('isState', wintypes.DWORD),
                ('wlanConnectionMode', wintypes.DWORD),
                ('strProfileName', wintypes.WCHAR * 256),
                ('wlanAssociationAttributes', _AssociationAttributes),
                ('wlanSecurityAttributes', _SecurityAttributes)]


def _load():
    """The DLL with its signatures, or None (and why in ``_unavailable``)."""
    global _dll, _unavailable
    if _dll is not None:
        return _dll
    if not IS_WINDOWS:
        _unavailable = 'not Windows'
        return None
    try:
        dll = ctypes.WinDLL('wlanapi')
        dll.WlanOpenHandle.argtypes = [wintypes.DWORD, ctypes.c_void_p,
                                       ctypes.POINTER(wintypes.DWORD),
                                       ctypes.POINTER(wintypes.HANDLE)]
        dll.WlanOpenHandle.restype = wintypes.DWORD
        dll.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        dll.WlanCloseHandle.restype = wintypes.DWORD
        dll.WlanEnumInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                           ctypes.POINTER(ctypes.c_void_p)]
        dll.WlanEnumInterfaces.restype = wintypes.DWORD
        dll.WlanQueryInterface.argtypes = [wintypes.HANDLE, ctypes.POINTER(_GUID),
                                           wintypes.DWORD, ctypes.c_void_p,
                                           ctypes.POINTER(wintypes.DWORD),
                                           ctypes.POINTER(ctypes.c_void_p),
                                           ctypes.c_void_p]
        dll.WlanQueryInterface.restype = wintypes.DWORD
        dll.WlanFreeMemory.argtypes = [ctypes.c_void_p]
        dll.WlanFreeMemory.restype = None
    except Exception as e:
        _unavailable = 'wlanapi.dll: %s' % e
        return None
    _dll = dll
    return dll


def _open():
    """One client handle for the life of the process, reopened on error."""
    global _handle, _unavailable
    dll = _load()
    if dll is None:
        return None
    if _handle is not None:
        return _handle
    negotiated = wintypes.DWORD(0)
    handle = wintypes.HANDLE()
    code = dll.WlanOpenHandle(_CLIENT_VERSION, None,
                              ctypes.byref(negotiated), ctypes.byref(handle))
    if code != 0:
        _unavailable = 'WlanOpenHandle: error %d' % code
        return None
    _handle = handle
    return handle


def _drop_handle():
    global _handle
    dll, handle = _dll, _handle
    _handle = None
    if dll is not None and handle is not None:
        try:
            dll.WlanCloseHandle(handle, None)
        except Exception:
            pass


def why_unavailable():
    """One line saying why nothing is answered, or ''."""
    return _unavailable


def interfaces():
    """Every wireless interface: ``[{'guid', 'description', 'state'}]``.

    None when the WLAN service cannot be asked at all; an empty list when
    it can and there is no wireless interface.
    """
    with _lock:
        dll = _load()
        handle = _open()
        if dll is None or handle is None:
            return None
        plist = ctypes.c_void_p()
        code = dll.WlanEnumInterfaces(handle, None, ctypes.byref(plist))
        if code != 0:
            _drop_handle()
            return None
        try:
            head = ctypes.cast(plist, ctypes.POINTER(_InterfaceInfoList)).contents
            count = int(head.dwNumberOfItems)
            base = ctypes.addressof(head) + _InterfaceInfoList.InterfaceInfo.offset
            found = []
            for index in range(count):
                info = _InterfaceInfo.from_address(
                    base + index * ctypes.sizeof(_InterfaceInfo))
                found.append({
                    'guid': _GUID.from_buffer_copy(info.InterfaceGuid),
                    'description': info.strInterfaceDescription,
                    'state': STATES.get(int(info.isState), 'unknown'),
                })
            return found
        finally:
            dll.WlanFreeMemory(plist)


def current_connection():
    """The first wireless interface's connection, or None.

    ``{'interface': description, 'state': one of STATES, 'ssid': str or
    None, 'signal': 0..100 or None, 'profile': str or None}``. ``ssid`` and
    ``signal`` are None unless the state is ``connected``. None means the
    question could not be asked (no wireless interface, no WLAN service)
    and the caller should fall back to whatever it did before.
    """
    found = interfaces()
    if not found:
        return None
    first = found[0]
    answer = {'interface': first['description'], 'state': first['state'],
              'ssid': None, 'signal': None, 'profile': None}
    if first['state'] != 'connected':
        return answer
    with _lock:
        dll, handle = _dll, _handle
        if dll is None or handle is None:
            return answer
        size = wintypes.DWORD(0)
        pdata = ctypes.c_void_p()
        code = dll.WlanQueryInterface(handle, ctypes.byref(first['guid']),
                                      _OPCODE_CURRENT_CONNECTION, None,
                                      ctypes.byref(size), ctypes.byref(pdata),
                                      None)
        if code != 0:
            # 5023 is "not connected" - the state changed between the two
            # calls. Anything else is the handle gone bad.
            if code != _ERROR_INVALID_STATE:
                _drop_handle()
            answer['state'] = 'disconnected' if code == _ERROR_INVALID_STATE \
                else answer['state']
            return answer
        try:
            attrs = ctypes.cast(pdata, ctypes.POINTER(_ConnectionAttributes)).contents
            assoc = attrs.wlanAssociationAttributes
            raw = bytes(assoc.dot11Ssid.ucSSID[:int(assoc.dot11Ssid.uSSIDLength)])
            answer['ssid'] = raw.decode('utf-8', errors='replace')
            answer['signal'] = int(assoc.wlanSignalQuality)
            answer['profile'] = attrs.strProfileName or None
            answer['state'] = STATES.get(int(attrs.isState), answer['state'])
        finally:
            dll.WlanFreeMemory(pdata)
    return answer


def wireless_state():
    """``(state, ssid)`` the way the network monitor has always read it.

    ``(None, None)`` when there is nothing to read.
    """
    info = current_connection()
    if info is None:
        return None, None
    return info['state'], info['ssid']


# --------------------------------------------------------------------------- #
# Being told, instead of asking
# --------------------------------------------------------------------------- #
#: WLAN_NOTIFICATION_SOURCE_ACM - the auto configuration module, which is
#: where "connection started", "connection complete" and "disconnected"
#: come from.
_SOURCE_ACM = 0x00000008
_SOURCE_NONE = 0

# WINFUNCTYPE exists only on Windows; elsewhere nothing here is ever called.
_WATCH_CALLBACK_TYPE = (ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
                        if IS_WINDOWS else None)

#: Windows holds the ADDRESS of the callback. A ctypes function object
#: Python has collected is freed memory the next notification calls into,
#: so the one registered is kept here until it is unregistered.
_watch_callback = None
_watch_listener = None


def watch(on_change):
    """Ask Windows to call ``on_change()`` on every WLAN connection event.

    The call arrives on a thread of Windows' own, so ``on_change`` should
    do no more than set an event. True when the registration took;
    False when it did not, and the caller should poll.
    """
    global _watch_callback, _watch_listener
    if not IS_WINDOWS:
        return False
    with _lock:
        dll = _load()
        handle = _open()
        if dll is None or handle is None:
            return False
        try:
            dll.WlanRegisterNotification.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL,
                _WATCH_CALLBACK_TYPE, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(wintypes.DWORD)]
            dll.WlanRegisterNotification.restype = wintypes.DWORD
        except Exception:
            return False

        def _fired(_data, _context):
            listener = _watch_listener
            if listener is not None:
                try:
                    listener()
                except Exception:
                    pass

        callback = _WATCH_CALLBACK_TYPE(_fired)
        previous = wintypes.DWORD(0)
        code = dll.WlanRegisterNotification(handle, _SOURCE_ACM, True, callback,
                                            None, None, ctypes.byref(previous))
        if code != 0:
            return False
        _watch_callback = callback
        _watch_listener = on_change
        return True


def unwatch():
    """Take the registration back (and only then let the callback go)."""
    global _watch_callback, _watch_listener
    with _lock:
        _watch_listener = None
        dll, handle = _dll, _handle
        if _watch_callback is not None and dll is not None and handle is not None:
            try:
                previous = wintypes.DWORD(0)
                dll.WlanRegisterNotification(handle, _SOURCE_NONE, True, None,
                                             None, None, ctypes.byref(previous))
            except Exception:
                pass
        _watch_callback = None

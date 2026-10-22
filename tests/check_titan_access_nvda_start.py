"""Live: does an NVDA starting up end the process that runs Titan Access's
NVDA controller? Run on a desktop of its own, so the user's real NVDA (on
the Default desktop) is neither seen nor touched.

    python tests/check_titan_access_nvda_start.py old|new [delay_ms]

Needs ``nvda.exe`` built from ``tests/nvda_like_start.c`` beside this file
(``cl /O2 nvda_like_start.c /Fe:nvda.exe /link user32.lib``): it does what
real NVDA does starting - FindWindow("wxWindowClassNR", "NVDA"), WM_QUIT,
wait for that process, TerminateProcess. ``old`` runs the controller as it
was (no guard): measured, the process was frozen 4 s and then terminated.
``new``: the window is taken down in time and the process lives.
"""
import ctypes, ctypes.wintypes as wt, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get('TEMP', HERE)
COMPONENT = os.path.join(os.path.dirname(HERE), 'data', 'components', 'titan access')
DESK = "TitanNvdaTest"


def victim(mode):
    sys.path.insert(0, COMPONENT)
    import psutil
    from titan_access import nvda_controller_server as n
    # The user's own NVDA, on the other desktop, is not the one starting.
    real = {p.pid for p in psutil.process_iter(['name'])
            if (p.info['name'] or '').lower() in n.NVDA_PROCESSES}
    keep_init = n._NvdaProcesses.__init__

    def init(self):
        keep_init(self)
        for pid in real:
            self._known[pid] = False
    n._NvdaProcesses.__init__ = init
    if mode == 'old':
        # What shipped before: no guard - the window stays up whatever runs.
        n.NvdaControllerServer._start_watch = lambda self: None
        n.NvdaControllerServer._set_window = lambda self, dll, show: False

    class Settings:
        mute_outside_tce = False
        def get_bool(self, s, k, d): return d
    engine = type('E', (), {'settings': Settings(), 'speech': None,
                            'speak': lambda *a, **k: None})()
    server = n.NvdaControllerServer(engine).start()
    print('VICTIM ready owns=%s window=%s' % (server.owns_endpoint,
                                              server.has_nvda_window()), flush=True)
    for i in range(14):
        time.sleep(1)
        print('VICTIM alive %d window=%s' % (i, server.has_nvda_window()), flush=True)
    server.stop()
    print('VICTIM finished normally', flush=True)


_k = ctypes.WinDLL('kernel32', use_last_error=True)
_k.CloseHandle.argtypes = [wt.HANDLE]
_k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
_k.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
_k.CreateFileW.restype = wt.HANDLE
_k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]


class SA(ctypes.Structure):
    _fields_ = [('n', wt.DWORD), ('sd', ctypes.c_void_p), ('inherit', wt.BOOL)]


class STARTUPINFO(ctypes.Structure):
    _fields_ = [('cb', wt.DWORD), ('lpReserved', wt.LPWSTR), ('lpDesktop', wt.LPWSTR),
                ('lpTitle', wt.LPWSTR), ('dwX', wt.DWORD), ('dwY', wt.DWORD),
                ('dwXSize', wt.DWORD), ('dwYSize', wt.DWORD), ('dwXCountChars', wt.DWORD),
                ('dwYCountChars', wt.DWORD), ('dwFillAttribute', wt.DWORD),
                ('dwFlags', wt.DWORD), ('wShowWindow', wt.WORD), ('cbReserved2', wt.WORD),
                ('lpReserved2', ctypes.c_void_p), ('hStdInput', wt.HANDLE),
                ('hStdOutput', wt.HANDLE), ('hStdError', wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wt.HANDLE), ('hThread', wt.HANDLE),
                ('dwProcessId', wt.DWORD), ('dwThreadId', wt.DWORD)]


def launch_on_desk(cmdline, out_path):
    k32 = _k
    sa = SA(ctypes.sizeof(SA), None, True)
    h = k32.CreateFileW(out_path, 0x40000000, 3, ctypes.byref(sa), 2, 0x80, None)
    si = STARTUPINFO(); si.cb = ctypes.sizeof(si)
    si.lpDesktop = DESK
    si.dwFlags = 0x100        # STARTF_USESTDHANDLES
    si.hStdOutput = si.hStdError = h
    pi = PROCESS_INFORMATION()
    ok = k32.CreateProcessW(None, ctypes.create_unicode_buffer(cmdline), None, None,
                            True, 0x08000000, None, None, ctypes.byref(si), ctypes.byref(pi))
    k32.CloseHandle(h)
    if not ok:
        raise OSError(ctypes.GetLastError())
    k32.CloseHandle(pi.hThread)
    return pi.hProcess, pi.dwProcessId


def main():
    mode = sys.argv[1]
    delay = sys.argv[2] if len(sys.argv) > 2 else '300'
    user32 = ctypes.windll.user32
    user32.CreateDesktopW.restype = wt.HANDLE
    desk = user32.CreateDesktopW(DESK, None, None, 0, 0x10000000, None)
    assert desk, ctypes.GetLastError()
    k32 = _k
    vout = os.path.join(OUT, 'victim_%s.txt' % mode)
    aout = os.path.join(OUT, 'nvda_%s.txt' % mode)
    hv, vpid = launch_on_desk('"%s" -u "%s" --victim %s' % (sys.executable, __file__, mode), vout)
    for _ in range(100):
        time.sleep(0.1)
        if 'VICTIM ready' in open(vout, errors='replace').read():
            break
    time.sleep(1.0)
    t0 = time.time()
    ha, _ = launch_on_desk('"%s" %s' % (os.path.join(HERE, 'nvda.exe'), delay), aout)
    k32.WaitForSingleObject(ha, 20000)
    k32.WaitForSingleObject(hv, 20000)
    code = wt.DWORD()
    k32.GetExitCodeProcess(hv, ctypes.byref(code))
    print('--- mode=%s delay=%sms' % (mode, delay))
    print(open(vout, errors='replace').read().strip().splitlines()[0])
    print(open(aout, errors='replace').read().strip())
    tail = open(vout, errors='replace').read().strip().splitlines()[-1]
    print('victim last line:', tail, '| exit code', code.value)
    user32.CloseDesktop(desk)


if __name__ == '__main__':
    if '--victim' in sys.argv:
        victim(sys.argv[sys.argv.index('--victim') + 1])
    else:
        main()

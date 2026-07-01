"""
Titan child-process tracker
============================
Stops helper subprocesses -- chiefly the 32-bit TTS engine "bridges"
(Eloquence / DECtalk / SMP / Festival / BestSpeech / SAPI) -- from outliving
the Titan process and lingering as orphans.

Two independent safety nets:

1. Windows Job Object (crash-safe). Every tracked child is assigned to a Job
   Object created with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. The job's only
   handle is held by this process; when Titan dies for ANY reason -- clean
   exit, os._exit(), an unhandled crash, or being killed from Task Manager --
   the OS closes that handle and terminates every process still in the job.
   This is the only mechanism that survives a hard crash, where no Python
   cleanup code gets to run.

2. Explicit terminate_all() for the normal shutdown path. Titan exits via
   os._exit(0) (see gui.shutdown_app), which bypasses atexit, so the GUI
   shutdown sequence calls terminate_all() to kill the bridges promptly and
   deterministically before the process disappears. It is also registered with
   atexit as a belt-and-suspenders for exit paths that DO run finalisers.

track_process() is safe to call from any thread and never raises, so engine
bridges can wire it in without worrying about breaking synthesis if anything
here is unavailable (e.g. a non-Windows host or a locked-down Job Object).
"""

import atexit
import sys
import threading

_IS_WINDOWS = sys.platform.startswith('win')

_lock = threading.Lock()
_tracked = []           # subprocess.Popen instances we've been asked to track
_job_handle = None      # HANDLE to the kill-on-close Job Object (Windows)
_job_init_done = False
_job_usable = False
_k32 = None             # cached kernel32 WinDLL once the job is set up


def _ensure_job():
    """Create the kill-on-job-close Job Object once. Best effort: on any
    failure we quietly fall back to the explicit terminate_all()/atexit path."""
    global _job_handle, _job_init_done, _job_usable, _k32
    if _job_init_done:
        return _job_usable
    _job_init_done = True
    if not _IS_WINDOWS:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL('kernel32', use_last_error=True)

        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.TerminateJobObject.restype = wintypes.BOOL
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return False

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ('PerProcessUserTimeLimit', ctypes.c_int64),
                ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', ctypes.c_uint32),
                ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', ctypes.c_uint32),
                ('Affinity', ctypes.c_size_t),
                ('PriorityClass', ctypes.c_uint32),
                ('SchedulingClass', ctypes.c_uint32),
            ]

        class EXT_LIMIT(ctypes.Structure):
            _fields_ = [
                ('BasicLimitInformation', BASIC_LIMIT),
                ('IoInfo', IO_COUNTERS),
                ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t),
                ('PeakJobMemoryUsed', ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        info = EXT_LIMIT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(
                job, JobObjectExtendedLimitInformation,
                ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            return False

        _job_handle = job
        _k32 = k32
        _job_usable = True
    except Exception as e:
        print(f"[process_tracker] Job Object unavailable: {e}")
        _job_usable = False
    return _job_usable


def _assign_to_job(proc):
    """Assign an already-running child to the kill-on-close job. Best effort:
    on Windows 8+ a process may live in several nested jobs, so this normally
    succeeds even if Titan itself was launched inside a job."""
    if not _job_usable or _k32 is None or proc is None:
        return
    PROCESS_TERMINATE = 0x0001
    PROCESS_SET_QUOTA = 0x0100
    h = _k32.OpenProcess(PROCESS_TERMINATE | PROCESS_SET_QUOTA, False, int(proc.pid))
    if not h:
        return
    try:
        _k32.AssignProcessToJobObject(_job_handle, h)
    finally:
        _k32.CloseHandle(h)


def track_process(proc):
    """Register a helper subprocess so it is killed when Titan exits.

    `proc` is a subprocess.Popen (or anything exposing .pid/.poll/.terminate).
    Safe to call from any thread; never raises."""
    if proc is None:
        return
    try:
        with _lock:
            _ensure_job()
            _tracked.append(proc)
        _assign_to_job(proc)
    except Exception:
        pass


def terminate_all(timeout=1.5):
    """Terminate every tracked subprocess. Idempotent; meant to be called on
    the shutdown path right before os._exit(). Never raises."""
    try:
        # Fastest and most thorough on Windows: one call nukes everything still
        # in the job, including grandchildren or bridges we lost the handle to.
        if _job_usable and _k32 is not None and _job_handle:
            try:
                _k32.TerminateJobObject(_job_handle, 1)
            except Exception:
                pass

        with _lock:
            procs = list(_tracked)
            _tracked.clear()

        for p in procs:
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(timeout=timeout)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
    except Exception:
        pass


# Belt-and-suspenders for exit paths that actually run finalisers. The primary
# Titan shutdown uses os._exit() and calls terminate_all() explicitly instead.
atexit.register(terminate_all)

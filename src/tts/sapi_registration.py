"""
SAPI5 Voice Registration for Titan TTS
=======================================
Registers Titan TTS as a SAPI5 voice visible to 32-bit and 64-bit SAPI
client applications (including screen readers like NVDA, JAWS, Narrator).

Per Microsoft SAPI 5.3 docs (ms717036), voice tokens MUST be stored under
HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens. SAPI's voice
enumerator only reads from HKLM - HKCU is for user-specific per-voice
settings (volume, rate, etc.), not for token registration. This means
we require administrator rights to write to HKLM.

The actual voice is implemented by two native C++ DLLs shipped in
``data/lib/``:
    titantts64.dll  - registered as an InprocServer32 in the 64-bit CLSID view
    titantts32.dll  - registered in WOW6432Node for 32-bit SAPI clients
The DLLs implement ISpTTSEngine and connect to a Python named-pipe server
(src.tts.sapi_pipe_server) that does the actual synthesis via the currently
configured Titan TTS engine.

Approach: build a .reg file with explicit paths for BOTH the 64-bit view
(HKLM\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TitanTTS) and the 32-bit
view (HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Speech\\Voices\\Tokens\\TitanTTS),
plus InprocServer32 entries in both HKLM\\SOFTWARE\\Classes\\CLSID and
HKLM\\SOFTWARE\\Classes\\WOW6432Node\\CLSID, and import it via reg.exe. If
we're not running elevated, ShellExecuteExW with the "runas" verb triggers
a single UAC prompt.

Registration only happens in "interactive" mode (triggered by the user
toggling the setting in the Settings dialog). Startup sync is silent: it
detects mismatch between stored setting and actual registry state, but
won't pop UAC on every launch - users must re-toggle the checkbox if the
registry was cleared externally.
"""

import os
import sys
import tempfile


# Stable identifiers - must not change across versions once shipped, or
# previously-registered voices will be orphaned.
TITAN_TTS_VOICE_TOKEN_NAME = 'TitanTTS'
TITAN_TTS_VOICE_DISPLAY_NAME = 'Titan TTS'
TITAN_TTS_VOICE_VENDOR = 'Titosoft'
TITAN_TTS_CLSID = '{A8B5D3E1-7C4F-4D89-9A2F-3B1C5D7E9F24}'


def _is_windows():
    return sys.platform == 'win32'


def _is_admin():
    if not _is_windows():
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _get_project_root():
    """Return the root of the TCE Launcher project (repo root or _internal dir)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        '..', '..'))


def _get_dll_paths():
    """
    Return (dll64_path, dll32_path). Both must exist for full 32/64 support,
    but if only one is present we still register that view.
    """
    root = _get_project_root()
    # Compiled with PyInstaller: data/lib may be inside _internal/data/lib
    candidates = [
        os.path.join(root, 'data', 'lib'),
        os.path.join(root, '_internal', 'data', 'lib'),
    ]
    dll64 = None
    dll32 = None
    for c in candidates:
        p64 = os.path.join(c, 'titantts64.dll')
        p32 = os.path.join(c, 'titantts32.dll')
        if dll64 is None and os.path.isfile(p64):
            dll64 = p64
        if dll32 is None and os.path.isfile(p32):
            dll32 = p32
    return dll64, dll32


def _reg_escape(s):
    """Escape a string for use inside a double-quoted .reg REG_SZ value."""
    return s.replace('\\', '\\\\').replace('"', '\\"')


_TOKEN_PATHS = (
    r'HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\TitanTTS',
    r'HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Speech\Voices\Tokens\TitanTTS',
)
_CLSID_PATHS = (
    r'HKEY_LOCAL_MACHINE\SOFTWARE\Classes\CLSID' + '\\' + TITAN_TTS_CLSID,
    r'HKEY_LOCAL_MACHINE\SOFTWARE\Classes\WOW6432Node\CLSID' + '\\' + TITAN_TTS_CLSID,
)


def _build_install_reg():
    """
    Build the content of a .reg file that registers Titan TTS in HKLM (both
    views), with InprocServer32 pointing at the native DLLs shipped in
    data/lib. The 64-bit CLSID hive gets titantts64.dll; WOW6432Node gets
    titantts32.dll so 32-bit SAPI clients load the matching-bitness server.
    """
    dll64, dll32 = _get_dll_paths()
    if not dll64 and not dll32:
        raise RuntimeError(
            "Titan TTS DLL not found in data/lib/. "
            "Expected titantts64.dll and/or titantts32.dll.")

    display = TITAN_TTS_VOICE_DISPLAY_NAME
    vendor = TITAN_TTS_VOICE_VENDOR

    lines = ['Windows Registry Editor Version 5.00', '']

    for token in _TOKEN_PATHS:
        lines.append(f'[{token}]')
        lines.append(f'@="{display}"')
        lines.append(f'"CLSID"="{TITAN_TTS_CLSID}"')
        lines.append('"LangDataPath"=""')
        lines.append('"VoicePath"=""')
        lines.append(f'"409"="{display}"')
        lines.append(f'"415"="{display}"')
        lines.append('')
        lines.append(f'[{token}\\Attributes]')
        lines.append(f'"Name"="{display}"')
        lines.append('"Gender"="Female"')
        lines.append('"Age"="Adult"')
        lines.append('"Language"="409;415"')
        lines.append(f'"Vendor"="{vendor}"')
        lines.append('"VendorPreferred"="1"')
        lines.append('"SayAsSupport"="spell=1;cardinal=1;ordinal=1"')
        lines.append('')

    # _CLSID_PATHS is (64-bit classes, WOW6432Node classes).
    dll_for_hive = (dll64 or dll32, dll32 or dll64)
    for clsid, dll_path in zip(_CLSID_PATHS, dll_for_hive):
        lines.append(f'[{clsid}]')
        lines.append('@="Titan TTS SAPI5 Voice"')
        lines.append('')
        lines.append(f'[{clsid}\\InprocServer32]')
        lines.append(f'@="{_reg_escape(dll_path)}"')
        lines.append('"ThreadingModel"="Both"')
        lines.append('')

    return '\r\n'.join(lines)


def _build_uninstall_reg():
    """Build the content of a .reg file that removes all Titan TTS entries."""
    paths = list(_TOKEN_PATHS) + list(_CLSID_PATHS) + [
        # Legacy HKCU entries from the first broken implementation - clean them too.
        r'HKEY_CURRENT_USER\SOFTWARE\Microsoft\Speech\Voices\Tokens\TitanTTS',
        r'HKEY_CURRENT_USER\SOFTWARE\Classes\CLSID' + '\\' + TITAN_TTS_CLSID,
    ]
    lines = ['Windows Registry Editor Version 5.00', '']
    for p in paths:
        lines.append(f'[-{p}]')
        lines.append('')
    return '\r\n'.join(lines)


def _write_reg_file(content):
    """Write a .reg file (UTF-16 LE with BOM) and return its path."""
    fd, path = tempfile.mkstemp(suffix='.reg', prefix='titan_tts_sapi_')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(b'\xff\xfe')  # UTF-16 LE BOM
            f.write(content.encode('utf-16-le'))
    except Exception:
        try:
            os.unlink(path)
        except Exception:
            pass
        raise
    return path


def _run_reg_import(reg_file):
    """Run reg.exe import directly (we already have admin). Returns True on success."""
    import subprocess
    try:
        result = subprocess.run(
            ['reg.exe', 'import', reg_file],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"[SAPIRegister] reg.exe import failed ({result.returncode}): "
                  f"{result.stderr.decode(errors='replace')}")
            return False
        return True
    except Exception as e:
        print(f"[SAPIRegister] reg.exe import error: {e}")
        return False


def _run_reg_import_elevated(reg_file):
    """
    Launch reg.exe import elevated via ShellExecuteExW runas verb.
    Shows a single UAC prompt; returns True if user accepted and reg succeeded.
    """
    import ctypes
    from ctypes import wintypes

    SW_HIDE = 0
    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NO_CONSOLE = 0x00008000

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD),
            ('fMask', wintypes.ULONG),
            ('hwnd', wintypes.HWND),
            ('lpVerb', wintypes.LPCWSTR),
            ('lpFile', wintypes.LPCWSTR),
            ('lpParameters', wintypes.LPCWSTR),
            ('lpDirectory', wintypes.LPCWSTR),
            ('nShow', ctypes.c_int),
            ('hInstApp', wintypes.HINSTANCE),
            ('lpIDList', ctypes.c_void_p),
            ('lpClass', wintypes.LPCWSTR),
            ('hkeyClass', wintypes.HKEY),
            ('dwHotKey', wintypes.DWORD),
            ('hIconOrMonitor', wintypes.HANDLE),
            ('hProcess', wintypes.HANDLE),
        ]

    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL

    sei = SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
    sei.lpVerb = 'runas'
    sei.lpFile = 'reg.exe'
    sei.lpParameters = f'import "{reg_file}"'
    sei.nShow = SW_HIDE

    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        err = ctypes.get_last_error() or kernel32.GetLastError()
        # 1223 = ERROR_CANCELLED (user clicked No on UAC prompt)
        if err == 1223:
            print("[SAPIRegister] User declined UAC elevation")
        else:
            print(f"[SAPIRegister] ShellExecuteExW failed: Win32 error {err}")
        return False

    if not sei.hProcess:
        return True

    try:
        kernel32.WaitForSingleObject(sei.hProcess, 30000)
        exit_code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(exit_code))
        ok = exit_code.value == 0
        if not ok:
            print(f"[SAPIRegister] reg.exe exited with code {exit_code.value}")
        return ok
    finally:
        kernel32.CloseHandle(sei.hProcess)


def _apply_reg_file(content, action_label):
    """Write content to a temp .reg file and import it, elevating via UAC if needed."""
    reg_file = _write_reg_file(content)
    try:
        if _is_admin():
            ok = _run_reg_import(reg_file)
        else:
            ok = _run_reg_import_elevated(reg_file)
        if ok:
            print(f"[SAPIRegister] {action_label} OK")
        else:
            print(f"[SAPIRegister] {action_label} FAILED")
        return ok
    finally:
        try:
            os.unlink(reg_file)
        except Exception:
            pass


def register(interactive=True):
    """
    Register Titan TTS as a SAPI5 voice in HKLM for both 32- and 64-bit clients.
    When interactive=False and we lack admin rights, skip silently (used by the
    startup sync path to avoid popping UAC on every launch).
    """
    if not _is_windows():
        return False
    if not interactive and not _is_admin():
        print("[SAPIRegister] Skipping register: not admin and non-interactive")
        return False
    return _apply_reg_file(_build_install_reg(),
                           f"Titan TTS registered as SAPI5 voice '{TITAN_TTS_VOICE_DISPLAY_NAME}'")


def unregister(interactive=True):
    """Remove all Titan TTS SAPI5 registry entries (HKLM 32/64 + legacy HKCU)."""
    if not _is_windows():
        return False
    if not interactive and not _is_admin():
        print("[SAPIRegister] Skipping unregister: not admin and non-interactive")
        return False
    return _apply_reg_file(_build_uninstall_reg(), "Titan TTS SAPI5 voice unregistered")


def is_registered():
    """Return True if the Titan TTS voice token exists in HKLM (either view)."""
    if not _is_windows():
        return False
    import winreg
    token_path = r'SOFTWARE\Microsoft\Speech\Voices\Tokens\TitanTTS'
    for access in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, token_path, 0,
                                winreg.KEY_READ | access):
                return True
        except OSError:
            continue
    return False


def apply_sapi_registration(enabled, interactive=False):
    """
    Sync registry state with the desired setting.

    interactive=True  -> called from the Settings dialog when the user toggled
                         the checkbox. Will prompt for UAC elevation if needed.
    interactive=False -> called at startup. Silent; won't prompt UAC. If the
                         stored setting says "enabled" but we're not admin, it
                         just leaves the registry untouched (user must re-toggle
                         the checkbox if the entries are missing).
    """
    if not _is_windows():
        return False
    try:
        currently_registered = is_registered()
        if enabled and not currently_registered:
            return register(interactive=interactive)
        if (not enabled) and currently_registered:
            return unregister(interactive=interactive)
        return True
    except Exception as e:
        print(f"[SAPIRegister] apply_sapi_registration error: {e}")
        return False

# -*- coding: utf-8 -*-
"""
File association for .TCA / .TCD packages
===========================================
Registers double-click handling for Titan package files under
HKEY_CURRENT_USER\\Software\\Classes -- unlike the SAPI5 voice registration
(src/tts/sapi_registration.py), this does NOT need HKLM/admin rights, since
per-user file associations live entirely in HKCU. Double-clicking a .tca/.tcd
in Explorer then launches Titan with --install-package "<path>".

Registration is best-effort and silent: called once from normal startup
(no UAC prompt possible or needed), failures are logged and ignored.
"""

import os
import sys
import winreg


_EXTENSIONS = ('.tca', '.tcd', '.tcs')
_PROGID = {
    '.tca': 'TitanTCE.Package.TCA',
    '.tcd': 'TitanTCE.Package.TCD',
    '.tcs': 'TitanTCE.Script.TCS',
}
_DESCRIPTION = {
    '.tca': 'Titan Application/Game Package',
    '.tcd': 'Titan Add-on Package',
    '.tcs': 'Titan Script',
}
# What Titan is being asked to do with the file that was double-clicked.
_SWITCH = {
    '.tca': '--install-package',
    '.tcd': '--install-package',
    '.tcs': '--run-script',
}


def _is_windows():
    return sys.platform == 'win32'


def _get_launch_command(switch):
    """The command line (%1 is the clicked file) that invokes Titan with
    ``switch``. Compiled Titan is its own executable; from source it is the
    interpreter plus main.py, which is the same program either way."""
    if getattr(sys, 'frozen', False):
        exe = sys.executable
        return f'"{exe}" {switch} "%1"'
    # Development mode: run through the current interpreter + main.py.
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
    main_py = os.path.join(root, 'main.py')
    return f'"{sys.executable}" "{main_py}" {switch} "%1"'


def register():
    """Register the .tca/.tcd/.tcs file associations in HKCU. Returns True on
    full success. Safe to call on every startup -- cheap, idempotent, no
    prompt."""
    if not _is_windows():
        return False
    try:
        ok = True
        for ext in _EXTENSIONS:
            progid = _PROGID[ext]
            command = _get_launch_command(_SWITCH[ext])
            try:
                # <ProgID> default value + description
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                         f'Software\\Classes\\{progid}') as key:
                    winreg.SetValueEx(key, '', 0, winreg.REG_SZ, _DESCRIPTION[ext])

                with winreg.CreateKeyEx(
                    winreg.HKEY_CURRENT_USER,
                    f'Software\\Classes\\{progid}\\shell\\open\\command'
                ) as key:
                    winreg.SetValueEx(key, '', 0, winreg.REG_SZ, command)

                # .tca / .tcd -> ProgID
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                         f'Software\\Classes\\{ext}') as key:
                    winreg.SetValueEx(key, '', 0, winreg.REG_SZ, progid)
            except OSError as e:
                print(f"[FileAssociation] Failed to register {ext}: {e}")
                ok = False
        if ok:
            print("[FileAssociation] .tca/.tcd/.tcs file associations registered")
        return ok
    except Exception as e:
        print(f"[FileAssociation] register() error: {e}")
        return False


def unregister():
    """Remove the .tca/.tcd/.tcs file associations from HKCU."""
    if not _is_windows():
        return False
    ok = True
    for ext in _EXTENSIONS:
        progid = _PROGID[ext]
        for subpath in (f'Software\\Classes\\{progid}\\shell\\open\\command',
                        f'Software\\Classes\\{progid}\\shell\\open',
                        f'Software\\Classes\\{progid}\\shell',
                        f'Software\\Classes\\{progid}',
                        f'Software\\Classes\\{ext}'):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subpath)
            except FileNotFoundError:
                pass
            except OSError as e:
                print(f"[FileAssociation] Failed to remove {subpath}: {e}")
                ok = False
    return ok


def is_registered():
    """True if .tca is currently associated with a Titan ProgID."""
    if not _is_windows():
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Software\\Classes\\.tca') as key:
            value, _type = winreg.QueryValueEx(key, '')
            return value == _PROGID['.tca']
    except OSError:
        return False
